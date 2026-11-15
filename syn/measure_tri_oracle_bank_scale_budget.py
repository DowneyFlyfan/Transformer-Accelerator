"""Fit one-bit scale choices for 32-output banks under exact transfer budgets."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
from safetensors import safe_open
import torch

from audit_tri_oracle_calibrated_weight_transport import pack, transfer_size
from measure_tri_oracle_down_code_calibration import reconstruct_input
from measure_tri_oracle_input_equalization import CACHE, GIB, HIDDEN, LAYERS, host_available
from tri_oracle_integer_reference import IntegerFeedForwardReference, _dot, _quantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


BANK_ROWS = 32
BANKS = HIDDEN // BANK_ROWS
BUDGET_PERCENT = (0, 5, 10, 20)


def read(path):
    return json.loads(path.read_text())


def bank_payloads(codes):
    """Count 64-byte transfers per bank from signed weight codes [H,K]."""
    packed = pack(codes.cpu())  # [8-row group, weight word, byte]
    magnitude = np.abs(packed.astype(np.int16))  # [256,704,64], safe at -128
    body = np.full(magnitude.shape[:-1], 64, dtype=np.int16)  # [256,704]
    for width in range(4, 8):
        escapes = (magnitude > (1 << (width - 1)) - 1).sum(axis=-1)  # Escapes per group and word
        np.minimum(body, width * 8 + escapes, out=body, casting="unsafe")
    words = (((body + 3) & ~3).reshape(BANKS, 4, 704)).sum(axis=1) + 8  # [64,704]
    beats = np.zeros(BANKS, dtype=np.int64)  # [B], B counts output banks
    for segment in range(4):
        for offset in range(0, 176, 32):
            length = min(32, 176 - offset)
            start = segment * 176 + offset
            stored = np.minimum(words[:, start:start + length].sum(axis=1), length * 256)  # [B]
            beats += (stored + 63) // 64
    assert int(beats.sum()) == transfer_size(packed)["payload_beats"]
    return beats


def choose_under_limit(costs, improvements, limit):
    """Maximize the total calibration improvement with an exact integer budget.

    One column is chosen per row. Both arrays are [bank, option]. Ties prefer
    lower option numbers at the same cost, then the smaller total cost.
    """
    assert costs.shape == improvements.shape and costs.ndim == 2
    assert (costs >= 0).all() and (costs[:, 0] == 0).all() and limit >= 0
    values = np.full(limit + 1, -np.inf)  # [budget+1], exact used cost
    values[0] = 0
    used_option = np.full((len(costs), limit + 1), -1, dtype=np.int8)  # [B,budget+1], backtracking choices
    for bank, row in enumerate(costs):
        following = np.full_like(values, -np.inf)  # [budget+1], after adding this bank
        for option, price in enumerate(row):
            if price > limit:
                continue
            trial = values[:limit + 1 - price] + improvements[bank, option]  # Fits at the new cost
            better = trial > following[price:]  # Same length as trial, strict improvement
            following[price:][better] = trial[better]
            used_option[bank, price:][better] = option
        values = following
    price = int(values.argmax())
    choices = [0] * len(costs)
    for bank in reversed(range(len(costs))):
        option = int(used_option[bank, price])
        assert option >= 0
        choices[bank] = option
        price -= costs[bank, option]
    assert price == 0
    return choices


def layer_measure(reference, down, capture, policy, fixed_path):
    """Evaluate [M,H] outputs for [H,K] weights and one scale bit per bank."""
    indices = [row for row in range(256) if row % 16]
    activation, residual, targets = (capture[name][indices].cuda() for name in ("activation", "residual", "target"))  # [M,H] each
    inputs, row_exponent, original_output = reconstruct_input(reference, activation, residual, policy)  # [M,K], [M,1], [M,H]
    target_norm = targets.norm(dim=1, keepdim=True).clamp_min(1e-20)  # [M,1]
    scalar = reference.down  # [H,K], baseline emitted weights
    exponent = reference.down_exponent
    fixed = torch.load(fixed_path, map_location="cpu", weights_only=True)
    assert int(fixed["scale"].item()) == exponent
    tuned = fixed["codes"].cuda()  # [H,K], unchanged compression decisions
    step = torch.full((BANKS, 1), exponent - 1, dtype=torch.int32, device=down.device)  # [B,1], candidate exponent
    expanded_exponent = step.repeat_interleave(BANK_ROWS, dim=0)  # [H,1]
    expanded_weights = torch.ldexp(down, -expanded_exponent)  # [H,K], finer code units
    finer = (expanded_weights.sign() * torch.floor(expanded_weights.abs() + 0.5)).clamp(-128, 127).to(torch.int8)  # [H,K]
    # A bank's one-bit scale option may saturate a few weights. Its cost and
    # calibration loss account for the weights actually representable there.
    weight_options = (scalar, tuned, finer)  # Each [H,K]
    scalar_beats, tuned_beats, finer_beats = (bank_payloads(weights) for weights in weight_options)  # [B] each
    assert np.array_equal(scalar_beats, tuned_beats) and (finer_beats >= scalar_beats).all()
    options = [original_output]  # Each [M,H], scale applied after the integer dot.
    for weights, weight_exponent in ((tuned, exponent), (finer, exponent-1)):
        options.append(torch.ldexp(_dot(inputs, weights).float(), row_exponent+weight_exponent))
    errors = torch.stack([((values-targets)/target_norm).reshape(len(indices), BANKS, BANK_ROWS).square().sum(2)
                          for values in options], dim=2)  # [M,B,3] squared relative contribution
    fit = errors[:120].mean(dim=0).cpu().numpy()  # [B,3], calibration images only
    improvements = fit[:, :1] - fit  # [B,3], additive loss improvement
    costs = np.stack((np.zeros_like(scalar_beats), np.zeros_like(scalar_beats), finer_beats - scalar_beats), axis=1)  # [B,3]
    measured = {}
    for percent in BUDGET_PERCENT:
        limit = int(scalar_beats.sum())*percent//100
        choices = choose_under_limit(costs, improvements, limit)
        used = sum(int(costs[bank, option]) for bank, option in enumerate(choices))
        assert used <= limit
        selected = errors[:, list(range(BANKS)), choices]  # [M,B], frozen choices
        weights = torch.cat([
            weight_options[option][bank * BANK_ROWS:(bank + 1) * BANK_ROWS]
            for bank, option in enumerate(choices)
        ])  # [H,K], assembled to audit the complete transport image
        assert int(bank_payloads(weights).sum()) == int(scalar_beats.sum())+used
        measured[percent] = {"payload_beats":int(scalar_beats.sum())+used,"finer_banks":choices.count(2),
                             "held_error":float(selected[120:].sum(dim=1).sqrt().mean()),
                             "choices":choices}
    channel, power = _quantize(down, per_row=True)  # [H,K] codes and [H,1] exponents
    channel_out = torch.ldexp(_dot(inputs,channel).float(),row_exponent+power.T)  # [M,H]
    return {"scalar_error":float(errors[120:,:,0].sum(dim=1).sqrt().mean()),
            "channel_error":float(((channel_out-targets)/target_norm)[120:].norm(dim=1).mean()),
            "scalar_payload_beats":int(scalar_beats.sum()),
            "channel_payload_beats":int(bank_payloads(channel).sum()),
            "budgets":measured}


@torch.inference_mode()
def run(output):
    assert Path("/.dockerenv").is_file() and __debug__
    assert int(Path("/sys/fs/cgroup/memory.max").read_text()) <= 2*GIB and host_available() >= 10*GIB
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.set_float32_matmul_precision("highest")
    assert torch.cuda.mem_get_info()[0] >= 3*GIB
    torch.cuda.set_per_process_memory_fraction(0.10)
    started = time.monotonic()
    source = CACHE / "gqa_testdev/scalar_down_code_calibration/receipt.json"
    native = ROOT / "records/tri_oracle_scalar_down_calibration.json"
    assert sha256(source) == read(native)["evidence_sha256"][str(source.relative_to(ROOT))]
    baseline = read(source)
    evidence = baseline["evidence_sha256"].copy()
    channel_receipt = CACHE / "gqa_testdev/activation_range_per_row/receipt.json"
    for path in (source, native, channel_receipt, Path(__file__).resolve(),
                 ROOT / "syn/audit_tri_oracle_calibrated_weight_transport.py"):
        evidence[str(path)] = sha256(path)
    assert all(sha256(Path(path)) == digest for path,digest in evidence.items())
    model = CACHE / "tiny_llava_v1"
    mapping = read(model / "model.safetensors.index.json")["weight_map"]
    epsilon = read(model / "config.json")["text_config"]["rms_norm_eps"]
    archive = torch.load(CACHE / "format320/captured_rows.pt", map_location="cpu", weights_only=True, mmap=True)
    policies = read(CACHE / "format335/layer_policy.json")["layers"]
    channel = read(channel_receipt)
    layers = []
    for index,(capture,policy) in enumerate(zip(archive,policies,strict=True)):
        assert host_available() >= 8.5*GIB
        weights = []
        for role in ("gate","up","down"):
            key, = (name for name in mapping if name.endswith(f".layers.{index}.mlp.{role}_proj.weight"))
            with safe_open(model/mapping[key],framework="pt",device="cpu") as shard:
                weights.append(shard.get_tensor(key).cuda())  # [K,H], [K,H], [H,K]
        fixed = source.parent / f"fixed_escape_codes/down_{index:02d}.pt"
        prior = baseline["layers"][index]
        evidence[str(fixed)] = sha256(fixed)
        assert evidence[str(fixed)] == prior["modes"]["fixed_escape_classes"]["codebook_sha256"]
        reference = IntegerFeedForwardReference(*weights,epsilon)
        row = layer_measure(reference,weights[-1],capture,policy,fixed)
        assert abs(row["scalar_error"]-prior["baseline"]) < 1e-7
        assert abs(row["channel_error"]-channel["layers"][index]["held"]["0"]["mean_relative_output_error"]) < 1e-7
        assert row["scalar_payload_beats"] == prior["baseline_transport"]["payload_beats"]
        layers.append({"layer":index,**row})
        print("BANK_SCALE_LAYER",index,row["scalar_error"],{k:v["held_error"] for k,v in row["budgets"].items()},flush=True)
    assert len(layers)==LAYERS and all(sha256(Path(path))==digest for path,digest in evidence.items())
    result = {"state":"bank_scale_budget_heldout_and_exact_transfer_sizes_measured","layers":layers,
              "evidence_sha256":evidence,"gpu_peak_bytes":torch.cuda.max_memory_allocated(),
              "wall_seconds":time.monotonic()-started,
              "scope":"Frozen prompt rows and exact encoded down-weight loads. A budget is per layer. The grouped "
                      "output scale is evaluated in software and needs a matched writeback implementation, answer "
                      "accuracy tests, and full-chip performance qualification."}
    output.mkdir()
    with (output / "receipt.json").open("x") as stream:
        json.dump(result,stream,indent=2,sort_keys=True)
        stream.write("\n")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    run(parser.parse_args().output)
