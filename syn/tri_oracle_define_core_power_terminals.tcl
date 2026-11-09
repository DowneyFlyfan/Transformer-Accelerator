# Define real supply terminals on the four already validated top-edge exits.
# Terminal rectangles lie inside existing M9 supply metal; no signal route or
# core placement is edited. The original core44 remains an immutable input.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI_ORACLE_PLACEMENT_PROBE_DIRECTORY)
read_db $root/.cache/physical/pnr/tri_oracle_core_power_access39/power_access_candidate.db
set_multi_cpu_usage -local_cpu 4
if {[get_db current_design .name] ne "tri_oracle_sram_memory_compute" ||
    [llength [get_db insts]] != 94471} {error "CORE_POWER40_WRONG_INPUT"}
proc power40_cells {} {
    set result {}
    foreach instance [get_db insts] {
        lappend result [list [get_db $instance .name] [get_db $instance .base_cell.name] \
            [get_db $instance .location] [get_db $instance .orient] [get_db $instance .place_status]]
    }
    return [lsort $result]
}
proc power40_signal_logic {} {
    set result {}
    foreach net [get_db nets] {
        if {[get_db $net .is_power] || [get_db $net .is_ground]} {continue}
        lappend result [list [get_db $net .name] [lsort [get_db $net .pins.name]] \
            [lsort [get_db $net .driver_ports.name]] [lsort [get_db $net .load_ports.name]]]
    }
    return [lsort $result]
}
set cells_before [power40_cells]
set logic_before [power40_signal_logic]
write_def $out/before.def -routing
foreach {net x1 x2} {VDD 5.99 7.99 VDD 711.85 713.85 VSS 1.99 3.99 VSS 715.85 717.85} {
    create_pg_pin -name $net -net $net -geometry M9 $x1 668.0 $x2 670.0
}
if {[power40_cells] ne $cells_before || [power40_signal_logic] ne $logic_before} {
    error "CORE_POWER40_CHANGED_CELLS_OR_SIGNAL_LOGIC"
}
write_def $out/after.def -routing
write_lef_abstract $out/core.lef -top_layer 10 -stripe_pins \
    -pg_pin_layers {8 9} -port_for_each_stripe_pin -extract_block_obs
check_place > $out/placement.rpt
source $root/syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/placement.rpt
check_drc -limit 100000 -out_file $out/route_drc.rpt
check_connectivity -type all -check_pg_ports -error 100000 -warning 100000 \
    -out_file $out/connectivity.rpt
check_antenna -out_file $out/antenna.rpt
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db delaycal_enable_si true
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
set_db timing_max_transition_use_si_transition true
set_db si_enable_drv_with_delta_slew true
set_db opt_post_route_report_si_transitions true
time_design -post_route -expanded_views -drv_report -report_dir $out/timing -report_prefix power_terminals
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set saved_check [get_db timing_analysis_check_type]
set file [open $out/slack_properties.tsv w]
puts $file "view\tslack_ns\tstartpoint\tendpoint"
foreach view {setup_slow setup_typ hold_fast} {
    set_db timing_analysis_check_type [expr {$view eq "hold_fast" ? "hold" : "setup"}]
    set command [list report_timing -view $view -max_paths 1 -max_slack 100]
    if {$view eq "hold_fast"} {lappend command -early} else {lappend command -check_type setup}
    eval $command > $out/timing_$view.rpt
    set paths [eval $command -collection]
    if {[sizeof_collection $paths] != 1} {error "CORE_POWER40_MISSING_ACTUAL_CORNER_PATH: $view"}
    foreach_in_collection path $paths {
        puts $file "$view\t[get_property $path slack]\t[get_object_name [get_property $path launching_point]]\t[get_object_name [get_property $path capturing_point]]"
    }
}
close $file
set_db timing_analysis_check_type $saved_check
if {[power40_cells] ne $cells_before || [power40_signal_logic] ne $logic_before} {
    error "CORE_POWER40_REPORTING_CHANGED_CELLS_OR_SIGNAL_LOGIC"
}
write_db -rc_extract $out/power_terminal_candidate.db
puts TRI_ORACLE_CORE_POWER_TERMINALS40_CANDIDATE_FINISHED
exit
