"""Measure the widened outgoing link with its actual horizontal pad orientation."""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import re

from prepare_tri_oracle_booth_packet_replay import replace_once
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, digest
from verify_tri_oracle_forwarded_clock_pulse import verify_pulses
from verify_tri_oracle_loaded_forwarded_pads import HEADER, LOADS, TARGET_HOLD, TARGET_SETUP, TIMING, WORK
from verify_tri_oracle_wide_request_trial import MODULE, TX


TRIAL = Path("records/tri_oracle_wide_request_trial.json")
PLAN = Path("records/tri_oracle_wide_request_native_import_inputs.json")
BASELINE = Path("records/tri_oracle_loaded_forwarded_pads.json")
OUTPUTS = [f"memory_tx_data[{bit}]" for bit in range(22)] + ["memory_tx_valid"]
PAD = "PDDW16DGZ_H_G"
CASES = (*LOADS, (25, 25))


def setup():
    evidence = {}

    def pin(path, expected=None):
        key = str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
        result = digest(path)
        assert expected is None or expected == result, path
        evidence[key] = result
        return path

    trial, plan, baseline = (json.loads(pin(record).read_text()) for record in (TRIAL, PLAN, BASELINE))
    mapped, = (pin(Path(path), sha) for path, sha in trial["evidence_sha256"].items()
               if path.endswith("/wide_request_trial/genus/netlist.v"))
    assignment, = (pin(Path(path), sha) for path, sha in plan["evidence_sha256"].items()
                   if path.endswith("/native_import/pad_assignment.json"))
    locations = json.loads(assignment.read_text())["signals"]
    properties = [locations[name] for name in OUTPUTS + ["memory_tx_clock"]]
    assert all(item["direction"] == "OUTPUT" and item["edge"] == "bottom" for item in properties)
    anchor_x = [item["anchor"][0] for item in properties]
    pad_span_um = (max(anchor_x) - min(anchor_x)) / 2000
    libraries = {name: pin(WORK / name, baseline["evidence_sha256"][str(WORK / name)]).resolve()
                 for name in ("pad_slow.lib", "pad_fast.lib", "pads.lef")}
    wide = HEADER
    for old, new in ((f"{TX} sender", f"{MODULE} sender"), ("[7:0] tx_data", "[21:0] tx_data"),
                     ("[8:0] peer_probe", "[22:0] peer_probe"), ("[7:0] data_word", "[21:0] data_word")):
        wide = replace_once(wide, old, new)
    wide += f"  {PAD} clock_pad (.I(source_clock), .OEN(1'b0), .REN(1'b1), .PAD(tx_clock), .C());\n"
    for bit, logical in enumerate(OUTPUTS):
        name = logical.removeprefix("memory_")
        data = f"data_word[{bit}]" if bit < 22 else "data_valid"
        wide += (f"  {PAD} data_pad_{bit} (.I({data}), .OEN(1'b0), .REN(1'b1), .PAD({name}), .C());\n"
                 f"  DFQD1BWP12T40P140 peer_capture_{bit} (.CP(tx_clock), .D({name}), .Q(peer_probe[{bit}]));\n")
    netlist = mapped.read_text() + "\n" + wide + "endmodule\n"
    out = mapped.resolve().parents[1] / "loaded_horizontal_pads"
    driver = pin(TIMING, baseline["evidence_sha256"][str(TIMING)]).read_text()
    driver = replace_once(driver, "set root [file dirname [file dirname [file normalize [info script]]]]", f"set root {{{ROOT}}}")
    driver = replace_once(driver, "set out [file normalize $::env(TRI_ORACLE_LOADED_PADS_OUTPUT)]", f"set out {{{out}}}")
    cases_line = "set cases {" + " ".join(f"{{{clock} {data}}}" for clock, data in CASES) + "}"
    driver, count = re.subn(r"(?m)^set cases .*$", cases_line, driver)
    assert count == 1 and driver.count("-max_paths 9") == 2
    driver = replace_once(driver, "!= 9", "!= 23").replace("-max_paths 9", "-nworst 1 -max_paths 23")
    # Innovus reports pulse checks only from views active for setup.
    driver = replace_once(driver, "set_analysis_view -setup $setup_views -hold $hold_views",
                          "set_analysis_view -setup [concat $setup_views $hold_views] -hold $hold_views")
    end = "}\nputs TRI_ORACLE_LOADED_FORWARD_PADS_FINISHED"
    driver = replace_once(driver, end,
                          "    foreach check {setup hold} {\n"
                          "        report_min_pulse_width -pins peer_capture_0/CP -path_type full_clock "
                          "-view ${check}_$id > $out/${id}_${check}_pulse.rpt\n"
                          "    }\n" + end)
    return out, {"netlist.v": netlist, "measure.tcl": driver}, libraries, evidence, pad_span_um


