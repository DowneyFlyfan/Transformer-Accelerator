"""Measure the wide forwarded-clock link through the installed input pads."""

import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re

from audit_tri_oracle_bonded_pad_timing import PAD_CORNERS, read_arcs
from prepare_tri_oracle_booth_packet_replay import replace_once
from verify_tri_oracle_forwarded_clock_pulse import verify_pulses
from verify_tri_oracle_wide_forwarded_clock_shaping import (
    DELAYS, DRIVERS, LOADS, NUMBER, PAD, PULSE_SPLIT, ROOT, SUFFIX, branch_inputs,
    capture_slew, check_run, correlated_pulses, data_margin, digest, receiver_slew_limit,
    setup as sender_inputs,
)


REFERENCE = Path("records/tri_oracle_wide_forwarded_clock_shaping.json")
TOP = "wide_forwarded_clock_peer_pads_arcs"
ARC_DRIVER = """                if {$i == 0 && $arm eq "raw"} {
                    set view ${corner}_$tag
                    set timing_option [dict get {slow -max fast -min} $corner]
                    for {set bit -1} {$bit < 23} {incr bit} {
                        if {$bit == -1} {
                            set pin clock
                            set tx variant_$i/clock_pad
                            set rx variant_$i/peer_clock_pad
                        } else {
                            set pin data_$bit
                            set tx variant_$i/data_pad_$bit
                            set rx variant_$i/peer_data_pad_$bit
                        }
                        report_delay_calculation $timing_option -active_arcs -from $tx/I -to $tx/PAD -view $view -out_file $out/${view}_tx_$pin.rpt
                        report_delay_calculation $timing_option -active_arcs -from $rx/PAD -to $rx/C -view $view -out_file $out/${view}_rx_$pin.rpt
                    }
                }
"""


def setup():
    sender, files, _, _ = sender_inputs()
    branches, baseline = branch_inputs(sender, files)
    previous = json.loads(REFERENCE.read_text())["evidence_sha256"]
    sources = [REFERENCE]
    for name, data in baseline.items():
        path = branches / name
        assert path.read_text() == data and digest(path) == previous[str(path.relative_to(ROOT))]
        sources.append(path)
    out = sender.with_name(TOP)
    patched = []
    capture = re.compile(r"(peer_capture_(\d+)) \(\.CP\(tx_clock\), \.D\((tx_data\[\d+\]|tx_valid)\)")
    for line in baseline["netlist.v"].splitlines():
        if "clock_pad (.I(" in line:
            patched.extend(("  wire received_clock;",
                            f"  {PAD} peer_clock_pad (.I(1'b0), .OEN(1'b1), .REN(1'b1), .PAD(tx_clock), .C(received_clock));"))
        match = capture.search(line)
        if match:
            instance, bit, data = match.groups()
            node = f"received_{bit}"
            patched.extend((f"  wire {node};",
                            f"  {PAD} peer_data_pad_{bit} (.I(1'b0), .OEN(1'b1), .REN(1'b1), .PAD({data}), .C({node}));"))
            line = replace_once(line, match[0], f"{instance} (.CP(received_clock), .D({node})")
        patched.append(line)
    netlist = "\n".join(patched) + "\n"
    assert netlist.count("peer_clock_pad (") == len(DELAYS)
    assert netlist.count("peer_data_pad_") == 23 * len(DELAYS)
    script = replace_once(baseline["measure.tcl"], f"set out {{{branches}}}", f"set out {{{out}}}")
    assert script.count("foreach arm {direct delayed}") == 2
    script = script.replace("foreach arm {direct delayed}", "foreach arm {direct delayed raw}")
    original = ('        set ignored_pin [dict get {direct A2 delayed A1} $arm]\n'
                '        puts $sdc "set_disable_timing -from $ignored_pin -to Z \\[get_cells {variant_*/sender/join_clock}\\]"\n')
    gated = '        if {$arm ne "raw"} {\n' + "".join("    " + line for line in original.splitlines(keepends=True)) + "        }\n"
    script = replace_once(script, original, gated)
    start = "            foreach corner {slow fast} {\n"
    script = replace_once(script, start, start + ARC_DRIVER)
    return out, {"measure.tcl": script, "netlist.v": netlist}, sources


