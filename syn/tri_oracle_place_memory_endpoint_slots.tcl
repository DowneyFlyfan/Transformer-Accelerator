# Consume the exact inserted/unplaced producer. Only new delay cells receive
# coordinates; every original cell's location, orientation and status is held.
source syn/tri_oracle_memory_physical_config.tcl
source syn/tri_oracle_memory_endpoint_policy.tcl
source syn/tri_oracle_require_clean_placement.tcl
source syn/tri_oracle_memory_point_dbu.tcl
set tag postroute_endpoint_free_slots_02
if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ne $tag} {error "Unexpected free-slot stage"}
set destination $out/${tag}.db
if {![catch {file lstat $destination ignored}]} {error "Refusing existing free-slot output"}
set plan $out/endpoint_free_slot_placement.tsv
set insertions $out/postroute_measured_endpoint_unplaced_insertions.tsv
foreach {path expected} [list $plan \
    678b047524f490340238dd68cea5e43416afa3fb2ed253cd5880b3ad8a38caea $insertions \
    eab94b4df11b9aedf4710ffec747dc353792d51bf095cc7bae506ea88835a6e9] {
    if {[lindex [exec sha256sum $path] 0] ne $expected} {error "Qualified placement input changed: $path"}
}
set channel [open $insertions r]
try {set lines [split [string trimright [read $channel] \n] \n]} finally {close $channel}
if {[lindex $lines 0] ne "endpoint\tinstance\tinput_net\toutput_net"} {error "Missing insertion header"}
set expected [dict create]
foreach line [lrange $lines 1 end] {
    set fields [split $line \t]
    if {[llength $fields] != 4} {error "Incomplete insertion row"}
    lassign $fields endpoint name input_net output_net
    if {[dict exists $expected $name]} {error "Duplicate inserted delay instance"}
    dict set expected $name $endpoint
}
if {[dict size $expected] != 6568} {error "Incomplete exact insertion inventory"}
set channel [open $plan r]
try {set lines [split [string trimright [read $channel] \n] \n]} finally {close $channel}
if {[lindex $lines 0] ne "endpoint\tinstance\tx_dbu\ty_dbu\torient\ttarget_x_dbu\ttarget_y_dbu"} {
    error "Missing free-slot placement header"
}
set slots [dict create]
foreach line [lrange $lines 1 end] {
    set fields [split $line \t]
    if {[llength $fields] != 7} {error "Incomplete free-slot placement row"}
    lassign $fields endpoint name x y orient target_x target_y
    if {![dict exists $expected $name] || [dict get $expected $name] ne $endpoint ||
        [dict exists $slots $name] || $orient ni {r0 mx}} {error "Unexpected free-slot instance/endpoint/orientation"}
    foreach coordinate [list $x $y $target_x $target_y] {
        if {![string is integer -strict $coordinate] || $coordinate < 0 || $coordinate > 10000000} {
            error "Unsupported integer placement coordinate"
        }
    }
    if {($x-20250)%280 != 0 || ($y-20000)%2400 != 0} {error "Off-grid free-slot coordinate"}
    dict set slots $name [list $endpoint $x $y $orient $target_x $target_y]
}
if {[dict size $slots] != [dict size $expected]} {error "Free-slot coverage differs from inserted delays"}
set_multi_cpu_usage -local_cpu 20
read_db $out/postroute_measured_endpoint_unplaced.db
tri_oracle_require_memory_design
source syn/tri_oracle_memory_postroute_settings.tcl
set_db delaycal_enable_si true
set_db si_delay_enable_report true
set original [dict create]
set new_count 0
foreach inst [get_db insts] {
    set name [get_db $inst .name]
    if {[dict exists $slots $name]} {
        incr new_count
        if {[get_db $inst .base_cell.name] ne {DEL100D1BWP12T40P140} ||
            [get_db $inst .place_status] ne {unplaced}} {error "Expected exact unplaced delay: $name"}
    } else {
        dict set original $name [list [get_db $inst .location] [get_db $inst .orient] \
            [get_db $inst .place_status] [get_db $inst .place_status_cts] \
            [get_db $inst .place_status_effective]]
    }
}
if {$new_count != 6568 || [dict size $original] != 899851} {error "Unplaced producer instance inventory changed"}
# Check every target's original measured coordinate before the first placement.
foreach name [dict keys $slots] {
    lassign [dict get $slots $name] endpoint x y orient target_x target_y
    set parent [string range $endpoint 0 [expr {[string last / $endpoint]-1}]]
    set inst [get_db insts $parent]
    if {[llength $inst] != 1 || [get_db $inst .name] ne $parent} {error "Missing exact target cell: $parent"}
    lassign [tri_oracle_memory_point_dbu [get_db $inst .location]] px py
    if {$px != $target_x || $py != $target_y} {
        error "Target cell location differs from original geometry: $parent"
    }
}
puts "TRI_ORACLE_MEMORY_FREE_SLOT_INPUTS_ADMITTED $new_count ORIGINALS [dict size $original]"
foreach name [dict keys $slots] {
    lassign [dict get $slots $name] endpoint x y orient target_x target_y
    place_inst $name [list [expr {$x/2000.0}] [expr {$y/2000.0}]] $orient -placed
    set inst [get_db insts $name]
    lassign [tri_oracle_memory_point_dbu [get_db $inst .location]] px py
    if {$px != $x || $py != $y ||
        [get_db $inst .orient] ne $orient || [get_db $inst .place_status] ne {placed}} {
        error "Native placement snapped away from its verified slot: $name"
    }
    set_db $inst .dont_touch true
}

