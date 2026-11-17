"""Compare installed clock inverters on the loaded wide request boundary."""

import argparse
from decimal import Decimal
from itertools import chain
import json
from pathlib import Path
import re

from prepare_tri_oracle_booth_packet_replay import replace_once
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, digest
from verify_tri_oracle_forwarded_clock_pulse import verify_pulses
from verify_tri_oracle_wide_loaded_pads import PAD, TARGET_HOLD, TARGET_SETUP


BASE = Path("records/tri_oracle_wide_loaded_pads.json")
DRIVER = Path("syn/tri_oracle_compare_forwarded_clock_pads.tcl")
SUFFIX = "BWP12T40P140"
DRIVERS = tuple(f"{family}{strength}{SUFFIX}"
                for family, sizes in (("CKND", (0, 1, 2, 4, 8, 12, 16)),
                                      ("DCCKND", (4, 8, 12, 16)))
                for strength in sizes)
LOADS = (5, 10)
WRAPPER = "tri_oracle_loaded_request_pads"
SENDER = "tri_oracle_memory_tx_credit_wide"
NUMBER = r"(-?[\d.]+)"


def setup():
    proof = json.loads(BASE.read_text())
    baseline_evidence = proof["evidence_sha256"]
    original, = (ROOT / path for path in baseline_evidence if path.endswith("/loaded_horizontal_pads/netlist.v"))
    original_dir = original.parent
    out = original_dir.with_name("wide_forwarded_clock_drivers")
    files = [original, original_dir / "tx_load_mmmc.tcl", *(original_dir / f"c{load}_d10.sdc" for load in LOADS)]
    assert all(digest(path) == baseline_evidence[str(path.relative_to(ROOT))] for path in files)
    lib_names = ("pad_slow.lib", "pad_fast.lib", "pads.lef")
    for name in lib_names:
        model = (original_dir / name).resolve(strict=True)
        assert digest(model) == baseline_evidence[str(model.relative_to(ROOT))]
        files.append(model)
    source, bond = original.read_text().split(f"module {WRAPPER} (", 1)
    declarations = ["  input wire clk, rst_n, in_valid, pad_credit", "  input wire [21:0] in_word"]
    modules, instances = [], []
    old = f"{DRIVERS[0]} g689(.I (clk), .ZN (pad_clock))"
    for index, cell in enumerate(DRIVERS):
        sender = f"{SENDER}_{index}"
        variant = f"wide_loaded_driven_{index}"
        mapped = replace_once(source, f"module {SENDER}(", f"module {sender}(")
        mapped = replace_once(mapped, old, f"{cell} g689(.I (clk), .ZN (pad_clock))")
        wrapper = replace_once(bond, f"{SENDER} sender", f"{sender} sender")
        modules.extend((mapped, f"module {variant} (" + wrapper))
        declarations.extend((f"  output wire clock_{index}, valid_{index}",
                             f"  output wire [21:0] data_{index}",
                             f"  output wire [22:0] probe_{index}"))
        instances.append(
            f"  {variant} variant_{index} (\n"
            "    .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_word(in_word), .pad_credit(pad_credit),\n"
            "    .in_ready(), .protocol_error(),\n"
            f"    .tx_valid(valid_{index}), .tx_clock(clock_{index}), .tx_data(data_{index}), .peer_probe(probe_{index})\n"
            "  );\n")
    root = "module wide_forwarded_clock_drivers (\n" + ",\n".join(declarations) + "\n);\n"
    mapped = "\n".join(modules) + "\n" + root + "".join(instances) + "endmodule\n"
    script = DRIVER.read_text()
    for before, after in (
        ("set root [file dirname [file dirname [file normalize [info script]]]]", f"set root {{{ROOT}}}"),
        ("set input $root/.cache/physical/whole_chip_xcelium_speed/loaded_forwarded_pads", f"set input {{{original_dir}}}"),
        ("set out [file normalize $::env(TRI_ORACLE_CLOCK_PAD_COMPARISON)]", f"set out {{{out}}}"),
        ("-top compare_forwarded_clock_pads", "-top wide_forwarded_clock_drivers"),
        ("[get_ports clock_*]] != 8", f"[get_ports clock_*]] != {len(DRIVERS)}"),
        ("[get_ports {data_* valid_*}]] != 72", f"[get_ports {{data_* valid_*}}]] != {23 * len(DRIVERS)}"),
        ("{$i < 8}", f"{{$i < {len(DRIVERS)}}}"),
        ("[sizeof_collection $peer] != 9", "[sizeof_collection $peer] != 23"),
    ):
        script = replace_once(script, before, after)
    assert script.count("-max_paths 9") == 2
    script = script.replace("-max_paths 9", "-nworst 1 -max_paths 23")
    return out, {"netlist.v": mapped, "measure.tcl": script}, proof, files


