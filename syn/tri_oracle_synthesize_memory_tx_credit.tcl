# Map the registered request link and check the opposite-edge launch budget.
set root [file dirname [file dirname [file normalize [info script]]]]
set out [file normalize $::env(TRI_ORACLE_TX_CREDIT_OUTPUT)]
file mkdir $out
set_db auto_ungroup none
set_db auto_super_thread false
read_libs [file join $root .cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib]
read_hdl -sv [list [file join $root verilog/tri_oracle_serial_flit_bridge.sv] \
                 [file join $root verilog/tri_oracle_memory_tx_credit.sv]]
elaborate tri_oracle_memory_tx_credit
check_design -unresolved
create_clock -name core_clock -period 1.72414 -waveform {0.0 0.86207} [get_ports clk]
create_generated_clock -name pad_sample_clock -source [get_ports clk] -edges {2 3 4} [get_ports pad_clock]
set_clock_uncertainty 0.05 [get_clocks {core_clock pad_sample_clock}]
set inputs [get_ports {in_valid in_word* pad_credit}]
set_input_delay 0.2 -clock core_clock [get_ports {in_valid in_word*}]
set_input_delay -min 0.25 -clock core_clock [get_ports pad_credit]
set_input_delay -max 0.35 -clock core_clock [get_ports pad_credit]
set_output_delay 0.2 -clock core_clock [get_ports {in_ready protocol_error}]
set outputs [get_ports {pad_valid pad_data*}]
set_output_delay 0.2 -clock pad_sample_clock $outputs
set_input_transition 0.05 $inputs
set_load 0.005 [all_outputs]
set_false_path -from [get_ports rst_n]
syn_generic
syn_map
syn_opt
check_design -unresolved > $out/mapped_check.rpt
report_area > $out/area.rpt
report_timing -max_paths 8 > $out/setup.rpt
report_timing -to $outputs -max_paths 12 > $out/pad_setup.rpt
write_hdl > $out/netlist.v
write_sdc > $out/constraints.sdc
puts TRI_ORACLE_MEMORY_TX_CREDIT_GENUS_FINISHED
exit
