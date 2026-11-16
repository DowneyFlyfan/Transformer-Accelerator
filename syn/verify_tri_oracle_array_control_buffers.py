"""Place bounded data fanout trees in the saved compute-array region."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from statistics import median_low
import subprocess

from link_tri_oracle_indexed_whole_chip import spans
from verify_tri_oracle_gated_array_placement import (
    ARRAY, LEF, WORK as PLACED, dimensions, gates_script, geometry, morton, row_grid, section, sorted_entries,
)
from verify_tri_oracle_gated_compute_array import PASS, ROOT, WORK as MAPPED, digest, read, renamed
from verify_tri_oracle_host_status import arguments
from verify_tri_oracle_pad_cold_reload import components


WORK = PLACED / "control_buffers"
PROOF = Path("records/tri_oracle_gated_array_placement.json")
TOP = "tri_oracle_pe_array"
BUFFER = "BUFFD8BWP12T40P140"
BRANCHES = {"g620956": ("Z", 608), "g620406": ("Z", 608), "g620957": ("Z", 608),
            "hi_fo_buf621057": ("ZN", 353), "occupancy_onehot_reg[0]": ("Q", 257)}
TERMINAL = re.compile(r"\.(\w+)\s*\(\s*(\w+(?:\[\d+\])?)\s*\)")
INSTANCE = re.compile(r"(?m)^ +\w+\s+(\\\S+|\w+)\s*\(([^;]+)\);")


def lookup_sources():
    prior = read(PROOF)["evidence_sha256"]
    mapped = read(ARRAY)["evidence_sha256"]
    inputs = [PROOF, ARRAY, LEF, PLACED / "placed.def", PLACED / "region.def", MAPPED / "netlist.v", MAPPED / "emitted.sdc"]
    for path in inputs[2:]:
        assert digest(path) == (prior | mapped)[str(path)], path
    return inputs


def edit(source, locations, allocate):
    first, last = spans(source.encode())[TOP]
    assert len(source) == len(source.encode())
    body = source[first:last]
    insts = {item[1].removeprefix("\\"): item for item in INSTANCE.finditer(body)}
    assert set(BRANCHES) <= insts.keys()
    drivers = {}
    for name, (output, _) in BRANCHES.items():
        net = dict(TERMINAL.findall(insts[name][2]))[output]
        assert net not in drivers
        drivers[net] = name, output
    assert set(drivers) == {"n_2289", "n_2290", "n_2293", "n_2281", "occupancy_onehot[0]"}

    loads = defaultdict(list)
    for name, item in insts.items():
        for port in TERMINAL.finditer(item[2]):
            pin, net = port.groups()
            if net in drivers and (name, pin) != drivers[net]:
                assert not pin.startswith("Z") and pin not in ("Q", "QN", "CP", "CPN", "CLK"), (net, name, pin)
                x, y = locations[name][2:4]
                loads[net].append((morton(x, y), x, y, item.start(2) + port.start(2), item.start(2) + port.end(2)))

    buffers = []
    replacements = []

    def buffer(input_net, points):
        name = f"tri_buffer_{len(buffers)}"
        output_net = name + "_net"
        x, y, side = allocate(median_low([a for a, _ in points]), median_low([b for _, b in points]))
        buffers.append((name, input_net, output_net, x, y, side))
        return output_net

    for net, instances in sorted(loads.items()):
        assert len(instances) == BRANCHES[drivers[net][0]][1], (net, len(instances))
        ordered = sorted(instances)
        for first_leaf in range(0, len(ordered), 128):
            group = ordered[first_leaf:first_leaf + 128]
            trunk = buffer(net, [(x, y) for _, x, y, _, _ in group])
            for index in range(0, len(group), 16):
                leaves = group[index:index + 16]
                output = buffer(trunk, [(x, y) for _, x, y, _, _ in leaves])
                replacements.extend((a, b, output) for _, _, _, a, b in leaves)
    assert len(replacements) == sum(count for _, count in BRANCHES.values())
    for a, b, new in sorted(replacements, reverse=True):
        assert body[a:b] in drivers
        body = body[:a] + new + body[b:]
    anchor = min(item.start() for item in insts.values())
    declarations = "".join(f"  wire {out};\n" for _, _, out, *_ in buffers)
    additions = "".join(f"  {BUFFER} {name} (.I({inp}), .Z({out}));\n" for name, inp, out, *_ in buffers)
    body = body[:anchor] + declarations + body[anchor:]
    return source[:first] + body.removesuffix("endmodule") + additions + "endmodule" + source[last:], buffers


def prepared():
    _, _, _, layout, region, netlist, _ = lookup_sources()
    old = layout.read_text()
    poses = dict(components(layout))
    locations = {name.decode().replace("\\", ""): pose for name, pose in poses.items()}
    assert len(locations) == len(poses) == 53622
    rows, occupied, height = row_grid(region.read_text())
    left, bottom, _, _, pitch = rows[0]
    sizes = dimensions([LEF], 2000)
    for master, status, x, y, side, _ in locations.values():
        width, cell_height = sizes[master]
        row = (y - bottom) // height
        col = (x - left) // pitch
        span = width // pitch
        assert status == "PLACED" and side == rows[row][2] and cell_height == height
        assert y == rows[row][1] and width % pitch == (x - left) % pitch == 0
        assert 0 <= col < col + span <= len(occupied[row]) and not any(occupied[row][col:col + span])
        occupied[row][col:col + span] = b"\x01" * span
    gaps = [(row, match.start(), match.end()) for row, bits in enumerate(occupied)
            for match in re.finditer(rb"\x00+", bits)]
    assert sum(stop - start for _, start, stop in gaps) == read(PROOF)["unoccupied_row_sites_after_placement"]
    width = sizes[BUFFER][0] // pitch
    assert sizes[BUFFER] == (width * pitch, height)

    def allocate(tx, ty):
        desired = round((tx - left) / pitch)
        choices = []
        for idx, (row, start, stop) in enumerate(gaps):
            if stop - start >= width:
                col = min(max(start, desired), stop - width)
                distance = abs(left + col * pitch - tx) + abs(rows[row][1] - ty)
                choices.append((distance, stop - start, idx, col))
        _, _, chosen, col = min(choices)
        row, start, stop = gaps.pop(chosen)
        gaps.extend((row, a, b) for a, b in ((start, col), (col + width, stop)) if a < b)
        return left + col * pitch, rows[row][1], rows[row][2]

    mapped, buffers = edit(netlist.read_text(), locations, allocate)
    seed = old.replace(f"COMPONENTS {len(poses)} ;\n", f"COMPONENTS {len(poses) + len(buffers)} ;\n", 1)
    new_cells = "".join(f"- {name} {BUFFER} + PLACED ( {x} {y} ) {side} ;\n" for name, _, _, x, y, side in buffers)
    seed = seed.replace("END COMPONENTS\n", new_cells + "END COMPONENTS\n", 1)
    script = gates_script().replace("$count != 53622", f"$count != {len(poses) + len(buffers)}")
    return mapped, seed, script, len(buffers), width * len(buffers)


def prepare():
    WORK.mkdir(parents=True, exist_ok=True)
    mapped, seed, script, _, _ = prepared()
    for name, text in (("netlist.v", mapped), ("seed.def", seed), ("place.tcl", script)):
        (WORK / name).write_text(text)
    sdc = WORK / "emitted.sdc"
    if not sdc.is_symlink():
        sdc.symlink_to((MAPPED / "emitted.sdc").resolve(strict=True))


def replay():
    run = WORK / "replay"
    run.mkdir(exist_ok=True)
    candidate = run / "decoupled_mapped.v"
    candidate.write_text(renamed((WORK / "netlist.v").read_text()))
    old = MAPPED / "replay/decoupled_mapped.v"
    argv = arguments(MAPPED / "replay/xrun.history")
    argv[argv.index(str(old.resolve()))] = str(candidate.resolve())
    command = ["docker", "exec", "-w", str(run.resolve()), "tri-oracle-eda", "/opt/cadence/bin/xrun", *argv]
    with (run / "console.log").open("w") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)


def verify():
    mapped, seed, script, buffers, added_sites = prepared()
    for name, text in (("netlist.v", mapped), ("seed.def", seed), ("place.tcl", script)):
        assert (WORK / name).read_text() == text
    console = (WORK / "console.log").read_text()
    assert "TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED" in console
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", console)
    placed = WORK / "placed.def"
    for kind, (count, before) in geometry(seed).items():
        new_count, after = section(placed.read_text(), kind)
        assert count == new_count and sorted_entries(before, kind, count) == sorted_entries(after, kind, count)
    assert dict(components(placed)) == dict(components(WORK / "seed.def"))
    assert (WORK / "emitted.sdc").resolve() == (MAPPED / "emitted.sdc").resolve()
    log = (WORK / "replay/console.log").read_text()
    assert log.splitlines().count(PASS) == log.count("Simulation complete via $finish(1)") == 1
    assert not re.search(r"\*[EF],", log)
    assert (WORK / "replay/decoupled_mapped.v").read_text() == renamed(mapped)
    assert str((WORK / "replay/decoupled_mapped.v").resolve()) in arguments(WORK / "replay/xrun.history")
    reports = [WORK / f"native_{mode}.rpt" for mode in ("setup", "hold", "gate_setup", "gate_hold")]
    timing = {path.stem.removeprefix("native_"): round(1000 * min(map(float, re.findall(r"Slack:=\s+(-?\d+\.\d+)", path.read_text()))), 6)
              for path in reports}
    evidence = [*lookup_sources(), Path(__file__).resolve().relative_to(ROOT), *reports, placed]
    evidence.extend(WORK / name for name in ("netlist.v", "place.tcl", "seed.def", "console.log", "placement.rpt",
                                            "replay/console.log", "replay/xrun.history", "replay/decoupled_mapped.v"))
    before = read(PROOF)
    original_deficit = -read(ARRAY)["remaining_geometric_site_margin_with_receiver_and_array_replacements"]
    return {"state": "data_fanout_buffer_trees_placed_and_lockstep_verified", "added_buffers": buffers,
            "added_row_sites": added_sites, "remaining_array_row_sites": before["unoccupied_row_sites_after_placement"] - added_sites,
            "projected_chip_site_deficit_if_repeated_across_twenty_arrays": original_deficit + 20 * added_sites,
            "original_data_load_counts": {name: count for name, (_, count) in BRANCHES.items()},
            "placement_timing_before_ps": before["placed_preroute_timing_ps"], "placement_timing_after_ps": timing,
            "scope": "Five data-control nets buffered without moving existing cells. One array replayed 786 "
                     "transactions. Timing uses estimated wires and an ideal clock in the same region.",
            "evidence_sha256": {str(path): digest(path) for path in evidence}}


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "replay", "verify"))
    action = parser.parse_args().action
    if action == "prepare":
        prepare()
    elif action == "replay":
        replay()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
