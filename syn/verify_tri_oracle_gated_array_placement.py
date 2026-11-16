"""Place the verified gated compute array in the saved tight array region."""
import argparse
from bisect import bisect_left, insort
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

from verify_tri_oracle_gated_compute_array import ROOT, WORK as GATED, digest, read, timing_script
from audit_tri_oracle_pad_ring_clearance import dimensions
from plan_tri_oracle_pad_ring_macros import ROW
from verify_tri_oracle_pad_cold_reload import components


WORK = GATED.with_name("gated_array_placement")
ARRAY = Path("records/tri_oracle_gated_compute_array.json")
REGION = Path("records/tri_oracle_arithmetic_placement_single_hold_repair.json")
CHECKER = Path("syn/tri_oracle_require_clean_placement.tcl")
LEF = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140.lef")


def section(text, name):
    match = re.search(rf"(?ms)^{name} (\d+) ;\n.*?^END {name}\n", text)
    assert match, name
    return int(match[1]), match[0]


def geometry(text):
    return {item: section(text, item) for item in ("PINS", "BLOCKAGES")}


def sorted_entries(section_text, name, count):
    _, _, body = section_text.partition("\n")
    body = body.removesuffix(f"END {name}\n")
    entries = [" ".join(item.split()) for item in re.split(r"(?m)^[ \t]*- ", body)[1:]]
    assert len(entries) == count and all(item.endswith(";") for item in entries)
    return sorted(entries)


def fixture(source):
    header, sep, _ = source.partition("\nCOMPONENTS ")
    assert sep and "DESIGN tri_oracle_pe_array ;" in header and "\nROW " in header and "\nTRACKS " in header
    return header + "\n\n" + "\n".join(text for _, text in geometry(source).values()) + "\nEND DESIGN\n"


