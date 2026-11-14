"""Screen the installed pad data arcs at the paper's peak clock period."""

import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import tarfile

from audit_tri_oracle_placed_chip_boundary import PAD_ARCHIVE, digest, pad_views


ROOT = Path(__file__).resolve().parents[1]
LIBRARY_ARCHIVE = PAD_ARCHIVE.with_name("tphn28hpcpgv18_170a_nldm.tar.gz")
CORNERS = {
    "ssg0p81v1p62v125c": ("0.81", "1.62", 125),
    "tt0p9v1p8v25c": ("0.9", "1.8", 25),
    "ffg0p99v1p98vm40c": ("0.99", "1.98", -40),
}
SIGNAL = re.compile(r"P(?:DD|DU|RD|RU)W\d{2}S?DGZ_[HV]_G")
BIDIRECTIONAL = re.compile(r"P(?:DD|DU)W")


def named_blocks(text, keyword):
    pattern = rf"(?m)^\s*{keyword}\s*\(\s*(\w*)\s*\)\s*\{{"
    for match in re.finditer(pattern, text):
        depth = 1
        for brace in re.finditer(r"[{}]", text[match.end():]):
            depth += 1 if brace[0] == "{" else -1
            if depth == 0:
                yield match[1], text[match.end():match.end() + brace.start()]
                break
        else:
            raise ValueError(f"Unterminated {keyword} {match[1]}")


def tables(library, pin, source):
    arcs = [body for _, body in named_blocks(pin, "timing")
            if re.search(rf'related_pin\s*:\s*"{source}"', body)
            and not re.search(r"timing_type\s*:\s*(?:three_state|setup|hold)", body)]
    arc, = arcs
    result = {}
    for edge in ("rise", "fall"):
        (name, body), = named_blocks(arc, f"cell_{edge}")
        template = library[name]
        assert "variable_1 :  input_net_transition" in template
        assert "variable_2 :  total_output_net_capacitance" in template
        axes = []
        for axis in (1, 2):
            values, = re.findall(rf'index_{axis}\s*\(\s*"([^"]+)"', template)
            grid = list(map(Decimal, values.split(",")))
            assert grid == sorted(set(grid)) and grid[0] > 0
            axes.append(grid)
        grid = [list(map(Decimal, row.split(","))) for row in re.findall(r'"([^"]+)"', body)]
        assert len(grid) == len(axes[0]) and all(len(row) == len(axes[1]) for row in grid)
        distances = [item for row in grid for item in row]
        assert all(value.is_finite() and value > 0 for value in distances)
        result[edge] = dict(min_ns=str(min(distances)), max_ns=str(max(distances)),
                            input_slew_range_ns=[str(axes[0][0]), str(axes[0][-1])],
                            output_load_range_pf=[str(axes[1][0]), str(axes[1][-1])])
    return result


def read_corner(archive, corner, masters, period):
    filename = "tphn28hpcpgv18" + corner + ".lib"
    member, = [entry for entry in archive if entry.isfile() and Path(entry.name).name == filename]
    assert member.size < 16 * 2**20
    with archive.extractfile(member) as stream:
        raw = stream.read()
    data = raw.decode("ascii")
    assert re.search(r'time_unit\s*:\s*"1ns"', data)
    assert re.search(r'capacitive_load_unit\s*\(\s*1\s*,\s*pf\s*\)', data)
    voltage, io_voltage, temperature = CORNERS[corner]
    for rail, expected in (("COREVDD1", voltage), ("IOVDD1", io_voltage)):
        value, = re.findall(rf"voltage_map\s*\(\s*{rail}\s*,\s*(\d+(?:\.\d+)?)", data)
        assert Decimal(value) == Decimal(expected)
    assert int(re.search(r"nom_temperature\s*:\s*(-?\d+)", data)[1]) == temperature
    templates = dict(named_blocks(data, "lu_table_template"))
    cells = {}
    for name, cell in named_blocks(data, "cell"):
        if name not in masters:
            continue
        assert name not in cells
        pins = dict(named_blocks(cell, "pin"))
        cells[name] = {"receive": tables(templates, pins["C"], "PAD")}
        if BIDIRECTIONAL.match(name):
            cells[name]["transmit"] = tables(templates, pins["PAD"], "I")
    assert set(cells) == masters
    summary = {}
    for path in ("receive", "transmit"):
        paths = {name: arcs[path] for name, arcs in cells.items() if path in arcs}
        summary[path] = {
            "masters": len(paths),
            "all_table_points_over_period_on_both_edges": sum(
                all(Decimal(edge["min_ns"]) > period for edge in arcs.values()) for arcs in paths.values()
            ),
            "minimum_delay_ns": str(min(Decimal(edge["min_ns"]) for arcs in paths.values() for edge in arcs.values())),
            "maximum_delay_ns": str(max(Decimal(edge["max_ns"]) for arcs in paths.values() for edge in arcs.values())),
            "illustrative_pad": paths["PDDW16DGZ_H_G"],
        }
    return dict(library_member_sha256=sha256(raw).hexdigest(), core_volts=voltage, pad_volts=io_voltage,
                temperature_celsius=temperature, **summary)


def run(pad_archive, timing_archive):
    boundary_path = ROOT / "records/tri_oracle_grouped_active_boundary.json"
    targets_path = ROOT / "records/paper_result_targets.json"
    boundary, targets = (json.loads(path.read_text()) for path in (boundary_path, targets_path))
    assert boundary["state"] == "grouped_active_placement_boundary_verified"
    cells, count, _, _, abstract = pad_views(pad_archive)
    assert abstract == boundary["pad_abstract_sha256"]
    masters = {name for name in cells if SIGNAL.fullmatch(name)}
    assert len(masters) == count == 56
    clock = targets["peak"]["clock_megahertz"]
    assert clock == targets["system_latency"]["clock_megahertz"] == 580
    period = Decimal(1000) / clock
    with tarfile.open(timing_archive, "r:gz") as archive:
        corners = {name: read_corner(archive, name, masters, period) for name in CORNERS}
    return dict(
        state="installed_signal_pad_data_arcs_screened_against_paper_clock",
        buffered_netlist_sha256=boundary["candidate_netlist_sha256"],
        paper_clock_megahertz=clock,
        paper_clock_period_ns=float(period),
        pad_abstract_sha256=abstract,
        pad_library_archive_sha256=digest(timing_archive),
        evidence_sha256={str(path.relative_to(ROOT)): digest(path) for path in
                         (boundary_path, targets_path, Path(__file__).resolve())},
        corners=corners,
        scope="Pad propagation delay at characterized table points. A delay greater than one clock period "
              "excludes an unshifted same-cycle direct path at those points. A pipelined or source-synchronous "
              "link can tolerate multi-cycle propagation. This screen establishes neither sustained bit rate "
              "nor timing with receiver setup, package loading, skew and board interconnect.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pad-archive", type=Path, default=PAD_ARCHIVE)
    parser.add_argument("--timing-archive", type=Path, default=LIBRARY_ARCHIVE)
    args = parser.parse_args()
    print(json.dumps(run(args.pad_archive, args.timing_archive), indent=2, sort_keys=True))
