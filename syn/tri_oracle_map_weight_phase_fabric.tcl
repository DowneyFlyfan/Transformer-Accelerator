# Map the five-cluster controller with the clock relationship at its boundary.
set root $::env(TRI_ORACLE_PHASE_ROOT)
set rtl $root/verilog
set top tri_oracle_weight_phase_fabric
set_db max_cpus [exec nproc]
set_db auto_super_thread false
read_libs $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib
read_hdl -sv [list $rtl/${top}.sv $rtl/tri_oracle_cluster_weight_phase.sv \
    $rtl/tri_oracle_weight_phase_port.sv $rtl/weight_stream_write_arbiter.sv]
elaborate $top
ungroup -all -flatten

# The core clock rises on the first falling edge of the memory clock.
create_clock -name memory_clock -period 0.862 -waveform {0.000 0.431} [get_ports memory_clk]
create_clock -name core_clock -period 1.724 -waveform {0.431 1.293} [get_ports core_clk]
set_clock_uncertainty 0.030 [get_clocks {memory_clock core_clock}]
set core_inputs [get_ports {read_cores* read_address* write_pending* write_allowed* write_core* write_address* write_rows* write_payload*}]
set_input_delay -max 0.20 -clock core_clock $core_inputs
set_input_delay -min 0.10 -clock core_clock $core_inputs
set_input_transition 0.05 $core_inputs
set macro_inputs [get_ports {memory_address* memory_ce_n* memory_we_n* memory_rows* memory_data*}]
set_output_delay -max 0.150 -clock memory_clock $macro_inputs
set_output_delay -min -0.140 -clock memory_clock $macro_inputs
set_load 0.010 $macro_inputs
set_output_delay -max 0.10 -clock core_clock [get_ports {write_retired*}]
set_output_delay -min -0.10 -clock core_clock [get_ports {write_retired*}]
set_false_path -from [get_ports rst_n]

syn_generic
syn_map
syn_opt
write_hdl > mapped.v
write_sdc > timing.sdc
check_design -unresolved > unresolved.rpt
report_area > area.rpt
report_timing -max_paths 20 > setup.rpt
report_timing -to [get_ports {write_retired*}] -max_paths 2 > retirement.rpt
puts TRI_ORACLE_WEIGHT_PHASE_FABRIC_MAPPED
exit 0
