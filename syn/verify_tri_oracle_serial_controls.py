"""Verify pad inventory, mapped serializer behavior and request timing bounds."""
import argparse
import json
from math import ceil
from pathlib import Path
import re

from link_tri_oracle_narrow_host import width
from link_tri_oracle_serial_controls import bind
from measure_tri_oracle_serial_memory_requests import digest, read


EXPECTED = {(22, 8, 3), (18, 4, 5), (17, 4, 5)}
OLD_REQUESTS = Path("records/tri_oracle_serial_memory_requests.json")
TARGET = Path("records/paper_result_targets.json")
PHYSICAL_IO = Path("records/tri_oracle_physical_io_budget.json")
AREA = re.compile(r"(?m)^tri_oracle_serial_control_pads\s+NA\s+(\d+)\s+([0-9.]+)")


def verify(run):
    binding_path = run / "binding.json"
    binding = read(binding_path)
    for name, hash_ in binding["evidence_sha256"].items():
        assert digest(Path(name)) == hash_, name
    pads, chip, physical = bind()
    assert (run / "binding/serial_control_pads.v").read_text() == pads
    assert (run / "binding/serial_control_wrapper.v").read_text() == chip
    assert width(physical) == binding["physical_signal_bits"] == 490
    assert binding["site_margin_by_case"]["pad50_independent_fillers"] == -35
    assert binding["site_margin_by_case"]["pad50_optimistic_shared_filler"] == 16

    logs = tuple(run / name / "console.log" for name in ("rtl", "wrapper_rtl", "wrapper_mapped", "forward"))
    paths = [binding_path, *logs, OLD_REQUESTS, TARGET, PHYSICAL_IO, Path(__file__)]
    for log in logs:
        text = log.read_text()
        assert not re.search(r"\*[EF],", text) and text.count("Simulation complete via $finish(1)") == 1, log
        if log.parent.name != "forward":
            matches = re.findall(r"SERIAL_FLIT_BRIDGE_PASS word_bits=(\d+) pad_bits=(\d+) parts=(\d+) "
                                 r"words=(\d+) stall_cycles=(\d+)", text)
            assert {tuple(map(int, row[:3])) for row in matches} == EXPECTED and len(matches) == 3
            assert all(int(row[3]) == 96 and int(row[4]) > 0 for row in matches)
    mapped_console = logs[2].read_text()
    assert "netlist.v" in mapped_console and "tcbn28hpcplusbwp12t40p140.v" in mapped_console
    assert "MEMORY_FORWARD_LINK_PASS reads=36 headers=6 words=21 overlap=21" in logs[3].read_text()
    mutation = run / "mutation/console.log"
    assert "PAD_ORDER_MISMATCH" in mutation.read_text() and "*F,FATSEV" in mutation.read_text()
    paths.append(mutation)

    genus = run / "genus"
    assert "TRI_ORACLE_SERIAL_CONTROLS_GENUS_FINISHED\n" in (genus / "console.log").read_text()
    assert "No unresolved references" in (genus / "mapped_check.rpt").read_text()
    timing = (genus / "timing.rpt").read_text()
    assert "Operating conditions:   ssg0p9v125c" in timing
    slacks = list(map(int, re.findall(r"Slack:=\s*(-?\d+)", timing)))
    assert len(slacks) == 8 and min(slacks) > 0
    cells, area = AREA.search((genus / "area.rpt").read_text()).groups()
    paths.extend(genus / name for name in ("console.log", "timing.rpt", "area.rpt", "mapped_check.rpt",
                                           "netlist.v", "constraints.sdc"))
    paths.extend(run / name for name in ("forward/tri_oracle_memory_forward_link_tb.sv",
        "control_wrapper_round_trip_tb.sv", "wrapper_mapped/peer.sv", "wrapper_mapped/round_trip_tb.sv"))

    new_pad = physical["memory_tx_data"][1]
    narrow = ceil(22 / new_pad)
    work = read(OLD_REQUESTS)["conditional_archived_workload"]
    requests = work["modeled_weight_requests"]
    target = read(TARGET)["system_latency"]
    cycles = target["milliseconds"] * target["clock_megahertz"] * 1000
    compact = work["estimates"]["aligned_address"]["flits_per_request"] * narrow
    full = work["estimates"]["full_address"]["flits_per_request"] * narrow
    receive_bits = binding["double_edge_receive_bits"]
    payload = read(PHYSICAL_IO)["receive_only_bounds"]["conditional_exact_weight_encoding_plus_full_index_and_sign"]
    compact_cycles = compact * requests
    full_cycles = full * requests
    assert compact_cycles < cycles < full_cycles and compact == 6 and full == 12
    return {
        "state": "serialized_control_pads_mapped_and_verified",
        "physical_chip_boundary_signal_bits": binding["physical_signal_bits"],
        "recovered_pads": binding["removed_signal_bits"],
        "receive_data_bits_per_edge": receive_bits,
        "illustrative_supply_and_ground_reserve": binding["illustrative_supply_and_ground_reserve"],
        "site_margin_by_case": binding["site_margin_by_case"],
        "mapped_slow_corner_setup_slack_ps": min(slacks),
        "mapped_cells": int(cells),
        "mapped_area_square_micrometers": float(area),
        "verified_memory_forward_packets": {"read_requests": 36, "write_headers": 6, "write_words": 21},
        "independent_request_link_lower_bound": {
            "target_cycles": cycles, "request_count": requests, "compact_cycles_per_request": compact,
            "full_address_cycles_per_request": full, "compact_only_link_cycles": compact_cycles,
            "full_address_only_link_cycles": full_cycles,
            "minimum_compact_fraction_if_every_target_cycle_can_serve_requests": (
                max(0, ceil((full_cycles - cycles) / (full - compact))) / requests),
        },
        "ideal_encoded_receive_payload_only_ms_at_existing_width": (
            payload["payload_bytes"] * 8 / (receive_bits * 2 * target["clock_megahertz"] * 1000)),
        "scope": "The three control serializers were tested as register-transfer logic and mapped gates. "
                 "The credited chip is bound structurally, and independently tested memory forward packets "
                 "use the narrowed serializer. Request and receive lower bounds assume unstalled links. "
                 "Full-chip execution, bonded routing, memory service overlap and package timing remain open.",
        "evidence_sha256": {str(path): digest(path) for path in (*paths, *map(Path, (
            "verilog/tri_oracle_serial_flit_bridge.sv", "verilog/tri_oracle_serial_flit_bridge_tb.sv",
            "syn/tri_oracle_synthesize_serial_controls.tcl", "syn/link_tri_oracle_serial_controls.py")))}
                         | binding["evidence_sha256"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.run), indent=2, sort_keys=True))
