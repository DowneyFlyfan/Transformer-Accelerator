"""Replay the native mapped softmax bank with the vendor result memories."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from run_tri_oracle_softmax_iomem import (
    ACCESS_MONITOR, ARCHIVE, BANK_MONITOR, LATENCY_MONITOR, MEMORY, REFERENCE, ROOT, RTL, TOP,
    replace, sha, standalone_top,
)

BANK = "tri_oracle_softmax_iomem_bank"
MEMORY_MASTER = "TS6N28HPCPSVTA16X128M2F"
STANDARD_MODELS = ROOT / ".cache/physical/library/tcbn28hpcplusbwp12t40p140.v"
XRUN = Path("/opt/cadence/bin/xrun")
PROBES = f"""
module tri_oracle_packed_softmax_mapping_probe #(parameter string KIND="") ();
    initial $display("PACKED_SOFTMAX_MAPPING %s %m", KIND);
endmodule
bind {BANK} tri_oracle_packed_softmax_mapping_probe #(.KIND("bank")) mapped_bank_probe ();
bind {MEMORY_MASTER} tri_oracle_packed_softmax_mapping_probe #(.KIND("memory")) mapped_memory_probe ();
"""
INPUT_WIDTHS = {
    "clk": 1, "rst_n": 1, "begin_row": 1, "load": 1, "slot": 8, "in_score": 16, "in_size": 10,
    "read_slot": 1, "write_weight": 1, "maximum": 16, "reciprocal": 29, "flush": 1,
}
OUTPUT_WIDTHS = {
    "local_maximum": 16, "local_sum": 38, "probability": 16, "write_valid": 1, "read_valid": 1,
    "write_line": 6, "read_line": 6, "write_data": 128,
}


def port_signature(text):
    modules = re.findall(rf"^module\s+{BANK}\s*\(([^;]+)\);\s*(.*?)^endmodule\b", text, re.M | re.S)
    assert len(modules) == 1, f"Expected one mapped definition of {BANK}"
    header, body = modules[0]
    ports = [port.strip() for port in header.split(",")]
    # Genus exports each packed memory word as its own escaped port.
    inputs = {**INPUT_WIDTHS, **{rf"\memory_q[{index}]": 128 for index in range(4)}}
    expected = {
        name: (direction, (width - 1, 0) if width > 1 else None)
        for direction, widths in (("input", inputs), ("output", OUTPUT_WIDTHS))
        for name, width in widths.items()
    }
    assert len(ports) == len(expected) and set(ports) == expected.keys(), ports
    observed = {}
    for direction, msb, lsb, group in re.findall(
        r"^\s*(input|output)\s+(?:\[(\d+):(\d+)\]\s+)?([^;]+);", body, re.M
    ):
        for name in map(str.strip, group.split(",")):
            assert name not in observed, name
            observed[name] = (direction, (int(msb), int(lsb)) if msb else None)
    assert observed == expected, [(name, observed.get(name), shape) for name, shape in expected.items()
                                   if observed.get(name) != shape]
    return sum(inputs.values()) + sum(OUTPUT_WIDTHS.values())


def native_census(lines):
    prefix = f"{TOP}.dut.aggregator"
    expected = {("bank", f"{prefix}[{bank}].datapath.mapped_bank_probe") for bank in range(5)}
    expected |= {
        ("memory", f"{prefix}[{bank}].local_result_memory[{macro}].memory.mapped_memory_probe")
        for bank in range(5) for macro in range(4)
    }
    actual = [tuple(line.split()[1:]) for line in lines if line.startswith("PACKED_SOFTMAX_MAPPING ")]
    assert len(actual) == len(set(actual)) == len(expected) and set(actual) == expected, set(actual) ^ expected


def verify(folder, output):
    receipt = folder / "receipt.json"
    mapped = json.loads(receipt.read_text())
    assert mapped["state"] == "packed_softmax_bank_external_memory_logic_mapped"
    assert mapped["native"]["native_exit_status"] == 0
    inputs = {Path(name): digest for name, digest in mapped["input_sha256"].items()}
    inputs.update({folder / name: digest for name, digest in mapped["output_sha256"].items()})
    assert all(sha(path) == digest for path, digest in inputs.items())
    netlist = folder / "netlist.v"
    verified_ports = port_signature(netlist.read_text())
    prior = json.loads(REFERENCE.read_text())
    assert sha(ARCHIVE) == prior["native_evidence_sha256"]
    assert sha(MEMORY) == "80450a3b83a12bf99c98cb6b47d56dcd41ac4895cb1f14257081a3cf31b5b450"
    with gzip.open(ARCHIVE, "rt") as stream:
        vectors = json.load(stream)["vectors"]
    assert hashlib.sha256(vectors.encode()).hexdigest() == prior["fixture_sha256"]
    bench_path = RTL / f"{TOP}.sv"
    bench = replace(bench_path.read_text(), "tri_oracle_proportional_softmax dut",
                    "tri_oracle_aggregator_softmax_iomem dut")
    bench = replace(bench, "endmodule", LATENCY_MONITOR + BANK_MONITOR + ACCESS_MONITOR + "endmodule")
    inputs.update({path: sha(path) for path in (
        receipt, ARCHIVE, REFERENCE, MEMORY, STANDARD_MODELS, bench_path, Path(__file__), XRUN,
        Path(__file__).with_name("run_tri_oracle_softmax_iomem.py"),
        RTL / "tri_oracle_aggregator_softmax.sv",
    )})
    memory_connections = ",\n            ".join(
        rf".\memory_q[{index}] (memory_q[{index}])" for index in range(4)
    )
    top = replace(standalone_top(False), ".write_data, .memory_q", ".write_data,\n            " + memory_connections)
    with tempfile.TemporaryDirectory(dir=ROOT / ".cache", prefix="mapped_packed_softmax_") as directory:
        work = Path(directory)
        generated = {}
        for name, content in (
            ("vectors.txt", vectors), (bench_path.name, bench),
            ("standalone.sv", top), ("probes.sv", PROBES),
        ):
            path = work / name
            path.write_text(content)
            generated[name] = path
        args = [str(XRUN), "-64bit", "-sv", "-define", "UNIT_DELAY",
                "-nospecify", "-notimingchecks", "-sequdp_nba_delay", "-xmerror", "RECOME", "-top", TOP,
                str(MEMORY), str(STANDARD_MODELS), str(netlist), str(generated["standalone.sv"]),
                str(generated[bench_path.name]), str(generated["probes.sv"]),
                f'+FIXTURE={generated["vectors.txt"]}']
        run = subprocess.run(args, cwd=work, capture_output=True, text=True, timeout=180)
        console = work / "xrun.log"
        log = console.read_text() if console.is_file() else run.stdout
    assert run.returncode == 0 and not re.search(r"\*[EF],", log), (log + run.stderr)[-6000:]
    assert not re.search(r"\*W,CUVW", log), log[-6000:]
    lines = log.splitlines()
    version = re.search(r"^TOOL:\s+xrun\(64\)\s+(25\.03-\w+): Started", log, re.M)
    assert version, log[:1500]
    assert lines.count(prior["simulation_marker"]) == 1
    assert [int(line.split()[1]) for line in lines if line.startswith("SOFTMAX_LONG_ROW_CYCLES ")] == [463] * 3
    native_census(lines)
    assert all(sha(path) == digest for path, digest in inputs.items())
    output.mkdir()
    console = output / "xrun.log"
    console.write_text(log)
    evidence = dict(state="packed_softmax_mapped_bank_and_vendor_memories_verified",
                    simulator="Cadence Xcelium", simulator_version=version[1], mapped_banks=5,
                    compiled_memories=20, checked_bank_signal_bits=verified_ports,
                    compared_probability_codes=12915, rows=39, first_output_cycles=463,
                    native_log_sha256=sha(console), input_sha256={str(path): digest for path, digest in inputs.items()},
                    scope="Functional mapped-bank logic with unit-delay vendor memories. The coordinator is source-level.")
    (output / "receipt.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(evidence["state"], verified_ports, prior["simulation_marker"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    verify(args.mapping.resolve(), args.output.resolve())
