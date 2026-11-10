"""Select a hardware ratio on separate diagram inputs and score it on the fixed pilot."""

import hashlib
import inspect
import json
from fractions import Fraction
from pathlib import Path

from evaluate_tri_oracle_batch417_sparse_answers import (
    HeadPolicy, RECENT_TOKENS, SINK_TOKENS, merge_input_digests,
)
from verify_tri_oracle_batch414_head_policy import (
    ALPHA, HEADS, ROOT, TILE, AutoTokenizer, CLIPImageProcessorPil, Image,
    LlavaForConditionalGeneration, LlavaProcessor, torch,
)
from transformers.models.llama.modeling_llama import ALL_ATTENTION_FUNCTIONS, LlamaAttention

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from score_tri_oracle_format326_vqav2 import load_official_sources, score_cases


RATIOS = ((1, 1), (5, 4), (3, 2), (2, 1), (3, 1), (4, 1), (6, 1), (8, 1), (16, 1),
          (32, 1), (64, 1), (128, 1), (255, 1))


def pixel_digest(path):
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        return hashlib.sha256(f"{image.width}x{image.height}:".encode() + image.tobytes()).hexdigest()


@torch.inference_mode()
def main():
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    check_memory(16 * GIB)
    assert torch.cuda.mem_get_info()[0] > 12 * GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.cuda.reset_peak_memory_stats()
    records = ROOT / "records"
    pilot_path = ROOT / ".cache/model_reference/vqav2_pilot/manifest.json"
    calibration_path = ROOT / ".cache/model_reference/ai2d285/inputs.json"
    policy_path = records / "batch416_vqa_head_policy_result.json"
    prior_path = records / "batch417_sparse_answers_result.json"
    policy = json.loads(policy_path.read_text())
    original = ALL_ATTENTION_FUNCTIONS["sdpa"]
    software = (Path(inspect.getsourcefile(LlamaAttention)), Path(inspect.getsourcefile(original)))
    paths = (calibration_path, policy_path, pilot_path, prior_path, Path(__file__), *software,
             ROOT / "syn/evaluate_tri_oracle_batch417_sparse_answers.py",
             ROOT / "syn/score_tri_oracle_format326_vqav2.py")
    hashes = policy["source_sha256"].copy()
    merge_input_digests(hashes, {str(path): sha256(path) for path in paths})
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    calibration_cases = json.loads(calibration_path.read_text())["cases"]
    # Inspect pilot image identities only while establishing the split.
    pilot_images = json.loads(pilot_path.read_text())["images"].values()
    assert len(calibration_cases) == 16 and len(pilot_images) == 64
    assert {case["image_sha256"] for case in calibration_cases}.isdisjoint(image["sha256"] for image in pilot_images)
    calibration_pixels = {pixel_digest(Path(case["image"])) for case in calibration_cases}
    assert len(calibration_pixels) == 16
    assert calibration_pixels.isdisjoint(pixel_digest(ROOT / image["path"]) for image in pilot_images)
    calibration_output = records / "batch418_ratio_calibration.json"
    evaluation_output = records / "batch418_vqa_ratio_result.json"
    assert not calibration_output.exists() and not evaluation_output.exists()

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
    assert len(layers) == 22
    controller = HeadPolicy(layers, original)

    def inputs(sample, calibration):
        with Image.open(ROOT / sample["image"]) as opened:
            image = opened.convert("RGB")
        if calibration:
            options = "\n".join(f"{chr(65+index)}. {value}" for index, value in enumerate(sample["options"]))
            suffix = f"\n{options}\nAnswer with the letter only.\nASSISTANT:"
        else:
            suffix = "\nAnswer the question using a single word or phrase.\nASSISTANT:"
        prompt = "USER: <image>\n" + sample["question"] + suffix
        # Single unpadded sequence [1, token] and image [1, 3, height, width].
        batch = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
        assert batch["input_ids"].shape[0] == 1 and bool(batch["attention_mask"].all())
        return batch

    def answer(batch, mode, ratio, limit):
        prefill = batch["input_ids"].shape[1]
        controller.begin(mode, prefill, ratio=ratio)
        # Generated IDs [1, prefill + answer] use one cache position per decode step.
        generated = model.generate(**batch, max_new_tokens=limit, do_sample=False, use_cache=True)
        tokens = generated[0, prefill:].tolist()
        assert 1 <= len(tokens) <= limit and controller.calls == [len(tokens)]*len(layers)
        return {
            "answer": processor.batch_decode(generated[:, prefill:], skip_special_tokens=True)[0],
            "answer_tokens": tokens, "prefill_tokens": prefill,
            "heads_streaming": sum(controller.head_counts), "prefill_kept_pairs": controller.prefill_kept,
            "prefill_dense_pairs": controller.prefill_dense, "decode_kept_pairs": controller.decode_kept,
            "decode_dense_pairs": controller.decode_dense,
        }

    ALL_ATTENTION_FUNCTIONS["sdpa"] = controller
    try:
        cached = [inputs(sample, True) for sample in calibration_cases]
        dense = [answer(batch, "explicit_dense_mask", (1, 1), 3) for batch in cached]
        trial_results = []
        for ratio in RATIOS:
            results = [answer(batch, "live_streaming", ratio, 3) for batch in cached]
            exact = sum(a["answer_tokens"] == b["answer_tokens"] for a, b in zip(results, dense, strict=True))
            kept = sum(item["prefill_kept_pairs"] for item in results)
            total = sum(item["prefill_dense_pairs"] for item in results)
            trial_results.append({"ratio": ratio, "exact_dense_answers": exact, "prefill_pairs_kept": kept,
                                  "prefill_pairs_dense": total, "streaming_heads": sum(item["heads_streaming"] for item in results),
                                  "answers": [item["answer_tokens"] for item in results]})
            print(f"BATCH418_CALIBRATION ratio={ratio[0]}/{ratio[1]} exact={exact}/16 kept={kept} total={total}", flush=True)
        del cached
        eligible = [trial for trial in trial_results if trial["exact_dense_answers"] == 16 and
                    trial["prefill_pairs_kept"] < trial["prefill_pairs_dense"]]
        winner = min(eligible, key=lambda trial: (trial["prefill_pairs_kept"], Fraction(*trial["ratio"]))) if eligible else None
        calibration = {
            "state": "ratio_selected_on_separate_diagram_inputs" if winner else "no_ratio_preserved_all_calibration_answers",
            "checkpoint_revision": policy["checkpoint_revision"], "calibration_questions": 16,
            "pilot_images_disjoint_by_file_and_rgb_pixels": True, "ratio_candidates": RATIOS,
            "selection_rule": "Require all 16 greedy answer sequences to equal the explicit dense mask control. Among those with fewer eligible pairs, minimize kept prefill pairs, breaking ties by smaller ratio.",
            "sink_tokens": SINK_TOKENS, "recent_tokens": RECENT_TOKENS, "tile_keys": TILE, "alpha_scaled_score_units": ALPHA,
            "selected_ratio": winner["ratio"] if winner else None, "dense_answers": [item["answer_tokens"] for item in dense],
            "trials": trial_results, "source_sha256": hashes, "full_paper_results_matched": False,
        }
        with calibration_output.open("x") as stream:
            stream.write(json.dumps(calibration, indent=2) + "\n")
        if winner is None:
            print("BATCH418_NO_RATIO", flush=True)
            return

        # Freeze selection before reading or scoring any pilot questions.
        ratio = tuple(winner["ratio"])
        calibration_digest = sha256(calibration_output)
        assert sha256(prior_path) == hashes[str(prior_path)]
        prior = json.loads(prior_path.read_text())
        assert prior["state"] == "sparse_attention_answer_pilot_scored"
        assert prior["checkpoint_revision"] == policy["checkpoint_revision"]
        assert all(str(path) in prior["source_sha256"] for path in (*software,
                   ROOT / "syn/evaluate_tri_oracle_batch417_sparse_answers.py",
                   ROOT / "syn/score_tri_oracle_format326_vqav2.py"))
        merge_input_digests(hashes, prior["source_sha256"])
        assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
        samples = json.loads(pilot_path.read_text())["samples"]
        assert len(samples) == 64
        baseline = {case["question_id"]: case for case in prior["cases"]["dense"]}
        results = []
        for index, sample in enumerate(samples):
            check_memory(12 * GIB)
            item = answer(inputs(sample, False), "live_streaming", ratio, 16)
            assert item["prefill_tokens"] == baseline[sample["question_id"]]["prefill_tokens"]
            results.append(item | {"question_id": sample["question_id"], "image_id": sample["image_id"]})
            print(f"BATCH418_PILOT case={index} qid={sample['question_id']}", flush=True)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"] = original

    evaluator, normalizer, evaluator_hashes = load_official_sources(ROOT)
    score = score_cases(samples, results, evaluator, normalizer)
    assert sha256(calibration_output) == calibration_digest
    merge_input_digests(hashes, evaluator_hashes)
    merge_input_digests(hashes, {str(calibration_output): calibration_digest})
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    result = {
        "state": "separately_selected_ratio_scored_on_fixed_vqa_pilot", "scope": __doc__,
        "checkpoint_revision": policy["checkpoint_revision"], "selected_ratio": ratio,
        "questions": len(samples), "head_decisions": len(samples)*len(layers)*HEADS,
        "streaming_heads": sum(item["heads_streaming"] for item in results),
        "prefill_pairs_dense": sum(item["prefill_dense_pairs"] for item in results),
        "prefill_pairs_kept": sum(item["prefill_kept_pairs"] for item in results),
        "changed_answer_sequences": sum(item["answer_tokens"] != baseline[item["question_id"]]["answer_tokens"] for item in results),
        "official_dense_consensus_percent": prior["scores"]["dense"]["official_vqa_consensus_percent_on64"],
        "official_selected_consensus_percent": score["official_vqa_consensus_percent_on64"],
        "eligible_pairs_are_analytic_not_measured_compute": True, "runtime_token_merging_applied": False,
        "score": score, "cases": results, "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
        "source_sha256": hashes, "full_paper_results_matched": False,
    }
    with evaluation_output.open("x") as stream:
        stream.write(json.dumps(result, separators=(",", ":")) + "\n")
    print(f"BATCH418_VERIFIED ratio={ratio[0]}/{ratio[1]} score={result['official_selected_consensus_percent']}", flush=True)


if __name__ == "__main__":
    main()
