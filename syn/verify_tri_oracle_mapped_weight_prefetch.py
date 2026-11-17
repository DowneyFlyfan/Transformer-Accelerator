"""Map the loader from the simulated chip's sources and verify its chip replays."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess

from prepare_tri_oracle_backpressured_weight_transport import RAW
from prepare_tri_oracle_phase_chip import INCLUDE
from verify_tri_oracle_phase_chip import require, summary, verify_case
from verify_tri_oracle_weight_tile_prefetch import ROOT, RUN


BUNDLE = RUN / "source/bundle.sv"
WORK = RUN / "cycle_bound_loader"
LOADER_FILES = ("tri_oracle_packed_weight_schedule.sv", "tri_oracle_paired_weight_schedule.sv",
                "tri_oracle_wide_weight_loader.sv", "weight_stream_write_arbiter.sv", f"{RAW}.sv")
CASES = ("early_gate", "weight_stall", "weight_prefetch_fault_lane0", "weight_prefetch_fault_lane1")
MARKERS = ("BATCH408_PASS", "PACKED_DECODER_PASS", "CHIP_WEIGHT_PREFETCH", "CHIP_WEIGHT_GUARD")
LIBRARY = ROOT / ".cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib"


def synthesis_inputs(bundle):
    includes = [Path(name) for name in INCLUDE.findall(bundle)]
    sources = []
    for name in LOADER_FILES:
        matches = [path for path in includes if path.name == name]
        require(len(matches) == 1, f"expected exactly one {name} in the chip bundle")
        path = matches[0]
        require(path.is_file() and path.is_relative_to(ROOT) and not set(str(path)).intersection("{}\\\n"),
                f"invalid loader source {path}")
        sources.append(path)
    return sources


def synthesis_script(sources):
    source_list = " ".join(f"{{{path}}}" for path in sources)
    return f"""set_db max_cpus [exec nproc]
