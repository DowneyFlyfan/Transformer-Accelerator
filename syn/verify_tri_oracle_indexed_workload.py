"""Independently reconcile the indexed workload and screen intermediate write widths."""

import argparse
from collections import Counter
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_packed_weight_path import STAGE, module_body
from audit_tri_oracle_placed_chip_boundary import digest
from link_tri_oracle_indexed_whole_chip import signature


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
    key_evidence = Path("records/tri_oracle_repaired_native_mixed_attention.json")
    fixture = json.loads(key_evidence.read_text())
    per_row = re.findall(r"(?m)^MIXED_ATTENTION_ROW .* values=(\d+) key_beats=(\d+)$",
                         "\n".join(fixture["matched_transcript"]))
    assert len(per_row) == fixture["matched_attention_rows"] == 10
    assert all(int(count) > 0 and int(beats) == 8*int(count) for count, beats in per_row)
    scenarios = {}
    for width, weight_cycles in sorted(cycle_counts.items()):
        widened_values_only = weight_cycles + values
        # The archived narrow-key fixture used eight response beats per key.
        # Include the same one-beat value scenario before adding key beats.
        narrow_keys = widened_values_only + 8 * values
        scenarios[str(width)] = {
            "weight_cycles": weight_cycles,
            "weight_plus_wide_value_cycles": widened_values_only,
            "weight_plus_wide_value_and_narrow_key_cycles": narrow_keys,
        }
    for width in (512, 2048):
        original = data["scenarios"][f"{width}_bit_write_lane"]
        assert scenarios[str(width)]["weight_cycles"] == original["weight_cycles"]
        assert scenarios[str(width)]["weight_plus_wide_value_cycles"] == original[
            "serialized_with_one_beat_values_cycles"
        ]
    assert scenarios["1024"] == scenarios["2048"]
    target = data["paper_cycle_budget"]
    assert scenarios["512"]["weight_plus_wide_value_cycles"] > target
    assert scenarios["1024"]["weight_plus_wide_value_cycles"] < target
    assert all(row["weight_plus_wide_value_and_narrow_key_cycles"] > target for row in scenarios.values())

    clock_mhz = json.loads(Path("records/paper_result_targets.json").read_text())["system_latency"]["clock_megahertz"]
    for row in scenarios.values():
        for name, cycles in tuple(row.items()):
            row[name.removesuffix("_cycles") + "_ms"] = round(cycles/(1000*clock_mhz), 6)
        row["average_key_beat_budget_after_weights_and_values"] = round(
            (target - row["weight_plus_wide_value_cycles"]) / values, 6
        )
    return {
        "state": "all_layer_indexed_service_and_write_width_scenarios_verified",
        "linked_candidate_sha256": data["linked_candidate_sha256"],
        "linked_write_payload_bits_per_lane": 512,
        "trained_layers": len(layers),
        "batches": workload,
        "paper_cycle_budget": target,
        "scenarios_by_write_lane_bits": scenarios,
        "evidence_sha256": {str(p): digest(p) for p in (measurement, key_evidence, Path(__file__))},
        "scope": "Archived schedule with complete indexed weights per batch and fixed lane steering. "
                 "Each stage is budgeted at the maximum of its read and write occupancy. "
                 "The attention scenarios serialize one value beat and optionally eight key beats per archived pair. "
                 "Request and response service share each weight lane. Compute, other traffic and physical timing remain pending.",
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
