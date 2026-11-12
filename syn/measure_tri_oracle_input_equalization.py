"""Measure per-input power-of-two scales with the existing signed8 datapath."""

import argparse
from copy import copy
import inspect
import json
from pathlib import Path
import time
from types import SimpleNamespace

from safetensors import safe_open
import torch
from torch.nn import functional

from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import IntegerFeedForwardReference, _quantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


CACHE = ROOT / ".cache/model_reference"
GIB = 2**30
ALPHAS = (0.25, 0.5, 0.75)
LAYERS, HIDDEN, EXPANSION = 22, 2048, 5632


def read(path):
    return json.loads(path.read_text())


def host_available():
    with Path("/proc/meminfo").open() as source:
        return 1024 * next(int(line.split()[1]) for line in source if line.startswith("MemAvailable:"))


def exponents(fit_input, gate, up, alpha):
    """Fit feature exponents [H] from captured fit rows [M,H] and checkpoint weights [K,H].

    Per-feature activation and weight maxima and their logarithms all have [H].
    Centering subtracts a scalar median before bounding each integer exponent.
    """
    act_max = fit_input.abs().amax(dim=0).clamp_min(1e-20)  # [H], fit rows only
    weight_max = torch.maximum(gate.abs().amax(dim=0), up.abs().amax(dim=0)).clamp_min(1e-20)  # [H]
    act_log, weight_log = torch.log2(act_max), torch.log2(weight_max)  # [H]
    balanced = alpha * (act_log - act_log.median()) - (1-alpha) * (weight_log - weight_log.median())  # [H]
    return balanced.round().clamp(-3, 3).to(torch.int32)


def variant(baseline, gate, up, powers):
    """Build an evaluator from frozen [K,H] gate/up weights and [H] feature scales.

    New weight codes stay signed8 [K,H] with a scalar exponent per matrix.
    The baseline's down projection and gate/up sign metadata remain attached.
    """
    adjusted = copy(baseline)
    gate_codes, gate_scale = _quantize(torch.ldexp(gate, powers))  # [K,H], scalar
    up_codes, up_scale = _quantize(torch.ldexp(up, powers))  # [K,H], scalar
    adjusted.gate, adjusted.gate_exponent = gate_codes, int(gate_scale)
    adjusted.up, adjusted.up_exponent = up_codes, int(up_scale)
    evaluate = adjusted.evaluate

    def scaled(activation, residual, **settings):
        # Activation [M,H] and pre-scale residual [M,H] are supplied by the existing
        # policy. The activation transform shares the same [H] powers for both projections.
        return evaluate(torch.ldexp(activation, -powers), residual, **settings)

    return SimpleNamespace(evaluate=scaled)


def evaluate(reference, capture, policy, prune):
    """Return mean relative output error and predicted skip count for a frozen split.

    Capture supplies activation/residual/target [M,H]. The reused integer policy
    returns values [M,H] and per-row skip counts [M]. Relative errors are [M].
    """
    activation, residual, target = capture
    _, values, stats = evaluate_policy(reference, activation, residual, policy, prune=prune)
    error = (values - target).norm(dim=1) / target.norm(dim=1).clamp_min(1e-20)  # [M]
    assert bool(torch.isfinite(error).all())
    return float(error.mean()), int(stats["skip_count"].sum())


def fit_layer(baseline, gate, up, fit, held, policy):
    """Choose using fit [M,H] rows, then evaluate separately on held [M,H] rows.

    Each tuple contains activation, pre-scale residual and full output target.
    Gate/up checkpoint weights are [K,H]. All candidate powers are [H].
    """
    fit_error, fit_skips = evaluate(baseline, fit, policy, True)
    scores = {"identity": fit_error}
    selected, fitted, powers = "identity", baseline, None
    for alpha in ALPHAS:
        column_powers = exponents(fit[0], gate, up, alpha)  # [H]
        candidate = variant(baseline, gate, up, column_powers)
        error, skips = evaluate(candidate, fit, policy, True)
        assert skips == fit_skips
        scores[str(alpha)] = error
        if error < scores[selected]:
            selected, fitted, powers = str(alpha), candidate, column_powers
    if powers is not None:
        probe = fit[0][:4]  # [4,H], fit-only float identity check
        for weight in (gate, up):
            actual = functional.linear(torch.ldexp(probe, -powers), torch.ldexp(weight, powers))  # [4,K]
            torch.testing.assert_close(actual, functional.linear(probe, weight), rtol=1e-5, atol=1e-5)
    results = {}
    for label, prune in (("dense", False), ("pruned", True)):
        original, original_skips = evaluate(baseline, held, policy, prune)
        changed, changed_skips = evaluate(fitted, held, policy, prune)
        assert original_skips == changed_skips
        results[label] = {"baseline": original, "equalized": changed, "predicted_skips": original_skips}
    return {"selection": selected, "fit_pruned_error": scores, "held": results,
            "feature_exponents": powers.tolist() if powers is not None else [0] * HIDDEN}


