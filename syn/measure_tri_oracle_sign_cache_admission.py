"""Evaluate bypassing sign lines requested by only one token per group."""

import argparse
import json
from pathlib import Path

import numpy as np

import measure_tri_oracle_packed_workload_traffic as traffic
from measure_tri_oracle_dual_port_sign_lines import route_buckets
from measure_tri_oracle_packed_sign_bursts import miss_indices
from measure_tri_oracle_packed_sign_lines import GROUPS, LINES_PER_GROUP, PREFILL_BATCH, packed_line_requests
from verify_tri_oracle_packed_down_weights import ROOT, sha256


CAPACITIES = (32, 64, 128)
MINIMUM_USES = (1, 2, 3, 4)


def admitted_misses(words, admitted, entries):
    """Return external reads in request order, leaving bypassed lines out of the cache."""
    assert words.shape == admitted.shape and admitted.dtype == np.bool_
    allocate = np.flatnonzero(admitted)
    external = ~admitted
    external[allocate[miss_indices(words[allocate], entries)]] = True
    return words[external]


def selected_miss_mask(frame, chosen):
    """Read each retained strip once and each bypassed strip on every request."""
    selected = np.zeros(frame.shape[1], dtype=bool)  # [S], admitted strips.
    selected[chosen] = True
    requests = np.nonzero(frame)[1]  # [requests per group], ordered by token then strip.
    external = ~selected[requests]
    _, first_requests = np.unique(requests, return_index=True)
    external[first_requests] = True
    return external


def retained_miss_mask(frame, entries, use_folded_index):
    """Choose one strip per slot to retain until the channel group finishes."""
    strip = np.arange(frame.shape[1])  # [S], valid strip indexes.
    uses = frame.sum(axis=0)  # [S], number of tokens requesting each strip.
    assert entries > 1 and entries & (entries - 1) == 0
    width = entries.bit_length() - 1
    indexed = strip.copy()
    if use_folded_index:
        for shift in range(width, frame.shape[1].bit_length(), width):
            indexed ^= strip >> shift
    slot = indexed & (entries - 1)  # [S], slot for each strip.
    order = np.lexsort((strip, -uses, slot))  # [S], highest-use strip first within each slot.
    chosen = order[np.r_[True, slot[order][1:] != slot[order][:-1]]]
    return selected_miss_mask(frame, chosen[uses[chosen] >= 2])


def ranked_miss_mask(frame, entries):
    """Assign distinct slots to the most-used strips, with ascending-index ties."""
    uses = frame.sum(axis=0)  # [S], per-strip request count.
    ranked = np.argsort(-uses, kind="stable")[:entries]  # Up to [entries] allocated strips.
    return selected_miss_mask(frame, ranked[uses[ranked] >= 2])


