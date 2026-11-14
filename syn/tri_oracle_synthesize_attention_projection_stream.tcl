# Map the grouped attention projection stream against the project timing library.
# Default constraints match the current full-chip boundary timing budget.
# Map against the slow project corner to reserve time for physical integration.
set root [file dirname [file dirname [file normalize [info script]]]]
set out [file normalize $::env(TRI_ORACLE_PROJECTION_STREAM_OUTPUT)]
file mkdir $out
set_db auto_ungroup none
set_db auto_super_thread false
set_db super_thread_servers {localhost}
set_db max_cpus_per_server 20
read_libs [file join $root .cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib]
read_hdl -sv [file join $root verilog/tri_oracle_attention_projection_scale.sv]
read_hdl -sv [file join $root verilog/tri_oracle_attention_projection_stream.sv]
elaborate tri_oracle_attention_projection_stream
check_design -unresolved
create_clock -name core_clock -period 1.72414 [get_ports clk]
set data_ports [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_input_delay 0.2 -clock core_clock $data_ports
set_output_delay 0.2 -clock core_clock [all_outputs]
set_input_transition 0.05 $data_ports
set_load 0.005 [all_outputs]
set_false_path -from [get_ports rst_n]
set_db syn_generic_effort medium
set_db syn_map_effort medium
set_db syn_opt_effort medium
syn_generic
syn_map
syn_opt
report_area > $out/area.rpt
report_timing -max_paths 16 > $out/timing.rpt
write_hdl > $out/netlist.v
write_sdc > $out/constraints.sdc
puts TRI_ORACLE_PROJECTION_STREAM_SYNTHESIS_PASS
exit
