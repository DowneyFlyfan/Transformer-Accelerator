"""Rank legal Booth-array slot swaps on the host graphics processor."""

import argparse
from collections import Counter
from collections import defaultdict
import json
from pathlib import Path
import re

import numpy as np
import torch

from prepare_tri_oracle_gpu_array_placement import assignment, memory_available
from verify_tri_oracle_booth_control_buffers import (
    WORK as BASE,
    LEF,
    components,
    digest,
    dimensions,
    gates_script,
    read,
)
from verify_tri_oracle_gated_array_placement import ROOT, section
from verify_tri_oracle_array_placement_trials import (
    early_congestion,
    pin_and_blockage_identity,
)
from verify_tri_oracle_booth_placement import occupancy
from verify_tri_oracle_booth_array import ARRAY
from verify_tri_oracle_gated_compute_array import timing_script

WORK = BASE / "timing_swaps"
PROOF = Path("records/tri_oracle_booth_control_buffers.json")


def graph_script():
    first = timing_script().split("report_timing -view setup_slow", 1)[0]
    return (
        first
        + r"""read_def $out/graph_input.def
if {[llength [get_db insts]] != 64805 || [llength [get_db ports]] != 4966} {error "BAD_BOOTH_GRAPH_SOURCE"}
report_timing -view setup_slow -from [get_ports {operand_a* operand_b*}] -max_paths 768 -nworst 1 -path_type full_clock > $out/operand_setup.rpt
set output [open $out/edges.tsv w]
set nets 0
set edges 0
foreach net [get_db nets] {
    set drivers [get_db $net .driver_pins.name]
    set driver_ports [get_db $net .driver_ports.name]
    set loads [get_db $net .load_pins.name]
    set load_ports [get_db $net .load_ports.name]
    if {[expr {[llength $drivers] + [llength $driver_ports]}] != 1} {continue}
    set degree [expr {[llength $loads] + [llength $load_ports]}]
    if {$degree == 0 || $degree > 64 || [lindex $driver_ports 0] in {clk rst_n}} {continue}
    set driver [lindex [concat $drivers $driver_ports] 0]
    foreach load [concat $loads $load_ports] {
        puts $output [join [list $driver $load $degree] "\t"]
        incr edges
    }
    incr nets
}
close $output
puts [list BOOTH_TIMING_GRAPH_EXPORTED $nets $edges]
exit
"""
    )


def pinned_sources():
    expected = read(PROOF)["evidence_sha256"]
    for name in ("placed.def", "netlist.v"):
        path = BASE / name
        assert digest(path) == expected[str(path)]
        yield path
    sdc = ARRAY / "emitted.sdc"
    assert (
        digest(sdc)
        == read(Path("records/tri_oracle_booth_array.json"))["evidence_sha256"][
            str(sdc)
        ]
    )
    yield sdc


def prepare_export():
    WORK.mkdir(exist_ok=True)
    assert not (WORK / "placed.def").is_symlink()
    for path in pinned_sources():
        target = WORK / ("graph_input.def" if path.name == "placed.def" else path.name)
        if not target.is_symlink():
            target.symlink_to(path.resolve(strict=True))
        assert target.resolve(strict=True) == path.resolve(strict=True)
    (WORK / "export.tcl").write_text(graph_script())


def graph(known, slots, placed):
    _, pin_text = section(placed, "PINS")
    ports = re.findall(
        r"(?ms)^- (\S+) \+ NET .*?\+ PLACED \( (\d+) (\d+) \) \w+ ;", pin_text
    )
    assert len(ports) == 4966
    coords = [(int(x), int(y)) for _, x, y in ports]
    endpoints = known | {name: len(known) + i for i, (name, _, _) in enumerate(ports)}

    def owner(value):
        value = value.replace("\\", "")
        if value in endpoints:
            return endpoints[value]
        return endpoints.get(value.rsplit("/", 1)[0])

    edges = defaultdict(float)
    count = 0
    with (WORK / "edges.tsv").open() as stream:
        for line in stream:
            driver, sink, fanout = line.rstrip("\n").split("\t")
            a, b = owner(driver), owner(sink)
            assert a is not None and b is not None, (driver, sink)
            count += 1
            if a != b:
                edge = tuple(sorted((a, b)))
                edges[edge] += (2.0 if edge[1] >= len(slots) else 1.0) / int(
                    fanout
                ) ** 0.4
    log = (WORK / "export.log").read_text()
    assert re.search(rf"(?m)^BOOTH_TIMING_GRAPH_EXPORTED \d+ {count}$", log)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", log)
    report = (WORK / "operand_setup.rpt").read_text()
    segments = re.split(r"(?m)^Path \d+: ", report)[1:]
    assert len(segments) == 768
    critical = {}
    for path in segments:
        slack = float(re.search(r"Slack:=\s+(-?\d+\.\d+)", path)[1])
        if slack > -0.3:
            continue
        previous = None
        for row in path.split("Other End Path:")[0].splitlines():
            items = row.split()
            if len(items) != 9 or items[3] not in ("R", "F"):
                continue
            node = owner(items[0])
            if node is not None and previous is not None and node != previous:
                edge = tuple(sorted((node, previous)))
                if edge in edges:
                    weight = (2 + 5 * float(items[-2])) * (1 + abs(slack))
                    critical[edge] = max(critical.get(edge, 0.0), weight)
            previous = node
    assert len(critical) > 500
    for edge, weight in critical.items():
        edges[edge] += weight
    active = np.zeros(len(slots), dtype=bool)
    for edge in critical:
        active[[i for i in edge if i < len(slots)]] = True
    return edges, critical, coords, active


