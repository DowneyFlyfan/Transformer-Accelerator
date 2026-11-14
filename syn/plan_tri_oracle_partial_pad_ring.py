"""Generate a partial perimeter seed that preserves the compiled memory halos."""

import argparse
from decimal import Decimal
import json
from pathlib import Path

from audit_tri_oracle_pad_ring_clearance import overlap
from audit_tri_oracle_placed_chip_boundary import digest
from plan_tri_oracle_pad_ring_macros import load_floorplan, macro_box, row_sites, shift_inward, validate_boxes


ROOT = Path(__file__).resolve().parents[1]


def shift_bottom(fixed, start, end, depth, grid):
    result = {}
    for name, pose in sorted(fixed.items(), key=lambda item: (item[1][1], item[0])):
        box = macro_box(pose)
        halo = pose[4][1]
        minimum = depth if max(start, box[0]) < min(end, box[2]) else 0
        required = minimum + halo
        for placed in result.values():
            other = macro_box(placed)
            if max(other[0], box[0]) < min(other[2], box[2]):
                required = max(required, other[3] + halo)
        result[name] = (pose[0], max(pose[1], -(-required // grid) * grid), *pose[2:])
    return result


def plan(design, libdir, output):
    prior_file = ROOT / "records/tri_oracle_grouped_active_placement.json"
    full_file = ROOT / "records/tri_oracle_pad_ring_macro_seed.json"
    boundary_file = ROOT / "records/tri_oracle_grouped_active_boundary.json"
    prior, full, boundary = (json.loads(path.read_text()) for path in (prior_file, full_file, boundary_file))
    assert prior["candidate_netlist_sha256"] == full["candidate_netlist_sha256"] == boundary["candidate_netlist_sha256"]
    assert digest(design) == prior["placed_design_exchange_sha256"] == boundary["placement_definition_sha256"]
    clearance_file = ROOT / "records/tri_oracle_pad_ring_clearance.json"
    assert digest(clearance_file) == full["evidence_sha256"][str(clearance_file.relative_to(ROOT))]
    clearance = json.loads(clearance_file.read_text())
    lefs = sorted(libdir.glob("*.lef"))
    tech, = libdir.glob("*.tlef")
    assert len(lefs) == 7
    assert all(digest(path) == clearance["evidence_sha256"][str(path.relative_to(ROOT))] for path in lefs)
    assert digest(tech) == full["evidence_sha256"][str(tech.relative_to(ROOT))]
    units, grid, rows, fixed, masters, cell_area = load_floorplan(design, lefs, tech)
    side = 3600 * units
    depth = int(Decimal(full["reserved_pad_depth_micrometers"]) * units)
    pitch = int(Decimal(boundary["minimum_signal_pad_micrometers"]) * units)
    corner = int(Decimal(boundary["minimum_corner_cell_micrometers"]) * units)
    assert depth == corner
    left, bottom, right, top = outline = depth, 0, side - depth, side - depth
    rows_height = int(Decimal("1.2") * units)
    site_width, = {item[3] for item in rows}
    site_area = site_width * rows_height
    assert cell_area % site_area == 0
    used = cell_area // site_area
    full_edge = (side - 2 * corner) // pitch
    assert full_edge * 4 == full["potential_perimeter_slots"]
    payload = boundary["modeled_payload_rate"]["bounds_by_bits_per_pad_per_cycle"]["2"]["minimum_payload_pads"]
    first = shift_inward(fixed, 0, left, grid)
    scenarios = {}
    for n in (0, 32, 64, 96, 128, 160, full_edge):
        end = right
        start = end - n * pitch
        relocated = shift_bottom(first, start, end, depth, grid)
        validate_boxes(relocated, outline)
        blockage = start, 0, end, depth
        reserved = dict(relocated)
        if n:
            assert not any(overlap(macro_box(pose), blockage) for pose in relocated.values())
            reserved["pad_placement_blockage"] = (start, 0, end - start, depth, (0, 0, 0, 0))
        sites = row_sites(rows, rows_height, outline, reserved)
        slots = 3 * full_edge + n
        scenarios[str(n)] = dict(total_signal_pad_slots=slots, slots_beyond_ideal_payload=slots-payload,
                                  free_placement_sites=sites-used, geometric_utilization_percent=100*used/sites,
                                  moved_macros=sum(relocated[name] != pose for name, pose in fixed.items()))
        if n == 64:
            selected = relocated
            blockages = [(0, 0, left, side), (right, 0, side, side), (left, top, right, side), blockage]
    assert scenarios[str(full_edge)]["free_placement_sites"] == -full["site_capacity"]["minimum_site_deficit"]
    output.mkdir()
    coordinates = output / "macros.tsv"
    with coordinates.open("x") as stream:
        stream.write("instance\tmaster\tx_um\ty_um\torient\tleft_um\tbottom_um\tright_um\ttop_um\n")
        for name, (x, y, _, _, halo) in sorted(selected.items()):
            master, orient = masters[name]
            values = [name, master, str(Decimal(x)/units), str(Decimal(y)/units), orient]
            stream.write("\t".join(values + [str(Decimal(value)/units) for value in halo]) + "\n")
    areas = output / "blockages.tsv"
    with areas.open("x") as stream:
        for rectangle in blockages:
            stream.write("\t".join(str(Decimal(value)/units) for value in rectangle) + "\n")
    return dict(
        state="partial_pad_ring_macro_and_blockage_seed_verified",
        candidate_netlist_sha256=prior["candidate_netlist_sha256"],
        selected_bottom_slots=64, ideal_double_data_rate_payload_pads=payload,
        original_macro_halos_preserved=len(fixed), standard_cell_sites_required=used,
        scenarios_by_reserved_bottom_slots=scenarios,
        evidence_sha256={str(path.relative_to(ROOT)): digest(path) for path in
                         (prior_file, full_file, boundary_file, clearance_file, design, tech, *lefs,
                          coordinates, areas, Path(__file__).resolve())},
        scope="Analytical placement capacity with existing macro sizes and original halos. The pad allowance assumes "
              "the selected depth and pitch and ideal two-bit-per-cycle receive throughput. Control, power, ground, "
              "package access, legal standard-cell placement and wiring remain to be verified.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("design", "libdir", "output"):
        parser.add_argument(name, type=lambda path: Path(path).absolute())
    print(json.dumps(plan(**vars(parser.parse_args())), sort_keys=True, indent=2))
