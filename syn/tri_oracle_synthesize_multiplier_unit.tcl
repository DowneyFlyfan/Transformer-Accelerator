if {[catch {
    set_db max_cpus_per_server 4
    set_db auto_super_thread false
    set_db fail_on_error_mesg true
    read_libs $::env(TRI_CARRY_LIB)
    read_hdl -sv [list $::env(TRI_BOOTH_UNIT) product.sv]
    elaborate product
    if {[check_design -unresolved -status]} {error "Unresolved multiplier hierarchy"}
    create_clock -name core -period 1.72414 [get_ports clk]
    set_clock_uncertainty 0.05 [get_clocks core]
    set_input_delay 0.2 -clock [get_clocks core] [remove_from_collection [all_inputs] [get_ports clk]]
    set_output_delay 0.2 -clock [get_clocks core] [all_outputs]
    set_input_transition 0.05 [remove_from_collection [all_inputs] [get_ports clk]]
    set_load 0.005 [all_outputs]
    set_db syn_generic_effort medium
    set_db syn_map_effort medium
    set_db syn_opt_effort medium
    syn_generic
    syn_map
    syn_opt
    report_area > area.rpt
    report_timing -max_paths 5 > setup.rpt
    write_hdl > netlist.v
    puts MULTIPLIER_UNIT_MAPPED
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit
