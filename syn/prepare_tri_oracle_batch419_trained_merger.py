"""Measure and freeze trained image-token sign frames for native merger tests."""

import json
from pathlib import Path
import tempfile

from evaluate_tri_oracle_batch417_sparse_answers import merge_input_digests
from verify_tri_oracle_batch414_head_policy import (
    ROOT, AutoTokenizer, CLIPImageProcessorPil, Image, LlavaForConditionalGeneration, LlavaProcessor, np, torch,
)
from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_integer_reference import _dot
from tri_oracle_token_merging_reference import merge_signs


GRID = 24
TOKENS = GRID * GRID
FEATURES = 2048
PERCENTAGES = (65, 70, 75, 80, 85, 90)
THRESHOLDS = tuple((percent*FEATURES+99)//100 for percent in PERCENTAGES)


def independent_map(similarity, threshold):
    """Use precomputed CUDA matching counts [image token, image token]."""
    origins = list(range(TOKENS))
    kinds = [0] * TOKENS
    for index in range(TOKENS):
        row, column = divmod(index, GRID)
        candidates = [(origins[index-GRID], 2)] if row else []
        if column:
            candidates.append((origins[index-1], 1))
        selected = next(((origin, kind) for origin, kind in candidates
                         if similarity[index, origin] >= threshold), None)
        if selected is not None:
            origins[index], kinds[index] = selected
    return origins, kinds


@torch.inference_mode()
def main():
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    check_memory(16 * GIB)
    assert torch.cuda.mem_get_info()[0] > 12 * GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.cuda.reset_peak_memory_stats()
    records = ROOT / "records"
    prior_path = records / "batch416_vqa_head_policy_result.json"
    prior = json.loads(prior_path.read_text())
    assert prior["state"] == "frozen_head_policy_measured_on_vqa_pilot"
    manifest_path = ROOT / ".cache/model_reference/vqav2_pilot/manifest.json"
    hashes = prior["source_sha256"].copy()
    merge_input_digests(hashes, {str(path): sha256(path) for path in
                        (Path(__file__), prior_path, manifest_path, ROOT / "syn/tri_oracle_token_merging_reference.py",
                         ROOT / "syn/evaluate_tri_oracle_batch417_sparse_answers.py")})
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    samples = json.loads(manifest_path.read_text())["samples"]
    assert len(samples) == len(prior["cases"]) == 64
    cache = ROOT / ".cache/model_reference"
    fixture = cache / "batch419"
    output = records / "batch419_trained_merger_fixture.json"
    assert not fixture.exists() and not output.exists()

    model_dir = cache / "tiny_llava_v1"
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    processor = LlavaProcessor(
        image_processor=CLIPImageProcessorPil.from_pretrained(model_dir, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1,
    )
    model = LlavaForConditionalGeneration.from_pretrained(
        model_dir, local_files_only=True, dtype=torch.float32, attn_implementation="sdpa", use_kernels=False,
    ).to("cuda").eval()
    layers = model.model.language_model.layers
    assert len(layers) == prior["layers_per_question"] == 22
    assert model.config.vision_config.image_size == GRID*model.config.vision_config.patch_size
    first_image_token = None
    captured = {}

    def hook(index):
        def before(_module, args, kwargs):
            """Read normalized hidden [1, sequence token, feature] entering attention.

            Retain only the sign of the contiguous image grid [image token, feature].
            """
            hidden = args[0] if args else kwargs["hidden_states"]
            assert hidden.shape[0] == 1 and hidden.shape[-1] == FEATURES and index not in captured
            captured[index] = hidden[0, first_image_token:first_image_token+TOKENS] < 0
            assert captured[index].shape == (TOKENS, FEATURES)
        return before

    handles = [layer.self_attn.register_forward_pre_hook(hook(index), with_kwargs=True)
               for index, layer in enumerate(layers)]
    totals = np.zeros((len(THRESHOLDS), 3), dtype=np.int64)  # [threshold, decision kind].
    by_layer = np.zeros((len(layers), len(THRESHOLDS), 3), dtype=np.int64)
    cases, anchor_maps, anchor_signs = [], [], []
    try:
        for case_index, sample in enumerate(samples):
            check_memory(12 * GIB)
            with Image.open(ROOT / sample["image"]) as opened:
                image = opened.convert("RGB")
            prompt = "USER: <image>\n" + sample["question"] + "\nAnswer the question using a single word or phrase.\nASSISTANT:"
            batch = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
            # The image placeholder expansion identifies the original raster grid in the sequence.
            positions = (batch["input_ids"][0] == model.config.image_token_index).nonzero().flatten().tolist()
            assert len(positions) == TOKENS and positions == list(range(positions[0], positions[0]+TOKENS))
            first_image_token = positions[0]
            assert batch["pixel_values"].shape == (1, 3, 336, 336)
            assert (sample["question_id"], batch["input_ids"].shape[1]) == (
                prior["cases"][case_index]["question_id"], prior["cases"][case_index]["prefill_tokens"])
            # One final vocabulary row [1, 1, vocabulary] verifies successful inference.
            logits = model(**batch, use_cache=False, logits_to_keep=1).logits
            assert logits.shape == (1, 1, 32064) and bool(torch.isfinite(logits).all())
            assert set(captured) == set(range(len(layers)))
            case_counts = np.zeros_like(totals)
            for layer_index in range(len(layers)):
                signs = captured.pop(layer_index)
                packed = np.packbits(signs.cpu().numpy(), axis=1, bitorder="little")  # [image token, sign byte].
                words = [int.from_bytes(row.tobytes(), "little") for row in packed]
                if case_index == 0:
                    anchor_signs.append(words)
                    bipolar = torch.where(signs, -1, 1).to(torch.int8)
                    # For signs in {-1,+1}, dot = matching - mismatching.
                    dot = _dot(bipolar, bipolar).cpu().numpy()
                    assert dot.shape == (TOKENS, TOKENS) and np.all(dot.diagonal() == FEATURES)
                    similarity = (dot + FEATURES) // 2
                    maps = []
                for threshold_index, threshold in enumerate(THRESHOLDS):
                    origins, kinds = merge_signs(words, GRID, FEATURES, threshold)
                    assert all(origin <= index and origins[origin] == origin for index, origin in enumerate(origins))
                    histogram = np.bincount(kinds, minlength=3)
                    assert int(histogram[0]) == len(set(origins)) and int(histogram.sum()) == TOKENS
                    case_counts[threshold_index] += histogram
                    by_layer[layer_index, threshold_index] += histogram
                    if case_index == 0:
                        assert (origins, kinds) == independent_map(similarity, threshold)
                        maps.append([(kind << 10) | origin for origin, kind in zip(origins, kinds, strict=True)])
                if case_index == 0:
                    anchor_maps.append(maps)
            totals += case_counts
            cases.append({"question_id": sample["question_id"], "first_image_token": first_image_token,
                          "decision_counts": case_counts.tolist()})
            print(f"BATCH419_CASE case={case_index} qid={sample['question_id']}", flush=True)
    finally:
        for handle in handles:
            handle.remove()

    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    with tempfile.TemporaryDirectory(dir=cache, prefix="batch419_fixture_") as name:
        staging = Path(name) / "fixture"
        staging.mkdir()
        with (staging / "signs.hex").open("x") as stream:
            stream.writelines(f"{word:0512x}\n" for layer in anchor_signs for word in layer)
        for index, threshold in enumerate(THRESHOLDS):
            with (staging / f"map_{threshold}.hex").open("x") as stream:
                stream.writelines(f"{word:03x}\n" for maps in anchor_maps for word in maps[index])
        fixture_hashes = {str(fixture / path.name): sha256(path) for path in sorted(staging.glob("*.hex"))}
        staging.rename(fixture)
    denominator = len(samples) * len(layers) * TOKENS
    assert np.all(totals.sum(axis=1) == denominator) and np.array_equal(by_layer.sum(axis=0), totals)
    report = {
        "state": "trained_image_token_merge_maps_cpu_cuda_equal_on_anchor", "scope": __doc__,
        "checkpoint_revision": prior["checkpoint_revision"], "images": len(samples), "layers_per_image": len(layers),
        "image_width": GRID, "image_height": GRID, "sign_features": FEATURES, "tokens_per_image_layer": TOKENS,
        "threshold_percentages": PERCENTAGES, "minimum_matches_inclusive": THRESHOLDS, "local_tie_priority": "up",
        "decision_columns": ["new", "left", "up"], "totals": totals.tolist(), "by_layer": by_layer.tolist(),
        "merged_fraction_by_threshold": (totals[:, 1:].sum(axis=1)/denominator).tolist(), "cases": cases,
        "anchor_question_id": samples[0]["question_id"], "anchor_cpu_cuda_map_comparisons": len(layers)*len(THRESHOLDS)*TOKENS,
        "anchor_cuda_pairwise_similarities": len(layers)*TOKENS*TOKENS,
        "prefill_inputs_merged_during_inference": False, "hardware_trained_merger_verified": False,
        "full_paper_results_matched": False, "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
        "source_sha256": hashes, "fixture": str(fixture), "files_sha256": fixture_hashes,
    }
    with output.open("x") as stream:
        stream.write(json.dumps(report, separators=(",", ":")) + "\n")
    print("BATCH419_FIXTURE_READY " + json.dumps(report["merged_fraction_by_threshold"]), flush=True)


if __name__ == "__main__":
    main()
