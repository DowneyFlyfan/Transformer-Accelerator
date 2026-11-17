"""Check burst packing and credit return on the repaired placed memory receiver."""

import argparse
from fractions import Fraction
import json
import mmap
from pathlib import Path
import re

from link_tri_oracle_indexed_whole_chip import module_at, pins, signature, spans
from verify_tri_oracle_booth_clock_boundary import PLACEMENT
from verify_tri_oracle_booth_request_encoder import CELLS, INTERCONNECT
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, digest
from verify_tri_oracle_serialized_placement_transfer import INSTANCE


RECEIVER = "tri_oracle_credit_metadata_ingress"
TOP = "tri_oracle_credit_memory_ingress_tb"
BASELINE = Path("records/tri_oracle_shared_edge_metadata.json")
BUDGET = Path("records/tri_oracle_bonded_system_budget.json")
BASE_RUN = ROOT / ".cache/physical/whole_chip_xcelium_speed/shared_edge_metadata"
BENCH = BASE_RUN / "credit_tb.sv"
TERMINAL = "Simulation complete via $finish(1)"
CASES = {
    "credit4": ("mapped4", ("CREDIT_FULL_RATE_PASS", "CREDIT_STALL_PASS")),
    "credit8": ("mapped8", ("CREDIT_DELAY_WINDOW_PASS", "CREDIT_STALL_PASS")),
}
LONG_CASES = {f"continuous_credit{delay}": delay for delay in range(4, 9)}
LONG_CHUNKS = 512
LONG_WORDS = LONG_CHUNKS * 7 // 8


def long_burst_bench():
    text = BENCH.read_text()
    edits = {
        "sent[lane]<64": f"sent[lane]<{LONG_CHUNKS}",
        "sent[lane]==63": f"sent[lane]=={LONG_CHUNKS - 1}",
        "received[lane]>=56": f"received[lane]>={LONG_WORDS}",
        "received[lane]==55": f"received[lane]=={LONG_WORDS - 1}",
        "received[0]==56 && received[1]==56": f"received[0]=={LONG_WORDS} && received[1]=={LONG_WORDS}",
        "sent[0]!=64 || sent[1]!=64": f"sent[0]!={LONG_CHUNKS} || sent[1]!={LONG_CHUNKS}",
        "chunks=64,64 responses=56,56": f"chunks={LONG_CHUNKS},{LONG_CHUNKS} responses={LONG_WORDS},{LONG_WORDS}",
        "repeat (500)": "repeat (4000)",
        "if (credit_stalls[0]==0 || credit_stalls[1]==0)":
            "if (ReturnCycles==8 && (credit_stalls[0]==0 || credit_stalls[1]==0))",
    }
    for original, replacement in edits.items():
        assert original in text
        text = text.replace(original, replacement)
    return text


def capture(source):
    index = spans(source)
    wrapper = module_at(source, index, "tri_oracle_chip_credited_metadata")
    link = pins(wrapper, RECEIVER, "credit_receiver")
    assert link["pad_data"] == b"memory_mem_rsp_data" and link["pad_metadata"] == b"memory_mem_rsp_metadata"
    assert link["pad_credit"] == b"memory_mem_rsp_credit"
    receiver = signature(module_at(source, index, RECEIVER))
    assert receiver["pad_data"] == (b"input", b"[447:0]") and receiver["out_data"] == (b"output", b"[1023:0]")
    dependencies = {}
    pending = [RECEIVER]
    while pending:
        master = pending.pop()
        if master in dependencies:
            continue
        body = module_at(source, index, master)
        dependencies[master] = body
        for instance in INSTANCE.finditer(body):
            child = instance[1].decode()
            if child in index:
                pending.append(child)
    return b"\n".join(dependencies[name] for name in sorted(dependencies)) + b"\n"


def inputs():
    placed = json.loads(PLACEMENT.read_text())
    interconnect = json.loads(INTERCONNECT.read_text())
    assert placed["database_fingerprint_sha256"] == interconnect["database_fingerprint_sha256"]
    assert interconnect["packed_memory_boundary_bits"]["response_data"] == 448
    baseline = json.loads(BASELINE.read_text())
    for name in (BENCH, CELLS.resolve()):
        assert digest(name) == baseline["evidence_sha256"][str(name)], name
    stage = Path(placed["database"]).parents[1]
    netlist = stage / "cold/cold.v"
    assert digest(netlist) == placed["evidence_sha256"][str(netlist)] == interconnect["evidence_sha256"][str(netlist)]
    with netlist.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        mapped = capture(source)
    return stage / "response_packing", netlist, mapped, baseline


