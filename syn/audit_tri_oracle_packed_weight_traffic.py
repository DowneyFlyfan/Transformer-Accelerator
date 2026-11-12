"""Reconstruct external weight traffic for the bit-exact trained frame."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_parallel_chip_synthesis import BASE, pin, read, verify
from verify_tri_oracle_packed_down_weights import ROOT


TOKENS, HIDDEN, CHANNELS = 16, 2048, 5632
PACKED_WORD, RESPONSE_BYTES = 8, 64


def read_rows(path, columns):
    values = [int(item, 16) for item in path.read_text().split()]
    assert len(values) == TOKENS * columns and all(0 <= value < 256 for value in values), path
    return [values[start:start + columns] for start in range(0, len(values), columns)]


def active_positions(rows):
    return [any(column) for column in zip(*rows, strict=True)]


def packed_words(active):
    assert len(active) % PACKED_WORD == 0
    return sum(any(active[start:start + PACKED_WORD]) for start in range(0, len(active), PACKED_WORD))


def project_traffic(keep, activation, down_input):
    retained = active_positions(keep)
    active_gate_input = active_positions(activation)
    active_down_input = active_positions(down_input)
    gate_groups = packed_words(retained)
    gate_words = packed_words(active_gate_input)
    down_words = packed_words(active_down_input)
    assert len(activation[0]) == HIDDEN and len(keep[0]) == len(down_input[0]) == CHANNELS

    # The scheduler transmits a whole 8-by-8 block if any row and input word
    # in the block can be used by the batch.
    gate_beats = gate_groups * gate_words
    down_beats = (HIDDEN // PACKED_WORD) * down_words

    # An element-addressable version can omit a weight position only if no
    # token both keeps its output channel and uses its input feature.
    feature_bits = [int.from_bytes(bytes(bool(value) for value in row), "little") for row in activation]
    gate_positions = 0
    for keep_column in zip(*keep, strict=True):
        used = 0
        for enabled, features in zip(keep_column, feature_bits, strict=True):
            if enabled:
                used |= features
        gate_positions += used.bit_count()
    return {
        "retained_gate_channels": sum(retained), "active_gate_input_features": sum(active_gate_input),
        "active_down_input_channels": sum(active_down_input), "gate_row_groups": gate_groups,
        "gate_input_words": gate_words, "down_input_words": down_words,
        "packed_beats": {"gate": gate_beats, "up": gate_beats, "down": down_beats},
        "weight_bytes": RESPONSE_BYTES * (2 * gate_beats + down_beats),
        "element_addressable_weight_positions": 2 * gate_positions + HIDDEN * sum(active_down_input),
    }


def run(output):
    record = ROOT / "records/wac_paired_chip_trained_result.json"
    evidence = read(record)
    assert evidence["state"] == "single_packed_lane_matched_full_width_trained_layer_from_checkpoint_images"
    run_dir = BASE / "paired_chip/full_native"
    receipt = run_dir / "trained_receipt.json"
    log = run_dir / "trained/xrun.log"
    pins = {}
    for path in (receipt, log):
        pin(pins, path, evidence["evidence_sha256"][str(path.relative_to(ROOT))])
    native = read(receipt)
    assert native["state"] == "paired_chip_replayed_exact_trained_frame_from_all_packed_weight_images"
    assert native["native"]["native_exit_status"] == 0 and native["native"]["log_sha256"] == pins[str(log.relative_to(ROOT))]
    assert native["counters"] == evidence["training_frame"] and native["counters"]["exact_outputs"] == TOKENS * HIDDEN
    fixture = ROOT / ".cache/model_reference"
    masks, activations, intermediate, pairs = (fixture / item for item in (
        "batch389/keep.hex", "batch403/activation.hex", "batch407/intermediate.hex", "batch396/outlier_pairs.hex"))
    bench = run_dir / "trained_tb.sv"
    scheduler = ROOT / "verilog/tri_oracle_packed_weight_schedule.sv"
    tensor = BASE / "paired_chip/tri_oracle_batched_tensor390.sv"
    for path in (masks, activations, intermediate, pairs, bench, scheduler, tensor):
        pin(pins, path, native["input_sha256"][str(path.relative_to(ROOT))])
    keep = read_rows(masks, CHANNELS)
    activation = read_rows(activations, HIDDEN)
    down_input = read_rows(intermediate, CHANNELS)
    assert all(value in (0, 1) for row in keep for value in row)
    assert all(enabled or value == 0 for mask, row in zip(keep, down_input, strict=True)
               for enabled, value in zip(mask, row, strict=True))
    predicted_skips = [CHANNELS - sum(row) for row in keep]
    assert 0 < sum(predicted_skips) < TOKENS * CHANNELS
    observed = project_traffic(keep, activation, down_input)
    log_text = log.read_text()
    branch, = re.findall(r"(?m)^PACKED_PAIR_BRANCHES gate_wide=(\d+) up_wide=(\d+) down_wide=(\d+) "
                         r"gate_narrow=0 up_narrow=0 down_narrow=0$", log_text)
    native_beats = dict(zip(("gate", "up", "down"), map(int, branch), strict=True))
    assert observed["packed_beats"] == native_beats == evidence["packed_weight_responses_by_projection"]
    assert log_text.count("Simulation complete via $finish(1)") == 1
    sign_reads, = re.findall(r"(?m)^BATCH408_SHARED_BUS sign_requests=(\d+) valid_masks=71 contended_cycles=\d+$", log_text)
    pair_masks = [int(item, 16) for item in pairs.read_text().split()]
    assert len(pair_masks) == TOKENS and all(item.bit_length() <= HIDDEN // 2 for item in pair_masks)
    assert int(sign_reads) == 2 * (CHANNELS // 32) * sum(item.bit_count() for item in pair_masks)
    assert 'if(req_length!=1)$fatal(1,"BATCH408_SIGN_BURST");' in bench.read_text()
    sign_bytes = int(sign_reads) * 8
    dense_bytes = 3 * HIDDEN * CHANNELS
    assert observed["weight_bytes"] == dense_bytes

    trial_bytes = {}
    for size in (1, 2, 4, 8, 16):
        trial_bytes[str(size)] = sum(project_traffic(keep[start:start + size], activation[start:start + size],
                                                   down_input[start:start + size])["weight_bytes"]
                                     for start in range(0, TOKENS, size))
    assert trial_bytes["16"] == observed["weight_bytes"]
    for path in (record, Path(__file__).resolve()):
        pin(pins, path)
    verify(pins)
    result = {"state": "packed_trained_frame_weight_traffic_reconstructed_exactly",
              "tokens": TOKENS, "verified_outputs": native["counters"]["exact_outputs"],
              "predicted_skips_by_token": predicted_skips, "predicted_skipped_channels": sum(predicted_skips),
              "dense_weight_payload_bytes_at_same_batch_size": dense_bytes, **observed,
              "sign_bytes": sign_bytes, "weight_and_sign_bytes": observed["weight_bytes"] + sign_bytes,
              "weight_payload_bytes_by_group_size_without_cross_group_reuse": trial_bytes,
              "input_sha256": pins,
              "scope": "One trained sixteen-token simulation. The regrouping figures are arithmetic for the current packed layout."}
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], native_beats, sum(predicted_skips), sign_bytes, trial_bytes, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
