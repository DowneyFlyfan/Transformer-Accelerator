"""Check the placed receive credit budget under archived fixed-lane steering."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

import torch

from verify_tri_oracle_booth_receive_credit_limit import BUDGET, TARGET, capacity, minimum_cycles
from verify_tri_oracle_booth_response_packing import ROOT, digest
from verify_tri_oracle_gearbox_workload import BEAT_BYTES, BLOCK_BYTES, chunks


RECORDS = Path("records")
DATA = Path(".cache/model_reference")
WORKLOAD = Path(".cache/memory_response_gearbox/workload_serial.json")
TRANSPORT = DATA / "lossless_weight_burst_probe/transport_receipt.json"
SCHEDULE = DATA / "normalized_weight_burst_schedule_v2/receipt.json"
TRACE = DATA / "normalized_workload_trace/receipt.json"
EXPORT = DATA / "packed_gate_up_export/v1"
LIMIT = RECORDS / "tri_oracle_corrected_booth_receive_credit_limit.json"
IO = RECORDS / "tri_oracle_physical_io_budget.json"
COMPACT = RECORDS / "tri_oracle_compact_index_ingress.json"
PLACED_TRAINED = RECORDS / "tri_oracle_corrected_booth_trained_credit_window.json"


def gate_payloads(source, matrices, trace, expected):
    counts = [Counter(), Counter()]
    # Block enumeration from the archived packed layout is
    # [output strip (704), input partition (4), bank within partition (2)].
    block_id = torch.arange(704 * 4 * 2, device="cuda")
    cluster = (block_id // 8 % 10) // 2
    upper_partition = block_id // 2 % 4 >= 2
    lane_one = (cluster > 2) | ((cluster == 2) & upper_partition)
    for matrix in matrices:
        assert source.tell() == matrix["offset_bytes"]
        raw = bytearray(matrix["bytes"])
        assert source.readinto(raw) == len(raw) and sha256(raw).hexdigest() == matrix["sha256"]
        weights = torch.frombuffer(raw, dtype=torch.int8).to("cuda").reshape(-1, BLOCK_BYTES)
        assert weights.shape == (len(block_id), BLOCK_BYTES)  # [block, byte]
        beats = torch.full_like(block_id, BLOCK_BYTES // BEAT_BYTES)
        for bits in (4, 5, 6, 7):
            literal_limit = (1 << (bits - 1)) - 1
            escapes = ((weights < -literal_limit) | (weights > literal_limit)).sum(dim=1)
            candidate = (BLOCK_BYTES * bits // 8 + escapes + BEAT_BYTES - 1) // BEAT_BYTES
            beats = torch.minimum(beats, candidate)
        tiled = trace[matrix["layer"]]
        frames = (tiled["prefill_rows"] + 15) // 16 + tiled["decode_rows"]
        profile = expected[f'{matrix["layer"]}/{matrix["branch"]}']
        assert int(beats.sum()) == profile["payload_beats"] and len(beats) == profile["blocks"]
        for lane, keep in enumerate((~lane_one, lane_one)):
            selected = beats[keep]
            counts[lane].update(gate_blocks=frames * len(selected),
                                gate_payload_beats=frames * int(selected.sum()),
                                gate_fragments=frames * int(chunks(selected).sum()))
    assert not source.read(1)
    return counts


def verify():
    evidence = {}

    def pin(path, proof=None):
        checksum = digest(path)
        if proof is not None:
            assert checksum == proof["evidence_sha256"][str(path)], path
        evidence[str(path)] = checksum
        return path

    def read(path, proof=None):
        return json.loads(pin(path, proof).read_text())

    budget, target, limit, compact, trained, io = map(read, (BUDGET, TARGET, LIMIT, COMPACT, PLACED_TRAINED, IO))
    assert limit["cold_netlist_sha256"] == trained["cold_netlist_sha256"]
    assert compact["compact_indexes_by_lane"] == [780, 756] and trained["trained_tiles"] == 78
    log, = (Path(name) for name in trained["evidence_sha256"] if name.endswith("/credit8/xrun.log"))
    observed, = re.findall(r"(?m)^COMPACT_INDEX_MATRIX_PASS compact0=(\d+) compact1=(\d+) ",
                          pin(log, trained).read_text())
    assert list(map(int, observed)) == compact["compact_indexes_by_lane"]
    assert limit["evidence_sha256"][str(BUDGET)] == evidence[str(BUDGET)]
    fields = budget["archived_workload_lower_bounds"]
    assert fields["encoded_weight_fragments"] + fields["sign_fragments"] == limit["archived_weight_and_sign_fragments"]
    transport = read(TRANSPORT, io)
    workload = read(WORKLOAD, budget)
    encoding_path = TRANSPORT.with_name("receipt.json")
    encoding = read(encoding_path)
    assert evidence[str(encoding_path)] == transport["input_sha256"][str(encoding_path)]
    trace = read(TRACE, workload)["layers"]["compact_streaming_pruned"]
    schedule = read(SCHEDULE, workload)
    manifest = read(EXPORT / "manifest.json", workload)
    weights = pin(EXPORT / "weights.bin", workload)
    assert len(trace) == 22 and len(manifest["matrices"]) == 44
    with weights.open("rb") as stream:
        gate = gate_payloads(stream, manifest["matrices"], trace, encoding["layer_branch_results"])
    assert sum(row["gate_fragments"] for row in gate) == workload["gate_up"]["payload_chunks"]
    indexes = workload["modeled_single_response_index_bursts"]
    assert sum(row["gate_blocks"] for row in gate) == indexes == compact["conditional_archived_budget"]["records_requiring_compact_link"]
    down_total = workload["down_projection"]["payload_chunks"]
    lower_down = []
    for lane, row in enumerate(gate):
        prior = transport["fixed_lane_traffic"][lane]
        assert row["gate_payload_beats"] == prior["encoded_gate_payload_beats"]
        assert row["gate_blocks"] == prior["gate_blocks"]
        original = sum(phase["lane_payload_beats"][lane] for phase in schedule["phases"].values())
        down_beats = original - row["gate_blocks"] * (BLOCK_BYTES // BEAT_BYTES)
        assert down_beats == prior["unencoded_down_beats"] and down_beats > 0
        row["down_payload_beats"] = down_beats
        lower_down.append(chunks(down_beats))
    assert sum(lower_down) <= down_total
    sign = fields["sign_fragments"]
    # Compact index records each occupy one fragment. Bound unknown down-burst
    # padding by giving all unassigned padding and sign data to either lane.
    lower = [row["gate_fragments"] + row["gate_blocks"] + down for row, down in zip(gate, lower_down, strict=True)]
    upper = [row["gate_fragments"] + row["gate_blocks"] + down_total - lower_down[1 - lane] + sign
             for lane, row in enumerate(gate)]
    all_fragments = fields["encoded_weight_fragments"] - indexes + sign
    assert sum(lower) <= all_fragments <= sum(upper)
    assert sum(row["gate_fragments"] for row in gate) + indexes + down_total + sign == all_fragments
    window = limit["paper_window_cycles"]
    cycles_per_ms = target["system_latency"]["clock_megahertz"] * 1000
    assert window == target["system_latency"]["milliseconds"] * cycles_per_ms
    cases = {}
    for name, case in limit["cases"].items():
        credits = int(name.split("_", 1)[0])
        periods = case["lane_credit_reuse_periods"]
        capacities = [capacity(window, credits, period) for period in periods]
        assert capacities == case["lane_fragment_capacity"]
        balanced = minimum_cycles(all_fragments, credits, periods)
        fixed = max(balanced, *(minimum_cycles(count, credits, [period])
                                for count, period in zip(lower, periods, strict=True)))
        cases[name] = {
            "optimistic_flexible_steering_ms": balanced / cycles_per_ms,
            "optimistic_fixed_steering_ms": fixed / cycles_per_ms,
            "minimum_margins_by_lane": [bound - count for bound, count in zip(capacities, upper, strict=True)],
            "maximum_margins_by_lane": [bound - count for bound, count in zip(capacities, lower, strict=True)],
        }
    pin(Path(__file__).resolve().relative_to(ROOT))
    return {
        "state": "archived_fixed_lane_credit_budget_with_compact_indexes_verified_on_host_gpu",
        "cold_netlist_sha256": limit["cold_netlist_sha256"],
        "gate_up_by_lane": gate,
        "compact_index_fragments": indexes,
        "weight_and_sign_fragments": all_fragments,
        "weight_and_sign_fragment_bounds_by_lane": [list(bounds) for bounds in zip(lower, upper, strict=True)],
        "cases": cases,
        "scope": "Archived fixed steering and compact indexes with the placed receiver's modeled "
                 "credit delays. Gate/up burst padding is exact. Lane-level down padding and sign "
                 "placement are bounded. Latency floors exclude requests, computation and other traffic.",
        "gpu": torch.cuda.get_device_name(),
        "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    assert torch.cuda.is_available() and torch.cuda.mem_get_info()[0] >= 1024**3
    torch.cuda.set_per_process_memory_fraction(0.08)
    print(json.dumps(verify(), indent=2, sort_keys=True))
