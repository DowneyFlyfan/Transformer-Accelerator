"""Check the host sideband protocol and its effect on prior mapped data streams."""

import argparse
import json
from pathlib import Path
import re
import shlex

from link_tri_oracle_chip_packet_io import ROOT, instance, ports
from link_tri_oracle_indexed_whole_chip import module_at, spans
from link_tri_oracle_narrow_host import declarations
from measure_tri_oracle_serial_memory_requests import digest, read, replace
from prepare_tri_oracle_host_boundary_rx import BASE, EXPECTED_RTL as RX, receiver
from verify_tri_oracle_host_projection import include
from verify_tri_oracle_host_rotary import MODEL


TX = "tri_oracle_host_status_link"
TEST = Path(f"verilog/{TX}_tb.sv")
SOURCE = Path(f"verilog/{TX}.sv")
NORMAL = "tri_oracle_host_normalization_rx"
NORM_DIR = ROOT / "host_normalization"
NORMAL_CASES = {
    "normalization": ("stream_bundle.sv", "tri_oracle_packet_normalization_stream_tb", "mapped",
                      "PACKET_NORMALIZATION_STREAM_PASS stats=512 replay=512 rows=512"),
    "projection": ("projection_cut_bundle.sv", "tri_oracle_packet_projection_normalization_tb", "projection",
                   "PACKET_PROJECTION_NORMALIZATION_PASS operands=512 gamma=512 rows=512"),
}


def prepare(directory, phase, pin):
    norm_path = Path("records/tri_oracle_host_normalization_packets.json")
    baseline = read(pin(norm_path))["evidence_sha256"]
    generated_rx = pin(directory / "boundary_rx.sv")
    assert generated_rx.read_text() == receiver()
    pin(BASE, baseline[str(BASE)])
    pin(Path("syn/prepare_tri_oracle_host_boundary_rx.py"))
    model = pin(MODEL, baseline[str(MODEL)])
    mapped_rx, mapped_tx = (pin(directory / f"genus_{lane}/netlist.v") for lane in ("rx", "tx"))
    original = NORM_DIR / "genus/netlist.v"
    pin(original, baseline[str(original)])
    for path, name in ((mapped_rx, RX), (mapped_tx, TX), (original, NORMAL)):
        data = path.read_bytes()
        index = spans(data)
        assert set(index) == {name}
    before = ports(original.read_bytes())
    assert ports(mapped_rx.read_bytes()) == before | {
        "control_valid": ("OUTPUT", None),
        "control_ready": ("INPUT", None),
        "control_action": ("OUTPUT", 2),
    }
    alias = directory / "normalization_alias.v"
    aliases = {name: name for name in before} | {
        "control_valid": "", "control_ready": "1'b0", "control_action": "",
    }
    generated = {
        alias: f"module {NORMAL} (\n" + ",\n".join(declarations(before)) + "\n);\n" +
               instance(RX, "receiver", aliases) + "endmodule\n",
        directory / "status_bundle.sv": "".join(include(path) for path in (model, mapped_rx, mapped_tx, pin(TEST))),
    }
    cases = {}
    for lane, (name, top, old_lane, marker) in NORMAL_CASES.items():
        old_bundle = NORM_DIR / name
        bundle = pin(old_bundle, baseline[str(old_bundle)]).read_text()
        for match in re.findall(r'(?m)^`include "([^"]+)"$', bundle):
            path = Path(match).relative_to(Path.cwd())
            pin(path, baseline[str(path)])
        changed = directory / name
        generated[changed] = replace(bundle, include(original), include(mapped_rx) + include(alias))
        old_history = NORM_DIR / old_lane / "xrun.history"
        old_args = arguments(pin(old_history, baseline[str(old_history)]))
        plusargs = [arg for arg in old_args if arg.startswith("+") and not arg.startswith("+DUMP=")]
        assert len(plusargs) == (2 if lane == "normalization" else 4)
        for arg in plusargs:
            path = Path(arg.split("=", 1)[1])
            name = str(path.relative_to(Path.cwd()))
            expected = baseline.get(name) or baseline[str(path)]
            pin(path, expected)
        dump = directory / lane / "normalized.hex"
        old_dump = NORM_DIR / old_lane / "normalized.hex"
        pin(old_dump, baseline[str(old_dump)])
        cases[lane] = {"bundle": str(changed.resolve()), "top": top, "expected": str(old_dump),
                       "args": [*plusargs, f"+DUMP={dump.resolve()}"], "pass_marker": marker}
    generated[directory / "replays.json"] = json.dumps(cases, indent=2, sort_keys=True) + "\n"
    for path, text in generated.items():
        if phase == "prepare":
            with path.open("x") as stream:
                stream.write(text)
        else:
            assert path.read_text() == text, path
            pin(path)
    return cases


