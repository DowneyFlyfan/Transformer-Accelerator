"""Bound weight savings from channel packing without changing the predictor masks."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path

from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ".cache/model_reference/normalized_workload_trace/receipt.json"
TRAFFIC = ".cache/model_reference/packed_workload_traffic_v1/packed_traffic.json"
TRAFFIC_RECORD = "records/wac_packed_workload_traffic_result.json"
TARGETS = "records/paper_result_targets.json"
HIDDEN = 2048
CHANNELS = 5632
LANES = 8
RESPONSE_BYTES = 64
PREFILL_BATCH = 16


def read(path):
    return json.loads((ROOT / path).read_text())


def sha(path):
    with (ROOT / path).open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def omitted_groups(rows, skipped, batch):
    """Each omitted eight-channel group consumes eight skips per row in its batch."""
    assert 0 <= skipped <= rows * CHANNELS
    full, tail = divmod(rows, batch)
    groups_per_batch = CHANNELS // LANES
    # Give the short batch first use of the skip budget. Its groups cost
    # fewer skips than full-batch groups and each saves at most the same bytes.
    tail_groups = min(groups_per_batch, skipped // (LANES * tail)) if tail else 0
    skipped -= tail_groups * LANES * tail
    return tail_groups + min(full * groups_per_batch, skipped // (LANES * batch))


def phase_bound(layer_rows, measured, batch):
    batches = sum((rows + batch - 1) // batch for rows, _ in layer_rows)
    max_omitted = sum(omitted_groups(rows, skipped, batch) for rows, skipped in layer_rows)
    gate_up_bytes_per_group = 2 * RESPONSE_BYTES * (HIDDEN // LANES)
    dense_gate_up = measured["no_predictor_gate_up_bytes"]
    max_gate_up_saved = min(dense_gate_up, max_omitted * gate_up_bytes_per_group)
    assert 0 <= dense_gate_up - measured["predictor_gate_up_bytes"] <= max_gate_up_saved
    # Assume a fully dense baseline, zero down reads, and free sign reads.
    # This favors the reordered candidate in both the numerator and denominator.
    max_baseline = batches * 3 * RESPONSE_BYTES * (HIDDEN // LANES) * (CHANNELS // LANES)
    assert dense_gate_up + measured["no_predictor_down_bytes"] <= max_baseline
    return {
        "batches": batches, "maximum_omitted_gate_up_channel_groups": max_omitted,
        "minimum_remaining_gate_up_bytes": dense_gate_up - max_gate_up_saved,
        "maximum_dense_baseline_bytes": max_baseline,
        "channel_positions": CHANNELS * sum(rows for rows, _ in layer_rows),
        "predicted_skipped_channels": sum(skipped for _, skipped in layer_rows),
    }


def measure():
    record = read(TRAFFIC_RECORD)
    pins = {name: sha(name) for name in (ARCHIVE, TRAFFIC, TARGETS)}
    assert all(record["evidence_sha256"][name] == digest for name, digest in pins.items())
    assert sha(PAPER_RELATIVE) == PAPER_SHA256
    pins[PAPER_RELATIVE] = PAPER_SHA256
    traffic, archive = read(TRAFFIC), read(ARCHIVE)
    prefill, decode = [], []
    for layer, pinned in zip(traffic["layers"], archive["layers"]["compact_streaming_pruned"], strict=True):
        assert layer["prefill"] == {"rows": pinned["prefill_rows"], "predicted_skipped": pinned["prefill_skipped"]}
        assert layer["decode_calls"] == pinned["decode_rows"] == record["decode_steps"]
        assert layer["decode_skipped"] == pinned["decode_skipped"]
        prefill.append((pinned["prefill_rows"], pinned["prefill_skipped"]))
        decode.append((pinned["decode_rows"], pinned["decode_skipped"]))
    assert len(prefill) == record["layers"]
    assert archive["prefill_tokens"] == traffic["prefill_tokens"] == record["prefill_tokens"]
    phases = {
        "prefill": phase_bound(prefill, traffic["prefill_by_batch_size"][str(PREFILL_BATCH)], PREFILL_BATCH),
        "decode": phase_bound(decode, traffic["decode"], 1),
    }
    combined = {key: sum(phase[key] for phase in phases.values()) for key in phases["prefill"]}
    for phase in [*phases.values(), combined]:
        phase["maximum_possible_reduction_percent"] = 100 * (
            1 - phase["minimum_remaining_gate_up_bytes"] / phase["maximum_dense_baseline_bytes"])
        phase["predicted_skipped_channels_percent"] = 100 * phase["predicted_skipped_channels"] / phase["channel_positions"]
    target = read(TARGETS)["disclosed_method_gains"]["feed_forward_external_memory_access_reduction_percent"]
    assert all(sha(path) == digest for path, digest in pins.items())
    pins[TRAFFIC_RECORD] = sha(TRAFFIC_RECORD)
    pins[str(Path(__file__).resolve().relative_to(ROOT))] = sha(Path(__file__).resolve())
    return {
        "state": "fixed_predictor_channel_packing_upper_bound_measured",
        "scope": "One pinned local 600-prefill and 60-decode trajectory. Allows any ordering of intermediate "
                 "channels within the existing batches and eight-lane transfer geometry. Holds predictor masks "
                 "and gate/up input packing fixed. Optimistically assumes no down-weight or sign reads.",
        "prefill_batch_rows": PREFILL_BATCH, "decode_batch_rows": 1,
        "paper_figure_31_6_5": {
            "predicted_channel_reduction_percent": {"VQAv2": 58, "GQA": 56},
            "gated_feedforward_external_memory_access_reduction_percent": {"VQAv2": target},
        },
        **phases, "combined": combined, "evidence_sha256": pins,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = measure()
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], result["combined"], flush=True)
