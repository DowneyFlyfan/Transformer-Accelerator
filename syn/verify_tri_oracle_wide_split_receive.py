"""Pair the mapped split-head receiver with the verified wide request transmitter."""

import argparse
import json
from pathlib import Path
import re

from link_tri_oracle_indexed_whole_chip import module_at, pins, signature, spans, update_instance
from prepare_tri_oracle_booth_packet_replay import replace_once
from verify_tri_oracle_booth_receive_credit_limit import TRACE, capacity
from verify_tri_oracle_booth_response_packing import CELLS, TERMINAL, TOP, digest, long_burst_bench
from verify_tri_oracle_wide_request_trial import FIXTURES, MATRIX, TOP as TRAINED_TOP, TRAFFIC


ROOT = Path(__file__).resolve().parents[1]
WIDE = Path("records/tri_oracle_wide_request_trial.json")
SPLIT = Path("records/tri_oracle_split_credit_ingress.json")
PACKING = Path("records/tri_oracle_corrected_booth_response_packing.json")
FIXED = Path("records/tri_oracle_corrected_booth_fixed_lane_credit_budget.json")
LIMIT = Path("records/tri_oracle_corrected_booth_receive_credit_limit.json")
OVERLAP = Path("records/tri_oracle_corrected_booth_request_response_overlap.json")
TARGETS = Path("records/paper_result_targets.json")
WORKLOAD = Path(".cache/memory_response_gearbox/workload_serial.json")
SCHEDULE = Path(".cache/model_reference/normalized_weight_burst_schedule_v2/receipt.json")
SERIAL = Path(".cache/physical/wide_weight_loader/joined_chip_partition/serial_projection_budget.json")
WRAPPER = "tri_oracle_credit_metadata_ingress"
RECEIVER = "tri_oracle_credit_memory_ingress"
PLACED_RECEIVER = f"tri_gated_rx_i_{RECEIVER}"
CASES = ("trained_delay7", "continuous_delay7", "continuous_delay8")


def read(path):
    return json.loads(path.read_text())


def setup():
    evidence = {}

    def pin(path, expected=None):
        checksum = digest(path)
        key = str(path.relative_to(ROOT) if path.is_absolute() else path)
        assert expected is None or expected == checksum, path
        assert evidence.setdefault(key, checksum) == checksum
        return path.resolve()

    wide, split, packing = (read(pin(path)) for path in (WIDE, SPLIT, PACKING))
    wide_hashes, split_hashes = (record["evidence_sha256"] for record in (wide, split))
    base, = (pin(Path(name), checksum) for name, checksum in wide_hashes.items() if name.endswith("/wide_request_trial/xrun.log"))
    wide_source = base.parent
    assert wide["cold_receiver_netlist_sha256"] == packing["cold_netlist_sha256"]
    original = wide_source.parent / "response_packing/placed_receiver.v"
    receiver_path = Path(".cache/physical/whole_chip_xcelium_speed/split_credit_ingress/genus/netlist.v")
    pin(receiver_path, split_hashes[str(receiver_path)])
    pin(original, packing["evidence_sha256"][str(original.relative_to(ROOT))])
    source, replacement = original.read_bytes(), receiver_path.read_bytes()
    old_index, new_index = spans(source), spans(replacement)
    assert PLACED_RECEIVER in old_index and RECEIVER in new_index and WRAPPER not in new_index
    assert signature(module_at(source, old_index, PLACED_RECEIVER)) == signature(module_at(replacement, new_index, RECEIVER))
    wrapper = module_at(source, old_index, WRAPPER)
    named = pins(wrapper, PLACED_RECEIVER, "receiver")
    assert named.keys() == signature(module_at(replacement, new_index, RECEIVER)).keys()
    # The placed implementation used shared metadata internally and left the
    # duplicate bits disconnected. The split receiver samples each lane's
    # inputs independently, so drive both from the same physical pad bits.
    metadata = {"pad_valid": b"[6]", "pad_words": b"[5:3]", "pad_compact": b"[2]",
                "pad_last": b"[1]", "pad_error": b"[0]"}
    assert all(b"UNCONNECTED_HIER" in named[pin] for pin in metadata)
    wired = update_instance(wrapper, PLACED_RECEIVER, "receiver", replacement=RECEIVER,
                            update={pin: b"{2{pad_metadata" + field + b"}}" for pin, field in metadata.items()})
    assert signature(wired) == signature(wrapper)
    receiver = replacement.decode() + "\n" + wired.decode() + "\n"

    path = wide_source / "bundle.sv"
    train = pin(path, wide_hashes[str(path.relative_to(ROOT))]).read_text()
    for name in re.findall(r'(?m)^\x60include "([^"]+)"$', train):
        item = Path(name)
        pin(item, wide_hashes[str(item.relative_to(ROOT))])
    for fixture in FIXTURES:
        resolved = (wide_source / fixture).resolve(strict=True)
        pin(resolved, wide_hashes[str(resolved.relative_to(ROOT))])
    out = wide_source / "split_receive"
    train = replace_once(train, str(original), str(out / "receiver.v"))

    previous_bench = original.with_name("continuous_credit_tb.sv")
    pin(previous_bench, packing["evidence_sha256"][str(previous_bench.relative_to(ROOT))])
    bench = long_burst_bench()
    assert bench == previous_bench.read_text()
    bench = replace_once(bench, "        int updated;\n", "        int updated;\n" + TRACE)
    return out, {"receiver.v": receiver, "bundle.sv": train, "credit_trace_tb.sv": bench}, wide_source, evidence


