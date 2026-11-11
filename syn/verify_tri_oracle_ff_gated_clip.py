"""Check the gated-product clip identity and re-score the fixed replay."""

import argparse
import json
from pathlib import Path

from verify_tri_oracle_ff_position_attribution import REFERENCE, ROOT, load_official_sources, read, score_cases, sha256


def down_code(value, shift):
    magnitude = abs(value)
    if shift:
        magnitude = (magnitude + (1 << (shift - 1))) >> shift
    return max(-128, min(127, -magnitude if value < 0 else magnitude))


def check_policy_bound(policy_paths):
    bounds = {}
    for path in policy_paths:
        settings = []
        for layer in read(path)["layers"]:
            settings.extend([layer["fallback"], *layer["buckets"]] if "fallback" in layer else [layer])
        maximum = max(max(0, item["maximum_up_gain_bits"] + item["down_shift_offset"]) for item in settings)
        bounds[path.parent.name] = dict(settings=len(settings), down_shift_upper_bound=maximum)
    maximum = max(item["down_shift_upper_bound"] for item in bounds.values())
    # Down requantization is monotone in its input for a fixed shift. If the
    # signed 16-bit endpoints already give the signed 8-bit endpoints, every
    # value beyond the signed 16-bit range gives the same final output code.
    assert all(down_code(-32768, shift) == -128 and down_code(32767, shift) == 127
               for shift in range(maximum + 1))
    assert down_code(65536, 9) != down_code(32767, 9)
    return bounds


def verify(case):
    raw_path, native_path, console = (case / name for name in ("receipt.json", "native_receipt.json", "console.log"))
    raw, native = read(raw_path), read(native_path)
    assert raw["state"] == "feedforward_gated_clip_counterfactual_scored"
    assert native["state"] == "native_exit" and native["native_exit_status"] == 0
    assert native["log_sha256"] == sha256(console)
    assert raw["questions"] == raw["reproduced_dense_integer_cases"] == 256 and raw["decoder_layers"] == 22
    pins = raw["source_sha256"]
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    manifest = REFERENCE / "grouped_precision_holdout/manifest.json"
    baseline = REFERENCE / "dense_integer_holdout/receipt.json"
    policy_paths = [REFERENCE / f"{name}/layer_policy.json" for name in ("format322", "format335")]
    assert all(pins[str(path)] == sha256(path) for path in (manifest, baseline, *policy_paths))
    bounds = check_policy_bound(policy_paths)
    samples = read(manifest)["samples"]
    questions = [row["question_id"] for row in samples]
    assert [int(line.split()[-1]) for line in console.read_text().splitlines()
            if line.startswith("FF_GATED_CLIP_CASE ")] == questions
    control, wide = (raw["answers"][name] for name in ("dense_integer", "wide_later_gated_product"))
    assert len(control) == len(wide) == 256
    assert all(row["wide_gated_rows"] == row["formerly_clipped"] == 0 for row in control)
    assert all(row["wide_gated_rows"] == row["prefill_rows"] + row["decode_rows"] - 22 for row in wide)
    assert all(row["prefill_skipped"] == row["decode_skipped"] == 0 for row in control + wide)
    reference = read(baseline)
    for rows in (control, wide):
        stripped = [{key: value for key, value in row.items() if key not in ("wide_gated_rows", "formerly_clipped")}
                    for row in rows]
        assert stripped == reference["cases"]
    evaluator, normalizer, sources = load_official_sources(ROOT)
    assert all(pins[name] == digest for name, digest in sources.items())
    score = score_cases(samples, wide, evaluator, normalizer)
    score["official_vqa_consensus_percent"] = score.pop("official_vqa_consensus_percent_on64")
    assert score == raw["scores"]["dense_integer"] == raw["scores"]["wide_later_gated_product"] == reference["score"]
    formerly_clipped = sum(row["formerly_clipped"] for row in wide)
    assert formerly_clipped > 0
    paths = (Path(__file__), raw_path, native_path, console, manifest, *policy_paths)
    return dict(state="gated_product_clip_redundant_for_verified_formats", questions=256, decoder_layers=22,
        score_percent=score["official_vqa_consensus_percent"], identical_cases=256, formerly_clipped_codes=formerly_clipped,
        wide_gated_rows=sum(row["wide_gated_rows"] for row in wide), policy_bounds=bounds,
        counterexample_at_shift_nine=True, elapsed_seconds=raw["wall_seconds"],
        evidence_sha256={str(path.relative_to(ROOT)): sha256(path) for path in paths},
        scope="The intermediate clip cannot change signed 8-bit down inputs under the verified shifts. This does not test wider shift policies.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    args = parser.parse_args()
    case = args.case.resolve()
    result = verify(case)
    with (case / "verified.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], result["score_percent"], result["formerly_clipped_codes"], flush=True)
