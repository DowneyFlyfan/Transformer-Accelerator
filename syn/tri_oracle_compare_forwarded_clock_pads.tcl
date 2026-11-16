# Apply the same clock and data loads to each duplicate timing harness.
set root [file dirname [file dirname [file normalize [info script]]]]
set input $root/.cache/physical/whole_chip_xcelium_speed/loaded_forwarded_pads
set out [file normalize $::env(TRI_ORACLE_CLOCK_PAD_COMPARISON)]
set mmmc [open $out/views.tcl w]
set previous [open $input/tx_load_mmmc.tcl r]
foreach line [split [read $previous] \n] {
    if {[regexp {^create_(library_set|rc_corner|timing_condition|delay_corner) } $line]} {puts $mmmc $line}
}
close $previous
set slow_views {}
set fast_views {}
foreach load {5 10} {
    set sdc [open $out/load_$load.sdc w]
    set source [open $input/c${load}_d10.sdc r]
    foreach line [split [read $source] \n] {
        if {![string match {set_load *} $line] && $line ne ""} {puts $sdc $line}
    }
    close $source
    puts $sdc "set_load $load \[get_ports clock_*\]"
    puts $sdc {set_load 10 [get_ports {data_* valid_*}]}
    close $sdc
    puts $mmmc [list create_constraint_mode -name load_$load -sdc_files [list $out/load_$load.sdc]]
    foreach corner {slow fast} {
        set view ${corner}_$load
        puts $mmmc [list create_analysis_view -name $view -constraint_mode load_$load -delay_corner dc_$corner]
        lappend ${corner}_views $view
    }
}
puts $mmmc [list set_analysis_view -setup [concat $slow_views $fast_views] -hold $fast_views]
close $mmmc

set_multi_cpu_usage -local_cpu 4
set_db design_process_node 28
set_db init_power_nets {VDD VDDPST}
set_db init_ground_nets {VSS VSSPST}
read_mmmc $out/views.tcl
read_physical -lefs [list \
    $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
    $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef $input/pads.lef]
read_netlist $out/netlist.v -top compare_forwarded_clock_pads
init_design
if {[sizeof_collection [get_ports clock_*]] != 8 ||
    [sizeof_collection [get_ports {data_* valid_*}]] != 72} {error "CLOCK_PAD_VARIANT_PORT_COUNT"}
for {set i 0} {$i < 8} {incr i} {
    set peer [get_pins variant_$i/peer_capture_*/D]
    if {[sizeof_collection $peer] != 9} {error "CLOCK_PAD_VARIANT_RECEIVERS $i"}
    foreach load {5 10} {
        foreach edge {rise fall} {
            report_timing -view slow_$load -${edge}_to $peer -max_paths 9 -path_type full_clock > $out/${i}_${load}_setup_$edge.rpt
            report_timing -early -view fast_$load -${edge}_to $peer -max_paths 9 -path_type full_clock > $out/${i}_${load}_hold_$edge.rpt
        }
        foreach corner {slow fast} {
            report_min_pulse_width -pins variant_$i/peer_capture_0/CP -path_type full_clock -view ${corner}_$load > $out/${i}_${load}_pulse_$corner.rpt
        }
    }
}
puts TRI_ORACLE_CLOCK_PAD_COMPARISON_FINISHED
exit