def launch_periods(transcript, delay):
    periods = []
    for lane in range(2):
        sends = [tuple(map(int, row)) for row in re.findall(
            rf"(?m)^CREDIT_LIMIT_SEND lane={lane} index=(\d+) ns=(\d+)$", transcript)]
        assert [index for index, _ in sends] == list(range(9))
        sample = int(re.search(rf"(?m)^CREDIT_LIMIT_SAMPLE lane={lane} ns=(\d+)$", transcript)[1])
        returned = int(re.search(rf"(?m)^CREDIT_LIMIT_RETURN lane={lane} ns=(\d+)$", transcript)[1])
        # The new credit can only fund a later launch. An uninterrupted initial
        # window can mask an earlier return, so derive reuse from the pulse.
        assert returned - sample == 10 * delay and sends[8][1] >= returned + 10
        period, remainder = divmod(returned + 10 - sends[0][1], 10)
        assert not remainder and sends[8][1] - sends[0][1] == 10 * max(period, 8)
        periods.append(period)
    return periods


def fits(cycles, fragments, reads, ranges, request_minima, credits, periods, disjoint_transfers):
    if cycles < 2 * reads:
        return False
    permitted = [
        (lower, min(upper, capacity(cycles, credits, period), cycles - disjoint_transfers * minimum))
        for (lower, upper), period, minimum in zip(ranges, periods, request_minima, strict=True)
    ]
    if any(lower > upper for lower, upper in permitted):
        return False
    # Pick the feasible integer interval for the first lane's response count.
    # Once these counts are fixed, unused cycles bound the requests on each
    # lane. The sum of the two quotients depends only on the first count's
    # residue modulo disjoint_transfers.
    (low_first, high_first), (low_other, high_other) = permitted
    first = max(low_first, fragments - high_other)
    last = min(high_first, fragments - low_other)
    return any((cycles - count) // disjoint_transfers +
               (cycles - fragments + count) // disjoint_transfers >= reads
               for count in range(first, min(last + 1, first + disjoint_transfers)))


def service_floor(fragments, reads, ranges, request_minima, credits, periods, disjoint_transfers):
    first, last = 0, (fragments + reads) * (max(periods) + disjoint_transfers)
    args = (fragments, reads, ranges, request_minima, credits, periods, disjoint_transfers)
    assert fits(last, *args)
    while first < last:
        midpoint = (first + last) // 2
        if fits(midpoint, *args):
            last = midpoint
        else:
            first = midpoint + 1
    assert not fits(first - 1, *args) and fits(first, *args)
    return first


