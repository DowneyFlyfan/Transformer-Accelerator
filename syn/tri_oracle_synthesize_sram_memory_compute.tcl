# Actual compiler-backed 19KB compute core; original port timing budgets.
# Eighteen synthesis workers plus two ongoing integration simulations fit the20CPU quota.
set_db max_cpus 18
set top tri_oracle_sram_memory_compute
if {$::env(TRI_ORACLE_TOP) ne $top} {error "Unexpected SRAM cache synthesis top"}
set output .cache/physical/synthesis/$top
file mkdir $output
read_libs $::env(TRI_ORACLE_LIBS)
read_hdl -sv [list verilog/tri_oracle_sram_memory_compute.sv verilog/tri_oracle_pe_array.sv]
elaborate $top
check_design -unresolved > $output/elaboration_check.rpt
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
