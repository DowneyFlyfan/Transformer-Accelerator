"""Extract a late trained attention row with both streaming and retrieval heads."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path

import torch

from prepare_tri_oracle_broker_context_fixture import FRAME, ROOT, digest, packed, words
from prepare_tri_oracle_context_spool_vectors import context_reference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    if output.exists() or not output.is_relative_to(ROOT / ".cache"):
        raise ValueError("Use a new output directory under the project cache")
    model = FRAME / "current_integer_attention_fixed_scales_v2"
    capture = FRAME / "current_attention_capture_v1/capture.pt"
    projection = FRAME / "context_output_projection_fixture_v1/receipt.json"
    record = json.loads((model / "receipt.json").read_text())
    model_digest = "bc296dad3c27873e1a9f7c8fd642b55c906a09e7876412793e65ffc84c597293"
    assert digest(model / "receipt.json") == model_digest
    numeric_source = model / "arithmetic.py"
    for path in (capture, numeric_source):
        assert digest(path) == record["input_sha256"][str(path)]
    spec = importlib.util.spec_from_file_location("frozen_attention_arithmetic", numeric_source)
    math_model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(math_model)

    files = {}
    def load_tensor(name, dtype, shape):
        path = model / "data" / (name + ".bin")
        assert digest(path) == record["files"]["data/" + path.name]["sha256"]
        files[str(path.relative_to(ROOT))] = digest(path)
        return torch.frombuffer(bytearray(path.read_bytes()), dtype=dtype).reshape(shape)

    layer, tokens = record["layer"], record["retained_tokens"]
    assert layer == 19 and tokens == 281
    rank = tokens - 1
    projected = load_tensor("projected", torch.int8, (40, tokens, 64))
    # Cross-check physical head/slot ordering against the previously emitted cache.
    cache_path = FRAME / "serialized_replay_consolidation_v1/older/rebuild/cache.hex"
    cache = words(cache_path)
    raw_projected = projected.numpy().tobytes()
    assert len(cache) == 40 * tokens
    assert b"".join(word.to_bytes(64, "little") for word in cache) == raw_projected

    capture_data = torch.load(capture, map_location="cpu", weights_only=True, mmap=True)
    original = capture_data["tensors"]
    positions = original["positions"].tolist()
    origins = original["origins"].tolist()
    start = capture_data["metadata"]["image_start"]
    assert len(positions) == tokens and len(origins) == 576
    roots = [i for i, representative in enumerate(origins) if i == representative]
    image_keys = [i for i, position in enumerate(positions) if start <= position < start + len(origins)]
    assert len(image_keys) == len(roots) and all(root in roots for root in origins)
    visible_image_tokens = max(0, min(len(origins), positions[rank] - start + 1))
    counts = Counter(origins[:visible_image_tokens])
    sizes = [1] * tokens
    for key, representative in zip(image_keys, roots):
        sizes[key] = counts[representative]
    assert all(0 < s <= 1023 for s in sizes) and max(sizes) > 1

    # [head, key, lane] integer dot products, with grouped K/V heads.
    vectors = projected.to(device="cuda", dtype=torch.int64)
    group = torch.arange(32, device="cuda") // 8
    q = vectors[:32, rank]
    k = vectors[32 + group]
    v = vectors[36 + group]
    classifiers = record["head_classifiers"]
    assert [r["head"] for r in classifiers] == list(range(32))
    shifts = [r["score_shift"] for r in classifiers]
    streaming = [r["streaming"] for r in classifiers]
    key = torch.arange(tokens, device="cuda")
    window = (key < 32) | (key >= tokens - 32)
    allowed = (~torch.tensor(streaming, device="cuda")[:, None]) | window[None, :]
    mass = torch.tensor(sizes, device="cuda")[None, :] * allowed
    scores = math_model.score_codes((q[:, None, :] * k).sum(-1), torch.tensor(shifts, device="cuda")[:, None])
    probability = math_model.probabilities(scores, mass)
    stored = load_tensor("attention_probabilities", torch.uint16, (32, tokens, tokens))[:,rank]
    assert torch.equal(probability.cpu(), stored.to(torch.int64))
    accum = (probability[:, :, None] * v).sum(1).cpu()
    stored_accum = load_tensor("attention_accumulators", torch.int32, (32, tokens, 64))[:,rank]
    assert torch.equal(accum, stored_accum.to(torch.int64))

    weights = json.loads(projection.read_text())
    assert weights["layer"] == layer and weights["output_exponents"] == record["output_exponents"]
    for name, field in (("weight_units.hex","weight_exponents"), ("output_units.hex","output_exponents")):
        path = projection.parent / name
        assert digest(path) == weights["files"][name]["sha256"]
        assert words(path) == [i & 255 for i in weights[field]]
    group_units = record["projection_output_exponents"][36:40]
    common, codes = context_reference(accum.tolist(), [group_units[h//8] for h in range(32)],
                                      weights["weight_exponents"], weights["output_exponents"])
    frozen_codes = load_tensor("output_input", torch.int8, (tokens, 2048))[rank]
    assert codes == frozen_codes.tolist() and common == record["output_input_exponents"][rank]
    output.mkdir(parents=True)
    for name, rows, width in [("q", projected[:32,rank].tolist(), 8),
                              ("k", projected[32:36].reshape(-1,64).tolist(), 8),
                              ("v", projected[36:40].reshape(-1,64).tolist(), 8),
                              ("gold", accum.tolist(), 32)]:
        (output / f"trained32_{name}.hex").write_text("".join(
            f"{packed(row,width):0{width*16}x}\n" for row in rows))
    config = [packed(streaming,1), packed(shifts,7), packed(group_units,9),
              packed(weights["weight_exponents"],9), packed(weights["output_exponents"],9), common & 1023]
    (output/"cfg.hex").write_text("".join(f"{x:072x}\n" for x in config))
    (output/"sizes.hex").write_text("".join(f"{x:03x}\n" for x in sizes))
    (output/"codes.hex").write_text("".join(f"{c & 255:02x}\n" for c in codes))
    for p in (model/"receipt.json", projection, capture, cache_path, numeric_source, Path(__file__).resolve()):
        files[str(p.relative_to(ROOT))] = digest(p)
    report = dict(layer=layer,query_rank=rank,retained_tokens=tokens,visible_keys=tokens,
                  model_question_id=record["questionId"],gpu=torch.cuda.get_device_name(),
                  streaming_heads=sum(streaming),retrieval_heads=32-sum(streaming),max_causal_size=max(sizes),
                  keys_with_size_above_one=sum(s>1 for s in sizes),dense_pairs=32*tokens,
                  selected_pairs=int(allowed.sum()),matched_probabilities=32*tokens,
                  matched_accumulators=2048,matched_frozen_context_bytes=2048,common_unit=common,
                  classification_input="Frozen trained head decisions supplied to the broker",
                  input_sha256=files,artifact_sha256={p.name:digest(p) for p in sorted(output.glob("*.hex"))})
    (output/"reference.json").write_text(json.dumps(report,indent=2)+"\n")
    print(f"TRAINED_WINDOW_REFERENCE_PASS selected_pairs={report['selected_pairs']} common_unit={common}")


if __name__ == "__main__":
    main()
