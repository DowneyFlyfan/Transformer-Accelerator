"""Check whether the placed receive path can use its capture slot as a ninth credit."""

import argparse
from fractions import Fraction
import json
from pathlib import Path
import re

import torch

from verify_tri_oracle_booth_response_packing import (
    BENCH, CELLS, LONG_CHUNKS, LONG_WORDS, ROOT, TERMINAL, TOP, digest, inputs, long_burst_bench,
)


PACKING = Path("records/tri_oracle_corrected_booth_response_packing.json")
FIFO_SLOTS = 8
CASES = ((8, 7), (9, 7), (9, 8), (10, 7))


def bench_source():
    reference_bench = long_burst_bench()
    anchor = "  localparam int Credits = 8;"
    assert reference_bench.count(anchor) == 1
    return reference_bench.replace(anchor, "  localparam int Credits = `TRI_ORACLE_INITIAL_CREDITS;")


def prepare():
    stage, _, actual, _ = inputs()
    assert (stage / "placed_receiver.v").read_bytes() == actual
    folder = stage.with_name("response_credit_window")
    folder.mkdir()
    (folder / "credit_window_tb.sv").write_text(bench_source())
    for credits, delay in CASES:
        (folder / f"credit{credits}_delay{delay}").mkdir()
    print(folder)


def count_transition_outcomes(credits, stages):
    """Count legal transitions in the capture, queue, head and return-pulse model."""
    shape = (2, FIFO_SLOTS + 1, 2, 1 << stages)
    capture, queued, head, pipe = torch.meshgrid(*(torch.arange(size, device="cuda") for size in shape), indexing="ij")
    pulses = torch.tensor([value.bit_count() for value in range(1 << stages)], device="cuda")
    available = credits - capture - queued - pulses[pipe]
    live = available >= 0
    capture, queued, head, pipe, available = (item[live] for item in (capture, queued, head, pipe, available))
    taken = ((capture > 0) & (queued < FIFO_SLOTS)).long()
    returned = pipe >> (stages - 1)
    overflow = 0
    for wants in (False, True):
        launch = ((available > 0) & wants).long()
        next_capture = capture + launch - taken
        overflow += int((next_capture > 1).sum()) * 2
        for ready in (False, True):
            release = (((head == 0) | ready) & ((queued + taken) > 0)).long()
            # When the queue is empty, release can bypass the captured word directly to the head.
            next_queue = queued + taken - release
            next_available = available + returned - launch
            next_pipe = ((pipe << 1) & ((1 << stages) - 1)) | release
            assert bool(((next_queue >= 0) & (next_queue <= FIFO_SLOTS)).all())
            assert bool(((next_available >= 0) & (next_available <= credits)).all())
            assert bool((next_capture + next_queue + next_available + pulses[next_pipe] == credits).all())
    return {"transitions": 4 * available.numel(), "overflow_transitions": overflow}


def verify():
    stage, cold, actual, _ = inputs()
    mapped = stage / "placed_receiver.v"
    packing = json.loads(PACKING.read_text())
    assert mapped.read_bytes() == actual
    assert digest(mapped) == packing["evidence_sha256"][str(mapped)]
    assert digest(cold) == packing["cold_netlist_sha256"]
    folder = stage.with_name("response_credit_window")
    bench = folder / "credit_window_tb.sv"
    assert bench.read_text() == bench_source()
    logs = [PACKING, cold, mapped, BENCH, bench, CELLS, Path(__file__).resolve().relative_to(ROOT)]
    measured = {}
    for credits, delay in CASES:
        run = folder / f"credit{credits}_delay{delay}"
        log, status = run / "xrun.log", run / "exit_status"
        text = log.read_text()
        assert all(f"\t{argument}\n" in text for argument in (
            str(mapped.resolve()), str(bench.resolve()), str(CELLS.resolve()), f"-top {TOP}"))
        for definition in (f"TRI_ORACLE_CREDIT_TEST_DELAY={delay}", f"TRI_ORACLE_INITIAL_CREDITS={credits}"):
            assert definition in text
        counts = f"chunks={LONG_CHUNKS},{LONG_CHUNKS} responses={LONG_WORDS},{LONG_WORDS}"
        delay_window, = re.findall(rf"(?m)^CREDIT_DELAY_WINDOW_PASS {counts} delay={delay} credit_stalls=(\d+),(\d+)$", text)
        stalls = list(map(int, delay_window))
        assert int(status.read_text()) == (2 if credits == 10 else 0)
        overflow = text.splitlines().count("CREDIT_RECEIVER_OVERFLOW")
        if credits == 10:
            assert overflow == 1 and TERMINAL not in text and "$fatal(1)" in text
        else:
            assert overflow == 0 and text.count(TERMINAL) == 1 and not re.search(r"\*(?:E|F|SE),", text)
            assert f"CREDIT_STALL_PASS {counts} " in text
        measured[f"{credits}_credits_delay_{delay}"] = {
            "initial_credits": credits, "return_delay_cycles": delay, "continuous_offer_stall_cycles": stalls,
            "payload_edge_utilization": float(Fraction(LONG_CHUNKS, LONG_CHUNKS + max(stalls))),
            "overflow_reported_in_stall_test": bool(overflow),
        }
        logs.extend((log, status))
    assert measured["8_credits_delay_7"]["continuous_offer_stall_cycles"] == (
        packing["continuous_test_bursts"]["7"]["idle_cycles_while_offering_chunks"])
    target = packing["minimum_payload_edge_utilization_for_archived_reads_in_paper_window"]
    assert measured["8_credits_delay_7"]["payload_edge_utilization"] < target
    assert measured["9_credits_delay_8"]["payload_edge_utilization"] < target
    assert measured["9_credits_delay_7"]["payload_edge_utilization"] >= target

    assert torch.cuda.is_available() and torch.cuda.mem_get_info()[0] >= 1024**3
    torch.cuda.set_per_process_memory_fraction(0.08)
    proof = {str(credits): {str(delay): count_transition_outcomes(credits, delay) for delay in range(1, 11)}
             for credits in (9, 10)}
    assert not any(row["overflow_transitions"] for row in proof["9"].values())
    assert all(row["overflow_transitions"] for row in proof["10"].values())
    return {
        "state": "placed_booth_nine_credit_receive_window_verified_in_directed_replay",
        "cold_netlist_sha256": packing["cold_netlist_sha256"],
        "fifo_slots_per_lane": FIFO_SLOTS,
        "modeled_payload_edge_utilization_target": target,
        "simulation": measured,
        "abstract_storage_transitions_by_credit_count_and_return_stages": proof,
        "verification_device": torch.cuda.get_device_name(),
        "scope": "Directed placed-receiver tests with altered peer initial credit counts. The host proof "
                 "checks abstract storage and delayed pulse conservation with one capture slot per lane. "
                 "The project full-chip peers continue to use eight credits.",
        "evidence_sha256": {str(path.relative_to(ROOT) if path.is_absolute() else path): digest(path) for path in logs},
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    if parser.parse_args().prepare:
        prepare()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
