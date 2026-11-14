# Map the eight-lane residual adder against the project timing library.
# Default constraints match the current full-chip boundary timing budget.
set root [file dirname [file dirname [file normalize [info script]]]]
set out [file normalize $::env(TRI_ORACLE_RESIDUAL_SYNTHESIS_OUTPUT)]
file mkdir $out
set_db auto_ungroup none
set_db auto_super_thread false
set_db super_thread_servers {localhost}
set_db max_cpus_per_server 20
read_libs [file join $root .cache/physical/library/tcbn28hpcplusbwp12t40p140tt1v25c.lib]
read_hdl -sv [file join $root verilog/tri_oracle_residual_add.sv]
elaborate tri_oracle_residual_add
check_design -unresolved
create_clock -name virtual_core -period 1.72414
set_input_delay 0.2 -clock virtual_core [all_inputs]
set_output_delay 0.2 -clock virtual_core [all_outputs]
set_input_transition 0.05 [all_inputs]
set_load 0.005 [all_outputs]
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
puts TRI_ORACLE_RESIDUAL_ADD_SYNTHESIS_PASS
exit
