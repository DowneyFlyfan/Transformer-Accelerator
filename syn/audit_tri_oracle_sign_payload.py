"""Quantify the memory and transfer cost of the packed sign cache."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / ".cache/model_reference"


def sha(path):
    with Path(path).open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def audit():
    legacy_path = MODEL / "normalized_sign_cache_workload/receipt.json"
    packed_path = MODEL / "packed_sign_line_workload/receipt.json"
    traffic_path = ROOT / "records/wac_packed_workload_traffic_result.json"
    weight_path = ROOT / "records/wac_weight_burst_schedule_result.json"
    bound_path = ROOT / "records/wac_primary_request_cycle_bound_result.json"
    packed_record_path = ROOT / "records/wac_packed_sign_line_result.json"
    cache_record_path = ROOT / "records/wac_dual_port_sign_line_cache_result.json"
    legacy, packed, traffic, bound, packed_record, cache = map(read, (
        legacy_path, packed_path, traffic_path, bound_path, packed_record_path, cache_record_path,
    ))
    assert bound["evidence_sha256"][str(legacy_path.relative_to(ROOT))] == sha(legacy_path)
    assert bound["evidence_sha256"][str(weight_path.relative_to(ROOT))] == sha(weight_path)
    assert read(weight_path)["evidence_sha256"][str(traffic_path.relative_to(ROOT))] == sha(traffic_path)
    assert packed_record["evidence_sha256"][str(packed_path.relative_to(ROOT))] == sha(packed_path)
    assert cache["trained_predictor_128"]["verified_masks"] == 2816
    assert set(legacy["layouts_byte_addresses"]) == set(packed["layouts_byte_addresses"])
    for phase in ("prefill", "decode"):
        assert legacy["phases"][phase]["logical"] == packed["phases"][phase]["sign_words"]
    weight_bytes = traffic["combined_sixteen_row_prefill_and_single_row_decode"]["with_predictor_weight_bytes"]
    assert weight_bytes > 0
    summary = {}
    for entries in (128, 256):
        size = str(entries)
        summary[size] = {}
        for layout in legacy["layouts_byte_addresses"]:
            narrow = legacy["summary"]["64"][layout]["external"]
            wide = packed["summary"][size][layout]["external_line_reads"]
            old_bytes, new_bytes = 8 * narrow, 64 * wide
            assert narrow > wide > 0 and new_bytes > old_bytes
            summary[size][layout] = {
                "legacy_requests": narrow, "packed_requests": wide,
                "legacy_sign_payload_bytes": old_bytes, "packed_sign_payload_bytes": new_bytes,
                "change_in_total_weight_and_sign_payload_percent": 100 * (new_bytes - old_bytes) / (weight_bytes + old_bytes),
                "break_even_request_energy_in_byte_energy_units": (new_bytes - old_bytes) / (narrow - wide),
                "packed_minus_legacy_sign_bytes_at_assumed_transfer_granularity": {
                    str(granularity): new_bytes - narrow * granularity for granularity in (8, 16, 32, 64)
                },
            }
    paths = (legacy_path, packed_path, traffic_path, weight_path, bound_path, packed_record_path, cache_record_path,
             Path(__file__).resolve())
    return {
        "state": "packed_sign_traffic_and_memory_cost_quantified",
        "weight_payload_bytes_held_fixed": weight_bytes,
        "summary": summary,
        "added_compiled_sram_bytes": {size: data["added_sram_bytes"] for size, data in cache["cache_variants"].items()},
        "scope": "Modeled sign transactions on the archived workload. The break-even model assumes the same fixed "
                 "energy per request and marginal energy per payload byte for both readers. Transfer granularity cases "
                 "assume one transfer per request. The physical external-memory controller and chip power are unmeasured.",
        "evidence_sha256": {str(path.relative_to(ROOT)): sha(path) for path in paths},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit()
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], result["summary"]["128"], flush=True)
