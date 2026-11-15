"""Measure signed-eight-bit activation range on separate calibration and holdout rows."""

import argparse
import json
from pathlib import Path
import time

import torch
from safetensors import safe_open

from measure_tri_oracle_input_equalization import CACHE, EXPANSION, GIB, HIDDEN, LAYERS, host_available
from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import IntegerFeedForwardReference, _quantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


EXPONENT_REDUCTIONS = (0, 1, 2)
FITTING_ROWS = 120


def read(path):
    return json.loads(path.read_text())


def limited_range(activation, reduction):
    """Clip archived activations [M,H] using a power-of-two [M,1] range.

    M counts rows and H counts normalized hidden features. A reduced row
    exponent preserves the signed-eight-bit product interface.
    """
    if reduction == 0:
        return activation, 0
    _, baseline_exponent = _quantize(activation, per_row=True)  # [M,1], from row maxima
    range_exponent = baseline_exponent - reduction  # [M,1], fixed trial reduction
    maximum = torch.ldexp(torch.full_like(activation[:, :1], 127), range_exponent)  # [M,1]
    clipped = activation.clamp(-maximum, maximum)  # [M,H], same representation as input
    _, actual_exponent = _quantize(clipped, per_row=True)  # [M,1], existing quantizer
    assert torch.equal(actual_exponent, torch.where(activation.abs().amax(dim=1, keepdim=True) == 0,
                                                   baseline_exponent, range_exponent))
    return clipped, int(activation.ne(clipped).sum())


def evaluate_ranges(reference, capture, policy):
    """Evaluate fixed trial ranges on captured activations, residuals and targets [M,H]."""
    activation, residual, target = capture
    target_norm = target.norm(dim=1).clamp_min(1e-20)  # [M], per-row normalization
    result = {}
    clipped_inputs, activation_distortions, output_errors = [], [], []
    for reduction in EXPONENT_REDUCTIONS:
        modified, clipped = limited_range(activation, reduction)  # [M,H], range trial
        codes, exponent = _quantize(modified, per_row=True)  # [M,H] signed8, [M,1]
        restored = torch.ldexp(codes.float(), exponent)  # [M,H], dequantized trial codes
        _, values, stats = evaluate_policy(reference, modified, residual, policy, prune=True)
        error = (values - target).norm(dim=1) / target_norm  # [M], normalized errors
        assert bool(torch.isfinite(error).all())
        clipped_inputs.append(modified)
        activation_distortions.append((restored - activation).square().mean(dim=1))  # [M]
        output_errors.append(error)
        result[reduction] = {"mean_relative_output_error": float(error.mean()), "clipped_activations": clipped,
                             "predicted_skips": int(stats["skip_count"].sum())}
    assert len({case["predicted_skips"] for case in result.values()}) == 1

    trials = torch.stack(clipped_inputs, dim=1)  # [M,C,H], C configured exponents
    distortions = torch.stack(activation_distortions, dim=1)  # [M,C], input-only differences
    errors = torch.stack(output_errors, dim=1)  # [M,C], diagnostic target differences
    input_only_choice = distortions.argmin(dim=1)  # [M], earlier exponent breaks ties
    indices = torch.arange(activation.shape[0], device=activation.device)  # [M]
    selected_rows = trials[indices, input_only_choice]  # [M,H], independent range selection
    _, selected_values, selected_stats = evaluate_policy(reference, selected_rows, residual, policy, prune=True)
    selected_error = (selected_values - target).norm(dim=1) / target_norm  # [M]
    torch.testing.assert_close(selected_error, errors[indices, input_only_choice], rtol=1e-6, atol=1e-7)
    assert int(selected_stats["skip_count"].sum()) == result[0]["predicted_skips"]
    best_with_targets = errors.min(dim=1).values  # [M], retrospective floor for these trials
    return result, {
        "activation_distortion_selection_mean_error": float(selected_error.mean()),
        "activation_distortion_selection_changed_rows": int(input_only_choice.ne(0).sum()),
        "target_aware_minimum_mean_error": float(best_with_targets.mean()),
        "target_aware_improvable_rows": int(best_with_targets.lt(errors[:, 0]).sum()),
    }


