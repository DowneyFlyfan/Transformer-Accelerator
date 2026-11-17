"""Time a forwarded clock formed by intersecting its direct and delayed copies."""

import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re

from prepare_tri_oracle_booth_packet_replay import replace_once
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, digest
from verify_tri_oracle_forwarded_clock_pulse import PERIOD, REPORT_ROUNDING, verify_pulses
from verify_tri_oracle_wide_forwarded_clock_drivers import (
    DRIVER, DRIVERS, LOADS, SENDER, SUFFIX, WRAPPER, data_margin, setup as comparison_inputs,
)
from verify_tri_oracle_wide_loaded_pads import PAD


PRIOR = Path("records/tri_oracle_wide_forwarded_clock_drivers.json")
EDGE_DRIVER = Path("syn/tri_oracle_measure_wide_forwarded_clock_edges.tcl")
SHAPER = f"AN2D1{SUFFIX}"
DELAYS = (None, 50, 75, 100, 150, 200, 250)
TOP = "wide_forwarded_clock_shaping"
NUMBER = r"(-?\d+\.\d+)"
PULSE_SPLIT = r"(?m)(?=^Path \d+:)"


def setup():
    previous, generated, _, inputs = comparison_inputs()
    proof = json.loads(PRIOR.read_text())
    for name, text in generated.items():
        path = previous / name
        assert path.read_text() == text and digest(path) == proof["evidence_sha256"][str(path.relative_to(ROOT))]
    first = inputs[0]
    assert first.name == "netlist.v" and first.parent.name == "loaded_horizontal_pads"
    assert digest(first) == proof["evidence_sha256"][str(first.relative_to(ROOT))]
    source, bond = first.read_text().split(f"module {WRAPPER} (", 1)
    old = f"{DRIVERS[0]} g689(.I (clk), .ZN (pad_clock))"
    declarations = ["  input wire clk, rst_n, in_valid, pad_credit", "  input wire [21:0] in_word"]
    modules, instances = [], []
    for index, delay in enumerate(DELAYS):
        sender, variant = f"{SENDER}_{index}", f"wide_shaped_{index}"
        mapped = replace_once(source, f"module {SENDER}(", f"module {sender}(")
        if delay is not None:
            cell = f"DEL{delay:03d}D1{SUFFIX}"
            mapped = replace_once(mapped, old, f"{DRIVERS[0]} g689(.I (clk), .ZN (clock_direct))")
            mapped = replace_once(mapped, "endmodule", "  wire clock_direct, clock_delayed;\n"
                                  f"  {cell} delayed_clock (.I(clock_direct), .Z(clock_delayed));\n"
                                  f"  {SHAPER} join_clock (.A1(clock_direct), .A2(clock_delayed), .Z(pad_clock));\n"
                                  "endmodule")
        wrapper = replace_once(bond, f"{SENDER} sender", f"{sender} sender")
        modules.extend((mapped, f"module {variant} (" + wrapper))
        declarations.extend((f"  output wire clock_{index}, valid_{index}",
                             f"  output wire [21:0] data_{index}",
                             f"  output wire [22:0] probe_{index}"))
        instances.append(f"  {variant} variant_{index} (.clk(clk), .rst_n(rst_n), .in_valid(in_valid),\n"
                         "    .in_word(in_word), .pad_credit(pad_credit), .in_ready(), .protocol_error(),\n"
                         f"    .tx_valid(valid_{index}), .tx_clock(clock_{index}), .tx_data(data_{index}),\n"
                         f"    .peer_probe(probe_{index}));\n")
    root = f"module {TOP} (\n" + ",\n".join(declarations) + "\n);\n"
    out = previous.with_name(TOP)
    script = generated["measure.tcl"]
    count = len(DELAYS)
    for before, after in (
        (f"set out {{{previous}}}", f"set out {{{out}}}"),
        ("-top wide_forwarded_clock_drivers", f"-top {TOP}"),
        (f"[get_ports clock_*]] != {len(DRIVERS)}", f"[get_ports clock_*]] != {count}"),
        (f"[get_ports {{data_* valid_*}}]] != {23 * len(DRIVERS)}", f"[get_ports {{data_* valid_*}}]] != {23 * count}"),
        (f"{{$i < {len(DRIVERS)}}}", f"{{$i < {count}}}"),
    ):
        script = replace_once(script, before, after)
    return out, {"netlist.v": "\n".join(modules) + "\n" + root + "".join(instances) + "endmodule\n",
                 "measure.tcl": script}, proof, [PRIOR, DRIVER, *(previous / name for name in generated), *inputs]


def branch_inputs(out, files):
    branches = out.with_name(f"{TOP}_edge_paths")
    header, _ = files["measure.tcl"].split("set mmmc", 1)
    header = replace_once(header, f"set out {{{out}}}", f"set out {{{branches}}}")
    return branches, {"netlist.v": files["netlist.v"], "measure.tcl": header + EDGE_DRIVER.read_text()}


