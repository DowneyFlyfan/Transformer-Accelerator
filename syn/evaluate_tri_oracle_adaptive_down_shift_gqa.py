"""Compare activation-selected shifts on the fixed GQA answer panel."""

import argparse
from collections import Counter
from copy import copy
import fcntl
import json
import os
from pathlib import Path

from evaluate_tri_oracle_weight_range_gqa import inputs as panel_inputs
from measure_tri_oracle_input_equalization import GIB, LAYERS
from run_pruned_accuracy_ablation import benchmark, decode, encode
from run_tri_oracle_full_down_code_gqa import hardware_needs_memory
from tri_oracle_integer_reference import _dot, _quantize, _requantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256

torch = benchmark.torch
MODES = ("baseline", "adaptive")
HOLDOUT = ROOT / "records/tri_oracle_gated_rounding_and_shift.json"
PROTOCOL = ROOT / "records/wac_gqa_accuracy_protocol_result.json"
JOINT = ROOT / "records/batch424_joint_pilot_result.json"
POLICIES = tuple(benchmark.REFERENCE / name / "layer_policy.json" for name in ("format322", "format335"))


def select_shift(retained, original):
    """Choose an eight-bit code scale from the retained [M,K] signed16 activations.

    M counts token rows and K is the feed-forward expansion. The original shift
    [M,1] supplies the shape and device. Return the smallest minimizing shift
    per row. The signed64 cost sums squared reconstruction errors in code units.
    """
    best_cost = torch.full_like(retained[:, 0], torch.iinfo(torch.int64).max)  # [M]
    best_shift = torch.zeros_like(original)  # [M,1]
    for candidate in range(10):
        shift = torch.full_like(original, candidate)  # [M,1]
        quantized = _requantize(retained, shift, 8)  # [M,K], saturated candidate codes
        cost = ((quantized << candidate) - retained).square().sum(1)  # [M]
        improved = cost < best_cost  # [M], preserve smallest shift at a tie
        best_shift = torch.where(improved[:, None], shift, best_shift)
        best_cost = torch.minimum(cost, best_cost)
    return best_shift


def evaluate_adaptive(reference, activation, residual, settings):
    """Use the existing gate, up, mask and weights for [M,H] activations."""
    assert settings["prune"] and settings["gate_threshold"] == settings["up_window"] == 0
    _, _, stats = reference.evaluate(activation, residual, **settings)
    codes, _ = _quantize(activation, per_row=True)  # [M,H], same signed8 input
    gate = _requantize(_dot(codes, reference.gate), stats["gate_shift"][:, None], 16)  # [M,K]
    up = _requantize(_dot(codes, reference.up), stats["up_shift"][:, None], 16)  # [M,K]
    original = stats["down_shift"][:, None]  # [M,1], current frame shift
    gated = _requantize(reference.silu_response[gate + 32768] * up,
                        torch.full_like(original, 8), 16)  # [M,K], unchanged gated codes
    norm = stats["norm_codes"]  # [M,H], original predictor input
    outliers = norm.abs() > 768  # [M,H], exact three-sigma threshold
    signs = (torch.where(norm < 0, -1, 1) * outliers).to(torch.int8)  # [M,H], signs on outliers
    skipped = (outliers.any(dim=1, keepdim=True) & (_dot(signs, reference.gate_sign) <= 0)
               & (_dot(signs, reference.up_sign) == 0))  # [M,K], original skip mask
    retained = gated.masked_fill(skipped, 0)  # [M,K], prediction applied before choosing the shift
    selected = select_shift(retained, original)  # [M,1], integer shift derived only from activations
    down = _requantize(retained, selected, 8).to(torch.int8)  # [M,K], signed down input
    raw = _dot(down, reference.down)  # [M,H], signed32 sums
    exponent = selected - 8 - stats["up_gain_bits"][:, None] + reference.down_exponent  # [M,H]
    result = torch.ldexp(raw.float(), exponent)  # [M,H], same physical output units as baseline
    stats["down_shift"] = selected[:, 0]  # [M] actual shift employed for this output
    return raw, result, stats


