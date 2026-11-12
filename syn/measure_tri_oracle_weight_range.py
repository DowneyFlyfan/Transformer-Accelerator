"""Fit signed-eight-bit gate and up weight ranges on archived prompt rows."""

import argparse
from copy import copy
import inspect
from itertools import product
import json
from pathlib import Path
import time

from safetensors import safe_open
import torch

from measure_tri_oracle_input_equalization import CACHE, GIB, HIDDEN, LAYERS, host_available, read
from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import IntegerFeedForwardReference, _quantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


OFFSETS = (0, -1, -2)


def codes_at(weight, exponent):
    """Quantize trained gate or up weights [K,H] at one scalar exponent.

    K is the feed-forward width and H is the hidden width. Scaled units,
    rounded units, and resulting signed-eight-bit codes all have [K,H].
    """
    power = torch.tensor(-exponent, dtype=torch.int32, device=weight.device)  # Scalar exponent from calibration.
    units = torch.ldexp(weight, power)  # [K,H], unrounded code units.
    rounded = units.sign() * torch.floor(units.abs() + 0.5)  # [K,H], ties away from zero.
    clipped = int(((rounded < -128) | (rounded > 127)).sum())
    return rounded.clamp(-128, 127).to(torch.int8).contiguous(), clipped


def error(reference, capture, policy, prune):
    """Evaluate one frozen weight range on captured prompt rows [M,H]."""
    activation, residual, expected = capture  # [M,H] normalized input, raw residual, and floating target.
    _, actual, stats = evaluate_policy(reference, activation, residual, policy, prune=prune)  # Output [M,H].
    norms = expected.double().norm(dim=1).clamp_min(1e-20)  # [M], one denominator per row.
    relative = (actual.double() - expected.double()).norm(dim=1) / norms  # [M].
    assert bool(torch.isfinite(relative).all())
    return float(relative.mean()), stats["skip_count"]  # Scalar mean and per-row [M] predicted skips.


def fit_layer(weights, fit, held, policy, epsilon):
    """Select on the fit split, then replay the winner on held prompt rows [M,H]."""
    gate, up, down = weights  # Trained gate/up [K,H], down [H,K].
    baseline = IntegerFeedForwardReference(gate, up, down, epsilon)
    baseline.down, powers = _quantize(down, per_row=True)  # Down codes [H,K] and exponents [H,1].
    baseline.down_exponent = powers.T  # [1,H], broadcast over rows.
    gate_ranges = {offset: codes_at(gate, baseline.gate_exponent + offset) for offset in OFFSETS}
    up_ranges = {offset: codes_at(up, baseline.up_exponent + offset) for offset in OFFSETS}
    assert torch.equal(gate_ranges[0][0], baseline.gate) and gate_ranges[0][1] == 0
    assert torch.equal(up_ranges[0][0], baseline.up) and up_ranges[0][1] == 0
    initial, fit_skips = error(baseline, fit, policy, True)  # Scalar error and [M] skip counts.
    best, selected, winner = initial, (0, 0), baseline
    scores = []
    for gate_offset, up_offset in product(OFFSETS, repeat=2):
        candidate = copy(baseline)  # Shares original signs, activation policy and down weights.
        candidate.gate, candidate.up = gate_ranges[gate_offset][0], up_ranges[up_offset][0]  # Both [K,H].
        candidate.gate_exponent += gate_offset
        candidate.up_exponent += up_offset
        measured, skips = error(candidate, fit, policy, True)  # Scalar error and [M] skip counts.
        assert torch.equal(skips, fit_skips)
        scores.append({"offsets": [gate_offset, up_offset], "mean_relative_error": measured})
        if measured < best:
            best, selected, winner = measured, (gate_offset, up_offset), candidate
    assert scores[0]["mean_relative_error"] == initial
    results = {}
    for mode, prune in (("dense", False), ("pruned", True)):
        original, old_skips = error(baseline, held, policy, prune)  # Scalar error and [M] skip counts.
        revised, new_skips = error(winner, held, policy, prune)  # Scalar error and [M] skip counts.
        assert torch.equal(old_skips, new_skips)
        results[mode] = {"baseline": original, "calibrated": revised, "predicted_skips": int(old_skips.sum())}
    return {"selected_offsets": selected, "fit_pruned_candidates": scores, "held": results,
            "clipped_weights": {"gate": gate_ranges[selected[0]][1], "up": up_ranges[selected[1]][1]}}


