"""Separate late down-input clipping from rounding on the paired answer panel."""

import argparse
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import evaluate_tri_oracle_late_down_quantization as separate
import evaluate_tri_oracle_late_prefill_projections as prior
from tri_oracle_integer_reference import _dot, _requantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


torch = prior.torch
MODES = ("unclipped_rounded", "clipped_unrounded", "bounded_clip_correction")
COUNTS = {mode: Counter() for mode in MODES}


def exact_overflow_dot(delta, weights):
    """Accumulate a [M,K] signed overflow using signed8 digit planes and [H,K] weights."""
    magnitude = delta.abs()  # [M,K], overflow of the rounded down operand
    sign = delta.sign()  # [M,K], −1, 0 or +1
    raw = None
    for offset in (0, 7, 14):
        digit = (((magnitude >> offset) & 127) * sign).to(torch.int8)  # [M,K], exact signed8 plane
        partial = _dot(digit, weights).to(torch.int64) << offset  # [M,H], aligned exact sum
        raw = partial if raw is None else raw + partial
    return raw


def project(reference, projections, activation, stats, mode):
    """Keep the same signed16 gated inputs and checkpoint weights for each arm."""
    gated = prior.gated_codes(reference, activation, stats)  # [M,K], existing gated code format
    gain = stats["up_gain_bits"][:, None]  # [M,1], existing up gain
    shift = stats["down_shift"][:, None]  # [M,1], configured down shift
    wide = _requantize(gated, shift, 16)  # [M,K], rounded before narrowing to signed8
    coarse = wide.clamp(-128, 127)  # [M,K], original clipped operand
    delta = wide - coarse  # [M,K], exact integer overflow
    bounded = delta.clamp(-128, 127)  # [M,K], one signed8 correction operand
    changed = delta.ne(0)  # [M,K], true only for clipped codes
    counters = COUNTS[mode]
    counters.update(rows=gated.shape[0], codes=gated.numel(), clipped_codes=int(changed.sum()),
                    rows_with_clipping=int(changed.any(dim=1).sum()),
                    correction_outside_signed8=int((bounded != delta).sum()))
    counters["maximum_abs_overflow"] = max(counters["maximum_abs_overflow"], int(delta.abs().max()))
    if mode == "clipped_unrounded":
        # Restore original signed16 values wherever rounding did not force saturation.
        restored = torch.where(changed, coarse << shift, gated)  # [M,K], values in original gated units
        inputs = torch.ldexp(restored.float(), -8 - gain)  # [M,K] physical input
        outputs = torch.nn.functional.linear(inputs, separate.floating_codes(reference))  # [M,H]
        scale_exp = torch.zeros_like(gain) + reference.down_exponent  # [M,1] or [M,H]
        return torch.ldexp(outputs, scale_exp)

    base = _dot(coarse.to(torch.int8), reference.down).to(torch.int64)  # [M,H] current signed8 array pass
    correction = (
        exact_overflow_dot(delta, reference.down) if mode == "unclipped_rounded"
        else _dot(bounded.to(torch.int8), reference.down).to(torch.int64)
    )  # [M,H] aligned additive correction
    return torch.ldexp((base + correction).float(), reference.down_exponent + shift - 8 - gain)


def prepare():
    dataset, labels, panel, controls, pins = separate.prepare()
    proof_path = ROOT / "records/tri_oracle_late_down_quantization.json"
    proof = prior.benchmark.read(proof_path)
    assert proof["state"] == "paired_late_down_quantization_independently_verified"
    assert proof["integer_control_correct"] == 89 and proof["projection_results"]["floating_input"]["correct"] == 95
    earlier = ROOT / ".cache/model_reference/gqa_testdev/late_down_quantization"
    for name in ("inputs.json", "predictions.jsonl", "receipt.json"):
        path = earlier / name
        checksum = sha256(path)
        assert checksum == proof["evidence_sha256"][str(path.relative_to(ROOT))]
        assert pins.setdefault(str(path), checksum) == checksum
    assert prior.benchmark.read(earlier / "inputs.json")["panel"] == panel
    for path in (proof_path, Path(__file__).resolve(), Path(separate.__file__).resolve()):
        checksum = sha256(path)
        assert pins.setdefault(str(path), checksum) == checksum
    return dataset, labels, panel, controls, pins


def run(output):
    with patch.multiple(prior, prepare=prepare, project=project, MODES=MODES):
        prior.run(output)
    assert all(0 <= counts["correction_outside_signed8"] <= counts["clipped_codes"] <= counts["codes"]
               for counts in COUNTS.values())
    prior.benchmark.write(output / "clipping_counts.json", COUNTS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.output.resolve())
