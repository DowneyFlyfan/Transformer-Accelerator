# Appended to the checked original frame144 elaboration prefix. Both affected
# source controllers use the tested maximum-active-row guard. All mapped
# controller imports and the original20 core/40 bank graph remain intact.
proc gate_snapshot175 {cells_file boundary_file preserve_file} {
    global top output
    set path numeric/engine/gated/implementation
    set gate [get_db hinsts -if [list .name == $path]]
    if {[llength $gate]!=1 || [get_db $gate .module.name] ne "tri_oracle_fabric_gated_executor_mapped153"} {
        error FRAME175_WRONG_PRIVATE_GATE
    }
    if {![get_db $gate .preserve]} {error FRAME175_GATE_PRESERVATION_LOST}
    set prefix "${path}/"
    set stream [open $cells_file w]
    set count 0
    foreach leaf [get_db [get_db designs $top] .insts] {
        set name [get_db $leaf .name]
        if {[string first $prefix $name]!=0} {continue}
        puts $stream "[string range $name [string length $prefix] end]\t[get_db $leaf .base_cell.name]"
        incr count
    }
    close $stream
    if {$count!=151275} {error FRAME175_GATE_CELL_COUNT_CHANGED}
    set stream [open $boundary_file w]
    set count 0
    foreach pin [get_db $gate .hpins] {
        set relative [string range [get_db $pin .name] [string length $prefix] end]
        if {[string first / $relative]>=0} {continue}
        set net [get_db $pin .hnet]
        if {[llength $net]!=1} {error FRAME175_GATE_BOUNDARY_DISCONNECTED}
        puts $stream "[get_db $pin .name]\t[get_db $net .name]"
        incr count
    }
    close $stream
    if {$count!=21012} {error FRAME175_GATE_BOUNDARY_WIDTH_CHANGED}
    set stream [open $preserve_file w]
    puts $stream "[get_db $gate .name]\t[get_db $gate .module.name]\t[get_db $gate .preserve]"
    close $stream
    exec env LC_ALL=C sort -o ${cells_file}.sorted $cells_file
    exec env LC_ALL=C sort -o $output/gate_expected.sorted $::env(TRI_ORACLE_GATE175_ISOLATED_CELLS)
    if {[catch {exec cmp -s ${cells_file}.sorted $output/gate_expected.sorted}]} {
        error FRAME175_GATE_DIFFERS_FROM_INDEPENDENT_ISOLATED_LEDGER
    }
}
set gate [get_db hinsts -if {.name == numeric/engine/gated/implementation}]
if {[llength $gate]!=1} {error FRAME175_PRIVATE_GATE_NOT_FOUND}
set_db $gate .preserve true
gate_snapshot175 $output/gate_cells_before.tsv $output/gate_boundary_before.tsv $output/gate_preservation_before.tsv
if {[catch {exec cmp -s $output/reused_controls_before.tsv.sorted $::env(TRI_ORACLE_GATE175_ORIGINAL_CONTROLS)}]} {
    error FRAME175_ORIGINAL25_CONTROL_CELLS_CHANGED
}
if {[check_design -unresolved -status]} {error FRAME175_UNRESOLVED_PREOPT_PARENT}
write_sdc > $output/elaborated_constraints.sdc
write_db -design $top $output/elaborated.db
exec python3 -B $root/syn/tri_oracle_row_guard175_checkpoint.py $output $::env(TRI_ORACLE_GATE175_PREPARED) $::env(TRI_ORACLE_GATE175_ISOLATED_CELLS)
puts TRI_ORACLE_FRAME175_FULL_PARENT_GUARD_CHECKPOINT_WRITTEN
syn_generic
write_db -design $top $output/generic.db
puts TRI_ORACLE_FRAME175_GENERIC_CHECKPOINT_WRITTEN
syn_map
write_db -design $top $output/mapped.db
puts TRI_ORACLE_FRAME175_MAPPED_CHECKPOINT_WRITTEN
syn_opt
write_db -design $top $output/postopt_candidate.db
verify_real_banks $output/preserved_banks_after.tsv false
snapshot_reused_controls131 $output/reused_controls_after.tsv $reused_control_expected
if {[catch {exec cmp -s $output/reused_controls_before.tsv.sorted $output/reused_controls_after.tsv.sorted}]} {
    error FRAME175_ORIGINAL_CONTROLLER_CELLS_CHANGED_AFTER_MAPPING
}
gate_snapshot175 $output/gate_cells_after.tsv $output/gate_boundary_after.tsv $output/gate_preservation_after.tsv
if {[check_design -unresolved -status]} {error FRAME175_UNRESOLVED_MAPPED_PARENT}
if {[check_design -undriven -multiple_driver -cross_hier -status]} {error FRAME175_BAD_MAPPED_PARENT_WIRING}
write_db -design $top $output/optimized.db
check_design -unresolved > $output/mapped_check.rpt
check_design -undriven -multiple_driver -cross_hier > $output/mapped_wiring.rpt
check_timing_intent -verbose > $output/timing_intent.rpt
report_area > $output/area.rpt
report_timing -max_paths 20 > $output/timing.rpt
write_hdl > $output/netlist.v
write_sdc > $output/constraints.sdc
puts TRI_ORACLE_FRAME175_PARENT_MAPPING_COMPLETED
exit
