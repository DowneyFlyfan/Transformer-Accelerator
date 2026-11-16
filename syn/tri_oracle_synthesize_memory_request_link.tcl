# Map either endpoint with the project's slow timing corner and interface budgets.
set root [file dirname [file dirname [file normalize [info script]]]]
set top $::env(TRI_ORACLE_REQUEST_ENDPOINT)
if {$top ni {tri_oracle_memory_request_tx tri_oracle_memory_request_rx}} {
    error "Unknown memory request endpoint $top"
}
set out [file normalize $::env(TRI_ORACLE_REQUEST_OUTPUT)]
file mkdir $out
set_db auto_ungroup none
set_db auto_super_thread false
read_libs [file join $root .cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib]
read_hdl -sv [file join $root verilog/tri_oracle_memory_request_link.sv]
elaborate $top
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
puts "TRI_ORACLE_MEMORY_REQUEST_LINK_GENUS_FINISHED $top"
exit