def run(output):
    steering_path = ROOT / "records/wac_dual_port_packed_sign_steering_result.json"
    lines_path = traffic.DATA / "packed_sign_line_workload/receipt.json"
    baseline_path = traffic.DATA / "packed_workload_traffic_v1/packed_traffic.json"
    steering, lines, baseline = (json.loads(path.read_text()) for path in (steering_path, lines_path, baseline_path))
    for path in (lines_path, baseline_path):
        assert sha256(path) == steering["evidence_sha256"][str(path.relative_to(ROOT))]
    layouts = lines["layouts_byte_addresses"]
    policies = [("direct", entries, minimum) for entries in CAPACITIES for minimum in MINIMUM_USES]
    policies.extend((mode, entries, 2) for mode in ("retain_low", "retain_fold") for entries in CAPACITIES)
    policies.extend(("ranked", entries, 2) for entries in (16, *CAPACITIES))
    totals = {policy: {layout: np.zeros(32, dtype=np.int64) for layout in layouts} for policy in policies}
    original = traffic.reconstruct

    def capture(reference, activation, stats):
        result = original(reference, activation, stats)
        # Integer normalization codes [T,H], then pair and strip masks [T,H/2] and [T,S].
        norms = stats["norm_codes"]
        active_pairs = (norms.abs() > 768).reshape(len(norms), -1, 2).any(dim=2).cpu().numpy()
        for first in range(0, len(active_pairs), PREFILL_BATCH):
            pairs = active_pairs[first:first + PREFILL_BATCH]  # [frame tokens,H/2].
            frame = pairs.reshape(len(pairs), LINES_PER_GROUP, -1).any(axis=2)  # [frame tokens,S].
            strips = np.nonzero(frame)[1]  # [requests per channel group], token order.
            if len(frame) == 1:
                # A single token has no repeated line in any group.
                for name, base in layouts.items():
                    distribution = route_buckets(packed_line_requests(pairs, base))
                    for by_layout in totals.values():
                        by_layout[name] += distribution
                continue
            uses = frame.sum(axis=0)[strips]  # [requests per group], use count of each requested strip.
            admission = {minimum: np.tile(uses >= minimum, GROUPS) for minimum in MINIMUM_USES}
            retained = {
                (mode, entries): np.tile(retained_miss_mask(frame, entries, mode == "retain_fold"), GROUPS)
                for mode, entries, _ in policies if mode.startswith("retain_")
            }
            retained.update({("ranked", entries): np.tile(ranked_miss_mask(frame, entries), GROUPS)
                             for mode, entries, _ in policies if mode == "ranked"})
            for name, base in layouts.items():
                words = packed_line_requests(pairs, base)  # [all group requests], absolute line addresses.
                for (mode, entries, minimum), by_layout in totals.items():
                    external = (admitted_misses(words, admission[minimum], entries) if mode == "direct"
                                else words[retained[mode, entries]])
                    by_layout[name] += route_buckets(external)
        return result

    output.mkdir()
    traffic.reconstruct = capture
    try:
        traffic.run(output / "replay")
    finally:
        traffic.reconstruct = original
    replay_path = output / "replay/packed_traffic.json"
    replay = json.loads(replay_path.read_text())
    assert all(replay[key] == baseline[key] for key in ("layers", "prefill_by_batch_size", "decode"))
    weights = steering["weight_cycles_by_lane"]
    target = steering["paper_latency_cycle_budget"]
    summary = {}
    for (mode, entries, minimum), by_layout in totals.items():
        if mode == "direct" and minimum == 1 and str(entries) in lines["summary"]:
            for name, distribution in by_layout.items():
                assert int(distribution.sum()) == lines["summary"][str(entries)][name]["external_line_reads"]
        outcomes = []
        for threshold in range(33):
            lanes = {
                name: [weights[0] + 2 * int(counts[:threshold].sum()), weights[1] + 2 * int(counts[threshold:].sum())]
                for name, counts in by_layout.items()
            }
            outcomes.append((max(max(pair) for pair in lanes.values()), threshold, lanes))
        worst, threshold, lanes = min(outcomes)
        if mode == "direct" and minimum == 1 and str(entries) in steering["summary"]:
            known = steering["summary"][str(entries)]
            assert threshold == known["send_to_primary_when_bucket_below"]
            assert worst == target - known["remaining_cycles_on_busiest_port"]
            assert lanes == known["lane_cycles_by_layout"]
        summary[f"{mode}:{entries}:{minimum}"] = {
            "policy": mode, "entries": entries, "minimum_uses": minimum, "data_sram_bytes": 64 * entries,
            "send_to_primary_when_bucket_below": threshold,
            "external_line_reads_by_layout": {name: int(counts.sum()) for name, counts in by_layout.items()},
            "lane_cycles_by_layout": lanes, "worst_port_cycles": worst, "worst_port_ms_at_580mhz": worst / 580000,
            "remaining_port_cycles": target - worst,
        }
    paths = (steering_path, lines_path, baseline_path, replay_path, Path(__file__).resolve(),
             Path(miss_indices.__code__.co_filename), Path(route_buckets.__code__.co_filename),
             Path(packed_line_requests.__code__.co_filename), Path(traffic.__file__).resolve())
    result = {
        "state": "sign_cache_admission_measured_on_pinned_workload",
        "paper_latency_cycle_budget": target, "summary": summary,
        "native_seconds": replay["native_seconds"], "peak_gpu_bytes": replay["peak_gpu_bytes"],
        "scope": "Models per-frame admission from token outlier metadata, two fixed memory lanes "
                 "and unchanged weight traffic. Port service excludes compute, admission logic and controller stalls.",
        "evidence_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in paths},
    }
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], {key: round(row["worst_port_ms_at_580mhz"], 5) for key, row in summary.items()}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
