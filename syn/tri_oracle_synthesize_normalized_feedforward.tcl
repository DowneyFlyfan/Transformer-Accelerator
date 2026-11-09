# Integrate the source-qualified prediction frontend with the mapped compute top.
# Run through the guarded flow after the current routed regression releases its lock.
set_db auto_ungroup none
set_db auto_super_thread false
set_db super_thread_servers {localhost localhost}
set_db max_cpus_per_server 10
set top tri_oracle_normalized_feedforward_core
if {$::env(TRI_ORACLE_TOP) ne $top} {error "Unexpected normalized feed-forward top"}
set output .cache/physical/synthesis/$top
file mkdir $output
read_libs $::env(TRI_ORACLE_LIBS)
read_hdl -netlist $::env(TRI_ORACLE_IMPORTED_CORE_NETLIST)
foreach dependency {tri_oracle_rmsnorm tri_oracle_sign_fetch tri_oracle_prediction_feedforward_core tri_oracle_normalized_feedforward_core} {
    read_hdl -sv verilog/${dependency}.sv
}
elaborate $top
check_design -unresolved
set imported [get_db hinsts execution/core]
if {[llength $imported] != 1 || [get_db $imported .name] ne "execution/core"} {
    error "Expected one top-level imported feed-forward core"
}
set_db $imported .preserve true
puts "TRI_ORACLE_IMPORTED_CORE_PRESERVED [get_db $imported .name]"
puts "TRI_ORACLE_WORKER_CONFIGURATION servers=[get_db / .super_thread_servers] cpus_per_server=[get_db / .max_cpus_per_server] automatic=[get_db / .auto_super_thread]"
create_clock -name core_clock -period 1.724137931 [get_ports clk]
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
write_db ${output}/generic.db
puts "TRI_ORACLE_GENERIC_CHECKPOINT_WRITTEN $top"
syn_map
write_db ${output}/mapped.db
puts "TRI_ORACLE_MAPPED_CHECKPOINT_WRITTEN $top"
syn_opt
report_area > ${output}/area.rpt
report_timing > ${output}/timing.rpt
report_power > ${output}/power_default_activity.rpt
write_hdl > ${output}/netlist.v
write_sdc > ${output}/constraints.sdc
puts "TRI_ORACLE_SYNTHESIS_PASS $top"
exit
