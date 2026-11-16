"""Compare sign-only and magnitude-weighted sign predictors at a fixed high skip count."""

import argparse
import json
from pathlib import Path
import runpy
import sys

import torch

from measure_tri_oracle_serial_memory_requests import replace
from verify_tri_oracle_late_down_precision import ROOT, digest


PARENT = ROOT / "syn/evaluate_tri_oracle_same_count_mask.py"
PARENT_RESULT = ROOT / "records/tri_oracle_prompt_mask_rates.json"
MODES = ("high_rate_magnitude", "high_rate_calibrated_sign", "high_rate_weighted_sign")


def weighted_sign_margins(norm, gate_sign, up_sign):
    """Reduce signed two-bit activation levels against the existing weight signs.

    norm [M,H] is the original signed16 prediction input. M indexes retained
    prompt rows and H indexes hidden features. The two weight-sign arrays
    [K,H] index the intermediate channels K and use signed values of +/-1.
    Return gate margin [M,K], absolute up margin [M,K], and scale [M].
    """
    from tri_oracle_integer_reference import _dot

    magnitude = norm.to(torch.int32).abs()  # [M,H], widen before taking abs(-32768)
    selected = magnitude > 768  # [M,H], preserve the original outlier detector
    # The outlier levels increment at four and five standard deviations.
    level = (((magnitude - 769).clamp_min(0) >> 8) + 1).clamp_max(3) * selected  # [M,H]
    signed = torch.where(norm < 0, -level, level).to(torch.int8)  # [M,H], signed levels for sign reduction
    gate = _dot(signed, gate_sign)  # [M,K], exact weighted matching minus mismatching mass
    up = _dot(signed, up_sign).abs()  # [M,K], absolute weighted up margin
    mass = level.sum(1, dtype=torch.int32)  # [M], row mass normalizes the joint bins
    return gate, up, mass


def generated():
    """Patch only the scoring and calibration branches of the pinned replay."""
    expected = json.loads(PARENT_RESULT.read_text())["evidence_sha256"][str(PARENT.relative_to(ROOT))]
    assert digest(PARENT) == expected
    source = PARENT.read_text()
    source = replace(source, "from evaluate_tri_oracle_prompt_arithmetic import",
                     "from evaluate_tri_oracle_weighted_sign_mask import weighted_sign_margins\n"
                     "from evaluate_tri_oracle_prompt_arithmetic import")
    source = replace(source, 'MODES = ("activation_oracle", "calibrated_sign_rank", "high_rate_magnitude")',
                     f"MODES = {MODES!r}")
    source = replace(source, '        if mode == "fit":\n',
                     '''        if mode in ("fit", "high_rate_weighted_sign"):
            weighted_gate, weighted_up, weighted_mass = weighted_sign_margins(
                norm, item.reference.gate_sign, item.reference.up_sign)  # [M,K], [M,K], [M]
        if mode == "fit":
''')
    start = source.index("            bins = bin_index(gate[shape_region]")
    end = source.index("            return raw, ordinary, stats\n", start)
    original = source[start:end]
    source = replace(source, original, '''            valid = (sample_n[:, None] > 0).expand_as(signal).flatten()  # [S*C]
            target = target.flatten()[valid]  # [V], independent label-free magnitude target
            for variant, (input_gate, input_up, mass) in enumerate(
                    ((gate, up, n), (weighted_gate, weighted_up, weighted_mass))):
                regions = bin_index(input_gate[shape_region], input_up[shape_region], mass[::8])
                indices = regions.long().flatten()[valid]  # [V], sign-bin identifiers
                context["bin_sums"][variant, index].scatter_add_(0, indices, target)
                context["bin_counts"][variant, index].scatter_add_(0, indices, TORCH.ones_like(indices))
''')
    start = source.index('        if mode in ("activation_oracle", "high_rate_magnitude"):')
    end = source.index("        budget = skip.sum", start)
    source = replace(source, source[start:end], '''        if mode == "high_rate_magnitude":
            score = products.abs()  # [M,K], after-compute diagnostic
        elif mode == "high_rate_calibrated_sign":
            bins = bin_index(gate, up, n).long()  # [M,K], original sign-only features
            score = context["rank_table"][0, index][bins].to(TORCH.int32) * 8193 + up  # [M,K]
        elif mode == "high_rate_weighted_sign":
            bins = bin_index(weighted_gate, weighted_up, weighted_mass).long()  # [M,K]
            score = context["rank_table"][1, index][bins].to(TORCH.int32) * 8193 + weighted_up  # [M,K]
        else:
            assert mode == "check_reconstruction"
            score = None

''')
    source = replace(source, 'if mode == "high_rate_magnitude" and not first:',
                     'if mode in MODES and not first:')
    source = replace(source, 'TORCH.zeros((LAYERS, CELLS), dtype=TORCH.int64, device="cuda")',
                     'TORCH.zeros((2, LAYERS, CELLS), dtype=TORCH.int64, device="cuda")')
    source = replace(source, '# [L,B] integer totals, where L is layer and B is the joint sign bin.',
                     '# [2,L,B] totals for unweighted and weighted scores, by layer and sign bin.')
    source = replace(source, '''        totals = samples.sum(0)  # [B], pooled bin counts
        pooled = TORCH.where(totals > 0, sums.sum(0) / totals.clamp_min(1), 4095.0)  # [B], prior mean
        average = (sums + pooled[None, :] * 32) / (samples + 32)  # [L,B], shrink sparse bins
        ranks = TORCH.argsort(average, dim=1, stable=True)  # [L,B], bins ordered by mean magnitude
        table = TORCH.empty_like(ranks).scatter_(1, ranks, TORCH.arange(CELLS, device="cuda").expand_as(ranks))
        context["rank_table"] = table  # [L,B], usable as a sign-score lookup''', '''        totals = samples.sum(1)  # [2,B], pooled bin counts
        pooled = TORCH.where(totals > 0, sums.sum(1) / totals.clamp_min(1), 4095.0)  # [2,B]
        average = (sums + pooled[:, None, :] * 32) / (samples + 32)  # [2,L,B]
        ranks = TORCH.argsort(average, dim=2, stable=True)  # [2,L,B]
        table = TORCH.empty_like(ranks).scatter_(2, ranks, TORCH.arange(CELLS, device="cuda").expand_as(ranks))
        context["rank_table"] = table  # [2,L,B], frozen sign-score tables''')
    source = replace(source, '"calibration_entries": int(samples.sum()),',
                     '"calibration_entries": samples.sum((1, 2)).tolist(),')
    source = replace(source, '"same_count_prompt_masks_host_panel_completed"',
                     '"high_rate_weighted_sign_host_panel_completed"')
    source = source.replace("SAME_COUNT_", "WEIGHTED_SIGN_")
    return source


def run(out):
    source = out / "paired_runner.py"
    content = generated()
    out.mkdir(parents=True, exist_ok=True)
    if source.exists():
        assert source.read_text() == content
    else:
        source.write_text(content)
    argv = sys.argv
    try:
        sys.argv = [str(source), str(out)]
        runpy.run_path(str(source), run_name="__main__")
    finally:
        sys.argv = argv


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=lambda name: Path(name).resolve())
    options = parser.parse_args()
    assert __debug__ and not Path("/.dockerenv").exists()
    assert Path.cwd() == ROOT and options.out.is_relative_to(ROOT / ".cache")
    run(options.out)
