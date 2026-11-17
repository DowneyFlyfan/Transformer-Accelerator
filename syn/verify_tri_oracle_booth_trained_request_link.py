"""Measure the placed eight-bit request serializer on the trained weight replay."""

import argparse
import json
import mmap
from pathlib import Path
import re

from link_tri_oracle_indexed_whole_chip import module_at, pins, signature, spans
from measure_tri_oracle_credited_request_link import FIFO, LINK, PEER
from prepare_tri_oracle_booth_packet_replay import replace_once
from verify_tri_oracle_booth_response_packing import ROOT, TERMINAL, digest
from verify_tri_oracle_booth_trained_credit_window import DELAY, FIXTURES, TOP
from verify_tri_oracle_serialized_placement_transfer import INSTANCE


BASELINE = Path("records/tri_oracle_corrected_booth_trained_credit_window.json")
REFERENCE = Path("records/tri_oracle_credited_request_link.json")
TX = "tri_oracle_memory_tx_credit"
WRAPPER = "tri_oracle_chip_credited_request"
MATRIX = re.compile(
    r"(?m)^(?:INDEXED_DOWN_TILE|STAGED_INDEXED_DOWN_MATRIX_PASS|"
    r"COMPACT_INDEX_MATRIX_PASS|EARLY_PAIR_SPARSE_ROWS_PASS|"
    r"MEMORY_REQUEST_HARDWARE_FIXTURE) .+$"
)


def placed_transmitter(cold):
    with cold.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        index = spans(source)
        wrapper = module_at(source, index, WRAPPER)
        wiring = pins(wrapper, TX, "request_link")
        assert wiring == {
            "clk": b"clk", "rst_n": b"rst_n", "in_word": b"wide_memory_tx_data",
            "in_valid": b"wide_memory_tx_valid", "in_ready": b"wide_memory_tx_ready",
            "pad_data": b"memory_tx_data", "pad_valid": b"memory_tx_valid",
            "pad_clock": b"memory_tx_clock", "pad_credit": b"memory_tx_credit",
            "protocol_error": b"request_protocol_error",
        }
        ports = signature(module_at(source, index, TX))
        assert ports["in_word"] == (b"input", b"[21:0]")
        assert ports["pad_data"] == (b"output", b"[7:0]")
        definitions = {}
        pending = [TX]
        while pending:
            name = pending.pop()
            if name in definitions:
                continue
            contents = module_at(source, index, name)
            definitions[name] = contents
            for match in INSTANCE.finditer(contents):
                child = match[1].decode()
                if child in index:
                    pending.append(child)
    return b"\n".join(definitions[name] for name in sorted(definitions)) + b"\n"


def setup():
    proof = json.loads(BASELINE.read_text())
    evidence = {BASELINE, REFERENCE, Path(__file__).relative_to(ROOT)}

    def pin(relative):
        path = ROOT / relative
        assert digest(path) == proof["evidence_sha256"][str(relative)], relative
        evidence.add(path)
        return path

    cold, = [pin(name) for name in proof["evidence_sha256"] if name.endswith("/cold/cold.v")]
    assert digest(cold) == proof["cold_netlist_sha256"]
    baseline = cold.parents[1] / "response_credit_trained"
    folder = baseline.with_name("request_link_trained")
    bench = pin((baseline / "trained_tb.sv").relative_to(ROOT))
    bundle = pin((baseline / "bundle.sv").relative_to(ROOT))
    log = pin((baseline / "credit8/xrun.log").relative_to(ROOT))
    previous = json.loads(REFERENCE.read_text())["evidence_sha256"]
    for relative in (PEER, FIFO):
        assert digest(relative) == previous[str(relative)]
        evidence.add(relative)
    for name in re.findall(r'(?m)^`include "([^"]+)"$', bundle.read_text()):
        pin(Path(name).relative_to(ROOT))
    fixtures = {}
    for name in FIXTURES:
        linked = baseline / "credit8" / name
        fixtures[name] = pin(linked.resolve(strict=True).relative_to(ROOT))

    revised = replace_once(bench.read_text(), "  tri_oracle_memory_forward_rx request_rx (",
                           LINK + "  tri_oracle_memory_forward_rx request_rx (")
    revised = replace_once(revised, ".rx_valid(wire_valid), .rx_ready(wire_ready), .rx_data(wire_data)",
                           ".rx_valid(flit_valid), .rx_ready(flit_ready), .rx_data(flit_data)")
    inventory = """      if (expected_flits.size() || physical_flits != 3*serialized_words)
        $fatal(1, "FORWARD_CREDIT_UNDRAINED_FLITS");
      $display("TRAINED_REQUEST_LINK flits=%0d pad_beats=%0d inactive_source_cycles=%0d",
               serialized_words,physical_flits,pad_stalls);
"""
    revised = replace_once(revised, '      $display("DUAL_GROUP_MATRIX_WRITES',
                           inventory + '      $display("DUAL_GROUP_MATRIX_WRITES')
    amended_bundle = replace_once(bundle.read_text(), str(bench), str(folder / bench.name))
    includes = [FIFO.resolve(), PEER.resolve(), folder / "placed_request_tx.v"]
    amended_bundle = "".join(f'`include "{path}"\n' for path in includes) + amended_bundle
    generated = {
        folder / bench.name: revised.encode(),
        folder / bundle.name: amended_bundle.encode(),
        folder / "placed_request_tx.v": placed_transmitter(cold),
    }
    return folder, proof, generated, fixtures, log, evidence


