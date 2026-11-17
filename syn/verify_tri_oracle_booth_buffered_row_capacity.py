"""Measure legal free sites in the exact cold-reloaded Booth placement."""

import json
from decimal import Decimal
from pathlib import Path
import re

from audit_tri_oracle_pad_ring_clearance import contains, dimensions
from audit_tri_oracle_physical_io_budget import macro_boxes
from verify_tri_oracle_booth_chip_geometry import geometry, layout
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, digest
from verify_tri_oracle_pad_cold_reload import components


PLACEMENT = Path("records/tri_oracle_corrected_booth_buffered_placement_roundtrip.json")
MODELS = Path("records/tri_oracle_corrected_booth_buffered_models.json")


def verify():
    placement = json.loads(PLACEMENT.read_text())
    models = json.loads(MODELS.read_text())
    assert placement["database_fingerprint_sha256"] == models["database_fingerprint_sha256"]
    database = Path(placement["database"])
    exported = database.parents[1] / "cold/layout.def"
    evidence = {}

    def pin(path, expected=None):
        actual = digest(path)
        assert expected is None or expected == actual, path
        evidence[str(path)] = actual
        return path

    pin(exported, placement["evidence_sha256"][str(exported)])
    libraries = [
        pin(path, models["evidence_sha256"][str(path)])
        for path in sorted((database / "libs/lef").glob("*.lef"))
    ]
    assert len(libraries) == 7, libraries
    die, units, rows, regions, groups, keepouts = geometry(exported, verify_top=True)
    expected = placement["geometry"]
    assert len(rows) == expected["placement_rows"] and len(keepouts) == expected["placement_blockages"]
    assert len(groups) == len(regions) == expected["regions"] == 20
    assert all(contains(die, bounds) for bounds in (*regions.values(), *keepouts))
    sizes = dimensions(libraries, units)
    memories = {name: pose for name, pose in components(exported) if pose[1] == "FIXED"}
    assert len(memories) == expected["fixed_memory_macros"]
    _, halos = macro_boxes(memories, sizes)
    assert all(contains(die, bounds) for bounds in halos.values())

    levels = sorted(rows)
    row_height = levels[1] - levels[0]
    counts, array_counts, array_sites, free, total_sites, free_sites = layout(
        exported, sizes, rows, regions, groups, keepouts + list(halos.values()), memories, row_height,
    )
    assert counts == {"PLACED": expected["standard_cells"], "FIXED": expected["fixed_memory_macros"]}
    assert array_counts.keys() == array_sites.keys() == free.keys() == regions.keys()
    assert all(value > 0 for value in array_counts.values())
    assert not memories and 0 <= sum(free.values()) <= free_sites < total_sites
    pitch = rows[levels[0]][3]
    site_area = Decimal(pitch * row_height) / (units * units)
    occupied = total_sites - free_sites
    density = round(Decimal(occupied) * 100 / total_sites, 2)
    report = exported.with_name("placement.rpt")
    text = pin(report, placement["evidence_sha256"][str(report)]).read_text()
    (native_density, native_occupied, native_total), = re.findall(
        r"(?m)^Placement Density:([\d.]+)%\((\d+)/(\d+)\)$", text,
    )
    assert density == Decimal(native_density)
    assert (round(occupied * site_area), round(total_sites * site_area)) == (int(native_occupied), int(native_total))
    pin(PLACEMENT)
    pin(MODELS)
    pin(Path(__file__).resolve().relative_to(ROOT))
    pin(Path("syn/verify_tri_oracle_booth_chip_geometry.py"))
    return {
        "state": "repaired_booth_native_placement_free_sites_verified",
        "database_fingerprint_sha256": placement["database_fingerprint_sha256"],
        "standard_cells": counts["PLACED"],
        "fixed_memory_macros": counts["FIXED"],
        "row_sites_available_after_keepouts": total_sites,
        "row_sites_occupied": occupied,
        "row_sites_free": free_sites,
        "row_sites_free_outside_compute_regions": free_sites - sum(free.values()),
        "row_sites_free_by_region": free,
        "least_free_region": min(free, key=free.get),
        "site_area_square_micrometers": str(site_area),
        "native_placement_density_percent_checked": str(density),
        "scope": "Counts from the cold-reloaded Design Exchange Format placement and Library Exchange Format dimensions. "
                 "Hard placement blockages and memory halos are excluded. This inventory measures standard-cell sites.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    print(json.dumps(verify(), indent=2, sort_keys=True))