def install(replacement, index, weights, context):
    """Keep the initial and decoding paths. Adapt only ordinary prompt rows."""
    initial = replacement.reference.evaluate
    ordinary = copy(replacement.reference)
    ordinary.down, scales = _quantize(weights.down_proj.weight, per_row=True)  # [H,K] and [H,1]
    ordinary.down_exponent = scales.T  # [1,H], same output scales in both arms

    def dispatch(activation, residual, **settings):
        # [M,H] normalized activation and original residual from the decoder.
        first = replacement.decoder.prefill_active and context["calls"][index] == 0
        context["calls"][index] += 1
        if first:
            assert activation.shape[0] == 1
            return initial(activation, residual, **settings)
        if replacement.decoder.prefill_active and context["adaptive"]:
            context["tested_rows"][index] += activation.shape[0]
            return evaluate_adaptive(ordinary, activation, residual, settings)
        return ordinary.evaluate(activation, residual, **settings)

    replacement.reference.evaluate = dispatch


def prepare():
    dataset, labels, pins = benchmark.inputs()
    ordered, controls, _ = panel_inputs(pins)
    assert len(ordered) == len({labels[key]["imageId"] for key in ordered}) == 200
    holdout = benchmark.read(HOLDOUT)
    proof = holdout["shift_selection"]["input_distortion"]
    assert holdout["held_rows"] == 2640 and proof["improved_layers"] == LAYERS
    for name, expected in holdout["evidence_sha256"].items():
        path = ROOT / name
        assert sha256(path) == expected and pins.setdefault(str(path), expected) == expected
    protocol = benchmark.read(PROTOCOL)
    assert protocol["checkpoint_revision"] == benchmark.REVISION
    assert protocol["prompt"] == benchmark.PROMPT and not any(protocol["exact_decoded_image_overlap"].values())
    for path in (HOLDOUT, PROTOCOL, JOINT, *POLICIES, Path(__file__).resolve(),
                 Path(encode.__code__.co_filename), Path(_requantize.__code__.co_filename)):
        checksum = sha256(path)
        assert pins.setdefault(str(path), checksum) == checksum
    assert sum(controls[key]["prediction"] == labels[key]["answer"] for key in ordered) == 116
    return dataset, labels, ordered, controls, pins


def score_row(row, key, controls, labels, tokenizer):
    assert row["questionId"] == key and row["baseline"] == controls[key]
    gold = labels[key]["answer"]
    for mode in MODES:
        item = row[mode]
        tokens = item["tokens"]
        assert 1 <= len(tokens) <= benchmark.MAX_NEW_TOKENS
        assert tokens[-1] == tokenizer.eos_token_id or len(tokens) == benchmark.MAX_NEW_TOKENS
        assert item["prediction"] == benchmark.normalize(tokenizer.decode(tokens, skip_special_tokens=True))
        assert type(item["skipped_channels"]) is int and item["skipped_channels"] > 0
    baseline = row["baseline"]["prediction"] == gold
    adaptive = row["adaptive"]["prediction"] == gold
    return Counter(baseline=baseline, adaptive=adaptive, gained=adaptive and not baseline,
                   lost=baseline and not adaptive)


def recover(stream, ordered, controls, labels, tokenizer):
    stream.seek(0)
    count, boundary, scores = 0, 0, Counter()
    while line := stream.readline():
        if not line.endswith(b"\n"):
            break
        assert count < len(ordered)
        scores.update(score_row(json.loads(line), ordered[count], controls, labels, tokenizer))
        count += 1
        boundary = stream.tell()
    stream.seek(boundary)
    stream.truncate()
    return count, scores


