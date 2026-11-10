# Map the already simulated four-macro context block at the slow 28 nm corner.
set root [file normalize $::env(TRI_ORACLE_ROOT)]
set output [file normalize $::env(TRI_ORACLE_CONTEXT_OUT)]
set top tri_oracle_attention_context428
set macro ts5n28hpcpsvta512x64m4f_130a
set macro_dir $root/.cache/physical/sram/activation_cache_banks_01/$macro
set_db max_cpus 20
read_libs [list \
    $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib \
    $macro_dir/NLDM/${macro}_ssg0p9v125c.lib]
read_hdl -sv $root/verilog/${top}.sv
elaborate $top
check_design -unresolved > $output/elaboration_check.rpt
create_clock -name core_clock -period 1.724137931 [get_ports clk]
set_clock_uncertainty 0.05 [get_clocks core_clock]
set inputs [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_input_delay 0.2 -clock core_clock $inputs
set_output_delay 0.2 -clock core_clock [all_outputs]
set_input_transition 0.05 $inputs
set_load 0.005 [all_outputs]
set_false_path -from [get_ports rst_n]
syn_generic
syn_map
syn_opt
check_design -unresolved > $output/mapped_check.rpt
check_timing_intent -verbose > $output/timing_intent.rpt
report_area > $output/area.rpt
report_timing > $output/timing.rpt
write_hdl > $output/netlist.v
write_sdc > $output/constraints.sdc
puts "CTX428_GENUS_DONE"
exit
