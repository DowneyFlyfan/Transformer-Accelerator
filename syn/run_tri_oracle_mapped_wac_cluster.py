"""Map one Tri-Oracle cluster around four verified compute core netlists."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from prepare_tri_oracle_wac_outlier_layer import read, sha, verify
from replay_mapped_cluster_fixture import STAGE, shared_memory_stage, wait_for_shared_memory

CORNER = "ssg0p9v125c"
UNITS = (
    "wac_softmax_types.sv", "tri_oracle_cluster_token_sizes_with_layer_ports.sv",
    "tri_oracle_local_merge_fabric.sv", "tri_oracle_attention_head_classifier410.sv",
    "tri_oracle_causal_token_size.sv", "tri_oracle_cumulative_token_merger423.sv",
    "tri_oracle_sram_compute_cluster.sv", "tri_oracle_strip_predictor.sv", "tri_oracle_token_merger.sv", "wrappers.sv",
)


def recipe(source, netlist, libraries, top, expected_memory, core_cells):
    lib_list = " ".join(f"{{{path}}}" for path in libraries)
    return rf"""set_db max_cpus 1
set_db auto_ungroup none
set_db auto_super_thread false
set_db super_thread_servers {{}}
set_db partition_based_synthesis false
set_db auto_partition false
set_db fail_on_error_mesg true
read_libs [list {lib_list}]
read_hdl -netlist {{{netlist}}}
read_hdl -sv {{{source}}}
elaborate {top}
set cores [get_db hinsts -if {{.module.name == tri_oracle_sram_memory_compute}}]
if {{[llength $cores] != 4}} {{error "Expected four imported compute cores"}}
foreach core $cores {{set_db $core .preserve true}}
foreach memory [get_db insts -if {{.base_cell.name =~ TS*N28HPCPSVTA*}}] {{set_db $memory .preserve true}}
proc census {{stage}} {{
    set cores [list]
    set memory [list]
    foreach cell [get_db insts] {{
        set name [get_db $cell .name]
        set master [get_db $cell .base_cell.name]
        if {{[regexp {{^source_cluster/implementation/cores\[[0-3]\]/compute/}} $name]}} {{lappend cores "$name\t$master"}}
        if {{[string match "TS*N28HPCPSVTA*" $master]}} {{lappend memory "$name\t$master"}}
    }}
    if {{[llength $cores] != {4*core_cells} || [llength $memory] != {expected_memory}}} {{
        error "Unexpected cluster inventory: compute=[llength $cores] memory=[llength $memory]"
    }}
    foreach {{suffix rows}} [list cores $cores memory $memory] {{
        set file [open "$stage.$suffix.tsv" w]
        foreach row [lsort $rows] {{puts $file $row}}
        close $file
    }}
}}
census before
check_design -unresolved > unresolved_before.rpt
create_clock -name core_clock -period 1.724137931 [get_ports clk]
set inputs [remove_from_collection [all_inputs] [get_ports {{clk rst_n}}]]
set_clock_uncertainty 0.05 [get_clocks core_clock]
set_input_delay 0.2 -clock core_clock $inputs
set_output_delay 0.2 -clock core_clock [all_outputs]
set_input_transition 0.05 $inputs
set_load 0.005 [all_outputs]
set_false_path -from [get_ports rst_n]
write_db elaborated.db
puts MAPPED_WAC_CLUSTER_ELABORATED
syn_generic
write_db generic.db
puts MAPPED_WAC_CLUSTER_GENERIC
syn_map
syn_opt
census after
check_design -unresolved > unresolved_after.rpt
report_area > area.rpt
report_timing -max_paths 10 > timing.rpt
write_hdl > netlist.v
write_sdc > clock.sdc
write_db mapped.db
puts MAPPED_WAC_CLUSTER_COMPLETE
exit
"""


def prepare(case, bank, output):
    setup_path = case / "receipt.json"
    setup = read(setup_path)
    assert setup["mapped_compute_leaf_count"] == 20 and setup["mapped_banks"] == []
    netlist = Path(setup["mapped_core_netlist"])
    inputs = setup["input_sha256"].copy()
    verify(inputs)
    assert inputs[str(netlist)] == sha(netlist)
    bundle = case / "bundle.sv"
    included = [Path(name) for name in re.findall(r'(?m)^`include "([^"]+)"$', bundle.read_text())]
    sources = [path for path in included if path.name in UNITS]
    assert len(sources) == len(UNITS) and {path.name for path in sources} == set(UNITS)
    assert all(inputs[str(path)] == sha(path) for path in sources)

    inventory_path = STAGE / "inventory.json"
    views_path = STAGE / "paper_operating_view_inventory.json"
    interfaces_path = STAGE / "memory_physical_view_interfaces.json"
    core_area = netlist.parent / "area.rpt"
    for path in (inventory_path, interfaces_path, core_area):
        assert inputs[str(path)] == sha(path)
    area_row = re.search(r"(?m)^tri_oracle_sram_memory_compute\s+NA\s+(\d+)", core_area.read_text())
    assert area_row and int(area_row[1]) > 0
    library_paths = [Path(path) for path in read(views_path)["common_corners"][CORNER]["files"]]
    assert len(library_paths) == 7
    views = read(interfaces_path)["macros"]
    memory_hashes = Counter(item["timing_sha256"][CORNER] for item in views.values())
    assert Counter(sha(path) for path in library_paths[1:]) == memory_hashes
    assert inputs[str(library_paths[0])] == sha(library_paths[0])
    expected = read(inventory_path)[str(bank)]["macros"]
    top = f"tri_oracle_native_cluster{bank}"
    output.mkdir()
    source = output / "sources.sv"
    source.write_text("`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n" +
                      "".join(f'`include "{path}"\n' for path in sources))
    script = output / "map.tcl"
    script.write_text(recipe(source, netlist, library_paths, top, sum(expected.values()), int(area_row[1])))
    inputs.update({str(path): sha(path) for path in (Path(__file__), setup_path, views_path, source, script, *library_paths)})
    verify(inputs)
    return inputs, script, top, expected


def run(case, bank, output):
    proof_path = case / "xcelium/mapped_wac_qualification.json"
    proof = read(proof_path)
    assert proof["state"] == "twenty_mapped_compute_cores_replayed_archived_attention"
    assert proof["mapped_compute_cores"] == 20 and proof["compared"]["values"] == 1023
    verify(proof["input_sha256"])
    inputs, script, top, expected = prepare(case, bank, output)
    for path, digest in proof["input_sha256"].items():
        assert inputs.get(path, digest) == digest, path
        inputs[path] = digest
    inputs[str(proof_path)] = sha(proof_path)
    (output / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    wait_for_shared_memory("cluster mapping with four preserved compute cores", 17)
    native = shared_memory_stage("cluster mapping with four preserved compute cores", output, [
        "/usr/bin/prlimit", "--as=7516192768", "--", "/opt/cadence/bin/genus", "-batch",
        "-log", str(output / "genus"), "-files", str(script),
    ], 2700, 0)
    assert (output / "console.log").read_text().splitlines().count("MAPPED_WAC_CLUSTER_COMPLETE") == 1
    for name in ("cores", "memory"):
        assert sha(output / f"before.{name}.tsv") == sha(output / f"after.{name}.tsv")
    after = (output / "after.memory.tsv").read_text().splitlines()
    assert Counter(line.split()[1] for line in after) == expected
    assert "No unresolved references" in (output / "unresolved_after.rpt").read_text()
    verify(inputs)
    exports = {name: sha(output / name) for name in ("after.cores.tsv", "after.memory.tsv", "netlist.v",
               "mapped.db", "clock.sdc", "area.rpt", "timing.rpt", "unresolved_after.rpt")}
    receipt = dict(state="cluster_mapped_around_four_verified_cores", bank=bank, top=top, compiled_memories=expected,
                   native=native, input_sha256=inputs, output_sha256=exports)
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["state"], bank, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("bank", type=int, choices=range(5))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.case.resolve(), args.bank, args.output.resolve())
