"""Try equivalent higher-drive cells on measured Booth multiplier paths."""

from argparse import ArgumentParser
from collections import Counter
import json
from math import isclose
from pathlib import Path
import re

from audit_tri_oracle_booth_operand_spans import CELL, lef_ports
from build_tri_oracle_booth_chip_seed import orient
from link_tri_oracle_indexed_whole_chip import spans
from verify_tri_oracle_array_placement_trials import pin_and_blockage_identity
from verify_tri_oracle_booth8 import simulation
from verify_tri_oracle_booth_placement import (
    LEF,
    components,
    dimensions,
    occupancy,
    row_grid,
)
from verify_tri_oracle_gated_compute_array import PASS, ROOT, digest, read, renamed
from verify_tri_oracle_host_status import arguments
from verify_tri_oracle_sparse_booth_array import checked_region
from verify_tri_oracle_sparse_booth_control_buffers import WORK as SPARSE_CONTROL

BASE = SPARSE_CONTROL / "operand_buffers"
WORK = BASE / "driver_sizing"
PROOF = Path("records/tri_oracle_sparse_booth_operand_buffers.json")
LIBS = [
    LEF.with_name("tcbn28hpcplusbwp12t40p140" + corner + ".lib")
    for corner in ("ssg0p9v125c", "ffg1p05vm40c")
]
POINT = re.compile(
    r"^\s*(product\[\d+\]\.recoded\.signed_multiplier/\w+)/\w+\s+\S+\s+\S+\s+[RF]\s+(\w+)\s+\d+\s+[\d.]+\s+([\d.]+)\s+[\d.]+\s*$",
    re.M,
)
NAMES = re.compile(r"(NR2|ND2|AOI21|AOI22|INR2|AOI211|OAI21|OAI22|INV)D1BWP12T40P140")


def candidates(path):
    result = {}
    for name, master, delay in POINT.findall(path.read_text()):
        if float(delay) >= 0.14 and NAMES.fullmatch(master):
            result[name] = max(result.get(name, 0), float(delay))
    assert result
    return sorted(result, key=lambda name: (-result[name], name))[:18]


def equivalent(sizes, physical_pins, before, after, functions):
    if after not in sizes:
        return False
    assert before in sizes and sizes[before][1] == sizes[after][1]
    same_pin_logic = all(
        cells.get(before) and cells[before] == cells.get(after) for cells in functions
    )
    return same_pin_logic and {
        name: item[0] for name, item in physical_pins[before].items()
    } == {name: item[0] for name, item in physical_pins[after].items()}


def cell_functions(path):
    # This flow permits only the simple logic cells with the same signal pins.
    # Strip formatting while retaining the output function expression.
    chunks = re.split(r'(?m)^\s*cell\s*\(\s*"?(\w+)"?\s*\)\s*\{', path.read_text())
    result = {}
    for name, desc in zip(chunks[1::2], chunks[2::2], strict=True):
        result[name] = tuple(
            "".join(value.split())
            for value in re.findall(r'(?m)^\s*function\s*:\s*"([^"]+)"\s*;', desc)
        )
    assert result
    return result


