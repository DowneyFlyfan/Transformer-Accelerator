"""Prepare the trained rank-one attention operand and result files for Xcelium."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from prepare_tri_oracle_context_spool_vectors import context_reference

ROOT = Path(__file__).resolve().parents[1]
FRAME = ROOT / ".cache/late_clipping_20261121/frame_integration"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def packed(values, bits):
    mask = (1 << bits) - 1
    return sum((value & mask) << (bits * index) for index, value in enumerate(values))


def words(path):
    return [int(line, 16) for line in path.read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    output = parser.parse_args().out.resolve()
    if not output.is_relative_to(ROOT / ".cache") or output.exists():
        raise ValueError("Use a new directory under the project cache")

    import torch

    broker = FRAME / "complete_head_broker_v1"
    replay = FRAME / "serialized_replay_consolidation_v1/older/rebuild"
    model = FRAME / "current_integer_attention_fixed_scales_v2"
    projection = FRAME / "context_output_projection_fixture_v1"
    trained = json.loads((broker / "trained32_reference.json").read_text())
    reference = json.loads((model / "receipt.json").read_text())
    weights = json.loads((projection / "receipt.json").read_text())
    for path, expected_hash in trained["source_sha256"].items():
        assert digest(ROOT / path) == expected_hash, path
    assert trained["layer"] == reference["layer"] == weights["layer"] == 19
    assert trained["query_rank"] == 1 and trained["total_keys"] == reference["retained_tokens"] == 281
    assert trained["visible_keys"] == 2 and trained["raw_context_values"] == 2048

    # Use the saved project tensor from the trained execution. Q heads occupy
    # rows 0..31, followed by four K groups and four V groups, with 281 slots each.
    cache = words(replay / "cache.hex")
    rows = trained["rows"]
    assert len(cache) == 40 * 281 and len(rows) == 32
    operands = {
        "q": [cache[h * 281 + 1] for h in range(32)],
        "k": [cache[(32 + g) * 281 + k] for g in range(4) for k in range(2)],
        "v": [cache[(36 + g) * 281 + k] for g in range(4) for k in range(2)],
        "gold": words(replay / "attention.hex"),
    }
    for name, extracted in operands.items():
        assert extracted == words(broker / f"trained32_{name}.hex"), name
    for head, row in enumerate(rows):
        assert row["head"] == head and packed(row["query"], 8) == operands["q"][head]
        for position in range(2):
            assert packed(row["keys"][position], 8) == operands["k"][2*(head//8)+position]
            assert packed(row["values"][position], 8) == operands["v"][2*(head//8)+position]
        assert packed(row["exact_accumulators"], 32) == operands["gold"][head]

    # Independent integer reconstruction using two recorded softmax probabilities per head.
    probabilities = torch.tensor([r["unsigned16_probabilities"] for r in rows], device="cuda", dtype=torch.int64)
    values = torch.tensor([r["values"] for r in rows], device="cuda", dtype=torch.int64)
    accumulators = (probabilities[:, :, None] * values).sum(dim=1).tolist()
    assert accumulators == [r["exact_accumulators"] for r in rows]
    groups = reference["projection_output_exponents"][36:40]
    units = [groups[h//8] for h in range(32)]
    assert units == [r["value_exponent"] for r in rows]
    for name, key in (("weight_units.hex", "weight_exponents"), ("output_units.hex", "output_exponents")):
        assert digest(projection / name) == weights["files"][name]["sha256"]
        assert words(projection / name) == [v & 255 for v in weights[key]]
    assert weights["output_exponents"] == reference["output_exponents"]
    common, codes = context_reference(accumulators, units, weights["weight_exponents"], weights["output_exponents"])
    frozen = model / "data/output_input.bin"
    assert digest(frozen) == reference["files"]["data/output_input.bin"]["sha256"]
    assert common == reference["output_input_exponents"][1]
    assert bytes(c & 255 for c in codes) == frozen.read_bytes()[2048:4096]
    streaming = packed([r["streaming"] for r in rows], 1)
    shifts = packed([r["score_shift"] for r in rows], 7)
    assert (streaming, shifts) == (trained["streaming_mask"], trained["score_shifts"])

    output.mkdir(parents=True)
    for name in operands:
        (output / f"trained32_{name}.hex").symlink_to(broker / f"trained32_{name}.hex")
    cfg = [streaming, shifts, packed(groups, 9), packed(weights["weight_exponents"], 9),
           packed(weights["output_exponents"], 9), common & 1023]
    (output / "cfg.hex").write_text("".join(f"{word:072x}\n" for word in cfg))
    (output / "codes.hex").write_text("".join(f"{c & 255:02x}\n" for c in codes))
    inputs = [broker / "trained32_reference.json", projection / "receipt.json", model / "receipt.json",
              replay / "cache.hex", replay / "attention.hex", frozen, Path(__file__),
              Path(__file__).with_name("prepare_tri_oracle_context_spool_vectors.py")]
    record = dict(layer=19, query_rank=1, visible_keys=2, retained_tokens=281,
                  model_question_id=reference["questionId"], gpu=torch.cuda.get_device_name(),
                  matched_accumulators=2048, matched_frozen_context_bytes=2048, common_unit=common,
                  code_range=[min(codes), max(codes)], group_units=groups,
                  input_sha256={str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  artifact_sha256={p.name: digest(p) for p in sorted(output.glob("*.hex"))})
    (output / "reference.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"TRAINED_BROKER_CONTEXT_FIXTURE_PASS accumulators=2048 bytes=2048 common_unit={common}")


if __name__ == "__main__":
    main()