def check_run(out, files):
    for name, text in files.items():
        assert (out / name).read_text() == text
    status = json.loads((out / "native_status.json").read_text())
    assert status["exit_status"] == 0 and status["stop_reason"] is None
    log = (out / "console.log").read_text()
    assert re.search(r"(?m)^TRI_ORACLE_CLOCK_PAD_COMPARISON_FINISHED$", log)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", log)


def latency_by_edge(report, prefix, delay, mode):
    """Check the path controlling each edge and subtract the clock's launch phase."""
    latencies = {}
    for path in re.split(PULSE_SPLIT, report.read_text())[1:]:
        start, end = re.findall(r"(?:Startpoint|Endpoint):\s+\(([RF])\)", path)
        blocks = path.split("Other End Path:")
        expected = {"direct": (False, False), "delayed": (True, True), "raw": (True, False)}[mode]
        for edge, block, through_delay in zip((start, end), blocks, expected, strict=True):
            cell = f"DEL{delay:03d}D1{SUFFIX}"
            actual = f"{prefix}sender/delayed_clock/Z" in block
            assert actual == through_delay, (report, edge)
            if actual:
                assert re.search(rf"{prefix}sender/delayed_clock/Z\s+{cell}\s+{NUMBER}\s+{NUMBER}\s+{edge}\b", block)
            phase = Decimal(re.search(r"(?m)^\s+clk\s+\(arrival\)\s+-\s+" + NUMBER, block)[1])
            points = {}
            for pin, master in (("sender/join_clock/Z", SHAPER), ("clock_pad/PAD", PAD),
                                ("peer_capture_0/CP", f"DFQD1{SUFFIX}")):
                arrival = re.search(rf"(?m)^\s+{prefix}{pin}\s+{master}\s+{NUMBER}\s+{NUMBER}\s+{edge}\b", block)
                assert arrival, (report, pin)
                points[pin] = Decimal(arrival[2]) - phase
            if mode != "raw" and edge in latencies:
                assert all(abs(latencies[edge][pin] - value) <= REPORT_ROUNDING for pin, value in points.items())
            latencies[edge] = points
    assert latencies.keys() == {"R", "F"}
    return latencies


def correlated_pulses(raw_report, branch_reports, view, prefix, delay):
    raw = verify_pulses(raw_report, view, prefix, PAD, complementary=False)
    latency_by_edge(raw_report, prefix, delay, "raw")
    edges, widths = {}, {}
    for arm, report in branch_reports.items():
        widths[arm] = verify_pulses(report, f"{view}_{arm}", prefix, PAD)
        edges[arm] = latency_by_edge(report, prefix, delay, arm)
    for edge in ("R", "F"):
        pin = "sender/join_clock/Z"
        separation = edges["delayed"][edge][pin] - edges["direct"][edge][pin]
        assert REPORT_ROUNDING < separation < PERIOD / 2 - REPORT_ROUNDING
    combined = {}
    for pin in ("sender/join_clock/Z", "clock_pad/PAD", "peer_capture_0/CP"):
        high = PERIOD / 2 + edges["direct"]["F"][pin] - edges["delayed"]["R"][pin]
        assert 0 < high < PERIOD
        combined[pin] = {"high": round(high * 1000), "low": round((PERIOD - high) * 1000)}
    result = {}
    for level, raw_pulse in raw.items():
        width = combined["peer_capture_0/CP"][level]
        minimum = max(pulses[level]["receiver_minimum_ps"] for pulses in widths.values())
        result[level] = {
            "receiver_width_ps": width,
            "pad_width_ps": combined["clock_pad/PAD"][level],
            "receiver_minimum_ps": minimum,
            "correlated_margin_ps": width - minimum - 50,
            "native_unconstrained_margin_ps": raw_pulse["margin_ps"],
        }
    # The unconstrained high pulse should use the same active branches.
    assert abs(result["high"]["receiver_width_ps"] - raw["high"]["receiver_width_ps"]) <= 2
    return result


def receiver_slew_limit(library):
    """Return the most restrictive upper slew index of the receiver pulse tables."""
    master = re.search(rf"(?ms)^cell \(DFQD1{SUFFIX}\)\s*\{{(.*?)(?=^cell \()", library.read_text())[1]
    clock = re.search(r"(?ms)^  pin\s*\(CP\)\s*\{(.*?)(?=^  pin\s*\()", master)[1]
    constraints = re.findall(r"(?:rise|fall)_constraint \(mpw_constraint_template_3x3\)\s*\{\s*index_1 \(\"([^\"]+)\"\);", clock)
    assert len(constraints) == 4
    return int(min(max(map(Decimal, table.split(","))) for table in constraints) * 1000)


