"""Qualify the mapped reservation and write buffer with timed memory writes."""

import argparse
import hashlib
import json
from pathlib import Path
import re

from prepare_tri_oracle_backpressured_weight_transport import RAW
from prepare_tri_oracle_phase_macro_boundary import REPAIRED_CLOCK_BOUNDARY, boundary
from verify_tri_oracle_mapped_weight_prefetch import (
    BUNDLE, INCLUDE, LIBRARY, ROOT, RUN, WORK as LOADER_WORK, invocation, synthesis_script,
)
from verify_tri_oracle_phase_chip import require, summary, verify_case
from verify_tri_oracle_phase_macro_boundary import critical_path, electrical


WORK = RUN / "mapped_ingress"
INGRESS = "tri_oracle_phase_weight_ingress"
CONTROL = INGRESS + "_control"
MARKER = "TRI_ORACLE_PHASE_INGRESS_MAPPED"
CASES = ("early_gate", "weight_stall", "weight_prefetch_fault_lane0", "weight_prefetch_fault_lane1", "scalar")
SPLIT = ("wide_core", "wide_address", "wide_group", "wide_rows", "wide_data",
         "staged_core", "staged_address", "staged_rows", "staged_data")
TIMING = WORK / "sram_timing"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_control():
    old_bundle = LOADER_WORK / "bundle.sv"
    includes = [Path(name) for name in INCLUDE.findall(old_bundle.read_text())]
    dependencies = ("weight_stream_write_arbiter.sv", "tri_oracle_weight_write_buffer.sv",
                    "tri_oracle_projection_weight_reuse.sv", f"{INGRESS}.sv")
    sources = []
    for name in dependencies:
        source, = (path for path in includes if path.name == name)
        sources.append(source)
    header, logic = sources[-1].read_text().split("\n);\n", 1)
    delimiter = "  tri_oracle_weight_phase_fabric_adapter weight_port ("
    logic, controller = logic.split(delimiter, 1)
    inside, body = logic.split("  assign wide_ready", 1)
    head = header.replace(f"module {INGRESS} (", f"module {CONTROL} (")
    head = head.replace("input logic clk, memory_clk, rst_n,\n  input logic [4:0][3:0] read_cores,",
                        "input logic clk, rst_n,\n  input logic [1:0] retired,")
    head = head.split("  output logic error,", 1)[0] + """  output logic error,
  output logic [1:0] load_valid, load_ready, pending, allowed,
  output logic [1:0][4:0] staged_core,
  output logic [1:0][9:0] staged_address,
  output logic [1:0][31:0] staged_rows,
  output logic [1:0][1023:0] staged_data
);
"""
    control = head + "  logic [1:0] malformed_wide;\n  logic malformed;\n\n  assign wide_ready" + body + "endmodule\n"
    external = inside.replace("malformed_wide, ", "").replace("  logic malformed;\n", "")
    wrapper = header + "\n);\n" + external + f"  {CONTROL} control (.*);\n\n" + delimiter + controller
    cut = WORK / f"{CONTROL}.sv"
    recipe = synthesis_script([*sources[:-1], cut]).replace(f"elaborate {RAW}", f"elaborate {CONTROL}")
    recipe = recipe.replace("TRI_ORACLE_BACKPRESSURED_WEIGHT_LOADER_MAPPED", MARKER)
    return sources, {cut: control, WORK / "phase_wrapper.sv": wrapper, WORK / "synthesize.tcl": recipe}


def mapped_replay_inputs(source, netlist, cut, wrapper):
    header = netlist.split(f"module {CONTROL}(", 1)[1].split(");", 1)[0]
    split = [f"{pin}[{lane}]" for pin in SPLIT for lane in range(2)]
    require(set(re.findall(r"\\(\w+\[\d+\])", header)) == set(split), "mapped ingress interface changed")
    mapped = netlist.replace(f"module {CONTROL}(", f"module {CONTROL}_mapped(", 1)
    ports = cut.split("\n);\n", 1)[0] + "\n);\n"
    connections = "".join(f"    .\\{pin} ({pin}),\n" for pin in split)
    adapter = ports + f"  {CONTROL}_mapped implementation (\n{connections}    .*\n  );\nendmodule\n"
    gate_path, adapter_path = WORK / "gates.v", WORK / "adapter.sv"
    original = (LOADER_WORK / "bundle.sv").read_text()
    include = f'`include "{source}"\n'
    require(original.count(include) == 1, "multiple source ingress definitions")
    mapped_bundle = original.replace(include, "".join(
        f'`include "{path}"\n' for path in (gate_path, adapter_path, wrapper)
    ))
    return {gate_path: mapped, adapter_path: adapter, WORK / "mapped/bundle.sv": mapped_bundle}


