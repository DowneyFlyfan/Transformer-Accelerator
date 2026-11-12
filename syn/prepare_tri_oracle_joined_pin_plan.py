"""Check boundary pin capacity on the joined design's paper-sized outline."""

import argparse
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import json
from pathlib import Path
import re

from prepare_tri_oracle_joined_decoder_candidate import ROOT, read
from prepare_tri_oracle_joined_macro_outline import VIEWS
from prepare_tri_oracle_parallel_chip_synthesis import TOP, pin, verify
from prepare_tri_oracle_parallel_pin_constraints import port_bits, source_ports


EDGES = {"left": ("M4", "HORIZONTAL", 1), "right": ("M4", "HORIZONTAL", 1),
         "top": ("M5", "VERTICAL", 0), "bottom": ("M5", "VERTICAL", 0)}


def technology(text, layer, direction):
    section, = re.findall(rf"(?ms)^LAYER {layer}\n(.*?)^END {layer}\s*$", text)
    assert re.findall(r"(?m)^\s*DIRECTION (\w+)\s*;", section) == [direction]
    pitch, = re.findall(r"(?m)^\s*PITCH (\S+) (\S+)\s*;", section)
    offset, = re.findall(r"(?m)^\s*OFFSET (\S+) (\S+)\s*;", section)
    return tuple(map(Decimal, pitch)), tuple(map(Decimal, offset))


def side_plan(ports, die, margin, text):
    assert ports and all(direction in {"in", "out"} for direction in ports.values())
    ordered = sorted(ports)
    assigned = {}
    for index, (side, (layer, direction, axis)) in enumerate(EDGES.items()):
        pitch, offset = technology(text, layer, direction)
        step, origin = pitch[axis], offset[axis]
        assert step > 0 and 0 <= origin < step and die[axis] > 2 * margin
        start = int(((margin - origin) / step).to_integral_value(rounding=ROUND_CEILING))
        stop = int(((die[axis] - margin - origin) / step).to_integral_value(rounding=ROUND_FLOOR))
        tracks = stop - start + 1
        pins = ordered[index * len(ordered) // 4:(index + 1) * len(ordered) // 4]
        assert 0 < len(pins) <= tracks, (side, len(pins), tracks)
        assigned[side] = {"layer": layer, "pitch_um": str(step), "nominal_tracks": tracks, "port_bits": len(pins),
                          "inputs": sum(ports[name] == "in" for name in pins), "first_pin": pins[0], "last_pin": pins[-1]}
    assert sum(group["port_bits"] for group in assigned.values()) == len(ports)
    return assigned


def run(output):
    outline = ROOT / "records/wac_joined_predictor_macro_outline_result.json"
    plan = read(outline)
    assert plan["state"] == "joined_predictor_macro_outline_geometry_verified"
    inputs = ROOT / ".cache/physical/shared_memory_layer_boundary/physical_inputs/macro_seed.json"
    tech = ROOT / read(VIEWS)["physical_abstracts"][0]
    ports_file = ROOT / ".cache/physical/wide_weight_loader/parallel_synthesis/genus_elaboration_guarded/port_inventory.tsv"
    source_record = ROOT / "records/wac_joined_chip_synthesis_preflight_result.json"
    source = read(source_record)
    assert source["state"] == "joined_chip_synthesis_source_cuts_elaborated"
    pins = {}
    for path in (outline, source_record, Path(__file__).resolve()):
        pin(pins, path)
    for path in (inputs, tech):
        pin(pins, path, plan["input_sha256"][str(path.relative_to(ROOT))])
    admission = ports_file.parents[1] / "native_parent_bit_level_10g_memory_guard_stop/admission.json"
    pin(pins, admission)
    pin(pins, ports_file, read(admission)["input_sha256"][str(ports_file.relative_to(ROOT))])
    rows = [line.split("\t") for line in ports_file.read_text().splitlines()]
    ports = dict(rows)
    assert len(ports) == len(rows) == 12365
    rtl_top = ports_file.parents[1] / f"{TOP}.sv"
    pin(pins, rtl_top, source["input_sha256"][str(rtl_top.relative_to(ROOT))])
    rtl_ports = source_ports(rtl_top.read_text())
    expected = {"clk": "in", "rst_n": "in"}
    for rtl_direction, native_direction in (("input", "in"), ("output", "out")):
        expected.update((bit, native_direction) for bit in port_bits(rtl_ports, rtl_direction))
    assert ports == expected
    seed = read(inputs)
    die = tuple(map(Decimal, plan["die_um"]))
    margin = Decimal(seed["core_margin_um"])
    sides = side_plan(ports, die, margin, tech.read_text())
    verify(pins)
    result = {"state": "joined_chip_boundary_pin_capacity_checked", "die_um": plan["die_um"],
              "edge_end_margin_um": str(margin), "port_bits": len(ports), "sides": sides,
              "scope": "Nominal track capacity on the outline using the archived Genus port inventory and existing side order. Native pin geometry and routing remain pending.",
              "input_sha256": pins}
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], len(ports), {side: (row["port_bits"], row["nominal_tracks"]) for side, row in sides.items()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)
