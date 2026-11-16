"""Measure sparse-candidate transfer unions in the existing packed weight layout."""
import argparse
from collections import Counter
from pathlib import Path
import json
import time

import numpy as np
from safetensors import safe_open

from audit_tri_oracle_ff_down_input import CACHE, ROOT, digest, read
from evaluate_tri_oracle_sparse_weight_predictor import (
    HIGH_RATE, TOP_COUNT, TORCH as torch, exact_budget_mask, probe,
)
from measure_tri_oracle_input_equalization import GIB, host_available
from measure_tri_oracle_packed_thresholds import BATCH, HIDDEN, ROWS, group_traffic, reconstruct
from measure_tri_oracle_packed_workload_traffic import (
    CHANNELS, RESPONSE_BYTES, WORD_BYTES, verify_traffic_control,
)
from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import IntegerFeedForwardReference

MODES = ("sparse_three_sigma", *TOP_COUNT)
OLD = CACHE / "ff_batch_shared_magnitude/receipt.json"
INPUT_RECORD = ROOT / "records/tri_oracle_shared_word_pruning_traffic.json"
EXPECTED_RESULT = ROOT / "records/tri_oracle_sparse_weight_predictor.json"


def words(active, size):
    # Group the [R,F] row-by-feature flags into [G,F/8] packed transport words.
    rows, features = active.shape
    assert rows % size == features % WORD_BYTES == 0
    return active.reshape(-1, size, features // WORD_BYTES, WORD_BYTES).any(3).any(1)


def traffic(codes, keep, dense, support, size):
    # The four arguments are [R,H], [R,K], [R,K], [R,H].
    after = dense.masked_fill(~keep, 0)  # [R,K] signed down coefficients.
    original = group_traffic(codes, keep, dense, after, size)
    active = words(codes.ne(0), size)  # [G,H/8] gate and up follow-up words.
    kept = words(keep, size)  # [G,K/8] groups of retained output rows.
    probed = words(support, size)  # [G,H/8] input words probed for all output rows.
    all_channels = CHANNELS // WORD_BYTES
    probe_count = int(probed.sum()) * all_channels
    repeated = int(((active & probed).sum(1) * kept.sum(1)).sum())
    assert 0 <= repeated <= probe_count
    # Independently materialize requested (input word, output group) pairs
    # for the first shared group and compare the explicit set union.
    a, k, p = (mask[0].cpu().numpy() for mask in (active, kept, probed))
    followup_grid = a[:, None] & k[None, :]
    probe_grid = np.broadcast_to(p[:, None], followup_grid.shape)
    formula = np.count_nonzero(p) * all_channels + np.count_nonzero(a & ~p) * np.count_nonzero(k)
    assert np.count_nonzero(followup_grid | probe_grid) == formula
    gate_followup = original["predictor_gate_up_bytes"]
    assert gate_followup == 2 * RESPONSE_BYTES * int((active.sum(1) * kept.sum(1)).sum())
    return original | {
        "probe_bytes": 2 * RESPONSE_BYTES * probe_count,
        "reused_probe_bytes": 2 * RESPONSE_BYTES * repeated,
        "opportunities": keep.numel(), "skipped": int((~keep).sum()),
        "probe_features": int(support.sum()), "probe_words": int(probed.sum()),
    }


@torch.inference_mode()
def run(out):
    assert Path.cwd() == ROOT and not Path("/.dockerenv").exists() and __debug__
    assert host_available() >= 10 * GIB and torch.cuda.mem_get_info()[0] >= 10 * GIB
    torch.set_num_threads(3)
    torch.cuda.set_per_process_memory_fraction(.30)
    torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    native_control = verify_traffic_control()
    previous_report = read(INPUT_RECORD)
    assert digest(OLD) == previous_report["evidence_sha256"][str(OLD.relative_to(ROOT))]
    previous = read(OLD)
    captured = CACHE / "format320/captured_rows.pt"
    policy_path = CACHE / "format335/layer_policy.json"
    model = CACHE / "tiny_llava_v1"
    index_path = model / "model.safetensors.index.json"
    config_path = model / "config.json"
    index = read(index_path)["weight_map"]
    shards = {model / name for name in set(index.values())}
    inputs = {path: digest(path) for path in (captured, policy_path, index_path, config_path, *sorted(shards))}
    for path, hash_ in inputs.items():
        assert previous["input_sha256"][str(path)] == hash_, path
    source = ROOT / "syn/evaluate_tri_oracle_sparse_weight_predictor.py"
    assert digest(source) == read(EXPECTED_RESULT)["evidence_sha256"][str(source.relative_to(ROOT))]
    provenance = {str(path.relative_to(ROOT)): digest(path) for path in (
        INPUT_RECORD, EXPECTED_RESULT, native_control, OLD, source, Path(__file__).resolve(),
        Path(group_traffic.__code__.co_filename), Path(reconstruct.__code__.co_filename))}
    data = torch.load(captured, map_location="cpu", weights_only=True, mmap=True)
    policies = read(policy_path)["layers"]
    epsilon = read(config_path)["text_config"]["rms_norm_eps"]
    selected = [i for i in range(256) if i % (BATCH + 1) != 0]
    assert len(selected) == ROWS * 2 and len(data) == len(policies) == 22
    previous_parts = {"fit": slice(0, ROWS), "held": slice(ROWS, ROWS * 2)}
    totals = {mode: {part: {str(size): Counter() for size in (1, BATCH)}
                     for part in previous_parts} for mode in MODES}
    controls = {part: Counter() for part in previous_parts}
    for layer, (sample, policy) in enumerate(zip(data, policies, strict=True)):
        assert host_available() >= 9 * GIB
        weights = []
        for branch in ("gate", "up", "down"):
            key, = (key for key in index if key.endswith(f".layers.{layer}.mlp.{branch}_proj.weight"))
            with safe_open(model / index[key], framework="pt", device="cpu") as shard:
                weights.append(shard.get_tensor(key).to("cuda"))  # [K,H] or [H,K] trained float weights.
        reference = IntegerFeedForwardReference(*weights, epsilon)
        activation, residual = (sample[name][selected].to("cuda") for name in ("activation", "residual"))
        assert activation.shape == residual.shape == (2 * ROWS, HIDDEN)
        _, _, stats = evaluate_policy(reference, activation, residual, policy, prune=False)
        codes, _, current, dense, pruned, _ = reconstruct(reference, activation, stats)
        budget = torch.full((len(codes), 1), CHANNELS * HIGH_RATE // 100, device="cuda", dtype=torch.int64)
        for part, area in previous_parts.items():
            controls[part].update(group_traffic(codes[area], ~current[area], dense[area], pruned[area], BATCH))
        for mode in MODES:
            scores, count = probe(reference, activation, stats["norm_codes"], stats, mode)
            if mode == "sparse_three_sigma":
                support = stats["norm_codes"].abs() > 768  # [R,H] predictor feature mask.
            else:
                count_requested = torch.full_like(budget, TOP_COUNT[mode])  # [R,1] requested features.
                support = exact_budget_mask(-codes.to(torch.int32).abs(), count_requested)
            assert torch.equal(count, support.sum(1))
            keep = ~exact_budget_mask(scores, budget)  # [R,K] candidate's retained channels.
            for part, area in previous_parts.items():
                for size in (1, BATCH):
                    totals[mode][part][str(size)].update(
                        traffic(codes[area], keep[area], dense[area], support[area], size))
        print("PACKED_SPARSE_LAYER", layer + 1, flush=True)
    for part, control in controls.items():
        old = previous["result"]["predictor_control"][part]
        assert all(value == old[name] for name, value in control.items())
    result = {}
    for mode, parts in totals.items():
        for part, by_size in parts.items():
            for size, values in by_size.items():
                assert values["opportunities"] == 22 * ROWS * CHANNELS
                assert values["skipped"] == 22 * ROWS * (CHANNELS * HIGH_RATE // 100)
                dense_bytes = values["no_predictor_gate_up_bytes"] + values["no_predictor_down_bytes"]
                followup = values["predictor_gate_up_bytes"] + values["predictor_down_bytes"]
                without_reuse = followup + values["probe_bytes"]
                assert values["reused_probe_bytes"] <= min(values["probe_bytes"], values["predictor_gate_up_bytes"])
                with_reuse = without_reuse - values["reused_probe_bytes"]
                result.setdefault(mode, {}).setdefault(part, {})[size] = {
                    **values, "dense_bytes": dense_bytes,
                    "bytes_with_probe_reuse": with_reuse, "bytes_without_probe_reuse": without_reuse,
                    "saved_percent_with_probe_reuse": 100 * (1 - with_reuse / dense_bytes),
                    "saved_percent_without_probe_reuse": 100 * (1 - without_reuse / dense_bytes),
                }
    report = {
        "state": "packed_sparse_probe_transport_modeled", "per_split_rows": len(data) * ROWS,
        "device": torch.cuda.get_device_name(), "device_peak_bytes": torch.cuda.max_memory_allocated(),
        "scope": "Fixed archived activation rows from 16 distinct images. Transport assumes the existing eight-channel packing and row sharing, with ideal reuse of overlapping probe reads. This is a software transfer count.",
        "elapsed_seconds": time.monotonic() - started, "result": result, "controls": controls,
        "input_sha256": provenance | {str(path.relative_to(ROOT)): sha for path, sha in inputs.items()},
    }
    with (out / "receipt.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print("PACKED_SPARSE_PASS", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=lambda name: Path(name).resolve())
    args = parser.parse_args()
    assert args.out.is_relative_to(ROOT / ".cache")
    args.out.mkdir(parents=True, exist_ok=True)
    run(args.out)
