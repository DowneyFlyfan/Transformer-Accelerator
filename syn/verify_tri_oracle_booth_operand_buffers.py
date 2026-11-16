"""Place repeaters on the slowest mapped Booth operand inputs."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median_low
import json
import re

from link_tri_oracle_indexed_whole_chip import spans
from verify_tri_oracle_array_placement_trials import pin_and_blockage_identity
from verify_tri_oracle_booth8 import simulation
from verify_tri_oracle_booth_control_buffers import WORK as CONTROL_BUFFERS
from verify_tri_oracle_booth_placement import (
    LEF,
    components,
    digest,
    dimensions,
    occupancy,
    read,
    row_grid,
)
from verify_tri_oracle_gated_array_placement import section
from verify_tri_oracle_gated_compute_array import PASS, ROOT, renamed
from verify_tri_oracle_host_status import arguments

WORK = CONTROL_BUFFERS / "operand_buffers"
BASE = WORK.parent / "timing_swaps"
PROOF = Path("records/tri_oracle_booth_timing_swaps.json")
BUDGET = Path("records/tri_oracle_booth_chip_geometry.json")
BUFFER = "BUFFD8BWP12T40P140"
LIMIT = 64
PATH_PIN = re.compile(r"(?m)^\s+Startpoint: \([RF]\) (operand_[ab]\[\d+\])$")
BOUNDARY = re.compile(
    r"(?ms)^- (operand_[ab]\[\d+\]) \+ NET .*?\+ PLACED \( (\d+) (\d+) \) \w+ ;"
)
SLACK = re.compile(r"Slack:=\s+(-?\d+\.\d+)")


def sources():
    proof = read(PROOF)["evidence_sha256"]
    inputs = {key.rsplit("/", 1)[-1]: Path(key) for key in proof}
    inputs["netlist.v"] = WORK.parent / "netlist.v"
    for name in (
        "placed.def",
        "netlist.v",
        "emitted.sdc",
        "edges.tsv",
        "operand_setup.rpt",
        "native_setup.rpt",
        "place.tcl",
        "region.def",
    ):
        path = (
            BASE / name
            if name in ("placed.def", "place.tcl", "native_setup.rpt")
            else inputs[name]
        )
        assert digest(path) == proof[str(path)]
        yield name, path


def slow_operands(bindings):
    slacks = {}
    for report in ("native_setup.rpt", "operand_setup.rpt"):
        for path in re.split(r"(?m)^Path \d+: ", bindings[report].read_text())[1:]:
            match = PATH_PIN.search(path)
            if match:
                name = match[1]
                slack = float(SLACK.search(path)[1])
                slacks[name] = min(slack, slacks.get(name, 0))
    chosen = sorted(slacks, key=lambda name: (slacks[name], name))[:LIMIT]
    assert len(chosen) == LIMIT and max(slacks[name] for name in chosen) < 0
    return chosen


def buffers(bindings, layout, poses):
    _, pins = section(layout, "PINS")
    locations = {name: (int(x), int(y)) for name, x, y in BOUNDARY.findall(pins)}
    assert len(locations) == 4096
    chosen = slow_operands(bindings)
    loads = defaultdict(list)
    with bindings["edges.tsv"].open() as edges:
        for line in edges:
            driver, sink, _ = line.rstrip().split("\t")
            if driver in locations and driver in chosen:
                owner, _, _ = sink.rpartition("/")
                match = re.fullmatch(r"operand_[ab]\[(\d+)\]", driver)
                assert owner.startswith(
                    f"product[{int(match[1]) // 8}].recoded.signed_multiplier/"
                )
                loads[driver].append(poses[owner.encode()][2:4])
    assert loads.keys() == set(chosen)

    rows, used, height = row_grid(bindings["region.def"].read_text())
    left, bottom, _, cols, pitch = rows[0]
    widths = dimensions([LEF], 2000)
    width = widths[BUFFER][0] // pitch
    assert widths[BUFFER] == (width * pitch, height)
    for master, status, x, y, _, _ in poses.values():
        length, remainder = divmod(widths[master][0], pitch)
        col, dx = divmod(x - left, pitch)
        row, dy = divmod(y - bottom, height)
        assert status == "PLACED" and not any((dx, dy, remainder))
        assert 0 <= row < len(rows) and 0 <= col < col + length <= cols
        assert not any(used[row][col : col + length])
        used[row][col : col + length] = b"\x01" * length
    gaps = [
        (row, slot.start(), slot.end())
        for row, line in enumerate(used)
        for slot in re.finditer(rb"\x00+", line)
        if slot.end() - slot.start() >= width
    ]
    sites = {}
    for name in chosen:
        pin_x, pin_y = locations[name]
        x = (pin_x + median_low([point[0] for point in loads[name]])) // 2
        y = (pin_y + median_low([point[1] for point in loads[name]])) // 2
        ideal = round((x - left) / pitch)
        options = []
        for index, (row, first, last) in enumerate(gaps):
            col = min(max(ideal, first), last - width)
            options.append(
                (abs(left + col * pitch - x) + abs(rows[row][1] - y), index, col)
            )
        _, index, col = min(options)
        row, first, last = gaps.pop(index)
        gaps.extend(
            (row, a, b)
            for a, b in ((first, col), (col + width, last))
            if b - a >= width
        )
        sites[name] = (left + col * pitch, rows[row][1], rows[row][2])
    return sites, width


def edit(source, wires):
    begin, end = spans(source.encode())["tri_oracle_pe_array"]
    text = source[begin:end]
    used = Counter()

    def connect(match):
        port, name, hi, lo = match.groups()
        bits = [f"{name}[{i}]" for i in range(int(hi), int(lo) - 1, -1)]
        assert len(bits) == 8 and port[-1] == name[-1]
        new = [wires.get(bit, bit) for bit in bits]
        used.update(bit for bit in bits if bit in wires)
        return f".{port} ({{{', '.join(new)}}})" if new != bits else match[0]

    text, count = re.subn(
        r"\.([ab])\s*\((operand_[ab])\[(\d+):(\d+)\]\)", connect, text
    )
    assert count == 512 and used == Counter(wires.keys())
    declaration = text.index(");") + 2
    wires_text = "".join(f"  wire {net};\n" for net in wires.values())
    text = text[:declaration] + "\n" + wires_text + text[declaration:]
    extra = "".join(
        f"  {BUFFER} {net}_cell (.I({signal}), .Z({net}));\n"
        for signal, net in wires.items()
    )
    assert "tri_operand_buffer_" not in source
    return (
        source[:begin]
        + text.removesuffix("endmodule")
        + extra
        + "endmodule"
        + source[end:]
    )


def prepare():
    bindings = dict(sources())
    placed = bindings["placed.def"]
    layout = placed.read_text()
    poses = {name.replace(b"\\", b""): pose for name, pose in components(placed)}
    assert len(poses) == 64805
    sites, width = buffers(bindings, layout, poses)
    assert len(sites) * width < min(
        read(BUDGET)["row_sites_free_by_array_region"].values()
    )
    wires = {name: f"tri_operand_buffer_{i}" for i, name in enumerate(sites)}
    netlist = edit(bindings["netlist.v"].read_text(), wires)
    lines = "".join(
        f"- {wires[name]}_cell {BUFFER} + PLACED ( {x} {y} ) {side} ;\n"
        for name, (x, y, side) in sites.items()
    )
    updated = len(poses) + len(sites)
    layout = layout.replace(f"COMPONENTS {len(poses)} ;", f"COMPONENTS {updated} ;", 1)
    layout = layout.replace("END COMPONENTS\n", lines + "END COMPONENTS\n", 1)
    script = (
        bindings["place.tcl"]
        .read_text()
        .replace("$count != 64805", f"$count != {updated}")
    )
    assert f"$count != {updated}" in script
    for name, content in (
        ("netlist.v", netlist),
        ("seed.def", layout),
        ("place.tcl", script),
    ):
        (WORK / name).write_text(content)
    sdc = WORK / "emitted.sdc"
    if not sdc.is_symlink():
        sdc.symlink_to(bindings["emitted.sdc"].resolve(strict=True))
    assert digest(sdc) == digest(bindings["emitted.sdc"])
    replay_output = WORK / "replay"
    replay_output.mkdir(exist_ok=True)
    replay_netlist = (replay_output / "decoupled_mapped.v").resolve()
    replay_netlist.write_text(renamed(netlist))
    earlier = WORK.parent / "replay/decoupled_mapped.v"
    script_args = arguments(earlier.parent / "xrun.history")
    script_args[script_args.index(str(earlier.resolve()))] = str(replay_netlist)
    (replay_output / "args.json").write_text(json.dumps(script_args))
    return bindings, sites, width


def verify():
    bindings = dict(sources())
    outputs = {
        name: WORK / name
        for name in (
            "console.log",
            "placed.def",
            "seed.def",
            "netlist.v",
            "placement.rpt",
        )
    }
    console = outputs["console.log"].read_text()
    assert re.search(r"(?m)^TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED$", console)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", console)
    after = dict(components(outputs["placed.def"]))
    before = dict(components(bindings["placed.def"]))
    assert dict(components(outputs["seed.def"])) == after
    assert all(after[name] == pose for name, pose in before.items())
    assert pin_and_blockage_identity(
        outputs["placed.def"].read_text()
    ) == pin_and_blockage_identity(bindings["placed.def"].read_text())
    region = bindings["region.def"].read_text()
    count, used, capacity = occupancy(region, outputs["placed.def"])
    _, was_used, was_capacity = occupancy(region, bindings["placed.def"])
    assert count == 64805 + LIMIT and capacity == was_capacity
    buffer_sites = used - was_used
    assert buffer_sites > 0 and buffer_sites < min(
        read(BUDGET)["row_sites_free_by_array_region"].values()
    )
    replay = WORK / "replay"
    dut = replay / "decoupled_mapped.v"
    wires = {
        name: f"tri_operand_buffer_{i}"
        for i, name in enumerate(slow_operands(bindings))
    }
    assert outputs["netlist.v"].read_text() == edit(
        bindings["netlist.v"].read_text(), wires
    )
    assert dut.read_text() == renamed(outputs["netlist.v"].read_text())
    assert arguments(replay / "xrun.history") == read(replay / "args.json")
    logs = simulation(replay, PASS, [dut], "decoupled_lockstep_tb")
    reports = {
        name: WORK / f"native_{name}.rpt"
        for name in ("setup", "hold", "gate_setup", "gate_hold")
    }
    timing = {
        name: min(map(float, SLACK.findall(path.read_text())))
        for name, path in reports.items()
    }
    base = read(PROOF)["pre_route_slack_after_ns"]
    evidence = [
        *bindings.values(),
        *outputs.values(),
        *reports.values(),
        *logs,
        PROOF,
        BUDGET,
        dut,
        WORK / "place.tcl",
        Path(__file__).resolve().relative_to(ROOT),
    ]
    return {
        "state": "targeted_booth_operand_buffers_placed_and_lockstep_tested",
        "clock_megahertz": 580,
        "added_buffers": LIMIT,
        "added_sites": buffer_sites,
        "delivered_lockstep_transactions": 786,
        "before_slack_ns": base,
        "after_slack_ns": timing,
        "setup_change_ns": round(timing["setup"] - base["setup"], 3),
        "scope": "One compute array with fixed boundary pins and unchanged original cell locations. Timing uses ideal clocks and pre-route wire estimates.",
        "evidence_sha256": {str(path): digest(path) for path in evidence},
    }


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    if parser.parse_args().action == "prepare":
        prepare()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
