# Map the grouped attention projection stream against the project timing library.
# Default constraints match the current full-chip boundary timing budget.
# Map against the slow project corner to reserve time for physical integration.
set root [file dirname [file dirname [file normalize [info script]]]]
set out [file normalize $::env(TRI_ORACLE_SHARED_PROJECTION_BANK_OUTPUT)]
file mkdir $out
set_db auto_ungroup none
set_db auto_super_thread false
set_db super_thread_servers {localhost}
set_db max_cpus_per_server 20
set logic_lib [file join $root .cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib]
set sram_root [file join $root .cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a]
set sram_lib [file join $sram_root NLDM/ts5n28hpcpsvta512x64m4f_130a_ssg0p9v125c.lib]
read_libs [list $logic_lib $sram_lib]
read_hdl -sv [file join $root verilog/tri_oracle_attention_projection_scale.sv]
read_hdl -sv [file join $root verilog/tri_oracle_attention_projection_stream.sv]
read_hdl -sv [file join $root verilog/tri_oracle_projection_activation_store.sv]
read_hdl -sv [file join $root verilog/tri_oracle_projection_shared_bank.sv]
elaborate tri_oracle_projection_shared_bank
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
puts TRI_ORACLE_SHARED_PROJECTION_BANK_SYNTHESIS_PASS
exit
