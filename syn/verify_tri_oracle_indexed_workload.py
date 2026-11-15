"""Independently reconcile the indexed workload and screen intermediate write widths."""

import argparse
from collections import Counter
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_packed_weight_path import STAGE, module_body, pins
from audit_tri_oracle_placed_chip_boundary import digest
from link_tri_oracle_indexed_whole_chip import module_at, signature, spans


KEY_REPLAY = Path("records/tri_oracle_repaired_native_mixed_attention.json")
WRAPPER = "tri_oracle_shared_memory_layer_PACKED_FEEDFORWARD_WEIGHTS1_parallel_chip"
ARBITER = "tri_oracle_wide_read_arbiter_parallel_chip"
KEY = "tri_oracle_key_redirect"
VALUE = "tri_oracle_wide_value_response"
ATTENTION_READS = {
    "key_redirect": KEY,
    "wide_attention_response": VALUE,
    "primary_key_reads": ARBITER,
    "wide_attention_reads": ARBITER,
}


def check_wide_transfers(before, after):
    original = {name: pins(before, master, name) for name, master in ATTENTION_READS.items()}
    linked = {name: pins(after, master, name) for name, master in ATTENTION_READS.items()}
    assert original == linked
    for name in ("primary_key_reads", "wide_attention_reads"):
        assert linked[name]["client_req_length[1]"] == b"{1'b0,1'b0,1'b0,1'b0,1'b0,1'b1}"


def verify_attention_transfer(candidate, fixture):
    evidence = fixture["evidence_sha256"]
    base, = (Path(name) for name in evidence if name.endswith("/legality/cold.v"))
    native_log, = (Path(name) for name in evidence if name.endswith("/mixed_attention/xrun.log"))
    assert digest(base) == evidence[str(base)] == fixture["repaired_netlist_sha256"]
    assert digest(native_log) == evidence[str(native_log)] and fixture["native"]["exit_status"] == 0

    with (
        base.open("rb") as original, candidate.open("rb") as linked,
        mmap.mmap(original.fileno(), 0, access=mmap.ACCESS_READ) as before,
        mmap.mmap(linked.fileno(), 0, access=mmap.ACCESS_READ) as after,
    ):
        old_index, new_index = spans(before), spans(after)
        for name in {KEY, VALUE, ARBITER, "tri_oracle_key_buffer_external_storage",
                     "tri_oracle_shared_sign_key_bank"}:
            assert module_at(before, old_index, name) == module_at(after, new_index, name), name
        check_wide_transfers(module_at(before, old_index, WRAPPER),
                             module_at(after, new_index, WRAPPER))

    transcript = native_log.read_text()
    rows = re.findall(r"(?m)^MIXED_ATTENTION_ROW head=(\d+) position=(\d+) values=(\d+) key_beats=(\d+)$",
                      transcript)
    external_keys = re.findall(r"(?m)^WIDE_KEY_REPLAY_ROW head=(\d+) position=(\d+) external_keys=(\d+)$",
                               transcript)
    assert len(rows) == len(external_keys) == fixture["matched_attention_rows"] == 10
    counts = []
    for (head, position, values, words), (key_head, key_position, keys) in zip(
        rows, external_keys, strict=True
    ):
        assert (head, position, values) == (key_head, key_position, keys)
        assert int(keys) > 0 and int(words) == 8 * int(keys)
        counts.append(int(keys))
    (keys, values), = re.findall(r"(?m)^WIDE_KEY_CHIP_PASS key_vectors=(\d+) value_vectors=(\d+)$",
                                 transcript)
    assert int(keys) == int(values) == sum(counts)
    return {
        "measured_netlist_sha256": fixture["repaired_netlist_sha256"],
        "rows": len(rows),
        "external_512_bit_key_responses": int(keys),
        "external_512_bit_value_responses": int(values),
        "internal_64_bit_key_words": 8 * sum(counts),
        "mapped_transport_and_named_connections_preserved": True,
    }


