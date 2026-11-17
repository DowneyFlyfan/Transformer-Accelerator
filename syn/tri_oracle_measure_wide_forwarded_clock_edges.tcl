set mmmc [open $out/views.tcl w]
set previous [open $input/tx_load_mmmc.tcl r]
foreach line [split [read $previous] \n] {
    if {[regexp {^create_(library_set|rc_corner|timing_condition|delay_corner) } $line]} {puts $mmmc $line}
}
close $previous
set slow_views {}
set fast_views {}
foreach load {5 10} {
    foreach arm {direct delayed} {
        set tag ${load}_$arm
        set sdc [open $out/load_$tag.sdc w]
        set source [open $input/c${load}_d10.sdc r]
        foreach line [split [read $source] \n] {
            if {![string match {set_load *} $line] && $line ne ""} {puts $sdc $line}
        }
        close $source
        puts $sdc "set_load $load \[get_ports clock_*\]"
        puts $sdc {set_load 10 [get_ports {data_* valid_*}]}
        # Keep physical loading unchanged while measuring one timing arc.
        set ignored_pin [dict get {direct A2 delayed A1} $arm]
        puts $sdc "set_disable_timing -from $ignored_pin -to Z \[get_cells {variant_*/sender/join_clock}\]"
        close $sdc
        puts $mmmc [list create_constraint_mode -name load_$tag -sdc_files [list $out/load_$tag.sdc]]
        foreach corner {slow fast} {
            set view ${corner}_$tag
            puts $mmmc [list create_analysis_view -name $view -constraint_mode load_$tag -delay_corner dc_$corner]
            lappend ${corner}_views $view
        }
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
read_netlist $out/netlist.v -top wide_forwarded_clock_shaping
init_design
if {[sizeof_collection [get_ports clock_*]] != 7 ||
    [sizeof_collection [get_ports {data_* valid_*}]] != 161} {error "CLOCK_PAD_VARIANT_PORT_COUNT"}
for {set i 0} {$i < 7} {incr i} {
    set peer [get_pins variant_$i/peer_capture_*/D]
    if {[sizeof_collection $peer] != 23} {error "CLOCK_PAD_VARIANT_RECEIVERS $i"}
    foreach load {5 10} {
        foreach arm {direct delayed} {
            set tag ${load}_$arm
            if {$arm eq "delayed"} {
                foreach edge {rise fall} {
                    report_timing -view slow_$tag -${edge}_to $peer -nworst 1 -max_paths 23 -path_type full_clock > $out/${i}_${tag}_setup_$edge.rpt
                    report_timing -early -view fast_$tag -${edge}_to $peer -nworst 1 -max_paths 23 -path_type full_clock > $out/${i}_${tag}_hold_$edge.rpt
                }
            }
            foreach corner {slow fast} {
                report_min_pulse_width -pins variant_$i/peer_capture_0/CP -path_type full_clock -view ${corner}_$tag > $out/${i}_${tag}_pulse_$corner.rpt
            }
        }
    }
}
puts TRI_ORACLE_CLOCK_PAD_COMPARISON_FINISHED
exit
