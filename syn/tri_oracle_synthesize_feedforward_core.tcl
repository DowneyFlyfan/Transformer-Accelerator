# Hierarchical synthesis using the qualified full-capacity mapped core.
# Standalone entry deliberately avoids common max_cpus alias overriding8.
set_db auto_ungroup none
set_db auto_super_thread false
set_db super_thread_servers {localhost localhost}
set_db max_cpus_per_server 8
set top tri_oracle_feedforward_core
if {$::env(TRI_ORACLE_TOP) ne $top} {error "Entry is for the feed-forward top"}
set output .cache/physical/synthesis/$top
file mkdir $output
read_libs $::env(TRI_ORACLE_LIBS)
# Genus25.10 documents -netlist as the structural reader for mixed RTL builds.
read_hdl -netlist $::env(TRI_ORACLE_IMPORTED_CORE_NETLIST)
foreach unit {strip_predictor channel_compactor predicted_dispatch sparse_weight_dma tile_executor silu_gate gated_executor down_executor feedforward_core} {
    read_hdl -sv verilog/tri_oracle_${unit}.sv
}
elaborate $top
check_design -unresolved
set core_instance [get_db hinsts *core]
if {[llength $core_instance] != 1} {error "Expected exactly one mapped core instance"}
set_db $core_instance .preserve true
puts "TRI_ORACLE_IMPORTED_CORE_PRESERVED [get_db $core_instance .name]"
puts "TRI_ORACLE_WORKER_CONFIGURATION servers=[get_db / .super_thread_servers] cpus_per_server=[get_db / .max_cpus_per_server] automatic=[get_db / .auto_super_thread]"
# Same local interface budgets as the qualified block flow.
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