def path_margins(report, view, mode, edge, pad):
    timing = "Setup" if mode == "setup" else "Hold"
    need = TARGET_SETUP if mode == "setup" else TARGET_HOLD
    margins = {}
    number = r"(-?[\d.]+)"
    for path in re.split(r"(?m)(?=^Path \d+:)", report.read_text())[1:]:
        transition, bit = re.search(r"Endpoint:\s+\(([RF])\) peer_capture_(\d+)/D", path).groups()
        bit = int(bit)
        assert bit not in margins and transition == edge[0].upper(), report
        assert timing + " Check" in path and re.search(rf"(?m)^\s*View:\s+{view}$", path), report
        assert re.findall(r"Clock:\s+\(([RF])\) core_clock", path)[:2] == ["R", "F"]
        capture, launch = map(Decimal, re.search(r"Clock Edge:\+\s+" + number + r"\s+" + number, path).groups())
        delta = capture - launch if mode == "setup" else launch - capture
        assert Decimal("0.85") < delta < Decimal("0.88")
        data_block, clock_block = path.split("Other End Path:")
        arrivals = []
        for block, pin, polarity in ((data_block, f"data_pad_{bit}/PAD", transition), (clock_block, "clock_pad/PAD", "R")):
            arc = re.search(rf"(?m)^\s+{pin}\s+-\s+I->PAD\s+{polarity}\s+{pad}\s+\d+"
                            rf"\s+{number}\s+{number}\s+{number}[ \t]*$", block)
            slew, delay, arrival = map(Decimal, arc.groups())
            assert slew > 0 and delay > 0, report
            arrivals.append(arrival)
        delta = arrivals[1] - arrivals[0] if mode == "setup" else arrivals[0] - arrivals[1]
        uncertainty = Decimal(re.search(r"Uncertainty:[+-]\s+" + number, path)[1])
        check = Decimal(re.search(rf"\b{timing}:[+-]\s*" + number, path)[1])
        reported = Decimal(re.search(r"Slack:=\s*" + number, path)[1])
        assert uncertainty == Decimal("0.050") and abs(delta - uncertainty - check - reported) <= Decimal("0.002")
        margins[bit] = int((reported + check - need) * 1000)
    assert margins.keys() == set(range(23)), report
    return margins


def verify():
    out, generated, libraries, evidence, pad_span_um = setup()
    for name, text in generated.items():
        assert (out / name).read_text() == text
    assert all((out / name).resolve() == source for name, source in libraries.items())
    console = out / "console.log"
    status = out / "native_status.json"
    native = json.loads(status.read_text())
    assert native["exit_status"] == 0 and native["stop_reason"] is None
    log = console.read_text()
    assert re.search(r"(?m)^TRI_ORACLE_LOADED_FORWARD_PADS_FINISHED$", log)
    assert not re.search(r"(?m)^\*\*?ERROR:", log)
    files = [console, status, out / "tx_load_mmmc.tcl", *(out / name for name in generated)]
    results = {}
    for clock, data in CASES:
        case = f"c{clock}_d{data}"
        sdc = out / f"{case}.sdc"
        assert f"set_load {clock} [get_ports tx_clock]" in sdc.read_text()
        assert f"set_load {data} [get_ports {{tx_data* tx_valid}}]" in sdc.read_text()
        files.append(sdc)
        metrics = {}
        for mode in ("setup", "hold"):
            view = f"{mode}_{case}"
            minimum = []
            for edge in ("rise", "fall"):
                report = out / f"{case}_{mode}_{edge}.rpt"
                margins = path_margins(report, view, mode, edge, PAD)
                worst = min(margins, key=margins.get)
                metrics[f"{mode}_{edge}_margin_ps"] = margins[worst]
                metrics[f"{mode}_{edge}_worst_pin"] = OUTPUTS[worst]
                minimum.append(margins[worst])
                files.append(report)
            pulse = out / f"{case}_{mode}_pulse.rpt"
            metrics[f"{mode}_clock_pulses"] = verify_pulses(pulse, view, clock_cell=PAD)
            files.append(pulse)
            metrics[f"minimum_{mode}_margin_ps"] = min(minimum)
        results[case] = metrics
    pin_scope = ("syn/verify_tri_oracle_forwarded_clock_pulse.py", str(Path(__file__).resolve().relative_to(ROOT)))
    evidence.update({str(path.relative_to(ROOT)): digest(path) for path in files + [ROOT / name for name in pin_scope]})
    return {
        "state": "wide_forwarded_clock_and_horizontal_data_pads_timed",
        "pad_cell": PAD, "modeled_peers": 23, "core_clock_megahertz": 580, "bottom_edge_anchor_span_um": pad_span_um,
        "peer_setup_requirement_ps": 200, "peer_hold_requirement_ps": 100,
        "clock_and_data_load_scenarios_pf": results, "native_resource_status": native,
        "scope": "Actual mapped widened sender and horizontal 16 mA library pads driving lumped loads "
                 "and peer flip-flop probes. Clock and data setup, hold and pulse-width evidence uses "
                 "the installed libraries. Routing, package, board and simultaneous switching are excluded.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    if args.phase == "prepare":
        output, files, sources, _, _ = setup()
        output.mkdir()
        for name, text in files.items():
            (output / name).write_text(text)
        for name, path in sources.items():
            (output / name).symlink_to(path)
        print(output)
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
