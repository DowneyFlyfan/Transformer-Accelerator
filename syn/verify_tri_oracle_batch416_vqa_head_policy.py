"""Measure the frozen head policy on the existing Visual Question Answering v2 pilot."""

import gzip
import json
from pathlib import Path

from verify_tri_oracle_batch414_head_policy import (
    ALPHA, HEADS, KEY_HEADS, ROOT, TILE, WIDTH, AutoTokenizer, CLIPImageProcessorPil,
    Image, LlavaForConditionalGeneration, LlavaProcessor, apply_rotary_pos_emb,
    causal_geometry, classify_layer, np, torch,
)
from run_tri_oracle_batch396_masks import GIB, check_memory, sha256


@torch.inference_mode()
def main():
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    check_memory(16 * GIB)
    assert torch.cuda.mem_get_info()[0] > 12 * GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.cuda.reset_peak_memory_stats()
    policy_path = ROOT / "records/batch414_head_policy_result.json"
    fixture_path = ROOT / "records/vqav2_pilot_data_qualification.json"
    policy = json.loads(policy_path.read_text())
    qualification = json.loads(fixture_path.read_text())
    assert policy["state"] == "frozen_head_policy_measured_across_pinned_model"
    assert (policy["tile_keys"], policy["local_ratio_threshold"], policy["alpha_scaled_score_units"]) == (TILE, 1, ALPHA)
    assert qualification["dataset_preparation_passed"] is True
    assert qualification["sample_count"] == qualification["unique_images"] == 64
    manifest_path = ROOT / qualification["manifest"]
    assert sha256(manifest_path) == qualification["manifest_sha256"]
    manifest = json.loads(manifest_path.read_text())
    samples = manifest["samples"]
    assert len(samples) == len({sample["question_id"] for sample in samples}) == 64
    assert set(manifest["images"]) == {str(sample["image_id"]) for sample in samples}
    assert all(ROOT / sample["image"] == ROOT / manifest["images"][str(sample["image_id"])]["path"] for sample in samples)
    hashes = policy["source_sha256"] | {
        str(path): sha256(path) for path in (policy_path, fixture_path, manifest_path, Path(__file__))
    } | {str(ROOT / image["path"]): image["sha256"] for image in manifest["images"].values()}
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    output = ROOT / "records/batch416_vqa_head_policy_result.json"
    details_path = ROOT / ".cache/model_reference/batch416_vqa_head_policy_details.json.gz"
    assert not output.exists() and not details_path.exists()

    model_dir = ROOT / ".cache/model_reference/tiny_llava_v1"
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    processor = LlavaProcessor(
        image_processor=CLIPImageProcessorPil.from_pretrained(model_dir, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1,
    )
    model = LlavaForConditionalGeneration.from_pretrained(
        model_dir, local_files_only=True, dtype=torch.float32, attn_implementation="sdpa", use_kernels=False,
    ).to("cuda").eval()
    layers = model.model.language_model.layers
    assert len(layers) == policy["layers_per_image"] == 22
    captured = {}

    def hook(index):
        def before(module, args, kwargs):
            """Project actual hidden [1, token, hidden] using trained weights.
            Save query [head, token, feature] and key [key head, token, feature].
            """
            hidden = args[0] if args else kwargs["hidden_states"]
            query = module.q_proj(hidden).reshape(1, -1, HEADS, WIDTH).transpose(1, 2)
            key = module.k_proj(hidden).reshape(1, -1, KEY_HEADS, WIDTH).transpose(1, 2)
            query, key = apply_rotary_pos_emb(query, key, *kwargs["position_embeddings"])
            assert index not in captured
            captured[index] = (query[0], key[0], module.scaling)
        return before

    handles = [layer.self_attn.register_forward_pre_hook(hook(index), with_kwargs=True) for index, layer in enumerate(layers)]
    cases, details = [], []
    cpu_scores = 0
    try:
        for index, sample in enumerate(samples):
            check_memory(12 * GIB)
            with Image.open(ROOT / sample["image"]) as opened:
                image = opened.convert("RGB")
            prompt = "USER: <image>\n" + sample["question"] + "\nAnswer the question using a single word or phrase.\nASSISTANT:"
            batch = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
            # One final logit row [batch=1, token=1, vocabulary] checks successful prefill.
            logits = model(**batch, use_cache=False, logits_to_keep=1).logits
            assert logits.shape == (1, 1, 32064) and bool(torch.isfinite(logits).all())
            assert set(captured) == set(range(len(layers)))
            sequence = captured[0][0].shape[1]
            geometry = causal_geometry(sequence)
            layer_results = [classify_layer(*captured.pop(layer), geometry, index == 0)[0]
                             for layer in range(len(layers))]
            if index == 0:
                cpu_scores = len(layers) * HEADS * int(np.count_nonzero(geometry[2]))
            counts = [[item["fixed_streaming"], item["float_streaming"], len(item["changed_head_ids"])]
                      for item in layer_results]
            fixed, floating, changes = map(sum, zip(*counts))
            cases.append({"question_id": sample["question_id"], "prefill_tokens": sequence,
                          "fixed_streaming": fixed, "float_streaming": floating, "changed_decisions": changes,
                          "layer_counts": counts})
            details.append(layer_results)
            print(f"BATCH416_CASE case={index} tokens={sequence} fixed={fixed} float={floating} changed={changes}", flush=True)
    finally:
        for handle in handles:
            handle.remove()

    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    encoded = json.dumps(details, separators=(",", ":")).encode()
    with details_path.open("xb") as stream:
        stream.write(gzip.compress(encoded, mtime=0))
    assert gzip.decompress(details_path.read_bytes()) == encoded
    decisions = len(cases) * len(layers) * HEADS
    fixed = sum(case["fixed_streaming"] for case in cases)
    floating = sum(case["float_streaming"] for case in cases)
    changed = sum(case["changed_decisions"] for case in cases)
    result = {
        "state": "frozen_head_policy_measured_on_vqa_pilot", "scope": __doc__, "checkpoint_revision": policy["checkpoint_revision"],
        "dataset": "Visual Question Answering v2 validation pilot", "questions": len(cases), "layers_per_question": len(layers),
        "heads_per_layer": HEADS, "head_decisions": decisions, "fixed_streaming": fixed, "float_streaming": floating,
        "changed_decisions": changed, "fixed_streaming_fraction": fixed/decisions, "float_streaming_fraction": floating/decisions,
        "paper_figure": "31.6.4", "paper_reported_streaming_fraction": 0.62, "fixed_fraction_minus_paper": fixed/decisions - 0.62,
        "local_ratio_threshold": 1, "alpha_scaled_score_units": ALPHA, "tile_keys": TILE,
        "anchor_cpu_verified_selected_scores": cpu_scores, "runtime_token_merging_applied": False,
        "task_accuracy_measured": False, "full_paper_results_matched": False, "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
        "layer_counts_columns": ["fixed_streaming", "float_streaming", "changed_decisions"], "cases": cases,
        "local_details": str(details_path), "local_details_sha256": sha256(details_path), "source_sha256": hashes,
    }
    with output.open("x") as stream:
        stream.write(json.dumps(result, separators=(",", ":")) + "\n")
    print(f"BATCH416_VERIFIED decisions={decisions} fixed={fixed} float={floating} changed={changed}", flush=True)


if __name__ == "__main__":
    main()
