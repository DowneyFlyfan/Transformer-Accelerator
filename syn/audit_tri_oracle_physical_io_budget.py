"""Bind Tri-Oracle's current signal boundary to pad geometry and workload traffic."""

import argparse
from collections import Counter
from decimal import Decimal
from fractions import Fraction
import json
import math
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import ENDMODULE, MODULE, TOP
from audit_tri_oracle_pad_ring_clearance import PAD_DEPTH_UM, dimensions, get_units, screen
from audit_tri_oracle_placed_chip_boundary import GROUPS, PAD_ARCHIVE, pad_views
from check_tri_oracle_paper300_gate import PAPER_SHA256
from link_tri_oracle_writeback_control import sha
from verify_tri_oracle_pad_cold_reload import components


ROOT = Path(__file__).resolve().parents[1]
PLACED = ROOT / ".cache/residual_bank_command_binding/physical/buffered_grant"
PROBE_REDUCED = (
    ROOT / ".cache/residual_command_request/descriptor_fields/physical/command_repeaters/internal_probes"
)
TRANSPORT = ROOT / ".cache/model_reference/lossless_weight_burst_probe"
PORT = re.compile(r"(?m)^[ \t]*(input|output)\s+(?:\[(\d+):(\d+)\]\s+)?(\w+);")
INTERFACE = {
    **{name: ports for name, ports in GROUPS.items() if name != "feedforward_result"},
    "projection_read": (
        "proj_req_valid proj_req_ready proj_req_address proj_req_length proj_rsp_valid "
        "proj_rsp_ready proj_rsp_last proj_rsp_error proj_rsp_data"
    ),
    "projection_residual_and_scale": (
        "proj_operand_ready proj_operand_token proj_operand_strip proj_operand_valid "
        "proj_residual_q32 proj_projection_shift"
    ),
    "projection_normalization_parameters": "proj_gamma_valid proj_gamma_ready proj_gamma_strip proj_gamma_data",
    "writeback_result": (
        "wb_frame_active wb_packet_error wb_out_valid wb_out_ready wb_out_tag wb_out_token "
        "wb_out_start wb_out_count wb_out_last wb_out_data"
    ),
    "residual_override": "residual_lease",
}


def read(path):
    return json.loads(path.read_bytes())


def boundary(candidate):
    with candidate.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        top, = (row for row in MODULE.finditer(data) if row[1].decode() == TOP)
        end = ENDMODULE.search(data, top.end()).start()
        header, body = data[top.start():end].decode().split(");", 1)
    ports = {}
    for direction, high, low, name in PORT.findall(body):
        assert name not in ports
        ports[name] = direction, abs(int(high) - int(low)) + 1 if high else 1
    names = re.findall(r"\w+", header.split("(", 1)[1])
    assert len(names) == len(set(names)) and set(names) == ports.keys()
    remaining = ports.copy()
    inventory = {}
    for role, members in INTERFACE.items():
        counts = Counter()
        for name in members.split():
            direction, width = remaining.pop(name)
            counts[direction] += width
        inventory[role] = {"input_bits": counts["input"], "output_bits": counts["output"]}
    assert not remaining, remaining
    return inventory


def fixed_memory(path, expected):
    fixed = {}
    count = 0
    for name, pose in components(path):
        count += 1
        if pose[1] == "FIXED":
            name = name.replace(b"\\", b"")
            assert name not in fixed and pose[0].startswith(("TS5N28", "TS6N28"))
            fixed[name] = pose
    assert count == expected and len(fixed) == 631
    return fixed


def macro_boxes(fixed, sizes):
    bodies, halos = {}, {}
    for name, (master, _, x, y, orientation, halo) in fixed.items():
        width, height = sizes[master]
        if orientation in {"W", "E", "FW", "FE"}:
            width, height = height, width
        west, south, east, north = halo
        bodies[name] = (x, y, x + width, y + height)
        halos[name] = (x - west, y - south, x + width + east, y + height + north)
    return bodies, halos


def slots(edges):
    return sum(item["sliding_slots_clear_of_fixed"] for item in edges.values())


def pressure(payload_bytes, cycles, clear_sites):
    bits = payload_bytes * 8
    return {
        "payload_bytes": payload_bytes,
        "one_bit_per_cycle_input_pads": math.ceil(Fraction(bits, cycles)),
        "two_bits_per_cycle_input_pads": math.ceil(Fraction(bits, 2 * cycles)),
        "payload_utilization_if_every_clear_pad_carries_two_bits": float(Fraction(bits, 2 * cycles * clear_sites)),
        "slots_left_before_other_signals_with_two_bits_per_cycle": (
            clear_sites - math.ceil(Fraction(bits, 2 * cycles))
        ),
    }