def verify_timing(netlist, evidence):
    previous = REPAIRED_CLOCK_BOUNDARY / "macro_boundary.v"
    original = previous.read_text()
    shell = boundary(True, True)
    require(original.endswith(shell), "unexpected original memory timing wrapper")
    candidate = TIMING / "macro_boundary.v"
    contents = candidate.read_text()
    require(contents.startswith(netlist.read_text() + "\n" + original[:-len(shell)]),
            "timing fixture did not use the mapped ingress, bank controller and clock")
    first_bank_control = "  tri_oracle_weight_phase_fabric controller ("
    require(contents.split(first_bank_control, 1)[1] == shell.split(first_bank_control, 1)[1],
            "memory bank or controller bindings changed")
    body = contents.split(f"  {CONTROL} ingress (\n", 1)[1].split("\n  );", 1)[0]
    connections = {f".{port}({port})" for port in
                   ("read_address", "reserve", "last_read", "reserve_strips", "wide_ready", "writes_empty",
                    "error", "scalar_valid", "scalar_core", "scalar_address", "scalar_rows", "scalar_data", "wide_valid")}
    connections.update({".clk(core_clk)", ".rst_n(core_rst_n)", ".retired(write_retired)",
                        ".pending(write_pending)", ".allowed(write_allowed)"})
    ports = (*((port, port, width) for port, width in
               (("wide_core", 5), ("wide_address", 10), ("wide_group", 2), ("wide_rows", 32), ("wide_data", 512))),
             ("staged_core", "write_core", 5), ("staged_address", "write_address", 10),
             ("staged_rows", "write_rows", 32), ("staged_data", "write_payload", 1024))
    for port, wire, width in ports:
        for lane in range(2):
            connections.add(f".\\{port}[{lane}] ({wire}[{(lane+1)*width-1}:{lane*width}])")
    require(set(body.strip().split(",\n    ")) == connections, "wrong mapped ingress connections")
    original_sdc = ROOT / "syn/tri_oracle_phase_macro_boundary.sdc"
    source_ports = "read_cores* read_address* write_pending* write_allowed* write_core* write_address* write_rows* write_payload*"
    ingress_ports = ("read_cores* read_address* reserve last_read reserve_strips* scalar_* wide_valid* "
                     "wide_core* wide_address* wide_group* wide_rows* wide_data*")
    expected = original_sdc.read_text().replace(source_ports, ingress_ports)
    sdc = TIMING / "boundary.sdc"
    require(sdc.read_text() == expected.replace("write_retired*", "wide_ready* writes_empty error"),
            "wrong memory timing constraints")
    old_driver = ROOT / "syn/tri_oracle_time_phase_macro_boundary.tcl"
    driver = TIMING / "timing.tcl"
    require(driver.read_text() ==
            old_driver.read_text().replace("$root/syn/tri_oracle_phase_macro_boundary.sdc", "boundary.sdc"),
            "timing commands changed")
    console, status = TIMING / "console.log", TIMING / "exit_status"
    log = console.read_text()
    require(status.read_text().strip() == "0" and log.splitlines().count("PHASE_MACRO_INVENTORY banks=320") == 1
            and log.splitlines().count("PHASE_MACRO_TIMING_COMPLETE") == 1
            and "Parasitics Mode: No SPEF/RCDB" in log and "Design Stage: PreRoute" in log,
            "native combined memory timing incomplete")
    evidence.extend((previous, candidate, original_sdc, sdc, old_driver, driver, console, status, TIMING / "views.tcl"))
    checks = {}
    for name in ("slow_setup", "typical_setup", "fast_hold"):
        path = TIMING / f"{name}.rpt"
        checks[name] = critical_path(path)
        first = path.read_text().split("Path 1:", 1)[1].split("Path 2:", 1)[0]
        endpoint = re.search(r"(?m)^\s*Endpoint: \([RF]\) (\S+)", first)
        require(endpoint is not None, f"missing worst endpoint in {path.name}")
        checks[name]["endpoint"] = endpoint[1]
        evidence.append(path)
    for view in ("slow", "typical"):
        path = TIMING / f"{view}_electrical.rpt"
        checks[f"{view}_electrical"] = electrical(path, view)
        evidence.append(path)
    return {"compiled_weight_memory_banks": 320, "checks": checks, "clock_periods_ps": {"memory": 862, "core": 1724},
            "scope": "Combined ingress, mapped clock, bank controller and compiled weight memory before placement."
                     " The boundary outputs use an assumed external hold budget of 100 ps."}


