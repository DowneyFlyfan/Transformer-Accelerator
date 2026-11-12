"""Measure the relinked response address on the matched buffered placement."""

import argparse
import json
from pathlib import Path
import re
import resource
import shutil
import time

from link_tri_oracle_response_address_candidate import BUFFERED, ROOT, read, sha
import measure_compact_placed_timing as timing
import place_compact_tensor as place
from place_linked_tsmc_bank_buffers import word
from run_tri_oracle_parallel_chip_synthesis import proc_identity


BASELINE = BUFFERED / "physical_comparison"
CHECKER = ROOT / "syn/tri_oracle_require_clean_placement.tcl"
TENSOR_PATH = "feedforward/compute/compute/tensor"
GIB = 2**30


PLACE = r'''
if {[llength [get_db ports]] != 14343} {error "Top-level ports changed"}
if {[lsort [get_db analysis_views .name]] ne {hold_fast setup_slow setup_typ}} {error "Analysis views changed"}
set banks [get_db hinsts -if {.name =~ *block_instance && .dont_touch == true}]
if {[llength $banks] != 5} {error "Protected compute banks changed"}
set unplaced [get_db insts -if {.place_status == unplaced}]
set changed [list]
foreach inst $unplaced {
    set name [get_db $inst .name]
    if {![string match $tensor_pattern $name]} {error "Unplaced cell outside the replaced tensor: $name"}
    lappend changed $name
}
puts "RESPONSE_ADDRESS_ECO_UNPLACED [llength $changed]"
if {[llength $changed] != 0} {
    place_eco -fix_placed_insts true -timing_driven false
    place_detail -eco true -inst $changed
}
foreach {seed expected_count} $buffer_plans {
    source $seed
    if {[dict size $locations] != $expected_count} {error "Wrong verified buffer count"}
    dict for {buffer config} $locations {
        lassign $config master x y
        set inst [get_db insts $buffer]
        if {[llength $inst] != 1 || [get_db $inst .base_cell.name] ne $master ||
            ![get_db $inst .base_cell.is_buffer] || [get_db $inst .place_status] ni {placed fixed}} {
            error "Verified buffer changed: $buffer"
        }
    }
    dict for {buffer expected} $branches {
        set net [get_db [get_db pins $buffer/Z] .net]
        if {[llength $net] != 1 || [get_db $net .driver_pins.name] ne [list $buffer/Z] ||
            [lsort [get_db $net .load_pins.name]] ne [lsort $expected]} {
            error "Verified buffer branch changed: $buffer"
        }
    }
    puts "RESPONSE_ADDRESS_PRESERVED_BUFFERS $expected_count"
}
set macros [get_db insts -if {.base_cell.name =~ TS*N28HPCPSVTA*}]
if {[llength $macros] != 623} {error "Compiled memory count changed"}
set stream [open macro_poses.tsv w]
foreach inst $macros {
    if {[get_db $inst .place_status] ne "fixed" || ![get_db $inst .is_place_halo]} {
        error "Compiled memory lost placement protection"
    }
    lassign [join [get_db $inst .location] " "] x y
    puts $stream [join [list [get_db $inst .name] [get_db $inst .base_cell.name] $x $y [get_db $inst .orient]] "\t"]
}
close $stream
check_place placement_violations.rpt > placement.rpt
puts "RESPONSE_ADDRESS_PLACEMENT_COUNTS [tri_oracle_require_clean_placement placement.rpt]"
write_netlist placed.v -exclude_leaf_cells
write_db placed.db
puts RESPONSE_ADDRESS_PLACEMENT_SAVED
exit
'''


def pin(pins, *paths):
    for path in paths:
        digest = sha(path)
        assert pins.setdefault(str(path), digest) == digest, path


def verify(pins):
    assert all(sha(path) == digest for path, digest in pins.items())


