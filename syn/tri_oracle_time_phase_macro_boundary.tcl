if {[catch {
    set root $::env(TRI_ORACLE_PHASE_ROOT)
    set standard $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140
    set master ts5n28hpcpsvta32x128m2fw_130a
    set macros $root/.cache/physical/sram/core_weights_masks_01/$master
    set tech $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef

    set definitions [open views.tcl w]
    puts $definitions [list create_constraint_mode -name related_clocks -sdc_files \
        [list $root/syn/tri_oracle_phase_macro_boundary.sdc]]
    foreach {view corner rules temp} {
        slow ssg0p9v125c qrc_rcworst 125
        typical tt1v25c qrc_typical 25
        fast ffg1p05vm40c qrc_rcbest -40
    } {
        puts $definitions [list create_library_set -name libs_$view -timing \
            [list ${standard}${corner}.lib $macros/NLDM/${master}_${corner}.lib]]
        puts $definitions [list create_rc_corner -name rc_$view -qrc_tech $root/.cache/physical/rc/$rules -temperature $temp]
        puts $definitions [list create_timing_condition -name tc_$view -library_sets [list libs_$view]]
        puts $definitions [list create_delay_corner -name dc_$view -timing_condition tc_$view -rc_corner rc_$view]
        puts $definitions [list create_analysis_view -name $view -constraint_mode related_clocks -delay_corner dc_$view]
    }
    puts $definitions {set_analysis_view -setup {slow typical} -hold {fast}}
    close $definitions
    # Keep the timing workers within the host's memory allowance while the
    # long chip replays are running in the same container.
    set_multi_cpu_usage -local_cpu 4
    set_db design_process_node 28
    set_db init_power_nets {VDD}
    set_db init_ground_nets {VSS}
    read_mmmc views.tcl
    read_physical -lefs [list $tech $standard.lef $macros/LEF/$master.lef]
    read_netlist macro_boundary.v -top tri_oracle_phase_macro_boundary
    init_design

    set banks [get_cells weight_bank_*]
    set count [sizeof_collection $banks]
    if {$count != 320} {error "Unexpected SRAM bank count: $count"}
    puts "PHASE_MACRO_INVENTORY banks=$count"
    foreach view {slow typical} {
        report_timing -view $view -max_paths 12 > ${view}_setup.rpt
        report_timing -view $view -to [get_pins weight_bank_*/CEB] -max_paths 6 > ${view}_chip_enable.rpt
        report_timing -view $view -to [get_pins weight_bank_*/WEB] -max_paths 6 > ${view}_write_enable.rpt
        report_timing -view $view -to [get_pins weight_bank_*/BWEB*] -max_paths 6 > ${view}_write_mask.rpt
        report_timing -view $view -to [get_pins weight_bank_*/D*] -max_paths 6 > ${view}_data.rpt
        report_timing -view $view -to [get_pins weight_bank_*/A*] -max_paths 6 > ${view}_address.rpt
    }
    report_timing -early -view fast -max_paths 12 > fast_hold.rpt
    foreach view {slow typical} {
        report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} \
            -view $view > ${view}_electrical.rpt
    }
    puts PHASE_MACRO_TIMING_COMPLETE
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