def arguments(path):
    match = re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", path.read_text())
    return shlex.split(match[-1])


def verify(directory, cases, pin):
    def proof(lane, top, sources, plusargs=()):
        out = directory / lane
        argv = arguments(pin(out / "xrun.history"))
        assert argv[argv.index("-top") + 1] == top
        assert all(str(pin(path).resolve()) in argv for path in sources)
        assert set(plusargs) <= set(argv)
        return pin(out / "console.log").read_text()

    red = proof("red", f"{TX}_tb", (directory / "boundary_rx.sv", directory / "red/baseline.sv", TEST))
    assert "STATUS_LEASE_SET_DROPPED" in red and "Simulation terminated via $fatal(1)" in red
    held = {}
    for lane, sources in {
        "rtl": (directory / "boundary_rx.sv", SOURCE, TEST),
        "mapped": (directory / "status_bundle.sv",),
    }.items():
        log = proof(lane, f"{TX}_tb", sources)
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        (count,) = re.findall(r"(?m)^HOST_STATUS_LINK_PASS replies=4 forward_words=3 gamma_records=1 held=(\d+)$", log)
        assert int(count) > 0
        held[lane] = int(count)
    for lane, replay in cases.items():
        source = Path(replay["bundle"]).relative_to(Path.cwd())
        log = proof(lane, replay["top"], (source,), replay["args"])
        assert log.count(replay["pass_marker"]) == 1
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        assert pin(directory / lane / "normalized.hex").read_bytes() == Path(replay["expected"]).read_bytes()
    stats = {}
    for lane, master in (("rx", RX), ("tx", TX)):
        run = directory / f"genus_{lane}"
        assert f"TRI_ORACLE_STATUS_GENUS_FINISHED {master}" in pin(run / "console.log").read_text()
        assert "No unresolved references" in pin(run / "mapped_check.rpt").read_text()
        assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", pin(run / "constraints.sdc").read_text())
        slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(run / "timing.rpt").read_text())))
        assert slack >= 0
        stats[lane] = slack
    pin(Path("syn/tri_oracle_synthesize_host_status_link.tcl"))
    pin(Path(__file__).resolve().relative_to(Path.cwd()))
    return {
        "state": "mapped_status_and_lease_protocol_verified_with_normalization_regressions",
        "status_outputs_targeted": 27, "lease_inputs_targeted": 1,
        "normalization_statistics_packets": 512, "normalization_replay_packets": 512,
        "projection_operand_packets": 512, "projection_coefficient_packets": 512,
        "isolated_worst_setup_slack_ps": stats,
        "held_status_or_source_words": held,
        "scope": "Mapped host parser and transmitter tested with synthetic sideband status and stalled "
                 "command replies, plus the exact mapped trained projection and normalization regressions. "
                 "Whole-chip binding and physical signal and power pad placement remain separate checks.",
    }


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    evidence = {}

    def pin(path, expected=None):
        name = str(path)
        if name not in evidence:
            evidence[name] = digest(path)
        assert expected is None or evidence[name] == expected, path
        return path

    prepared = prepare(args.directory, args.phase, pin)
    if args.phase == "verify":
        print(json.dumps(verify(args.directory, prepared, pin) | {"evidence_sha256": evidence},
                         indent=2, sort_keys=True))
