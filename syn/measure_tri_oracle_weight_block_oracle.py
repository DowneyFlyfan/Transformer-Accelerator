"""Measure the packed-transport tradeoff when exact channel contributions are known."""

import argparse
from collections import Counter
import json
from pathlib import Path
import time

from safetensors import safe_open
import torch

from measure_tri_oracle_input_equalization import CACHE, GIB, HIDDEN, LAYERS, host_available, read
from measure_tri_oracle_packed_thresholds import BATCH, ROWS
from measure_tri_oracle_packed_workload_traffic import group_traffic, packed_counts, reconstruct
from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import IntegerFeedForwardReference, _dot, _quantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


RATES = (10, 20, 30, 40, 50, 57, 100)
CONFIGURATIONS = {"packed_shared": (BATCH, 8), "channel_shared": (BATCH, 1), "packed_per_token": (1, 8)}


def score_blocks(dense, weights, scales, dense_norm, tokens, width):
    """Score isolated contributions from exact down inputs [R,K] and weights [H,K]."""
    rows, channels = dense.shape
    assert rows % tokens == channels % width == 0
    physical = torch.ldexp(weights.float(), scales)  # [H,K], weight codes with per-output exponents [H,1].
    vectors = physical.T.reshape(channels // width, width, HIDDEN)  # [B,width,H], B channel blocks.
    gram = torch.bmm(vectors, vectors.transpose(1, 2))  # [B,width,width], within-block inner products.
    inputs = dense.float().reshape(rows, channels // width, width)  # [R,B,width], integer code units.
    squared = torch.einsum("rbi,bij,rbj->rb", inputs, gram, inputs).clamp_min(0)  # [R,B].
    relative = squared / dense_norm.float().square().clamp_min(1e-30)[:, None]  # [R,B].
    return relative.reshape(rows // tokens, tokens, channels // width).sum(dim=1)  # [G,B], G token groups.


def oracle(codes, dense, weights, scales, tokens, width):
    """Drop whole blocks ranked by exact isolated output contribution per byte saved."""
    rows, channels = dense.shape
    groups, blocks = rows // tokens, channels // width
    assert codes.shape == (rows, HIDDEN)
    output = torch.ldexp(_dot(dense, weights).float(), scales.T)  # [R,H], omit common per-row powers in relative error.
    norm = output.double().norm(dim=1).clamp_min(1e-20)  # [R].
    scores = score_blocks(dense, weights, scales, norm, tokens, width)  # [G,B].
    gate_words = packed_counts(codes.ne(0), tokens)  # [G], input transport granularity remains eight features.
    down_live = dense.ne(0).reshape(groups, tokens, blocks, width).any(dim=3).any(dim=1)  # [G,B].
    cost = 2 * 8 * width * gate_words[:, None] + (HIDDEN * width) * down_live  # [G,B], bytes saved by dropping each block.
    assert bool((cost > 0).all()) and bool(torch.isfinite(scores).all())
    total = cost.sum(dim=1)  # [G], dense traffic for one token group.
    order = torch.argsort(scores / cost, dim=1, stable=True)  # [G,B], lowest normalized contribution per byte first.
    ordered = cost.gather(1, order)  # [G,B], byte costs in oracle order.
    before = ordered.cumsum(dim=1) - ordered  # [G,B], savings before including each block.
    results = {}
    for rate in RATES:
        selected = before * 100 < rate * total[:, None]  # [G,B], smallest ranked prefix reaching the target.
        removed = torch.zeros_like(selected).scatter(1, order, selected)  # [G,B], mask restored to original order.
        mask = removed[:, None, :, None].expand(groups, tokens, blocks, width).reshape(rows, channels)  # [R,K].
        saved = int((removed * cost).sum())
        assert saved * 100 >= rate * int(total.sum())
        if width == 8:
            check = group_traffic(codes, ~mask, dense, dense.masked_fill(mask, 0), tokens)
            assert int(total.sum()) == check["no_predictor_gate_up_bytes"] + check["no_predictor_down_bytes"]
            assert int(total.sum()) - saved == check["predictor_gate_up_bytes"] + check["predictor_down_bytes"]
        contributions = dense.masked_fill(~mask, 0)  # [R,K], inputs removed by the oracle.
        effect = torch.ldexp(_dot(contributions, weights).float(), scales.T)  # [R,H], exact integer output difference.
        changes = effect.double().norm(dim=1) / norm  # [R], relative output change.
        if rate == 100:
            assert torch.equal(effect, output) and bool(removed.all())
        results[rate] = Counter(dense_weight_bytes=int(total.sum()), saved_weight_bytes=saved,
                                relative_error_sum=float(changes.sum()))
    return results


@torch.inference_mode()
def run(output):
    started = time.monotonic()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.set_float32_matmul_precision("highest")
    assert host_available() >= 16 * GIB and torch.cuda.mem_get_info()[0] >= 8 * GIB
    torch.cuda.set_per_process_memory_fraction(0.125)
    torch.cuda.reset_peak_memory_stats()
    record = ROOT / "records/wac_packed_predictor_threshold_result.json"
    verified = read(record)
    assert verified["state"] == "packed_predictor_threshold_tradeoff_independently_verified"
    measured = CACHE / "packed_thresholds_v1.json"
    assert sha256(measured) == verified["evidence_sha256"][str(measured.relative_to(ROOT))]
    prior = read(measured)
    pins = prior["input_sha256"].copy()
    for file in (record, measured, Path(__file__).resolve(), Path(group_traffic.__code__.co_filename).resolve()):
        pins[str(file)] = sha256(file)
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    model = CACHE / "tiny_llava_v1"
    index = read(model / "model.safetensors.index.json")["weight_map"]
    epsilon = read(model / "config.json")["text_config"]["rms_norm_eps"]
    archive = torch.load(CACHE / "format320/captured_rows.pt", map_location="cpu", weights_only=True, mmap=True)  # [256,H] per layer.
    policies = read(CACHE / "format335/layer_policy.json")["layers"]
    assert len(archive) == len(policies) == LAYERS
    selected = [row for row in range(128, 256) if row % (BATCH + 1)]
    totals = {name: {rate: Counter() for rate in RATES} for name in CONFIGURATIONS}
    for layer, (capture, policy) in enumerate(zip(archive, policies, strict=True)):
        assert host_available() >= 15 * GIB
        weights = []
        for projection in ("gate", "up", "down"):
            key, = (name for name in index if name.endswith(f".layers.{layer}.mlp.{projection}_proj.weight"))
            with safe_open(model / index[key], framework="pt", device="cpu") as shard:
                weights.append(shard.get_tensor(key).to("cuda"))  # Gate/up [K,H], down [H,K].
        reference = IntegerFeedForwardReference(*weights, epsilon)
        activation, residual = (capture[name][selected].to("cuda") for name in ("activation", "residual"))  # [120,H].
        assert activation.shape == residual.shape == (ROWS, HIDDEN)
        _, _, stats = evaluate_policy(reference, activation, residual, policy, prune=False)
        codes, _, _, dense, _, _ = reconstruct(reference, activation, stats)  # [120,H] activation codes, [120,K] down codes.
        down, exponents = _quantize(weights[-1], per_row=True)  # [H,K], [H,1].
        for name, (tokens, width) in CONFIGURATIONS.items():
            for rate, outcome in oracle(codes, dense, down, exponents, tokens, width).items():
                totals[name][rate].update(outcome)
        print("WEIGHT_ORACLE_LAYER", layer, flush=True)
    profiles = {name: {str(rate): {**dict(counts),
                   "weight_reduction_percent": 100 * counts["saved_weight_bytes"] / counts["dense_weight_bytes"],
                   "mean_relative_output_change": counts["relative_error_sum"] / (LAYERS * ROWS)}
                       for rate, counts in rates.items()} for name, rates in totals.items()}
    assert profiles["packed_shared"]["57"]["dense_weight_bytes"] == verified["baseline"]["held"]["dense_bytes"]
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    result = {"state": "packed_weight_contribution_oracle_measured", "held_rows": LAYERS * ROWS,
              "profiles": profiles, "native_seconds": time.monotonic() - started,
              "peak_gpu_bytes": torch.cuda.max_memory_allocated(), "input_sha256": pins,
              "scope": "Exact contributions rank isolated channel blocks on held rows. The ranked prefix is a heuristic. "
                       "Traffic excludes sign reads, and the channel-granular layout is hypothetical."}
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], {name: rows["57"] for name, rows in profiles.items()}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
