"""Check the mapped request sender through loaded clock and data pads."""
import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import tarfile

from measure_tri_oracle_serial_memory_requests import digest, read
from measure_tri_oracle_credited_request_link import ROOT, WORK as LINK


WORK = Path(".cache/physical/whole_chip_xcelium_speed/loaded_forwarded_pads")
LINK_PROOF = Path("records/tri_oracle_credited_request_link.json")
PAD_PROOF = Path("records/tri_oracle_bonded_pad_timing.json")
TIMING = Path("syn/tri_oracle_load_forwarded_pads.tcl")
SLOW = "ssg0p81v1p62v125c"
FAST = "ffg0p99v1p98vm40c"
LOADS = [(5, 5), (5, 10), (10, 5), (10, 10), (5, 25), (25, 5)]
PADS = ("PDDW16DGZ_H_G", "PDDW16DGZ_V_G")
TARGET_SETUP = Decimal("0.20")
TARGET_HOLD = Decimal("0.10")

HEADER = """module tri_oracle_loaded_request_pads (
  input wire clk, rst_n, in_valid, pad_credit,
  input wire [21:0] in_word,
  output wire in_ready, protocol_error, tx_valid, tx_clock,
  output wire [7:0] tx_data,
  output wire [8:0] peer_probe
);
  wire data_valid, source_clock;
  wire [7:0] data_word;
  tri_oracle_memory_tx_credit sender (
    .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready), .in_word(in_word),
    .pad_credit(pad_credit), .protocol_error(protocol_error), .pad_valid(data_valid),
    .pad_clock(source_clock), .pad_data(data_word)
  );
"""


def prepare(out):
    out.mkdir(parents=True, exist_ok=True)
    proof = read(PAD_PROOF)
    stored = proof["evidence_sha256"]
    archive, = [Path(name) for name in stored if name.endswith("_nldm.tar.gz")]
    geometry, = [Path(name) for name in stored if name.endswith("sefu10lm.tar.gz")]
    assert all(digest(path) == stored[str(path)] for path in (archive, geometry))
    with tarfile.open(archive) as bundle:
        for mode, corner in (("slow", SLOW), ("fast", FAST)):
            path, = [name for name in proof["pad_library_member_sha256"] if name.endswith(corner + ".lib")]
            with bundle.extractfile(path) as stream:
                data = stream.read()
            assert sha256(data).hexdigest() == proof["pad_library_member_sha256"][path]
            (out / f"pad_{mode}.lib").write_bytes(data)
    with tarfile.open(geometry) as bundle:
        item, = [member for member in bundle if member.isfile() and member.name.endswith(".lef")]
        with bundle.extractfile(item) as stream:
            (out / "pads.lef").write_bytes(stream.read())
    sender = LINK / "genus/netlist.v"
    assert digest(sender) == read(LINK_PROOF)["evidence_sha256"][str(sender)]
    text = HEADER
    text += "  PDDW16DGZ_H_G clock_pad (.I(source_clock), .OEN(1'b0), .REN(1'b1), .PAD(tx_clock), .C());\n"
    for bit in range(9):
        name = f"tx_data[{bit}]" if bit < 8 else "tx_valid"
        data = f"data_word[{bit}]" if bit < 8 else "data_valid"
        text += (f"  {PADS[bit % 2]} data_pad_{bit} (.I({data}), .OEN(1'b0), .REN(1'b1), .PAD({name}), .C());\n"
                 f"  DFQD1BWP12T40P140 peer_capture_{bit} (.CP(tx_clock), .D({name}), .Q(peer_probe[{bit}]));\n")
    (out / "netlist.v").write_text(sender.read_text() + "\n" + text + "endmodule\n")


