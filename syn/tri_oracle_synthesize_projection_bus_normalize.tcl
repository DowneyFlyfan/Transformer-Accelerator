# Map the projection bus controller around the verified residual normalizer.
if {[catch {
    set root [file dirname [file dirname [file normalize [info script]]]]
    set out [file normalize $::env(TRI_ORACLE_PROJECTION_BUS_OUTPUT)]
    set normalizer [file normalize $::env(TRI_ORACLE_IMPORTED_NORMALIZER_NETLIST)]
    file mkdir $out
    set top tri_oracle_projection_bus_normalize
    set_db auto_ungroup none
    set_db auto_super_thread false
    set_db super_thread_servers {localhost}
    set_db max_cpus_per_server 20
    read_libs [file join $root .cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib]
    read_hdl -netlist $normalizer
    foreach name {projection_strip_reader projection_normalize projection_packet_dma projection_bus_normalize} {
        read_hdl -sv [file join $root verilog/tri_oracle_${name}.sv]
    }
    elaborate $top
    check_design -unresolved
    set imported [get_db hinsts normalizer/normalizer]
    if {[llength $imported] != 1 || [get_db $imported .name] ne "normalizer/normalizer"} {
        error "Expected one mapped residual bank normalizer"
    }
    set_db $imported .preserve true
    puts "PROJECTION_BUS_IMPORTED_NORMALIZER [get_db $imported .name]"
    create_clock -name core_clock -period 1.72414 [get_ports clk]
    set_clock_uncertainty 0.05 [get_clocks core_clock]
    set inputs [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
    set_input_delay 0.2 -clock core_clock $inputs
    set_input_transition 0.05 $inputs
    set_output_delay 0.2 -clock core_clock [all_outputs]
    set_load 0.005 [all_outputs]
    set_false_path -from [get_ports rst_n]
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
    puts "PROJECTION_BUS_NORMALIZER_MAPPED"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