def verify():
    out, files, source, evidence = setup()
    for name, expected in files.items():
        path = out / name
        assert path.read_text() == expected
        evidence[str(path.relative_to(ROOT))] = digest(path)
    native = {}
    for fixture in FIXTURES:
        assert (out / "trained_delay7" / fixture).resolve(strict=True) == (source / fixture).resolve(strict=True)
    for case in CASES:
        folder = out / case
        log, status = folder / "xrun.log", folder / "exit_status"
        transcript = log.read_text()
        assert status.read_text().strip() == "0" and transcript.count(TERMINAL) == 1
        assert not re.search(r"\*(?:E|F|SE),", transcript)
        for path in (log, status):
            evidence[str(path.relative_to(ROOT))] = digest(path)
        native[case] = transcript

    baseline = (source / "xrun.log").read_text()
    updated = native["trained_delay7"]
    for text in (baseline, updated):
        assert f"\t-top {TRAINED_TOP}\n" in text and "\t+FULL_MATRIX\n" in text
        assert "TRI_ORACLE_TRAINED_WINDOW=8" in text and "TRI_ORACLE_TRAINED_RETURN=7" in text
        assert "STAGED_INDEXED_DOWN_MATRIX_PASS cases=78 exact_bytes=11534336 " in text
        assert "NATIVE_MEMORY_IO_PASS acks=16 faults=2 " in text
    assert f"\t{out / 'bundle.sv'}\n" in updated and MATRIX.findall(updated) == MATRIX.findall(baseline)
    bench_cycles = [int(re.search(r"(?m)^DUAL_GROUP_MATRIX_WRITES writes=90112 cycles=(\d+)$", text)[1])
                    for text in (baseline, updated)]
    flits = [tuple(map(int, TRAFFIC.findall(text)[0])) for text in (baseline, updated)]
    assert flits[0][:2] == flits[1][:2] == (9280, 9280)

    target, fixed, limit, link, workload, schedule, serial = (
        read(path) for path in (TARGETS, FIXED, LIMIT, OVERLAP, WORKLOAD, SCHEDULE, SERIAL))
    cold_digest = read(WIDE)["cold_receiver_netlist_sha256"]
    assert all(record["cold_netlist_sha256"] == cold_digest for record in (fixed, limit, link))
    assert fixed["evidence_sha256"][str(LIMIT)] == digest(LIMIT)
    assert fixed["evidence_sha256"][str(WORKLOAD)] == digest(WORKLOAD) == link["evidence_sha256"][str(WORKLOAD)]
    for path in (SCHEDULE, SERIAL, TARGETS):
        assert workload["evidence_sha256"][str(path)] == digest(path)
    ranges = fixed["weight_and_sign_fragment_bounds_by_lane"]
    fragments = fixed["weight_and_sign_fragments"]
    assert fragments == link["archived_response_fragments_after_compact_indexes"]
    requests = link["archived_weight_read_requests"] + link["archived_sign_line_read_requests"]
    assert link["archived_weight_read_requests"] == workload["one_request_cycle_per_burst"]
    down_max = max(int(length) for phase in schedule["phases"].values() for length in phase["down"])
    minima = [2 * lane["gate_blocks"] + (lane["down_payload_beats"] + down_max - 1) // down_max
              for lane in fixed["gate_up_by_lane"]]
    assert sum(minima) <= requests
    window = link["paper_window_cycles"]
    assert window == target["system_latency"]["clock_megahertz"] * target["system_latency"]["milliseconds"] * 1000
    assert window == serial["target_cycles"]
    projection_cycles = serial["minimum_projection_issue_cycles"]

    def floors(credits, periods):
        result = {}
        for disjoint in (1, 2):
            combined = service_floor(fragments, requests, ranges, minima, credits, periods, disjoint)
            left = window - combined
            result[str(disjoint)] = {
                "optimistic_read_service_floor_cycles": combined,
                "paper_budget_cycles_left_at_floor": left,
                "minimum_projection_overlap_cycles_if_archived_issue_count_holds": max(0, projection_cycles - left),
            }
        return result

    measured = {}
    for delay in (7, 8):
        transcript = native[f"continuous_delay{delay}"]
        assert f"\t-top {TOP}\n" in transcript
        assert all(f"\t{path}\n" in transcript for path in (out / "receiver.v", out / "credit_trace_tb.sv", CELLS.resolve()))
        assert f"TRI_ORACLE_CREDIT_TEST_DELAY={delay}" in transcript
        periods = launch_periods(transcript, delay)
        prefix = r"CREDIT_DELAY_WINDOW_PASS chunks=512,512 responses=448,448 delay="
        stalls = list(map(int, re.search(rf"(?m)^{prefix}{delay} credit_stalls=(\d+),(\d+)$", transcript).groups()))
        assert "CREDIT_STALL_PASS chunks=512,512 responses=448,448 " in transcript
        for period, stall in zip(periods, stalls, strict=True):
            assert capacity(511 + stall, 8, period) < 512 <= capacity(512 + stall, 8, period)
        previous = limit["cases"][f"8_credits_delay_{delay}"]["lane_credit_reuse_periods"]
        measured[str(delay)] = {"credits": 8, "lane_reuse_periods": periods, "continuous_stalls": stalls,
                                "placed_receiver_lane_reuse_periods": previous,
                                "bounds_by_disjoint_request_transfers_per_read": floors(8, periods)}
    placed_models = {}
    for delay in (7, 8):
        case = limit["cases"][f"9_credits_delay_{delay}"]
        placed_models[str(delay)] = floors(9, case["lane_credit_reuse_periods"])
    for path in (FIXED, LIMIT, OVERLAP, TARGETS, WORKLOAD, SCHEDULE, SERIAL, Path(__file__).resolve().relative_to(ROOT)):
        evidence[str(path)] = digest(path)
    return {
        "state": "wide_transmitter_and_split_receiver_mapped_replay",
        "trained_tiles": 78, "trained_weight_bytes": 11534336,
        "placed_receive_fixture_cycles": bench_cycles[0], "split_receive_fixture_cycles": bench_cycles[1],
        "fixture_cycles_saved": bench_cycles[0] - bench_cycles[1],
        "request_flits": flits[1][0], "credit_checks": measured,
        "original_receiver_nine_credit_bounds_by_delay_then_disjoint_transfers": placed_models,
        "fixed_lane_lower_bound_read_requests": minima, "paper_window_cycles": window,
        "archived_minimum_projection_issue_cycles": projection_cycles,
        "scope": "Mapped sender, memory loader and split receiver under modeled credit delays. "
                 "Read-service bounds charge two shared transmitter transfers per archived read and compare granting "
                 "zero or one same-lane request/response overlap. They allow ideal scheduling within traced lane bounds. "
                 "The projection comparison uses the issue count from a separate archived controller model. "
                 "The split receiver awaits whole-chip integration and physical timing.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    if args.phase == "prepare":
        out, files, source, _ = setup()
        out.mkdir()
        for name, contents in files.items():
            (out / name).write_text(contents)
        for name in CASES:
            (out / name).mkdir()
        for fixture in FIXTURES:
            (out / "trained_delay7" / fixture).symlink_to((source / fixture).resolve(strict=True))
        print(out)
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
