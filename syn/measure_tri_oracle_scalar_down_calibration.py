"""Fit bounded scalar down codes with and without fixed escape classes."""

import argparse
from collections import Counter
import json
from pathlib import Path
import time

from safetensors import safe_open
import torch

from audit_tri_oracle_calibrated_weight_transport import pack, transfer_size
from measure_tri_oracle_down_code_calibration import IDENTITY, RIDGE_FRACTIONS, fit_codebook, reconstruct_input, score
from measure_tri_oracle_input_equalization import CACHE, EXPANSION, GIB, HIDDEN, LAYERS, host_available
from tri_oracle_integer_reference import IntegerFeedForwardReference
from verify_tri_oracle_packed_down_weights import ROOT, sha256


ESCAPE_LIMITS = (7, 15, 31, 63)
MODES = ("scalar", "fixed_escape_classes")


def read(path):
    return json.loads(path.read_text())


def retain_escape_classes(original, candidate):
    """Keep all four literal flags for every signed eight-bit weight [H,K]."""
    baseline = original.to(torch.int16).abs()  # [H,K], cannot overflow at -128
    changed = candidate.to(torch.int16).abs()  # [H,K], candidate magnitude
    crossed = torch.zeros_like(original, dtype=torch.bool)  # [H,K]
    for threshold in ESCAPE_LIMITS:
        crossed |= (baseline > threshold) != (changed > threshold)
    selected = torch.where(crossed, original, candidate)  # [H,K], one code step maximum
    final = selected.to(torch.int16).abs()  # [H,K]
    assert all(torch.equal(final > limit, baseline > limit) for limit in ESCAPE_LIMITS)
    return selected


