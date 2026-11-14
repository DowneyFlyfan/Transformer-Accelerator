"""Bound weight savings from the applied skip masks on the archived workload."""

from decimal import Decimal
from hashlib import file_digest, sha256
import json
from pathlib import Path


TRACE = Path(".cache/model_reference/normalized_workload_trace/receipt.json")
TRAFFIC = Path(".cache/model_reference/packed_workload_traffic_v1/packed_traffic.json")
TRACE_AUDIT = Path("records/normalized_workload_trace_result.json")
TRAFFIC_AUDIT = Path("records/wac_packed_workload_traffic_result.json")
TARGETS = Path("records/paper_result_targets.json")
HIDDEN = 2048
PHASES = ("prefill", "decode")


def sha(path):
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def read(path, evidence=None):
    raw = path.read_bytes()
    if evidence is not None and sha256(raw).hexdigest() != evidence[str(path)]:
        raise ValueError(f"Changed archive input: {path}")
    return json.loads(raw)


def full_channel_bound(rows, skips, channels, batch_size):
    """Spend skips on the short batch first, then on full batches."""
    if min(rows, channels, batch_size) <= 0 or not 0 <= skips <= rows * channels:
        raise ValueError("Invalid skip counts or batch geometry")
    full, tail = divmod(rows, batch_size)
    tail_channels = min(channels, skips // tail) if tail else 0
    return full + bool(tail), tail_channels + (skips - tail_channels * tail) // batch_size


def percent(numerator, denominator):
    return str((Decimal(100) * numerator / denominator).quantize(Decimal("0.000001")))


def audit():
    if not __debug__:
        raise RuntimeError("Run the workload audit with Python assertions enabled")
    trace_audit = read(TRACE_AUDIT)
    traffic_audit = read(TRAFFIC_AUDIT)
    trace = read(TRACE, trace_audit["evidence_sha256"])
    traffic = read(TRAFFIC, traffic_audit["evidence_sha256"])
    target = read(TARGETS, traffic_audit["evidence_sha256"])
    policy = "compact_streaming_pruned"
    layers = trace["layers"][policy]
    channels = trace["channels"]
    assert len(layers) == len(traffic["layers"]) == trace_audit["layers"] == 22
    assert channels == trace_audit["channels_per_row"] == 5632
    assert trace["checkpoint_revision"] == trace_audit["checkpoint_revision"]
    assert trace["prefill_tokens"] == target["energy_point"]["input_prefill_tokens"]
    assert trace["decode_steps"] == target["energy_point"]["output_decode_tokens"]
    for index, (layer, transfer) in enumerate(zip(layers, traffic["layers"], strict=True)):
        assert layer["layer"] == index
        assert transfer["prefill"] == {"rows": layer["prefill_rows"], "predicted_skipped": layer["prefill_skipped"]}
        assert transfer["decode_skipped"] == layer["decode_skipped"]
        assert transfer["decode_calls"] == layer["decode_rows"] == trace["decode_steps"]
        for phase in PHASES:
            assert 0 <= layer[f"{phase}_skipped"] == layer[f"{phase}_predicted"] <= layer[f"{phase}_rows"] * channels

    totals = {f"{phase}_{field}": sum(layer[f"{phase}_{field}"] for layer in layers)
              for phase in PHASES for field in ("rows", "skipped")}
    assert all(value == trace_audit["totals"][policy][key] for key, value in totals.items())
    skips = totals["prefill_skipped"] + totals["decode_skipped"]
    dense_channel_scenarios = {}
    for size in (1, 4, 8, 16):
        available, removed = 0, 0
        for layer in layers:
            for phase in PHASES:
                batches, removed_channels = full_channel_bound(layer[f"{phase}_rows"], layer[f"{phase}_skipped"],
                                                                channels, size if phase == "prefill" else 1)
                available += batches * channels
                removed += removed_channels
        dense_channel_scenarios[str(size)] = {"batch_channels": available, "max_removed_batch_channels": removed,
                                              "max_percent": percent(removed, available)}
    packed = traffic_audit["combined_sixteen_row_prefill_and_single_row_decode"]
    terms = (traffic["prefill_by_batch_size"]["16"], traffic["decode"])
    weight_baseline = sum(row[key] for row in terms for key in ("no_predictor_gate_up_bytes", "no_predictor_down_bytes"))
    sign_payload = sum(row["sign_bytes"] for row in terms)
    assert weight_baseline == packed["without_predictor_weight_bytes"] and sign_payload == packed["sign_bytes"]
    # For gate and up, the existing scheduler keeps every output channel used
    # by any token in the batch. An omitted channel saves at most HIDDEN bytes
    # per matrix. For down, an omitted input channel can already be zero for
    # other tokens, so charge a full column to every pruned token-channel pair.
    # This overcounts shared columns and ignores response granularity.
    gate_up_upper = dense_channel_scenarios["16"]["max_removed_batch_channels"] * 2 * HIDDEN
    down_upper = skips * HIDDEN
    upper = gate_up_upper + down_upper
    with_predictor = sum(row[key] for row in terms for key in ("predictor_gate_up_bytes", "predictor_down_bytes"))
    assert with_predictor == packed["with_predictor_weight_bytes"]
    paper_reduction = target["disclosed_method_gains"]["feed_forward_external_memory_access_reduction_percent"]
    return {
        "state": "applied_weight_skip_masks_cannot_reach_target_with_packing_alone_on_local_trace",
        "checkpoint_revision": trace["checkpoint_revision"], "prefill_tokens": trace["prefill_tokens"],
        "decode_steps": trace["decode_steps"], "layers": len(layers),
        "hidden_features": HIDDEN, "channels": channels, **totals,
        "skip_mask_percent": {phase: percent(totals[f"{phase}_skipped"], totals[f"{phase}_rows"] * channels)
                              for phase in PHASES},
        "dense_whole_channel_fetch_scenarios": dense_channel_scenarios,
        "packed_predictor_off_weight_baseline_bytes": weight_baseline,
        "packed_predictor_sign_bytes": sign_payload,
        "packed_projected_percent_saving_at_observed_sign_cost":
            percent(weight_baseline - with_predictor - sign_payload, weight_baseline),
        "max_eliminated_gate_and_up_weight_bytes": gate_up_upper,
        "max_eliminated_down_weight_bytes": down_upper,
        "max_weight_bytes_eliminated_by_preserving_applied_masks": upper,
        "max_percent_of_packed_baseline_saving_with_free_signs": percent(upper, weight_baseline),
        "max_percent_of_packed_baseline_saving_at_observed_sign_cost": percent(upper - sign_payload, weight_baseline),
        "paper_feedforward_external_access_reduction_percent": paper_reduction,
        "paper_target_unreachable_under_bound": 100 * upper < paper_reduction * weight_baseline,
        "scope": "One fixed local model trajectory. The bound counts only skipping from its existing masks versus its "
                 "existing dense packed baseline. Independent lossless coding, batching changes, different masks, or "
                 "different paper inputs and accounting are outside the bound.",
        "evidence_sha256": {str(path): sha(path) for path in (TRACE, TRAFFIC, TRACE_AUDIT, TRAFFIC_AUDIT,
                                                             TARGETS, Path(__file__).relative_to(Path.cwd()))},
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, sort_keys=True))
