"""Measure the signed-eight-bit late-prompt correction with all pruning enabled."""
import argparse
from collections import Counter
from copy import copy
import json
from pathlib import Path
import time

from audit_tri_oracle_placed_fanout import GIB, memory
from evaluate_tri_oracle_late_prefill_projections import LATE, gated_codes
from run_pruned_accuracy_ablation import benchmark, decode, encode
from run_tri_oracle_full_down_code_gqa import hardware_needs_memory
from tri_oracle_integer_reference import _dot, _quantize, _requantize


ROOT = benchmark.ROOT
DATA = ROOT / ".cache/model_reference/gqa_testdev"
torch = benchmark.torch


def configure(replacement, projection, layer_index, context, workload):
    first = copy(replacement.reference)
    ordinary = copy(first)
    # Checkpoint weight [O,K] has O output features and K intermediate channels.
    ordinary.down, scales = _quantize(projection.down_proj.weight, per_row=True)  # [O,K], [O,1]
    ordinary.down_exponent = scales.T  # [1,O], output-specific power-of-two exponent.

    def evaluate(activation, residual, **settings):
        # Base evaluator receives [M,H] tensors for M retained rows and H input features.
        prefill = replacement.decoder.prefill_active
        first_row = prefill and context["calls"][layer_index] == 0
        context["calls"][layer_index] += 1
        if first_row:
            assert activation.shape[0] == 1 and int(replacement.decoder.positions[0]) == 0
        reference = first if first_row else ordinary
        raw, values, stats = reference.evaluate(activation, residual, **settings)  # [M,O], [M,O], statistics
        if not (context["corrected"] and prefill and LATE[0] <= layer_index < LATE[1]):
            return raw, values, stats
        assert settings["prune"]
        # Rebuild the existing skip mask from the exact signed pre-scale normalization [M,H].
        norm = stats["norm_codes"]  # [M,H], the base evaluator's normalization codes.
        outliers = norm.abs() > 768  # [M,H], existing strict outlier test.
        signs = (torch.where(norm < 0, -1, 1) * outliers).to(torch.int8)  # [M,H], signed outliers.
        gate_margin = _dot(signs, reference.gate_sign)  # [M,K], gate sign agreement.
        up_margin = _dot(signs, reference.up_sign)  # [M,K], up sign agreement.
        skip = ((stats["outlier_count"][:, None] > 0)
                & (gate_margin <= settings.get("gate_threshold", 0))
                & (up_margin.abs() <= settings.get("up_window", 0)))  # [M,K], predicted skipped channels.
        assert torch.equal(skip.sum(dim=1, dtype=torch.int32), stats["skip_count"])
        gated = gated_codes(reference, activation, stats)  # [M,K], exact existing signed16 codes.
        shift = stats["down_shift"][:, None]  # [M,1], configured row-wise down shift.
        wide = _requantize(gated, shift, 16)  # [M,K], rounded before signed8 saturation.
        coarse = wide.clamp(-128, 127)  # [M,K], same signed8 down codes before skipping.
        overflow = wide - coarse  # [M,K], part lost to saturation.
        delta = overflow.clamp(-128, 127).masked_fill(skip, 0).to(torch.int8)  # [M,K], retained signed8 delta.
        active = delta.ne(0).any(dim=1)  # [M], rows with at least one retained correction.
        if context["verify_raw"]:
            base = _dot(coarse.masked_fill(skip, 0).to(torch.int8), reference.down)  # [M,O], oracle coarse sums.
            assert torch.equal(base, raw)
        selected = delta[active]  # [A,K], A active rows collected from M input rows.
        workload.update(rows=gated.shape[0], codes=gated.numel(), active_rows=selected.shape[0],
                        saturated_codes=int(overflow.ne(0).sum()),
                        retained_corrections=int(selected.ne(0).sum()),
                        skipped_saturated_codes=int((skip & overflow.ne(0)).sum()))
        context["corrected_rows"][layer_index] += gated.shape[0]
        if selected.shape[0]:
            total = raw.clone()  # [M,O], all original sums, updated on the A selected rows.
            total[active] += _dot(selected, reference.down)  # [A,O], additive correction before scaling.
            # Even doubling the original channel magnitude cannot exceed the signed32 sum.
            assert reference.channels * 2 * 128 * 128 < (1 << 31)
            gain = stats["up_gain_bits"][:, None]  # [M,1], inherited row-wise gain.
            values = torch.ldexp(total.float(), reference.down_exponent + shift - 8 - gain)  # [M,O]
            raw = total
        return raw, values, stats

    replacement.reference.evaluate = evaluate


