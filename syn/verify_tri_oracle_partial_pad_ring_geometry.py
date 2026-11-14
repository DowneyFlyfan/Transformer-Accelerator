"""Check every placed cell against the partial pad ring and kept macro halos."""

import argparse
import csv
from decimal import Decimal
import json
from pathlib import Path
import re

from audit_tri_oracle_pad_ring_clearance import POSE, contains, dimensions, get_units, overlap
from audit_tri_oracle_placed_chip_boundary import digest
from plan_tri_oracle_pad_ring_macros import ROW, macro_box, validate_boxes


ROOT = Path(__file__).resolve().parents[1]


def scaled(text, units):
    value = Decimal(text) * units
    assert value == int(value), text
    return int(value)


def seed_geometry(seed, units, sizes):
    boxes = {}
    expected = {}
    with (seed / "macros.tsv").open() as source:
        for row in csv.DictReader(source, delimiter="\t"):
            name = row["instance"].replace("\\", "")
            assert name not in expected
            x = scaled(row["x_um"], units)
            y = scaled(row["y_um"], units)
            halo = tuple(scaled(row[side + "_um"], units) for side in ("left", "bottom", "right", "top"))
            master = row["master"]
            boxes[name] = x, y, *sizes[master], halo
            expected[name] = master, x, y, row["orient"], halo
    with (seed / "blockages.tsv").open() as source:
        blockages = [tuple(scaled(value, units) for value in line.split()) for line in source]
    assert len(expected) == 631 and len(blockages) == 4
    outline = (0, 0, 3600 * units, 3600 * units)
    validate_boxes(boxes, outline)
    macro_halos = list(map(macro_box, boxes.values()))
    assert all(contains(outline, blockage) and
               not any(overlap(blockage, halo) for halo in macro_halos) for blockage in blockages)
    return expected, macro_halos + blockages


def mark_reserved(grid, row_y, origin_x, pitch, height, box):
    left, bottom, right, top = box
    if max(row_y, bottom) >= min(row_y + height, top):
        return
    start = max(0, (left - origin_x) // pitch)
    stop = min(len(grid), -(-(right - origin_x) // pitch))
    if start < stop:
        grid[start:stop] = b"\x01" * (stop - start)


def check_geometry(layout, seed, libraries):
    with layout.open() as source:
        units = get_units(source)
        sizes = dimensions(libraries, units)
        macros, reserved = seed_geometry(seed, units, sizes)
        height = scaled("1.2", units)
        rows = {}
        outline = (0, 0, 3600 * units, 3600 * units)
        die = None
        for line in source:
            if line == f"DIEAREA ( 0 0 ) ( {outline[2]} {outline[3]} ) ;\n":
                die = outline
            if match := ROW.match(line):
                x, y, direction, count, pitch = match.groups()
                x, y, count, pitch = map(int, (x, y, count, pitch))
                assert y not in rows
                grid = bytearray(count)
                for box in reserved:
                    mark_reserved(grid, y, x, pitch, height, box)
                rows[y] = x, pitch, direction, grid
            if match := re.fullmatch(r"COMPONENTS (\d+) ;\n", line):
                count = int(match[1])
                break
        else:
            raise ValueError("Missing component section")
        assert die and count == 3765868 and len(rows) == 2966
        placed = fixed = used_sites = 0
        for line in source:
            if line == "END COMPONENTS\n":
                break
            if not line.startswith("- "):
                continue
            match = POSE.match(line)
            assert match, line
            name, master, status, x, y, orientation = match.groups()
            x, y = int(x), int(y)
            if status == "FIXED":
                halo_line = next(source)
                assert re.fullmatch(r"\s*\+ HALO (?:\d+ ){3}\d+\s*\n", halo_line), name
                halo = tuple(map(int, halo_line.split()[2:]))
                assert macros.pop(name.replace("\\", "")) == (master, x, y, orientation, halo), name
                fixed += 1
                continue
            origin, pitch, row_side, grid = rows[y]
            width, cell_height = sizes[master]
            assert cell_height % height == 0 and width % pitch == (x - origin) % pitch == 0, name
            assert orientation in ({"N", "FN"} if row_side == "N" else {"FS", "S"}), name
            for row_y in range(y, y + cell_height, height):
                row_origin, row_pitch, _, row_grid = rows[row_y]
                assert row_origin == origin and row_pitch == pitch
                begin, end = (x - origin) // pitch, (x + width - origin) // pitch
                assert 0 <= begin < end <= len(row_grid), name
                assert not any(row_grid[begin:end]), (name, x, y, "overlap, macro halo or pad reserve")
                row_grid[begin:end] = b"\x02" * (end - begin)
                used_sites += end - begin
            placed += 1
        else:
            raise ValueError("Unterminated component section")
    assert placed + fixed == count and fixed == 631 and not macros
    return dict(standard_cells=placed, fixed_memories=fixed, used_sites=used_sites,
                free_unblocked_sites=sum(row[3].count(0) for row in rows.values()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("trial", "seed", "libraries"):
        parser.add_argument(name, type=lambda value: Path(value).absolute())
    args = parser.parse_args()
    record = ROOT / "records/tri_oracle_partial_pad_ring_seed.json"
    plan = json.loads(record.read_text())
    native = json.loads((args.trial / "receipt.json").read_text())
    export = args.trial / "pad_ring.def"
    assert digest(export) == native["output_definition_sha256"]
    assert native["input_candidate_sha256"] == plan["candidate_netlist_sha256"]
    lefs = sorted(args.libraries.glob("*.lef"))
    assert len(lefs) == 7
    inputs = (args.seed / "macros.tsv", args.seed / "blockages.tsv", *lefs)
    assert all(digest(path) == plan["evidence_sha256"][str(path.relative_to(ROOT))] for path in inputs)
    result = check_geometry(export, args.seed, lefs)
    assert result["used_sites"] == plan["standard_cell_sites_required"]
    print(json.dumps(result, sort_keys=True, indent=2))
