"""Assign the credited chip ports to flip-chip contacts and verify their geometry."""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
from hashlib import sha256
from itertools import combinations, product
import json
from math import isqrt
from pathlib import Path
import re
from struct import unpack, unpack_from
import tarfile

import torch

from audit_tri_oracle_bonded_pad_capacity import (
    CREDIT, EDGES, PHYSICAL, ROOT, WRAPPER, free_intervals, read, vendor_rules,
)
from audit_tri_oracle_pad_ring_clearance import contains, dimensions, get_units, overlap
from audit_tri_oracle_physical_io_budget import macro_boxes
from audit_tri_oracle_placed_chip_boundary import PAD_ARCHIVE, digest
from verify_tri_oracle_host_control import outer_ports
from verify_tri_oracle_pad_cold_reload import components


BONDED = Path("records/tri_oracle_bonded_pad_capacity.json")
BUMP_ARCHIVE = Path("tsmc28hpc/IO/tpbn28v_140b/AN61001_20180130/tpbn28v_140a_gdsfcmt10mz.tar.gz")
GDS_SUFFIX = "/fc/fc_eu/MTRDL/10m/10M_Z/tpbn28v.gds"
BUMP = "PAD80MTB_EU"


def gds_geometry(archive):
    with tarfile.open(archive, "r:gz") as source:
        (member,) = (entry for entry in source if entry.isfile() and entry.name.endswith(GDS_SUFFIX))
        with source.extractfile(member) as stream:
            data = stream.read()

    def decode_real8(raw):
        return (Decimal(int.from_bytes(raw[1:], "big")) / 2**56
                * Decimal(16)**((raw[0] & 127) - 64))

    offset = 0
    cells = defaultdict(dict)
    name = None
    boundary = False
    dbu_nm = None
    while offset < len(data) and data[offset:offset + 4] != b"\0" * 4:
        count, kind, _ = unpack_from(">HBB", data, offset)
        assert count >= 4 and count % 2 == 0 and offset + count <= len(data)
        value = data[offset + 4:offset + count]
        offset += count
        if kind == 3:  # UNITS
            assert len(value) == 16
            nm = decode_real8(value[8:]) * 10**9
            dbu_nm = int(round(nm))
            assert abs(nm - dbu_nm) < Decimal("1e-12") and dbu_nm > 0
        elif kind == 6:  # STRNAME
            name = value.rstrip(b"\0").decode("ascii")
            assert name not in cells
        elif kind == 8:  # BOUNDARY
            boundary = True
            layer = datatype = None
        elif kind in (9, 10, 11, 21, 45):  # Unsupported geometry/hierarchy in these views.
            raise ValueError(f"Expected flat boundary shapes, got record {kind}")
        elif kind == 13 and boundary:
            layer, = unpack(">h", value)
        elif kind == 14 and boundary:
            datatype, = unpack(">h", value)
        elif kind == 16 and boundary:
            coords = unpack(">" + "i" * (len(value) // 4), value)
            xs, ys = coords[::2], coords[1::2]
            assert len(xs) >= 5 and (xs[0], ys[0]) == (xs[-1], ys[-1])
            assert name is not None and layer is not None and datatype is not None
            assert (layer, datatype) not in cells[name]
            cells[name][layer, datatype] = (min(xs), min(ys), max(xs), max(ys))
        elif kind == 17:  # ENDEL
            boundary = False
    assert dbu_nm is not None and not any(data[offset:])
    assert set(cells) == {f"PAD{size}MTB_EU" for size in (80, 85, 90, 100, 110)}
    boxes = cells[BUMP]
    assert len(boxes) == 7 and all(contains((0, 0, 93300, 93300), box) for box in boxes.values())
    extent = tuple(max(box[axis] for box in boxes.values()) for axis in (2, 3))
    assert extent == (93300, 93300) and dbu_nm == 1
    return dbu_nm, extent, sha256(data).hexdigest()


def as_units(um, units):
    value = Decimal(um) * units
    assert value == int(value), um
    return int(value)


def port_bits(wrapper):
    ports = outer_ports(wrapper.read_text())
    return {
        bit: direction.lower()
        for name, (direction, size) in ports.items()
        for bit in ([name] if size is None else (f"{name}[{index}]" for index in range(size)))
    }


def conditioning_cells(halos, signals, supplies, side, corner, length, depth, grid):
    strips = {
        "bottom": ((corner, 0, side - corner, depth), 0),
        "left": ((0, corner, depth, side - corner), 1),
        "right": ((side - depth, corner, side, side - corner), 1),
        "top": ((corner, side - depth, side - corner, side), 0),
    }
    free = {}
    for edge, (strip, axis) in strips.items():
        free[edge] = []
        for start, stop in free_intervals(strip, axis, halos):
            start = -(-start // grid) * grid
            for at in range(start, stop - length + 1, length):
                box = list(strip)
                box[axis], box[axis + 2] = at, at + length
                free[edge].append(tuple(box))
    counts = {edge: len(values) for edge, values in free.items()}
    assert supplies["corner_ground"] == 2 * len(EDGES)
    entries = []
    for edge in EDGES:
        first, last = free[edge].pop(0), free[edge].pop()
        for side_of_edge, box in (("start", first), ("end", last)):
            entries.append((f"io_ground_{edge}_{side_of_edge}", "corner_ground", edge, box))
    # A supply group begins behind one of the corner grounds. Placing the
    # input/output supply cells after the core supply gives physical clearance
    # between the core supply cells and the first digital function cell.
    for role in ("core_supply", "io_supply"):
        for index in range(supplies[role]):
            entries.append((f"{role}_{index}", role, "top", free["top"].pop(0)))
    for direction, bit_group in (("input", "memory_mem_rsp_data["), ("input", ""), ("output", "")):
        for name, use in signals.items():
            if use != direction or name.startswith("memory_mem_rsp_data[") != bool(bit_group):
                continue
            edge = max(EDGES, key=lambda item: len(free[item]))
            assert free[edge], "Ran out of conditioning cell sites"
            entries.append((name, direction, edge, free[edge].pop(0)))
    assert len(entries) == len(signals) + sum(supplies.values())
    assert {name for name, _, _, _ in entries} >= signals.keys()
    return counts, entries


def overlaid_grid(side, edge_inset, footprint, ap_pitch, macros, halos, wanted):
    array_side = 1 + isqrt(wanted - 1)
    # A square grid aligned to the top redistribution layer's routing pitch.
    maximum = (side - 2 * edge_inset - footprint) // (array_side - 1)
    pitch = maximum // ap_pitch * ap_pitch
    assert pitch > footprint
    stage = torch.device("cuda")
    axis = torch.arange(array_side, device=stage, dtype=torch.int32) * pitch
    x, y = (field.reshape(-1) for field in torch.meshgrid(axis, axis, indexing="ij"))
    offsets = [
        (i, j) for i, j in product(
            range(-(-(edge_inset + footprint//2) // ap_pitch) * ap_pitch,
                  side - edge_inset - footprint//2 - int(axis[-1]) + 1, ap_pitch), repeat=2)
    ]
    assert offsets
    corner = torch.stack((x, y), dim=1)
    bodies = torch.tensor(macros, dtype=torch.int32, device=stage)
    memory_halos = torch.tensor(halos, dtype=torch.int32, device=stage)

    def overlaps(lower, upper, boxes):
        return ((lower[:, :, None, :] < boxes[None, None, :, 2:]).all(dim=3)
                & (boxes[None, None, :, :2] < upper[:, :, None, :]).all(dim=3)).any(dim=2)

    best = None
    for start in range(0, len(offsets), 8):
        candidates = offsets[start:start + 8]
        shift = torch.tensor(candidates, dtype=torch.int32, device=stage)
        lower = corner[None] + shift[:, None, :] - footprint//2
        upper = lower + footprint
        hit_body = overlaps(lower, upper, bodies)
        hit_halo = overlaps(lower, upper, memory_halos)
        scores = list(zip(hit_body.sum(1).tolist(), hit_halo.sum(1).tolist(), candidates, strict=True))
        index = min(range(len(scores)), key=scores.__getitem__)
        if best is None or scores[index] < best[0]:
            best = (scores[index], lower[index].tolist(), upper[index].tolist(),
                    hit_body[index].tolist(), hit_halo[index].tolist())
    score, lower, upper, hit_body, hit_halo = best
    order = sorted(range(len(lower)), key=lambda i: (hit_body[i], hit_halo[i], i))
    chosen = [tuple(lower[i] + upper[i]) for i in order[:wanted]]
    for i in range(len(lower)):
        rect = tuple(lower[i] + upper[i])
        assert hit_body[i] == any(overlap(rect, box) for box in macros)
        assert hit_halo[i] == any(overlap(rect, box) for box in halos)
    assert len(chosen) == wanted
    return {
        "array_side": array_side, "pitch": pitch, "sites": len(lower), "offsets_checked": len(offsets),
        "best_body_clear_sites": len(lower) - score[0], "overlaid_body_count_used": sum(hit_body[i] for i in order[:wanted]),
        "overlaid_halo_count_used": sum(hit_halo[i] for i in order[:wanted]),
    }, chosen


def residue_counts(mask, step):
    rows = torch.arange(mask.shape[0], device=mask.device) % step
    columns = torch.arange(mask.shape[1], device=mask.device) % step
    ids = rows[:, None] * step + columns[None, :]
    return torch.bincount(ids[mask], minlength=step * step)


def tile_cover_bound(mask, tile_side):
    # Each nonempty bin can hold at most one bump when every pair of
    # centers in a bin is less than a footprint apart in both dimensions.
    # Include partially clipped bins for each alignment of the partition.
    padding = tile_side - 1
    padded = torch.nn.functional.pad(mask.float(), (padding,) * 4)
    occupied = torch.nn.functional.max_pool2d(padded[None], tile_side, stride=1)[0].bool()
    return int(residue_counts(occupied, tile_side).min())


def body_clear_capacity(side, margin, footprint, ap_pitch, maximum_trial_pitch, bodies, units):
    lower = -(-(margin + footprint//2) // ap_pitch) * ap_pitch
    upper = side - margin - footprint//2
    axis = torch.arange(lower, upper + 1, ap_pitch, device="cuda", dtype=torch.int32)
    boxes = torch.tensor(bodies, dtype=torch.int32, device=axis.device)

    def intersects_axis(index):
        before_end = axis[:, None] - footprint//2 < boxes[None, :, index + 2]
        after_start = boxes[None, :, index] < axis[:, None] + footprint//2
        return (before_end & after_start).float()

    # The matrix product counts exact intersections because its terms are
    # binary and the finite memory inventory is much smaller than 2**24.
    allowed = (intersects_axis(0) @ intersects_axis(1).T) == 0
    tile_side = -(-footprint // ap_pitch)
    limit = tile_cover_bound(allowed, tile_side)
    trials = {str(Decimal(step * ap_pitch) / units): int(residue_counts(allowed, step).max())
              for step in range(tile_side, 1 + maximum_trial_pitch // ap_pitch)}
    assert max(trials.values()) <= limit
    return {
        "track_centers_away_from_memory": int(allowed.sum()),
        "maximum_contacts_by_tested_regular_pitch_um": trials,
        "upper_bound_for_any_body_clear_track_aligned_placement": limit,
        "tile_width_in_top_metal_tracks": tile_side,
    }


def run(pdk_root, out):
    bonded, credited, physical = (read(path) for path in (BONDED, CREDIT, PHYSICAL))
    assert digest(WRAPPER) == credited["evidence_sha256"][str(WRAPPER)]
    signals = port_bits(WRAPPER)
    assert len(signals) == bonded["total_signals"] == 531
    assert sum(name.startswith("memory_mem_rsp_data[") for name in signals) == bonded["data_receive_signals"] == 448
    layout = Path(bonded["cold_floorplan"])
    assert digest(layout) == bonded["evidence_sha256"][str(layout)]
    lefs = [Path(name) for name in physical["evidence_sha256"] if name.endswith(".lef")]
    assert len(lefs) == 7 and all(digest(path) == bonded["evidence_sha256"][str(path)] for path in lefs)
    technology, = sorted(lefs[0].parent.glob("*.tlef"))
    tech = technology.read_text()
    grid_um, = re.findall(r"(?m)^MANUFACTURINGGRID (\S+) ;$", tech)
    top, = re.findall(r"(?ms)^LAYER AP\n(.*?)^END AP$", tech)
    (px, py), = re.findall(r"(?m)^\s+PITCH\s+(\S+) (\S+) ;$", top)
    assert px == py and re.search(r"(?ms)^VIA VIA10AP_1cut DEFAULT\n.*?^END VIA10AP_1cut$", tech)
    assert re.search(r"(?m)^\s+OFFSET\s+0\.0+ 0\.0+ ;$", top)
    macro_lefs = [path for path in lefs if path.name.startswith("ts")]
    obs = set()
    for path in macro_lefs:
        (block,) = re.findall(r"(?ms)^\s+OBS\s*\n(.*?)^\s+END\s*\n", path.read_text())
        obs.update(re.findall(r"(?m)^\s+LAYER (\S+) ;$", block))
    assert obs and not {"M10", "AP", "RV"} & obs

    io_archive = pdk_root.joinpath(*PAD_ARCHIVE.parts[2:])
    release = io_archive.with_name("tphn28hpcpgv18_170a_rln.tar.gz")
    assert all(digest(path) == bonded["evidence_sha256"][str(path)] for path in (io_archive, release))
    depth, corner, _, io_cases, supplies = vendor_rules(io_archive, release)
    assert supplies == bonded["illustrative_supply_and_ground_pads"]
    bump_archive = pdk_root / BUMP_ARCHIVE
    dbu, size, member_hash = gds_geometry(bump_archive)
    with layout.open() as stream:
        units = get_units(stream)
    fixed = {name: pose for name, pose in components(layout) if pose[1] == "FIXED"}
    assert len(fixed) == bonded["geometry"]["fixed_memory_macros"] == 631
    body, halo = macro_boxes(fixed, dimensions(lefs, units))
    body, halo = tuple(body.values()), tuple(halo.values())
    side = as_units(3600, units)
    corner = as_units(corner, units)
    depth = as_units(depth, units)
    grid = as_units(grid_um, units)
    footprint = as_units(Decimal(size[0] * dbu) / 1000, units)
    ap_pitch = as_units(px, units)
    length = as_units(io_cases["unbonded_cell_bodies"][0], units)
    site_counts, entries = conditioning_cells(halo, signals, supplies, side, corner, length, depth, grid)
    assert site_counts == bonded["geometry"]["capacity_by_case_and_edge"]["unbonded_cell_bodies"]

    die = (0, 0, side, side)
    corners = [(x, y, x + corner, y + corner) for x, y in product((0, side - corner), repeat=2)]
    pad_boxes = [entry[3] for entry in entries] + corners
    assert all(contains(die, pad) and not any(overlap(pad, box) for box in halo) for pad in pad_boxes)
    assert all(not overlap(a, b) for a, b in combinations(pad_boxes, 2))
    isolated = as_units(3, units)
    for _, role, _, (lx, ly, ux, uy) in entries:
        if role == "core_supply":
            box = (lx - isolated, ly - isolated, ux + isolated, uy + isolated)
            assert all(not overlap(box, pad) for _, use, _, pad in entries if use in ("input", "output"))
    torch.cuda.set_per_process_memory_fraction(0.15)
    array, bumps = overlaid_grid(side, corner, footprint, ap_pitch, body, halo, len(entries))
    margin_um = str(Decimal(corner) / units)
    clear = {
        str(Decimal(margin) / units):
            body_clear_capacity(side, margin, footprint, ap_pitch, array["pitch"], body, units)
        for margin in (0, corner)
    }
    body_clear_limit = clear[margin_um]["upper_bound_for_any_body_clear_track_aligned_placement"]
    interior = (corner, corner, side - corner, side - corner)
    assert all(contains(interior, box) for box in bumps)
    assert all((lx + ux) % (2 * ap_pitch) == (ly + uy) % (2 * ap_pitch) == 0
               for lx, ly, ux, uy in bumps)
    assert all(not overlap(a, b) for a, b in combinations(bumps, 2))
    assert len({name for name, _, _, _ in entries}) == len(entries)
    assert len(bumps) == len(entries)

    out.mkdir(parents=True, exist_ok=True)
    placement = out / "contacts.json"
    content = json.dumps({
        "database_units_per_micrometer": units,
        "contacts": [dict(terminal=name, role=role, edge=edge, io_box=box, bump_box=bump)
                     for (name, role, edge, box), bump in zip(entries, bumps, strict=True)],
    }, indent=2) + "\n"
    if placement.exists():
        assert placement.read_text() == content
    else:
        placement.write_text(content)

    return {
        "state": "flip_chip_contact_geometry_constructed_for_credited_interface",
        "signal_contacts": len(signals),
        "memory_data_contacts": bonded["data_receive_signals"],
        "supply_and_ground_contacts_scenario": sum(supplies.values()),
        "installed_bump_master": BUMP,
        "full_checked_footprint_um": size[0] * dbu / 1000,
        "array_rows_and_columns": [array["array_side"]] * 2,
        "array_sites": array["sites"],
        "remaining_array_sites": array["sites"] - len(entries),
        "pitch_um_aligned_to_top_redistribution_layer": array["pitch"] / units,
        "assumed_die_edge_clearance_um": corner / units,
        "array_origins_checked_on_gpu": array["offsets_checked"],
        "maximum_body_clear_sites_in_trial_array": array["best_body_clear_sites"],
        "minimum_memory_overlays_at_checked_pitch_and_edge_clearance": array["overlaid_body_count_used"],
        "lower_bound_on_over_memory_contacts_with_assumed_margin": max(0, len(entries) - body_clear_limit),
        "contacts_over_memory_halos": array["overlaid_halo_count_used"],
        "body_clear_track_aligned_capacity_by_edge_margin_um": clear,
        "conditioning_cells_by_edge": dict(Counter(edge for _, _, edge, _ in entries)),
        "conditioning_slots_available_by_edge": site_counts,
        "bump_stream_sha256": member_hash,
        "scope": "Constructive contact geometry using the installed bump bounding boxes and fixed macro halos. "
                 "The bump pitch and edge margin are explicit layout scenarios. The body-clear capacity bound "
                 "applies to rectangular footprint boxes centered on the tested metal track grid. "
                 "Memory abstracts have no top redistribution layer obstructions. The array still requires "
                 "package approval for bump-over-memory placement, continuous supply rails, a routed "
                 "redistribution layer, package escape and timing verification.",
        "evidence_sha256": {str(path): digest(path) for path in (
            BONDED, CREDIT, PHYSICAL, WRAPPER, layout, *lefs, technology, io_archive, release,
            bump_archive, placement, Path(__file__).resolve().relative_to(ROOT))},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    options = parser.parse_args()
    assert Path.cwd() == ROOT and not Path("/.dockerenv").exists() and __debug__ and torch.cuda.is_available()
    assert options.out.resolve().is_relative_to(ROOT / ".cache")
    print(json.dumps(run(options.pdk_root, options.out), indent=2, sort_keys=True))
