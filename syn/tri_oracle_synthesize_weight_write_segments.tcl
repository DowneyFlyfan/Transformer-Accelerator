if {[catch {
    set_db max_cpus [exec nproc]
    set_db auto_super_thread false
    set_db fail_on_error_mesg true
    read_libs [list $::env(TRI_ORACLE_LIBRARY)]
    read_hdl -sv [list $::env(TRI_ORACLE_SEGMENTS)]
    elaborate tri_oracle_weight_write_segments
    create_clock -name core_clock -period 1.72414 [get_ports clk]
    set_clock_uncertainty 0.05 [get_clocks core_clock]
    set inputs [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
    set_input_delay 0.2 -clock core_clock $inputs
    set_input_transition 0.05 $inputs
    set_output_delay 0.2 -clock core_clock [all_outputs]
    set_load 0.005 [all_outputs]
    set_false_path -from [get_ports rst_n]
    syn_generic
    syn_map
    check_design -unresolved > unresolved.rpt
    report_area > area.rpt
    report_timing -max_paths 5 > timing.rpt
    write_hdl > mapped.v
    puts WEIGHT_SEGMENTS_MAPPED
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