@torch.inference_mode()
def run(output, diagram):
    """Read checkpoint weights [K,H]/[H,K] and captured tensors [256,H] per layer.

    Each of the two splits contains eight images with sixteen sampled rows each.
    Omit position zero, which uses its own hardware format. Each fit/held tuple
    then supplies [120,H] tensors. All matrix evaluation is layer-local.
    """
    started = time.monotonic()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.set_float32_matmul_precision("highest")
    assert host_available() >= 16 * GIB and torch.cuda.mem_get_info()[0] >= 8 * GIB
    torch.cuda.set_per_process_memory_fraction(0.1)
    torch.cuda.reset_peak_memory_stats()
    model = CACHE / "tiny_llava_v1"
    capture = ROOT / "records/format320_multi_image_range_audit.json"
    reference = CACHE / "ff_quantization_sources_channel_scaled/receipt.json"
    metadata, prior = read(capture), read(reference)
    assert metadata["checkpoint_revision"] == prior["checkpoint_revision"] and metadata["labels_used"] is False
    assert [case["split"] for case in metadata["inputs"]] == ["calibration"]*8 + ["held"]*8
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
    for path in (capture, reference, diagram, Path(__file__).resolve(),
                 Path(evaluate_policy.__code__.co_filename), Path(inspect.getfile(IntegerFeedForwardReference))):
        pins[str(path)] = sha256(path)
    captures = torch.load(rows, map_location="cpu", weights_only=True, mmap=True)
    policies = read(policy)["layers"]
    assert len(captures) == len(policies) == LAYERS
    epsilon = read(config)["text_config"]["rms_norm_eps"]
    row_indices = [[row for row in range(offset, offset+128) if row%16] for offset in (0, 128)]
    layers = []
    for layer, (data, settings) in enumerate(zip(captures, policies, strict=True)):
        assert host_available() >= 14.5 * GIB
        matrices = []
        for name in ("gate", "up", "down"):
            key, = (item for item in mapping if item.endswith(f".layers.{layer}.mlp.{name}_proj.weight"))
            with safe_open(model/mapping[key], framework="pt", device="cpu") as shard:
                matrices.append(shard.get_tensor(key).to(device="cuda", dtype=torch.float32))
        gate, up, down = matrices  # gate/up [K,H], down [H,K], frozen checkpoint values
        assert gate.shape == up.shape == (EXPANSION, HIDDEN) and down.shape == (HIDDEN, EXPANSION)
        baseline = IntegerFeedForwardReference(gate, up, down, epsilon)
        baseline.down, down_powers = _quantize(down, per_row=True)  # [H,K], [H,1]
        baseline.down_exponent = down_powers.T  # [1,H], current ordinary-row output scales
        fit, held = (tuple(data[name][ids].to(device="cuda", dtype=torch.float32)
                           for name in ("activation", "residual", "target")) for ids in row_indices)
        assert all(value.shape == (120, HIDDEN) for split in (fit, held) for value in split)
        report = fit_layer(baseline, gate, up, fit, held, settings)
        layers.append({"layer": layer, **report})
        print("INPUT_EQUALIZATION_LAYER", layer, report["selection"], report["held"]["pruned"], flush=True)
        del baseline, gate, up, down, fit, held, matrices
    assert all(sha256(Path(name)) == expected for name, expected in pins.items())
    summary = {mode: {kind: sum(item["held"][mode][kind] for item in layers)/LAYERS
                      for kind in ("baseline", "equalized")} for mode in ("dense", "pruned")}
    result = {"state": "fit_only_power_of_two_input_equalization_measured_on_held_rows",
              "checkpoint_revision": metadata["checkpoint_revision"], "layers": layers, "held_summary": summary,
              "rows_per_split_per_layer": 120, "fit_images": 8, "held_images": 8, "device": torch.cuda.get_device_name(),
              "peak_gpu_bytes": torch.cuda.max_memory_allocated(), "seconds": time.monotonic()-started,
              "input_sha256": pins,
              "scope": "Captured ordinary feed-forward rows. Both branches retain signed8 matrix inputs. "
                       "Pruning decisions use the original weight sign metadata and residual."}
    with output.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print("INPUT_EQUALIZATION_COMPLETE", json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("diagram", type=Path)
    run(**vars(parser.parse_args()))
