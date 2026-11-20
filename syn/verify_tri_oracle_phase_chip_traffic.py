"""Reconcile native trained memory payload with the archived weight packing."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from prepare_tri_oracle_batch407_learned_fixture import byte_codes, word_codes
from tri_oracle_integer_reference import _dot
from verify_tri_oracle_mapped_weight_prefetch import invocation
from verify_tri_oracle_phase_chip import INCLUDE, ROOT, require, summary, verify_case


MODELS = ROOT / ".cache/model_reference"
RECORDS = ROOT / "records"
RUN = ROOT / ".cache/phase_chip"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def demand(keep, activation, intermediate, output_features):
    keep_blocks = keep.reshape(keep.shape[0], -1, 8).any(2)
    activation_words = activation.reshape(activation.shape[0], -1, 8).any(2)
    gate = (keep_blocks[:, :, None] & activation_words[:, None, :]).any(0)
    down_words = intermediate.reshape(intermediate.shape[0], -1, 8).any(2).any(0)
    return int(gate.sum()), int(down_words.sum()) * (output_features // 8)


def compare_zero_mask_union_counterfactual(arrays, archives, evidence):
    keep, activation, _ = arrays
    tokens, channels = keep.shape
    paper = ROOT / PAPER_RELATIVE
    require(digest(paper) == PAPER_SHA256, "paper edition changed")
    bundle = RUN / "source/bundle.sv"
    predictor, = (Path(path) for path in INCLUDE.findall(bundle.read_text())
                  if Path(path).name == "tri_oracle_strip_predictor.sv")
    require("(gate_mask & up_mask)" in predictor.read_text(), "packed core mask rule changed")
    branch = MODELS / "batch396/branch_masks.hex"
    receipt = RECORDS / "batch396_mask_fixture.json"
    require(digest(branch) == json.loads(receipt.read_text())["files_sha256"][str(branch)],
            "archived branch masks changed")
    words = [int(word, 16) for word in branch.read_text().split()]
    planes = np.array([[(word >> shift) & 0xffffffff for shift in (64, 32, 0)] for word in words],
                      dtype=np.uint32)
    bits = (planes[..., None] >> np.arange(32, dtype=np.uint32)) & 1
    gate_zero, up_zero, old_skip = bits.reshape(tokens, channels // 32, 3, 32).transpose(2, 0, 1, 3)
    gate_zero, up_zero, old_skip = (plane.reshape(keep.shape).astype(bool)
                                    for plane in (gate_zero, up_zero, old_skip))
    require(np.array_equal(old_skip, gate_zero & up_zero) and np.array_equal(~old_skip, keep),
            "archived keep mask differs from the implemented branch intersection")
    # The page-one weight-prediction paragraph identifies near-zero locations
    # shared by BOTH branches. The archived skip intersection follows that rule.
    # This alternative instead skips either branch's near-zero prediction; it
    # is a local counterfactual, not the paper's rule. Thresholds stay frozen.
    union_keep = ~gate_zero & ~up_zero
    require(not np.any(union_keep & ~keep), "counterfactual would require unarchived gated values")
    hidden = activation.shape[1]
    intermediate_path, down_path, expected_path = archives
    original = byte_codes(intermediate_path, keep.shape)
    alternate = np.where(union_keep, original, 0).astype(np.int8)
    weights = byte_codes(down_path, (hidden, channels))
    frozen = word_codes(expected_path)
    baseline = _dot(torch.as_tensor(original, device="cuda"), torch.as_tensor(weights, device="cuda"))
    changed = _dot(torch.as_tensor(alternate, device="cuda"), torch.as_tensor(weights, device="cuda")).cpu().numpy()
    require(np.array_equal(baseline.cpu().numpy(), frozen), "archived arithmetic did not reproduce the replay")
    require(np.array_equal(alternate.astype(np.int32) @ weights.astype(np.int32).T, changed),
            "processor and graphics-card counterfactual dot products disagreed")
    gate, down = demand(union_keep, activation, alternate != 0, hidden)
    require(demand(*(torch.as_tensor(a, device="cuda") for a in (union_keep, activation, alternate != 0)),
                   hidden) == (gate, down), "counterfactual traffic accounting disagreed")
    evidence.extend((paper, bundle, predictor, branch, receipt, *archives,
                     ROOT / "syn/prepare_tri_oracle_batch407_learned_fixture.py",
                     ROOT / "syn/tri_oracle_integer_reference.py"))
    return {"skipped_token_channels": int((~union_keep).sum()), "changed_integer_outputs": int((frozen != changed).sum()),
            "projected_weight_payload_bytes": (2 * gate + down) * 64,
            "counterfactual_skip_rule": "gate_nearzero OR up_nearzero",
            "paper_skip_rule": "gate_nearzero AND up_nearzero",
            "paper_rule_agrees_with_archived_hardware": True,
            "scope": "Host counterfactual with the archived branch thresholds and weights. "
                     "The union of near-zero masks is a local alternative, not the paper's rule. "
                     "The page-one weight-prediction paragraph requires near-zero locations shared by both branches. "
                     "Model accuracy has a separate benchmark."}


def verify():
    require(not Path("/.dockerenv").exists(), "run this software verification on the host")
    require(torch.cuda.is_available() and torch.cuda.mem_get_info()[0] > 1024**3,
            "need at least one gibibyte available on the graphics card")
    output, phases = verify_case(RUN, "trained")
    native = summary(output, "BATCH408_PASS")
    require(native["trained"] == 1 and native["exact_outputs"] == native["tokens"] * native["outputs"],
            "incomplete native workload")
    tokens, hidden, channels, output_features = (native[key] for key in ("tokens", "hidden", "intermediate", "outputs"))
    require(all(n % 8 == 0 for n in (hidden, channels, output_features)), "partial packed word in trained workload")
    proof = RECORDS / "tri_oracle_phase_chip_trained.json"
    reference = json.loads(proof.read_text())
    log = RUN / "trained/xrun.log"
    require(reference["evidence_sha256"][str(log.relative_to(ROOT))] == digest(log)
            and reference["cases"]["trained"]["command"] == native, "trained simulator transcript changed")
    args = {line.strip() for line in invocation(output)}
    evidence = [proof, log, RUN / "trained/exit_status", Path(__file__).resolve()]

    arrays = []
    for option, folder, filename, record, width in (
        ("FIXTURE", "batch389", "keep.hex", "batch389_fixture_preparation.json", channels),
        ("LEARNED_FIXTURE", "batch403", "activation.hex", "batch403_activation_precision.json", hidden),
        ("INTERMEDIATE_FIXTURE", "batch407", "intermediate.hex", "batch407_learned_fixture.json", channels),
    ):
        path = MODELS / folder / filename
        archive = RECORDS / record
        require(f"+{option}={path.parent}" in args and
                digest(path) == json.loads(archive.read_text())["files_sha256"][str(path)],
                f"workload input changed: {path.name}")
        raw = np.fromiter((int(word, 16) for word in path.read_text().split()), dtype=np.uint8)
        arrays.append(raw.reshape(tokens, width) != 0)
        evidence.extend((archive, path))
    gate, down = demand(*arrays, output_features)
    require(demand(*(torch.as_tensor(a, device="cuda") for a in arrays), output_features) == (gate, down),
            "processor and graphics-card traffic accounting disagreed")
    branch = summary(output, "PACKED_PAIR_BRANCHES")
    require((branch["gate_wide"], branch["up_wide"], branch["down_wide"]) == (gate, gate, down)
            and not any(branch[name + "_narrow"] for name in ("gate", "up", "down")),
            "predicted group demand differs from the native weight transfers")
    beats = summary(output, "PACKED_DECODER_PASS")["wide_beats"]
    require(beats == 2 * gate + down == phases["packed"], "native weight counts disagree")
    signs = summary(output, "DUAL_LANE_PACKED_SIGN_PASS")
    require(signs["responses"] == signs["requests"], "incomplete predictor reads")
    targets_path = RECORDS / "paper_result_targets.json"
    target = json.loads(targets_path.read_text())
    prior = RECORDS / "tri_oracle_archived_weight_batching_bounds.json"
    require(json.loads(prior.read_text())["minimum_weight_bytes_with_current_64_byte_layout"] == 64 * beats,
            "this replay changed the archived packing bound")
    evidence.extend((targets_path, prior))
    archive_paths = [MODELS / item for item in ("batch407/intermediate.hex", "batch389/down.hex", "batch403/expected.hex")]
    for path, record in zip(archive_paths, ("batch407_learned_fixture.json", "batch389_fixture_preparation.json",
                                           "batch403_activation_precision.json"), strict=True):
        require(digest(path) == json.loads((RECORDS / record).read_text())["files_sha256"][str(path)],
                f"archived arithmetic input changed: {path.name}")
    alternative = compare_zero_mask_union_counterfactual(arrays, archive_paths, evidence)
    dense_bytes = 2 * hidden * channels + output_features * channels
    return {
        "state": "trained_two_phase_weight_payload_reconciled",
        "tokens": tokens,
        "exact_outputs": native["exact_outputs"],
        "gate_up_skipped_token_channels": arrays[0].size - int(arrays[0].sum()),
        "gate_up_token_channels": arrays[0].size,
        "weight_payload_bytes": 64 * beats,
        "dense_weight_payload_bytes": dense_bytes,
        "weight_payload_reduction_percent": 100 * (dense_bytes - 64 * beats) / dense_bytes,
        "additional_predictor_sign_payload_bytes": 64 * signs["responses"],
        "paper_feedforward_external_access_reduction_percent":
            target["disclosed_method_gains"]["feed_forward_external_memory_access_reduction_percent"],
        "graphics_card": torch.cuda.get_device_name(),
        "zero_mask_union_counterfactual": alternative,
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in sorted(set(evidence))},
        "scope": "Weight and predictor-sign read payloads of one trained layer over 16 tokens. "
                 "The paper reports feedforward external-memory accesses under its own workload and reduction settings.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path)
    args = parser.parse_args()
    result = verify()
    if args.record:
        args.record.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Verified {result['weight_payload_bytes']:,} weight bytes and "
          f"{result['additional_predictor_sign_payload_bytes']:,} predictor sign bytes.")
