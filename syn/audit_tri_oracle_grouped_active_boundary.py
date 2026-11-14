"""Bind the chip boundary check to the grouped-active placement."""
from decimal import Decimal
from fractions import Fraction
import sys
import json
from pathlib import Path

from audit_tri_oracle_placed_chip_boundary import (
    PAD_ARCHIVE, check_ports, def_boundary, digest, pad_limit, pad_views, summarize_ports, verilog_ports,
)

root = Path.cwd()
if len(sys.argv) != 3:
    raise SystemExit("Usage: audit_tri_oracle_grouped_active_boundary.py PARENT_EXPORT_DIR CANDIDATE_EXPORT_DIR")
before, after = [Path(arg).resolve() for arg in sys.argv[1:]]
source = root / "records/tri_oracle_grouped_active_placement.json"
record = json.loads(source.read_text())
assert digest(before / "trial.v") == record["parent_netlist_sha256"]
assert digest(after / "active.v") == record["candidate_netlist_sha256"]
assert digest(after / "active.def") == record["placed_design_exchange_sha256"]
cells, signal_cells, minimum_width, corner, abstract_hash = pad_views(PAD_ARCHIVE)

observed = []
for path, stem in [(before, "trial"), (after, "active")]:
    ports = verilog_ports(path / f"{stem}.v")
    die, terminals, sides, pads = def_boundary(path / f"{stem}.def", cells)
    check_ports(ports, terminals)
    observed.append((die, terminals, sides, pads, ports))
assert observed[0] == observed[1], "Buffer insertion changed the chip interface"
die, terminals, sides, pads, ports = observed[1]
assert die == (Decimal(3600), Decimal(3600))
groups = summarize_ports(ports)
assert len(terminals) == sum(group["total"] for group in groups.values()) == sum(sides.values())
capacity = pad_limit(die, minimum_width, corner)
channels = ("memory_primary_read", "memory_auxiliary_read", "memory_write")
memory = sum(groups[name]["total"] for name in channels)
assert not pads and memory > capacity
targets_path = root / "records/paper_result_targets.json"
traffic_path = root / "records/wac_packed_workload_traffic_result.json"
targets = json.loads(targets_path.read_text())
traffic = json.loads(traffic_path.read_text())
assert traffic["state"] == "normalized_workload_packed_weight_traffic_independently_reconciled"
latency = targets["system_latency"]
assert latency["prefill_tokens"] == traffic["prefill_tokens"] == 600
assert latency["decode_tokens"] == traffic["decode_steps"] == 60
cycles = latency["clock_megahertz"] * 1000 * latency["milliseconds"]
payload = traffic["combined_sixteen_row_prefill_and_single_row_decode"]
bits = 8 * (payload["with_predictor_weight_bytes"] + payload["sign_bytes"])
rate = Fraction(bits, cycles)
assert cycles == 508660000
assert rate > capacity
bounds = {}
for bits_per_pad in (1, 2):
    required = -(-bits // (cycles * bits_per_pad))
    max_other_pads = capacity - required
    bounds[str(bits_per_pad)] = dict(
        minimum_payload_pads=required,
        signal_slots_left_after_payload=max_other_pads,
        transfer_time_floor_ms=round(float(Fraction(bits, capacity * bits_per_pad * latency["clock_megahertz"] * 1000)), 3),
    )
paper = root / targets["source"]
assert digest(paper) == "6d6b998c459ade605e082d723374462e1d14b53d6a6b13063ca0f8d1180b1d9f"
result = dict(
    state="grouped_active_placement_boundary_verified",
    candidate_netlist_sha256=record["candidate_netlist_sha256"],
    parent_netlist_sha256=record["parent_netlist_sha256"],
    die_micrometers=[str(size) for size in die],
    placement_definition_sha256=digest(after / "active.def"),
    terminals=len(terminals), raw_external_memory_channel_signals=memory,
    terminals_by_edge=sides, signals_by_function=groups,
    pad_library_signal_masters=signal_cells, pad_abstract_sha256=abstract_hash,
    audited_pad_instances=sum(pads.values()), single_row_signal_pad_limit=capacity,
    minimum_signal_pad_micrometers=str(minimum_width), minimum_corner_cell_micrometers=str(corner),
    modeled_payload_rate=dict(prefill_tokens=600, decode_tokens=60, cycle_budget=cycles,
                              packed_weight_and_sign_read_bits=bits,
                              minimum_mean_payload_bits_per_cycle=round(float(rate), 3),
                              bounds_by_bits_per_pad_per_cycle=bounds,
                              scope="One archived local model trace and only packed weight and sign reads. "
                                    "The transfer floor assumes every signal pad receives payload at full rate."),
    evidence_sha256={str(path.relative_to(root)): digest(path) for path in
                     (source, before / "trial.def", root / "syn/audit_tri_oracle_placed_chip_boundary.py",
                      Path(__file__).resolve(), targets_path, traffic_path, paper)},
    scope="Native placement export and one-row perimeter bound using the installed 28 nm pad library. "
          "The bound leaves out power and ground pads, spacing and package constraints. "
          "The placement has no cells from the audited pad library.",
)
print(json.dumps(result, sort_keys=True, indent=2))
