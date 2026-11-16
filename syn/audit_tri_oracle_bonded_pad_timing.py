"""Screen bonded input-pad skew against the mapped dual-edge receiver."""
import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import tarfile

from measure_tri_oracle_serial_memory_requests import digest, read


ROOT = Path(__file__).resolve().parents[1]
REC = Path("records/tri_oracle_shared_edge_metadata.json")
GEOMETRY = Path("records/tri_oracle_bonded_pad_capacity.json")
TARGETS = Path("records/paper_result_targets.json")
CELL_NAMES = ("PDDW04DGZ_H_G", "PDDW04DGZ_V_G")
DRIVER_CELLS = tuple(f"PDDW{drive:02d}DGZ_{side}_G" for drive in (4, 8, 12, 16) for side in ("H", "V"))
PAD_CORNERS = ("ssg0p81v1p62v125c", "ffg0p99v1p98vm40c", "tt0p9v1p8v25c")


def axis(source, index):
    pattern = rf'\bindex_{index}\s*\(\s*"([^"]+)"'
    value = re.search(pattern, source)[1]
    return tuple(map(Decimal, value.split(",")))


def read_arcs(data, name, output=False):
    start = re.search(rf"(?m)^cell\s*\({name}\)\s*{{", data).end()
    end = re.search(r"(?m)^cell\s*\(", data[start:]).start() + start
    cell = data[start:end]
    assert re.search(r"\bpin\(PAD\)\s*{", cell)
    if output:
        arc = cell.split("pin(PAD)", 1)[1].split("pin(C)", 1)[0]
        expected = "I"
    else:
        arc = cell.split("pin(C)", 1)[1].split("internal_power()", 1)[0]
        expected = "PAD"
    assert 'timing_sense : "positive_unate"' in arc and f'related_pin : "{expected}"' in arc
    result = {}
    metrics = ("cell_rise", "cell_fall", "rise_transition", "fall_transition") if output else ("cell_rise", "cell_fall")
    for metric in metrics:
        table, rows = re.search(rf"{metric}\(\s*(\w+)\s*\)\s*{{(.*?)}}", arc, re.S).groups()
        template = re.search(rf"lu_table_template\(\s*{table}\s*\)\s*{{(.*?)}}", data, re.S)[1]
        assert re.search(r"variable_1\s*:\s*input_net_transition", template)
        assert re.search(r"variable_2\s*:\s*total_output_net_capacitance", template)
        slews, loads = (axis(template, i) for i in (1, 2))
        values = [tuple(map(Decimal, row.split(","))) for row in re.findall(r'"([\d., ]+)"', rows)]
        assert len(values) == len(slews) and all(len(row) == len(loads) for row in values)
        assert all(all(a <= b for a, b in zip(row, row[1:])) for row in values)
        result[metric] = (slews, loads, values)
    return result


def pad_points(data):
    assert re.search(r'time_unit\s*:\s*"1ns"', data)
    assert re.search(r"capacitive_load_unit\s*\(1,pf\)", data)
    points = []
    for name in CELL_NAMES:
        arcs = read_arcs(data, name)
        for metric, (slews, loads, values) in arcs.items():
            assert slews[0] == Decimal("0.5") and loads == (
                Decimal("0.01"), Decimal("0.03"), Decimal("0.05"),
                Decimal("0.10"), Decimal("0.30"), Decimal("0.50"))
            points.extend((name, metric.removeprefix("cell_"), load, delay)
                          for load, delay in zip(loads, values[0], strict=True))
    return points


def envelope(points, maximum, half_period):
    chosen = [row for row in points if row[2] <= maximum]
    greatest_data_delay = max(row[3] for row in chosen)
    least_data_delay = min(row[3] for row in chosen)
    # Clock and data pads may use either physical orientation in the ring.
    matched = {(name, edge, load): delay for name, edge, load, delay in chosen}
    half_periods = [
        half_period - abs(matched[name, "rise", load] - matched[name, "fall", load])
        for name, edge, load in matched if edge == "rise"
    ]
    return greatest_data_delay - least_data_delay, min(half_periods)


def output_screen(data, period):
    """Use the least characterized slew and check the worst output polarity."""
    drivers = {}
    for name in DRIVER_CELLS:
        arcs = read_arcs(data, name, output=True)
        for slews, loads, _ in arcs.values():
            assert slews[0] == Decimal("0.1") and loads[:3] == (5, 10, 25)
        drivers[name] = {
            str(load): {
                "worst_pad_delay_ns": max(arcs[metric][2][0][i] for metric in ("cell_rise", "cell_fall")),
                "worst_pad_transition_ns": max(arcs[metric][2][0][i]
                                                  for metric in ("rise_transition", "fall_transition")),
            }
            for i, load in enumerate((5, 10, 25))
        }
    best = min(item["5"]["worst_pad_delay_ns"] for item in drivers.values())
    assert best > period
    return {
        "core_input_transition_ps": 100,
        "slow_corner": PAD_CORNERS[0],
        "best_worst_polarity_delay_at_5pf_ns": float(best),
        "period_ns": round(float(period), 6),
        "drivers": {
            name: {load: {metric: float(value) for metric, value in timing.items()} for load, timing in values.items()}
            for name, values in drivers.items()
        },
        "scope": "A single-cycle link sampled by an unshifted remote clock cannot accommodate these "
                 "characterized slow-corner output delays, even before adding internal logic and board delay. "
                 "A phase-aligned forwarded clock or a multicycle interface changes this constraint.",
    }