def indexed_weight_beats(transport, encoding):
    """Count payload and one full index response per gate/up block."""
    lanes = transport["fixed_lane_traffic"]
    index_beats = sum(lane["gate_blocks"] for lane in lanes)
    payload_beats = sum(lane["encoded_gate_payload_beats"] + lane["unencoded_down_beats"] for lane in lanes)
    total = payload_beats + index_beats
    assert total == sum(lane["encoded_weight_response_beats"] for lane in lanes)
    assert total == transport["encoded_weight_response_beats"]
    normalized = encoding["normalized_traffic"]
    assert index_beats == normalized["gate_up_index_beats"]
    assert total == normalized["total_weight_beats_if_only_gate_up_encoded"]
    return total


def ingress_trial(receive_pads, clear_sites, cycles, ports, payloads):
    control_roles = ("command_and_response", "clock_and_reset")
    unswitched_control = sum(sum(ports[role].values()) for role in control_roles)
    available_after_data = clear_sites - receive_pads
    capacity_bits = 2 * receive_pads * cycles
    return {
        "receive_pads": receive_pads,
        "ideal_internal_512_bit_beats_per_four_clocks": 2 * receive_pads * 4 // 512,
        "sites_after_dedicated_receive_pads": available_after_data,
        "existing_command_response_clock_and_reset_bits": unswitched_control,
        "site_deficit_with_dedicated_control_pads": max(0, unswitched_control - available_after_data),
        "fraction_of_ideal_receive_capacity": {
            name: float(Fraction(scenario["payload_bytes"] * 8, capacity_bits))
            for name, scenario in payloads.items()
        },
    }


