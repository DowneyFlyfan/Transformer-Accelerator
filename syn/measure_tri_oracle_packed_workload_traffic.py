"""Count current packed weight transfers on the pinned 600/60 model trace."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

# Keep the attention backend used by the verified local benchmarks.
sys.modules["kernels"] = None
import evaluate_tri_oracle_batch424_joint_pilot as joint
import run_tri_oracle_normalized_workload_trace as trace
import tri_oracle_integer_reference as integer
from audit_tri_oracle_packed_weight_traffic import read_rows
from verify_tri_oracle_packed_down_weights import ROOT, sha256


DATA = ROOT / ".cache/model_reference"
ARCHIVE = DATA / "normalized_workload_trace/receipt.json"
PREFILL_GROUPS = (1, 4, 8, 16)
HIDDEN, CHANNELS = 2048, 5632
RESPONSE_BYTES = 64
WORD_BYTES = 8


def packed_counts(active, size):
    """Count used eight-element words per group from active features [R,F]."""
    rows, features = active.shape
    assert rows > 0 and features % WORD_BYTES == 0
    padded = trace.torch.nn.functional.pad(active, (0, 0, 0, (-rows) % size))  # [G*size,F], zero tail rows.
    words = padded.reshape(-1, size, features // WORD_BYTES, WORD_BYTES)  # [G,size,F/8,8].
    return words.any(dim=3).any(dim=1).sum(dim=1)  # [G], one word count per group.


def group_traffic(activation, keep, dense_down, pruned_down, size):
    """Project transport from activation [R,H] and channel matrices [R,K]."""
    assert activation.shape[1] == HIDDEN and keep.shape[1] == CHANNELS
    activation_words = packed_counts(activation.ne(0), size)  # [G], active input words for gate/up.
    gate_groups = packed_counts(keep, size)  # [G], retained groups of eight output rows.
    dense_down_words = packed_counts(dense_down.ne(0), size)  # [G], active input words before prediction.
    pruned_down_words = packed_counts(pruned_down.ne(0), size)  # [G], active input words after prediction.
    assert bool((pruned_down_words <= dense_down_words).all())
    return Counter(
        no_predictor_gate_up_bytes=2 * RESPONSE_BYTES * (CHANNELS // WORD_BYTES) * int(activation_words.sum()),
        predictor_gate_up_bytes=2 * RESPONSE_BYTES * int((activation_words * gate_groups).sum()),
        no_predictor_down_bytes=RESPONSE_BYTES * (HIDDEN // WORD_BYTES) * int(dense_down_words.sum()),
        predictor_down_bytes=RESPONSE_BYTES * (HIDDEN // WORD_BYTES) * int(pruned_down_words.sum()),
    )


def grouped_row_indices(exponents, offset):
    """Recover policy evaluation row order from per-row input exponents [R]."""
    first = 1 if offset == 0 else 0
    if first:
        yield trace.torch.zeros(1, dtype=trace.torch.long, device=exponents.device)  # [1], protected first prompt row.
    ordinary = exponents[first:]  # [R-first], later rows evaluated by exponent bucket.
    for value in sorted(set(ordinary.tolist())):
        yield trace.torch.nonzero(ordinary == value, as_tuple=True)[0] + first  # [B], original indices for one bucket.


def reconstruct(reference, activation, stats):
    """Reconstruct exact inputs to the down projection from activation [R,H]."""
    torch = trace.torch
    codes, exponents = integer._quantize(activation, per_row=True)  # [R,H] signed8, [R,1] powers.
    norms = stats["norm_codes"]  # [R,H], raw residual after prediction normalization.
    outliers = norms.abs() > 768  # [R,H], strict three-sigma threshold.
    signs = (torch.where(norms < 0, -1, 1) * outliers).to(torch.int8)  # [R,H], signed outlier indicators.
    gate_margin = integer._dot(signs, reference.gate_sign)  # [R,K], signed match differences.
    up_margin = integer._dot(signs, reference.up_sign)  # [R,K], signed match differences.
    skip = outliers.any(dim=1, keepdim=True) & gate_margin.le(0) & up_margin.eq(0)  # [R,K], branch intersection.
    assert torch.equal(skip.sum(dim=1), stats["skip_count"])
    gate = integer._requantize(integer._dot(codes, reference.gate), stats["gate_shift"][:, None], 16)  # [R,K].
    up = integer._requantize(integer._dot(codes, reference.up), stats["up_shift"][:, None], 16)  # [R,K].
    gated = integer._requantize(reference.silu_response[gate + 32768] * up,
                                torch.full_like(stats["down_shift"][:, None], 8), 16)  # [R,K].
    dense = integer._requantize(gated, stats["down_shift"][:, None], 8).to(torch.int8)  # [R,K], before prediction.
    pruned = dense.masked_fill(skip, 0)  # [R,K], actual down input.
    sign_bytes = int(outliers.reshape(-1, HIDDEN // 2, 2).any(dim=2).sum()) * (CHANNELS // 32) * 2 * 8
    return codes, exponents[:, 0], skip, dense, pruned, sign_bytes


def verify_traffic_control():
    """Check the packing model against the previously measured native frame."""
    torch = trace.torch
    record = ROOT / "records/wac_packed_trained_weight_traffic_result.json"
    proof = trace.read(record)
    assert proof["state"] == "packed_trained_frame_weight_traffic_reconstructed_exactly"
    tensors = []
    for file, columns in (("batch403/activation.hex", HIDDEN), ("batch389/keep.hex", CHANNELS),
                          ("batch407/intermediate.hex", CHANNELS)):
        path = DATA / file
        assert sha256(path) == proof["evidence_sha256"][str(path.relative_to(ROOT))]
        tensors.append(torch.tensor(read_rows(path, columns)).ne(0))  # [16,H] or [16,K], nonzero flags.
    activation, keep, down = tensors
    measured = group_traffic(activation, keep, down, down, 16)
    assert measured["predictor_gate_up_bytes"] + measured["predictor_down_bytes"] == proof["weight_bytes"]
    return record


def run(output):
    started = time.monotonic()
    output.mkdir()
    traffic_control = verify_traffic_control()
    history = ROOT / "records/wac_unified_decode_read_budget_result.json"
    assert sha256(ARCHIVE) == trace.read(history)["evidence_sha256"][str(ARCHIVE.relative_to(ROOT))]
    archived = trace.read(ARCHIVE)
    traffic = {str(size): Counter() for size in PREFILL_GROUPS}
    decode_traffic = Counter()
    layers = [{"prefill": None, "decode_calls": 0, "decode_skipped": 0} for _ in range(22)]
    references = {}
    captured = None
    original_install, original_dot = trace.install_channel_scaling, integer._dot
    original_evaluate, original_memory = joint.evaluate_protected, trace.check_memory

    def check_memory(reserve):
        available = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                         if line.startswith("MemAvailable:"))
        anonymous = next(int(line.split()[1]) for line in Path("/sys/fs/cgroup/memory.stat").read_text().splitlines()
                         if line.startswith("anon "))
        minimum = 16 if reserve >= 16 * trace.GIB else 15
        assert available >= minimum * trace.GIB and anonymous < 2.5 * trace.GIB, (available, anonymous)

    def install(replacement, index, weight, context):
        # Checkpoint down weights have shape [H,K] and are used by the existing installer.
        references[id(replacement.reference)] = index
        return original_install(replacement, index, weight, context)

    def dot(left, right):
        # The actual down projection receives integer input [B,K] and weights [H,K].
        if captured is not None and left.shape[1] == CHANNELS:
            assert right.shape == (HIDDEN, CHANNELS)
            captured.append(left)
        return original_dot(left, right)

    def evaluate(reference, activation, residual, ordinary, first, offset, *, prune):
        # Model inputs are normalized activation and raw residual [R,H].
        nonlocal captured
        if not prune:
            return original_evaluate(reference, activation, residual, ordinary, first, offset, prune=False)
        assert captured is None
        down_groups = []  # Ordered actual [B,K] arrays from the existing fixed-point policy.
        captured = down_groups
        try:
            result = original_evaluate(reference, activation, residual, ordinary, first, offset, prune=True)
        finally:
            captured = None
        codes, exponents, skip, dense, pruned, sign_bytes = reconstruct(reference, activation, result[2])
        for actual, indices in zip(down_groups, grouped_row_indices(exponents, offset), strict=True):
            assert trace.torch.equal(actual, pruned.index_select(0, indices))
        row = layers[references[id(reference)]]
        if offset == 0:
            assert row["prefill"] is None
            row["prefill"] = {"rows": len(codes), "predicted_skipped": int(skip.sum())}
            for size in PREFILL_GROUPS:
                traffic[str(size)].update(group_traffic(codes, ~skip, dense, pruned, size))
                traffic[str(size)]["sign_bytes"] += sign_bytes
        else:
            assert len(codes) == 1 and offset == archived["prefill_tokens"] + row["decode_calls"]
            row["decode_calls"] += 1
            row["decode_skipped"] += int(skip.sum())
            decode_traffic.update(group_traffic(codes, ~skip, dense, pruned, 1))
            decode_traffic["sign_bytes"] += sign_bytes
        return result

    trace.install_channel_scaling, trace.check_memory = install, check_memory
    joint.evaluate_protected, integer._dot = evaluate, dot
    try:
        trace.run(output)
    finally:
        trace.install_channel_scaling, trace.check_memory = original_install, original_memory
        joint.evaluate_protected, integer._dot = original_evaluate, original_dot
    replay = output / "receipt.json"
    actual = trace.read(replay)
    for name in ("state", "checkpoint_revision", "prefill_tokens", "decode_steps", "forced_tokens", "channels", "layers"):
        assert actual[name] == archived[name], name
    for observed, expected in zip(layers, archived["layers"]["compact_streaming_pruned"], strict=True):
        assert observed["prefill"] == {"rows": expected["prefill_rows"], "predicted_skipped": expected["prefill_skipped"]}
        assert observed["decode_calls"] == expected["decode_rows"] and observed["decode_skipped"] == expected["decode_skipped"]
    evidence = (traffic_control, history, ARCHIVE, replay, Path(trace.__file__).resolve(),
                Path(integer.__file__).resolve(), Path(__file__).resolve())
    report = {"state": "packed_traffic_projected_from_exact_normalized_workload_trace",
              "prefill_tokens": archived["prefill_tokens"], "decode_steps": archived["decode_steps"],
              "prefill_by_batch_size": traffic, "decode": decode_traffic, "layers": layers,
              "native_seconds": time.monotonic() - started, "peak_gpu_bytes": actual["graphics_peak_bytes"],
              "evidence_sha256": {str(file.relative_to(ROOT)): sha256(file) for file in evidence},
              "scope": "Software replay with exact integer transport inputs. Predictor-off traffic holds the pruned activation trajectory fixed."}
    (output / "packed_traffic.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report["state"], dict(traffic["16"]), dict(decode_traffic), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
