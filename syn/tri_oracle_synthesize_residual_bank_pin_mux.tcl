# Map one four-port selector before linking it to the existing compiled bank.
if {[catch {
    set root [file dirname [file dirname [file normalize [info script]]]]
    set out [file normalize $::env(TRI_ORACLE_RESIDUAL_BANK_MUX_OUTPUT)]
    file mkdir $out
    set top tri_oracle_residual_bank_pin_mux
    set_db auto_ungroup none
    set_db auto_super_thread false
    set_db super_thread_servers {localhost}
    set_db max_cpus_per_server 20
    read_libs [file join $root .cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib]
    read_hdl -sv [file join $root verilog/tri_oracle_residual_bank_pin_mux.sv]
    elaborate $top
    check_design -unresolved
    create_clock -name virtual_core -period 1.72414
    set_input_delay 0.2 -clock virtual_core [all_inputs]
    set_output_delay 0.2 -clock virtual_core [all_outputs]
    set_input_transition 0.05 [all_inputs]
    set_load 0.005 [all_outputs]
    set_db syn_generic_effort low
    set_db syn_map_effort medium
    set_db syn_opt_effort medium
    syn_generic
    syn_map
    syn_opt
    report_area > [file join $out area.rpt]
    report_timing -max_paths 5 > [file join $out timing.rpt]
    write_hdl > [file join $out netlist.v]
    write_sdc > [file join $out constraints.sdc]
    puts "RESIDUAL_INPUT_BANK_PIN_MUX_MAPPED"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
