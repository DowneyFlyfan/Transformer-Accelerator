"""Map and check clock gating on the complete 32-by-8 compute array."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess

from link_tri_oracle_indexed_whole_chip import module_at, spans
from verify_tri_oracle_gated_receive_storage import CELL_SITE_AREA, ROOT, digest, mapped_ports, read, timing_source
from verify_tri_oracle_host_status import arguments


CARRY = Path(".cache/physical/carry_lookahead_comparison/carry_save_pipeline")
BASE = CARRY / "decoupled_valid_trial/reuse_result_stage/onehot_queue_trial"
WORK = Path(".cache/physical/whole_chip_xcelium_speed/gated_compute_array")
TARGETS = Path("records/paper_result_targets.json")
RTL_PROOF = Path("records/tri_oracle_onehot_result_queue_rtl_replay.json")
MAPPED_PROOF = Path("records/tri_oracle_onehot_queue_mapped_results.json")
MAPPED_RECEIPT = BASE / "mapped_comparison.json"
REPLAY_PROOF = BASE / "mapped_replay/verified.json"
PHYSICAL_PROOF = Path("records/tri_oracle_hot_timed_array_twenty_core_composition.json")
CHIP_BUDGET = Path("records/tri_oracle_gated_receive_storage.json")
RTL = BASE / "synthesis_array.sv"
CONSTRAINT = CARRY / "constraints.sdc"
SLOW_LIB = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib")
TOP = "tri_oracle_pe_array"
PASS = "DECOUPLED_ARRAY_PASS lines=32 lanes=8 edges=1158 accepted=790 delivered=786 reset_discarded=4 peak_pending=4"
HISTORY = BASE / "mapped_replay/xrun.history"


def compile_script():
    source = (BASE / "synthesize.tcl").read_text()
    anchor = "    set_db auto_super_thread false\n"
    assert source.count(anchor) == 1
    return source.replace(anchor, anchor + "    set_db lp_insert_clock_gating true\n"
                          "    puts TRI_ORACLE_COMPUTE_CLOCK_GATING=[get_db lp_insert_clock_gating]\n")


def timing_script():
    source = timing_source().replace("tri_oracle_credit_metadata_ingress", TOP)
    source = source.replace("$out/constraints.sdc", "$out/emitted.sdc")
    source = source.replace("if {[sizeof_collection [get_ports pad_metadata*]] != 7} {error \"SHARED_METADATA_PORT_COUNT\"}\n", "")
    return source.replace("TRI_ORACLE_MAPPED_RECEIVER_TIMING_FINISHED", "TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED")


def prepare():
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "synthesize.tcl").write_text(compile_script())
    (WORK / "timing.tcl").write_text(timing_script())


def renamed(source):
    # The lockstep test instantiates the candidate under a distinct module name.
    original = rf"(?m)^module {TOP}(?=\s*\()"
    text, replacements = re.subn(original, f"module {TOP}_decoupled", source)
    assert replacements == 1
    return text


def replay():
    directory = WORK / "replay"
    directory.mkdir(exist_ok=True)
    netlist = directory / "decoupled_mapped.v"
    netlist.write_text(renamed((WORK / "netlist.v").read_text()))
    argv = arguments(HISTORY)
    reference = (BASE / "mapped_replay/decoupled_mapped.v").resolve()
    argv[argv.index(str(reference))] = str(netlist.resolve())
    native = ["docker", "exec", "-e", "USER=downeyflyfan", "-e", "LOGNAME=downeyflyfan", "-e", "CDS_LIC_FILE=5280@localhost",
              "-e", "LM_LICENSE_FILE=5280@localhost", "-w", str(directory.resolve()),
              "tri-oracle-eda", "/opt/cadence/bin/xrun", *argv]
    with (directory / "console.log").open("w") as console:
        subprocess.run(native, stdout=console, stderr=subprocess.STDOUT, check=True)


def area(path):
    row = re.search(rf"(?m)^{TOP}\s+NA\s+(\d+)\s+([\d.]+)", path.read_text())
    sites = Decimal(row[2]) / CELL_SITE_AREA
    assert sites == int(sites), path
    return int(row[1]), int(sites)


def verify():
    evidence = {}

    def pin(path, expected=None):
        actual = digest(path)
        assert expected is None or actual == expected, path
        assert evidence.setdefault(str(path), actual) == actual, path
        return path

    rtl = read(pin(RTL_PROOF))
    publication = read(pin(MAPPED_PROOF))["evidence_sha256"]
    mapped = read(pin(MAPPED_RECEIPT, publication[str(MAPPED_RECEIPT)]))
    original_replay = read(pin(REPLAY_PROOF, publication[str(REPLAY_PROOF)]))
    targets = read(pin(TARGETS))
    for path in (RTL, CONSTRAINT, SLOW_LIB, CARRY / "carry_save.sv", BASE / "mapped_replay/mapped_tb.sv"):
        sources = (rtl, mapped, original_replay)
        checksums = {item["evidence_sha256"][str(path)] for item in sources if str(path) in item["evidence_sha256"]}
        assert len(checksums) == 1, path
        pin(path, checksums.pop())
    assert "create_clock -name core -period 1.724140" in CONSTRAINT.read_text()
    assert targets["system_latency"]["clock_megahertz"] == 580

    synth = pin(WORK / "synthesize.tcl")
    assert synth.read_text() == compile_script()
    transcript = pin(WORK / "console.log").read_text()
    assert "TRI_ORACLE_COMPUTE_CLOCK_GATING=true" in transcript
    assert re.search(r"(?m)^REDUCTION_SYNTH_COMPARE_PASS \d+$", transcript)
    assert str(RTL.resolve()) in transcript
    assert "ssg0p9v125c" in pin(WORK / "area.rpt").read_text()
    emitted = pin(WORK / "emitted.sdc").read_text()
    assert re.search(r'create_clock -name "?core"? -period 1\.72414\b', emitted)
    stock = pin(BASE / "mapped/netlist.v", mapped["evidence_sha256"][str(BASE / "mapped/netlist.v")])
    candidate = pin(WORK / "netlist.v")
    for path in (stock, candidate):
        data = path.read_bytes()
        ports = mapped_ports(module_at(data, spans(data), TOP))
        assert ports["operand_a"] == ports["operand_b"] == ("INPUT", 32 * 8 * 8)
        assert ports["lane_enable"] == ("INPUT", 256) and ports["out_sums"] == ("OUTPUT", 608)
        if path == stock:
            original_ports = ports
        else:
            assert ports == original_ports
    clocks = re.findall(rb"(?m)^\s+(CKL\w+)\s+\S+\s*\(\s*\.", candidate.read_bytes())
    assert clocks and not re.search(rb"(?m)^\s+CKL\w+\s+\S+\s*\(\s*\.", stock.read_bytes())

    cycle_source = pin(WORK / "replay/decoupled_mapped.v")
    assert cycle_source.read_text() == renamed(candidate.read_text())
    replay_log = pin(WORK / "replay/console.log").read_text()
    assert not re.search(r"\*[EF],", replay_log)
    assert replay_log.splitlines().count(PASS) == 1 and replay_log.count("Simulation complete via $finish(1)") == 1
    new_argv = arguments(pin(WORK / "replay/xrun.history"))
    old_argv = arguments(pin(HISTORY))
    old_argv[old_argv.index(str((BASE / "mapped_replay/decoupled_mapped.v").resolve()))] = str(cycle_source.resolve())
    assert new_argv == old_argv

    assert pin(WORK / "timing.tcl").read_text() == timing_script()
    native_log = pin(WORK / "timing.log").read_text()
    assert re.search(r"(?m)^TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED$", native_log)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", native_log)
    margins = {}
    for mode, label in (("setup", "Setup"), ("hold", "Hold"), ("gate_setup", "Clock Gating Setup"),
                        ("gate_hold", "Clock Gating Hold")):
        text = pin(WORK / f"native_{mode}.rpt").read_text()
        assert re.search(rf"(?m)^Path \d+:.*\b{label} Check with Pin", text)
        margins[mode] = float(min(map(Decimal, re.findall(r"Slack:=\s+(-?\d+\.\d+)", text))) * 1000)

    original_cells, original_sites = area(pin(BASE / "mapped/area.rpt", mapped["evidence_sha256"][str(BASE / "mapped/area.rpt")]))
    cells, sites = area(pin(WORK / "area.rpt"))
    physical = read(pin(PHYSICAL_PROOF))
    counts = physical["regions"]
    scale = targets["silicon"]["clusters"] * targets["silicon"]["cores_per_cluster"]
    assert len(counts) == scale == 20
    current_sites, = {row["sites_per_core"] for row in counts}
    deficit = read(pin(CHIP_BUDGET))["remaining_geometric_site_margin_if_substituted"]
    for path in (BASE / "synthesize.tcl", WORK / "emitted.sdc", Path(__file__).resolve().relative_to(ROOT)):
        pin(path)
    return {
        "state": "clock_gated_32_by_8_array_mapped_and_lockstep_verified",
        "clock_megahertz": 580, "delivered_lockstep_transactions": 786,
        "ungated_mapped_cells": original_cells, "ungated_mapped_sites": original_sites,
        "current_placed_sites_per_array": current_sites,
        "clock_gated_mapped_cells": cells, "clock_gated_mapped_sites": sites, "inserted_gate_instances": len(clocks),
        "mapped_sites_saved_per_array": original_sites - sites,
        "potential_sites_recovered_against_placed_arrays": scale * (current_sites - sites),
        "remaining_geometric_site_margin_with_receiver_and_array_replacements": deficit + scale * (current_sites - sites),
        "minimum_initial_native_slack_ps": margins,
        "scope": "One complete mapped array was replayed with the published lockstep fixture. Native timing is "
                 "pre-layout. The whole-chip site estimate substitutes this mapping for all 20 placed arrays and "
                 "omits the cost of physical optimization and clock distribution.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "replay", "verify"))
    action = parser.parse_args().action
    if action == "prepare":
        prepare()
    elif action == "replay":
        replay()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
