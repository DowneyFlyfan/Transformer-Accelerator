# Initial technology-mapped synthesis. Interface budgets are local assumptions.
set_db max_cpus 18
set top $::env(TRI_ORACLE_TOP)
set output .cache/physical/synthesis/$top
file mkdir $output
read_libs $::env(TRI_ORACLE_LIBS)
if {$top in {tri_oracle_memory_compute tri_oracle_compute_cluster tri_oracle_compute_fabric}} {
    read_hdl -sv verilog/tri_oracle_word_bank.sv
    if {[info exists ::env(TRI_ORACLE_REUSE_PE)] && $::env(TRI_ORACLE_REUSE_PE) eq "1"} {
        read_hdl -sv .cache/physical/synthesis/tri_oracle_pe_array/netlist.v
    } else {
        read_hdl -sv verilog/tri_oracle_pe_array.sv
    }
}
if {$top in {tri_oracle_compute_cluster tri_oracle_compute_fabric}} {
    read_hdl -sv verilog/tri_oracle_memory_compute.sv
}
if {$top eq "tri_oracle_compute_fabric"} {read_hdl -sv verilog/tri_oracle_compute_cluster.sv}
read_hdl -sv verilog/${top}.sv
elaborate $top
check_design -unresolved
create_clock -name core_clock -period 1.724137931 [get_ports clk]
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
if {[info exists ::env(TRI_ORACLE_SAVE_SYNTH_CHECKPOINTS)] && $::env(TRI_ORACLE_SAVE_SYNTH_CHECKPOINTS) eq "1"} {
    write_db ${output}/generic.db
    puts "TRI_ORACLE_GENERIC_CHECKPOINT_WRITTEN $top"
}
syn_map
if {[info exists ::env(TRI_ORACLE_SAVE_SYNTH_CHECKPOINTS)] && $::env(TRI_ORACLE_SAVE_SYNTH_CHECKPOINTS) eq "1"} {
    write_db ${output}/mapped.db
    puts "TRI_ORACLE_MAPPED_CHECKPOINT_WRITTEN $top"
}
syn_opt
report_area > ${output}/area.rpt
report_timing > ${output}/timing.rpt
report_power > ${output}/power_default_activity.rpt
write_hdl > ${output}/netlist.v
write_sdc > ${output}/constraints.sdc
puts "TRI_ORACLE_SYNTHESIS_PASS $top"
exit