proc tri_oracle_memory_require_original_placements {original} {
    set seen 0
    foreach inst [get_db insts] {
        set name [get_db $inst .name]
        if {![dict exists $original $name]} {continue}
        set state [list [get_db $inst .location] [get_db $inst .orient] \
            [get_db $inst .place_status] [get_db $inst .place_status_cts] \
            [get_db $inst .place_status_effective]]
        if {$state ne [dict get $original $name]} {error "Original cell placement/status changed: $name"}
        incr seen
    }
    if {$seen != [dict size $original]} {error "An original instance is missing"}
    return $seen
}
set preserved [tri_oracle_memory_require_original_placements $original]
check_place > $out/${tag}_placement.rpt
tri_oracle_require_clean_placement $out/${tag}_placement.rpt
puts "TRI_ORACLE_MEMORY_FREE_SLOT_PLACEMENT_LEGAL 6568 ORIGINALS_PRESERVED $preserved"
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
set saved_timing [get_db route_with_timing_driven]
set saved_si [get_db route_with_si_driven]
set_db route_with_timing_driven false
set_db route_with_si_driven false
set router_report $out/${tag}_router.rpt
if {![catch {file lstat $router_report ignored}]} {error "Refusing existing free-slot router trace"}
try {
    redirect $router_report {
        puts "TRI_ORACLE_LOCAL_ECO_MODE [get_db route_with_timing_driven] [get_db route_with_si_driven]"
        route_eco
    } -tee
} finally {
    set_db route_with_timing_driven $saved_timing
    set_db route_with_si_driven $saved_si
    tri_oracle_reset_router_timing
}
set channel [open $router_report r]
try {set evidence [tri_oracle_memory_endpoint_router_evidence [read $channel]]} finally {close $channel}
set preserved [tri_oracle_memory_require_original_placements $original]
unset original
if {[llength [get_db insts *TRI_MEMORY_ENDPOINT_HOLD_*]] != 6568} {error "Routed delay count changed"}
foreach name [dict keys $slots] {
    set inst [get_db insts $name]
    lassign [dict get $slots $name] endpoint x y orient target_x target_y
    lassign [tri_oracle_memory_point_dbu [get_db $inst .location]] px py
    if {[llength $inst] != 1 || [get_db $inst .base_cell.name] ne {DEL100D1BWP12T40P140} ||
        ![get_db $inst .dont_touch] || $px != $x || $py != $y ||
        [get_db $inst .orient] ne $orient} {error "Routed delay identity/protection/placement changed"}
}
set channel [open $out/${tag}_preservation.rpt w]
puts $channel "original_cells_location_orientation_and_status_preserved: $preserved"
puts $channel "new_delay_cells_at_verified_free_slots: 6568"
puts $channel "router_diagnostic_evidence: $evidence"
close $channel
check_place > $out/${tag}_routed_placement.rpt
tri_oracle_require_clean_placement $out/${tag}_routed_placement.rpt
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
write_db -rc_extract $destination
puts "TRI_ORACLE_MEMORY_FREE_SLOT_CHECKPOINT_WRITTEN"
report_timing -view setup_slow > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
puts "TRI_ORACLE_MEMORY_FREE_SLOT_COMMANDS_FINISHED"
exit