def capture_slew(report, prefix, delay):
    samples = set()
    for path in re.split(PULSE_SPLIT, report.read_text())[1:]:
        clock = path.split("Other End Path:")[1]
        if delay is not None:
            assert re.search(rf"{prefix}sender/join_clock/Z\s+-\s+A2->Z\s+R\s+{SHAPER}\b", clock)
            assert f"{prefix}sender/delayed_clock/Z" in clock
        sample = re.search(rf"{prefix}peer_capture_0/CP\s+-\s+CP\s+R\s+DFQD1{SUFFIX}\s+\d+\s+{NUMBER}", clock)
        if sample:
            samples.add(int(Decimal(sample[1]) * 1000))
    assert len(samples) == 1, report
    return samples.pop()


def verify():
    out, files, prior, sources = setup()
    branches, active_files = branch_inputs(out, files)
    check_run(out, files)
    check_run(branches, active_files)
    limits = {}
    for corner, condition in (("slow", "ssg0p9v125c"), ("fast", "ffg1p05vm40c")):
        library = ROOT / f".cache/physical/library/tcbn28hpcplusbwp12t40p140{condition}.lib"
        limits[corner] = receiver_slew_limit(library)
        sources.append(library)
    results, reports = {}, []
    for index, delay in enumerate(DELAYS):
        prefix = f"variant_{index}/"
        result = {}
        for load in LOADS:
            measured = {"corners": {}}
            pulse_margins = []
            for mode, corner in (("setup", "slow"), ("hold", "fast")):
                view = f"{corner}_{load}"
                active_view = f"{view}_delayed"
                timing, slews = [], set()
                for edge in ("rise", "fall"):
                    report = branches / f"{index}_{load}_delayed_{mode}_{edge}.rpt"
                    timing.append(data_margin(report, prefix, active_view, DRIVERS[0], mode, edge))
                    slews.add(capture_slew(report, prefix, delay))
                    reports.append(report)
                assert len(slews) == 1
                slew = slews.pop()
                measured[f"minimum_{mode}_margin_ps"] = min(timing)
                pulse = out / f"{index}_{load}_pulse_{corner}.rpt"
                isolated = {arm: branches / f"{index}_{load}_{arm}_pulse_{corner}.rpt" for arm in ("direct", "delayed")}
                if delay is None:
                    evidence = verify_pulses(pulse, view, prefix, PAD)
                    for arm, report in isolated.items():
                        assert verify_pulses(report, f"{view}_{arm}", prefix, PAD) == evidence
                    for row in evidence.values():
                        row["correlated_margin_ps"] = row["native_unconstrained_margin_ps"] = row.pop("margin_ps")
                else:
                    evidence = correlated_pulses(pulse, isolated, view, prefix, delay)
                measured["corners"][corner] = {
                    "pulses": evidence,
                    "receiver_rising_slew_ps": slew,
                    "receiver_pulse_table_upper_index_ps": limits[corner],
                    "receiver_rising_slew_extrapolated": slew > limits[corner],
                }
                pulse_margins.extend(row["correlated_margin_ps"] for row in evidence.values())
                reports.extend((pulse, *isolated.values()))
            measured["minimum_pulse_margin_ps"] = min(pulse_margins)
            if delay is None:
                expected = prior["drivers"][DRIVERS[0]]["clock_load_pf"][str(load)]
                assert all(abs(expected[key] - measured[key]) <= 3 for key in expected)
            result[str(load)] = measured
        results["direct" if delay is None else f"DEL{delay:03d}"] = result
    sources.extend((Path(__file__).resolve(), EDGE_DRIVER, Path("syn/verify_tri_oracle_forwarded_clock_pulse.py")))
    for run in (out, branches):
        sources.extend(run / name for name in ("console.log", "native_status.json", "views.tcl", *files))
        sources.extend(sorted(run.glob("load_*.sdc")))
    report_manifest = "".join(f"{digest(path)}  {path.relative_to(out.parent)}\n" for path in sorted(reports))
    return {
        "state": "wide_forwarded_clock_edges_correlated_before_routing",
        "core_clock_megahertz": 580, "data_load_pf": 10, "setup_hold_peer_pins": 23,
        "pulse_uncertainty_ps": 50,
        "margin_by_delay_cell_and_clock_load_pf": results,
        "scope": "Standalone slow and fast corner models with installed horizontal pads and lumped loads. "
                 "The AND gate pairs the direct falling edge with the delayed rising edge. Separate timing modes "
                 "retain both physical pin loads and measure each arc. The narrower pulse uses the larger "
                 "modeled receiver requirement across the two modes. Rising slew beyond the receiver pulse "
                 "table is flagged. The models exclude routed parasitics, package, board and within-die variation. "
                 "These results do not authorize clock distribution or whole-chip routing.",
        "timing_report_count": len(reports),
        "timing_report_manifest_sha256": sha256(report_manifest.encode()).hexdigest(),
        "evidence_sha256": {str(path.relative_to(ROOT) if path.is_absolute() else path): digest(path) for path in sources},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "prepare-branches", "verify"))
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    if args.phase != "verify":
        output, files, _, _ = setup()
        if args.phase == "prepare-branches":
            output, files = branch_inputs(output, files)
        output.mkdir()
        for name, text in files.items():
            (output / name).write_text(text)
        print(output)
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
