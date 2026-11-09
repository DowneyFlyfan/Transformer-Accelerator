# Retain the optimized graph and classify exact proven disconnected wrapper inputs.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_predicted_feedforward_frame
set output $::env(TRI_ORACLE_SYNTH_OUTPUT)
set previous $root/.cache/physical/synthesis/tri_oracle_predicted_feedforward_rowguard175
set candidate $root/.cache/physical/synthesis/tri_oracle_predicted_feedforward_resume199
set_db fail_on_error_mesg true
read_db $candidate/postopt_candidate.db
current_design $top
set_db max_cpus_per_server 20
source $candidate/retained_inventory_procedures.tcl
source $root/syn/tri_oracle_mapped_boundary199.tcl
proc snapshot_leaf213 {filename} {
    set stream [open $filename w]
    foreach cell [get_db insts] {puts $stream "[get_db $cell .name]\t[get_db $cell .base_cell.name]"}
    close $stream
    exec env LC_ALL=C sort -S 64M -T $::env(TRI_ORACLE_SYNTH_OUTPUT) -o ${filename}.sorted $filename
}
proc snapshot_ports213 {filename} {
    set rows {}
    foreach port [get_db ports] {lappend rows "[get_db $port .name]\t[get_db $port .direction]"}
    set stream [open $filename w]
    foreach row [lsort $rows] {puts $stream $row}
    close $stream
}
snapshot_leaf213 $output/all_cells_before.tsv
snapshot_ports213 $output/ports_before.tsv
set stream [open $output/cleanup_targets.txt r]
set names [split [string trim [read $stream]] "\n"];close $stream
if {[llength $names]!=32106 || [llength [lsort -unique $names]]!=32106} {error POSTOPT213_WRONG_CLEANUP_COUNT}
set targets {}
foreach name $names {
    set pin "hpin:${top}/${name}"
    if {[get_db $pin .name] ne $name || [get_db $pin .direction] ne "in"} {error POSTOPT213_TARGET_IDENTITY_CHANGED}
    if {[llength [get_db $pin .net]]!=0 || [llength [get_db $pin .hport.net]]!=0} {error POSTOPT213_TARGET_HAS_FLAT_CONNECTION}
    if {[string match */implementation/* $name]} {error POSTOPT213_PRESERVED_IMPLEMENTATION_TARGET}
    lappend targets $pin
}
snapshot_leaf213 $output/all_cells_after.tsv
snapshot_ports213 $output/ports_after.tsv
if {[catch {exec cmp -s $output/all_cells_before.tsv.sorted $output/all_cells_after.tsv.sorted}]} {error POSTOPT213_LEAF_CELLS_CHANGED}
if {[catch {exec cmp -s $output/ports_before.tsv $output/ports_after.tsv}]} {error POSTOPT213_TOP_PORTS_CHANGED}
check_design -unresolved > $output/postopt_check.rpt
check_design -undriven -multiple_driver -cross_hier > $output/postopt_wiring.rpt
if {[check_design -unresolved -status] || [check_design -multiple_driver -status] || [check_design -cross_hier -status]} {error POSTOPT213_LIVE_WIRING_CHECK_FAILED}
set raw_undriven [check_design -undriven -status]
if {$raw_undriven!=1} {error POSTOPT213_UNEXPECTED_RAW_UNDRIVEN_STATUS}
puts "POSTOPT213_RAW_UNDRIVEN_STATUS $raw_undriven"
exec python3 -B $root/syn/tri_oracle_audited_wiring213.py $output/postopt_wiring.rpt $output/cleanup_targets.txt $output/audited_wiring.json
write_db -design $top $output/audited_candidate.db
set down_controls [get_db hinsts -if {.module.name == tri_oracle_down_executor_staged}]
set projection_controls [get_db hinsts -if {.module.name == tri_oracle_sparse_weight_dma_pipelined}]
if {[llength $down_controls]!=20 || [llength $projection_controls]!=5} {error POSTOPT213_CONTROL_SET_CHANGED}
set reused_control_expected [dict create]
foreach control $down_controls {dict set reused_control_expected [get_db $control .name] 11049}
foreach control $projection_controls {dict set reused_control_expected [get_db $control .name] 2047}
verify_real_banks $output/preserved_banks_after.tsv false
snapshot_reused_controls131 $output/reused_controls_after.tsv $reused_control_expected
tri_oracle_boundary199_open $output/boundary_connections_after.tsv
tri_oracle_control_boundaries199 [concat $down_controls $projection_controls] $output/mapped_controller_boundaries_after.tsv
gate_snapshot199 $output/gate_cells_after.tsv $output/gate_boundary_after.tsv $output/gate_preservation_after.tsv
tri_oracle_boundary199_close
write_sdc > $output/postopt_constraints.sdc
exec python3 -B $root/syn/tri_oracle_mapped_restore199.py $previous $output after
write_db -design $top $output/optimized.db
report_area > $output/area.rpt
report_timing -max_paths 20 > $output/timing.rpt
write_hdl > $output/netlist.v
write_sdc > $output/constraints.sdc
puts TRI_ORACLE_POSTOPT213_AUDITED_FINALIZATION_COMPLETED
exit
