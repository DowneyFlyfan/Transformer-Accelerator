"""Map the core around a preserved processing-array netlist."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_wac_outlier_layer import ROOT, RTL, read, sha, verify
from replay_mapped_cluster_fixture import shared_memory_stage, wait_for_shared_memory

PHYSICAL = ROOT / ".cache/physical"
ARRAY = PHYSICAL / "synthesis/tri_oracle_pe_array/netlist.v"
LIBRARIES = PHYSICAL / "wac_shared_imem_elaboration/inputs.json"


def recipe(candidate):
    inventory = read(LIBRARIES)
    libraries = {name: digest for name, digest in inventory.items() if name.endswith(".lib")}
    assert len(libraries) == 4 and all("ssg0p9v125c" in name for name in libraries)
    verify(libraries)
    lib_list = " ".join(f"{{{name}}}" for name in libraries)
    rtl = [*(RTL / f"tri_oracle_wac_{name}.sv" for name in ("softmax_imem", "imem_owner", "outlier_sign")),
           candidate / "tri_oracle_sram_memory_compute.sv", candidate / "tri_oracle_wac_softmax.sv"]
    rtl_list = " ".join(f"{{{name}}}" for name in rtl)
    script = """set_db max_cpus 1
set_db auto_super_thread false
set_db super_thread_servers {}
set_db fail_on_error_mesg true
set_db auto_ungroup none
set_db partition_based_synthesis false
set_db auto_partition false
""" + f"""read_libs [list {lib_list}]
read_hdl -netlist {{{ARRAY}}}
read_hdl -sv [list {rtl_list}]
""" + r"""elaborate tri_oracle_sram_memory_compute
set array [get_db hinsts -if {.module.name == tri_oracle_pe_array}]
if {[llength $array] != 1 || [get_db $array .name] ne "compute"} {error WAC_EXPECTED_MAPPED_PE_ARRAY}
set_db $array .preserve true
foreach mem [get_db insts -if {.base_cell.name =~ TS*N28HPCPSVTA*}] {set_db $mem .preserve true}
proc snapshot {stem} {
    set pe [list]
    set memory [list]
    foreach cell [get_db insts] {
        set name [get_db $cell .name]
        set master [get_db $cell .base_cell.name]
        if {[string match "compute/*" $name]} {lappend pe "$name	$master"}
        if {[string match "TS*N28HPCPSVTA*" $master]} {lappend memory "$name	$master"}
    }
    if {[llength $pe] != 54580 || [llength $memory] != 28} {
        error "WAC_CORE_INVENTORY pe=[llength $pe] memory=[llength $memory]"
    }
    foreach {suffix rows} [list pe $pe memory $memory] {
        set file [open "$stem.$suffix.tsv" w]
        foreach row [lsort $rows] {puts $file $row}
        close $file
    }
}
snapshot before
check_design -unresolved > unresolved_before.rpt
create_clock -name core_clock -period 1.724137931 [get_ports clk]
set inputs [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_clock_uncertainty 0.05 [get_clocks core_clock]
set_input_delay 0.2 -clock core_clock $inputs
set_output_delay 0.2 -clock core_clock [all_outputs]
set_input_transition 0.05 $inputs
set_load 0.005 [all_outputs]
set_false_path -from [get_ports rst_n]
write_db elaborated.db
puts WAC_MAPPED_PE_CORE_ELABORATED
syn_generic
write_db generic.db
puts WAC_MAPPED_PE_CORE_GENERIC
syn_map
syn_opt
snapshot after
check_design -unresolved > unresolved_after.rpt
report_area > area.rpt
report_timing -max_paths 10 > timing.rpt
write_hdl > netlist.v
write_sdc > clock.sdc
write_db mapped.db
puts WAC_MAPPED_PE_CORE_COMPLETE
exit
"""
    return script, libraries, rtl


def run(candidate, output):
    paths = [candidate / name for name in ("receipt.json", "xcelium/head_offload_qualification.json",
                                          "trained_metadata/receipt.json", "outlier_routes/receipt.json")]
    setup, attention, trained, routes = (read(path) for path in paths)
    assert setup["outlier_owner"] == "core_simd_round_robin"
    assert attention["state"] == "dynamic_head_offload_replayed_on_twenty_core_layer"
    assert trained["state"] == "trained_metadata_activation_and_masks_verified_at_simd_interface"
    assert routes["state"] == "twenty_core_outlier_destinations_verified"
    inputs = setup["input_sha256"].copy()
    for evidence in (attention["input_sha256"], trained["source_sha256"], routes["input_sha256"]):
        for name, digest in evidence.items():
            assert inputs.get(name, digest) == digest, name
            inputs[name] = digest
    gate_log = ARRAY.with_name("xcelium_gate_no_timing.log")
    text = gate_log.read_text()
    assert text.count("PASS: 300 full 32x8 signed compute transactions, masks, stalls, reset; NO_STALL=") == 2
    assert not re.search(r"\*[EF],", text)
    script_text, libraries, rtl = recipe(candidate)
    inputs.update(libraries)
    for path in (Path(__file__), gate_log, ARRAY, LIBRARIES, *paths, *rtl):
        digest = sha(path)
        assert inputs.get(str(path), digest) == digest, path
        inputs[str(path)] = digest
    verify(inputs)
    output.mkdir()
    script = output / "map.tcl"
    script.write_text(script_text)
    inputs[str(script)] = sha(script)
    (output / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    wait_for_shared_memory("core mapping with preserved array", 17)
    native = shared_memory_stage("core mapping with preserved array", output, [
        "/usr/bin/prlimit", "--as=7516192768", "--", "/opt/cadence/bin/genus", "-batch",
        "-log", str(output / "genus"), "-files", str(script),
    ], 2700, 0)
    assert "WAC_MAPPED_PE_CORE_COMPLETE" in (output / "console.log").read_text().splitlines()
    for name in ("pe", "memory"):
        assert (output / f"before.{name}.tsv").read_bytes() == (output / f"after.{name}.tsv").read_bytes()
    assert "No unresolved references" in (output / "unresolved_after.rpt").read_text()
    verify(inputs)
    result = dict(state="mapped_core_preserved_verified_processing_array", native=native, input_sha256=inputs,
                  mapped_pe_cells=54580, memories=28)
    (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    run(**vars(parser.parse_args()))
