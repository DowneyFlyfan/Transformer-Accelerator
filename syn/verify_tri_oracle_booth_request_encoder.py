"""Replay both request formats on the repaired chip's actual mapped encoder."""

import argparse
import json
import mmap
from pathlib import Path
import re

from link_tri_oracle_indexed_whole_chip import module_at, pins, signature, spans
from verify_tri_oracle_booth_clock_boundary import PLACEMENT
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, digest


ENCODER = "tri_oracle_memory_request_tx"
RECEIVER = "tri_oracle_memory_request_rx"
TOP = "tri_oracle_memory_request_link_tb"
BENCH = Path(f"verilog/{TOP}.sv")
RTL = Path("verilog/tri_oracle_memory_request_link.sv")
CELLS = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140.v")
REFERENCE = Path("records/tri_oracle_mapped_memory_request_link.json")
REFERENCE_RX = Path("records/tri_oracle_memory_forward_link.json")
INTERCONNECT = Path("records/tri_oracle_corrected_booth_memory_interconnect.json")


def sources():
    placed = json.loads(PLACEMENT.read_text())
    reference = json.loads(REFERENCE.read_text())
    interconnect = json.loads(INTERCONNECT.read_text())
    assert interconnect["database_fingerprint_sha256"] == placed["database_fingerprint_sha256"]
    assert interconnect["packed_memory_boundary_bits"]["transmit_data"] == 8
    for path in (BENCH, CELLS):
        assert digest(path) == reference["evidence_sha256"][str(path)], path
    rx_proof = json.loads(REFERENCE_RX.read_text())
    assert digest(RTL) == rx_proof["evidence_sha256"][str(RTL)]
    stage = Path(placed["database"]).parents[1]
    cold = stage / "cold/cold.v"
    assert digest(cold) == placed["evidence_sha256"][str(cold)] == interconnect["evidence_sha256"][str(cold)]
    with cold.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        index = spans(data)
        link = module_at(data, index, "tri_oracle_memory_io_link")
        assert pins(link, "tri_oracle_shared_read_core", "reads")["req_address"] == b"req_address"
        read_core = module_at(data, index, "tri_oracle_shared_read_core")
        request = pins(read_core, ENCODER, "request_tx")
        assert request["tx_data"] == b"tx_data" and request["req_address"] == b"req_address"
        assert request["req_valid"] == b"permitted_valid" and request["primary_wide"] == b"primary_wide"
        mapped = module_at(data, index, ENCODER)
        assert signature(mapped)["tx_data"] == (b"output", b"[21:0]")
    rtl = RTL.read_bytes()
    receiver_start = f"module {RECEIVER} (".encode()
    assert rtl.count(receiver_start) == 1
    receiver = b"`timescale 1ns/1ps\n" + rtl[rtl.index(receiver_start):]
    return stage / "request_encoder", cold, mapped + b"\n", receiver, reference


def prepare():
    work, _, mapped, receiver, _ = sources()
    work.mkdir()
    for name, content in (("mapped_tx.v", mapped), ("reference_receiver.sv", receiver)):
        (work / name).write_bytes(content)
    print(work)


def verify():
    work, cold, mapped, receiver, reference = sources()
    transmitter, peer = work / "mapped_tx.v", work / "reference_receiver.sv"
    assert transmitter.read_bytes() == mapped and peer.read_bytes() == receiver
    invocation = work / "xrun.log"
    text = invocation.read_text()
    for argument in (f"-top {TOP}", str(transmitter.resolve()), str(peer.resolve()),
                     str(BENCH.resolve()), str(CELLS.resolve())):
        assert f"\t{argument}\n" in text, argument
    assert text.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*(?:E|F|SE),", text)
    summary, = re.findall(r"(?m)^MEMORY_REQUEST_LINK_PASS (.+)$", text)
    counts = dict((name, int(value)) for name, value in (item.split("=") for item in summary.split()))
    assert counts == reference["unit_replay"]
    return {
        "state": "placed_booth_memory_request_encoder_replayed_with_reference_receiver",
        "cold_netlist_sha256": digest(cold),
        "native_replay": counts,
        "encoded_flits_per_read": {"compact": 2, "full": 4},
        "flit_data_bits": 22,
        "pad_data_bits": 8,
        "ideal_pad_data_cycles_per_read": {"compact": 6, "full": 12},
        "scope": "Xcelium replay of the mapped encoder extracted from the current placed export with the "
                 "reference receive model under stalls. The pad cycle counts are serialization minima.",
        "evidence_sha256": {str(path): digest(path) for path in (
            PLACEMENT, REFERENCE, REFERENCE_RX, INTERCONNECT, cold, transmitter, peer, RTL, BENCH, CELLS, invocation,
            Path(__file__).resolve().relative_to(ROOT))},
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
