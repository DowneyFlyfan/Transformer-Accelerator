"""Check the credited chip boundary against bonded pad capacity with fixed memory halos."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import tarfile

from audit_tri_oracle_pad_ring_clearance import dimensions, get_units, overlap, screen
from audit_tri_oracle_physical_io_budget import macro_boxes
from audit_tri_oracle_placed_chip_boundary import PAD_ARCHIVE, digest, pad_views
from link_tri_oracle_narrow_host import width
from verify_tri_oracle_host_control import outer_ports
from verify_tri_oracle_pad_cold_reload import components


ROOT = Path(__file__).resolve().parents[1]
BASE = Path(".cache/physical/whole_chip_xcelium_speed")
PHYSICAL = Path("records/tri_oracle_physical_io_budget.json")
CREDIT = Path("records/tri_oracle_split_credit_ingress.json")
TARGETS = Path("records/paper_result_targets.json")
PREPARED = BASE / "full_multicore/prepared.json"
WRAPPER = BASE / "split_credit_ingress/chip_binding/credit_wrapper.v"
RELEASE_PDF = "RN_TPHN28HPCPGV18_170A.pdf"
DATA_PORT = "memory_mem_rsp_data"
EDGES = ("bottom", "left", "right", "top")


def read(path):
    return json.loads(path.read_text())


def vendor_rules(lef_archive, release_archive):
    _, _, width_um, corner_um, abstract = pad_views(lef_archive)
    with tarfile.open(lef_archive, "r:gz") as package:
        (member,) = (entry for entry in package if entry.isfile() and entry.name.endswith(".lef"))
        with package.extractfile(member) as stream:
            pad_lef = stream.read().decode()
    pad_sizes = {
        name: tuple(map(Decimal, re.search(r"(?m)^    SIZE (\S+) BY (\S+) ;$", body).groups()))
        for name, body in re.findall(r"(?ms)^MACRO (\w+)\n(.*?)^END \1\s*$", pad_lef)
    }
    with tarfile.open(release_archive, "r:gz") as package:
        (member,) = (entry for entry in package
                     if entry.isfile() and Path(entry.name).name == RELEASE_PDF)
        with package.extractfile(member) as stream:
            raw = stream.read()
    text = subprocess.run(["pdftotext", "-layout", "-", "-"], input=raw, capture_output=True,
                          check=True).stdout.decode()
    pitch, = re.findall(r"the I/O x-pitch is (\d+)um\.", text)
    depth, = re.findall(r"The I/O height is (\d+)um\.", text)
    assert Decimal(pitch) == width_um
    depth_um = Decimal(depth)
    for name in ("PVDD1DGZ", "PVDD2DGZ", "PVDD2POC", "PVSS2DGZ", "PVSS3DGZ"):
        for orientation in ("H", "V"):
            assert pad_sizes[f"{name}_{orientation}_G"] == (width_um, depth_um)
    core, = re.findall(r"PVDD1DGZ\+\s+PCLAMPC\s+(\d+)\+0\s+1\+1", text)
    io, = re.findall(r"(?m)^ +domain +(\d+)\s*\n +PVDD2DGZ +N/A\s*$", text)
    assert re.search(r"PVSS2DGZ\).*?PVSS3DGZ\).*?corner cell \(PCORNER\)", text, re.DOTALL)

    def fillers(name):
        (left, right), = re.findall(rf"(?m)^\s*{name}\*\*\s+([\d.]+)um\s+([\d.]+)um\s+", text)
        return Decimal(left), Decimal(right)

    left50, right50 = fillers("PAD50")
    left60, right60 = fillers("PAD60")
    # The shared case gives each neighboring pair a single filler and
    # omits filler at the ends. It is an optimistic capacity bound.
    cases = {
        "unbonded_cell_bodies": (width_um, Decimal(0), Decimal(0)),
        "pad50_optimistic_shared_filler": (width_um, max(left50, right50), Decimal(0)),
        "pad50_independent_fillers": (width_um, left50 + right50, left50 + right50),
        "pad60_independent_fillers": (width_um, left60 + right60, left60 + right60),
    }
    return depth_um, corner_um, abstract, cases, {
        "core_supply": int(core), "io_supply": int(io), "corner_ground": 2 * len(EDGES)}


def free_intervals(strip, axis, halos):
    cursor, stop = strip[axis], strip[axis + 2]
    blocked = sorted((max(strip[axis], box[axis]), min(stop, box[axis + 2]))
                     for box in halos if overlap(box, strip))
    intervals = []
    for start, end in blocked:
        if start > cursor:
            intervals.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < stop:
        intervals.append((cursor, stop))
    return intervals


def capacity(intervals, units, case):
    width_um, gap_um, end_clearance_um = case
    cell, gap, end_clearance = (value * units for value in (width_um, gap_um, end_clearance_um))
    assert all(value == int(value) and value >= 0 for value in (cell, gap, end_clearance))
    count = 0
    for start, stop in intervals:
        usable = stop - start - end_clearance
        count += max(0, int((usable + gap) // (cell + gap)))
    return count


def geometry(layout, expected, lefs, depth_um, corner_um, cases):
    assert digest(layout) == expected, layout
    with layout.open() as stream:
        units = get_units(stream)
        for line in stream:
            if match := re.fullmatch(r"DIEAREA \( (\d+) (\d+) \) \( (\d+) (\d+) \) ;\n", line):
                outline = tuple(map(int, match.groups()))
                break
        else:
            raise ValueError(f"Missing die outline in {layout}")
    assert outline == (0, 0, 3600 * units, 3600 * units)
    _, _, right, top = outline
    sizes = dimensions(lefs, units)
    fixed = {name: pose for name, pose in components(layout) if pose[1] == "FIXED"}
    assert len(fixed) == 631 and all(pose[0].startswith(("TS5N28", "TS6N28")) for pose in fixed.values())
    _, halos = macro_boxes(fixed, sizes)
    depth, corner = (int(value * units) for value in (depth_um, corner_um))
    strips = {
        "bottom": ((corner, 0, right - corner, depth), 0),
        "left": ((0, corner, depth, top - corner), 1),
        "right": ((right - depth, corner, right, top - corner), 1),
        "top": ((corner, top - depth, right - corner, top), 0),
    }
    free = {name: free_intervals(strip, axis, halos.values()) for name, (strip, axis) in strips.items()}
    capacity_by_case = {
        label: {name: capacity(free[name], units, case) for name in EDGES}
        for label, case in cases.items()
    }
    baseline = screen(units, outline, halos, cases["unbonded_cell_bodies"][0], corner_um, depth_um)
    assert capacity_by_case["unbonded_cell_bodies"] == {
        name: baseline[name]["sliding_slots_clear_of_fixed"] for name in EDGES}
    no_macros = [(corner, right - corner)]
    return {
        "fixed_memory_macros": len(fixed),
        "capacity_by_case_and_edge": capacity_by_case,
        "upper_bound_without_macros_by_case": {
            label: len(EDGES) * capacity(no_macros, units, case) for label, case in cases.items()},
    }


def conclusions(summary, signals, data, payload, reserve, clock_mhz):
    fixed_signals = signals - data
    ideal_lanes = -(-payload["payload_bits"] // (2 * payload["target_cycles"]))
    rows = {}
    for name, edge_counts in summary["capacity_by_case_and_edge"].items():
        available = sum(edge_counts.values())
        budget = max(0, available - fixed_signals - reserve)
        rows[name] = {
            "sites": available,
            "sites_at_existing_width_before_supplies": available - signals,
            "sites_at_existing_width_with_supply_scenario": available - signals - reserve,
            "maximum_data_pads_with_fixed_signals_and_supply_scenario": budget,
            "extra_sites_needed_for_ideal_encoded_traffic": max(0, ideal_lanes - budget),
            "ideal_encoded_payload_only_ms": (
                float(Decimal(payload["payload_bits"]) / (Decimal(2 * budget * clock_mhz) * 1000))
                if budget else None),
        }
    return rows


def run(pdk_root):
    physical, credit, targets, prepared = (read(path) for path in (PHYSICAL, CREDIT, TARGETS, PREPARED))
    assert digest(WRAPPER) == credit["evidence_sha256"][str(WRAPPER)]
    ports = outer_ports(WRAPPER.read_text())
    signals = width(ports)
    direction, data = ports[DATA_PORT]
    assert signals == credit["whole_chip_structural_signal_bits"] == 531
    assert direction == "INPUT" and data == 448

    old_pins = physical["evidence_sha256"]
    assert digest(TARGETS) == old_pins[str(TARGETS)]
    lefs = tuple(Path(name) for name in old_pins if name.endswith(".lef"))
    older, = (Path(name) for name in old_pins if name.endswith("/cold.def"))
    native = Path(prepared["bundle"]).parent.parent.relative_to(ROOT)
    receipt_path = native / "verified.json"
    receipt = read(receipt_path)
    latest = native / "cold/layout.def"
    assert receipt["cold_netlist_sha256"] == prepared["cold_netlist_sha256"]
    expected_latest = receipt["evidence_sha256"][str(latest)]
    assert len(lefs) == 7 and all(digest(path) == old_pins[str(path)] for path in lefs)

    archive = pdk_root.joinpath(*PAD_ARCHIVE.parts[2:])
    release = archive.with_name("tphn28hpcpgv18_170a_rln.tar.gz")
    assert digest(archive) == old_pins[str(PAD_ARCHIVE)]
    depth, corner, abstract, cases, supplies = vendor_rules(archive, release)
    args = (lefs, depth, corner, cases)
    with ProcessPoolExecutor(max_workers=2) as pool:
        reference = pool.submit(geometry, older, old_pins[str(older)], *args)
        recent = pool.submit(geometry, latest, expected_latest, *args)
        old, new = reference.result(), recent.result()
    assert old["capacity_by_case_and_edge"]["unbonded_cell_bodies"] == physical["macro_halo_clear_slots_by_edge"]
    assert old == new, "The cold floorplans have different pad capacity"

    peak = targets["peak"]["clock_megahertz"]
    clock_count = physical["target_cycles"]
    assert clock_count == peak * 1000 * targets["system_latency"]["milliseconds"]
    encoded = physical["receive_only_bounds"]["conditional_exact_weight_encoding_plus_full_index_and_sign"]
    payload = {"payload_bits": 8 * encoded["payload_bytes"], "target_cycles": clock_count}
    min_data_lanes = -(-payload["payload_bits"] // (2 * clock_count))
    assert min_data_lanes == encoded["two_bits_per_cycle_input_pads"] == 383

    # One illustrative no-clamp scenario. Two I/O grounds across every
    # active side represent the two corner transitions. This is a geometry
    # budget and gives no assurance of current delivery or ESD performance.
    scenarios = conclusions(new, signals, data, payload, sum(supplies.values()), peak)
    assert scenarios["pad50_optimistic_shared_filler"]["sites_at_existing_width_before_supplies"] < 0
    assert new["upper_bound_without_macros_by_case"]["pad50_independent_fillers"] < signals + sum(supplies.values())

    inputs = (PHYSICAL, CREDIT, TARGETS, PREPARED, receipt_path, WRAPPER,
              older, latest, *lefs, archive, release, Path(__file__).resolve().relative_to(ROOT))
    return {
        "state": "credited_interface_exceeds_pad50_capacity_on_fixed_floorplans",
        "die_mm": targets["silicon"]["die_dimensions_mm"],
        "pad_view_sha256": abstract,
        "data_receive_signals": data,
        "other_signals": signals - data,
        "total_signals": signals,
        "illustrative_supply_and_ground_pads": supplies,
        "ideal_encoded_minimum_data_pads": min_data_lanes,
        "cold_floorplan": str(latest),
        "matched_predecessor_floorplan": str(older),
        "geometry": new,
        "scenarios": scenarios,
        "scope": "Fixed memory halo and bonded spacing capacity bounds for a perimeter of 20-micrometer "
                 "digital pad bodies. The optimistic shared-filler case excludes filler at interval ends. "
                 "The independent-filler case includes both sides per pad. Bond extensions, core-power "
                 "latch-up isolation, power delivery, package escape and routability can reduce capacity "
                 "further. The power and ground counts are an explicit scenario. The payload estimate "
                 "excludes control traffic and assumes both clock edges are fully useful.",
        "evidence_sha256": {str(path): digest(path) for path in inputs},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk-root", required=True, type=Path)
    options = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(run(options.pdk_root), indent=2, sort_keys=True))
