"""Score complete VQAv2 validation predictions using the pinned evaluator."""

import argparse
from collections import Counter
from itertools import islice
import json
from pathlib import Path
from zipfile import ZipFile

from score_tri_oracle_format326_vqav2 import load_official_sources, score_cases, sha


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".cache/model_reference/vqav2_pilot"
QUESTION_ARCHIVE = DATA / "v2_Questions_Val_mscoco.zip"
ANNOTATION_ARCHIVE = DATA / "v2_Annotations_Val_mscoco.zip"
ARCHIVES = {
    QUESTION_ARCHIVE: "e71f6c5c3e97a51d050f28243e262b28cd0c48d11a6b4632d769d30d3f93222a",
    ANNOTATION_ARCHIVE: "0caae7c8d1dafd852727f5ac046bc1efca9b72026bd6ffa34fc489f3a7b3291e",
}


def load_validation():
    for path, digest in ARCHIVES.items():
        if sha(path) != digest:
            raise ValueError(f"Validation archive changed: {path}")
    with ZipFile(QUESTION_ARCHIVE) as archive:
        questions = json.loads(archive.read("v2_OpenEnded_mscoco_val2014_questions.json"))
    with ZipFile(ANNOTATION_ARCHIVE) as archive:
        annotations = json.loads(archive.read("v2_mscoco_val2014_annotations.json"))
    if questions["data_subtype"] != "val2014" or annotations["data_subtype"] != "val2014":
        raise ValueError("Both archives must use the val2014 split")
    images = {row["question_id"]: row["image_id"] for row in questions["questions"]}
    labels = {row["question_id"]: row for row in annotations["annotations"]}
    if (len(images) != 214354 or len(images) != len(questions["questions"])
            or len(labels) != len(annotations["annotations"]) or labels.keys() != images.keys()
            or len(set(images.values())) != 40504):
        raise ValueError("Incomplete or duplicate validation annotations")
    for question_id, row in labels.items():
        answer_ids = {answer["answer_id"] for answer in row["answers"]}
        if (row["image_id"] != images[question_id] or len(row["answers"]) != 10
                or answer_ids != set(range(1, 11))):
            raise ValueError(f"Invalid annotation for question {question_id}")
    return labels


def score_predictions(labels, predictions, evaluator, normalizer):
    """Score the requested cohort in bounded batches and aggregate exact points."""
    if not labels:
        raise ValueError("Empty scoring cohort")
    predictions = iter(predictions)
    seen = set()
    totals, counts = Counter(), Counter()
    while batch := list(islice(predictions, 1024)):
        samples = []
        for row in batch:
            question_id, image_id, answer = (row.get(key) for key in ("question_id", "image_id", "answer"))
            if (type(question_id) is not int or question_id not in labels
                    or question_id in seen):
                raise ValueError(f"Unknown or duplicate prediction question: {question_id}")
            label = labels[question_id]
            if type(image_id) is not int or image_id != label["image_id"] or not isinstance(answer, str):
                raise ValueError(f"Wrong image or missing answer for question {question_id}")
            seen.add(question_id)
            samples.append(label)
        scores = score_cases(samples, batch, evaluator, normalizer)["per_question_score"]
        for label in samples:
            points = scores[str(label["question_id"])]
            if points not in (0, 30, 60, 90, 100):
                raise ValueError(f"Unexpected ten-annotator score: {points}")
            kind = label["answer_type"]
            totals[kind] += int(points)
            counts[kind] += 1
    if len(seen) != len(labels):
        raise ValueError(f"Missing {len(labels) - len(seen)} predictions")
    return {
        "questions": len(seen),
        "official_consensus_points": sum(totals.values()),
        "official_consensus_percent": round(sum(totals.values()) / len(seen), 2),
        "per_answer_type_percent": {kind: round(totals[kind] / count, 2)
                                    for kind, count in sorted(counts.items())},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path,
                        help="JSON Lines with question_id, image_id and answer for every validation question")
    args = parser.parse_args()
    digest = sha(args.predictions)
    evaluator, normalizer, sources = load_official_sources(ROOT)
    labels = load_validation()
    with args.predictions.open() as stream:
        scores = score_predictions(labels, map(json.loads, stream), evaluator, normalizer)
    if sha(args.predictions) != digest:
        raise ValueError("Predictions changed during scoring")
    result = dict(split="VQAv2 val2014", predictions_sha256=digest, **scores,
                  archive_sha256={path.name: value for path, value in ARCHIVES.items()},
                  evaluator_source_sha256={Path(path).name: value for path, value in sources.items()})
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
