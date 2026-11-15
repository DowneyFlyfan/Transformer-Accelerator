"""Test late-prompt feed-forward projection substitutions on the fixed panel."""

import argparse
from collections import Counter
from copy import copy
import json
from pathlib import Path

from evaluate_tri_oracle_gqa_prefill_layer_groups import (
    GROUPS, JOINT, POLICIES, group_tokens, prepare, torch,
)
from last_row_residual_planes import accumulate_planes, down_plane
from measure_tri_oracle_input_equalization import GIB, LAYERS
from run_pruned_accuracy_ablation import benchmark, encode
from run_tri_oracle_full_down_code_gqa import hardware_needs_memory
from tri_oracle_integer_reference import _dot, _quantize, _requantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


LATE = GROUPS["layers_17_21"]
MODES = ("floating_gate_up", "floating_down", "down_residual_plane")
FINE_BITS = 4


def gated_codes(reference, activation, stats):
    """Recover the original [M,K] fixed-point gated result from [M,H] inputs."""
    codes, _ = _quantize(activation, per_row=True)  # [M,H] original signed8 input
    gate = _requantize(_dot(codes, reference.gate), stats["gate_shift"][:, None], 16)  # [M,K]
    up = _requantize(_dot(codes, reference.up), stats["up_shift"][:, None], 16)  # [M,K]
    product = reference.silu_response[gate + 32768] * up  # [M,K], original ungated product precision
    return _requantize(product, torch.full_like(stats["down_shift"][:, None], 8), 16)  # [M,K]


def project(reference, projections, activation, stats, mode):
    """Change a single projection stage on retained prompt rows [M,H]."""
    gain = stats["up_gain_bits"][:, None]  # [M,1] original compensated up gain
    down_shift = stats["down_shift"][:, None]  # [M,1] original input shift
    if mode == "floating_gate_up":
        # The checkpoint projections produce [M,K]. Keep the existing signed16
        # gated activation format and the signed8 down path after substitution.
        gate = projections.act_fn(projections.gate_proj(activation))  # [M,K]
        up = projections.up_proj(activation)  # [M,K]
        physical = torch.ldexp(gate * up, 8 + gain)  # [M,K], same gated-code units
        gated = (physical.sign() * torch.floor(physical.abs() + 0.5)).clamp(-32768, 32767).to(torch.int64)
    else:
        gated = gated_codes(reference, activation, stats)  # [M,K] exact original nonlinear path
    if mode == "floating_down":
        # Replace the down input quantizer and dot product while preserving the
        # upstream signed16 result, including its original clipping.
        return projections.down_proj(torch.ldexp(gated.float(), -8 - gain))  # [M,H]

    coarse = _requantize(gated, down_shift, 8).to(torch.int8)  # [M,K] original down code format
    if mode == "down_residual_plane":
        fine = down_plane(gated, coarse, down_shift, FINE_BITS)  # [M,K] signed8 residuals
        raw = accumulate_planes(coarse, fine, reference.down, FINE_BITS)  # [M,H] aligned integer sums
        return torch.ldexp(raw.float(), reference.down_exponent + down_shift - 8 - gain - FINE_BITS)
    raw = _dot(coarse, reference.down)  # [M,H], existing signed8 array
    return torch.ldexp(raw.float(), reference.down_exponent + down_shift - 8 - gain)


def install(item, projections, index, context):
    """Preserve scalar scales for the first prompt row and channel scales after it."""
    first = copy(item.reference)
    ordinary = copy(first)
    ordinary.down, scales = _quantize(projections.down_proj.weight, per_row=True)  # [H,K], [H,1]
    ordinary.down_exponent = scales.T  # [1,H]

    def evaluate(activation, residual, **settings):
        is_first = item.decoder.prefill_active and context["calls"][index] == 0
        context["calls"][index] += 1
        if is_first:
            assert activation.shape[0] == 1 and int(item.decoder.positions[0]) == 0
        reference = first if is_first else ordinary
        raw, baseline, stats = reference.evaluate(activation, residual, **settings)
        mode = context["projection_mode"]
        if mode is None or not item.decoder.prefill_active or not LATE[0] <= index < LATE[1]:
            return raw, baseline, stats
        assert not settings["prune"]
        amended = project(reference, projections, activation, stats, mode)  # [M,H]
        assert amended.shape == baseline.shape and bool(torch.isfinite(amended).all())
        context["substituted"][index] += activation.shape[0]
        return raw, amended, stats

    item.reference.evaluate = evaluate


