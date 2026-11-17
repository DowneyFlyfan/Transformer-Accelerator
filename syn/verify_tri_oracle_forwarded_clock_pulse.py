"""Verify both receiver clock pulses and combine them with the pad setup and hold checks."""
from decimal import Decimal
import json
from pathlib import Path
import re

from verify_tri_oracle_loaded_forwarded_pads import LOADS, ROOT, WORK as HARNESS, digest, read


WORK = HARNESS.with_name("forwarded_clock_pulse")
BASE = Path("records/tri_oracle_loaded_forwarded_pads.json")
TARGETS = Path("records/paper_result_targets.json")
TCL = Path("syn/tri_oracle_report_forwarded_clock_pulse.tcl")
REPORT_ROUNDING = Decimal("0.002")
PERIOD = Decimal("1.72414")
RECEIVER = "peer_capture_0/CP"


def verify_pulses(report, view, prefix="", clock_cell="PDDW16DGZ_H_G", *, complementary=True):
    pulses = {}
    receiver_pin = prefix + RECEIVER
    for path in re.split(r"(?m)(?=^Path \d+:)", report.read_text())[1:]:
        assert re.search(rf"(?m)^\s*View:\s+{view}$", path), report
        assert f"PulseWidth Check with Pin {receiver_pin}->CP" in path, report
        start, end = re.findall(rf"(?:Startpoint|Endpoint):\s+\(([RF])\) {receiver_pin}\b", path)
        assert (start, end) in (("R", "F"), ("F", "R")), report
        clocks = re.findall(r"Clock:\s+\(([RF])\) core_clock", path)
        assert clocks == [end, start], report
        number = r"(-?\d+\.\d+)"
        capture, launch = map(Decimal, re.search(r"Arrival:=\s+" + number + r"\s+" + number, path).groups())
        required = Decimal(re.search(r"PulseWidth:-\s+" + number, path)[1])
        uncertainty = Decimal(re.search(r"Uncertainty:-\s+" + number, path)[1])
        slack = Decimal(re.search(r"Slack:=\s+" + number, path)[1])
        assert required > 0 and uncertainty == Decimal("0.050"), report
        assert abs(capture - launch - required - uncertainty - slack) <= REPORT_ROUNDING, report
        pad_times = []
        for block, edge, expected in zip(path.split("Other End Path:"), (start, end), (launch, capture), strict=True):
            pad = re.search(rf"(?m)^\s+{prefix}clock_pad/PAD\s+{clock_cell}\s+{number}\s+{number}\s+{edge}[ \t]*$", block)
            receiver = re.search(rf"(?m)^\s+{receiver_pin}\s+DFQD1BWP12T40P140\s+{number}\s+{number}\s+{edge}[ \t]*$", block)
            assert pad and receiver, report
            assert Decimal(pad[1]) > 0 and abs(Decimal(receiver[2]) - expected) <= REPORT_ROUNDING, report
            pad_times.append(Decimal(pad[2]))
        level = "high" if start == "R" else "low"
        assert level not in pulses, report
        pulses[level] = {
            "receiver_width_ps": int((capture - launch) * 1000),
            "pad_reference_width_ps": int((pad_times[1] - pad_times[0]) * 1000),
            "receiver_minimum_ps": int(required * 1000),
            "margin_ps": int(slack * 1000),
        }
    assert pulses.keys() == {"high", "low"}, report
    for quantity in ("receiver_width_ps", "pad_reference_width_ps"):
        widths = [pulse[quantity] for pulse in pulses.values()]
        assert all(0 < width < PERIOD * 1000 for width in widths), report
        if complementary:
            assert abs(sum(widths) - PERIOD * 1000) <= REPORT_ROUNDING * 1000, report
    return pulses


def verify():
    console = WORK / "console.log"
    transcript = console.read_text()
    assert re.search(r"(?m)^TRI_ORACLE_FORWARDED_CLOCK_PULSE_FINISHED$", transcript)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", transcript)
    base = read(BASE)
    paper_rates = {point["clock_megahertz"] for point in read(TARGETS)["silicon"]["reported_system_power_watts"]}
    assert base["core_clock_mhz"] in paper_rates and abs(1000 / PERIOD - base["core_clock_mhz"]) < Decimal("0.001")
    harness = [HARNESS / name for name in ("netlist.v", "tx_load_mmmc.tcl", "pads.lef", "pad_slow.lib", "pad_fast.lib")]
    harness.extend(HARNESS / f"c{clock}_d{data}.sdc" for clock, data in LOADS)
    assert all(digest(path) == base["evidence_sha256"][str(path)] for path in harness)
    sampled = {}
    reports = []
    for clock, data in LOADS:
        scenario = f"c{clock}_d{data}"
        corners = {}
        for corner, label in (("slow", "setup"), ("fast", "hold")):
            view = f"{label}_{scenario}"
            report = WORK / f"{view}.rpt"
            corners[corner] = verify_pulses(report, view)
            reports.append(report)
        pulse_margin = min(pulse["margin_ps"] for levels in corners.values() for pulse in levels.values())
        prior = base["scenarios_by_clock_then_data_load_pf"][scenario]
        sampled[scenario] = {
            "corners": corners,
            "minimum_pulse_margin_ps": pulse_margin,
            "minimum_setup_margin_ps": prior["minimum_setup_margin_ps"],
            "minimum_hold_margin_ps": prior["minimum_hold_margin_ps"],
        }
    # Changing data-pad load in isolation cannot change the clock waveform in this model.
    for first, second in (("c5_d5", "c5_d10"), ("c5_d5", "c5_d25"), ("c10_d5", "c10_d10")):
        assert sampled[first]["corners"] == sampled[second]["corners"]
    return {
        "state": "forwarded_clock_pulse_limits_verified_through_installed_pad_and_receiver_probe",
        "core_clock_megahertz": base["core_clock_mhz"],
        "pulse_uncertainty_ps": 50,
        "receiver_cell": "DFQD1BWP12T40P140",
        "scenarios_by_clock_then_data_load_pf": sampled,
        "scope": "Minimum high and low pulse-width checks use the existing propagated clock pad and a library flop "
                 "as the receiver probe. Pulse requirements are specific to that modeled flop and its effective clock "
                 "slew. Actual package, board, receiver and core clock tree are not characterized by this test.",
        "evidence_sha256": {str(path): digest(path) for path in (
            BASE, TARGETS, TCL, Path(__file__).resolve().relative_to(ROOT), console, *harness, *reports,
        )},
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), indent=2, sort_keys=True))