@torch.inference_mode()
def run(output):
    started = time.monotonic()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.set_float32_matmul_precision("highest")
    assert host_available() >= 16 * GIB and torch.cuda.mem_get_info()[0] >= 8 * GIB
    torch.cuda.set_per_process_memory_fraction(0.125)
    torch.cuda.reset_peak_memory_stats()
    model = CACHE / "tiny_llava_v1"
    capture = ROOT / "records/format320_multi_image_range_audit.json"
    reference = CACHE / "ff_quantization_sources_channel_scaled/receipt.json"
    metadata, prior = read(capture), read(reference)
    assert metadata["checkpoint_revision"] == prior["checkpoint_revision"] and metadata["labels_used"] is False
    assert [case["split"] for case in metadata["inputs"]] == ["calibration"] * 8 + ["held"] * 8
    assert len({case["image_pixel_sha256"] for case in metadata["inputs"]}) == 16
    assert all(len(case["selected_token_positions"]) == 16 and case["selected_token_positions"][0] == 0
               for case in metadata["inputs"])
    rows = CACHE / "format320/captured_rows.pt"
    policy = CACHE / "format335/layer_policy.json"
    config, manifest = model / "config.json", model / "model.safetensors.index.json"
    mapping = read(manifest)["weight_map"]
    shards = {model / name for name in mapping.values()}
    pins = {str(path): sha256(path) for path in (rows, policy, config, manifest, *shards)}
    assert all(prior["input_sha256"][name] == digest for name, digest in pins.items())
    for file in (capture, reference, Path(__file__).resolve(), Path(evaluate_policy.__code__.co_filename),
                 Path(inspect.getfile(IntegerFeedForwardReference)), Path(host_available.__code__.co_filename)):
        pins[str(file)] = sha256(file)
    captures = torch.load(rows, map_location="cpu", weights_only=True, mmap=True)  # Per-layer tensors [256,H].
    policies = read(policy)["layers"]
    assert len(captures) == len(policies) == LAYERS
    epsilon = read(config)["text_config"]["rms_norm_eps"]
    splits = [[row for row in range(start, start + 128) if row % 16] for start in (0, 128)]
    layers = []
    for layer, (data, settings) in enumerate(zip(captures, policies, strict=True)):
        assert host_available() >= 15 * GIB
        weights = []
        for kind in ("gate", "up", "down"):
            key, = (name for name in mapping if name.endswith(f".layers.{layer}.mlp.{kind}_proj.weight"))
            with safe_open(model / mapping[key], framework="pt", device="cpu") as shard:
                weights.append(shard.get_tensor(key).to(device="cuda", dtype=torch.float32))  # [K,H] or [H,K].
        fit, held = (tuple(data[name][indices].to(device="cuda", dtype=torch.float32)
                           for name in ("activation", "residual", "target")) for indices in splits)  # [120,H] each.
        assert all(item.shape == (120, HIDDEN) for subset in (fit, held) for item in subset)
        result = fit_layer(weights, fit, held, settings, epsilon)
        layers.append({"layer": layer, **result})
        print("WEIGHT_RANGE_LAYER", layer, result["selected_offsets"], result["held"]["pruned"], flush=True)
        del weights, fit, held
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    summary = {mode: {label: sum(item["held"][mode][label] for item in layers) / LAYERS
                      for label in ("baseline", "calibrated")} for mode in ("dense", "pruned")}
    report = {"state": "gate_up_weight_ranges_fit_and_replayed_on_held_prompt_rows",
              "checkpoint_revision": metadata["checkpoint_revision"], "layers": layers, "held_summary": summary,
              "rows_per_split_per_layer": 120, "fit_images": 8, "held_images": 8,
              "peak_gpu_bytes": torch.cuda.max_memory_allocated(), "seconds": time.monotonic() - started,
              "input_sha256": pins}
    with output.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(report["state"], summary, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