def paths(report, view, mode, edge, prefix="", clock_cell=PADS[0]):
    text = report.read_text()
    timing = "Setup" if mode == "setup" else "Hold"
    items = re.split(r"(?m)(?=^Path \d+:)", text)[1:]
    margins = {}
    for item in items:
        endpoint_pattern = rf"Endpoint:\s+\(([RF])\) {prefix}(peer_capture_(\d+)/D)"
        data_edge, endpoint, bit = re.search(endpoint_pattern, item).groups()
        assert endpoint not in margins and timing + " Check" in item, report
        assert data_edge == edge[0].upper() and re.search(rf"(?m)^\s*View:\s+{view}$", item), report
        source, dest = re.findall(r"Clock:\s+\(([RF])\) core_clock", item)[:2]
        assert (source, dest) == ("R", "F"), report
        capture, launch = map(Decimal, re.search(r"Clock Edge:\+\s+(-?[\d.]+)\s+(-?[\d.]+)", item).groups())
        assert Decimal("0.85") < abs(capture - launch) < Decimal("0.88"), report
        assert capture > launch if mode == "setup" else capture < launch
        data_path, clock_path = item.split("Other End Path:")
        number = r"(-?[\d.]+)"
        arrivals = []
        for block, pin, cell, transition in (
            (data_path, f"{prefix}data_pad_{bit}/PAD", PADS[int(bit) % 2], data_edge),
            (clock_path, f"{prefix}clock_pad/PAD", clock_cell, "R"),
        ):
            pad_arc = rf"(?m)^\s+{pin}\s+-\s+I->PAD\s+{transition}\s+{cell}\s+\d+"
            line = re.search(pad_arc + rf"\s+{number}\s+{number}\s+{number}[ \t]*$", block)
            assert line is not None, (report, pin)
            slew, delay, arrival = map(Decimal, line.groups())
            assert slew > 0 and delay > 0, report
            arrivals.append(arrival)
        separation = arrivals[1] - arrivals[0] if mode == "setup" else arrivals[0] - arrivals[1]
        uncertainty = Decimal(re.search(r"Uncertainty:[+-]\s+" + number, item)[1])
        assert uncertainty == Decimal("0.050"), report
        check_val = Decimal(re.search(rf"\b{timing}:[+-]\s*(-?[\d.]+)", item)[1])
        raw_slack = Decimal(re.search(r"Slack:=\s*(-?[\d.]+)", item)[1])
        requirement = TARGET_SETUP if mode == "setup" else TARGET_HOLD
        assert abs(separation - uncertainty - check_val - raw_slack) <= Decimal("0.002"), report
        margins[endpoint] = (raw_slack + check_val - requirement) * 1000
    assert set(margins) == {f"peer_capture_{bit}/D" for bit in range(9)}, report
    return margins


def verify(out):
    console = out / "console.log"
    assert re.search(r"(?m)^TRI_ORACLE_LOADED_FORWARD_PADS_FINISHED$", console.read_text())
    results = {}
    files = [out / name for name in ("netlist.v", "tx_load_mmmc.tcl", "pads.lef", "pad_slow.lib", "pad_fast.lib")]
    for clock, data in LOADS:
        name = f"c{clock}_d{data}"
        files.append(out / f"{name}.sdc")
        row = {}
        for mode in ("setup", "hold"):
            view = f"{mode}_{name}"
            for edge in ("rise", "fall"):
                report = out / f"{name}_{mode}_{edge}.rpt"
                items = paths(report, view, mode, edge)
                row[f"minimum_{mode}_{edge}_margin_ps"] = float(min(items.values()))
                files.append(report)
            row[f"minimum_{mode}_margin_ps"] = min(row[f"minimum_{mode}_{edge}_margin_ps"] for edge in ("rise", "fall"))
        results[name] = row
    assert results["c5_d25"]["minimum_setup_margin_ps"] < results["c5_d10"]["minimum_setup_margin_ps"]
    return {
        "state": "loaded_physical_forwarded_pads_timed_with_explicit_capture_probes",
        "core_clock_mhz": 580, "checked_receivers": 9, "data_transitions_per_receiver": 2,
        "peer_setup_budget_ps": 200, "peer_hold_budget_ps": 100,
        "scenarios_by_clock_then_data_load_pf": results,
        "scope": "The mapped sender, inverting clock path and installed output pad timing arcs drive peer timing probes. "
                 "The model replaces probe setup and hold time with explicit 200 and 100 ps external requirements. "
                 "The pad and core models use different characterized voltages. Lumped load cases exclude routing, "
                 "board and package flight skew, power integrity, and on-chip variation. Clock pulse width is not "
                 "qualified by these setup and hold checks. This is a timing screen for the outgoing link.",
        "evidence_sha256": {str(p.relative_to(ROOT) if p.is_absolute() else p): digest(p)
                            for p in (*files, console, LINK_PROOF, PAD_PROOF, TIMING, Path(__file__).resolve())},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify"))
    options = parser.parse_args()
    assert Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    out = WORK.resolve()
    if options.mode == "prepare":
        prepare(out)
    else:
        print(json.dumps(verify(out), indent=2, sort_keys=True))
