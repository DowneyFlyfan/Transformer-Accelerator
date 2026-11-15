# Map compact indexes and full-width responses into the mapped weight transport.
set root [file dirname [file dirname [file normalize [info script]]]]
set out [file normalize $::env(TRI_ORACLE_COMPACT_INDEX_OUTPUT)]
file mkdir $out
set_db auto_ungroup none
set_db auto_super_thread false
read_libs [file join $root .cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib]
read_hdl -sv [file join $root verilog/tri_oracle_memory_response_gearbox.sv]
read_hdl -sv [file join $root verilog/tri_oracle_compact_index_ingress.sv]
elaborate tri_oracle_compact_index_ingress
check_design -unresolved
create_clock -name core_clock -period 1.72414 [get_ports clk]
set_clock_uncertainty 0.05 [get_clocks core_clock]
set data_ports [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_input_delay 0.2 -clock core_clock $data_ports
set_output_delay 0.2 -clock core_clock [all_outputs]
set_input_transition 0.05 $data_ports
set_load 0.005 [all_outputs]
set_false_path -from [get_ports rst_n]
syn_generic
syn_map
syn_opt
check_design -unresolved > $out/mapped_check.rpt
report_area > $out/area.rpt
report_timing -max_paths 8 > $out/timing.rpt
write_hdl > $out/netlist.v
write_sdc > $out/constraints.sdc
puts TRI_ORACLE_COMPACT_INDEX_GENUS_FINISHED
exit