def verify(measurement, candidate):
    assert __debug__
    data = json.loads(measurement.read_text())
    assert data["state"] == "all_layer_indexed_read_and_write_service_scenarios_measured"
    assert digest(candidate) == data["linked_candidate_sha256"]
    for name, expected in data["evidence_sha256"].items():
        assert digest(Path(name)) == expected, name
    with candidate.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        ports = signature(f"module {STAGE} (".encode() + module_body(source, STAGE))
        assert all(ports[f"write_payload[{lane}]"] == (b"output", b"[511:0]") for lane in range(2))

    layers = data["layers"]
    assert [row["layer"] for row in layers] == list(range(22))
    workload = Counter()
    cycle_counts = Counter()
    width_pairs = (1, 2, 4)
    for layer in layers:
        batch_count = sum(layer["batches"].values())
        workload.update(layer["batches"])
        for branch, expected_tiles, expected_words in (("paired", 2816, 360448), ("down", 1536, 180224)):
            lanes = layer[f"{branch}_lanes"]
            assert [sum(lane[key] for lane in lanes) for key in ("tiles", "write_beats")] == [
                expected_tiles, expected_words
            ]
            for group in width_pairs:
                # Once an entire stage retires, the next stage can start.
                # Within the stage, use the longest resource occupancy.
                occupancy = [count for lane in lanes for count in (
                    lane["requests"] + lane["response_beats"], lane["write_beats"] // group
                )]
                cycle_counts[512*group] += batch_count * max(occupancy)
    assert workload == {"prefill": 466, "decode": 1320}

    values = data["one_beat_per_archived_value_response_cycles"]
    fixture = json.loads(KEY_REPLAY.read_text())
    wide_transfer = verify_attention_transfer(candidate, fixture)
    wide_field = "weight_plus_wide_key_and_value_requests_and_responses_cycles"
    scenarios = {}
    for width, weight_cycles in sorted(cycle_counts.items()):
        widened_values_only = weight_cycles + values
        scenarios[str(width)] = {
            "weight_cycles": weight_cycles,
            "weight_plus_wide_value_cycles": widened_values_only,
            wide_field: weight_cycles + 4 * values,
            "weight_plus_narrow_key_fallback_and_wide_value_requests_and_responses_cycles":
                weight_cycles + 11 * values,
        }
    for width in (512, 2048):
        original = data["scenarios"][f"{width}_bit_write_lane"]
        assert scenarios[str(width)]["weight_cycles"] == original["weight_cycles"]
        assert scenarios[str(width)]["weight_plus_wide_value_cycles"] == original[
            "serialized_with_one_beat_values_cycles"
        ]
    assert scenarios["1024"] == scenarios["2048"]
    target = data["paper_cycle_budget"]
    assert scenarios["512"][wide_field] > target > scenarios["1024"][wide_field]

    clock_mhz = json.loads(Path("records/paper_result_targets.json").read_text())["system_latency"]["clock_megahertz"]
    for row in scenarios.values():
        for name, cycles in tuple(row.items()):
            row[name.removesuffix("_cycles") + "_ms"] = round(cycles/(1000*clock_mhz), 6)
        row["remaining_paper_cycles_after_wide_service"] = target - row[wide_field]
    return {
        "state": "all_layer_indexed_service_and_write_width_scenarios_verified",
        "linked_candidate_sha256": data["linked_candidate_sha256"],
        "linked_write_payload_bits_per_lane": 512,
        "trained_layers": len(layers),
        "batches": workload,
        "paper_cycle_budget": target,
        "archived_visible_pairs": values,
        "observed_attention_transfers": wide_transfer,
        "scenarios_by_write_lane_bits": scenarios,
        "evidence_sha256": {str(p): digest(p) for p in (measurement, KEY_REPLAY, Path(__file__))},
        "scope": "Modeled archived schedule with complete indexed weights per batch and fixed lane steering. "
                 "Each stage is budgeted at the maximum of its read and write occupancy. "
                 "The primary scenario serializes one request and one 512-bit response per key and per value, "
                 "as supported by the measured eligible rows. The fallback scenario models one key request "
                 "and eight 64-bit key responses per pair. Neither assumes reuse between pairs. Compute, other traffic, "
                 "stalls and physical timing remain outside both scenarios.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measurement", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    record = verify(args.measurement, args.candidate)
    with args.output.open("x") as fd:
        json.dump(record, fd, indent=2, sort_keys=True)
        fd.write("\n")
    print(json.dumps(record["scenarios_by_write_lane_bits"], indent=2), flush=True)


if __name__ == "__main__":
    main()