set_db auto_super_thread false
set_db fail_on_error_mesg true
read_libs $::env(TRI_ORACLE_WIDE_LIB)
read_hdl -sv [list {source_list}]
elaborate {RAW}
create_clock -name core_clock -period 1.72414 [get_ports clk]
set_clock_uncertainty 0.05 [get_clocks core_clock]
set nonclock_inputs [remove_from_collection [all_inputs] [get_ports {{clk rst_n}}]]
set_input_delay 0.2 -clock core_clock $nonclock_inputs
set_input_transition 0.05 $nonclock_inputs
set_output_delay 0.2 -clock core_clock [all_outputs]
set_load 0.005 [all_outputs]
set_false_path -from [get_ports rst_n]
syn_generic
syn_map
syn_opt
check_design -unresolved > check.rpt
report_area > area.rpt
report_timing -max_paths 15 > timing.rpt
write_hdl > netlist.v
puts TRI_ORACLE_BACKPRESSURED_WEIGHT_LOADER_MAPPED
exit
"""


def mapping_evidence(work, sources):
    script = work / "synthesize.tcl"
    expected = synthesis_script(sources)
    require(script.read_text() == expected, "synthesis inputs differ from the chip bundle")
    console = work / "console.log"
    log = console.read_text().splitlines()
    require((work / "exit_status").read_text().strip() == "0"
            and log.count("TRI_ORACLE_BACKPRESSURED_WEIGHT_LOADER_MAPPED") == 1
            and log.count("@file(synthesize.tcl) 5: " + expected.splitlines()[4]) == 1,
            "native mapping did not use the checked synthesis inputs")
    checks = (work / "check.rpt").read_text()
    require(all(f"No {kind} in design '{RAW}'" in checks for kind in ("unresolved references", "empty modules")),
            "mapped loader has unresolved logic")
    return [script, console, work / "exit_status", work / "check.rpt", work / "netlist.v"]


def mapped_sources(work, source):
    netlist = (work / "netlist.v").read_text()
    header = netlist.split(f"module {RAW}(", 1)[1].split(");", 1)[0]
    pins = ("req_address", "req_length", "load_core", "load_addr", "load_row_enable")
    split = [f"{pin}[{lane}]" for pin in pins for lane in range(2)]
    require(set(re.findall(r"\\(\w+\[\d+\])", header)) == set(split)
            and re.search(r"(?m)^  input \[1:0\] [^;]*\bload_ready\b", netlist),
            "mapped loader interface changed")
    gates = work / "gates.v"
    adapter = work / "adapter.sv"
    connections = "".join(f"    .\\{pin} ({pin}),\n" for pin in split)
    ports = source.read_text().split("\n);\n", 1)[0] + "\n);\n"
    wrapper = ports + f"  {RAW}_mapped implementation (\n{connections}    .*\n  );\nendmodule\n"
    bundle = BUNDLE.read_text().replace(f'`include "{source}"\n', f'`include "{gates}"\n`include "{adapter}"\n')
    return {gates: netlist.replace(f"module {RAW}(", f"module {RAW}_mapped(", 1),
            adapter: wrapper, work / "bundle.sv": bundle}


def invocation(log):
    return log.split("\nxrun\n", 1)[1].split("\n\n", 1)[0].strip().splitlines()


def replay(work, name):
    case = work / name
    case.mkdir()
    baseline = (RUN / name / "xrun.log").read_text().replace(str(BUNDLE), str(work / "bundle.sv"))
    arguments = [arg for line in invocation(baseline) for arg in line.split()]
    command = ["docker", "exec", "-w", str(case), "tri-oracle-eda", "timeout", "-k", "5", "240",
               "prlimit", "--as=5368709120", "--", "/opt/cadence/bin/xrun", *arguments]
    with (case / "console.log").open("w") as console:
        status = subprocess.run(command, stdout=console, stderr=subprocess.STDOUT, check=False).returncode
    (case / "exit_status").write_text(f"{status}\n")
    require(status == 0, f"{name}: Xcelium returned {status}")


def verify(work, sources):
    evidence = [BUNDLE, *sources, LIBRARY, Path(__file__).resolve(), *mapping_evidence(work, sources)]
    for path, contents in mapped_sources(work, sources[-1]).items():
        require(path.read_text() == contents, f"changed mapped replay input {path}")
        evidence.append(path)
    timing_report = work / "timing.rpt"
    path = re.search(r"(?m)^Path 1: (MET|VIOLATED) \((-?\d+) ps\) Setup Check", timing_report.read_text())
    require(path is not None, "missing mapped setup report")
    evidence.append(timing_report)
    cases = {}
    for name in CASES:
        source, expected_phase = verify_case(RUN, name)
        mapped, phase = verify_case(work, name)
        require(invocation(mapped) == invocation(source.replace(str(BUNDLE), str(work / "bundle.sv")))
                and phase == expected_phase, f"{name}: changed simulator input or physical counts")
        results = {}
        markers = (*MARKERS, "BATCH408_FAULT_DRAINED") if "fault" in name else MARKERS
        for marker in markers:
            result = summary(mapped, marker)
            require(result == summary(source, marker), f"{name}: changed {marker}")
            results[marker] = result
        baseline_trace, mapped_trace = RUN / name / "progress.log", work / name / "progress.log"
        require(baseline_trace.read_bytes() == mapped_trace.read_bytes(), f"{name}: changed command cycles")
        require(results["BATCH408_PASS"]["exact_outputs"] == 504, f"{name}: incomplete output check")
        evidence.extend(folder / name / item for folder in (RUN, work)
                        for item in ("xrun.log", "progress.log", "exit_status"))
        cases[name] = results
    pins = {}
    for artifact in sorted(set(evidence)):
        with artifact.open("rb") as stream:
            pins[str(artifact.relative_to(ROOT))] = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"state": "mapped_loader_matches_source_chip_cycles", "cases": cases, "evidence_sha256": pins,
            "synthesis_setup_slack_ps": int(path[2]),
            "scope": "Mapped weight loader in chip command simulation with timed memory models. "
                     "Setup estimate uses block-level constraints before placement."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=WORK)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--replay", action="store_true")
    action.add_argument("--check-mapping", action="store_true")
    parser.add_argument("--record", type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    sources = synthesis_inputs(BUNDLE.read_text())
    if args.prepare:
        work.mkdir()
        (work / "synthesize.tcl").write_text(synthesis_script(sources))
        return
    if args.check_mapping:
        mapping_evidence(work, sources)
        print("Verified that Genus loaded the loader sources from the chip bundle.")
        return
    if args.replay:
        mapping_evidence(work, sources)
        for path, contents in mapped_sources(work, sources[-1]).items():
            path.write_text(contents)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda case: replay(work, case), CASES))
    result = verify(work, sources)
    if args.record:
        args.record.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("Verified cycle-for-cycle agreement in all four mapped-loader chip replays.")


if __name__ == "__main__":
    main()
