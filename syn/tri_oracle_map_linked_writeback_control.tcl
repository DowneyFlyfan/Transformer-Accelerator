set root $::env(TRI_ORACLE_ROOT)
set_db max_cpus_per_server [exec nproc]
read_libs [file join $root .cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib]
read_hdl -sv [file join $root verilog/tri_oracle_linked_writeback_control.sv]
elaborate tri_oracle_linked_writeback_control
check_design -unresolved
create_clock -name core -period 1.72414 [get_ports clk]
set_clock_uncertainty 0.05 [get_clocks core]
set data_inputs [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_input_delay 0.2 -clock core $data_inputs
set_output_delay 0.2 -clock core [all_outputs]
set_false_path -from [get_ports rst_n]
set_input_transition 0.05 $data_inputs
set_load 0.005 [all_outputs]
syn_generic
syn_map
syn_opt
report_area > area.rpt
report_timing -max_paths 8 > timing.rpt
write_hdl > netlist.v
puts LINKED_WRITEBACK_CONTROL_MAPPED
exit
