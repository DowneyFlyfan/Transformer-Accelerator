"""Check the local balanced GQA protocol and the down-scale calibration split."""

import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image
from pyarrow.parquet import ParquetFile

from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256, sha


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / ".cache/model_reference"
GQA = MODEL / "gqa_testdev"
SCORING_REFERENCE = "https://cs.stanford.edu/people/dorarad/gqa/evaluate.html"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pixel_identity(stream):
    with Image.open(stream) as opened:
        image = opened.convert("RGB")
        dimensions = image.size
        identity = hashlib.sha256()
        for size in dimensions:
            identity.update(size.to_bytes(4, "big"))
        identity.update(image.tobytes())
    return dimensions, identity.hexdigest()


def audit():
    evidence = {}

    def pin(path, expected=None):
        digest = sha(path)
        require(expected is None or digest == expected, f"Changed evidence: {path}")
        require(evidence.setdefault(str(path), digest) == digest, f"Inconsistent evidence: {path}")
        return digest

    def read(path, expected=None):
        pin(path, expected)
        return json.loads(path.read_text())

    dataset_path = GQA / "dataset_verification.json"
    dataset = read(dataset_path)
    questions_path = GQA / "testdev_balanced_questions.json"
    questions = read(questions_path, dataset["question_sha256"])
    images_path = GQA / "testdev_balanced_images.parquet"
    pin(images_path, dataset["image_archive_sha256"])
    require(len(questions) == dataset["questions"] == 12578, "Wrong balanced question count")
    require(all(item["isBalanced"] is True and isinstance(item["answer"], str) and item["answer"]
                for item in questions.values()), "Unbalanced or unlabeled question")
    question_images = {item["imageId"] for item in questions.values()}
    require(question_images == dataset["images"].keys() and len(question_images) == dataset["unique_images"] == 398,
            "Question and image coverage differ")

    configuration = {name: read(GQA / name / "inputs.json")
                     for name in ("dense_reference", "pruned_reference", "down_scale_full")}
    dense, pruned, calibrated = configuration.values()
    require(dense["revision"] == pruned["checkpoint_revision"] == calibrated["checkpoint_revision"],
            "Checkpoint revision differs between benchmark runs")
    require(dense["prompt"] == pruned["prompt"] == calibrated["prompt"], "Prompt differs between benchmark runs")
    require(dense["max_new_tokens"] == pruned["decoder_max_new_tokens"] == calibrated["decoder_max_new_tokens"],
            "Generation budget differs between benchmark runs")
    require(calibrated["questions"] == len(questions), "Calibrated run has a different denominator")
    tokenizer = MODEL / "tiny_llava_v1/tokenizer.json"
    pin(tokenizer)
    for path in (dataset_path, questions_path, images_path, tokenizer):
        require(all(manifest["input_sha256"][str(path)] == evidence[str(path)] for manifest in configuration.values()),
                f"Benchmark manifests disagree on {path}")

    calibration_path = MODEL / "down_output_scale_calibration/receipt.json"
    calibration = read(calibration_path, calibrated["calibration_sha256"])
    capture_path = ROOT / "records/format320_multi_image_range_audit.json"
    capture = read(capture_path, calibration["input_sha256"][str(capture_path)])
    require(capture["labels_used"] is False and capture["checkpoint_revision"] == calibrated["checkpoint_revision"],
            "Calibration label or checkpoint provenance changed")
    manifest_path = MODEL / "ai2d285/inputs.json"
    manifest = read(manifest_path, capture["source_sha256"][str(manifest_path)])
    calibration_pixels = {"calibration": set(), "held": set()}
    for case, archived in zip(manifest["cases"], capture["inputs"], strict=True):
        path = ROOT / case["image"]
        pin(path, case["image_sha256"])
        with path.open("rb") as stream:
            _, pixel = pixel_identity(stream)
        require(pixel == case["pixel_sha256"] == archived["image_pixel_sha256"], f"Calibration image changed: {path}")
        calibration_pixels[archived["split"]].add(pixel)
    require([len(group) for group in calibration_pixels.values()] == [8, 8]
            and calibration_pixels["calibration"].isdisjoint(calibration_pixels["held"]),
            "Expected two distinct eight-image calibration splits")

    benchmark_pixels = {}
    for batch in ParquetFile(images_path).iter_batches(batch_size=8, columns=["id", "image"]):
        for row in batch.to_pylist():
            key, encoded = row["id"], row["image"]["bytes"]
            expected = dataset["images"][key]
            require(key not in benchmark_pixels and hashlib.sha256(encoded).hexdigest() == expected["sha256"],
                    f"Wrong or duplicate image: {key}")
            dimensions, pixel = pixel_identity(io.BytesIO(encoded))
            require(list(dimensions) == expected["dimensions"], f"Wrong image dimensions: {key}")
            benchmark_pixels[key] = pixel
    require(benchmark_pixels.keys() == question_images, "Benchmark image decode did not cover every question")
    overlap = {name: sorted(set(benchmark_pixels.values()) & group) for name, group in calibration_pixels.items()}
    require(not any(overlap.values()), "Decoded calibration images overlap with benchmark images")

    pin(ROOT / PAPER_RELATIVE, PAPER_SHA256)
    targets = read(ROOT / "records/paper_result_targets.json")
    target = targets["accuracy_and_energy"]["TinyLLaVA-v1"]["GQA"]["accuracy"]
    pin(Path(__file__).resolve())
    require(all(sha(name) == digest for name, digest in evidence.items()), "Evidence changed during audit")
    return dict(state="balanced_gqa_testdev_inputs_and_calibration_isolation_verified",
                checkpoint_revision=calibrated["checkpoint_revision"], questions=len(questions), images=len(benchmark_pixels),
                calibration_images={name: len(group) for name, group in calibration_pixels.items()},
                exact_decoded_image_overlap={name: len(group) for name, group in overlap.items()},
                prompt=calibrated["prompt"], decoder_max_new_tokens=calibrated["decoder_max_new_tokens"],
                answer_processing="Trim whitespace and trailing periods, lowercase, then exact match",
                scoring_reference=SCORING_REFERENCE, paper_reported_accuracy_percent=target,
                paper_prompt_and_split_confirmed=False, mapped_execution_accuracy_verified=False, input_sha256=evidence)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit()
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], result["questions"], result["images"], result["exact_decoded_image_overlap"], flush=True)