def pad_delay(report, instance, source, sink, corner, view, axes):
    text = report.read_text()
    assert f"-view {view} " in text.splitlines()[5], report
    for label, expected in (("From pin", f"{instance}/{source}"), ("To Pin", f"{instance}/{sink}"),
                            ("Cell", PAD), ("Library", f"tphn28hpcpgv18{corner}"), ("Arc sense", "positive unate")):
        assert re.search(rf"(?m)^{label}\s*:\s+{re.escape(expected)}[ \t]*$", text), report
    fields = {
        metric: tuple(map(Decimal, re.search(rf"(?m)^{label}\s*:\s+{NUMBER} ns\s+{NUMBER} ns", text).groups()))
        for metric, label in (("input_slew", "Input transition time"), ("delay", "Cell delay"),
                              ("output_slew", "Output transition time"))
    }
    result = {}
    for index, edge in enumerate(("rise", "fall")):
        slews, _, _ = axes[f"cell_{edge}"]
        sample = {metric + "_ps": float(value[index] * 1000) for metric, value in fields.items()}
        assert all(value > 0 for value in sample.values()), report
        sample["slew_below_table"] = fields["input_slew"][index] < slews[0]
        sample["slew_above_table"] = fields["input_slew"][index] > slews[-1]
        result[edge] = sample
    return result


def verify_receive_pins(report, prefix, edge):
    """Require the matching receiver pad on every data path and on its capture clock."""
    for path in re.split(PULSE_SPLIT, report.read_text())[1:]:
        data, clock = path.split("Other End Path:")
        bit = re.search(rf"Endpoint:\s+\([RF]\) {prefix}peer_capture_(\d+)/D\b", data)[1]
        assert re.search(rf"{prefix}peer_data_pad_{bit}/C\s+-\s+PAD->C\s+{edge[0].upper()}\s+{PAD}\b", data)
        assert re.search(rf"{prefix}peer_clock_pad/C\s+-\s+PAD->C\s+R\s+{PAD}\b", clock)