@torch.inference_mode()
def run(output):
    start = time.monotonic()
    assert Path("/.dockerenv").exists()
    assert int(Path("/sys/fs/cgroup/memory.max").read_text()) <= 3 * GIB
    assert benchmark.host_available() >= 12 * GIB and not hardware_needs_memory()
    assert torch.cuda.mem_get_info()[0] >= 12 * GIB
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    torch.cuda.set_per_process_memory_fraction(0.78)
    torch.cuda.reset_peak_memory_stats()
    dataset, labels, evidence = benchmark.inputs()
    baseline_dir = DATA / "paired_ablation"
    receipt, manifest, archive = (baseline_dir / name for name in ("receipt.json", "inputs.json", "predictions.jsonl"))
    prior = benchmark.read(receipt)
    settings = benchmark.read(manifest)
    assert prior["exact_matches"]["weight_skipping"] == 80 and prior["questions"] == 160
    assert benchmark.digest(manifest) == prior["inputs_sha256"]
    assert benchmark.digest(archive) == prior["predictions_sha256"]
    assert settings["checkpoint_revision"] == benchmark.REVISION and settings["prompt"] == benchmark.PROMPT
    assert settings["decoder_max_new_tokens"] == benchmark.MAX_NEW_TOKENS
    for name, checksum in settings["input_sha256"].items():
        assert benchmark.digest(Path(name)) == checksum, name
        assert evidence.setdefault(name, checksum) == checksum
    controls = {row["questionId"]: row["modes"]["weight_skipping"]
                for line in archive.open() if (row := json.loads(line))}
    assert set(controls) == {key for group in settings["panel"].values() for key in group}
    assert len(controls) == 160 and controls.keys() <= labels.keys()
    for path in (manifest, archive, receipt, Path(__file__).resolve(), Path(gated_codes.__code__.co_filename)):
        evidence[str(path)] = benchmark.digest(path)
    images = benchmark.load_images(dataset)
    tokenizer = benchmark.AutoTokenizer.from_pretrained(benchmark.MODEL, local_files_only=True)
    processor = benchmark.LlavaProcessor(
        image_processor=benchmark.CLIPImageProcessorPil.from_pretrained(benchmark.MODEL, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1,
    )
    model = benchmark.LlavaForConditionalGeneration.from_pretrained(
        benchmark.MODEL, local_files_only=True, dtype=torch.float32, attn_implementation="sdpa",
        use_kernels=False, device_map={"": "cuda:0"},
    ).eval()
    assert model.generation_config.eos_token_id == tokenizer.eos_token_id == 2
    original = benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"]
    joint = benchmark.read(ROOT / "records/batch424_joint_pilot_result.json")
    decoder = benchmark.CompactDecoder(model, original, tuple(joint["local_ratio"]))
    first, ordinary = (benchmark.read(benchmark.REFERENCE / name / "layer_policy.json")["layers"]
                       for name in ("format322", "format335"))
    layers = decoder.language.layers
    replacements = [benchmark.FeedForward(layer, decoder, a, b)
                    for layer, a, b in zip(layers, first, ordinary, strict=True)]
    assert len(replacements) == 22
    context, workload = {}, Counter()
    for index, (replacement, layer) in enumerate(zip(replacements, layers, strict=True)):
        configure(replacement, layer.mlp, index, context, workload)
    benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    scores = Counter()
    output.mkdir()
    saved = output / "predictions.jsonl"
    inputs = output / "inputs.json"
    benchmark.write(inputs, dict(checkpoint_revision=benchmark.REVISION, late_layers=list(range(*LATE)),
                                 prompt=benchmark.PROMPT, panel=sorted(controls), input_sha256=evidence))
    try:
        with saved.open("x", buffering=1) as stream:
            for index, key in enumerate(sorted(controls), 1):
                available, anonymous = memory()
                assert available >= 8.5 * GIB and anonymous < 2.75 * GIB and not hardware_needs_memory()
                label = labels[key]
                # Embeddings [1,T,H] contain T prompt rows and H model features.
                embeddings, image_start = encode(model, processor, images[label["imageId"]], label["question"])
                outcomes = []
                for corrected in (False, True):
                    context.update(corrected=corrected, verify_raw=index <= 8,
                                   calls=[0] * 22, corrected_rows=[0] * 22)
                    for item in replacements:
                        item.begin(True, True)
                    tokens = decode(decoder, embeddings, image_start, benchmark.MODE, tokenizer.eos_token_id)
                    predicted = benchmark.normalize(tokenizer.decode(tokens, skip_special_tokens=True))
                    skipped = sum(item.prefill_skipped + item.decode_skipped for item in replacements)
                    assert skipped > 0 and all(item.prefill_rows == size and item.decode_rows == len(tokens) - 1
                                              for item, size in zip(replacements, decoder.layer_slots, strict=True))
                    if corrected:
                        assert context["corrected_rows"] == [size if LATE[0] <= layer < LATE[1] else 0
                                                             for layer, size in enumerate(decoder.layer_slots)]
                    else:
                        assert tokens == controls[key]["tokens"]
                        assert predicted == controls[key]["prediction"] and skipped == controls[key]["skipped_channels"]
                    correct = predicted == label["answer"]
                    scores["corrected" if corrected else "baseline"] += correct
                    outcomes.append(dict(tokens=tokens, answer=predicted, correct=correct, skipped=skipped))
                baseline, correction = outcomes
                scores["gained"] += correction["correct"] and not baseline["correct"]
                scores["lost"] += baseline["correct"] and not correction["correct"]
                stream.write(json.dumps(dict(questionId=key, baseline=baseline, corrected=correction)) + "\n")
                if index % 8 == 0:
                    print("JOINT_CLIP_PROGRESS", index, len(controls), dict(scores), flush=True)
    finally:
        benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for item in replacements:
            item.close()
    assert all(benchmark.digest(Path(name)) == checksum for name, checksum in evidence.items())
    assert scores["baseline"] == 80 and scores["corrected"] == 80 + scores["gained"] - scores["lost"]
    assert workload["saturated_codes"] == workload["retained_corrections"] + workload["skipped_saturated_codes"]
    benchmark.write(output / "receipt.json",
                    dict(state="paired_joint_late_clip_completed", questions=len(controls), scores=scores,
                         workload=workload, wall_seconds=time.monotonic() - start, torch=str(torch.__version__),
                         max_gpu_bytes=torch.cuda.max_memory_allocated(), inputs_sha256=benchmark.digest(inputs),
                         predictions_sha256=benchmark.digest(saved)))
    print("JOINT_CLIP_COMPLETED", dict(scores), dict(workload), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output.resolve())
