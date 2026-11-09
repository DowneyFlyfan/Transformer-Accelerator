# Provisional parent mapping; final physical timing must use full core models.
set top tri_oracle_predicted_feedforward_frame
if {$::env(TRI_ORACLE_TOP) ne $top} {error "Unexpected staged prepared-frame top"}
set output $::env(TRI_ORACLE_SYNTH_OUTPUT)
file mkdir $output
set_db auto_ungroup none
set_db partition_based_synthesis false
set_db auto_partition false
set_db auto_super_thread false
set_db super_thread_servers {}
set_db max_cpus_per_server 18
puts "TRI_ORACLE_BOUNDARY_TRIAL pbs=[get_db / .partition_based_synthesis] partition=[get_db / .auto_partition] automatic=[get_db / .auto_super_thread] servers=[get_db / .super_thread_servers] max_cpus=[get_db / .max_cpus_per_server]"
read_libs $::env(TRI_ORACLE_LIBS)
# The original core is represented by its actual extracted library cell here.
# Its complete mapped netlist is restored for function and physical validation.
read_hdl -sv $output/compiled_cluster_sources.sv
elaborate $top
check_design -unresolved > $output/elaboration_check.rpt
set down_controls [get_db hinsts -if {.module.name == tri_oracle_down_executor_staged}]
set projection_controls [get_db hinsts -if {.module.name == tri_oracle_sparse_weight_dma_pipelined}]
if {[llength $down_controls]!=20 || [llength $projection_controls]!=5} {
    error "Staged source binding mismatch: [llength $down_controls] down controls, [llength $projection_controls] projection controls"
}
set staged_file [open $output/staged_control_bindings.tsv w]
puts $staged_file "instance\tmodule"
foreach control [concat $down_controls $projection_controls] {
    puts $staged_file "[get_db $control .name]\t[get_db $control .module.name]"
}
close $staged_file
puts TRI_ORACLE_FRAME122_STAGED_CONTROLS_20_DOWN_5_PROJECTION_BOUND

proc verify_real_banks {filename preserve_now} {
    set cores [get_db insts -if {.base_cell.name == tri_oracle_sram_memory_compute}]
    set memories [get_db insts -if {.base_cell.name == TS6N28HPCPSVTA16X128M2F}]
    if {[llength $cores] != 20 || [llength $memories] != 40} {
        error "Expected20 full-core cells and40 aggregate memories; observed [llength $cores], [llength $memories]"
    }
    set file [open $filename w]
    puts $file "instance\tmaster\tarea_um2\tpreserve"
    foreach inst [concat $cores $memories] {
        if {$preserve_now} {set_db $inst .preserve true}
        if {![get_db $inst .preserve]} {error "Required core or bank lost preservation"}
        set area [get_db $inst .base_cell.area]
        if {[get_db $inst .base_cell.name] eq "tri_oracle_sram_memory_compute" &&
            abs($area - 482369.843750) > 0.01} {
            error "Core model area does not match the actual original footprint"
        }
        puts $file "[get_db $inst .name]\t[get_db $inst .base_cell.name]\t$area\t[get_db $inst .preserve]"
    }
    close $file
}
verify_real_banks $output/preserved_banks_before.tsv true
puts TRI_ORACLE_BOUNDARY_TRIAL_TWENTY_CORES_FORTY_BANKS_PRESERVED
create_clock -name core_clock -period 1.72414 [get_ports clk]
set_clock_uncertainty 0.05 [get_clocks core_clock]
set inputs [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_input_delay 0.2 -clock core_clock $inputs
set_output_delay 0.2 -clock core_clock [all_outputs]
set_input_transition 0.05 $inputs
set_load 0.005 [all_outputs]
set_false_path -from [get_ports rst_n]
set scope [open $output/boundary_model_scope.rpt w]
puts $scope "Provisional synthesis trial only. Model80 retains38 setup and26 hold transition comparison failures, maximum3.4ps."
puts $scope "All6337 setup and6332 hold worst-slack comparisons passed unchanged1ps/0.1% limits."
puts $scope "Final functional checks restore original core44 mapped netlist; final physical checks require full keep_all core models."
puts $scope "No core power model was extracted; parent power does not establish chip power or paper energy."
close $scope
set_db syn_generic_effort medium
set_db syn_map_effort medium
set_db syn_opt_effort medium
syn_generic
write_db $output/generic.db
puts "TRI_ORACLE_GENERIC_CHECKPOINT_WRITTEN $top"
syn_map
write_db $output/mapped.db
puts "TRI_ORACLE_MAPPED_CHECKPOINT_WRITTEN $top"
syn_opt
verify_real_banks $output/preserved_banks_after.tsv false
write_db $output/optimized.db
check_design -unresolved > $output/mapped_check.rpt
check_timing_intent -verbose > $output/timing_intent.rpt
report_area > $output/area.rpt
report_timing -max_paths 20 > $output/timing.rpt
write_hdl > $output/netlist.v
write_sdc > $output/constraints.sdc
puts "TRI_ORACLE_FRAME122_SYNTHESIS_PASS $top"
exit