def quick_budget(layout, region, sizes, selected):
    rows, grid, height = row_grid(region)
    origin, bottom, _, columns, pitch = rows[0]
    names = {
        name.decode().replace("\\", ""): (name, pose)
        for name, pose in components(layout)
    }
    for _, (master, status, x, y, _, _) in names.values():
        width, remainder = divmod(sizes[master][0], pitch)
        j, xr = divmod(x - origin, pitch)
        i, yr = divmod(y - bottom, height)
        assert status == "PLACED" and not (xr or yr or remainder)
        assert 0 <= i < len(rows) and 0 <= j < j + width <= columns
        assert not any(grid[i][j : j + width])
        grid[i][j : j + width] = b"\1" * width
    functions = [cell_functions(path) for path in LIBS]
    pins = lef_ports([LEF])
    edits = {}
    for name in selected:
        raw, (master, _, x, y, side, _) = names[name]
        stronger = master.replace("D1BWP", "D2BWP")
        if not equivalent(sizes, pins, master, stronger, functions):
            continue
        old_width, new_width = (sizes[p][0] // pitch for p in (master, stronger))
        i, j = (y - bottom) // height, (x - origin) // pitch
        grid[i][j : j + old_width] = b"\0" * old_width
        choices = []
        for next_i in range(max(0, i - 15), min(len(rows), i + 16)):
            start, stop = max(0, j - 215), min(columns, j + 216)
            for run in re.finditer(rb"\x00+", grid[next_i][start:stop]):
                if run.end() - run.start() >= new_width:
                    col = min(
                        max(start + run.start(), j), start + run.end() - new_width
                    )
                    distance = abs(next_i - i) * height + abs(col - j) * pitch
                    if distance <= 60000:
                        choices.append((distance, next_i, col))
        if not choices:
            grid[i][j : j + old_width] = b"\1" * old_width
            continue
        _, rr, cc = min(choices)
        assert not any(grid[rr][cc : cc + new_width])
        grid[rr][cc : cc + new_width] = b"\1" * new_width
        layout_side = orient(rows[rr][2].encode(), side.encode()).decode()
        edits[name] = (
            raw,
            master,
            stronger,
            origin + cc * pitch,
            rows[rr][1],
            layout_side,
            new_width - old_width,
        )
    assert edits
    return edits


def mapped_edit(text, edits):
    definitions = spans(text)
    first, last = definitions["tri_oracle_pe_array"]
    children = {
        match[2].removeprefix(b"\\"): match[1].decode()
        for match in CELL.finditer(text, first, last)
    }
    counts = Counter(children.values())
    patches = []
    for path, (_, old, new, *_) in edits.items():
        scope, leaf = path.split("/")
        master = children[scope.encode()]
        assert counts[master] == 1
        start, stop = definitions[master]
        (instance,) = [
            cell
            for cell in CELL.finditer(text, start, stop)
            if cell[2].removeprefix(b"\\") == leaf.encode()
        ]
        assert instance[1].decode() == old
        patches.append((instance.start(1), instance.end(1), new.encode()))
    for lo, hi, new in sorted(patches, reverse=True):
        text = text[:lo] + new + text[hi:]
    return text


def prepared():
    proof = read(PROOF)["evidence_sha256"]
    for name in ("placed.def", "netlist.v", "place.tcl", "native_setup.rpt"):
        path = BASE / name
        assert digest(path) == proof[str(path)]
    region = checked_region()
    edits = quick_budget(
        BASE / "placed.def",
        region.read_text(),
        dimensions([LEF], 2000),
        candidates(BASE / "native_setup.rpt"),
    )
    original = (BASE / "placed.def").read_bytes()
    layout = {}
    for raw, old, new, x, y, side, _ in edits.values():
        pattern = re.compile(
            rb"(?m)^- "
            + re.escape(raw)
            + rb" "
            + old.encode()
            + rb" \+ PLACED \( \d+ \d+ \) \w+\b"
        )
        (found,) = pattern.finditer(original)
        layout[found.span()] = b"- %s %s + PLACED ( %d %d ) %s" % (
            raw,
            new.encode(),
            x,
            y,
            side.encode(),
        )
    for (lo, hi), value in sorted(layout.items(), reverse=True):
        original = original[:lo] + value + original[hi:]
    return edits, original, mapped_edit((BASE / "netlist.v").read_bytes(), edits)


def prepare():
    edits, seed, netlist = prepared()
    (WORK / "seed.def").write_bytes(seed)
    (WORK / "netlist.v").write_bytes(netlist)
    (WORK / "place.tcl").write_bytes((BASE / "place.tcl").read_bytes())
    if not (WORK / "emitted.sdc").is_symlink():
        (WORK / "emitted.sdc").symlink_to((BASE / "emitted.sdc").resolve(strict=True))
    run = WORK / "replay"
    dut = run / "decoupled_mapped.v"
    dut.write_text(renamed(netlist.decode()))
    argv = arguments(BASE / "replay/xrun.history")
    argv[argv.index(str((BASE / "replay/decoupled_mapped.v").resolve()))] = str(
        dut.resolve()
    )
    (run / "args.json").write_text(json.dumps(argv))
    print(
        "ARRAY_DRIVER_SIZING_TRIAL",
        len(edits),
        sum(info[-1] for info in edits.values()),
        flush=True,
    )


def verify():
    edits, seed, netlist = prepared()
    assert (WORK / "seed.def").read_bytes() == seed and (
        WORK / "netlist.v"
    ).read_bytes() == netlist
    assert (WORK / "place.tcl").read_bytes() == (BASE / "place.tcl").read_bytes()
    assert digest(WORK / "emitted.sdc") == digest(BASE / "emitted.sdc")
    target = Path("records/paper_result_targets.json")
    frequency = read(target)["peak"]["clock_megahertz"]
    (period,) = re.findall(
        r'(?m)^create_clock -name "core" -period ([\d.]+)',
        (WORK / "emitted.sdc").read_text(),
    )
    assert isclose(float(period), 1000 / frequency, abs_tol=1e-5)
    raw = dict(components(BASE / "placed.def"))
    placed = WORK / "placed.def"
    changed = dict(components(placed))
    assert changed == dict(components(WORK / "seed.def"))
    assert set(raw) == set(changed)
    assert {name for name in raw if raw[name] != changed[name]} == {
        item[0] for item in edits.values()
    }
    assert pin_and_blockage_identity(placed.read_text()) == pin_and_blockage_identity(
        (BASE / "placed.def").read_text()
    )
    region = checked_region().read_text()
    count, total, _ = occupancy(region, placed)
    old_count, previous, _ = occupancy(region, BASE / "placed.def")
    sites = sum(info[-1] for info in edits.values())
    assert count == old_count and total - previous == sites
    log = (WORK / "console.log").read_text()
    assert re.search(r"(?m)^TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED$", log)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", log)
    run = WORK / "replay"
    dut = run / "decoupled_mapped.v"
    assert dut.read_text() == renamed(netlist.decode())
    assert arguments(run / "xrun.history") == read(run / "args.json")
    sims = simulation(run, PASS, [dut], "decoupled_lockstep_tb")
    reports = {
        mode: WORK / f"native_{mode}.rpt"
        for mode in ("setup", "hold", "gate_setup", "gate_hold")
    }
    values = {
        mode: min(map(float, re.findall(r"Slack:=\s+(-?\d+\.\d+)", file.read_text())))
        for mode, file in reports.items()
    }
    facts = read(PROOF)["after_slack_ns"]
    evidence = [
        PROOF,
        target,
        *LIBS,
        LEF,
        *sims,
        *reports.values(),
        dut,
        Path(__file__).resolve().relative_to(ROOT),
        *[
            WORK / name
            for name in (
                "console.log",
                "place.tcl",
                "emitted.sdc",
                "netlist.v",
                "seed.def",
                "placed.def",
            )
        ],
    ]
    return dict(
        state="targeted_sparse_array_driver_sizing_measured",
        moves=len(edits),
        clock_megahertz=frequency,
        added_sites=sites,
        delivered_lockstep_transactions=786,
        before_slack_ns=facts,
        worst_setup_change_ns=round(values["setup"] - facts["setup"], 3),
        after_slack_ns=values,
        scope="Equivalent combinational drive variants on one array, with the original timing and physical boundary. Early wire estimates and ideal clocks are used.",
        evidence_sha256={str(path): digest(path) for path in evidence},
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    if parser.parse_args().action == "prepare":
        prepare()
    else:
        print(json.dumps(verify(), sort_keys=True, indent=2))
