"""Separate late down-input and weight quantization on the pinned answer panel."""

import argparse
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch

from audit_tri_oracle_down_weight_scale_resolution import linear_weight_codes
import evaluate_tri_oracle_late_prefill_projections as prior
from tri_oracle_integer_reference import _dot, _requantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


torch = prior.torch
MODES = ("floating_input", "floating_weights", "fractional_weight_scale")
MANTISSA_BITS = 15
ORIGINAL_PREPARE = prior.prepare


@lru_cache(maxsize=5)
def fractional_codes(projection):
    """Return signed8 checkpoint codes [H,K] and fixed-point scales [1,H]."""
    codes, scale = linear_weight_codes(projection.weight)["linear_absmax"]  # [H,K], [H,1]
    mantissa, exponent = torch.frexp(scale)  # [H,1] in both representations
    coefficient = torch.round(mantissa * (1 << MANTISSA_BITS)).to(torch.int32)  # [H,1]
    assert bool(((coefficient > 0) & (coefficient <= (1 << MANTISSA_BITS))).all())
    recovered = torch.ldexp(coefficient.float(), exponent - MANTISSA_BITS)  # [H,1]
    assert float(((recovered - scale).abs() / scale).max()) <= 2 ** -MANTISSA_BITS
    return codes, recovered.T


@lru_cache(maxsize=10)
def floating_codes(reference):
    """Convert unchanged signed8 weight codes [H,K] for diagnostic linear arithmetic."""
    return reference.down.float()


def project(reference, projections, activation, stats, mode):
    """Change one side of the late down projection on retained [M,H] prompt rows."""
    gated = prior.gated_codes(reference, activation, stats)  # [M,K], unchanged signed16 path
    gain = stats["up_gain_bits"][:, None]  # [M,1] existing up gain
    shift = stats["down_shift"][:, None]  # [M,1] existing configured shift
    if mode == "floating_input":
        # Keep the same quantized weights and their existing scalar or per-channel scale.
        exact_input = torch.ldexp(gated.float(), -8 - gain)  # [M,K], scaled original gated integers
        output = torch.nn.functional.linear(exact_input, floating_codes(reference))  # [M,H]
        scale_exponent = torch.zeros_like(gain) + reference.down_exponent  # [M,1] or [M,H]
        return torch.ldexp(output, scale_exponent)

    codes = _requantize(gated, shift, 8).to(torch.int8)  # [M,K], same rounded and clipped input
    exponent = shift - 8 - gain  # [M,1] physical interpretation of the signed8 codes
    if mode == "floating_weights":
        return projections.down_proj(torch.ldexp(codes.float(), exponent))  # [M,H]
    assert mode == "fractional_weight_scale"
    weights, scale = fractional_codes(projections.down_proj)  # [H,K], [1,H]
    return torch.ldexp(_dot(codes, weights).float(), exponent) * scale  # [M,H]


def prepare():
    dataset, labels, panel, controls, pins = ORIGINAL_PREPARE()
    measured = ROOT / "records/tri_oracle_late_prefill_projection_precision.json"
    report = prior.benchmark.read(measured)
    assert report["state"] == "paired_late_projection_precision_independently_verified"
    assert report["integer_control_correct"] == 89
    assert report["projection_results"]["floating_down"]["correct"] == 96
    earlier = ROOT / ".cache/model_reference/gqa_testdev/late_prefill_projections"
    assert prior.benchmark.read(earlier / "inputs.json")["panel"] == panel
    for file in ("inputs.json", "predictions.jsonl", "receipt.json"):
        path = earlier / file
        assert sha256(path) == report["evidence_sha256"][str(path.relative_to(ROOT))]
        pins[str(path)] = sha256(path)
    for path in (measured, Path(__file__).resolve(), Path(linear_weight_codes.__code__.co_filename)):
        checksum = sha256(path)
        assert pins.setdefault(str(path), checksum) == checksum
    return dataset, labels, panel, controls, pins


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    # Reuse the verified decoder and unchanged baseline controls for every arm.
    with patch.multiple(prior, prepare=prepare, project=project, MODES=MODES):
        prior.run(args.output.resolve())
