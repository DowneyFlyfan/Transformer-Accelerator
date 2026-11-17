set rtl $::env(TRI_ORACLE_PHASE_ROOT)/verilog
set top tri_oracle_phase_chip_clock
set_db max_cpus [exec nproc]
set_db auto_super_thread false
read_libs $::env(TRI_ORACLE_PHASE_ROOT)/.cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib
read_hdl -sv [list $rtl/${top}.sv $rtl/tri_oracle_weight_phase_clock.sv]
elaborate $top
ungroup -all -flatten
create_clock -name memory_clock -period 0.862 -waveform {0.000 0.431} [get_ports memory_clk]
create_generated_clock -name core_clock -source [get_ports memory_clk] -edges {2 4 6} [get_ports core_clk]
set_clock_uncertainty 0.030 [get_clocks {memory_clock core_clock}]
set_false_path -from [get_ports rst_n]
syn_generic
syn_map
syn_opt
write_hdl > mapped.v
write_sdc > timing.sdc
check_design -unresolved > unresolved.rpt
report_area > area.rpt
report_timing -max_paths 10 > setup.rpt
puts PHASE_CHIP_CLOCK_MAPPED
exit 0
