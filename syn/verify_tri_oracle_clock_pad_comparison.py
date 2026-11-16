"""Compare the strongest installed pad variants on the mapped forwarded clock."""
import argparse
from itertools import product
import json
from pathlib import Path
import re

from verify_tri_oracle_forwarded_clock_pulse import verify_pulses
from verify_tri_oracle_loaded_forwarded_pads import ROOT, WORK as HARNESS, digest, paths, read


BASE_TIMING = Path("records/tri_oracle_loaded_forwarded_pads.json")
BASE_PULSE = Path("records/tri_oracle_forwarded_clock_pulse.json")
TCL = Path("syn/tri_oracle_compare_forwarded_clock_pads.tcl")
PARSERS = (Path("syn/verify_tri_oracle_loaded_forwarded_pads.py"),
           Path("syn/verify_tri_oracle_forwarded_clock_pulse.py"))
WORK = HARNESS.with_name("clock_pad_comparison")
CELLS = tuple(f"PD{pull}W16{schmitt}DGZ_{side}_G" for pull, schmitt, side in
              product(("D", "U"), ("", "S"), ("H", "V")))
LOADS = (5, 10)


def inputs():
    prior = read(BASE_TIMING)["evidence_sha256"]
    files = [HARNESS / name for name in ("netlist.v", "tx_load_mmmc.tcl", "pads.lef", "pad_slow.lib", "pad_fast.lib")]
    files.extend(HARNESS / f"c{load}_d10.sdc" for load in LOADS)
    assert all(digest(path) == prior[str(path)] for path in files)
    return files


def netlist(source):
    sender, wrapper = source.split("module tri_oracle_loaded_request_pads (", 1)
    ports = ["  input wire clk, rst_n, in_valid, pad_credit", "  input wire [21:0] in_word"]
    instances = []
    wrappers = []
    for index, cell in enumerate(CELLS):
        module = f"loaded_clock_pad_{index}"
        variant, count = re.subn(r"\bPDDW16DGZ_H_G clock_pad \(", f"{cell} clock_pad (", wrapper)
        assert count == 1
        wrappers.append(f"module {module} (" + variant)
        ports.extend((f"  output wire clock_{index}, valid_{index}", f"  output wire [7:0] data_{index}",
                      f"  output wire [8:0] probe_{index}"))
        instances.append(f"""  {module} variant_{index} (
    .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_word(in_word), .pad_credit(pad_credit),
    .in_ready(), .protocol_error(), .tx_valid(valid_{index}), .tx_clock(clock_{index}),
    .tx_data(data_{index}), .peer_probe(probe_{index})
  );""")
    top = ("module compare_forwarded_clock_pads (\n" + ",\n".join(ports) + "\n);\n"
           + "\n".join(instances) + "\nendmodule\n")
    return sender + "\n".join(wrappers) + "\n" + top


def prepare():
    source = inputs()[0]
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "netlist.v").write_text(netlist(source.read_text()))


def verify():
    harness = inputs()
    design = WORK / "netlist.v"
    assert design.read_text() == netlist(harness[0].read_text())
    console = WORK / "console.log"
    transcript = console.read_text()
    assert re.search(r"(?m)^TRI_ORACLE_CLOCK_PAD_COMPARISON_FINISHED$", transcript)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", transcript)
    files = [*harness, design, console, WORK / "views.tcl", *(WORK / f"load_{load}.sdc" for load in LOADS)]
    baseline = read(BASE_PULSE)["scenarios_by_clock_then_data_load_pf"]
    results = {}
    for index, cell in enumerate(CELLS):
        prefix = f"variant_{index}/"
        loads = {}
        for load in LOADS:
            checks = {}
            for mode, corner in (("setup", "slow"), ("hold", "fast")):
                margins = []
                for edge in ("rise", "fall"):
                    report = WORK / f"{index}_{load}_{mode}_{edge}.rpt"
                    margins.extend(paths(report, f"{corner}_{load}", mode, edge, prefix, cell).values())
                    files.append(report)
                checks[f"minimum_{mode}_margin_ps"] = int(min(margins))
            pulse_margins = []
            for corner in ("slow", "fast"):
                report = WORK / f"{index}_{load}_pulse_{corner}.rpt"
                pulses = verify_pulses(report, f"{corner}_{load}", prefix, cell)
                pulse_margins.extend(item["margin_ps"] for item in pulses.values())
                files.append(report)
            checks["minimum_pulse_margin_ps"] = min(pulse_margins)
            if not index:
                reference = baseline[f"c{load}_d10"]
                assert all(abs(reference[key] - value) <= 3 for key, value in checks.items()), (checks, reference)
            loads[str(load)] = checks
        results[cell] = loads
    return {
        "state": "strongest_eight_installed_clock_pads_compared_with_native_timing",
        "core_clock_megahertz": 580,
        "data_pad_load_pf": 10,
        "scenarios_by_clock_load_pf": results,
        "scope": "Change exclusively the forwarded clock pad master in eight copies of the same mapped harness. "
                 "Check native setup, hold and receiver pulse width in the slow and fast library views at the tested "
                 "lumped loads. Routed interconnect, package, board and external receiver are outside this model.",
        "evidence_sha256": {str(path): digest(path) for path in (
            BASE_TIMING, BASE_PULSE, TCL, Path(__file__).resolve().relative_to(ROOT), *PARSERS, *files,
        )},
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify"))
    if parser.parse_args().mode == "prepare":
        prepare()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
