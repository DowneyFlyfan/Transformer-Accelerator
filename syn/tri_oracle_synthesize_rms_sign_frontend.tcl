# Standalone source-qualified frontend; run through the existing synthesis guard.
# Physical reproduction still requires complete processor/memory integration.
set_db max_cpus 20
set top tri_oracle_rms_sign_predictor
if {$::env(TRI_ORACLE_TOP) ne $top} {error "Unexpected frontend synthesis top"}
set output .cache/physical/synthesis/$top
file mkdir $output
read_libs $::env(TRI_ORACLE_LIBS)
foreach dependency {tri_oracle_rmsnorm tri_oracle_sign_fetch tri_oracle_strip_predictor} {
    read_hdl -sv verilog/${dependency}.sv
}
read_hdl -sv verilog/${top}.sv
elaborate $top
check_design -unresolved
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
syn_map
write_db ${output}/mapped.db
syn_opt
report_area > ${output}/area.rpt
report_timing > ${output}/timing.rpt
report_power > ${output}/power_default_activity.rpt
write_hdl > ${output}/netlist.v
write_sdc > ${output}/constraints.sdc
puts "TRI_ORACLE_SYNTHESIS_PASS $top"
exit