def prepare(directory):
    link_path = directory / "receipt.json"
    candidate = directory / "candidate.v"
    baseline_path = BASELINE / "receipt.json"
    link, baseline = read(link_path), read(baseline_path)
    assert link["state"] == "mapped_response_address_logic_linked_with_buffered_fabric_preserved"
    assert link["candidate_sha256"] == sha(candidate)
    assert baseline["state"] == "compact_attention_capture_buffer_matched_pre_route_timing_measured"
    verify(baseline["evidence_sha256"])
    report = BASELINE / "report/timing.rpt"
    assert timing.timing_paths(report) == baseline["timing"]
    source = BASELINE / "eco/placed.db"
    poses = BASELINE / "report/macro_poses.tsv"
    assert set(poses.read_text().splitlines()) == set((BASELINE / "eco/macro_poses.tsv").read_text().splitlines())
    assert len(set(poses.read_text().splitlines())) == baseline["fixed_memory_macros"] == 623
    assert shutil.disk_usage(directory).free >= 12 * GIB
    row_plan = BUFFERED.parent / "physical_comparison/eco/seeds.tcl"
    attention_plan = BASELINE / "eco/seeds.tcl"
    pins = {str(ROOT / path): digest for path, digest in link["input_sha256"].items()}
    pin(pins, link_path, candidate, baseline_path, report, poses, row_plan, attention_plan, CHECKER,
        Path(__file__).resolve(), Path(timing.timing_scripts.__code__.co_filename).resolve(),
        Path(place.verify_topology.__code__.co_filename).resolve())
    verify(pins)
    top = link["top"]
    output = directory / "physical_comparison"
    converted, eco = output / "text_source", output / "eco"
    converted.mkdir(parents=True)
    eco.mkdir()
    save, placement = converted / "save.tcl", eco / "place.tcl"
    save.write_text(f"""set_multi_cpu_usage -local_cpu 1
read_db {word(str(source))}
set_multi_cpu_usage -local_cpu 1
if {{[get_db current_design .name] ne {word(top)}}} {{error "Wrong buffered baseline"}}
if {{[lsort [get_db analysis_views .name]] ne {{hold_fast setup_slow setup_typ}}}} {{error "Analysis views changed"}}
set_db write_db_binary_timing_constraints false
write_db placed.db
puts VERIFIED_TEXT_TIMING_ECO_SOURCE_SAVED
exit
""")
    placement.write_text(f"""set_multi_cpu_usage -local_cpu 1
eco_design {word(str(converted / 'placed.db'))} {word(top)} {word(str(candidate))} -keep_inst_location -no_eco_place -no_eco_route -skip_ccopt -report_file eco.rpt
set_multi_cpu_usage -local_cpu 1
if {{[get_db current_design .name] ne {word(top)}}} {{error "Wrong response-address candidate"}}
source {word(str(CHECKER))}
set tensor_pattern {word(TENSOR_PATH + '/*')}
set buffer_plans [list {word(str(row_plan))} 192 {word(str(attention_plan))} 72]
{PLACE}""")
    pin(pins, save, placement)
    result = {"state": "response_address_placement_comparison_prepared", "top": top,
              "candidate_sha256": pins[str(candidate)], "baseline_database": place.artifact_fingerprint(source),
              "input_sha256": pins}
    with (output / "prepared.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], flush=True)


def wait_for_training(pid):
    identity = proc_identity(pid)
    if not identity:
        return
    args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    assert any(arg.endswith(b"/replay_tri_oracle_linked_response_training.py") for arg in args)
    deadline = time.monotonic() + 24 * 3600
    print("Waiting for exact linked training replay", pid, flush=True)
    while proc_identity(pid) == identity:
        assert time.monotonic() < deadline
        time.sleep(5)


def run(directory, worker):
    output = directory / "physical_comparison"
    setup_path = output / "prepared.json"
    setup = read(setup_path)
    assert setup["state"] == "response_address_placement_comparison_prepared"
    wait_for_training(worker)
    attention_path = directory / "integrated_attention/receipt.json"
    trained_path = directory / "integrated_trained/receipt.json"
    attention, trained = read(attention_path), read(trained_path)
    assert attention["state"] == "response_address_linked_netlist_preserved_archived_attention"
    assert trained["state"] == "response_address_linked_netlist_preserved_trained_layer"
    assert trained["progress_matches_archived_cycles"] and trained["counters"]["exact_outputs"] == 32768
    assert attention["replay"]["native_exit_status"] == trained["native"]["native_exit_status"] == 0
    pins = setup["input_sha256"].copy()
    for result in (attention, trained):
        assert result["candidate_sha256"] == setup["candidate_sha256"] and result["compiled_memory_macros"] == 623
        for path, digest in result["input_sha256"].items():
            assert pins.setdefault(path, digest) == digest, path
    pin(pins, setup_path, attention_path, trained_path)
    verify(pins)
    assert shutil.disk_usage(directory).free >= 12 * GIB
    baseline_db = BASELINE / "eco/placed.db"
    assert place.artifact_fingerprint(baseline_db) == setup["baseline_database"]
    expected = set((BASELINE / "report/macro_poses.tsv").read_text().splitlines())
    converted, eco = output / "text_source", output / "eco"
    for folder, script, start, reserve, marker in (
        (converted, "save.tcl", 18, 8, "VERIFIED_TEXT_TIMING_ECO_SOURCE_SAVED"),
        (eco, "place.tcl", 19, 6.5, "RESPONSE_ADDRESS_PLACEMENT_SAVED"),
    ):
        native = place.native(folder, folder / script, [], start, reserve, address_space_gib=24)
        log = (folder / "console.log").read_text()
        place.require_clean_native(log)
        assert native["native_exit_status"] == 0 and log.splitlines().count(marker) == 1
    assert set((eco / "macro_poses.tsv").read_text().splitlines()) == expected
    assert re.findall(r"(?m)^RESPONSE_ADDRESS_PRESERVED_BUFFERS (\d+)$", log) == ["192", "72"]
    leaves, = map(int, re.findall(r"(?m)^RESPONSE_ADDRESS_PLACEMENT_COUNTS (\d+) [0-9.]+$", log))
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (2 * GIB, hard))
    try:
        modules, instances, actual_leaves = place.verify_topology(
            (directory / "candidate.v").read_text(), (eco / "placed.v").read_text(), setup["top"])
    finally:
        resource.setrlimit(resource.RLIMIT_AS, (soft, hard))
    assert actual_leaves == leaves and modules == 208

    database = eco / "placed.db"
    checkpoint = place.artifact_fingerprint(database)
    prefixes = ("libs/mmmc/", "libs/lef/")
    baseline_libraries = {name: data["sha256"] for name, data in setup["baseline_database"]["files"].items()
                          if name.startswith(prefixes)}
    candidate_libraries = {name: data["sha256"] for name, data in checkpoint["files"].items()
                           if name.startswith(prefixes)}
    assert baseline_libraries and candidate_libraries == baseline_libraries
    assert (baseline_db / "viewDefinition.tcl").read_bytes() == (database / "viewDefinition.tcl").read_bytes()
    spef = output / "estimated_slow.spef"
    extraction, report = timing.timing_scripts(database, setup["top"], CHECKER, spef)
    extracted, log = timing.run_stage(output / "extract", extraction, expected, leaves)
    assert "PreRoute RC Extraction DONE" in log and log.splitlines().count("COMPACT_ESTIMATED_PARASITICS_WRITTEN") == 1
    nets, spef_sha = timing.count_nets(spef, setup["top"]), sha(spef)
    reported, log = timing.run_stage(output / "report", report, expected, leaves)
    assert log.splitlines().count("COMPACT_ESTIMATED_PARASITICS_RELOADED") == 1
    assert log.splitlines().count("LINKED_PLACED_TIMING_VIEW_WRITTEN setup_slow") == 1
    annotation, report_path = (output / "report" / name for name in ("annotation.rpt", "timing.rpt"))
    assert timing.annotated_nets(annotation) == nets and sha(spef) == spef_sha
    assert place.artifact_fingerprint(database) == checkpoint
    assert place.artifact_fingerprint(baseline_db) == setup["baseline_database"]
    verify(pins)
    actual = timing.timing_paths(report_path)
    baseline = read(BASELINE / "receipt.json")["timing"]
    pin(pins, eco / "placed.v", eco / "macro_poses.tsv", annotation, report_path)
    result = {
        "state": "linked_response_address_matched_placement_timing_measured", "candidate_sha256": setup["candidate_sha256"],
        "timing": actual, "baseline_timing": baseline,
        "delta_worst_slack_ns": actual["worst_slack_ns"] - baseline["worst_slack_ns"],
        "fixed_memory_macros": len(expected), "retained_timing_buffers": 264, "placed_instances": leaves,
        "native_placement": native, "native_extraction": extracted, "native_report": reported,
        "placed_database": checkpoint, "estimated_spef_sha256": spef_sha, "evidence_sha256": pins,
        "scope": "Matched slow-corner timing estimate on the placed decoder with pre-route parasitics.",
    }
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], actual["worst_slack_ns"], result["delta_worst_slack_ns"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("candidate_directory", type=lambda path: Path(path).resolve())
    parser.add_argument("--after", type=int, default=0)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.candidate_directory)
    else:
        run(args.candidate_directory, args.after)
