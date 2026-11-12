"""Budget fixed packed-sign steering against the two actual weight schedules."""

import argparse
import json
from pathlib import Path

import numpy as np

import measure_tri_oracle_packed_workload_traffic as traffic
from measure_tri_oracle_packed_sign_lines import CAPACITIES, PAIRS, PREFILL_BATCH, packed_line_requests
from measure_tri_oracle_sign_cache_workload import misses
from measure_tri_oracle_weight_burst_schedule import projection_histograms
from verify_tri_oracle_packed_down_weights import ROOT, sha256


BUCKETS = 32


def read(path):
    return json.loads(path.read_text())


def route_buckets(addresses):
    """XOR-fold the 58-bit line addresses to a five-bit steering index."""
    folded = addresses.copy()
    for shift in range(5, 58, 5):
        folded ^= addresses >> shift
    return np.bincount((folded & (BUCKETS - 1)).astype(np.int64), minlength=BUCKETS)


def run(output):
    sign_path = traffic.DATA / "packed_sign_line_workload/receipt.json"
    sign_record_path = ROOT / "records/wac_packed_sign_line_result.json"
    weight_path = ROOT / "records/wac_weight_burst_schedule_result.json"
    packed_path = traffic.DATA / "packed_workload_traffic_v1/packed_traffic.json"
    bound_path = ROOT / "records/wac_primary_request_cycle_bound_result.json"
    signs, sign_record, weights, archive, bound = map(read, (sign_path, sign_record_path, weight_path, packed_path, bound_path))
    assert sha256(sign_path) == sign_record["evidence_sha256"][str(sign_path.relative_to(ROOT))]
    assert sha256(packed_path) == weights["evidence_sha256"][str(packed_path.relative_to(ROOT))]
    paths = (sign_path, sign_record_path, weight_path, packed_path, bound_path, Path(__file__).resolve(),
             Path(projection_histograms.__code__.co_filename), Path(packed_line_requests.__code__.co_filename),
             Path(misses.__code__.co_filename), Path(traffic.__file__).resolve())
    pins = {str(path.relative_to(ROOT)): sha256(path) for path in paths}
    layouts = signs["layouts_byte_addresses"]
    weight_counts = {phase: [{"payload": 0, "bursts": 0}, {"payload": 0, "bursts": 0}]
                     for phase in ("prefill", "decode")}
    buckets = {size: {layout: np.zeros(BUCKETS, dtype=np.int64) for layout in layouts} for size in CAPACITIES[1:]}
    original_group, original_reconstruct = traffic.group_traffic, traffic.reconstruct

    def capture_weight(activation, keep, dense_down, pruned_down, size):
        totals = original_group(activation, keep, dense_down, pruned_down, size)
        if activation.device.type == "cpu" or (size != PREFILL_BATCH and (size != 1 or len(activation) != 1)):
            return totals
        phase = weight_counts["prefill" if size == PREFILL_BATCH else "decode"]
        for gate, down in projection_histograms(activation, keep, pruned_down, size):
            for lane, (gate_reads, down_reads) in enumerate(zip(gate, down, strict=True)):
                histogram = gate_reads + down_reads
                phase[lane]["payload"] += sum(length * count for length, count in histogram.items())
                phase[lane]["bursts"] += sum(histogram.values())
        return totals

    def capture_sign(reference, activation, stats):
        result = original_reconstruct(reference, activation, stats)
        norms = stats["norm_codes"]  # [token rows, hidden features] from the archived integer policy.
        masks = (norms.abs() > 768).reshape(len(norms), PAIRS, 2).any(dim=2).cpu().numpy()  # [rows, pairs].
        for first in range(0, len(masks), PREFILL_BATCH):
            frame = masks[first:first + PREFILL_BATCH]  # [frame rows, pairs].
            for layout, base in layouts.items():
                addresses = packed_line_requests(frame, base)  # [sign-line requests in original order].
                for size in CAPACITIES[1:]:
                    buckets[size][layout] += route_buckets(misses(addresses, size))
        return result

    output.mkdir()
    traffic.group_traffic, traffic.reconstruct = capture_weight, capture_sign
    try:
        traffic.run(output / "replay")
    finally:
        traffic.group_traffic, traffic.reconstruct = original_group, original_reconstruct
    replay_path = output / "replay/packed_traffic.json"
    replay = read(replay_path)
    for field in ("layers", "prefill_by_batch_size", "decode"):
        assert replay[field] == archive[field], field
    for phase, actual in weight_counts.items():
        expected = weights["phases"][phase]
        assert [lane["payload"] for lane in actual] == expected["lane_payload_beats"]
        assert sum(lane["bursts"] for lane in actual) == sum(sum(expected[kind].values()) for kind in ("gate_up", "down"))
    weight_cycles = [sum(phase[lane]["payload"] + phase[lane]["bursts"] for phase in weight_counts.values())
                     for lane in (0, 1)]
    target = bound["paper_latency_cycle_budget"]
    frequency = 1000 * bound["paper_clock_mhz"]
    summary = {}
    for size, distribution in buckets.items():
        for layout, counts in distribution.items():
            assert int(counts.sum()) == signs["summary"][str(size)][layout]["external_line_reads"]
        outcomes = []
        for threshold in range(BUCKETS + 1):
            per_layout = {}
            for layout, counts in distribution.items():
                # Both lanes account for one request cycle and one response per sign miss.
                reads = [int(counts[:threshold].sum()), int(counts[threshold:].sum())]
                per_layout[layout] = [cycles + 2 * count for cycles, count in zip(weight_cycles, reads, strict=True)]
            outcomes.append((max(max(lanes) for lanes in per_layout.values()), threshold, per_layout))
        worst, threshold, per_layout = min(outcomes)
        summary[size] = {
            "send_to_primary_when_bucket_below": threshold, "lane_cycles_by_layout": per_layout,
            "worst_port_service_ms": worst / frequency, "remaining_cycles_on_busiest_port": target - worst,
            "bucket_counts_by_layout": {layout: counts.tolist() for layout, counts in distribution.items()},
        }
    assert all(sha256(ROOT / path) == digest for path, digest in pins.items())
    pins[str(replay_path.relative_to(ROOT))] = sha256(replay_path)
    result = {
        "state": "dual_port_packed_sign_steering_budget_measured_on_local_trace",
        "weight_by_phase_and_lane": weight_counts, "weight_cycles_by_lane": weight_cycles,
        "summary": summary, "paper_latency_cycle_budget": target, "peak_gpu_bytes": replay["peak_gpu_bytes"],
        "scope": "Exact reconstructed weight and sign schedules with zero cross-frame weight reuse. Models a shared "
                 "sign cache and fixed steering across two serialized memory ports. Counts port service cycles only. "
                 "Compute, all other traffic and controller stalls require separate measurement.",
        "evidence_sha256": pins,
    }
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], {size: (row["send_to_primary_when_bucket_below"], row["worst_port_service_ms"])
                            for size, row in summary.items()}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