def prepare_swaps():
    assert memory_available() >= 9 * 2**30
    assert torch.cuda.mem_get_info()[0] >= 5 * 2**30
    torch.cuda.set_per_process_memory_fraction(0.12)
    torch.set_num_threads(4)
    sources = list(pinned_sources())
    assert all(
        (WORK / link).resolve(strict=True) == source.resolve(strict=True)
        for link, source in zip(
            ("graph_input.def", "netlist.v", "emitted.sdc"), sources, strict=True
        )
    )
    assert (WORK / "export.tcl").read_text() == graph_script()
    raw = BASE / "placed.def"
    poses = sorted(components(raw))
    known = {
        name.decode().replace("\\", ""): index for index, (name, _) in enumerate(poses)
    }
    assert len(poses) == len(known) == 64805
    sizes = dimensions([LEF], 2000)
    widths = np.array([sizes[pose[0]][0] for _, pose in poses])
    slots = np.array([pose[2:4] for _, pose in poses], dtype=np.int32)
    assert len(set(map(tuple, slots))) == len(poses)
    edges, critical, ports, active = graph(known, slots, raw.read_text())
    print("TIMING_SWAP_INPUT", len(critical), int(active.sum()), len(edges), flush=True)
    assigned, summary = assignment(
        widths,
        slots,
        ports,
        edges,
        critical,
        active_cells=active,
        displacement_penalty=0.55,
    )
    text = raw.read_text()
    start, body = text.split("COMPONENTS ", 1)
    _, end = body.split("END COMPONENTS\n", 1)
    with (WORK / "seed.def").open("w") as out:
        out.write(start + f"COMPONENTS {len(poses)} ;\n")
        for i, (name, pose) in enumerate(poses):
            x, y, side = poses[assigned[i]][1][2:5]
            out.write(f"- {name.decode()} {pose[0]} + PLACED ( {x} {y} ) {side} ;\n")
        out.write("END COMPONENTS\n" + end)
    (WORK / "place.tcl").write_text(
        gates_script().replace("$count != 53622", "$count != 64805")
    )
    summary.update(
        active_cells=int(active.sum()), seed_sha256=digest(WORK / "seed.def")
    )
    (WORK / "assignment.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )


def verify():
    source_layout, netlist, sdc = pinned_sources()
    for name, source in (
        ("graph_input.def", source_layout),
        ("netlist.v", netlist),
        ("emitted.sdc", sdc),
    ):
        assert (WORK / name).resolve(strict=True) == source.resolve(strict=True)
    assert (WORK / "export.tcl").read_text() == graph_script()
    assert (WORK / "place.tcl").read_text() == gates_script().replace(
        "$count != 53622", "$count != 64805"
    )
    log = (WORK / "console.log").read_text()
    assert re.search(r"(?m)^TRI_ORACLE_GATED_ARRAY_PLACED 64805 [0-9.]+$", log)
    assert re.search(r"(?m)^TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED$", log)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", log)
    before = dict(components(source_layout))
    layout = WORK / "placed.def"
    assert not layout.is_symlink()
    after = dict(components(layout))
    assert before.keys() == after.keys()
    assert {key: pose[0] for key, pose in after.items()} == {
        key: pose[0] for key, pose in before.items()
    }
    assert after == dict(components(WORK / "seed.def"))
    sizes = dimensions([LEF], 2000)

    def slots(cells):
        return Counter((sizes[pose[0]], *pose[2:5]) for pose in cells.values())

    assert slots(before) == slots(after)
    assert pin_and_blockage_identity(layout.read_text()) == pin_and_blockage_identity(
        source_layout.read_text()
    )
    region = (BASE.parent / "region.def").resolve().relative_to(ROOT)
    count, used, total = occupancy(region.read_text(), layout)
    assert count == 64805
    baseline = read(PROOF)
    assert total - used == baseline["remaining_row_sites"]
    assignment_record = read(WORK / "assignment.json")
    assert assignment_record["seed_sha256"] == digest(WORK / "seed.def")
    assert assignment_record["moved_cells"] == sum(
        before[name][2:5] != after[name][2:5] for name in before
    )
    reports = [
        WORK / f"native_{name}.rpt"
        for name in ("setup", "hold", "gate_setup", "gate_hold")
    ]
    slack = {
        path.stem.removeprefix("native_"): min(
            map(float, re.findall(r"Slack:=\s+(-?\d+\.\d+)", path.read_text()))
        )
        for path in reports
    }
    assert slack["setup"] > baseline["pre_route_slack_after_ns"]["setup"]
    evidence = [
        PROOF,
        source_layout,
        region,
        netlist,
        sdc,
        LEF,
        layout,
        *reports,
        Path(assignment.__code__.co_filename).resolve().relative_to(ROOT),
        Path(__file__).resolve().relative_to(ROOT),
    ]
    evidence.extend(
        WORK / name
        for name in (
            "export.tcl",
            "export.log",
            "operand_setup.rpt",
            "edges.tsv",
            "seed.def",
            "place.tcl",
            "console.log",
            "placement.rpt",
            "assignment.json",
        )
    )
    return dict(
        state="booth_array_gpu_ranked_slot_swaps_legally_placed",
        clock_megahertz=baseline["clock_megahertz"],
        pre_route_slack_before_ns=baseline["pre_route_slack_after_ns"],
        pre_route_slack_after_ns=slack,
        remaining_row_sites=total - used,
        early_congestion=early_congestion(log),
        assignment=assignment_record,
        scope="Same standard cells and signal connectivity, same occupied site widths and fixed boundary pins. "
        "Native timing uses early wire estimates and an ideal clock.",
        evidence_sha256={str(path): digest(path) for path in evidence},
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("export", "prepare", "verify"))
    action = cli.parse_args().action
    if action == "export":
        prepare_export()
    elif action == "prepare":
        prepare_swaps()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
