# Map the dual-edge capture storage at the slow core corner.
set root [file dirname [file dirname [file normalize [info script]]]]
set out [file normalize $::env(TRI_ORACLE_DUAL_EDGE_OUTPUT)]
file mkdir $out
set_db auto_ungroup none
set_db auto_super_thread false
read_libs [file join $root .cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib]
read_hdl -sv [file join $root verilog/tri_oracle_dual_edge_memory_capture.sv]
elaborate tri_oracle_dual_edge_memory_capture
check_design -unresolved
create_clock -name core_clock -period 1.72414 -waveform {0 0.86207} [get_ports clk]
set core [get_clocks core_clock]
set_clock_uncertainty 0.05 $core
# Assumed peer launch and on-die interface budgets, before pads and routing.
set data [get_ports pad_data*]
set sideband [get_ports {pad_valid* pad_last* pad_error* pad_compact* pad_words*}]
set_output_delay 0.2 -clock $core [get_ports {out_* pad_ready[0]}]
set_output_delay 0.2 -clock $core -clock_fall [get_ports {pad_ready[1]}]
set_input_delay 0.2 -clock $core $data
set_input_delay 0.2 -clock $core -clock_fall -add_delay $data
set_input_delay 0.2 -clock $core $sideband
set_input_delay 0.2 -clock $core -clock_fall -add_delay $sideband
set_input_delay 0.2 -clock $core [get_ports out_ready*]
set_input_transition 0.05 [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_load 0.005 [all_outputs]
set_false_path -from [get_ports rst_n]
syn_generic
syn_map
syn_opt
check_design -unresolved > $out/mapped_check.rpt
report_area > $out/area.rpt
report_timing -max_paths 10 > $out/timing.rpt
report_timing -from [get_ports {pad_data[0]}] -max_paths 2 > $out/input_timing.rpt
report_timing -to [get_ports {out_data[448]}] -max_paths 2 > $out/falling_output_timing.rpt
report_timing -to [get_ports {pad_ready[1]}] -max_paths 2 > $out/falling_ready_timing.rpt
write_hdl > $out/netlist.v
write_sdc > $out/constraints.sdc
puts TRI_ORACLE_DUAL_EDGE_CAPTURE_GENUS_FINISHED
exit
