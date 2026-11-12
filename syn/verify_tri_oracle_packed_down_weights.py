"""Check every packed byte against archived trained weights and prepare a fabric test."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path

from pack_tri_oracle_weights import pack_weights


ROOT = Path(__file__).resolve().parents[1]
FIRST_ROW, TILE_ROWS = 1760, 160
FIRST_PART_WORD, WORDS = 33, 2


def sha256(path):
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def signed(byte):
    return byte - 256 if byte >= 128 else byte


def prepare(output):
    weights_record = ROOT / "records/batch389_fixture_preparation.json"
    input_record = ROOT / "records/batch407_learned_fixture.json"
    weights = json.loads(weights_record.read_text())
    inputs = json.loads(input_record.read_text())
    rows, features = weights["output_features"], weights["intermediate_features"]
    assert (rows, features, weights["original_layer"]) == (2048, 5632, 0)
    assert (inputs["hidden"], inputs["intermediate"], inputs["original_checkpoint_layer"]) == (rows, features, 0)
    assert inputs["source_sha256"][str(weights_record)] == sha256(weights_record)
    source = Path(weights["fixture"]) / "down.hex"
    activation_path = Path(inputs["fixture"]) / "intermediate.hex"
    assert sha256(source) == weights["files_sha256"][str(source)]
    assert sha256(activation_path) == inputs["files_sha256"][str(activation_path)]
    reference = bytes.fromhex(source.read_text())
    activation = bytes.fromhex(activation_path.read_text())[:features]
    assert len(reference) == rows * features and len(activation) == features

    output.mkdir()
    packed = output / "packed.bin"
    with source.open("rb") as data, packed.open("xb") as destination:
        pack_weights(data, destination, rows, features)
    assert packed.stat().st_size == len(reference)

    with packed.open("rb") as data:
        for first_row in range(0, rows, 8):
            block = data.read(features * 8)
            for lane in range(8):
                actual = b"".join(block[offset + lane * 8:offset + (lane + 1) * 8]
                                  for offset in range(0, len(block), 64))
                start = (first_row + lane) * features
                assert actual == reference[start:start + features], (first_row, lane)
        assert data.read() == b""

    part_words = features // (4 * 8)
    with packed.open("rb") as data, (output / "responses.hex").open("x") as responses:
        for cluster in range(5):
            for part in range(4):
                for group in range(4):
                    row = FIRST_ROW + cluster * 32 + group * 8
                    word = part * part_words + FIRST_PART_WORD
                    data.seek((row // 8 * (features // 8) + word) * 64)
                    for _ in range(WORDS):
                        responses.write(data.read(64)[::-1].hex() + "\n")

    def feature_start(part, beat):
        return 8 * (part * part_words + FIRST_PART_WORD + beat)

    with (output / "activations.hex").open("x") as stream:
        for part in range(4):
            for beat in range(WORDS):
                start = feature_start(part, beat)
                stream.write(activation[start:start + 8][::-1].hex() + "\n")

    with (output / "expected.hex").open("x") as stream:
        for beat in range(WORDS):
            selected = [feature_start(part, beat) + byte for part in range(4) for byte in range(8)]
            for row in range(FIRST_ROW, FIRST_ROW + TILE_ROWS):
                result = sum(signed(activation[index]) * signed(reference[row * features + index])
                             for index in selected)
                stream.write(f"{result & 0xffffffff:08x}\n")

    evidence = (weights_record, input_record, source, activation_path, Path(__file__),
                Path(__file__).with_name("pack_tri_oracle_weights.py"), *sorted(output.iterdir()))
    report = {"state": "trained_layer_zero_down_weights_round_trip_exact",
              "rows": rows, "features": features, "exact_bytes": len(reference),
              "packed_responses": len(reference) // 64, "fabric_tile_first_row": FIRST_ROW,
              "fabric_part_first_word": FIRST_PART_WORD, "fabric_tile_rows": TILE_ROWS,
              "fabric_test_responses": TILE_ROWS // 8 * 4 * WORDS,
              "fabric_test_outputs": TILE_ROWS * WORDS,
              "evidence_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in evidence}}
    (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f'{report["state"]} bytes={len(reference)} responses={len(reference) // 64}')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output.resolve())
