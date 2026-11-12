"""Check the inherited memory-macro coordinates and bind them to the linked chip."""

import argparse
from collections import Counter
from decimal import Decimal
from itertools import combinations
import json
from pathlib import Path
import re
import resource

from audit_linked_layer_memory import inventory
from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from prepare_tri_oracle_parallel_chip_synthesis import BASE, pin, read, verify
from run_tri_oracle_parallel_chip_synthesis import wait_for_receipt
from verify_tri_oracle_packed_down_weights import ROOT


PHYSICAL = ROOT / ".cache/physical"
REFERENCE = PHYSICAL / "context_external/shared_decoder"
MM2 = Decimal(10**6)


def footprint(text):
    master, = re.findall(r"(?m)^\s*MACRO\s+(\w+)\s*$", text)
    origin, = re.findall(r"(?m)^\s*ORIGIN\s+(\S+)\s+(\S+)\s*;", text)
    size, = re.findall(r"(?m)^\s*SIZE\s+(\S+)\s+BY\s+(\S+)\s*;", text)
    assert tuple(map(Decimal, origin)) == (0, 0), master
    width, height = map(Decimal, size)
    assert width > 0 and height > 0, master
    return master, (width, height)


def check_geometry(seed, dimensions, paper_outline, grid):
    die_x, die_y = map(Decimal, seed["die_um"])
    margin, halo = map(Decimal, (seed["core_margin_um"], seed["halo_um"]))
    assert (die_x, die_y) == paper_outline
    assert Decimal(seed["manufacturing_grid_um"]) == grid > 0
    assert 0 < halo <= margin and 2 * margin < min(die_x, die_y)
    boxes = {}
    footprint_area = halo_area = Decimal(0)
    for path, pose in seed["placements"].items():
        x, y = map(Decimal, (pose["x_um"], pose["y_um"]))
        width, height = dimensions[pose["master"]]
        assert pose["orientation"] == "r0" and x % grid == y % grid == 0, path
        box = (x - halo, y - halo, x + width + halo, y + height + halo)
        assert margin <= box[0] < box[2] <= die_x - margin, path
        assert margin <= box[1] < box[3] <= die_y - margin, path
        boxes[path] = box
        footprint_area += width * height
        halo_area += (box[2] - box[0]) * (box[3] - box[1])
    for (left, a), (right, b) in combinations(boxes.items(), 2):
        assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (left, right)
    core_area = (die_x - 2 * margin) * (die_y - 2 * margin)
    assert footprint_area < halo_area < core_area
    return {"macro_area_mm2": str(footprint_area / MM2), "macro_and_halo_area_mm2": str(halo_area / MM2),
            "core_area_outside_macro_halos_mm2": str((core_area - halo_area) / MM2)}


def run(synthesis, output, mapped):
    pins = {}
    recorded = ROOT / "records/wac_corrected_context_decoder_native_result.json"
    baseline = read(recorded)
    pin(pins, recorded)
    pin(pins, ROOT / PAPER_RELATIVE, PAPER_SHA256)
    memory = REFERENCE / "linked_context_replay_complete_attention_serial/memory_receipt.json"
    pin(pins, memory, baseline["evidence_sha256"][str(memory.relative_to(ROOT))])
    census = read(memory)
    assert census["candidate_netlist_sha256"] == baseline["candidate_netlist_sha256"]
    paper = ROOT / "records/paper_result_targets.json"
    pin(pins, paper, census["input_sha256"][str(paper)])
    target = read(paper)["silicon"]
    outline = tuple(1000 * Decimal(str(size)) for size in target["die_dimensions_mm"])

    inputs = PHYSICAL / "shared_memory_layer_boundary/physical_inputs/receipt.json"
    seed_file = inputs.with_name("macro_seed.json")
    pin(pins, inputs)
    old = read(inputs)
    assert old["state"] == "shared_memory_layer_physical_inputs_statically_verified"
    pin(pins, seed_file, old["output_sha256"][str(seed_file)])
    seed = read(seed_file)
    seed["placements"] = {"layer." + name: location for name, location in seed["placements"].items()}
    expected = {name: location["master"] for name, location in seed["placements"].items()}
    counts = Counter(expected.values())
    assert len(expected) == census["compiled_instances"] == old["preserved_macro_locations"] == 623
    assert counts == {master: item["instances"] for master, item in census["by_master"].items()}

    views_file = PHYSICAL / "wac_budgeted_parent_boundary/linked_tsmc_physical_views.json"
    views = read(views_file)
    pin(pins, views_file)
    tech, _, *macros = views["physical_abstracts"]
    for name in (tech, *macros):
        pin(pins, ROOT / name, views["evidence_sha256"][name])
    grid, = re.findall(r"(?m)^\s*MANUFACTURINGGRID\s+(\S+)\s*;", (ROOT / tech).read_text())
    dimensions = dict(footprint((ROOT / name).read_text()) for name in macros)
    assert len(dimensions) == len(macros) and dimensions.keys() == counts.keys()
    geometry = check_geometry(seed, dimensions, outline, Decimal(grid))

    reference_netlist = REFERENCE / "linked_context_decoder_complete_attention/candidate.v"
    reference_link = reference_netlist.with_name("receipt.json")
    pin(pins, reference_netlist, baseline["candidate_netlist_sha256"])
    pin(pins, reference_link, census["input_sha256"][str(reference_link)])
    reference_paths = inventory(reference_netlist.read_text(), read(reference_link)["top"])
    assert expected == {"layer." + name: master for name, master in reference_paths.items()}
    report = {"state": "parallel_chip_macro_outline_preflight", "die_um": seed["die_um"],
              "compiled_memory_instances": len(expected), "macros_by_master": dict(counts), **geometry}
    if mapped:
        link = synthesis / "linked_chip/receipt.json"
        proof = read(link)
        assert proof["state"] == "parallel_chip_parent_linked_with_verified_mapped_imports"
        assert proof["compiled_memories"] == counts
        netlist = link.with_name("chip.v")
        pin(pins, link)
        pin(pins, netlist, proof["chip_sha256"])
        actual = inventory(netlist.read_text(), proof["top"])
        assert actual == expected, (sorted(expected.keys() - actual.keys())[:8],
                                    sorted(actual.keys() - expected.keys())[:8],
                                    sorted(path for path in actual.keys() & expected.keys()
                                           if actual[path] != expected[path])[:8])
        seed["linked_netlist_sha256"] = proof["chip_sha256"]
        report.update(state="linked_parallel_chip_macro_seed_verified", candidate_sha256=proof["chip_sha256"])

    pin(pins, Path(__file__).resolve())
    pin(pins, Path(inventory.__code__.co_filename).resolve())
    verify(pins)
    output.mkdir()
    if mapped:
        bound = output / "macro_seed.json"
        bound.write_text(json.dumps(seed, indent=2) + "\n")
        report["output_sha256"] = {}
        pin(report["output_sha256"], bound)
    report["input_sha256"] = pins
    (output / "receipt.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report["state"], len(expected), geometry, flush=True)


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (2**31, 2**31))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    parser.add_argument("--synthesis", type=lambda value: Path(value).resolve(), default=BASE / "parallel_synthesis")
    parser.add_argument("--mapped", action="store_true")
    parser.add_argument("--link-worker", type=int)
    args = parser.parse_args()
    if args.link_worker is not None:
        assert args.mapped
        wait_for_receipt(args.synthesis / "linked_chip/receipt.json", args.link_worker, "link_tri_oracle_parallel_chip.py")
    run(args.synthesis, args.output, args.mapped)
