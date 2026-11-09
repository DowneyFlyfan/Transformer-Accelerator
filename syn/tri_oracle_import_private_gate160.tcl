set output $::env(TRI_ORACLE_GATE160_OUTPUT)
set top tri_oracle_fabric_gated_executor_mapped153
set_db fail_on_error_mesg true
set_db auto_ungroup none
set_db max_cpus_per_server 20
set_db message:ELABUTL/ELABUTL-124 .severity Error
set_db message:ELABUTL/ELABUTL-123 .severity Error
read_libs {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator/.cache/physical/library/tcbn28hpcplusbwp12t40p140tt1v25c.lib}
read_hdl -netlist $output/private_candidate.v
elaborate $top
if {[check_design -unresolved -status]} {error GATE160_UNRESOLVED_NATIVE_IMPORT}
if {[check_design -undriven -multiple_driver -cross_hier -status]} {error GATE160_BAD_NATIVE_WIRING}
check_design -undriven -multiple_driver -cross_hier > $output/isolated_wiring.rpt
set stream [open $output/isolated_cells.tsv w]
set cells [get_db [get_db designs $top] .insts]
if {[llength $cells]<1000} {error GATE160_MAPPED_CELLS_MISSING}
foreach leaf $cells {
    set master [get_db $leaf .base_cell.name]
    if {![string match *BWP12T40P140 $master]} {error GATE160_NONSTANDARD_LEAF}
    puts $stream "[get_db $leaf .name]\t$master"
}
close $stream
set stream [open $output/isolated_hierarchy.tsv w]
foreach instance [get_db [get_db designs $top] .hinsts] {
    puts $stream "[get_db $instance .name]\t[get_db $instance .module.name]"
}
close $stream
write_hdl > $output/qualified_import.v
write_db -design $top $output/isolated.db
puts TRI_ORACLE_GATE160_PRIVATE_NATIVE_IMPORT_EXPORTED
exit
