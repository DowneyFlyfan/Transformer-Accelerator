"""Check the trained ranked sign predictor at the mapped gate boundary."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

from prepare_tri_oracle_packed_sign_predictor import ROOT, sha


TOP = "tri_oracle_packed_outlier_replay"
BENCH = "tri_oracle_packed_sign_predictor_tb"
CELLS = ROOT / ".cache/physical/library/tcbn28hpcplusbwp12t40p140.v"
MEMORIES = {"TS5N28HPCPSVTA32X128M2FW": 4, "TS5N28HPCPSVTA512X64M4F": 2}
RTL_ONLY = {"tri_oracle_ranked_sign_slots.sv", "tri_oracle_ranked_sign_line_cache.sv", "tri_oracle_packed_sign_fetch.sv"}


def require(value, message):
    if not value:
        raise ValueError(message)


def bindings(source, mapped):
    expected, fields = {}, []
    for name, (direction, shape) in source.items():
        if len(shape) <= 1:
            expected[name] = direction, shape[0] if shape else None
            fields.append(f".{name}({name})")
        elif name in mapped:
            require(all(last == 0 for _, last in shape), f"Unsupported packed source layout: {name}")
            expected[name] = direction, (math.prod(first + 1 for first, _ in shape) - 1, 0)
            fields.append(f".{name}({name})")
        else:
            require(len(shape) == 2, f"Unsupported split source layout: {name}")
            high, low = shape[0]
            for index in range(low, high + 1):
                lane = f"{name}[{index}]"
                expected[lane] = direction, shape[1]
                fields.append(f".\\{lane} ({lane})")
    require(expected == mapped, "Port shape or direction differs from the trained predictor")
    return fields


def adapter_text(source, mapped):
    from verify_linked_placed_topology import module_index, parse_module

    header = source.split(");", 1)[0] + ");"
    port_lines = header.partition(") (")[2].splitlines()
    directions = {}
    for line in filter(str.strip, port_lines[:-1]):
        match = re.fullmatch(r"\s*(input|output) logic\s+((?:\[\d+:\d+\]\s*)*)([^\n]+)", line)
        require(match is not None, f"Unsupported source port: {line}")
        direction, dimensions, names = match.groups()
        shape = tuple(tuple(map(int, dims)) for dims in re.findall(r"\[(\d+):(\d+)\]", dimensions))
        for name in names.rstrip(",").split(","):
            name = name.strip()
            require(re.fullmatch(r"\w+", name) and name not in directions, f"Invalid source port: {name}")
            directions[name] = direction, shape
    modules = module_index(mapped)
    top, = (name for name in modules if name.startswith(TOP))
    require(top != TOP, "Expected the parameter-specialized Genus top name")
    _, ports, nets, _, _ = parse_module(mapped, modules[top])
    fields = bindings(directions, ports)
    require(nets.get("sign_memory_state") == (2, 0), "Missing mapped packed-fetch state")
    connections = ",\n        ".join(fields)
    # The packed reader advances Request (1) to Response (2) only when the
    # cache accepts its request. Count that actual mapped transition once.
    observation = """    logic [2:0] previous_fetch_state;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) previous_fetch_state <= 3'd0;
        else previous_fetch_state <= mapped.sign_memory_state;
    end
    wire observed_cache_accept = previous_fetch_state == 3'd1 && mapped.sign_memory_state == 3'd2;
"""
    return f"{header}\n    {top} mapped (\n        {connections}\n    );\n{observation}endmodule\n"


def memory_witness():
    return """module ranked_memory_witness #(parameter string MASTER="") ();
    initial $display("RANKED_GATE_MEMORY %s %m", MASTER);