def verify():
    out, files, sources = setup()
    check_run(out, files)
    reports, libraries, diagnostics, results = [], {}, {}, {}
    standard_corners = {"slow": "ssg0p9v125c", "fast": "ffg1p05vm40c"}
    for corner, pad_corner in zip(("slow", "fast"), PAD_CORNERS[:2], strict=True):
        pad_lib = out.parent / "loaded_horizontal_pads" / f"pad_{corner}.lib"
        core_lib = ROOT / f".cache/physical/library/tcbn28hpcplusbwp12t40p140{standard_corners[corner]}.lib"
        sources.extend((pad_lib, core_lib))
        pad_text = pad_lib.read_text()
        libraries[corner] = receiver_slew_limit(core_lib)
        measured_slews = {}
        for mode, source, sink in (("tx", "I", "PAD"), ("rx", "PAD", "C")):
            axes = read_arcs(pad_text, PAD, output=mode == "tx")
            for load in LOADS:
                view = f"{corner}_{load}_raw"
                checks = {}
                for signal, instance in (("clock", "clock_pad"), *((f"data_{bit}", f"data_pad_{bit}") for bit in range(23))):
                    report = out / f"{view}_{mode}_{signal}.rpt"
                    master = f"peer_{instance}" if mode == "rx" else instance
                    checks[signal] = pad_delay(report, f"variant_0/{master}", source, sink, pad_corner, view, axes)
                    reports.append(report)
                measured_slews[load, mode] = checks
                data_slews = [item["input_slew_ps"] for name, signal in checks.items()
                              if name != "clock" for item in signal.values()]
                diagnostics.setdefault(f"{corner}_{load}", {})[mode] = {
                    "outside_table_sample_count": sum(item["slew_below_table"] or item["slew_above_table"]
                                                     for signal in checks.values() for item in signal.values()),
                    "total_edge_samples": 2 * len(checks),
                    "input_slew_table_range_ps": {edge: [float(axes[f"cell_{edge}"][0][bound] * 1000)
                                                       for bound in (0, -1)] for edge in ("rise", "fall")},
                    "clock": checks["clock"],
                    "data_input_slew_range_ps": [min(data_slews), max(data_slews)],
                }
        for load in LOADS:
            tx, rx = (measured_slews[load, mode] for mode in ("tx", "rx"))
            for name, signal in tx.items():
                for edge, sample in signal.items():
                    assert abs(sample["output_slew_ps"] - rx[name][edge]["input_slew_ps"]) <= 0.2

    for index, delay in enumerate(DELAYS):
        variant = "direct" if delay is None else f"DEL{delay:03d}"
        prefix = f"variant_{index}/"
        results[variant] = {}
        for load in LOADS:
            fields = {}
            for mode, corner in (("setup", "slow"), ("hold", "fast")):
                view = f"{corner}_{load}"
                slack, slew = [], set()
                for edge in ("rise", "fall"):
                    report = out / f"{index}_{load}_delayed_{mode}_{edge}.rpt"
                    verify_receive_pins(report, prefix, edge)
                    slack.append(data_margin(report, prefix, f"{view}_delayed", DRIVERS[0], mode, edge))
                    slew.add(capture_slew(report, prefix, delay))
                    reports.append(report)
                assert len(slew) == 1
                raw = out / f"{index}_{load}_raw_pulse_{corner}.rpt"
                branches = {arm: out / f"{index}_{load}_{arm}_pulse_{corner}.rpt" for arm in ("direct", "delayed")}
                reports.extend((raw, *branches.values()))
                for report in (raw, *branches.values()):
                    for path in re.split(PULSE_SPLIT, report.read_text())[1:]:
                        assert all(f"{prefix}peer_clock_pad/C" in phase for phase in path.split("Other End Path:"))
                if delay is None:
                    pulses = verify_pulses(raw, f"{view}_raw", prefix)
                    assert all(verify_pulses(report, f"{view}_{arm}", prefix) == pulses for arm, report in branches.items())
                    margins = {level: pulse["margin_ps"] for level, pulse in pulses.items()}
                else:
                    pulses = correlated_pulses(raw, branches, f"{view}(?:_raw)?", prefix, delay)
                    margins = {level: pulse["correlated_margin_ps"] for level, pulse in pulses.items()}
                fields[corner] = {
                    f"minimum_{mode}_margin_ps": min(slack), "pulse_margins_ps": margins,
                    "peer_flop_rising_slew_ps": slew.pop(), "peer_flop_upper_pulse_table_slew_ps": libraries[corner],
                }
            results[variant][str(load)] = fields
    sources.extend((Path(__file__), out / "console.log", out / "native_status.json", out / "views.tcl",
                    *(out / name for name in files), *sorted(out.glob("load_*.sdc"))))
    manifest = "".join(f"{digest(path)}  {path.name}\n" for path in sorted(reports))
    return {
        "state": "wide_request_peer_pad_arc_and_timing_evaluation",
        "core_clock_megahertz": 580, "receiver_pad_master": PAD, "data_load_pf": 10, "data_and_valid_lanes": 23,
        "timing": results, "direct_variant_pad_slew_diagnostics": diagnostics,
        "scope": "Pre-route sender and peer timing at 580 MHz with installed transmit and receive pads. "
                 "Board and package are represented by lumped loads. Arc diagnostics compare measured input "
                 "transitions to the library table ranges. Pulse results for the delay cells correlate the "
                 "active falling and rising paths. "
                 "These results do not qualify board hardware, routed timing, or the paper's performance.",
        "report_count": len(reports),
        "report_manifest_sha256": sha256(manifest.encode()).hexdigest(),
        "evidence_sha256": {str(path.relative_to(ROOT) if path.is_absolute() else path): digest(path) for path in sources},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    if args.phase == "prepare":
        output, generated, _ = setup()
        output.mkdir()
        for name, source in generated.items():
            (output / name).write_text(source)
        print(output)
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