@torch.inference_mode()
def run(output):
    assert Path("/.dockerenv").is_file() and __debug__
    assert int(Path("/sys/fs/cgroup/memory.max").read_text()) <= 3 * GIB
    if benchmark.host_available() < 12 * GIB or hardware_needs_memory():
        return 75
    if torch.cuda.mem_get_info()[0] < 12 * GIB:
        return 75
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    torch.cuda.set_per_process_memory_fraction(0.78)
    dataset, labels, ordered, controls, pins = prepare()
    tokenizer = benchmark.AutoTokenizer.from_pretrained(benchmark.MODEL, local_files_only=True)
    processor = benchmark.LlavaProcessor(
        image_processor=benchmark.CLIPImageProcessorPil.from_pretrained(benchmark.MODEL, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1,
    )
    images = benchmark.load_images(dataset)
    model = benchmark.LlavaForConditionalGeneration.from_pretrained(
        benchmark.MODEL, local_files_only=True, dtype=torch.float32, attn_implementation="sdpa",
        use_kernels=False, device_map={"": "cuda:0"},
    ).eval()
    assert model.generation_config.eos_token_id == tokenizer.eos_token_id == 2
    original = benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder = benchmark.CompactDecoder(model, original, tuple(benchmark.read(JOINT)["local_ratio"]))
    first, ordinary = (benchmark.read(path)["layers"] for path in POLICIES)
    layers = decoder.language.layers
    replacements = [benchmark.FeedForward(layer, decoder, initial, later)
                    for layer, initial, later in zip(layers, first, ordinary, strict=True)]
    context = {}
    for index, (replacement, layer) in enumerate(zip(replacements, layers, strict=True)):
        install(replacement, index, layer.mlp, context)

    output.mkdir(exist_ok=True)
    manifest, predictions = (output / name for name in ("inputs.json", "predictions.jsonl"))
    configuration = dict(checkpoint_revision=benchmark.REVISION, questions=ordered,
                         prompt=benchmark.PROMPT, maximum_new_tokens=benchmark.MAX_NEW_TOKENS, input_sha256=pins)
    benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        with (output / "run.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if manifest.exists():
                assert benchmark.read(manifest) == configuration
            else:
                assert not predictions.exists()
                benchmark.write(manifest, configuration)
            with predictions.open("a+b") as stream:
                done, scores = recover(stream, ordered, controls, labels, tokenizer)
                for completed, key in enumerate(ordered[done:], done + 1):
                    if benchmark.host_available() < 8.5 * GIB or hardware_needs_memory():
                        return 75
                    label = labels[key]
                    embeddings, image_start = encode(model, processor, images[label["imageId"]],
                                                     label["question"])  # [1,T,H], T prompt tokens
                    row = {"questionId": key}
                    for mode in MODES:
                        context.update(calls=[0] * LAYERS, tested_rows=[0] * LAYERS, adaptive=(mode == "adaptive"))
                        for item in replacements:
                            item.begin(True, True)
                        tokens = decode(decoder, embeddings, image_start, benchmark.MODE, tokenizer.eos_token_id)
                        assert context["tested_rows"] == [item.prefill_rows - 1 if mode == "adaptive" else 0
                                                         for item in replacements]
                        row[mode] = {"tokens": tokens,
                                     "prediction": benchmark.normalize(tokenizer.decode(tokens, skip_special_tokens=True)),
                                     "skipped_channels": sum(item.prefill_skipped + item.decode_skipped
                                                             for item in replacements)}
                    scores.update(score_row(row, key, controls, labels, tokenizer))
                    stream.write((json.dumps(row) + "\n").encode())
                    if completed % 8 == 0:
                        stream.flush()
                        os.fsync(stream.fileno())
                        print("ADAPTIVE_SHIFT_PANEL_PROGRESS", completed, len(ordered), dict(scores), flush=True)
            assert scores["baseline"] == 116 and scores["adaptive"] - scores["baseline"] == scores["gained"] - scores["lost"]
            assert all(sha256(Path(name)) == checksum for name, checksum in pins.items())
            benchmark.write(output / "receipt.json",
                            dict(state="paired_gqa_adaptive_down_shift_completed", scores=dict(scores),
                                 questions=len(ordered), inputs_sha256=sha256(manifest),
                                 predictions_sha256=sha256(predictions)))
    finally:
        benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for replacement in replacements:
            replacement.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if args.preflight:
        _, _, ordered, _, evidence = prepare()
        print("ADAPTIVE_SHIFT_PANEL_INPUTS_VERIFIED", len(ordered), len(evidence))
    else:
        raise SystemExit(run(args.output.resolve()))
