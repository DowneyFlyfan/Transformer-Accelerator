# Timing-only harness with real pad cells and lumped external loads.
set root [file dirname [file dirname [file normalize [info script]]]]
set out [file normalize $::env(TRI_ORACLE_LOADED_PADS_OUTPUT)]
set library $root/.cache/physical/library
set cases {{5 5} {5 10} {10 5} {10 10} {5 25} {25 5}}
set mmmc [open $out/tx_load_mmmc.tcl w]
foreach {name lib rc t} {
    slow tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib qrc_rcworst 125
    fast tcbn28hpcplusbwp12t40p140ffg1p05vm40c.lib qrc_rcbest -40
} {
    puts $mmmc [list create_library_set -name ls_$name -timing [list $library/$lib $out/pad_$name.lib]]
    puts $mmmc [list create_rc_corner -name rc_$name -qrc_tech $root/.cache/physical/rc/$rc -temperature $t]
    puts $mmmc [list create_timing_condition -name tc_$name -library_sets [list ls_$name]]
    puts $mmmc [list create_delay_corner -name dc_$name -timing_condition tc_$name -rc_corner rc_$name]
}
set setup_views {}
set hold_views {}
foreach pair $cases {
    lassign $pair clock_load data_load
    set id c${clock_load}_d${data_load}
    set sdc [open $out/$id.sdc w]
    puts $sdc {create_clock -name core_clock -period 1.72414 -waveform {0.0 0.86207} [get_ports clk]}
    puts $sdc {set_propagated_clock [get_clocks core_clock]}
    puts $sdc {set_clock_uncertainty 0.05 [get_clocks core_clock]}
    puts $sdc {set_input_transition 0.05 [get_ports clk]}
    puts $sdc {set_false_path -from [get_ports rst_n]}
    puts $sdc "set_load $clock_load \[get_ports tx_clock\]"
    puts $sdc "set_load $data_load \[get_ports {tx_data* tx_valid}\]"
    close $sdc
    puts $mmmc [list create_constraint_mode -name mode_$id -sdc_files [list $out/$id.sdc]]
    foreach {check corner} {setup slow hold fast} {
        puts $mmmc [list create_analysis_view -name ${check}_$id -constraint_mode mode_$id -delay_corner dc_$corner]
    }
    lappend setup_views setup_$id
    lappend hold_views hold_$id
}
puts $mmmc [list set_analysis_view -setup $setup_views -hold $hold_views]
close $mmmc

set_multi_cpu_usage -local_cpu 4
set_db design_process_node 28
set_db init_power_nets {VDD VDDPST}
set_db init_ground_nets {VSS VSSPST}
read_mmmc $out/tx_load_mmmc.tcl
read_physical -lefs [list \
    $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
    $library/tcbn28hpcplusbwp12t40p140.lef $out/pads.lef]
read_netlist $out/netlist.v -top tri_oracle_loaded_request_pads
init_design
set peer [get_pins {peer_capture_*/D}]
if {[sizeof_collection $peer] != 9} {error "PEER_CAPTURE_COUNT_MISMATCH"}
foreach pair $cases {
    lassign $pair clock_load data_load
    set id c${clock_load}_d${data_load}
    foreach edge {rise fall} {
        report_timing -view setup_$id -${edge}_to $peer -max_paths 9 -path_type full_clock > $out/${id}_setup_$edge.rpt
        report_timing -early -view hold_$id -${edge}_to $peer -max_paths 9 -path_type full_clock > $out/${id}_hold_$edge.rpt
    }
}
puts TRI_ORACLE_LOADED_FORWARD_PADS_FINISHED
exit