def verify(include_timing=False):
    sources, generated = prepare_control()
    for path, contents in generated.items():
        require(path.read_text() == contents, f"ingress cut changed: {path.name}")
    log_path = WORK / "console.log"
    log = log_path.read_text().splitlines()
    exit_status, checks = WORK / "exit_status", WORK / "check.rpt"
    recipe = generated[WORK / "synthesize.tcl"].splitlines()
    require(exit_status.read_text().strip() == "0" and log.count(MARKER) == 1
            and log.count("@file(synthesize.tcl) 5: " + recipe[4]) == 1
            and f"No unresolved references in design '{CONTROL}'" in checks.read_text(),
            "ingress mapping did not use the verified cut")
    loader = ROOT / "records/tri_oracle_mapped_weight_prefetch_loader.json"
    previous = json.loads(loader.read_text())
    require(previous["state"] == "mapped_loader_matches_source_chip_cycles", "missing loader verification")
    loader_inputs = [LOADER_WORK / item for item in ("bundle.sv", "gates.v", "adapter.sv")]
    for path in loader_inputs:
        require(digest(path) == previous["evidence_sha256"][str(path.relative_to(ROOT))],
                f"mapped loader input changed: {path.name}")
    netlist, timing = WORK / "netlist.v", WORK / "timing.rpt"
    wrapper, cut = WORK / "phase_wrapper.sv", WORK / f"{CONTROL}.sv"
    mapped = mapped_replay_inputs(sources[-1], netlist.read_text(), generated[cut], wrapper)
    for path, contents in mapped.items():
        require(path.read_text() == contents, f"mapped replay inputs changed: {path.name}")
    report = re.search(r"(?m)^Path 1: (?:MET|VIOLATED) \((-?\d+) ps\) ", timing.read_text())
    require(report is not None, "missing mapped ingress timing")
    evidence = [BUNDLE, LIBRARY, loader, netlist, timing, log_path, exit_status, checks, Path(__file__).resolve(),
                *loader_inputs, *sources, *generated, *mapped]
    candidate = WORK / "mapped"
    bundle = candidate / "bundle.sv"
    cases = {}
    for case in CASES:
        control, reference = verify_case(RUN, case)
        text, physical = verify_case(candidate, case)
        require(physical == reference and invocation(text) == invocation(control.replace(str(BUNDLE), str(bundle))),
                f"{case}: changed physical phase counts or simulator inputs")
        results = {}
        for marker in ("BATCH408_PASS", "PACKED_DECODER_PASS", "CHIP_WEIGHT_PREFETCH", "CHIP_WEIGHT_GUARD"):
            results[marker] = summary(text, marker)
            require(results[marker] == summary(control, marker), f"{case}: changed {marker}")
        if "fault" in case:
            require(summary(text, "BATCH408_FAULT_DRAINED") == {"fault": 18, "output_prefix_packets": 0},
                    f"{case}: faulty command produced output")
        require(results["BATCH408_PASS"]["exact_outputs"] == 504, f"{case}: incomplete output check")
        require((candidate / case / "progress.log").read_bytes() == (RUN / case / "progress.log").read_bytes(),
                f"{case}: changed command cycles")
        evidence.extend(folder / case / item for folder in (RUN, candidate)
                        for item in ("xrun.log", "progress.log", "exit_status"))
        cases[case] = results
    negative = candidate / "weight_guard_disabled"
    text = (negative / "xrun.log").read_text()
    control = RUN / "weight_guard_disabled/xrun.log"
    require((negative / "exit_status").read_text().strip() == "2"
            and invocation(text) == invocation(control.read_text().replace(str(BUNDLE), str(bundle)))
            and "+IGNORE_WEIGHT_REUSE" in text
            and "CHIP_WEIGHT_PREFETCH_OVERWRITE cluster=0 word=0" in text
            and "Simulation terminated via $fatal(1)" in text
            and "BATCH408_PASS" not in text, "disabled reservation failed to expose an unread write")
    evidence.append(control)
    evidence.extend(negative / item for item in ("xrun.log", "exit_status"))
    result = {
        "state": "mapped_ingress_matches_source_chip_with_timed_memories",
        "block_setup_slack_ps": int(report[1]),
        "cases": cases,
        "disabled_reservation_rejected": {"cluster": 0, "word": 0, "native_status": 2},
        "scope": "Chip command simulation using the mapped loader, reservation, write buffer and bank controller."
                 " Compiled memory timing checks were enabled. Reported setup slack covers the isolated ingress cut.",
    }
    if include_timing:
        result["combined_memory_timing"] = verify_timing(netlist, evidence)
    result["evidence_sha256"] = {str(path.relative_to(ROOT)): digest(path) for path in sorted(set(evidence))}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--include-timing", action="store_true")
    args = parser.parse_args()
    report = verify(args.include_timing)
    if args.record:
        args.record.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("Verified the mapped reservation and buffer through chip commands and compiler memory timing models.")
