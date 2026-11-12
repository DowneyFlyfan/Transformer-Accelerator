"""Bound the request savings from batching adjacent packed sign misses."""

import argparse
import json
from pathlib import Path

import numpy as np

import measure_tri_oracle_packed_workload_traffic as traffic
from measure_tri_oracle_packed_sign_lines import LINES_PER_GROUP, PAIRS, PREFILL_BATCH, packed_line_requests
from measure_tri_oracle_sign_cache_workload import GROUPS, misses
from verify_tri_oracle_packed_down_weights import ROOT, sha256


# The 64- and 128-entry splits were measured on this workload. Use the 64-entry
# split for 32 entries as well so the comparison keeps that steering fixed.
PRIMARY_BUCKETS = {32: 10, 64: 10, 128: 9}


def read(path):
    return json.loads(path.read_text())


def folded(addresses, width):
    result = addresses.copy()
    for shift in range(width, 58, width):
        result ^= addresses >> shift
    return result & ((1 << width) - 1)


def miss_indices(addresses, entries):
    if not addresses.size:
        return np.empty(0, dtype=np.int64)
    slots = folded(addresses, entries.bit_length() - 1)
    order = np.argsort(slots, kind="stable")
    ordered = addresses[order]
    mask = np.empty(addresses.shape, dtype=bool)
    mask[order] = np.r_[True, ordered[1:] != ordered[:-1]]
    return np.flatnonzero(mask)


def bursts(addresses, max_beats, owners=None):
    if not addresses.size:
        return 0
    boundaries = addresses[1:] != addresses[:-1] + 1
    if owners is not None:
        boundaries |= owners[1:] != owners[:-1]
    lengths = np.diff(np.r_[0, np.flatnonzero(boundaries) + 1, addresses.size])
    return int(((lengths + max_beats - 1) // max_beats).sum())


def run(output):
    steering_path = ROOT / "records/wac_dual_port_packed_sign_steering_result.json"
    payload_path = ROOT / "records/wac_packed_sign_payload_result.json"
    original_path = traffic.DATA / "packed_sign_line_workload/receipt.json"
    baseline_path = traffic.DATA / "packed_workload_traffic_v1/packed_traffic.json"
    bounds_path = ROOT / "records/wac_dual_lane_burst_budget_result.json"
    steering, payload, original, baseline, bounds = map(read, (
        steering_path, payload_path, original_path, baseline_path, bounds_path,
    ))
    assert payload["evidence_sha256"][str(original_path.relative_to(ROOT))] == sha256(original_path)
    assert steering["evidence_sha256"][str(baseline_path.relative_to(ROOT))] == sha256(baseline_path)
    max_beats = bounds["native_burst_probe"]["max_beats"]
    layouts = original["layouts_byte_addresses"]
    totals = {size: {layout: [{"beats": 0, "token_group_bursts": 0, "frame_bursts": 0} for _ in range(2)]
                     for layout in layouts} for size in PRIMARY_BUCKETS}
    paths = (steering_path, payload_path, original_path, baseline_path, bounds_path, Path(__file__).resolve(),
             Path(packed_line_requests.__code__.co_filename), Path(misses.__code__.co_filename),
             Path(traffic.__file__).resolve())
    pins = {str(path.relative_to(ROOT)): sha256(path) for path in paths}
    original_reconstruct = traffic.reconstruct

    def capture(reference, activation, stats):
        result = original_reconstruct(reference, activation, stats)
        norms = stats["norm_codes"]  # [rows, hidden features] from the integer policy.
        masks = (norms.abs() > 768).reshape(len(norms), PAIRS, 2).any(dim=2).cpu().numpy()  # [rows, pairs].
        for first in range(0, len(masks), PREFILL_BATCH):
            frame = masks[first:first + PREFILL_BATCH]  # [frame rows, pairs].
            strips = frame.reshape(len(frame), LINES_PER_GROUP, -1).any(axis=2)  # [frame rows, strips].
            tokens = np.nonzero(strips)[0]
            owners = (np.arange(GROUPS)[:, None] * len(frame) + tokens[None, :]).reshape(-1)
            for layout, base in layouts.items():
                addresses = packed_line_requests(frame, base)
                for size, threshold in PRIMARY_BUCKETS.items():
                    selected = miss_indices(addresses, size)
                    pending, pending_owners = addresses[selected], owners[selected]
                    if size == 64:
                        assert np.array_equal(pending, misses(addresses, size))
                    auxiliary = folded(pending, 5) >= threshold
                    for lane, summary in enumerate(totals[size][layout]):
                        on_lane = auxiliary == bool(lane)
                        words = pending[on_lane]
                        summary["beats"] += int(words.size)
                        summary["token_group_bursts"] += bursts(words, max_beats, pending_owners[on_lane])
                        summary["frame_bursts"] += bursts(words, max_beats)
        return result

    output.mkdir()
    traffic.reconstruct = capture
    try:
        traffic.run(output / "replay")
    finally:
        traffic.reconstruct = original_reconstruct
    replay_path = output / "replay/packed_traffic.json"
    replay = read(replay_path)
    assert all(replay[key] == baseline[key] for key in ("prefill_by_batch_size", "decode", "layers"))
    summary = {}
    for size, by_layout in totals.items():
        for layout, lanes in by_layout.items():
            if size in (64, 128):
                assert sum(lane["beats"] for lane in lanes) == original["summary"][str(size)][layout]["external_line_reads"]
            assert all(lane["frame_bursts"] <= lane["token_group_bursts"] <= lane["beats"] for lane in lanes)
        modes = {"single": "beats", "same_token_and_group": "token_group_bursts", "whole_frame": "frame_bursts"}
        cycles = {mode: max(max(weight + lane["beats"] + lane[key] for weight, lane in
                                zip(steering["weight_cycles_by_lane"], lanes, strict=True))
                            for lanes in by_layout.values()) for mode, key in modes.items()}
        if size in (64, 128):
            assert cycles["single"] == steering["paper_latency_cycle_budget"] - steering["summary"][str(size)]["remaining_cycles_on_busiest_port"]
        summary[size] = {"busiest_port_cycles": cycles, "worst_port_ms": {
            mode: value / (1000 * bounds["clock_megahertz"]) for mode, value in cycles.items()}}
    assert all(sha256(ROOT / path) == digest for path, digest in pins.items())
    pins[str(replay_path.relative_to(ROOT))] = sha256(replay_path)
    result = {
        "state": "packed_sign_burst_savings_bounded_on_archived_trace",
        "primary_buckets": PRIMARY_BUCKETS, "per_lane": totals, "summary": summary,
        "paper_latency_ms": bounds["paper_latency_ms"], "peak_gpu_bytes": replay["peak_gpu_bytes"],
        "scope": "Optimistic batching of consecutive addresses in the ordered sign miss stream after steering. "
                 "Holds hits and evictions fixed, with no added lookahead, buffering, traffic or compute cycles. "
                 "The per-token/group case stays within one predictor group and token. No burst reader is implemented here.",
        "evidence_sha256": pins,
    }
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], {size: row["worst_port_ms"] for size, row in summary.items()}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
