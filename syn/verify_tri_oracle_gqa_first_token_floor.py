"""Measure the error floor imposed by the first token in saved Graph Question Answering runs."""
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
import re

from tokenizers import Tokenizer

from verify_tri_oracle_gqa_accuracy_loss import DATA, ROOT, jsonl, matched, read, sha

RECORDS = ROOT / "records"
PROTOCOL = RECORDS / "wac_gqa_accuracy_protocol_result.json"
TARGETS = RECORDS / "paper_result_targets.json"
DENSE = RECORDS / "gqa_testdev_dense_reference_result.json"
CLIPPED = RECORDS / "tri_oracle_full_calibrated_clipped_accuracy.json"
WORD_PREFIX = re.compile(r"▁?[A-Za-z0-9]+", re.ASCII)
DECODER = [
    {"type": "Replace", "pattern": {"String": "▁"}, "content": " "},
    {"type": "ByteFallback"},
    {"type": "Fuse"},
    {"type": "Strip", "content": " ", "start": 1, "stop": 0},
]


def audit():
    assert __debug__ and not Path("/.dockerenv").exists()
    evidence = {}

    def pin(path, expected=None):
        key = str(path.relative_to(ROOT))
        value = sha(path)
        assert expected is None or value == expected, path
        evidence[key] = value
        return path

    protocol, target, dense, clipped = (read(pin(path)) for path in (PROTOCOL, TARGETS, DENSE, CLIPPED))
    label_path = DATA / "testdev_balanced_questions.json"
    tokenizer_path = DATA.parent / "tiny_llava_v1/tokenizer.json"
    for path in (label_path, tokenizer_path, ROOT / target["source"]):
        pin(path, protocol["input_sha256"][str(path)])
    labels = read(label_path)
    config = read(tokenizer_path)
    assert config["decoder"] == {"type": "Sequence", "decoders": DECODER}
    assert any(row["id"] == 2 and row["content"] == "</s>" and row["special"]
               for row in config["added_tokens"])
    added = {row["id"] for row in config["added_tokens"]}
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    observed = {}
    for name, report in (("dense_reference", dense), ("full_calibrated_clip", clipped)):
        folder = DATA / name
        outputs = folder / "predictions.jsonl"
        receipt = folder / "receipt.json"
        for path in (outputs, receipt):
            pin(path, report["evidence_sha256"][str(path.relative_to(ROOT))])
        manifest = read(pin(folder / "inputs.json", read(receipt)["inputs_sha256"]))
        assert manifest.get("revision", manifest.get("checkpoint_revision")) == protocol["checkpoint_revision"]
        assert manifest["prompt"] == protocol["prompt"]
        rows = jsonl(outputs)
        assert rows.keys() == labels.keys() and len(rows) == report["questions"] == protocol["questions"]
        scores = {key: matched(row, labels[key]["answer"], tokenizer, protocol["decoder_max_new_tokens"])
                  for key, row in rows.items()}
        assert sum(scores.values()) == report["exact_matches"]
        observed[name] = rows, scores

    dense_rows, dense_score = observed["dense_reference"]
    clip_rows, clip_score = observed["full_calibrated_clip"]
    by_type = defaultdict(Counter)
    for key, label in labels.items():
        group = by_type[label["types"]["structural"]]
        reference_hit, candidate_hit = dense_score[key], clip_score[key]
        first = clip_rows[key]["tokens"][0]
        changed = first != dense_rows[key]["tokens"][0]
        answer = label["answer"]
        text = tokenizer.id_to_token(first)
        certified = first not in added and WORD_PREFIX.fullmatch(text) is not None
        # The decoder cannot remove a leading regular ASCII word after
        # whitespace trimming. Byte fallback only joins adjacent byte tokens.
        # Remaining tokens can append characters while this prefix persists.
        incompatible = (first == 2 and answer != "") or (
            certified and not answer.startswith(text.removeprefix("▁").lower())
        )
        assert not incompatible or not candidate_hit
        dense_only = reference_hit and not candidate_hit
        group.update(questions=1, dense_hits=int(reference_hit), clipped_hits=int(candidate_hit),
                     dense_only_errors=int(dense_only), clipped_only_hits=int(candidate_hit and not reference_hit),
                     dense_only_with_changed_first_token=int(dense_only and changed),
                     dense_only_with_certified_incompatible_prefix=int(dense_only and incompatible),
                     certified_incompatible_prefix=int(incompatible))

    totals = Counter()
    for group in by_type.values():
        totals.update(group)
    count = totals["questions"]
    dense_correct, clipped_correct = totals["dense_hits"], totals["clipped_hits"]
    observed_drop_pp = Decimal(100) * (dense_correct - clipped_correct) / count
    paper = target["accuracy_and_energy"]["TinyLLaVA-v1"]["GQA"]
    paper_score = Decimal(str(paper["accuracy"]))
    paper_loss = Decimal(str(paper["reported_accuracy_loss"]))
    paper_implied_dense = paper_score + paper_loss
    high_limit = count - totals["certified_incompatible_prefix"]
    min_absolute = int((paper_score * count / 100).to_integral_value(rounding=ROUND_CEILING))
    min_paired = int((Decimal(dense_correct) - paper_loss * count / 100).to_integral_value(rounding=ROUND_CEILING))
    return dict(
        state="gqa_first_token_error_floor_independently_rescored",
        totals=dict(totals), by_question_type={key: dict(value) for key, value in sorted(by_type.items())},
        dense_accuracy_percent=100 * dense_correct / count, clipped_accuracy_percent=100 * clipped_correct / count,
        paper_reported_clipped_accuracy_percent=float(paper_score),
        paper_inferred_dense_accuracy_percent=float(paper_implied_dense),
        paper_reported_loss_percentage_points=float(paper_loss),
        local_loss_percentage_points=float(observed_drop_pp),
        extra_answers_for_paper_absolute_target=min_absolute - clipped_correct,
        extra_answers_for_paper_loss_target=min_paired - clipped_correct,
        unchanged_first_token_accuracy_upper_bound_percent=100 * high_limit / count,
        unchanged_first_token_correct_answer_upper_bound=high_limit,
        evidence_sha256=evidence | {str(Path(__file__).resolve().relative_to(ROOT)): sha(Path(__file__))},
        scope="Conservative bound on accuracy when the first answer token is held fixed. Counts use "
              "frozen software runs on the same locally labeled questions. Paper protocol and chip accuracy remain open.",
    )


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, sort_keys=True))
