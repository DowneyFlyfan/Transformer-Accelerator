"""Isolate final down-projection input clipping and rounding on archived later rows."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path

from safetensors import safe_open
import torch

from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import IntegerFeedForwardReference, _dot, _quantize, _requantize

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache/model_reference"
GIB = 2**30


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def exact_down_dot(inputs, weights):
    """Signed16 codes [rows, channels] and signed8 weights [outputs, channels]."""
    # Each digit has shape [rows, channels]. The first two are nonnegative
    # radix-128 remainders and the top digit is the arithmetic quotient.
    low = inputs.remainder(128).to(torch.int8)
    middle = (inputs >> 7).remainder(128).to(torch.int8)
    high = (inputs >> 14).to(torch.int8)
    # Accumulate [rows, outputs] in signed64 to avoid overflow after shifting.
    sums = _dot(low, weights).long() + (_dot(middle, weights).long() << 7) + (_dot(high, weights).long() << 14)
    # The first four rows and sixteen outputs provide an independent exact oracle.
    assert torch.equal(sums[:4, :16], (inputs[:4].double() @ weights[:16].double().T).long())
    return sums


def measure(reference, activation, residual, target, policy):
    """Activation, residual and float target are [later rows, hidden features]."""
    # Baseline output and per-row control settings come from the production dispatch.
    raw, baseline, stats = evaluate_policy(reference, activation, residual, policy, prune=False)
    codes, _ = _quantize(activation, per_row=True)  # [rows, hidden features]
    gate = _requantize(_dot(codes, reference.gate), stats["gate_shift"][:, None], 16)  # [rows, channels]
    up = _requantize(_dot(codes, reference.up), stats["up_shift"][:, None], 16)  # [rows, channels]
    shift = stats["down_shift"][:, None]  # [rows, 1], broadcast over channels or outputs.
    gated = _requantize(reference.silu_response[gate + 32768] * up, torch.full_like(shift, 8), 16)  # [rows, channels]
    rounded = _requantize(gated, shift, 16)  # [rows, channels], no final signed8 clip.
    signed8 = rounded.clamp(-128, 127).to(torch.int8)  # [rows, channels]
    assert torch.equal(_dot(signed8, reference.down), raw)
    scale = reference.down_exponent + shift - 8 - stats["up_gain_bits"][:, None]  # [rows, 1]
    # These two output variants both keep the existing signed16 gated-product limit.
    no_clip = torch.ldexp(exact_down_dot(rounded, reference.down).float(), scale)  # [rows, hidden features]
    no_clip_or_round = torch.ldexp(exact_down_dot(gated, reference.down).float(), scale - shift)  # [rows, hidden features]
    denominator = target.double().norm(dim=1).clamp_min(1e-20)  # [rows]
    errors = {}
    for mode, values in (("baseline", baseline), ("no_clip", no_clip), ("no_clip_or_round", no_clip_or_round)):
        # Relative errors are evaluated on the same archived target row for every mode.
        relative = (values.double() - target.double()).norm(dim=1) / denominator  # [rows]
        errors[mode] = float(relative.mean())
    return dict(mean_row_relative_error=errors, intermediate_values=rounded.numel(),
                clipped=int(((rounded < -128) | (rounded > 127)).sum()),
                rounded_to_zero=int(((gated != 0) & (rounded == 0)).sum()))


@torch.inference_mode()
def run(output):
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(0.25)
    capture_record = ROOT / "records/format320_multi_image_range_audit.json"
    policy_record = ROOT / "records/format335_rowbalanced_calibration.json"
    capture = read(capture_record)
    fitted = read(policy_record)
    assert capture["checkpoint_revision"] == fitted["checkpoint_revision"]
    rows_path = CACHE / "format320/captured_rows.pt"
    policy_path = CACHE / "format335/layer_policy.json"
    model = CACHE / "tiny_llava_v1"
    index_path = model / "model.safetensors.index.json"
    config_path = model / "config.json"
    index = read(index_path)["weight_map"]
    paths = [rows_path, policy_path, index_path, config_path, *(model / shard for shard in sorted(set(index.values())))]
    known = capture["source_sha256"] | capture["generated_sha256"] | fitted["generated_sha256"]
    pins = {str(path): digest(path) for path in paths}
    for name, sha in pins.items():
        assert sha == known.get(name, known.get(str(Path(name).relative_to(ROOT)))), name
    for path in (Path(__file__), capture_record, policy_record, *(ROOT / "syn" / name for name in (
            "tri_oracle_integer_reference.py", "tri_oracle_format335_policy.py", "tri_oracle_model_reference.py"))):
        pins[str(path)] = digest(path)
    archived = torch.load(rows_path, map_location="cpu", weights_only=True, mmap=True)
    policies = read(policy_path)["layers"]
    epsilon = read(config_path)["text_config"]["rms_norm_eps"]
    assert len(archived) == len(policies) == 22
    # Each of the eight diagnostic images contributed 16 rows. Exclude position zero.
    selected = [row for row in range(128, 256) if row % 16 != 0]
    assert all(item["selected_token_positions"][0] == 0 for item in capture["inputs"][8:])
    results = []
    for layer, (data, policy) in enumerate(zip(archived, policies, strict=True)):
        assert policy["layer"] == layer
        weights = []
        for kind in ("gate", "up", "down"):
            name, = (name for name in index if name.endswith(f".layers.{layer}.mlp.{kind}_proj.weight"))
            with safe_open(model / index[name], framework="pt", device="cpu") as shard:
                weights.append(shard.get_tensor(name).to("cuda"))  # [channels, hidden] or [hidden, channels]
        reference = IntegerFeedForwardReference(*weights, epsilon)
        # Select original later rows from the fixed normalized input, residual and float target.
        tensors = [data[key][selected].to("cuda") for key in ("activation", "residual", "target")]
        assert all(item.shape == (120, 2048) for item in tensors)
        results.append(dict(layer=layer, **measure(reference, *tensors, policy)))
        print("FF_DOWN_INPUT_LAYER", layer, results[-1]["mean_row_relative_error"], flush=True)
    assert all(digest(Path(path)) == sha for path, sha in pins.items())
    result = dict(state="down_input_clipping_and_rounding_attributed_on_archived_rows",
                  checkpoint_revision=capture["checkpoint_revision"], rows_per_layer=len(selected),
                  diagnostic_images=8, layers=results, input_sha256=pins,
                  graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                  scope="Later prefill rows from the earlier diagnostic split. Floating targets are fixed. No task accuracy was measured.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)
