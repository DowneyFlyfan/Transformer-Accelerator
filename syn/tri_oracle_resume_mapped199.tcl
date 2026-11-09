# Resume only final optimization from the source-bound completed mapping.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_predicted_feedforward_frame
set output $::env(TRI_ORACLE_SYNTH_OUTPUT)
set previous $::env(TRI_ORACLE_RESUME199_SOURCE)
set_db fail_on_error_mesg true
read_db $previous/mapped.db
if {[llength [get_db designs]]!=1 || [get_db [get_db designs] .name] ne $top} {error FRAME199_WRONG_RESTORED_TOP}
current_design $top
set_db auto_ungroup none
set_db partition_based_synthesis false
set_db auto_partition false
set_db auto_super_thread false
set_db super_thread_servers {}
set_db max_cpus_per_server 20
set_db syn_global_effort none
set_db control_logic_optimization none
set_db syn_opt_effort medium
if {[get_db / .control_logic_optimization] ne "none" || [get_db / .syn_global_effort] ne "none"} {error FRAME199_UNEXPECTED_OPTIMIZER_OVERRIDE}
source $output/retained_inventory_procedures.tcl
source $root/syn/tri_oracle_mapped_boundary199.tcl
tri_oracle_boundary199_open $output/boundary_connections_before.tsv
set down_controls [get_db hinsts -if {.module.name == tri_oracle_down_executor_staged}]
set projection_controls [get_db hinsts -if {.module.name == tri_oracle_sparse_weight_dma_pipelined}]
if {[llength $down_controls]!=20 || [llength $projection_controls]!=5} {error FRAME199_RESTORED_CONTROLS_MISSING}
set reused_control_expected [dict create]
foreach group [list $down_controls $projection_controls] expected {6075 2840} cell_count {11049 2047} {
    foreach control $group {
        if {![get_db $control .preserve]} {error FRAME199_CONTROL_PRESERVATION_LOST}
        dict set reused_control_expected [get_db $control .name] $cell_count
        set hpins [get_db $control .hpins]
        if {[llength $hpins]!=$expected} {error FRAME199_WRONG_CONTROL_BOUNDARY_WIDTH}
    }
}
tri_oracle_control_boundaries199 [concat $down_controls $projection_controls] $output/mapped_controller_boundaries.tsv
verify_real_banks $output/preserved_banks_before.tsv false
snapshot_reused_controls131 $output/reused_controls_before.tsv $reused_control_expected
if {[catch {exec cmp -s $output/reused_controls_before.tsv.sorted $previous/reused_controls_before.tsv.sorted}]} {error FRAME199_ORIGINAL25_CONTROL_CELLS_CHANGED}
gate_snapshot199 $output/gate_cells_before.tsv $output/gate_boundary_before.tsv $output/gate_preservation_before.tsv
tri_oracle_boundary199_close
check_design -unresolved > $output/restored_check.rpt
check_design -undriven -multiple_driver -cross_hier > $output/restored_wiring.rpt
if {[check_design -unresolved -status]} {error FRAME199_UNRESOLVED_COLD_RESTORE}
if {[check_design -undriven -multiple_driver -cross_hier -status]} {error FRAME199_BAD_COLD_RESTORE_WIRING}
write_sdc > $output/restored_constraints.sdc
write_hdl > $output/mapped_restore.v
write_sdc > $output/mapped_restore.sdc
exec python3 -B $root/syn/tri_oracle_mapped_restore199.py $previous $output
puts TRI_ORACLE_FRAME199_MAPPED_COLD_RESTORE_VERIFIED
# No generic synthesis or technology mapping is repeated here.
syn_opt
write_db -design $top $output/postopt_candidate.db
verify_real_banks $output/preserved_banks_after.tsv false
snapshot_reused_controls131 $output/reused_controls_after.tsv $reused_control_expected
if {[catch {exec cmp -s $output/reused_controls_before.tsv.sorted $output/reused_controls_after.tsv.sorted}]} {error FRAME199_ORIGINAL25_CONTROLS_CHANGED_AFTER_OPT}
tri_oracle_boundary199_open $output/boundary_connections_after.tsv
tri_oracle_control_boundaries199 [concat $down_controls $projection_controls] $output/mapped_controller_boundaries_after.tsv
gate_snapshot199 $output/gate_cells_after.tsv $output/gate_boundary_after.tsv $output/gate_preservation_after.tsv
tri_oracle_boundary199_close
if {[check_design -unresolved -status]} {error FRAME199_UNRESOLVED_OPTIMIZED_PARENT}
if {[check_design -undriven -multiple_driver -cross_hier -status]} {error FRAME199_BAD_OPTIMIZED_PARENT_WIRING}
check_design -unresolved > $output/postopt_check.rpt
check_design -undriven -multiple_driver -cross_hier > $output/postopt_wiring.rpt
write_sdc > $output/postopt_constraints.sdc
exec python3 -B $root/syn/tri_oracle_mapped_restore199.py $previous $output after
write_db -design $top $output/optimized.db
check_design -unresolved > $output/mapped_check.rpt
check_design -undriven -multiple_driver -cross_hier > $output/mapped_wiring.rpt
check_timing_intent -verbose > $output/timing_intent.rpt
report_area > $output/area.rpt
report_timing -max_paths 20 > $output/timing.rpt
write_hdl > $output/netlist.v
write_sdc > $output/constraints.sdc
puts TRI_ORACLE_FRAME199_PARENT_OPTIMIZATION_COMPLETED
exit