def run():
    assert Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    proof = read(REC)
    release_paths = read(GEOMETRY)["evidence_sha256"]
    abstract, = [Path(name) for name in release_paths if name.endswith("sefu10lm.tar.gz")]
    assert digest(abstract) == release_paths[str(abstract)]
    archive = abstract.with_name("tphn28hpcpgv18_170a_nldm.tar.gz")
    with tarfile.open(abstract, "r:gz") as bundle:
        member, = [entry for entry in bundle if entry.isfile() and entry.name.endswith(".lef")]
        with bundle.extractfile(member) as stream:
            physical = stream.read().decode()
    for name in DRIVER_CELLS:
        cell = re.search(rf"(?ms)^MACRO {name}\n(.*?)^END {name}\s*$", physical)[1]
        assert re.search(r"(?m)^    SIZE 20(?:\.0+)? BY 110(?:\.0+)? ;$", cell)
        assert re.search(r"(?m)^    PIN PAD\s*$", cell)

    half_period = Decimal(1000) / (2 * Decimal(read(TARGETS)["system_latency"]["clock_megahertz"]))
    corners = {}
    members = {}
    output = None
    with tarfile.open(archive, "r:gz") as bundle:
        inventory = [member for member in bundle if member.isfile()]
        for corner in PAD_CORNERS:
            source, = [item for item in inventory if item.name.endswith(f"pgv18{corner}.lib")]
            with bundle.extractfile(source) as stream:
                raw = stream.read()
            members[source.name] = sha256(raw).hexdigest()
            lib = raw.decode()
            corners[corner] = pad_points(lib)
            if corner == PAD_CORNERS[0]:
                output = output_screen(lib, 2 * half_period)

    setup = Decimal(str(proof["mapped_shared_metadata_setup_margin_ps"])) / 1000
    hold = Decimal(str(proof["mapped_shared_metadata_hold_margin_ps"])) / 1000
    delay = Decimal("0.2")  # port delay from the pinned setup/hold reports
    for name, checksum in proof["evidence_sha256"].items():
        if name.endswith("/constraints.sdc"):
            path = Path(name)
            assert digest(path) == checksum
            assert re.search(r"set_input_delay .* 0\.2 \[get_ports \{pad_metadata\[0\]\}\]", path.read_text())
            sdc = path
    screens = {}
    for maximum in (Decimal("0.05"), Decimal("0.50")):
        skew = {corner: envelope(points, maximum, half_period) for corner, points in corners.items()}
        setup_penalty = skew[PAD_CORNERS[0]][0]
        hold_penalty = skew[PAD_CORNERS[1]][0]
        valid_start = delay - hold + hold_penalty
        valid_end = delay + setup - setup_penalty
        screens[str(int(maximum * 1000))] = {
            "assumed_load_range_femtofarads": [10, int(maximum * 1000)],
            "pad_delay_envelope_ps_by_corner": {name: float(values[0] * 1000)
                                                for name, values in skew.items()},
            "minimum_clock_half_period_ps_by_corner": {name: round(float(values[1] * 1000), 3)
                                                        for name, values in skew.items()},
            "projected_setup_margin_at_200ps_ps": float((setup - setup_penalty) * 1000),
            "projected_hold_margin_at_200ps_ps": float((hold - hold_penalty) * 1000),
            "projected_peer_launch_window_after_clock_ps": [float(valid_start * 1000), float(valid_end * 1000)],
        }
    assert screens["50"]["projected_setup_margin_at_200ps_ps"] > screens["500"]["projected_setup_margin_at_200ps_ps"]
    return {
        "state": "bonded_input_skew_and_output_delay_screened_against_580mhz",
        "pad_cells": CELL_NAMES, "characterized_pad_input_slew_ps": 500,
        "load_sweeps": screens,
        "single_cycle_output_screen": output,
        "pad_library_member_sha256": members,
        "scope": "Analytic screen using nonlinear delay tables for two physical pad orientations. "
                 "The clock and data pad transitions and core-side loads are allowed to differ within each sweep. "
                 "Pad and core library voltages differ, and the model omits clock-tree skew, package, board, "
                 "interconnect and voltage variation. The launch window is a conditional budget.",
        "evidence_sha256": {str(path): digest(path) for path in (REC, GEOMETRY, TARGETS, sdc, abstract, archive,
                                                                 Path(__file__).resolve().relative_to(ROOT))},
    }


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(run(), indent=2, sort_keys=True))
