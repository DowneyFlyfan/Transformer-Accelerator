"""Reconstruct clock buffer placement capacity from two native Innovus exports."""

from decimal import Decimal
from hashlib import file_digest
import json
from pathlib import Path
import re

from audit_tri_oracle_pad_ring_clearance import dimensions
from audit_tri_oracle_physical_io_budget import macro_boxes
from verify_tri_oracle_pad_cold_reload import boundary_sections, components


ROOT = Path(__file__).resolve().parents[1]
RESIZED = Path("records/tri_oracle_whole_chip_value_register_placement.json")
BUFFERED = Path("records/tri_oracle_resized_chip_expanded_control_placement_and_timing.json")
INPUTS = {
    "resized": (RESIZED, "/native_receipt.json", "/cold/layout.def", "/cold/placement.rpt"),
    "control_buffered": (BUFFERED, "/expanded_connected/verified.json",
                         "/native/layout.def", "/native/geometry.rpt"),
}
MASTERS = ("CKBD0", "CKBD4", "CKBD8")
EMPTY_SPAN = re.compile(rb"\x00+")
DENSITY = re.compile(r"(?m)^Placement Density:([\d.]+)%\((\d+)/(\d+)\)$")
ROW = re.compile(r"(?m)^ROW ROW_\d+ core12T (\d+) (\d+) (N|FS) DO (\d+) BY 1 STEP (\d+) 0$")
REGION = re.compile(r"(?m)^- (tri_array_region_\d+) \( (\d+) (\d+) \) \( (\d+) (\d+) \) ;$")


def pin(path, evidence, expected=None):
    with path.open("rb") as stream:
        actual = file_digest(stream, "sha256").hexdigest()
    assert expected is None or actual == expected, path
    evidence[str(path)] = actual
    return path


def linked_file(record, suffix, evidence):
    name, = (name for name in record["evidence_sha256"] if name.endswith(suffix))
    return pin(Path(name), evidence, record["evidence_sha256"][name])


def row_geometry(path):
    lines = []
    with path.open() as stream:
        for line in stream:
            if line.startswith("COMPONENTS "):
                break
            lines.append(line)
        else:
            raise ValueError(f"Missing components in {path}")
    header = "".join(lines)
    assert "\nUNITS DISTANCE MICRONS 2000 ;\n" in header
    assert "\nDIEAREA ( 0 0 ) ( 7200000 7200000 ) ;\n" in header
    rows = {int(y): (int(x), side, int(count), int(step))
            for x, y, side, count, step in ROW.findall(header)}
    regions = {name: tuple(map(int, coordinates))
               for name, *coordinates in REGION.findall(header)}
    assert len(rows) == 2966
    return rows, regions


