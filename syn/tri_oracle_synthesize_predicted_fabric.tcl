# Existing shared prediction, one twenty-core fabric and actual cluster memories.
set top tri_oracle_predicted_fabric
if {$::env(TRI_ORACLE_TOP) ne $top} {error "Unexpected prediction/fabric top"}
set output .cache/physical/synthesis/$top
file mkdir $output
set_db auto_ungroup none
set_db max_cpus 18
read_libs $::env(TRI_ORACLE_LIBS)
read_hdl -netlist $::env(TRI_ORACLE_IMPORTED_CORE_NETLIST)
read_hdl -sv $output/compiled_cluster_sources.sv
elaborate $top
check_design -unresolved > $output/elaboration_check.rpt
set imported [get_db hinsts -if {.module.name == tri_oracle_sram_memory_compute}]
if {[llength $imported] != 20} {
    error "Expected20 complete imported cores; observed [llength $imported]"
}
set file [open $output/imported_cores.tsv w]
puts $file "instance\tmodule\tpreserve"
foreach inst $imported {
    set_db $inst .preserve true
    if {![get_db $inst .preserve]} {error "Imported core not preserved"}
    puts $file "[get_db $inst .name]\t[get_db $inst .module.name]\t[get_db $inst .preserve]"
}
close $file
puts TRI_ORACLE_PREDICTED_FABRIC_TWENTY_CORES_PRESERVED
create_clock -name core_clock -period 1.72414 [get_ports clk]
set_clock_uncertainty 0.05 [get_clocks core_clock]
set inputs [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_input_delay 0.2 -clock core_clock $inputs
set_output_delay 0.2 -clock core_clock [all_outputs]
set_input_transition 0.05 $inputs
set_load 0.005 [all_outputs]
set_false_path -from [get_ports rst_n]
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
check_design -unresolved > $output/mapped_check.rpt
check_timing_intent -verbose > $output/timing_intent.rpt
report_area > $output/area.rpt
report_timing > $output/timing.rpt
report_power > $output/power_default_activity.rpt
write_hdl > $output/netlist.v
write_sdc > $output/constraints.sdc
puts "TRI_ORACLE_SYNTHESIS_PASS $top"
exit
