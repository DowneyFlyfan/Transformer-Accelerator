"""Bind the placed and serialized boundaries to the paper's workload cycle budget."""
from collections import Counter
from decimal import Decimal
from fractions import Fraction
import json
from math import ceil
from pathlib import Path
import re

from audit_tri_oracle_placed_chip_boundary import check_ports, def_boundary, pad_limit, verilog_ports
from check_tri_oracle_paper300_gate import PAPER_SHA256
from measure_tri_oracle_serial_memory_requests import digest, read


ROOT = Path(__file__).resolve().parents[1]
RECORDS = Path("records")
WORK = Path(".cache/physical/whole_chip_xcelium_speed/architecture_budget")


def overlap_floor(first, second, window):
    """Required cycles that the two activities must share within the window."""
    assert 0 <= first <= window and 0 <= second <= window
    return max(0, first + second - window)


def verify():
    evidence = {}

    def pin(path, expected=None):
        checksum = digest(path)
        assert expected is None or checksum == expected, path
        assert evidence.setdefault(str(path), checksum) == checksum, path
        return path

    def record(name):
        return read(pin(RECORDS / f"{name}.json"))

    targets = record("paper_result_targets")
    pin(Path(targets["source"]), PAPER_SHA256)
    target = targets["system_latency"]
    cycles_per_ms = target["clock_megahertz"] * 1000
    window = target["milliseconds"] * cycles_per_ms
    assert (target["prefill_tokens"], target["decode_tokens"]) == (600, 60)

    cold = record("tri_oracle_cold_memory_boundary")
    placed_inputs = cold["evidence_sha256"]
    (v, v_digest), = ((Path(name), sha) for name, sha in placed_inputs.items() if name.endswith("/cold/cold.v"))
    (layout, d_digest), = ((Path(name), sha) for name, sha in placed_inputs.items() if name.endswith("/cold/layout.def"))
    assert v_digest == cold["cold_netlist_sha256"]
    pin(v, v_digest)
    pin(layout, d_digest)
    pad_time = record("tri_oracle_loaded_forwarded_pads")
    (lef, lef_hash), = ((Path(name), sha) for name, sha in pad_time["evidence_sha256"].items() if name.endswith("/pads.lef"))
    pad_text = pin(lef, lef_hash).read_text()
    pad_masters = set(re.findall(r"(?m)^MACRO (\w+)$", pad_text))
    assert pad_masters
    ports = verilog_ports(v)
    die, terminals, edges, pads = def_boundary(layout, pad_masters)
    check_ports(ports, terminals)
    assert list(die) == [width * 1000 for width in targets["silicon"]["die_dimensions_mm"]]
    assert len(terminals) == cold["top_level_signal_bits"] and sum(edges.values()) == len(terminals)
    assert ports["clk"] == ("INPUT", None) and ports["command_opcode"] == ("INPUT", 3)
    assert all(ports[name] == ("INPUT", width) for name, width in cold["read_boundary"]["grouped_external_read_widths_bits"].items())
    assert not pads, pads
    pad_bound = record("tri_oracle_restored_placed_chip_boundary")
    assert pad_bound["pad_abstract_sha256"] == lef_hash
    upper_pads = pad_limit(die, Decimal(pad_bound["minimum_signal_pad_width_um"]), Decimal(pad_bound["minimum_corner_width_um"]))
    assert len(terminals) > upper_pads == pad_bound["single_row_pad_capacity_with_corners"]

    tx = record("tri_oracle_credited_request_link")
    rx = record("tri_oracle_shared_edge_metadata")
    (wrapper, wrapper_hash), = ((Path(name), sha) for name, sha in tx["evidence_sha256"].items()
                               if name.endswith("/top_wrapper.v"))
    header = pin(wrapper, wrapper_hash).read_text().split(");", 1)[0]
    pad_ports = re.findall(r"(?m)^  (input|output) wire (?:\[(\d+):0\] )?(\w+),?$", header)
    assert len(pad_ports) == len(header.splitlines()) - 1
    by_name = {name: (direction, int(high) + 1 if high else 1) for direction, high, name in pad_ports}
    assert len(by_name) == len(pad_ports)
    signal_bits = sum(width for _, width in by_name.values())
    assert signal_bits == tx["candidate_signal_pins_if_link_replaces_ready_and_adds_clock"]
    tx_bits = by_name["memory_tx_data"][1]
    rx_bits = by_name["memory_mem_rsp_data"][1]
    assert by_name["memory_tx_data"] == ("output", 8) and by_name["memory_tx_clock"] == ("output", 1)
    assert by_name["memory_tx_credit"] == ("input", 1)
    assert by_name["memory_mem_rsp_data"] == ("input", rx["receive_data_width_bits"]) == ("input", 448)
    assert by_name["memory_mem_rsp_credit"] == ("output", 2)
    assert by_name["memory_mem_rsp_metadata"] == ("input", rx["receive_metadata_width_bits"])

    gearbox = record("tri_oracle_memory_response_gearbox")
    workload_path = Path(".cache/memory_response_gearbox/workload_serial.json")
    workload = read(pin(workload_path, gearbox["evidence_sha256"][str(workload_path)]))
    recomputed = read(pin(WORK / "gearbox_recomputed.json"))
    assert workload.keys() == recomputed.keys()
    assert all(workload[key] == recomputed[key] for key in workload if key != "evidence_sha256")
    assert workload["paper_system_latency_ms"] == target["milliseconds"]
    assert gearbox["digital_width_bits"] == {"input_per_lane": rx_bits, "lanes_tested": 2, "output_per_lane": 512}
    signs = record("tri_oracle_ranked_sign_workload_bounds")
    assert (signs["prompt_tokens"], signs["decode_steps"]) == (target["prefill_tokens"], target["decode_tokens"])
    assert signs["paper_latency_cycle_budget"] == cold["paper_latency_cycles"] == window
    forward = record("tri_oracle_serial_control_pads")["independent_request_link_lower_bound"]
    requests = workload["one_request_cycle_per_burst"]
    assert requests == forward["request_count"] and forward["target_cycles"] == window
    compact, full = (forward[f"{mode}_cycles_per_request"] for mode in ("compact", "full_address"))
    assert (compact, full) == (6, 12)

    # Each separately padded response ends on a 448-bit fragment. Grant two
    # useful fragments per cycle, one on each edge, and perfectly balanced lanes.
    sign_fragments = signs["modeled_sign_line_reads"] * ceil(Fraction(512, rx_bits))
    weight_fragments = workload["burst_aligned_aggregate_fragments"]
    read_cycles = ceil(Fraction(weight_fragments + sign_fragments, 2))
    raw_cycles = ceil(Fraction(8 * signs["modeled_weight_plus_sign_read_bytes"], 2 * rx_bits))
    compact_cycles = compact * requests
    full_cycles = full * requests
    assert read_cycles < window < raw_cycles and compact_cycles < window < full_cycles
    minimum_compact = ceil(Fraction(full_cycles - window, full - compact))
    assert (full_cycles - (full - compact) * minimum_compact <= window
            < full_cycles - (full - compact) * (minimum_compact - 1))
    required_overlap = overlap_floor(read_cycles, compact_cycles, window)

    directions = Counter(terminals.values())
    for helper in (verify, check_ports, def_boundary, verilog_ports, pad_limit):
        pin(Path(helper.__code__.co_filename).resolve().relative_to(ROOT))
    return {
        "state": "exact_placed_and_serialized_boundaries_checked_against_archived_workload",
        "placed": {"cold_netlist_sha256": v_digest, "layout_sha256": d_digest, "die_um": [int(side) for side in die],
                   "signal_bits": len(terminals), "input_bits": directions["INPUT"], "output_bits": directions["OUTPUT"],
                   "installed_pad_instances": sum(pads.values()), "perimeter_pad_upper_bound_before_macros": upper_pads,
                   "clear_geometric_pad_sites_in_existing_layout": cold["clear_pad_sites"]},
        "separate_wrapper": {"digital_signal_bits": signal_bits, "supply_and_ground_reservations": rx["supply_ground_placeholder_pads"],
                             "outgoing_bits_per_cycle": tx_bits, "incoming_bits_per_cycle": 2 * rx_bits},
        "paper_window_cycles": window,
        "archived_workload_lower_bounds": {
            "ideal_unencoded_response_cycles": raw_cycles,
            "ideal_unencoded_response_ms": raw_cycles / cycles_per_ms,
            "encoded_weight_fragments": weight_fragments,
            "sign_fragments": sign_fragments,
            "ideal_encoded_response_cycles": read_cycles,
            "ideal_encoded_response_ms": read_cycles / cycles_per_ms,
            "compact_weight_request_cycles": compact_cycles,
            "full_address_weight_request_cycles": full_cycles,
            "minimum_compact_request_count": minimum_compact,
            "minimum_compact_request_fraction": float(Fraction(minimum_compact, requests)),
            "minimum_simultaneous_request_and_response_cycles_if_all_compact": required_overlap,
            "fraction_of_request_cycles_that_must_overlap_if_all_compact": float(Fraction(required_overlap, compact_cycles)),
        },
        "scope": "The placed candidate still uses external wide ports. The distinct serialized wrapper is a "
                 "structural boundary. The archived encoded workload uses one response fragment per clock edge and "
                 "one request byte per clock with ideal scheduling. Bounds omit lane imbalance, request stalls, "
                 "the outgoing sign requests, attention and other traffic, and computation. The archived trajectory "
                 "is a local approximation of the paper's benchmark.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), indent=2, sort_keys=True))
