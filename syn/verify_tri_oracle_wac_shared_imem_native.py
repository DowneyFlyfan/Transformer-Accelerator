"""Audit the Genus core-local softmax and the two reused memory banks."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_wac_shared_imem import TOP
from run_tri_oracle_aggregator_softmax import sha
from run_tri_oracle_wac_shared_imem import MACROS


def audit_wiring(memory_pins, vector_pins):
    master = MACROS[0][0]
    memory = {}
    for line in memory_pins.splitlines():
        owner, pin, net = line.split("\t")
        bank = int(re.fullmatch(r"inputs\[([01])\]", owner)[1])
        assert pin.startswith(master + "/") and net
        key = bank, pin.removeprefix(master + "/")
        assert key not in memory
        memory[key] = net
    vector = {}
    for line in vector_pins.splitlines():
        pin, net = line.split("\t")
        port = re.fullmatch(r"simd/mem_q\[([01])\]\[(\d+)\]", pin)
        if port:
            key = tuple(map(int, port.groups()))
            assert key not in vector and net
            vector[key] = net
    assert len(memory) == 280
    reads = {}
    writes = set()
    for bank in range(2):
        for port, expected in (("CLK", "clk"), ("CEB", f"imem_ce_n[{bank}]"), ("WEB", f"imem_we_n[{bank}]")):
            assert memory[bank, port] == expected
        for bit in range(9):
            assert memory[bank, f"A[{bit}]"] == f"imem_address[{bit}]"
        for bit in range(64):
            reads[bank, bit] = memory[bank, f"Q[{bit}]"]
            writes.add(memory[bank, f"D[{bit}]"])
    assert len(set(reads.values())) == len(writes) == 128
    assert reads == vector, "A vendor memory data bit does not connect to its corresponding core softmax input"
    return len(memory), len(reads)


def qualify(folder):
    manifest = folder / "inputs.json"
    inputs = json.loads(manifest.read_text())
    assert all(sha(Path(path)) == expected for path, expected in inputs.items())
    log = (folder / "console.log").read_text()
    assert log.splitlines().count("WAC_SHARED_IMEM_GENUS_ELABORATED") == 1
    assert log.splitlines()[-1] == "Normal exit."
    unresolved = (folder / "unresolved.rpt").read_text()
    assert all(f"No {kind} in design '{TOP}'" in unresolved for kind in ("unresolved references", "empty modules"))
    memory = [tuple(line.split("\t")) for line in (folder / "memories.tsv").read_text().splitlines()]
    expected = {(f"{bank}[{index}]", master) for master, bank, count in MACROS for index in range(count)}
    assert len(memory) == len(expected) and set(memory) == expected
    inputs_checked, softmax_data_bits = audit_wiring((folder / "input_pins.tsv").read_text(),
                                                     (folder / "simd_pins.tsv").read_text())
    constraints = (folder / "clock.sdc").read_text()
    assert "set_units -time 1000ps" in constraints
    clock = re.search(r'^create_clock -name "core_clock" -period (\S+)', constraints, re.M)
    assert clock and abs(float(clock[1]) - 1000 / 580) < 0.00001
    evidence = (manifest, *(folder / name for name in (
        "console.log", "unresolved.rpt", "memories.tsv", "input_pins.tsv", "simd_pins.tsv", "clock.sdc", "elaborated.db",
    )))
    return dict(state="genus_core_local_softmax_memory_connections_verified",
                compiled_memories=len(memory), input_memory_bytes=8192, input_memory_pins=inputs_checked,
                softmax_input_data_bits=softmax_data_bits, constraint_mhz=580,
                native_evidence_sha256={str(path): sha(path) for path in evidence})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("elaboration", type=Path)
    args = parser.parse_args()
    print(json.dumps(qualify(args.elaboration.resolve()), indent=2))