def prepare():
    work, _, mapped, _ = inputs()
    work.mkdir()
    (work / "placed_receiver.v").write_bytes(mapped)
    (work / "continuous_credit_tb.sv").write_text(long_burst_bench())
    for name in (*CASES, *LONG_CASES):
        (work / name).mkdir()
    print(work)


def verify():
    work, cold, mapped, baseline = inputs()
    extracted = work / "placed_receiver.v"
    assert extracted.read_bytes() == mapped
    results = {}
    evidence = [PLACEMENT, BASELINE, INTERCONNECT, cold, extracted, BENCH, CELLS,
                Path(__file__).resolve().relative_to(ROOT)]
    for name, (old_folder, signals) in CASES.items():
        prior = BASE_RUN / old_folder / "console.log"
        assert digest(prior) == baseline["evidence_sha256"][str(prior)]
        log = work / name / "xrun.log"
        text = log.read_text()
        expected = [line for line in prior.read_text().splitlines() if line.startswith(signals)]
        measured = [line for line in text.splitlines() if line.startswith(signals)]
        assert len(measured) == len(signals) and measured == expected
        for argument in (f"-top {TOP}", str(extracted.resolve()), str(BENCH), str(CELLS.resolve())):
            assert f"\t{argument}\n" in text, argument
        if name == "credit8":
            assert "TRI_ORACLE_CREDIT_TEST_DELAY=8" in text
        assert text.count(TERMINAL) == 1 and not re.search(r"\*(?:E|F|SE),", text)
        results[name] = measured
        evidence.extend((prior, log))
    long_bench = work / "continuous_credit_tb.sv"
    assert long_bench.read_text() == long_burst_bench()
    evidence.extend((long_bench, BUDGET))
    prior_budget = json.loads(BUDGET.read_text())
    assert prior_budget["separate_wrapper"]["incoming_bits_per_cycle"] == 896
    needed = Fraction(prior_budget["archived_workload_lower_bounds"]["ideal_encoded_response_cycles"],
                      prior_budget["paper_window_cycles"])
    long_bursts = {}
    for name, delay in LONG_CASES.items():
        log = work / name / "xrun.log"
        text = log.read_text()
        for argument in (f"-top {TOP}", str(extracted.resolve()), str(long_bench.resolve()), str(CELLS.resolve())):
            assert f"\t{argument}\n" in text, argument
        assert f"TRI_ORACLE_CREDIT_TEST_DELAY={delay}" in text
        assert text.count(TERMINAL) == 1 and not re.search(r"\*(?:E|F|SE),", text)
        counts = f"chunks={LONG_CHUNKS},{LONG_CHUNKS} responses={LONG_WORDS},{LONG_WORDS}"
        assert f"CREDIT_STALL_PASS {counts} " in text
        if delay == 4:
            assert text.splitlines().count(f"CREDIT_FULL_RATE_PASS {counts} delay=4") == 1
            stalls = [0, 0]
        else:
            row, = re.findall(rf"(?m)^CREDIT_DELAY_WINDOW_PASS {counts} delay={delay} credit_stalls=(\d+),(\d+)$", text)
            stalls = list(map(int, row))
        utilization = Fraction(LONG_CHUNKS, LONG_CHUNKS + max(stalls))
        long_bursts[str(delay)] = {
            "credit_return_delay_cycles": delay,
            "chunks_per_lane": LONG_CHUNKS,
            "reconstructed_512_bit_words_per_lane": LONG_WORDS,
            "idle_cycles_while_offering_chunks": stalls,
            "balanced_finite_burst_payload_edge_utilization": float(utilization),
            "reaches_archived_workload_utilization_target": utilization >= needed,
        }
        evidence.append(log)
    return {
        "state": "placed_booth_memory_receiver_burst_packing_verified",
        "cold_netlist_sha256": digest(cold),
        "input_data_bits_per_edge": 448,
        "parallel_credit_lanes": 2,
        "full_burst_input_chunks_per_lane": 64,
        "full_burst_output_words_per_lane": 56,
        "control_replays": results,
        "continuous_test_bursts": long_bursts,
        "minimum_payload_edge_utilization_for_archived_reads_in_paper_window": float(needed),
        "scope": "Xcelium replay of the exact mapped receiver extracted from the placed export. "
                 "It checks dense packing across word boundaries, both sampled edges, output backpressure "
                 "and multiple credit return delays. The 512-chunk test checks continuous offers on both lanes. "
                 "The required utilization comes from the archived workload under the paper's time budget. "
                 "These finite synthetic bursts are functional tests at a modeled clock.",
        "evidence_sha256": {str(path): digest(path) for path in evidence},
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
