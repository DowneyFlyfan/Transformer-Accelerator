"""Bound response traffic by the measured credit reuse periods of the placed link."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_booth_packet_replay import replace_once
from verify_tri_oracle_booth_response_packing import BUDGET, CELLS, ROOT, TERMINAL, TOP, digest, inputs


PACKING = Path("records/tri_oracle_corrected_booth_response_packing.json")
WINDOWS = Path("records/tri_oracle_corrected_booth_response_credit_window.json")
TARGET = Path("records/paper_result_targets.json")
DELAY = 7
TRACE = """        if (!warmup && !stress && sent[lane]<=Credits) begin
          if (pad_valid[lane])
            $display("CREDIT_LIMIT_SEND lane=%0d index=%0d ns=%0d",lane,sent[lane],$time);
          if (pad_credit[lane])
            $display("CREDIT_LIMIT_SAMPLE lane=%0d ns=%0d",lane,$time);
          if (returns[lane][ReturnCycles-1])
            $display("CREDIT_LIMIT_RETURN lane=%0d ns=%0d",lane,$time);
        end
"""


def setup():
    stage, cold, mapped, _ = inputs()
    extracted = stage / "placed_receiver.v"
    proof = json.loads(PACKING.read_text())
    bench = stage / "continuous_credit_tb.sv"
    assert extracted.read_bytes() == mapped
    for path in (cold, extracted, bench):
        assert proof["evidence_sha256"][str(path)] == digest(path)
    assert proof["cold_netlist_sha256"] == digest(cold)
    observed = stage / "continuous_credit7/xrun.log"
    assert proof["evidence_sha256"][str(observed)] == digest(observed)
    source = bench.read_text()
    assert "localparam int Credits = 8;" in source and "always #5 clk=~clk;" in source
    updated = replace_once(source, "        int updated;\n", "        int updated;\n" + TRACE)
    return stage.with_name("response_credit_limit"), updated, proof, (cold, extracted, bench, observed)


def capacity(cycles, credits, period):
    # Every interval of 'period' launches can use each credit at most once.
    # Break the entire window into disjoint intervals and bound the remainder
    # by both the available credits and the single launch per edge.
    complete, remainder = divmod(cycles, period)
    return complete * min(credits, period) + min(credits, remainder)


def minimum_cycles(fragments, credits, periods):
    first, last = 0, fragments * max(periods)
    while first < last:
        midpoint = (first + last) // 2
        if sum(capacity(midpoint, credits, period) for period in periods) < fragments:
            first = midpoint + 1
        else:
            last = midpoint
    return first


def verify():
    folder, source, proof, origin = setup()
    bench = folder / "credit_limit_tb.sv"
    assert bench.read_text() == source
    log, status = folder / "xrun.log", folder / "exit_status"
    transcript = log.read_text()
    assert int(status.read_text()) == 0
    assert transcript.count(TERMINAL) == 1 and not re.search(r"\*(?:E|F|SE),", transcript)
    assert f"\t-top {TOP}\n" in transcript
    source_args = {Path(arg).resolve() for arg in re.findall(r"(?m)^\t(/\S+)\s*$", transcript)}
    assert {path.resolve() for path in (bench, CELLS, origin[1])} <= source_args
    assert f"TRI_ORACLE_CREDIT_TEST_DELAY={DELAY}" in transcript
    offsets = []
    for lane in range(2):
        sends = [tuple(map(int, row)) for row in re.findall(
            rf"(?m)^CREDIT_LIMIT_SEND lane={lane} index=(\d+) ns=(\d+)$", transcript)]
        assert [index for index, _ in sends] == list(range(9)), sends
        start = sends[0][1]
        first_sample = int(re.search(rf"(?m)^CREDIT_LIMIT_SAMPLE lane={lane} ns=(\d+)$", transcript)[1])
        first_return = int(re.search(rf"(?m)^CREDIT_LIMIT_RETURN lane={lane} ns=(\d+)$", transcript)[1])
        # The shared receiver registers this pulse at the first possible rising
        # edge after capture. The peer sees it at its next sampling edge.
        assert first_sample - start == (2 - lane) * 10
        assert first_return - first_sample == DELAY * 10
        # The return updates the peer counter after this edge. It can fund
        # a send only on a subsequent sampling edge.
        first_reuse = sends[8][1]
        assert first_reuse - first_return == 10
        offsets.append((first_reuse - start) // 10 - DELAY)

    budget, target, window_proof = (json.loads(path.read_text()) for path in (BUDGET, TARGET, WINDOWS))
    assert proof["cold_netlist_sha256"] == window_proof["cold_netlist_sha256"]
    window = budget["paper_window_cycles"]
    frequency = target["system_latency"]["clock_megahertz"]
    assert window == target["system_latency"]["milliseconds"] * frequency * 1000
    archived = budget["archived_workload_lower_bounds"]
    fragments = archived["encoded_weight_fragments"] + archived["sign_fragments"]
    cases = {str(key): (8, int(key), row["idle_cycles_while_offering_chunks"])
             for key, row in proof["continuous_test_bursts"].items()}
    cases.update({name: (row["initial_credits"], row["return_delay_cycles"],
                         row["continuous_offer_stall_cycles"])
                  for name, row in window_proof["simulation"].items() if not row["overflow_reported_in_stall_test"]})
    results = {}
    for credits, delay, idle in cases.values():
        periods = [delay + offset for offset in offsets]
        # Each recorded uninterrupted offer burst ended at the first
        # cycle allowed by this bound on both lanes.
        for period, stalls in zip(periods, idle, strict=True):
            cycles = 512 + stalls
            assert capacity(cycles - 1, credits, period) < 512 <= capacity(cycles, credits, period)
        lane_capacity = [capacity(window, credits, period) for period in periods]
        lower_bound = minimum_cycles(fragments, credits, periods)
        results[f"{credits}_credits_delay_{delay}"] = {
            "lane_credit_reuse_periods": periods,
            "lane_fragment_capacity": lane_capacity,
            "total_fragment_margin": sum(lane_capacity) - fragments,
            "optimistic_response_cycles": lower_bound,
            "optimistic_response_ms_at_paper_clock": lower_bound / (frequency * 1000),
        }
    return {
        "state": "placed_response_credit_reuse_bounds_checked_against_native_bursts",
        "cold_netlist_sha256": proof["cold_netlist_sha256"],
        "paper_window_cycles": window,
        "archived_weight_and_sign_fragments": fragments,
        "cases": results,
        "scope": "The placed receiver is coupled to modeled credit return delays. Bounds allow ideal "
                 "fragment steering across the two lanes and omit computation, turnaround and all "
                 "other traffic. Passing the bound only establishes response capacity under these assumptions.",
        "evidence_sha256": {str(path.relative_to(ROOT) if path.is_absolute() else path): digest(path)
                            for path in (*origin, bench, log, status, CELLS,
                                         PACKING, BUDGET, TARGET, WINDOWS, Path(__file__).resolve())},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    if args.phase == "prepare":
        folder, source, _, _ = setup()
        folder.mkdir()
        (folder / "credit_limit_tb.sv").write_text(source)
        print(folder)
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