def main():
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pad-archive", type=Path, default=PAD_ARCHIVE)
    args = parser.parse_args()
    evidence = {}

    def pin(path, expected=None, *, label=None):
        name = label or (str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path))
        if name not in evidence:
            evidence[name] = sha(path)
        assert expected is None or evidence[name] == expected, name
        return path

    def record(name):
        return read(pin(ROOT / "records" / name))

    native = record("tri_oracle_buffered_grant_whole_chip_cold_reload.json")
    probes = record("tri_oracle_internal_writeback_probes.json")
    repeater = record("tri_oracle_descriptor_repeaters_seed.json")
    targets = record("paper_result_targets.json")
    prior_pad = record("tri_oracle_restored_placed_chip_boundary.json")
    ranked = record("tri_oracle_ranked_sign_workload_bounds.json")
    traffic = record("wac_packed_workload_traffic_result.json")
    pin(ROOT / targets["source"], PAPER_SHA256)
    assert probes["parent_candidate_sha256"] == repeater["candidate_sha256"]
    candidate_ports = boundary(pin(PROBE_REDUCED / "candidate.v", probes["candidate_sha256"]))
    assert sum(sum(role.values()) for role in candidate_ports.values()) == probes["new_signal_bits"] == 7945
    geometry = PLACED / "cold/cold.def"
    pin(geometry, native["evidence_sha256"][str(geometry.relative_to(ROOT))])
    comparison_seed = pin(PROBE_REDUCED.parent / "seed.def", repeater["seed_sha256"])
    fixed = fixed_memory(geometry, native["exact_reachable_connectivity"]["physical_leaf_instances"])
    assert fixed == fixed_memory(comparison_seed, repeater["untouched_existing_components"] + repeater["verified_repeaters"])
    with geometry.open() as stream:
        units = get_units(stream)
        for line in stream:
            if match := re.fullmatch(r"DIEAREA \( (\d+) (\d+) \) \( (\d+) (\d+) \) ;\n", line):
                outline = tuple(map(int, match.groups()))
                break
            if line.startswith("COMPONENTS "):
                raise ValueError("Design outline is missing")
        else:
            raise ValueError("Design outline is missing")
    width_mm, height_mm = targets["silicon"]["die_dimensions_mm"]
    assert outline == (0, 0, int(width_mm*1000*units), int(height_mm*1000*units))
    macro_names = {master for master, *_ in fixed.values()}
    database = PLACED / "native/placed.db"
    cold_path = PLACED / "cold/cold_receipt.json"
    cold = read(pin(cold_path, native["evidence_sha256"][str(cold_path.relative_to(ROOT))]))
    library_dir = database / "libs/lef"
    libraries = sorted(library_dir.glob("*.lef"))
    for library in libraries:
        pin(library, cold["database_fingerprint"]["files"][str(library.relative_to(database))]["sha256"])
    sizes = dimensions(libraries, units)
    assert macro_names <= sizes.keys()
    bodies, halos = macro_boxes(fixed, sizes)
    _, _, pad_width, corner, abstract = pad_views(pin(args.pad_archive, label=str(PAD_ARCHIVE)))
    assert abstract == prior_pad["pad_abstract_sha256"]
    body_sites = screen(units, outline, bodies, pad_width, corner, PAD_DEPTH_UM)
    halo_sites = screen(units, outline, halos, pad_width, corner, PAD_DEPTH_UM)
    assert all(halo_sites[edge]["sliding_slots_clear_of_fixed"] <= body_sites[edge]["sliding_slots_clear_of_fixed"]
               for edge in body_sites)
    usable = slots(halo_sites)
    assert usable > 0

    latency = targets["system_latency"]
    cycles = latency["clock_megahertz"] * 1000 * latency["milliseconds"]
    assert (latency["prefill_tokens"], latency["decode_tokens"]) == (ranked["prompt_tokens"], ranked["decode_steps"])
    assert cycles == ranked["paper_latency_cycle_budget"]
    weight_budget = pin(TRANSPORT / "coalesced_write_budget.json")
    modeled = read(weight_budget)
    encoded_receipt = TRANSPORT / "transport_receipt.json"
    encoded = read(pin(encoded_receipt, modeled["input_sha256"][str(encoded_receipt.relative_to(ROOT))]))
    assert cycles == modeled["target_cycles"] and len(encoded["fixed_lane_traffic"]) == 2
    assert encoded["encoded_weight_response_beats"] == sum(
        lane["encoded_weight_response_beats"] for lane in encoded["fixed_lane_traffic"]
    )
    weight = traffic["combined_sixteen_row_prefill_and_single_row_decode"]
    assert weight["without_predictor_weight_bytes"] == ranked["modeled_dense_weight_read_bytes"]
    assert weight["with_predictor_weight_bytes"] == 64 * encoded["original_weight_beats"]
    sign_bytes = 64 * ranked["modeled_sign_line_reads"]
    assert ranked["modeled_weight_plus_sign_read_bytes"] == weight["with_predictor_weight_bytes"] + sign_bytes
    encoding_receipt = TRANSPORT / "receipt.json"
    encoding = read(pin(encoding_receipt, encoded["input_sha256"][str(encoding_receipt.relative_to(ROOT))]))
    encoded_bytes = 64 * indexed_weight_beats(encoded, encoding) + sign_bytes
    minimum = {
        "archived_weight_and_sign": pressure(ranked["modeled_weight_plus_sign_read_bytes"], cycles, usable),
        "conditional_exact_weight_encoding_plus_full_index_and_sign": pressure(encoded_bytes, cycles, usable),
    }
    assert minimum["conditional_exact_weight_encoding_plus_full_index_and_sign"]["payload_bytes"] < minimum[
        "archived_weight_and_sign"
    ]["payload_bytes"]
    for source in (
        Path(__file__).name,
        "audit_tri_oracle_mapped_redundancy.py",
        "audit_tri_oracle_pad_ring_clearance.py",
        "audit_tri_oracle_placed_chip_boundary.py",
        "verify_tri_oracle_pad_cold_reload.py",
    ):
        pin(ROOT / "syn" / source)
    print(json.dumps({
        "state": "physical_pad_and_workload_budget_bound_to_candidate",
        "candidate_sha256": probes["candidate_sha256"],
        "cold_floorplan_candidate_sha256": native["candidate_sha256"],
        "physical_signal_bits": probes["new_signal_bits"],
        "signal_bits_by_role": candidate_ports,
        "macro_clear_slots_with_fixed_halos": usable,
        "macro_body_clear_slots": slots(body_sites),
        "perimeter_slots_before_blockages": sum(edge["slots"] for edge in body_sites.values()),
        "macro_halo_clear_slots_by_edge": {
            edge: value["sliding_slots_clear_of_fixed"] for edge, value in halo_sites.items()
        },
        "target_cycles": cycles,
        "receive_only_bounds": minimum,
        "trial_448_receive_pads_at_two_bits_per_cycle": ingress_trial(
            448, usable, cycles, candidate_ports, minimum
        ),
        "scope": (
            "Pad geometry assumes one row and the smallest installed signal pad. It preserves fixed memory macro "
            "halos. The payload estimates grant every assigned data lane one or two useful bits per clock and "
            "exclude compute stalls, other memory traffic, pad spacing, control, power, package, and timing. "
            "The encoded scenario assumes the archived encoding across the full workload and one index response "
            "per encoded block. The 448-pad trial assumes both edges of the paper's core clock carry data "
            "and counts the site's deficit before adding any other interface functions. "
            "The reduced-pin netlist still needs a physical interface."
        ),
        "evidence_sha256": evidence,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
