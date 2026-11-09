# Repair only data-net counterparts/victims in the bound cold reports. Keep
# every original cell (including the hold repairs) unchanged; any added cell
# must be a bounded, legally placed process-antenna diode.
source syn/tri_oracle_memory_physical_config.tcl
source syn/tri_oracle_memory_route_pair_policy.tcl
source syn/tri_oracle_memory_route_scope.tcl
source syn/tri_oracle_signal_repair_targets.tcl
source syn/tri_oracle_memory_point_dbu.tcl
source syn/tri_oracle_require_clean_placement.tcl
set tag postroute_slot_selected_routes_03
if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ne $tag} {error "Unexpected selected-routing stage"}
set destination $out/${tag}.db
foreach path [list $destination $out/${tag}_router.rpt $out/${tag}_router.tif] {
    if {![catch {file lstat $path ignored}]} {error "Refusing existing selected-routing output: $path"}
}
set reports $out/qualification_postroute_qualify_after_endpoint_slots
foreach {relative checksum} {
    route_drc.rpt 1af67e9905a51c4d5f7818545df5bcb8461df472a3d7bfb29ec6d1c8cacd0efe
    antenna.rpt d20d521519d4094bb378a87e66bbb4988cd822469ce1bcd93f54acdec733e157
    qualification_si_reports/qualification_si.tran.gz 70c6d517f86b9b75c232a22b4c88b8cb95d0fd55f0cb80d291861f0f4ad368ba
    qualification_si_reports/qualification_si.cap.gz ab2d1fe7c1026a0981940bdc4d22cd29b4ffa2d82544245f338ab8801cc091e6
    qualification_si_reports/qualification_si.SI_Glitches.rpt.gz bbf48ee68403392b47045aad6b76da475336331b84433e9bdf42afffb0f046aa
} {
    if {[lindex [exec sha256sum $reports/$relative] 0] ne $checksum} {
        error "Cold selected-routing input changed: $relative"
    }
}
set channel [open $reports/route_drc.rpt r]
try {set pairs [tri_oracle_memory_route_drc_pairs [read $channel]]} finally {close $channel}
set channel [open $reports/antenna.rpt r]
try {set antenna [tri_oracle_route_antenna_targets [read $channel]]} finally {close $channel}
set slew [tri_oracle_route_slew_targets [exec gzip -dc $reports/qualification_si_reports/qualification_si.tran.gz]]
set capacitance [tri_oracle_route_capacitance_targets [exec gzip -dc $reports/qualification_si_reports/qualification_si.cap.gz]]
set glitch [tri_oracle_route_glitch_targets [exec gzip -dc $reports/qualification_si_reports/qualification_si.SI_Glitches.rpt.gz]]
if {[llength $pairs] != 39 || [llength $antenna] != 1 || [llength $slew] != 155 ||
    [llength $capacitance] != 0 || [llength $glitch] != 1} {
    error "Complete measured selected-routing inventory changed"
}
set signal [lsort -unique [concat $slew $capacitance $glitch]]
set candidates [concat $signal $antenna]
foreach pair $pairs {lappend candidates [dict get $pair first] [dict get $pair second]}
set candidates [lsort -unique $candidates]
set_multi_cpu_usage -local_cpu 20
read_db $out/postroute_endpoint_free_slots_02.db
tri_oracle_require_memory_design
source syn/tri_oracle_memory_postroute_settings.tcl
set_db delaycal_enable_si true
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
set classifications [dict create]
set net_objects [dict create]
set channel [open $out/${tag}_native_classification.tsv w]
try {
    puts $channel "net\tis_clock\tis_power\tis_ground"
    foreach name $candidates {
        if {[regexp {[*?]} $name]} {error "Ambiguous native candidate pattern: $name"}
        set net [get_db nets $name]
        if {[llength $net] != 1 || [get_db $net .name] ne $name} {
            error "Missing or ambiguous exact candidate net: $name"
        }
        set flags [dict create]
        foreach attribute {is_clock is_power is_ground} {
            set value [get_db $net .$attribute]
            if {![string is boolean -strict $value]} {error "Unknown native net classification: $name"}
            dict set flags $attribute $value
        }
        dict set classifications $name $flags
        dict set net_objects $name $net
        puts $channel "$name\t[dict get $flags is_clock]\t[dict get $flags is_power]\t[dict get $flags is_ground]"
    }
} finally {close $channel}
set geometry [tri_oracle_memory_route_data_targets $pairs $classifications]
foreach name [concat $signal $antenna] {
    set flags [dict get $classifications $name]
    tri_oracle_route_require_data_net $name [dict get $flags is_clock] \
        [dict get $flags is_power] [dict get $flags is_ground]
}
set names [lsort -unique [concat $geometry $signal $antenna]]
if {[llength $names] == 0 || [llength $names] > 600} {error "Unbounded selected data-net inventory"}
set delays [get_db insts *TRI_MEMORY_ENDPOINT_HOLD_*]
if {[llength $delays] != 6568} {error "Exact repaired endpoint inventory changed"}
foreach inst $delays {
    if {[get_db $inst .base_cell.name] ne {DEL100D1BWP12T40P140} ||
        ![get_db $inst .dont_touch]} {error "Endpoint delay identity/protection changed"}
}
proc tri_oracle_memory_route_native_row {inst} {
    return [list [get_db $inst .base_cell.name] \
        [tri_oracle_memory_point_dbu [get_db $inst .location]] \
        [get_db $inst .orient] [get_db $inst .place_status] \
        [get_db $inst .place_status_cts] [get_db $inst .place_status_effective] \
        [get_db $inst .dont_touch]]
}
set original [dict create]
foreach inst [get_db insts] {
    set row [tri_oracle_memory_route_native_row $inst]
    tri_oracle_memory_route_valid_row $row
    dict set original [get_db $inst .name] $row
}
if {[dict size $original] != 906419} {error "Exact producer cell inventory changed"}
set diode ANTENNABWP12T40P140
if {[llength [get_db base_cells $diode]] != 1} {error "Characterized antenna diode is absent"}
check_place > $out/${tag}_placement_before.rpt
tri_oracle_require_clean_placement $out/${tag}_placement_before.rpt
set channel [open $out/${tag}_targets.tsv w]
try {
    puts $channel "net\tgeometry\tantenna\tsignal_integrity"
    foreach name $names {
        puts $channel "$name\t[expr {$name in $geometry}]\t[expr {$name in $antenna}]\t[expr {$name in $signal}]"
    }
} finally {close $channel}
set_db route_detail_fix_antenna true
set_db route_antenna_diode_insertion true
set_db route_antenna_cell_name $diode
reset_db route_detail_end_iteration
set_db route_detail_search_and_repair true
set saved_timing [get_db route_with_timing_driven]
set saved_si [get_db route_with_si_driven]
set saved_selected [get_db route_selected_net_only]
set saved_check_type [get_db timing_analysis_check_type]
set_db route_with_timing_driven true
set_db route_with_si_driven true
foreach name $signal {
    set_route_attributes -nets $name -si_post_route_fix true -preferred_extra_space_tracks 2
}
# Update the actual original setup views before native opaque timing export.
# Neither this export nor selected-net repair changes a timing constraint.
set_db timing_analysis_check_type setup
report_timing -view setup_slow > $out/${tag}_setup_slow_before.rpt
report_timing -view setup_typ > $out/${tag}_setup_typ_before.rpt
set timing [tri_oracle_export_router_timing $out/${tag}_router.tif]
set router_report $out/${tag}_router.rpt
deselect_obj -all
foreach name $names {select_obj [dict get $net_objects $name]}
set_db route_selected_net_only true
puts "TRI_ORACLE_MEMORY_SELECTED_ROUTE_TARGETS [llength $names] CONFLICT_PAIRS [llength $pairs]"
try {
    redirect $router_report {
        puts "TRI_ORACLE_MEMORY_SELECTED_ROUTE_MODE [get_db route_with_timing_driven] [get_db route_with_si_driven] [get_db route_selected_net_only]"
        route_detail -selected
    } -tee
} finally {
    set_db route_selected_net_only $saved_selected
    set_db route_with_timing_driven $saved_timing
    set_db route_with_si_driven $saved_si
    set_db timing_analysis_check_type $saved_check_type
    deselect_obj -all
    tri_oracle_reset_router_timing
}
set consumed [tri_oracle_require_router_timing_trace $router_report $timing]
set channel [open $router_report r]
try {set evidence [tri_oracle_memory_selected_route_evidence [read $channel]]} finally {close $channel}
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
set preserved 0
set added {}
foreach inst [get_db insts] {
    set name [get_db $inst .name]
    set row [tri_oracle_memory_route_native_row $inst]
    if {[dict exists $original $name]} {
        tri_oracle_memory_route_original_row $name [dict get $original $name] $row
        incr preserved
    } else {
        tri_oracle_memory_route_added_row $name $row
        lappend added [list $name $row]
    }
}
tri_oracle_memory_route_scope_counts $preserved [dict size $original] [llength $added]
unset original
if {[llength [get_db insts *TRI_MEMORY_ENDPOINT_HOLD_*]] != 6568} {error "Routing changed repaired delay inventory"}
set channel [open $out/${tag}_preservation.rpt w]
try {
    puts $channel "original_model_location_orientation_status_and_protection_preserved: $preserved"
    puts $channel "protected_endpoint_delays: 6568"
    puts $channel "added_antenna_diodes: [llength $added]"
    puts $channel "added_cell_inventory: $added"
    puts $channel "exact_native_timing_consumption: $consumed"
    puts $channel "router_diagnostic_evidence: $evidence"
} finally {close $channel}
check_place > $out/${tag}_placement_after.rpt
tri_oracle_require_clean_placement $out/${tag}_placement_after.rpt
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
write_db -rc_extract $destination
puts "TRI_ORACLE_MEMORY_SELECTED_ROUTE_CHECKPOINT_WRITTEN"
report_timing -view setup_slow > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
check_drc -out_file $out/${tag}_drc_after.rpt
check_antenna -out_file $out/${tag}_antenna_after.rpt
check_connectivity -type all -out_file $out/${tag}_connectivity.rpt
time_design -post_route -drv_report -expanded_views \
    -report_dir $out/${tag}_after -report_prefix $tag
puts "TRI_ORACLE_MEMORY_SELECTED_ROUTE_COMMANDS_FINISHED"
exit
