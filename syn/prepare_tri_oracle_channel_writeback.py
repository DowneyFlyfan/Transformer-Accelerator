"""Compare down-projection weight scales on the archived layer 10 chip operands."""

from hashlib import file_digest
import json
from pathlib import Path

import numpy as np
from safetensors import safe_open
import torch

from tri_oracle_integer_reference import _dot, _quantize

ROOT = Path(__file__).resolve().parents[1]
OUT = (
    ROOT
    / ".cache/placement_coordinate_reuse/trained_layer11_boundary/channel_writeback"
)
BOUNDARY = OUT.parent
HIDDEN = 2048
CHANNELS = 5632


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def json_input(path):
    return json.loads(path.read_text())


def codes(path, bits, shape):
    count = int(np.prod(shape))
    with path.open() as stream:
        array = np.fromiter(
            (int(line, 16) for line in stream), dtype=f"<u{bits // 8}", count=count
        )
        assert not stream.readline(), path
    return array.view(f"<i{bits // 8}").reshape(shape)


def pack(values, bits):
    return sum(
        (int(value) & ((1 << bits) - 1)) << (i * bits) for i, value in enumerate(values)
    )


def round_away_float(values):
    return np.copysign(np.floor(np.abs(values) + 0.5), values).astype(np.int64)


def writeback(bypass, codes, shifts):
    combined = bypass + (codes.astype(np.int64) << shifts)
    assert np.max(np.abs(combined)) < 2**62
    result = np.sign(combined) * ((np.abs(combined) + 4096) >> 13)
    return np.clip(result, -32768, 32767)


