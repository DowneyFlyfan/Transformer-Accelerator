"""Independently recompute the trained projection fixture on the host GPU."""

from hashlib import file_digest, sha256
import json
from pathlib import Path

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".cache/model_reference"
FIXTURE_RECORD = ROOT / ".cache/physical/whole_chip_xcelium_speed/prepared.json"
GROUPS, TOKENS, FEATURES, HIDDEN = 40, 409, 64, 2048
ROTARY_GROUPS = 36


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def load(path):
    return json.loads(path.read_text())


def unpack_hex_bytes(path, word_bytes):
    result = bytearray()
    with path.open() as stream:
        for line in stream:
            word = bytes.fromhex(line)
            assert len(word) == word_bytes, path
            result.extend(reversed(word))
    return result


def project(activations, weights, cosines, sines, shifts, biases):
    device = torch.device("cuda:0")
    # Integer products have magnitude at most 128**2. The sum of 2048 such
    # magnitudes is below 2**53, so double-precision accumulation is exact.
    tokens = torch.as_tensor(activations, device=device, dtype=torch.float64)
    rows = torch.as_tensor(weights, device=device, dtype=torch.float64)
    dots = torch.matmul(rows, tokens.T).transpose(1, 2).to(torch.int64)
    lower, upper = dots[:ROTARY_GROUPS].chunk(2, dim=2)
    cosines = torch.as_tensor(cosines, device=device, dtype=torch.int64)
    sines = torch.as_tensor(sines, device=device, dtype=torch.int64)
    rotary = torch.cat((lower * cosines - upper * sines, upper * cosines + lower * sines), dim=2)
    vectors = torch.cat((rotary, dots[ROTARY_GROUPS:]))
    shift = torch.tensor(shifts, device=device)[:, None, None] + torch.tensor(biases, device=device)[None, :, None]
    assert 0 < int(shift.min()) <= int(shift.max()) < 63
    half = torch.ones_like(shift) << (shift - 1)
    rounded = ((vectors.abs() + half) >> shift) * vectors.sign()
    return rounded.clamp(-128, 127).to(torch.int8).cpu().numpy()


def verify():
    paths = {}

    def pin(path, expected=None):
        actual = digest(path)
        assert expected is None or actual == expected, path
        paths[str(path.relative_to(ROOT))] = actual
        return path

    projection_manifest = load(pin(DATA / "batch429/reference.json"))
    layer_manifest = load(pin(DATA / "batch430/reference.json"))
    assert projection_manifest["question"] == layer_manifest["question"] == 42000

    def binary(batch, name, manifest, dtype, shape):
        path = pin(DATA / batch / name, manifest["fixture_sha256"][name])
        return np.fromfile(path, dtype=dtype).reshape(shape)

    weights = binary("batch429", "weights.bin", projection_manifest, np.int8, (GROUPS, FEATURES, HIDDEN))
    activation = binary("batch430", "activation.bin", layer_manifest, np.int8, (TOKENS, HIDDEN))
    cosines = binary("batch430", "cos.bin", layer_manifest, "<i2", (TOKENS, FEATURES // 2))
    sines = binary("batch430", "sin.bin", layer_manifest, "<i2", (TOKENS, FEATURES // 2))
    shifts, biases = layer_manifest["shifts"], layer_manifest["shift_biases"]
    assert len(shifts) == GROUPS and len(biases) == TOKENS

    record = load(pin(FIXTURE_RECORD))
    fixture = Path(record["fixture"])

    def fixture_file(name):
        path = fixture / name
        return pin(path, record["evidence_sha256"][str(path.relative_to(ROOT))])

    for name, array, word in (("activation", activation, 8), ("weights", weights, 8),
                              ("cos", cosines, 64), ("sin", sines, 64)):
        assert unpack_hex_bytes(fixture_file(name + ".hex"), word) == array.tobytes(), name
    assert [int(line, 16) for line in fixture_file("biases.hex").read_text().splitlines()] == biases
    serialized_shifts = int(fixture_file("shifts.hex").read_text(), 16)
    assert 0 <= serialized_shifts < (1 << (6 * GROUPS))
    assert [(serialized_shifts >> (6 * index)) & 63 for index in range(GROUPS)] == shifts

    vectors = project(activation, weights, cosines, sines, shifts, biases)
    assert vectors.shape == (GROUPS, TOKENS, FEATURES)
    expected = np.frombuffer(unpack_hex_bytes(fixture_file("expected.hex"), FEATURES), dtype=np.int8)
    expected = expected.reshape(vectors.shape)
    mismatches = np.argwhere(vectors != expected)
    assert not len(mismatches), f"First mismatching group, token, feature: {mismatches[0].tolist()}"
    pin(Path(__file__).resolve())
    return {
        "state": "trained_projection_fixture_verified_with_independent_gpu_arithmetic",
        "question": layer_manifest["question"],
        "gpu": torch.cuda.get_device_name(0),
        "peak_gpu_tensor_bytes": torch.cuda.max_memory_allocated(0),
        "groups": GROUPS,
        "retained_tokens": TOKENS,
        "matched_int8_outputs": vectors.size,
        "outputs_sha256": sha256(vectors.tobytes()).hexdigest(),
        "scope": "One trained software projection fixture, including rotary arithmetic for query and key groups.",
        "evidence_sha256": paths,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    assert torch.cuda.is_available()
    assert torch.cuda.mem_get_info(0)[0] >= 1024**3
    print(json.dumps(verify(), indent=2, sort_keys=True))