@torch.inference_mode()
def execute(output):
    """Use one layer of archived rows and frozen weights at a time on the graphics processor."""
    assert __debug__ and Path("/.dockerenv").is_file()
    assert int(Path("/sys/fs/cgroup/memory.max").read_text().strip()) <= 3 * GIB
    started = time.monotonic()
    assert host_available() >= 10 * GIB and torch.cuda.mem_get_info()[0] >= 8 * GIB
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.set_float32_matmul_precision("highest")
    torch.cuda.set_per_process_memory_fraction(0.125)
    torch.cuda.reset_peak_memory_stats()

    model = CACHE / "tiny_llava_v1"
    capture_record = ROOT / "records/format320_multi_image_range_audit.json"
    prior_record = CACHE / "ff_quantization_sources_channel_scaled/receipt.json"
    metadata, prior = read(capture_record), read(prior_record)
    assert metadata["checkpoint_revision"] == prior["checkpoint_revision"] and metadata["labels_used"] is False
    assert [case["split"] for case in metadata["inputs"]] == ["calibration"] * 8 + ["held"] * 8
    assert len({case["image_pixel_sha256"] for case in metadata["inputs"]}) == 16
    assert all(len(case["selected_token_positions"]) == 16 and case["selected_token_positions"][0] == 0
               for case in metadata["inputs"])
    captures = CACHE / "format320/captured_rows.pt"
    policy = CACHE / "format335/layer_policy.json"
    config, manifest = model / "config.json", model / "model.safetensors.index.json"
    mapping = read(manifest)["weight_map"]
    shards = {model / name for name in mapping.values()}
    inputs = {str(path): sha256(path) for path in (captures, policy, config, manifest, *shards)}
    assert all(prior["input_sha256"][name] == checksum for name, checksum in inputs.items())
    for path in (capture_record, prior_record, Path(__file__).resolve(),
                 Path(host_available.__code__.co_filename).resolve(),
                 ROOT / "syn/tri_oracle_format335_policy.py", ROOT / "syn/tri_oracle_integer_reference.py"):
        inputs[str(path)] = sha256(path)
    batches = torch.load(captures, map_location="cpu", weights_only=True, mmap=True)
    settings = read(policy)["layers"]
    assert len(batches) == len(settings) == LAYERS
    indices = [tuple(row for row in range(start, start + 128) if row % 16) for start in (0, 128)]
    assert all(len(rows) == FITTING_ROWS for rows in indices)
    epsilon = read(config)["text_config"]["rms_norm_eps"]
    layers = []
    for layer, (batch, settings_per_layer) in enumerate(zip(batches, settings, strict=True)):
        assert host_available() >= 8 * GIB
        matrices = []
        for role in ("gate", "up", "down"):
            key, = (name for name in mapping if name.endswith(f".layers.{layer}.mlp.{role}_proj.weight"))
            with safe_open(model / mapping[key], framework="pt", device="cpu") as shard:
                matrices.append(shard.get_tensor(key).to(device="cuda", dtype=torch.float32))
        gate, up, down = matrices  # Frozen [K,H], [K,H], [H,K], where K is expansion channels
        assert gate.shape == up.shape == (EXPANSION, HIDDEN) and down.shape == (HIDDEN, EXPANSION)
        reference = IntegerFeedForwardReference(gate, up, down, epsilon)
        reference.down, down_scale = _quantize(down, per_row=True)  # [H,K], [H,1]
        reference.down_exponent = down_scale.T  # [1,H], original channel scales on output
        fit, held = (tuple(batch[role][list(rows)].to(device="cuda", dtype=torch.float32)
                           for role in ("activation", "residual", "target")) for rows in indices)
        assert all(value.shape == (FITTING_ROWS, HIDDEN) for split in (fit, held) for value in split)
        fit_scores, _ = evaluate_ranges(reference, fit, settings_per_layer)
        choice = min(EXPONENT_REDUCTIONS, key=lambda mode: fit_scores[mode]["mean_relative_output_error"])
        held_scores, row_selections = evaluate_ranges(reference, held, settings_per_layer)
        layers.append({"layer": layer, "fit_selected_exponent_reduction": choice,
                       "fit": fit_scores, "held": held_scores, **row_selections})
        print("ACTIVATION_RANGE_LAYER", layer, choice, held_scores[0]["mean_relative_output_error"],
              held_scores[choice]["mean_relative_output_error"], flush=True)
        del gate, up, down, matrices, fit, held, reference

    assert all(sha256(Path(path)) == checksum for path, checksum in inputs.items())
    aggregate = {str(mode): sum(row["held"][mode]["mean_relative_output_error"] for row in layers) / LAYERS
                 for mode in EXPONENT_REDUCTIONS}
    aggregate["fit_selected"] = sum(row["held"][row["fit_selected_exponent_reduction"]]["mean_relative_output_error"]
                                    for row in layers) / LAYERS
    for name in ("activation_distortion_selection_mean_error", "target_aware_minimum_mean_error"):
        aggregate[name] = sum(row[name] for row in layers) / LAYERS
    result = {
        "state": "signed8_activation_range_fit_and_held_rows_measured",
        "checkpoint_revision": metadata["checkpoint_revision"],
        "held_images": 8, "calibration_images": 8, "rows_per_split_per_layer": FITTING_ROWS,
        "layers": layers, "held_mean_relative_output_error": aggregate,
        "device": torch.cuda.get_device_name(), "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
        "elapsed_seconds": time.monotonic() - started, "evidence_sha256": inputs,
        "scope": "Offline approximation error on ordinary prompt rows. All candidates keep the existing integer "
                 "arithmetic and pruning mask. The target-aware minimum uses held output targets and is diagnostic. "
                 "Answer accuracy, hardware integration and paper matching require separate checks.",
    }
    output.mkdir()
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(result["state"], aggregate, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    execute(parser.parse_args().output)
