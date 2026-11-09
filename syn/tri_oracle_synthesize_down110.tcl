# Small-block slow-corner mapping only, before full-parent integration.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_down_executor
set output $::env(TRI_ORACLE_DOWN110_OUTPUT)
set_db auto_ungroup none
set_db partition_based_synthesis false
set_db auto_partition false
set_db auto_super_thread false
set_db super_thread_servers {}
set_db max_cpus_per_server 18
read_libs $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib
read_hdl -sv $root/verilog/tri_oracle_down_executor.sv
elaborate $top
check_design -unresolved > $output/elaboration.rpt
create_clock -name core_clock -period 1.72414 [get_ports clk]
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
write_db $output/generic.db
syn_map
write_db $output/mapped.db
syn_opt
write_db $output/optimized.db
check_design -unresolved > $output/mapped_check.rpt
check_timing_intent -verbose > $output/timing_intent.rpt
report_area > $output/area.rpt
report_timing -max_paths 10 > $output/timing.rpt
write_hdl > $output/netlist.v
write_sdc > $output/constraints.sdc
puts TRI_ORACLE_DOWN110_SLOW_MAPPING_FINISHED_REQUIRES_REPORT_REVIEW
exit
