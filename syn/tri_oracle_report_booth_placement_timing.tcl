# Run one pre-route timing view from the supplied, verified placement database.
if {[catch {
    set view $::env(TRI_ORACLE_BOOTH_TIMING_VIEW)
    set top $::env(TRI_ORACLE_BOOTH_TIMING_TOP)
    if {$view ni {setup_slow setup_typ hold_fast}} {
        error "Unexpected timing view: $view"
    }
    set cpus [exec nproc]
    set_multi_cpu_usage -local_cpu $cpus
    read_db $::env(TRI_ORACLE_BOOTH_TIMING_DATABASE)
    set_multi_cpu_usage -local_cpu $cpus
    if {[get_db current_design .name] ne $top} {
        error "Unexpected placement top"
    }
    set_analysis_view -setup [list $view] -hold [list $view]
    set selected {}
    foreach clock [get_db clocks] {
        if {[get_db $clock .name] eq "$view/core_clock"} {
            lappend selected $clock
        }
    }
    if {[llength $selected] != 1 || [get_db [lindex $selected 0] .is_propagated]} {
        error "The selected view must have one ideal core_clock"
    }

    set_db timing_analysis_type single
    set_db extract_rc_engine pre_route
    set_db delaycal_ignore_net_load false
    set_db delaycal_enable_high_fanout false
    set_db enable_ui_precision true
    set_db ui_precision_timing 6
    puts "BOOTH_TIMING_SETTINGS before $view [get_db delaycal_enable_high_fanout] [get_db delaycal_ignore_net_load]"
    write_sdc -view $view before.sdc
    if {$view eq "hold_fast"} {
        report_timing -view $view -early -max_paths 20 > timing.rpt
    } else {
        report_timing -view $view -check_type setup -max_paths 20 > timing.rpt
    }
    report_annotated_parasitics -view $view > annotation.rpt
    write_sdc -view $view after.sdc
    if {[get_db delaycal_enable_high_fanout] || [get_db delaycal_ignore_net_load]} {
        error "Timing changed a required delay setting"
    }
    puts "BOOTH_TIMING_SETTINGS after $view [get_db delaycal_enable_high_fanout] [get_db delaycal_ignore_net_load]"
    puts "BOOTH_PLACEMENT_TIMING_PASS $view"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