def verified_late_controls(panel, pins):
    directory = ROOT / ".cache/model_reference/gqa_testdev/prefill_layer_groups"
    ledger = ROOT / "records/tri_oracle_prefill_layer_group_precision.json"
    prior = benchmark.read(ledger)
    assert prior["state"] == "paired_gqa_prompt_precision_layer_groups_independently_verified"
    receipt = directory / "receipt.json"
    predictions = directory / "predictions.jsonl"
    manifest = directory / "inputs.json"
    for path in (receipt, predictions, manifest):
        expected = prior["evidence_sha256"][str(path.relative_to(ROOT))]
        assert sha256(path) == expected
        assert pins.setdefault(str(path), expected) == expected
    assert benchmark.read(manifest)["panel"] == panel
    pins[str(ledger)] = sha256(ledger)
    with predictions.open() as stream:
        rows = [json.loads(line) for line in stream]
    assert [row["questionId"] for row in rows] == panel
    return {row["questionId"]: row["groups"]["layers_17_21"] for row in rows}


@torch.inference_mode()
def run(output):
    assert Path("/.dockerenv").is_file() and __debug__
    assert int(Path("/sys/fs/cgroup/memory.max").read_text()) <= 3 * GIB
    assert benchmark.host_available() >= 12 * GIB and torch.cuda.mem_get_info()[0] >= 12 * GIB
    assert not hardware_needs_memory()
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    torch.cuda.set_per_process_memory_fraction(0.78)
    dataset, labels, panel, controls, pins = prepare()
    # Replace the predecessor runner hash only by adding this experiment's source.
    for path in (Path(__file__).resolve(), Path(down_plane.__code__.co_filename)):
        pins[str(path)] = sha256(path)
    float_controls = verified_late_controls(panel, pins)
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
    decoder = benchmark.CompactDecoder(model, original, tuple(benchmark.read(JOINT)["local_ratio"]))
    first, ordinary = (benchmark.read(path)["layers"] for path in POLICIES)
    layers = decoder.language.layers
    replacements = [benchmark.FeedForward(layer, decoder, initial, later)
                    for layer, initial, later in zip(layers, first, ordinary, strict=True)]
    context = {"projection_mode": None}
    for index, (item, layer) in enumerate(zip(replacements, layers, strict=True)):
        install(item, layer.mlp, index, context)

    def embeddings_for(key):
        label = labels[key]
        return encode(model, processor, images[label["imageId"]], label["question"])  # [1,T,H], scalar origin

    chosen = {}
    for key in panel:
        chosen.setdefault(labels[key]["types"]["structural"], key)
    assert len(chosen) == 5
    output.mkdir()
    manifest, predictions = (output / name for name in ("inputs.json", "predictions.jsonl"))
    benchmark.write(manifest, dict(checkpoint_revision=benchmark.REVISION, panel=panel, modes=list(MODES),
                                   late_layers=list(range(*LATE)), prompt=benchmark.PROMPT,
                                   maximum_new_tokens=benchmark.MAX_NEW_TOKENS, input_sha256=pins))
    scores = Counter()
    benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        for key in chosen.values():
            embeddings, origin = embeddings_for(key)  # [1,T,H], scalar origin
            for bounds, expected in (((0, 0), controls[key]["integer_both"]), (LATE, float_controls[key])):
                actual = group_tokens(decoder, replacements, context, embeddings, origin, tokenizer.eos_token_id, bounds)
                assert actual == expected, (key, bounds)
        print("LATE_PROJECTION_CONTROL_TOKENS_MATCHED", len(chosen) * 2, flush=True)
        with predictions.open("x", buffering=1) as stream:
            for completed, key in enumerate(panel, 1):
                assert benchmark.host_available() >= 8.5 * GIB and not hardware_needs_memory()
                embeddings, origin = embeddings_for(key)  # [1,T,H], scalar origin
                tokens_by_mode = {}
                for mode in MODES:
                    context.update(projection_mode=mode, substituted=[0] * LAYERS)
                    tokens = group_tokens(decoder, replacements, context, embeddings, origin, tokenizer.eos_token_id, (0, 0))
                    assert context["substituted"] == [decoder.layer_slots[index] if LATE[0] <= index < LATE[1]
                                                      else 0 for index in range(LAYERS)]
                    decoded = benchmark.normalize(tokenizer.decode(tokens, skip_special_tokens=True))
                    scores[mode] += decoded == labels[key]["answer"]
                    tokens_by_mode[mode] = tokens
                stream.write(json.dumps({"questionId": key, "tokens": tokens_by_mode}) + "\n")
                if completed % 8 == 0:
                    print("LATE_PROJECTION_PROGRESS", completed, len(panel), dict(scores), flush=True)
    finally:
        benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for item in replacements:
            item.close()
    assert all(sha256(Path(name)) == checksum for name, checksum in pins.items())
    benchmark.write(output / "receipt.json",
                    dict(state="paired_late_projection_precision_completed", questions=len(panel),
                         exact_matches=dict(scores), control_tokens_matched=len(chosen)*2,
                         inputs_sha256=sha256(manifest), predictions_sha256=sha256(predictions)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output.resolve())