def slice_for(box, x, y, pitch, height, columns, row_count):
    x0, y0, x1, y1 = box
    return (max(0, (x0-x)//pitch), max(0, (y0-y)//height),
            min(columns, -((x-x1)//pitch)), min(row_count, -((y-y1)//height)))


def measure(layout, report, rows, regions, sizes, units, component_count):
    levels = sorted(rows)
    height = levels[1] - levels[0]
    x, _, columns, pitch = rows[levels[0]]
    y = levels[0]
    assert levels == list(range(y, y + height * len(rows), height))
    assert all((left, count, step) == (x, columns, pitch)
               for left, _, count, step in rows.values())
    widths = {}
    for master in MASTERS:
        width, cell_height = sizes[master + "BWP12T40P140"]
        assert width % pitch == 0 and cell_height == height
        widths[master] = width // pitch

    fixed = {name: pose for name, pose in components(layout) if pose[1] == "FIXED"}
    assert len(fixed) == 631
    _, halos = macro_boxes(fixed, sizes)
    count, blockages = boundary_sections(layout)["BLOCKAGES"]
    grid = [bytearray(columns) for _ in rows]
    for box in (*halos.values(), *blockages):
        lo, first, hi, last = slice_for(box, x, y, pitch, height, columns, len(rows))
        if hi > lo:
            mark = b"\x01" * (hi - lo)
            for index in range(first, last):
                grid[index][lo:hi] = mark
    capacity = sum(row.count(0) for row in grid)

    placed = 0
    occupied = 0
    for name, pose in components(layout):
        master, status, at_x, at_y, orientation, _ = pose
        if status == "FIXED":
            assert fixed.pop(name) == pose
            continue
        assert status == "PLACED" and at_y in rows
        permitted = ("N", "FN") if rows[at_y][1] == "N" else ("FS", "S")
        assert orientation in permitted
        width, cell_height = sizes[master]
        lo, misalignment = divmod(at_x - x, pitch)
        sites, remainder = divmod(width, pitch)
        hi = lo + sites
        assert misalignment == remainder == 0 and cell_height == height
        assert 0 <= lo < hi <= columns
        row = grid[(at_y-y)//height]
        assert row.find(b"\x01", lo, hi) == -1, name
        row[lo:hi] = b"\x01" * sites
        placed += 1
        occupied += sites
    assert not fixed and placed + 631 == component_count

    density, native_occupied, native_total = DENSITY.search(report.read_text()).groups()
    site_area = Decimal(pitch * height) / units ** 2
    assert round(occupied * site_area) == int(native_occupied)
    assert round(capacity * site_area) == int(native_total)
    assert round(Decimal(occupied) * 100 / capacity, 2) == Decimal(density)
    region_data = {}
    for name, box in regions.items():
        lo, first, hi, last = slice_for(box, x, y, pitch, height, columns, len(rows))
        assert box == (x + lo*pitch, y + first*height, x + hi*pitch, y + last*height)
        free = longest = 0
        fits = dict.fromkeys(MASTERS, 0)
        for index in range(first, last):
            for gap in EMPTY_SPAN.finditer(grid[index], lo, hi):
                length = gap.end() - gap.start()
                free += length
                longest = max(longest, length)
                for master, width in widths.items():
                    fits[master] += length // width
        region_data[name] = {"available_sites": free, "longest_contiguous_run": longest,
                             "copies_that_fit_by_master": fits}

    available = capacity - occupied
    assert available == sum(row.count(0) for row in grid)
    assert available == sum(item["available_sites"] for item in region_data.values())
    return {
        "placed_components": placed,
        "fixed_memory_macros": 631,
        "placement_blockages": count,
        "occupied_sites_touching_geometric_blockage": 0,
        "available_sites": available,
        "available_area_mm2": float(available * site_area / 1_000_000),
        "copies_that_fit_by_master": {
            master: sum(item["copies_that_fit_by_master"][master] for item in region_data.values())
            for master in MASTERS
        },
        "regions_with_no_room_by_master": {
            master: sorted(name for name, item in region_data.items()
                           if not item["copies_that_fit_by_master"][master])
            for master in MASTERS
        },
        "region_details": region_data,
    }


def verify():
    evidence, inputs = {}, {}
    for label, (path, receipt_suffix, layout_suffix, report_suffix) in INPUTS.items():
        record = json.loads(pin(path, evidence).read_text())
        receipt = json.loads(linked_file(record, receipt_suffix, evidence).read_text())
        design = linked_file(receipt, "/cold.v", evidence)
        layout = linked_file(receipt, layout_suffix, evidence)
        report = linked_file(receipt, report_suffix, evidence)
        count = record["placed_instances"] if label == "resized" else record["placement"]["components"]
        inputs[label] = (layout, report, evidence[str(design)], count)

    _, regions = row_geometry(inputs["control_buffered"][0])
    assert len(regions) == 20
    units = 2000
    lib = inputs["resized"][0].parents[1] / "import/placed.db/libs/lef"
    lefs = sorted([lib / "tcbn28hpcplusbwp12t40p140.lef", *lib.glob("ts[56]*.lef")])
    assert len(lefs) == 7
    sizes = dimensions([pin(path, evidence) for path in lefs], units)

    results = {}
    for label, (layout, report, sha, count) in inputs.items():
        rows, _ = row_geometry(layout)
        results[label] = measure(layout, report, rows, regions, sizes, units, count)
        results[label]["cold_netlist_sha256"] = sha
    assert results["resized"]["available_sites"] - results["control_buffered"]["available_sites"] == (
        json.loads(BUFFERED.read_text())["placement"]["buffered_sites"]
    )
    for name in ("verify_tri_oracle_value_register_clock_rows", "verify_tri_oracle_pad_cold_reload",
                 "audit_tri_oracle_pad_ring_clearance",
                 "audit_tri_oracle_physical_io_budget"):
        pin(Path("syn") / (name + ".py"), evidence)
    return {
        "state": "native_placement_clock_buffer_row_geometry_verified",
        "placement": results,
        "comparison_regions": regions,
        "evidence_sha256": evidence,
        "scope": ("Counted contiguous row gaps from two exact native exports and reconciled occupied and "
                  "usable area with both Innovus reports. The resized export is measured on the same "
                  "20 region boundaries defined by the control-buffered export. Fits are geometric "
                  "single-master capacities for each region. Clock loads, wire routing and timing "
                  "require separate verification."),
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT
    print(json.dumps(verify(), indent=2, sort_keys=True))
