"""Replay a trained projection through the exact cold chip and both packet links."""

import argparse
import json
from pathlib import Path
import re
import shlex

import link_tri_oracle_chip_packet_io as link
from measure_tri_oracle_serial_memory_requests import digest, read


ROOT = link.ROOT
RECORDS = Path("records")
SOURCE = ROOT / "chip_packet_io"
PEER = ROOT / "memory_forward_link/genus_rx/netlist.v"
TEMPLATE = Path("verilog/tri_oracle_packet_projection_tb.svh")
NATIVE_PREFIX = ROOT / "single/cache_reused.hex"
FIXTURES = ("activation.hex", "weights.hex", "cos.hex", "sin.hex", "biases.hex", "shifts.hex", "expected.hex")


def prepare(output, phase):
    evidence = {}

    def pin(path, expected=None):
        checksum = digest(path)
        assert expected is None or checksum == expected, path
        evidence[str(path)] = checksum
        return path

    whole = read(pin(RECORDS / "tri_oracle_chip_packet_io.json"))
    forward = read(pin(RECORDS / "tri_oracle_memory_forward_link.json"))
    prefix = read(pin(RECORDS / "tri_oracle_full_chip_xcelium_multicore_prefix.json"))
    inputs = read(pin(ROOT / "prepared.json"))
    assert whole["cold_netlist_sha256"] == forward["cold_netlist_sha256"] == prefix["cold_netlist_sha256"]
    assert prefix["cold_netlist_sha256"] == inputs["cold_netlist_sha256"]
    directory = Path(inputs["fixture"]).relative_to(Path.cwd())
    for name in FIXTURES:
        path = directory / name
        pin(path, inputs["evidence_sha256"][str(path)])
    pin(NATIVE_PREFIX, prefix["evidence_sha256"][str(NATIVE_PREFIX)])
    assert len(NATIVE_PREFIX.read_text().splitlines()) == prefix["independent_cache_vectors"] == 16
    pin(PEER, forward["evidence_sha256"][str(PEER)])
    pin(link.MEMORY_NETLIST, whole["evidence_sha256"][str(link.MEMORY_NETLIST)])
    pin(link.HOST_NETLIST, whole["evidence_sha256"][str(link.HOST_NETLIST)])

    cold, models, core, adapters, outer, internal, _, _, _ = link.load()
    pin(cold, whole["cold_netlist_sha256"])
    for model in models:
        pin(model, whole["evidence_sha256"][str(model)])
    wrapper = pin(SOURCE / "wrapper.v", whole["evidence_sha256"][str(SOURCE / "wrapper.v")])
    assert wrapper.read_text() == link.wrapper_text(core, adapters, outer, internal)
    stimulus = pin(TEMPLATE).read_text()
    exposed = {"clk", "rst_n", *(name for name in outer if name.startswith("host_")),
               "angle_valid", "angle_last", "angle_ready", "angle_cos", "angle_sin",
               "memory_tx_valid", "memory_tx_ready", "memory_tx_data",
               "memory_mem_rsp_valid", "memory_mem_rsp_ready", "memory_mem_rsp_last", "memory_mem_rsp_data"}
    assert exposed <= outer.keys()
    connections = {name: name if name in exposed else ("'0" if direction == "INPUT" else "")
                   for name, (direction, _) in outer.items()}
    assert stimulus.count("  // CHIP_INSTANCE") == 1
    bench_text = stimulus.replace("  // CHIP_INSTANCE", link.instance(link.WRAPPER, "dut", connections).rstrip())
    bench = output / "projection_tb.sv"
    bundle = output / "wrapper_bundle.sv"
    sources = (*models, cold, link.HOST_NETLIST, link.MEMORY_NETLIST, PEER, wrapper, bench)
    bundle_text = "`define UNIT_DELAY\n" + "".join(f'`include "{path.resolve()}"\n' for path in sources)
    for path, expected in ((bench, bench_text), (bundle, bundle_text)):
        if phase == "prepare":
            with path.open("x") as stream:
                stream.write(expected)
        else:
            assert path.read_text() == expected
            pin(path)
    return directory, whole["cold_netlist_sha256"], evidence


def verify(output, directory, cold_sha256, evidence):
    native = output / "native"
    status_path = output / "native_status.json"
    status = read(status_path)
    log_path = native / "xrun.log"
    history_path = native / "xrun.history"
    dump = output / "cache.hex"
    assert status["native_exit_status"] == 0 and status["stop_reason"] is None
    assert status["log_sha256"] == digest(log_path)
    assert dump.read_bytes() == NATIVE_PREFIX.read_bytes()
    history = history_path.read_text()
    command = re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1]
    argv = shlex.split(command)
    assert argv[argv.index("-top") + 1] == link.BENCH
    assert str((output / "wrapper_bundle.sv").resolve()) in argv
    assert f"+FIXTURE={directory.resolve()}" in argv and f"+DUMP={dump.resolve()}" in argv
    log = log_path.read_text()
    assert not re.search(r"\*[EF],", log)
    assert log.count("Simulation complete via $finish(1)") == 1
    fields, = re.findall(r"(?m)^COLD_PACKET_PROJECTION_PASS (.+)$", log)
    totals = {name: int(value) for name, value in (word.split("=") for word in fields.split())}
    assert (totals["vectors"], totals["acks"], totals["writes"]) == (16, 16, 128)
    assert totals["activation_words"] > 0 and totals["weight_words"] > 0 and totals["stalls"] > 0
    for path in (log_path, history_path, dump, status_path, Path(__file__).resolve(), Path(link.__file__).resolve()):
        evidence[str(path)] = digest(path)
    return {
        "state": "trained_projection_replayed_through_linked_whole_chip_packet_io",
        "cold_netlist_sha256": cold_sha256,
        "trained_projection": totals,
        "matched_cache_output_bytes": 1024,
        "native_resources": status,
        "scope": "One trained query projection for 16 tokens on the exact cold whole chip. The real host, "
                 "read, write and acknowledgment links execute the transaction. Rotary input remains parallel. "
                 "The memory peer is a testbench and physical interface timing, other operators and full-model "
                 "execution remain open.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    fixture, cold, evidence = prepare(args.directory, args.phase)
    if args.phase == "verify":
        print(json.dumps(verify(args.directory, fixture, cold, evidence), indent=2, sort_keys=True))
    else:
        print(fixture.resolve())