def data_margin(report, prefix, view, driver, mode, edge):
    timing = "Setup" if mode == "setup" else "Hold"
    requirement = TARGET_SETUP if mode == "setup" else TARGET_HOLD
    margins = {}
    for path in re.split(r"(?m)(?=^Path \d+:)", report.read_text())[1:]:
        transition, bit = re.search(rf"Endpoint:\s+\(([RF])\) {prefix}peer_capture_(\d+)/D", path).groups()
        assert transition == edge[0].upper() and bit not in margins
        assert re.search(rf"(?m)^\s*View:\s+{view}$", path)
        assert timing + " Check" in path
        assert re.findall(r"Clock:\s+\(([RF])\) core_clock", path)[:2] == ["R", "F"]
        data, clock = path.split("Other End Path:", 1)
        assert re.search(rf"{prefix}data_pad_{bit}/PAD\s+-\s+I->PAD\s+{transition}\s+{PAD}", data)
        assert re.search(rf"{prefix}clock_pad/PAD\s+-\s+I->PAD\s+R\s+{PAD}", clock)
        assert re.search(rf"{prefix}sender/g689/ZN\s+-\s+I->ZN\s+R\s+{driver}", clock)
        check = Decimal(re.search(rf"\b{timing}:[+-]\s*" + NUMBER, path)[1])
        raw = Decimal(re.search(r"Slack:=\s*" + NUMBER, path)[1])
        margins[bit] = int((raw + check - requirement) * 1000)
    assert set(margins) == {str(index) for index in range(23)}, report
    return min(margins.values())


def verify():
    out, generated, baseline, inputs = setup()
    for name, text in generated.items():
        assert (out / name).read_text() == text
    status_file = out / "native_status.json"
    native = json.loads(status_file.read_text())
    assert native["exit_status"] == 0 and native["stop_reason"] is None
    console = out / "console.log"
    log = console.read_text()
    assert re.search(r"(?m)^TRI_ORACLE_CLOCK_PAD_COMPARISON_FINISHED$", log)
    assert not re.search(r"(?m)^\*\*?ERROR:", log)
    identity = {}
    for kind in ("ssg0p9v125c", "ffg1p05vm40c"):
        library = ROOT / f".cache/physical/library/tcbn28hpcplusbwp12t40p140{kind}.lib"
        inputs.append(library)
        text = library.read_text()
        for driver in DRIVERS:
            cell = re.search(rf"(?ms)^cell\s+\({driver}\)\s*\{{(.*?)(?=^cell\s+\()", text)[1]
            assert re.search(r'function\s*:\s*"(?:!I|\(!I\))"', cell)
            area = Decimal(re.search(r"area\s*:\s*([\d.]+)", cell)[1])
            if driver in identity:
                assert identity[driver] == float(area)
            else:
                identity[driver] = float(area)
    reports = []
    results = {}
    for index, driver in enumerate(DRIVERS):
        prefix = f"variant_{index}/"
        loads = {}
        for load in LOADS:
            item = {}
            pulses = []
            for mode, corner in (("setup", "slow"), ("hold", "fast")):
                samples = []
                view = f"{corner}_{load}"
                for edge in ("rise", "fall"):
                    report = out / f"{index}_{load}_{mode}_{edge}.rpt"
                    samples.append(data_margin(report, prefix, view, driver, mode, edge))
                    reports.append(report)
                item[f"minimum_{mode}_margin_ps"] = min(samples)
                pulse = out / f"{index}_{load}_pulse_{corner}.rpt"
                measured = verify_pulses(pulse, view, prefix, PAD)
                pulses.extend(pulse["margin_ps"] for pulse in measured.values())
                reports.append(pulse)
            item["minimum_pulse_margin_ps"] = min(pulses)
            if index == 0:
                reference = baseline["clock_and_data_load_scenarios_pf"][f"c{load}_d10"]
                expected_pulse = min(p["margin_ps"] for p in chain(reference["setup_clock_pulses"].values(),
                                                                  reference["hold_clock_pulses"].values()))
                assert abs(expected_pulse - item["minimum_pulse_margin_ps"]) <= 3
                assert all(abs(reference[f"minimum_{kind}_margin_ps"] - item[f"minimum_{kind}_margin_ps"]) <= 3
                           for kind in ("setup", "hold"))
            loads[str(load)] = item
        results[driver] = {"clock_cell_area_um2": identity[driver], "clock_load_pf": loads}
    sources = [BASE, DRIVER, Path(__file__).resolve(), status_file, console, out / "views.tcl",
               *(out / key for key in generated), *(out / f"load_{load}.sdc" for load in LOADS),
               *inputs, *reports]
    return {
        "state": "wide_forwarded_clock_inverters_compared_on_horizontal_pads",
        "core_clock_megahertz": 580, "data_load_pf": 10, "setup_hold_peer_pins": 23,
        "drivers": results, "scope": "Standalone timing with a single inverter changed per variant. "
        "Every clock and data output uses the installed horizontal 16 mA pad. Lumped loads exclude "
        "routing, package and board skew, power integrity and statistical variation.",
        "evidence_sha256": {str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path): digest(path) for path in sources},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    if args.phase == "prepare":
        folder, files, _, _ = setup()
        folder.mkdir()
        for name, text in files.items():
            (folder / name).write_text(text)
        print(folder)
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