def row_slots(region, widths):
    rows = [(int(x), int(y), side, int(count), int(pitch))
            for line in region.splitlines() if (match := ROW.match(line))
            for x, y, side, count, pitch in (match.groups(),)]
    assert len(rows) == 593 and len({(x, count, step) for x, _, _, count, step in rows}) == 1
    left, bottom, _, columns, pitch = rows[0]
    height = rows[1][1] - bottom
    assert height == 2400 and pitch == 280
    assert [row[1] for row in rows] == [bottom + i * height for i in range(len(rows))]
    reserved = [bytearray(columns) for _ in rows]
    block_count, body = section(region, "BLOCKAGES")
    boxes = re.findall(r"(?m)^\s*- PLACEMENT RECT \( (\d+) (\d+) \) \( (\d+) (\d+) \) ;$", body)
    assert len(boxes) == block_count == 27551
    for x0, y0, x1, y1 in (tuple(map(int, box)) for box in boxes):
        start = max(0, (x0 - left) // pitch)
        end = min(columns, -((left - x1) // pitch))
        low = max(0, (y0 - bottom) // height)
        high = min(len(rows), -((bottom - y1) // height))
        if start < end:
            for row in reserved[low:high]:
                row[start:end] = b"\x01" * (end - start)
    gaps = defaultdict(list)
    for row, status in enumerate(reserved):
        for match in re.finditer(rb"\x00+", status):
            gaps[len(match[0])].append((row, match.start()))
    free_sites = sum(width * len(places) for width, places in gaps.items())
    lengths = sorted(gaps)
    slots = defaultdict(list)
    for width, count in sorted(widths.items(), reverse=True):
        for _ in range(count):
            index = bisect_left(lengths, width)
            assert index < len(lengths), (width, len(slots[width]), count)
            size = lengths[index]
            row, column = gaps[size].pop()
            if not gaps[size]:
                lengths.pop(index)
                del gaps[size]
            if size > width:
                leftover = size - width
                if leftover not in gaps:
                    insort(lengths, leftover)
                gaps[leftover].append((row, column + width))
            slots[width].append((left + column * pitch, rows[row][1], rows[row][2]))
    return slots, free_sites


def morton(x, y):
    """Retain spatial locality when pairing native targets and legal slots."""
    x, y = x // 280, y // 2400
    assert 0 <= x < 8192 and 0 <= y < 8192
    value = 0
    for index in range(13):
        value |= ((x >> index) & 1) << (2 * index)
        value |= ((y >> index) & 1) << (2 * index + 1)
    return value


def write_seed():
    attempt = (WORK / "attempt.def").read_text()
    assert "TRI_ORACLE_GATED_ARRAY_ATTEMPT_SAVED" in (WORK / "attempt.log").read_text()
    region = (WORK / "region.def").read_text()
    count, previous = section(attempt, "COMPONENTS")
    sizes = dimensions([LEF], 2000)
    grouped = defaultdict(list)
    seen = set()
    for line in previous.splitlines():
        match = re.match(r"^- (\S+) (\S+)", line)
        if not match:
            continue
        name, master = match.groups()
        assert name not in seen, name
        seen.add(name)
        width, height = sizes[master]
        assert width % 280 == 0 and height == 2400
        pose = re.search(r"\+ (?:PLACED|FIXED) \( (\d+) (\d+) \)", line)
        x, y = map(int, pose.groups()) if pose else (929980, 751600)
        grouped[width // 280].append((morton(x, y), name, master))
    assert len(seen) == count == read(ARRAY)["clock_gated_mapped_cells"]
    demand = Counter({width: len(cells) for width, cells in grouped.items()})
    sites = sum(width * number for width, number in demand.items())
    assert sites == read(ARRAY)["clock_gated_mapped_sites"]
    slots, free_sites = row_slots(region, demand)

    target = WORK / "seed.def"
    first, _, remainder = region.partition("\nPINS ")
    with target.open("w") as stream:
        stream.write(first + f"\nCOMPONENTS {count} ;\n")
        for width, cells in sorted(grouped.items()):
            coordinates = sorted(slots[width], key=lambda slot: morton(*slot[:2]))
            for (_, name, master), (x, y, side) in zip(sorted(cells), coordinates, strict=True):
                stream.write(f"- {name} {master} + PLACED ( {x} {y} ) {side} ;\n")
        stream.write("END COMPONENTS\n\nPINS " + remainder)
    print(json.dumps({"seeded_cells": count, "available_sites": free_sites, "used_sites": sites,
                      "unused_sites": free_sites - sites, "seed_sha256": digest(target)}, sort_keys=True))


def gates_script(trial=False):
    setup, report = timing_script().split("report_timing -view setup_slow", 1)
    if trial:
        return setup + """read_def $out/region.def
place_design -no_pre_place_opt
write_def $out/attempt.def
check_place > $out/attempt.rpt
puts TRI_ORACLE_GATED_ARRAY_ATTEMPT_SAVED
exit
"""
    return setup + f"""read_def $out/seed.def
set count [llength [get_db insts]]
set pins [llength [get_db ports]]
set blockages [llength [get_db place_blockages]]
if {{$count != 53622 || $pins != 4966 || $blockages != 27551}} {{error "GATED_ARRAY_REGION_IMPORT $count $pins $blockages"}}
check_place > $out/placement.rpt
source $root/{CHECKER}
lassign [tri_oracle_require_clean_placement $out/placement.rpt] placed density
if {{$placed != $count || [llength [get_db insts]] != $count}} {{error "GATED_ARRAY_PLACEMENT_COUNT_CHANGED"}}
puts [list TRI_ORACLE_GATED_ARRAY_PLACED $placed $density]
write_def $out/placed.def
report_timing -view setup_slow""" + report


def bind():
    inputs = {path: digest(path) for path in (ARRAY, REGION, CHECKER)}
    prior = read(REGION)["evidence_sha256"]
    (receipt,) = (Path(name) for name in prior if name.endswith("/single_hold_repair/verified.json"))
    assert digest(receipt) == prior[str(receipt)]
    inputs[receipt] = prior[str(receipt)]
    referenced = read(receipt)["evidence_sha256"]
    (old,) = (Path(name) for name in referenced if name.endswith("/single_hold_repair/physical/tri_oracle_pe_array/native/after.def"))
    assert digest(old) == referenced[str(old)]
    inputs[old] = referenced[str(old)]
    mapped = read(ARRAY)["evidence_sha256"]
    for name in ("netlist.v", "emitted.sdc"):
        path = GATED / name
        assert digest(path) == mapped[str(path)]
        inputs[path] = mapped[str(path)]
    return old, inputs


def prepare():
    old, _ = bind()
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "region.def").write_text(fixture(old.read_text()))
    (WORK / "place.tcl").write_text(gates_script())
    (WORK / "attempt.tcl").write_text(gates_script(trial=True))
    for name in ("netlist.v", "emitted.sdc"):
        selected = (GATED / name).resolve(strict=True)
        path = WORK / name
        if path.is_symlink():
            assert path.resolve(strict=True) == selected
        else:
            path.symlink_to(selected)


def verify():
    old, evidence = bind()
    placed_layout = WORK / "placed.def"
    assert (WORK / "region.def").read_text() == fixture(old.read_text())
    assert (WORK / "place.tcl").read_text() == gates_script()
    for name in ("netlist.v", "emitted.sdc"):
        assert (WORK / name).resolve(strict=True) == (GATED / name).resolve(strict=True)
    console = (WORK / "console.log").read_text()
    cells, density = re.search(r"(?m)^TRI_ORACLE_GATED_ARRAY_PLACED (\d+) ([\d.]+)$", console).groups()
    assert re.search(r"(?m)^TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED$", console)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", console)
    before, after = (geometry(path.read_text()) for path in (WORK / "region.def", placed_layout))
    for section_name in before:
        count, a = before[section_name]
        same_count, b = after[section_name]
        assert count == same_count, section_name
        assert sorted_entries(a, section_name, count) == sorted_entries(b, section_name, same_count), section_name
    assert sum(1 for _ in components(placed_layout)) == int(cells) == read(ARRAY)["clock_gated_mapped_cells"]
    timing = {}
    for mode in ("setup", "hold", "gate_setup", "gate_hold"):
        path = WORK / f"native_{mode}.rpt"
        text = path.read_text()
        if mode.startswith("gate_"):
            assert "Clock Gating " + mode.removeprefix("gate_").title() + " Check" in text, path
        timing[mode] = min(map(float, re.findall(r"Slack:=\s+(-?\d+\.\d+)", text))) * 1000
        evidence[path] = digest(path)
    seed = {name: pose for name, pose in components(WORK / "seed.def")}
    assert seed == dict(components(placed_layout)) and len(seed) == int(cells)
    packing = read(WORK / "seed.json")
    assert packing["seed_sha256"] == digest(WORK / "seed.def") and packing["seeded_cells"] == int(cells)
    assert packing["used_sites"] == read(ARRAY)["clock_gated_mapped_sites"]
    assert packing["unused_sites"] == packing["available_sites"] - packing["used_sites"] > 0
    attempt = (WORK / "attempt.log").read_text()
    unresolved, = re.findall(r"(?m)^\*\*ERROR: \(IMPSP-2021\):\s+Could not legalize <(\d+)> instances", attempt)
    for path in (placed_layout, LEF, *(WORK / name for name in ("region.def", "seed.def", "attempt.def", "attempt.log",
                                                              "seed.json", "place.tcl", "console.log", "placement.rpt")),
                 Path(__file__).resolve().relative_to(ROOT)):
        evidence[path] = digest(path)
    return {"state": "gated_array_legal_in_exact_tight_region", "placed_cells": int(cells),
            "io_pin_locations_preserved": before["PINS"][0], "neighbor_blockages_preserved": before["BLOCKAGES"][0],
            "available_row_sites": packing["available_sites"], "unoccupied_row_sites_after_placement": packing["unused_sites"],
            "default_placement_unlegalized_cells": int(unresolved),
            "reported_placement_density_percent": float(density), "placed_preroute_timing_ps": timing,
            "scope": "One physical array region with the saved pin locations and neighboring cell blockages. "
                     "Pre-route timing uses early wire estimates with ideal clocks. This is a legal geometry "
                     "witness, and timing closure requires physical optimization.",
            "evidence_sha256": {str(path): value for path, value in evidence.items()}}


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "seed", "verify"))
    action = parser.parse_args().action
    if action == "prepare":
        prepare()
    elif action == "seed":
        write_seed()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
