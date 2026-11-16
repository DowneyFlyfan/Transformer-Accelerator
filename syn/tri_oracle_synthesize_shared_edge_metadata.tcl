# Check both clock edges on every shared metadata bit.
set root [file dirname [file dirname [file normalize [info script]]]]
set base [file join $root .cache/physical/whole_chip_xcelium_speed]
set prior [file join $base split_credit_ingress]
set out [file normalize $::env(TRI_ORACLE_METADATA_OUTPUT)]
file mkdir $out
set top tri_oracle_credit_metadata_ingress

set_db auto_ungroup none
set_db auto_super_thread false
read_libs [file join $root .cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib]
read_hdl -sv [list [file join $root verilog/tri_oracle_credit_metadata_ingress.sv] \
                 [file join $prior tri_oracle_credit_memory_ingress.sv] \
                 [file join $prior tri_oracle_credit_bypass_fifo.sv] \
                 [file join $root verilog/tri_oracle_dual_edge_memory_capture.sv] \
                 [file join $root verilog/tri_oracle_memory_response_gearbox.sv] \
                 [file join $base compact_responses/tri_oracle_compact_response_lane.sv]]
elaborate $top
check_design -unresolved
create_clock -name core_clock -period 1.72414 -waveform {0 0.86207} [get_ports clk]
set core [get_clocks core_clock]
set_clock_uncertainty 0.05 $core
set shared [get_ports {pad_data* pad_metadata*}]
set metadata [get_ports pad_metadata*]
set_input_delay 0.2 -clock $core $shared
set_input_delay 0.2 -clock $core -clock_fall -add_delay $shared
set_input_delay 0.2 -clock $core [get_ports out_ready*]
set_output_delay 0.2 -clock $core [all_outputs]
set_input_transition 0.05 [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_load 0.005 [all_outputs]
set_false_path -from [get_ports rst_n]

syn_generic
syn_map
syn_opt
check_design -unresolved > $out/mapped_check.rpt
report_area > $out/area.rpt
report_timing -max_paths 16 > $out/setup.rpt
report_timing -from $metadata -nworst 4 -max_paths 40 > $out/metadata_setup.rpt
write_hdl > $out/netlist.v
write_sdc > $out/constraints.sdc
puts "TRI_ORACLE_SHARED_EDGE_METADATA_FINISHED early=0"
exit
