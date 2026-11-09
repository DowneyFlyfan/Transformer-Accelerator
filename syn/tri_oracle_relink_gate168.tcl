# Append only after the verified frame145 pre-optimization cold-restore prefix.
set imported $::env(TRI_ORACLE_GATED168_MODULE)
set gate_path numeric/engine/gated
set gate [get_db hinsts -if [list .name == $gate_path]]
if {[llength $gate]!=1 || [get_db $gate .module.name] ne "tri_oracle_fabric_gated_executor"} {
    error FRAME168_ORIGINAL_GATE_HIERARCHY_MISMATCH
}
proc boundary159 {instance filename expected} {
    set prefix "[get_db $instance .name]/"
    set stream [open $filename w]
    set count 0
    foreach pin [get_db $instance .hpins] {
        set relative [string range [get_db $pin .name] [string length $prefix] end]
        if {[string first / $relative]>=0} {continue}
        set net [get_db $pin .hnet]
        if {[llength $net]!=1} {error FRAME168_DISCONNECTED_GATE_BOUNDARY}
        puts $stream "[get_db $pin .name]\t[get_db $net .name]"
        incr count
    }
    close $stream
    if {$count!=$expected} {error "FRAME168_GATE_BOUNDARY_BIT_COUNT $count $expected"}
}
boundary159 $gate $output/gate_boundary_before.tsv $::env(TRI_ORACLE_GATED168_BOUNDARY_BITS)
set loaded_modules [get_db modules .name]
set stream [open $output/preexisting_module_names.txt w]
foreach name $loaded_modules {puts $stream $name}
close $stream
foreach name $::env(TRI_ORACLE_GATED168_MODULE_NAMES) {
    if {[lsearch -exact $loaded_modules $name]>=0} {error "FRAME168_IMPORTED_MODULE_COLLISION $name"}
}
read_hdl -netlist $output/gated_import.v
elaborate $imported
current_design $imported
if {[check_design -unresolved -status]} {error FRAME168_UNRESOLVED_PRIVATE_IMPORT}
if {[check_design -undriven -multiple_driver -cross_hier -status]} {error FRAME168_BAD_PRIVATE_IMPORT_WIRING}
set source_cells [get_db [get_db designs $imported] .insts]
set stream [open $output/gate_source_cells.tsv w]
foreach leaf $source_cells {
    set master [get_db $leaf .base_cell.name]
    if {![string match *BWP12T40P140 $master]} {error FRAME168_NONSTANDARD_GATE_LEAF}
    puts $stream "[get_db $leaf .name]\t$master"
}
close $stream
if {[llength $source_cells]<1000} {error FRAME168_GATE_CELL_INVENTORY_MISSING}
exec env LC_ALL=C sort -o $output/gate_source_cells.sorted $output/gate_source_cells.tsv
exec env LC_ALL=C sort -o $output/isolated_expected_cells.sorted $::env(TRI_ORACLE_GATED168_ISOLATED_CELLS)
if {[catch {exec cmp -s $output/gate_source_cells.sorted $output/isolated_expected_cells.sorted}]} {
    error FRAME168_GATE_IMPORT_DIFFERS_FROM_QUALIFIED_ISOLATED_CELLS
}
current_design $top
change_link -instances [get_db hinsts -if [list .name == $gate_path]] -design_name [get_db designs $imported]
set gate [get_db hinsts -if [list .name == $gate_path]]
if {[llength $gate]!=1 || [get_db $gate .module.name] ne $imported} {error FRAME168_MAPPED_GATE_LINK_FAILED}
boundary159 $gate $output/gate_boundary_after.tsv $::env(TRI_ORACLE_GATED168_BOUNDARY_BITS)
write_sdc > $output/relinked_constraints.sdc
set_db $gate .preserve true
write_sdc > $output/elaborated_constraints.sdc
set stream [open $output/gate_parent_cells.tsv w]
set prefix "${gate_path}/"
set count 0
foreach leaf [get_db [get_db designs $top] .insts] {
    set name [get_db $leaf .name]
    if {[string first $prefix $name]!=0} {continue}
    puts $stream "[string range $name [string length $prefix] end]\t[get_db $leaf .base_cell.name]"
    incr count
}
close $stream
if {$count!=[llength $source_cells]} {error FRAME168_GATE_CELL_COUNT_CHANGED}
if {![get_db $gate .preserve]} {error FRAME168_GATE_PRESERVATION_LOST}
set stream [open $output/gate_preservation.tsv w]
puts $stream "[get_db $gate .name]\t[get_db $gate .module.name]\t[get_db $gate .preserve]"
close $stream
snapshot_reused_controls131 $output/reused_controls_after.tsv $reused_control_expected
verify_real_banks $output/preserved_banks_after.tsv false
set down_controls [get_db hinsts -if {.module.name == tri_oracle_down_executor_staged}]
set projection_controls [get_db hinsts -if {.module.name == tri_oracle_sparse_weight_dma_pipelined}]
if {[llength $down_controls]!=20 || [llength $projection_controls]!=5} {error FRAME168_ORIGINAL_CONTROLLERS_LOST}
set stream [open $output/retained_controller_boundaries.tsv w]
puts $stream "instance\thpin\thnet"
foreach control [concat $down_controls $projection_controls] {
    foreach pin [get_db $control .hpins] {
        set net [get_db $pin .hnet]
        if {[llength $net]!=1} {error FRAME168_ORIGINAL_CONTROLLER_DISCONNECTED}
        puts $stream "[get_db $control .name]\t[get_db $pin .name]\t[get_db $net .name]"
    }
}
close $stream
if {[check_design -unresolved -status]} {error FRAME168_UNRESOLVED_RELINKED_PARENT}
check_design -unresolved > $output/relinked_unresolved.rpt
puts TRI_ORACLE_FRAME168_NO_UNRESOLVED_IMPORTS_OR_RELINK
if {[check_design -undriven -multiple_driver -cross_hier -status]} {error FRAME168_BAD_RELINKED_WIRING}
check_design -undriven -multiple_driver -cross_hier > $output/relinked_wiring.rpt
write_db -design $top $output/elaborated.db
puts TRI_ORACLE_FRAME168_MAPPED_GATE_RELINK_CHECKPOINT_WRITTEN
exit
