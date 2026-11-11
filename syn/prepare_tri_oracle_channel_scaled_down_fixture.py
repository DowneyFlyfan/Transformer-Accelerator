"""Prepare a full-width trained replay with per-output-channel down weights."""

import argparse
import json
from pathlib import Path

import numpy as np
from safetensors import safe_open
import torch

from audit_tri_oracle_ff_down_input import CACHE, ROOT, digest, read
from prepare_tri_oracle_batch407_learned_fixture import byte_codes, word_codes
from tri_oracle_integer_reference import _dot, _quantize

TOKENS, HIDDEN, CHANNELS = 16, 2048, 5632
ARCHIVED_ROWS = {
    "activation.hex": HIDDEN,
    "keep.hex": CHANNELS,
    "shifts.hex": 3,
    "intermediate.hex": CHANNELS,
}


def write_hex(path, values, bits):
    with path.open("x") as stream:
        mask = (1 << bits) - 1
        stream.writelines(f"{int(value) & mask:0{bits // 4}x}\n" for value in values.reshape(-1))


@torch.inference_mode()
def prepare(output):
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(0.25)
    trained_path = ROOT / "records/batch389_fixture_preparation.json"
    benchmark_path = ROOT / "records/ff_channel_scaled_down_holdout_result.json"
    diagnostic_path = ROOT / "records/ff_quantization_sources.json"
    trained, benchmark, diagnostic = (read(path) for path in (trained_path, benchmark_path, diagnostic_path))
    assert trained["state"] == "complete_trained_layer_fixture_scalar_cuda_equal"
    assert trained["original_layer"] == 0 and trained["tokens"] == TOKENS
    assert (trained["input_features"], trained["intermediate_features"], trained["output_features"]) == (HIDDEN, CHANNELS, HIDDEN)
    assert benchmark["state"] == "channel_scaled_down_projection_benchmark_independently_scored"
    assert benchmark["checkpoint_revision"] == diagnostic["checkpoint_revision"]
    pinned = trained["files_sha256"] | {str(ROOT / name): sha for name, sha in benchmark["evidence_sha256"].items()}
    pinned.update({str(ROOT / name): sha for name, sha in diagnostic["evidence_sha256"].items()})
    native_audit = CACHE / "ff_quantization_sources_channel_scaled/receipt.json"
    assert pinned[str(native_audit)] == digest(native_audit)
    prior = read(native_audit)
    model = CACHE / "tiny_llava_v1"
    index_path = model / "model.safetensors.index.json"
    index = read(index_path)["weight_map"]
    key, = (name for name in index if name.endswith(".layers.0.mlp.down_proj.weight"))
    shard_path = model / index[key]
    for path in (index_path, shard_path):
        pinned[str(path)] = prior["input_sha256"][str(path)]
    for path in (Path(__file__), trained_path, benchmark_path, diagnostic_path,
                 ROOT / "syn/prepare_tri_oracle_batch407_learned_fixture.py", ROOT / "syn/tri_oracle_integer_reference.py"):
        pinned[str(path)] = digest(path)
    assert all(digest(Path(name)) == sha for name, sha in pinned.items())
    source = Path(trained["fixture"])
    # Archived down inputs [token, channel] already include the original weight skip mask.
    intermediate = byte_codes(source / "intermediate.hex", (TOKENS, CHANNELS))
    baseline_weights = byte_codes(source / "down.hex", (HIDDEN, CHANNELS))
    baseline = intermediate.astype(np.int32) @ baseline_weights.astype(np.int32).T  # [token, output]
    assert np.array_equal(baseline, word_codes(source / "expected.hex"))
    with safe_open(shard_path, framework="pt", device="cpu") as shard:
        weights = shard.get_tensor(key).float()  # [output, channel], original trained down projection.
    assert weights.shape == (HIDDEN, CHANNELS)
    code, exponent = _quantize(weights.to("cuda"), per_row=True)  # [output, channel], [output, 1]
    exponents = exponent.cpu().numpy().reshape(HIDDEN)  # [output]
    assert [int(exponents.min()), int(exponents.max())] == prior["layers"][0]["channel_scale_exponent_range"]
    # Independent NumPy quantization with the same signed8 rounding and range.
    weights_cpu = weights.numpy()  # [output, channel]
    maximum = np.abs(weights_cpu).max(axis=1)  # [output]
    mantissa, exp = np.frexp(maximum)
    expected_exp = np.where(maximum == 0, 0, exp - 7 + (mantissa > 127 / 128)).astype(np.int32)
    assert np.array_equal(exponents, expected_exp)
    scaled = np.ldexp(weights_cpu, -expected_exp[:, None])  # [output, channel]
    cpu_codes = np.clip(np.sign(scaled) * np.floor(np.abs(scaled) + np.float32(0.5)), -128, 127).astype(np.int8)
    assert np.array_equal(code.cpu().numpy(), cpu_codes)
    # The benchmark kept the first token on the baseline down weights.
    later = intermediate[1:]  # [15 later tokens, channels]
    expected = later.astype(np.int32) @ cpu_codes.astype(np.int32).T  # [15 later tokens, outputs]
    actual = _dot(torch.from_numpy(later).to("cuda"), code)
    assert np.array_equal(actual.cpu().numpy(), expected)
    assert np.any(expected != baseline[1:])
    assert CHANNELS * 128 * 128 < np.iinfo(np.int32).max

    output.mkdir()
    for name in ("gate.hex", "up.hex"):
        (output / name).symlink_to(source / name)
    for name, width in ARCHIVED_ROWS.items():
        words = byte_codes(source / name, (TOKENS, width))  # [token, flattened fixture fields]
        write_hex(output / name, words[1:], 8)
    write_hex(output / "down.hex", cpu_codes, 8)
    write_hex(output / "weight_scale.hex", exponents, 8)
    write_hex(output / "expected.hex", expected, 32)
    assert all(digest(Path(name)) == sha for name, sha in pinned.items())
    result = dict(state="trained_channel_scaled_down_fixture_cpu_and_gpu_equal", fixture=str(output),
                  checkpoint_revision=benchmark["checkpoint_revision"], layer=0, tokens=TOKENS - 1,
                  original_token_positions=trained["original_token_positions"][1:], hidden=HIDDEN, intermediate=CHANNELS,
                  exact_integer_outputs=expected.size, changed_raw_outputs=int(np.count_nonzero(expected != baseline[1:])),
                  scales=int(exponents.size), exponent_range=[int(exponents.min()), int(exponents.max())],
                  input_sha256=pinned, files_sha256={path.name: digest(path) for path in sorted(output.iterdir())},
                  scope="Hardware replay inputs and exact raw output words. Output scales are separate signed exponents.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print("CHANNEL_SCALED_DOWN_FIXTURE_READY", result["tokens"], result["exact_integer_outputs"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    prepare(parser.parse_args().output)