endmodule
""" + "".join(f'bind {master} ranked_memory_witness #(.MASTER("{master}")) ranked_witness ();\n'
             for master in MEMORIES)


def run(mapping, integrated, output):
    native_path = ROOT / "records/wac_ranked_sign_predictor_native_result.json"
    mapping_path = mapping / "native_receipt.json"
    native, mapped = (json.loads(path.read_text()) for path in (native_path, mapping_path))
    require(native["state"] == "ranked_32_sign_predictor_verified_in_xcelium"
            and mapped["native_exit_status"] == 0 and mapped["stop"] is None,
            "A successful source replay and native mapping are required")
    require(mapped["input_sha256"][str(native_path.relative_to(ROOT))] == sha(native_path),
            "Mapping did not bind the verified source replay")
    pins = mapped["input_sha256"].copy()

    def pin(path, expected=None):
        name, digest = str(path.relative_to(ROOT)), sha(path)
        require((expected is None or expected == digest) and pins.setdefault(name, digest) == digest,
                f"Changed input: {path}")

    for name, digest in mapped["outputs"].items():
        pin(mapping / name, digest)
    require(all(sha(ROOT / name) == digest for name, digest in pins.items()), "Mapping evidence changed")
    pin(mapping_path)
    pin(Path(__file__).resolve())
    cell_evidence = ROOT / "records/wac_response_address_mapped_result.json"
    pin(cell_evidence)
    pin(CELLS, json.loads(cell_evidence.read_text())["evidence_sha256"][str(CELLS.relative_to(ROOT))])
    gate = mapping / "netlist.v"
    source = integrated / f"{TOP}.sv"
    pin(source)
    adapter = adapter_text(source.read_text(), gate.read_text())
    invocation = integrated / "green/invocation.json"
    pin(invocation)
    prior = json.loads(invocation.read_text())["argv"]
    require(prior.count(str(source)) == 1, "Source replay did not identify the selected predictor")
    output.mkdir()
    wrapper, probe = output / "mapped_predictor.sv", output / "memory_witness.sv"
    source_bench, mapped_bench = integrated / f"{BENCH}.sv", output / f"{BENCH}.sv"
    pin(source_bench)
    text = source_bench.read_text()
    expected_monitor = "dut.cache_req_valid && dut.cache_req_ready"
    require(text.count(expected_monitor) == 1, "Source bench request monitor changed")
    mapped_bench.write_text(text.replace(expected_monitor, "dut.observed_cache_accept"))
    wrapper.write_text(adapter)
    probe.write_text(memory_witness())
    pin(wrapper)
    pin(probe)
    pin(mapped_bench)
    argv = []
    for word in prior:
        if word == str(source):
            argv.extend(map(str, (CELLS, gate, wrapper, probe)))
        elif word == str(source_bench):
            argv.append(str(mapped_bench))
        elif not (word.startswith("/") and Path(word).name in RTL_ONLY):
            argv.append(word)
    tool = output / "invocation.json"
    tool.write_text(json.dumps({"argv": argv}, indent=2) + "\n")
    pin(tool)
    available = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                     if line.startswith("MemAvailable:"))
    require(available >= 15 * 1024**2, "Insufficient host memory for the gate replay")
    console = output / "console.log"
    try:
        with console.open("x") as stream:
            status = subprocess.run(argv, cwd=output, stdout=stream, stderr=subprocess.STDOUT, timeout=180).returncode
    finally:
        if (output / "xcelium.d").is_dir():
            shutil.rmtree(output / "xcelium.d")
    (output / "exit_status").write_text(f"{status}\n")
    log = console.read_text()
    require(status == 0 and not re.search(r"\*[EF],", log), f"Mapped replay failed: {console}")
    metrics, = re.findall(r"(?m)^PACKED_SIGN_PREDICTOR_PASS (.+)$", log)
    observed = {name: int(value) for name, value in (field.split("=") for field in metrics.split())}
    require(observed == native["trained_replay"], "Mapped mask, read or cycle counters changed")
    memories = re.findall(r"(?m)^RANKED_GATE_MEMORY (\w+) (.+)$", log)
    instances = {re.sub(r"[\\\s]", "", path) for _, path in memories}
    require(len(instances) == len(memories) and Counter(master for master, _ in memories) == MEMORIES
            and all(path.startswith(f"{BENCH}.dut.mapped.") for path in instances),
            "Native SRAM census differs from the mapped predictor")
    for path in (console, output / "xrun.log", output / "exit_status"):
        pin(path)
    require(all(sha(ROOT / name) == digest for name, digest in pins.items()), "Evidence changed during gate replay")
    result = {
        "state": "ranked_sign_predictor_mapped_gates_replayed_trained_fixture",
        "native_exit_status": status, "trained_replay": observed, "memory_instances_by_master": dict(MEMORIES),
        "scope": "Functional native gate-level replay of the mapped predictor. Physical timing is separate.",
        "input_sha256": pins,
    }
    (output / "receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], metrics, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("mapping", "integrated", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    run(args.mapping, args.integrated, args.output)