def prepare():
    folder, _, generated, fixtures, _, _ = setup()
    folder.mkdir()
    for path, contents in generated.items():
        path.write_bytes(contents)
    for name, source in fixtures.items():
        (folder / name).symlink_to(source)
    print(folder)


def verify():
    folder, proof, generated, fixtures, baseline_log, evidence = setup()
    for path, contents in generated.items():
        assert path.read_bytes() == contents
    for name, source in fixtures.items():
        assert (folder / name).resolve(strict=True) == source
    log_path, exit_status = folder / "xrun.log", folder / "exit_status"
    assert int(exit_status.read_text()) == 0
    log = log_path.read_text()
    assert log.count(TERMINAL) == 1 and not re.search(r"\*(?:E|F|SE),", log)
    for arg in (f"-top {TOP}", str(folder / "bundle.sv"), "+FULL_MATRIX"):
        assert f"\t{arg}\n" in log, arg
    assert "TRI_ORACLE_TRAINED_WINDOW=8" in log and f"TRI_ORACLE_TRAINED_RETURN={DELAY}" in log
    original = MATRIX.findall(baseline_log.read_text())
    assert MATRIX.findall(log) == original
    assert "STAGED_INDEXED_DOWN_MATRIX_PASS cases=78 exact_bytes=11534336 " in log
    assert "NATIVE_MEMORY_IO_PASS acks=16 faults=2 " in log
    assert "INDEXED_WEIGHT_MODE_PASS switched_to_raw=1" in log
    cycles, = re.findall(r"(?m)^DUAL_GROUP_MATRIX_WRITES writes=90112 cycles=(\d+)$", log)
    flits, beats, inactive = map(int, re.search(
        r"(?m)^TRAINED_REQUEST_LINK flits=(\d+) pad_beats=(\d+) inactive_source_cycles=(\d+)$", log
    ).groups())
    overlap, = re.findall(r"(?m)^NATIVE_FORWARD_MIXED_PASS headers=16 words=128 reads_during_writes=(\d+)$", log)
    assert flits > 8704 and beats == 3 * flits and int(overlap) > 0
    baseline_cycles = proof["receivers"]["8"]["matrix_cycles"]
    evidence.update((*generated, log_path, exit_status))
    return {
        "state": "placed_booth_request_serializer_verified_on_trained_matrix",
        "cold_netlist_sha256": proof["cold_netlist_sha256"],
        "trained_tiles": 78, "exact_weight_bytes": 11534336,
        "modeled_request_flight_cycles": 2, "modeled_credit_return_cycles": 6,
        "ideal_flit_interface_matrix_cycles": baseline_cycles, "pad_interface_matrix_cycles": int(cycles),
        "added_matrix_cycles": int(cycles) - baseline_cycles,
        "request_flits": flits, "pad_beats": beats, "inactive_pad_cycles_with_request_offered": inactive,
        "reads_accepted_during_writes": int(overlap),
        "scope": "Zero-delay placed serializer and response receiver with the archived mapped loader "
                 "and write path, an eight-bit digital pad interface, and a modeled off-chip peer. "
                 "Physical pad delay and whole-chip timing are outside this replay.",
        "evidence_sha256": {str(path.relative_to(ROOT) if path.is_absolute() else path): digest(path)
                            for path in evidence},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    if args.phase == "prepare":
        prepare()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