@torch.inference_mode()
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(0.10)
    torch.cuda.reset_peak_memory_stats()
    prep = BOUNDARY / "live_chip_bridge_tail_checked/prepared.json"
    saved = json_input(prep)
    fixture = Path(saved["flags"]["FIXTURE"])
    norm = fixture.parents[1] / "layer10_normalization"
    norm_proof = json_input(norm / "receipt.json")
    assert norm_proof["positions"] == [607, 608] and norm_proof["layer"] == 10
    labels = BOUNDARY / "live_chip_bridge_tail_checked/bridge_handoff.hex"
    prior = json_input(ROOT / "records/tri_oracle_mapped_parent_live_writeback.json")
    assert sha(labels) == prior["evidence_sha256"][str(labels.relative_to(ROOT))]
    keys_path = (
        ROOT / ".cache/model_reference/tiny_llava_v1/model.safetensors.index.json"
    )
    keys = json_input(keys_path)["weight_map"]
    (key,) = [key for key in keys if key.endswith(".layers.10.mlp.down_proj.weight")]
    weights_path = keys_path.with_name(keys[key])
    assert sha(keys_path) == norm_proof["input_sha256"][str(keys_path)]
    assert sha(weights_path) == norm_proof["input_sha256"][str(weights_path)]
    with safe_open(weights_path, framework="pt", device="cpu") as shard:
        checkpoint = shard.get_tensor(key).float()
    assert tuple(checkpoint.shape) == (HIDDEN, CHANNELS)
    gpu_weights = checkpoint.to("cuda")
    global_codes, global_exp = _quantize(gpu_weights)
    lane_codes, lane_exponents = _quantize(gpu_weights, per_row=True)
    lane_exponents = lane_exponents.cpu().numpy().reshape(HIDDEN).astype(np.int64)
    old_weights = codes(fixture / "down.hex", 8, (HIDDEN, CHANNELS))
    assert np.array_equal(global_codes.cpu().numpy(), old_weights)
    inputs = codes(norm / "intermediate.hex", 8, (2, CHANNELS))
    signed = norm_proof["output_sha256"]
    assert sha(norm / "intermediate.hex") == signed.get(
        str(norm / "intermediate.hex"), signed.get("intermediate.hex")
    )
    raw_gold = codes(norm / "expected.hex", 32, (2, HIDDEN))
    assert sha(norm / "expected.hex") == signed.get(
        str(norm / "expected.hex"), signed.get("expected.hex")
    )
    int_gpu_inputs = torch.from_numpy(inputs).to("cuda")
    assert np.array_equal(_dot(int_gpu_inputs, global_codes).cpu().numpy(), raw_gold)
    raw_better = _dot(int_gpu_inputs, lane_codes).cpu().numpy()
    assert np.array_equal(
        raw_better,
        inputs.astype(np.int32) @ lane_codes.cpu().numpy().astype(np.int32).T,
    )
    input_exp = np.asarray(
        norm_proof["feedforward_output_exponents"], dtype=np.int64
    ) - int(global_exp)
    packed = [int(word, 16) for word in labels.read_text().splitlines()]
    assert len(packed) == 512
    old_shifts = np.asarray(norm_proof["feedforward_output_exponents"])[:, None] + 26

    def lane(word, bits, offset):
        value = word >> offset & ((1 << bits) - 1)
        return value - (1 << bits) if value >> (bits - 1) else value

    bypass = np.asarray(
        [lane(word, 29, 29 * i) for word in packed for i in range(8)], dtype=np.int64
    ).reshape(2, HIDDEN)
    old_results = np.asarray(
        [lane(word, 16, 493 + 16 * i) for word in packed for i in range(8)],
        dtype=np.int64,
    ).reshape(2, HIDDEN)
    assert all(
        (word >> 488) & 31 == int(old_shifts[i // 256, 0])
        for i, word in enumerate(packed)
    )
    assert np.array_equal(writeback(bypass, raw_gold, old_shifts), old_results)
    new_shifts = input_exp[:, None] + lane_exponents[None, :] + 26
    assert int(new_shifts.min()) >= 0 and int(new_shifts.max()) <= 31
    new_results = writeback(bypass, raw_better, new_shifts)
    # Reference holds the same integer gated operand. Only the down-weight
    # quantization changes. The shared residual is exact in units of 2^-26.
    exact_updates = (
        np.ldexp(inputs.astype(np.float64), input_exp[:, None])
        @ checkpoint.numpy().astype(np.float64).T
    )
    reference_q13 = np.clip(
        round_away_float(
            (np.ldexp(bypass.astype(np.float64), -26) + exact_updates) * 8192
        ),
        -32768,
        32767,
    )
    errors = {}
    for label, values in (
        ("scalar_weight_scale", old_results),
        ("output_channel_weight_scales", new_results),
    ):
        error = values - reference_q13
        errors[label] = {
            "root_mean_squared_code_error": float(np.sqrt(np.mean(error**2))),
            "maximum_absolute_code_error": int(np.max(np.abs(error))),
            "exact_codes": int(np.count_nonzero(error == 0)),
        }
    # Emit the exact new row words for a lane-scaled HDL replay.
    rows = []
    for token in range(2):
        for offset in range(0, HIDDEN, 8):
            s = slice(offset, offset + 8)
            word = (
                pack(new_results[token, s], 16) << 528
                | pack(new_shifts[token, s], 5) << 488
                | pack(raw_better[token, s], 32) << 232
                | pack(bypass[token, s], 29)
            )
            rows.append(f"{word:0164x}")
    vectors = OUT / "lane_writeback.hex"
    vectors.write_text("\n".join(rows) + "\n")
    paths = [
        prep,
        norm / "receipt.json",
        labels,
        keys_path,
        weights_path,
        fixture / "down.hex",
        norm / "intermediate.hex",
        norm / "expected.hex",
        vectors,
        Path(__file__),
    ]
    receipt = dict(
        state="layer10_channel_scaled_writeback_reference_verified",
        positions=[607, 608],
        values=int(new_results.size),
        global_weight_exponent=int(global_exp),
        input_exponents=[int(e) for e in input_exp],
        lane_weight_exponent_range=[
            int(lane_exponents.min()),
            int(lane_exponents.max()),
        ],
        shift_range=[int(new_shifts.min()), int(new_shifts.max())],
        changed_codes=int(np.count_nonzero(new_results != old_results)),
        errors=errors,
        graphics_peak_bytes=torch.cuda.max_memory_allocated(),
        evidence_sha256={str(path.relative_to(ROOT)): sha(path) for path in paths},
    )
    (OUT / "reference.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                name: field
                for name, field in receipt.items()
                if name != "evidence_sha256"
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