@torch.inference_mode()
def run(output):
    assert __debug__ and Path("/.dockerenv").is_file()
    assert int(Path("/sys/fs/cgroup/memory.max").read_text()) <= 2 * GIB and host_available() >= 10 * GIB
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.set_float32_matmul_precision("highest")
    assert torch.cuda.mem_get_info()[0] >= 3 * GIB
    torch.cuda.set_per_process_memory_fraction(0.10)
    torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    earlier = CACHE / "gqa_testdev/down_code_calibration_export/receipt.json"
    calibrated_record = ROOT / "records/tri_oracle_down_code_calibration.json"
    transport_record = ROOT / "records/tri_oracle_calibrated_weight_transport.json"
    saved = read(calibrated_record)
    assert sha256(earlier) == saved["evidence_sha256"][str(earlier.relative_to(ROOT))]
    channel = read(earlier)
    evidence = channel["evidence_sha256"].copy()
    for path in (Path(__file__).resolve(), earlier, calibrated_record, transport_record,
                 Path(transfer_size.__code__.co_filename).resolve()):
        evidence[str(path)] = sha256(path)
    assert all(sha256(Path(path)) == checksum for path, checksum in evidence.items())
    model = CACHE / "tiny_llava_v1"
    mapping = read(model / "model.safetensors.index.json")["weight_map"]
    epsilon = read(model / "config.json")["text_config"]["rms_norm_eps"]
    archive = torch.load(CACHE / "format320/captured_rows.pt", map_location="cpu", weights_only=True, mmap=True)
    policies = read(CACHE / "format335/layer_policy.json")["layers"]
    indices = [row for row in range(256) if row % 16]
    fit, validation, calibration, hold = slice(0, 60), slice(60, 120), slice(0, 120), slice(120, 240)
    assert len(archive) == len(policies) == LAYERS
    output.mkdir()
    code_dir = output / "fixed_escape_codes"
    code_dir.mkdir()
    layers = []
    for index, (capture, policy) in enumerate(zip(archive, policies, strict=True)):
        assert host_available() >= 8.5 * GIB
        matrices = []
        for suffix in ("gate", "up", "down"):
            key, = (name for name in mapping if name.endswith(f".layers.{index}.mlp.{suffix}_proj.weight"))
            with safe_open(model / mapping[key], framework="pt", device="cpu") as shard:
                matrices.append(shard.get_tensor(key).to(device="cuda", dtype=torch.float32))
        gate, up, down = matrices  # [K,H], [K,H], [H,K], with K=5,632 and H=2,048
        assert gate.shape == up.shape == (EXPANSION, HIDDEN) and down.shape == (HIDDEN, EXPANSION)
        reference = IntegerFeedForwardReference(gate, up, down, epsilon)
        original = reference.down  # [H,K], existing scalar quantizer's emitted codes
        exponent = torch.full((1, 1), reference.down_exponent, dtype=torch.int32, device=original.device)
        activation, residual, targets = (capture[name][indices].to(device="cuda", dtype=torch.float32)
                                         for name in ("activation", "residual", "target"))  # [240,H]
        codes, shifts, baseline = reconstruct_input(reference, activation, residual, policy)

        def fit_mode(rows, fraction):
            return fit_codebook(codes[rows], shifts[rows], baseline[rows], targets[rows], original, exponent, fraction)

        def measure(rows, weights):
            return score(codes[rows], shifts[rows], targets[rows], weights, exponent)

        valid = {mode: {IDENTITY: measure(validation, original)} for mode in MODES}
        for fraction in RIDGE_FRACTIONS:
            tested = fit_mode(fit, fraction)  # [H,K], calibration fitting images only
            valid["scalar"][str(fraction)] = measure(validation, tested)
            valid["fixed_escape_classes"][str(fraction)] = measure(validation, retain_escape_classes(original, tested))
        row = {"layer": index, "scale_exponent": reference.down_exponent, "baseline": measure(hold, original),
               "baseline_transport": transfer_size(pack(original.cpu())), "modes": {}}
        for mode in MODES:
            choice = min(valid[mode], key=valid[mode].__getitem__)
            candidate = original if choice == IDENTITY else fit_mode(calibration, float(choice))  # [H,K]
            if mode == "fixed_escape_classes":
                candidate = retain_escape_classes(original, candidate)
            measured = transfer_size(pack(candidate.cpu()))
            row["modes"][mode] = {"validation": valid[mode], "choice": choice,
                                    "held_error": measure(hold, candidate), "transport": measured,
                                    "changed_codes": int(candidate.ne(original).sum())}
            if mode == "fixed_escape_classes":
                assert measured == row["baseline_transport"]
                path = code_dir / f"down_{index:02d}.pt"
                with path.open("xb") as stream:
                    torch.save({"codes": candidate.cpu(), "scale": exponent.cpu()}, stream)
                row["modes"][mode]["codebook_sha256"] = sha256(path)
        layers.append(row)
        print("SCALAR_DOWN_CALIBRATION", index, row["baseline"],
              {mode: row["modes"][mode]["held_error"] for mode in MODES}, flush=True)
    assert all(sha256(Path(path)) == checksum for path, checksum in evidence.items())
    aggregate = {"baseline": sum(row["baseline"] for row in layers) / LAYERS}
    aggregate.update({mode: sum(row["modes"][mode]["held_error"] for row in layers) / LAYERS for mode in MODES})
    selection = {mode: Counter(row["modes"][mode]["choice"] for row in layers) for mode in MODES}
    result = {"state": "scalar_down_code_calibration_and_fixed_escape_transport_measured", "layers": layers,
              "held_mean_relative_error": aggregate, "held_images": 8, "held_rows_per_layer": 120,
              "selection_counts": selection, "checkpoint_revision": channel["checkpoint_revision"],
              "peak_gpu_bytes": torch.cuda.max_memory_allocated(), "elapsed_seconds": time.monotonic()-started,
              "evidence_sha256": evidence,
              "scope": "Paired layer error with one unchanged weight exponent per matrix. The fixed-escape mode "
                       "preserves every literal decision for every supported packed width, so tile transfer lengths "
                       "remain exact. Answer accuracy and mapped execution require additional verification."}
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print("SCALAR_DOWN_CALIBRATION_COMPLETE", aggregate, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)
