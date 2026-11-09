# One measured, bounded engineering change order. Keep routed.db immutable;
# this writes a separate diagnostic checkpoint, never a closure verdict.
source syn/tri_oracle_memory_physical_config.tcl
source syn/tri_oracle_memory_typed_endpoint_policy.tcl
source syn/tri_oracle_require_clean_placement.tcl
source syn/tri_oracle_signal_repair_targets.tcl
set tag postroute_measured_endpoint_hold_03
if {[info exists ::env(TRI_ORACLE_MEMORY_ENDPOINT_DIAGNOSTIC_ONLY)]} {
    if {$::env(TRI_ORACLE_MEMORY_ENDPOINT_DIAGNOSTIC_ONLY) ne {1}} {
        error "Invalid unplaced endpoint diagnostic mode"
    }
    set tag postroute_measured_endpoint_unplaced
}
if {![info exists ::env(TRI_ORACLE_PHYSICAL_STAGE)] ||
    $::env(TRI_ORACLE_PHYSICAL_STAGE) ne $tag} {error "Unexpected memory endpoint repair stage"}
set destination $out/${tag}.db
if {![catch {file lstat $destination ignored}]} {error "Refusing existing output checkpoint"}
set inventory $out/postroute_endpoint_margin_probe.tsv
if {[lindex [exec sha256sum $inventory] 0] ne \
    "9a3d75a3897239710f0797a17b6fca9d2b4d03623c4587e346eddd284cd03681"} {
    error "Measured endpoint inventory differs from its qualified producer"
}
set channel [open $inventory r]
try {set measured [tri_oracle_memory_endpoint_inventory [read $channel]]} finally {close $channel}
set cell_inventory $out/postroute_endpoint_cell_probe.tsv
if {[lindex [exec sha256sum $cell_inventory] 0] ne \
    "9a4c010c6b3da1d78c43d71dbdddd36105afec69021b4f663c58a1d0164a76d0"} {
    error "Native endpoint model/net inventory differs from its qualified producer"
}
set channel [open $cell_inventory r]
try {
    set native_cells [tri_oracle_memory_endpoint_cells_inventory [read $channel] $measured]
} finally {close $channel}
set_multi_cpu_usage -local_cpu 20
read_db $out/routed.db
tri_oracle_require_memory_design
source syn/tri_oracle_memory_postroute_settings.tcl
set_db delaycal_enable_si true
set_db si_delay_enable_report true
set delay_cell DEL100D1BWP12T40P140
set base [get_db base_cells $delay_cell]
if {[llength $base] != 1 || [get_db $base .name] ne $delay_cell} {
    error "Required characterized delay cell is absent"
}
if {[llength [get_db insts *TRI_MEMORY_ENDPOINT_HOLD_*]] != 0} {
    error "This exact predecessor must not already contain the new repair cells"
}

# Recollect all negative holds from the restored database. Convert native pin
# collections directly to database objects; no wildcard indexed-name lookup.
set paths [report_timing -early -view hold_fast -collection \
    -max_paths 10000 -nworst 1 -max_slack 0]
if {[sizeof_collection $paths] != [dict size $measured]} {
    error "Restored negative-hold count differs from the complete measured inventory"
}
set targets [copy_collection [get_property $paths capturing_point]]
set admitted [dict create]
foreach_in_collection path $paths {
    set launch [get_object_name [get_property $path launching_point]]
    set capture [get_object_name [get_property $path capturing_point]]
    set hold [get_property $path slack]
    if {![dict exists $measured $capture] || [dict exists $admitted $capture]} {
        error "Unexpected or repeated restored hold endpoint: $capture"
    }
    lassign [dict get $measured $capture] expected_launch expected_hold slow typical expected_kind
    set kind [tri_oracle_memory_endpoint_kind $launch $capture $hold]
    if {$launch ne $expected_launch || $kind ne $expected_kind ||
        abs($hold-$expected_hold) > 0.000001} {
        error "Restored timing path differs from its measured producer: $capture"
    }
    set pin [get_db [get_property $path capturing_point]]
    if {[llength $pin] != 1 || [get_db $pin .name] ne $capture ||
        [get_db $pin .direction] ne {in}} {
        error "Native endpoint pin identity is not unique: $capture"
    }
    set inst [get_db $pin .inst]
    set expected_inst [string range $capture 0 [expr {[string last / $capture]-1}]]
    if {[llength $inst] != 1 || [get_db $inst .name] ne $expected_inst} {
        error "Native endpoint instance identity differs: $capture"
    }
    set model [get_db $inst .base_cell.name]
    tri_oracle_memory_endpoint_typed_cell $kind $model
    set net [get_db $pin .net]
    if {[llength $net] != 1} {error "Missing unique data net at $capture"}
    lassign [dict get $native_cells $capture] expected_model expected_net
    if {$model ne $expected_model || [get_db $net .name] ne $expected_net} {
        error "Native endpoint model/net differs from its exact inventory: $capture"
    }
    tri_oracle_route_require_data_net [get_db $net .name] \
        [get_db $net .is_clock] [get_db $net .is_power] [get_db $net .is_ground]
    dict set admitted $capture [list $launch $hold $kind $model]
}
unset paths
if {[dict size $admitted] != [dict size $measured]} {error "Incomplete native endpoint admission"}

# Recheck setup in batches before the first mutation. All endpoints must have
# both original views and at least0.450ns of measured headroom.
set margins [dict create]
foreach view {setup_slow setup_typ} {
    set setup [report_timing -view $view -check_type setup -to $targets \
        -max_paths 10000 -nworst 1 -collection]
    set count [sizeof_collection $setup]
    if {$count <= 0 || $count >= 10000} {error "Incomplete $view setup inventory"}
    set observed [dict create]
    foreach_in_collection path $setup {
        set capture [get_object_name [get_property $path capturing_point]]
        if {![dict exists $admitted $capture]} {error "Unexpected $view setup endpoint"}
        set slack [get_property $path slack]
        tri_oracle_finite_timing_value $slack
        if {![dict exists $observed $capture] || $slack < [dict get $observed $capture]} {
            dict set observed $capture $slack
        }
    }
    unset setup
    if {[dict size $observed] != [dict size $measured]} {error "Missing $view setup endpoints"}
    foreach capture [dict keys $admitted] {
        dict set margins $capture $view [dict get $observed $capture]
    }
}
foreach capture [dict keys $admitted] {
    tri_oracle_memory_feedback_headroom $capture [dict get $margins $capture]
}
set channel [open $out/${tag}_admission.tsv w]
puts $channel "launch\tendpoint\thold_fast_ns\tkind\tbase_cell\tsetup_slow_ns\tsetup_typ_ns"
foreach capture [lsort [dict keys $admitted]] {
    lassign [dict get $admitted $capture] launch hold kind model
    puts $channel [join [list $launch $capture $hold $kind $model \
        [dict get $margins $capture setup_slow] [dict get $margins $capture setup_typ]] \t]
}
close $channel
puts "TRI_ORACLE_MEMORY_MEASURED_ENDPOINTS_ADMITTED [dict size $admitted]"

set_db eco_update_timing false
set_db eco_refine_place false
set_db eco_check_logical_equivalence true
set_db eco_batch_mode true
set results {}
set index 0
try {
    foreach capture [lsort [dict keys $admitted]] {
        set name TRI_MEMORY_ENDPOINT_HOLD_$index
        if {[llength [get_db insts $name]] != 0} {error "New delay name is already present"}
        # -pins is a string; a Tcl list adds literal braces to indexed names.
        set result [eco_add_repeater -cells $delay_cell -pins $capture -name $name -no_place]
        tri_oracle_memory_endpoint_insertion $name $result
        lappend results [list $capture {*}$result]
        incr index
    }
} finally {set_db eco_batch_mode false}
set channel [open $out/${tag}_insertions.tsv w]
puts $channel "endpoint\tinstance\tinput_net\toutput_net"
foreach result $results {puts $channel [join $result \t]}
close $channel
puts "TRI_ORACLE_MEMORY_MEASURED_ENDPOINT_DELAYS_INSERTED [llength $results]"
if {$tag eq {postroute_measured_endpoint_unplaced}} {
    source syn/tri_oracle_memory_endpoint_unplaced_diagnostic.tcl
    error "Unplaced diagnostic returned without its required terminal marker/exit"
}
# Attempt02 could not legalize412 added cells with all PLACED neighbors frozen.
# Permit incremental movement of PLACED cells; FIXED cells remain fixed. The
# unchanged strict placement gate and later routing/timing checks still apply.
place_eco -fix_placed_insts false
check_place > $out/${tag}_placement.rpt
tri_oracle_require_clean_placement $out/${tag}_placement.rpt
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
foreach result $results {
    set inst [get_db insts [lindex $result 1]]
    if {[llength $inst] != 1 || [get_db $inst .name] ne [lindex $result 1] ||
        [get_db $inst .base_cell.name] ne $delay_cell} {
        error "Inserted delay identity changed before routing"
    }
    set_db $inst .dont_touch true
}

# Route the changed connections once. This geometric step is not the later
# independent timing, signal-integrity, geometry or antenna qualification.
set saved_timing [get_db route_with_timing_driven]
set saved_si [get_db route_with_si_driven]
set_db route_with_timing_driven false
set_db route_with_si_driven false
set router_report $out/${tag}_router.rpt
if {![catch {file lstat $router_report ignored}]} {error "Refusing existing native router report"}
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
set channel [open $out/${tag}_routing_evidence.rpt w]
puts $channel $evidence
close $channel
if {[llength [get_db insts *TRI_MEMORY_ENDPOINT_HOLD_*]] != [dict size $admitted]} {
    error "Routed endpoint-delay inventory differs from admitted count"
}
foreach result $results {
    set inst [get_db insts [lindex $result 1]]
    if {[llength $inst] != 1 || [get_db $inst .name] ne [lindex $result 1] ||
        [get_db $inst .base_cell.name] ne $delay_cell ||
        ![get_db $inst .dont_touch]} {error "Routed endpoint-delay identity/protection changed"}
}
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
write_db -rc_extract $destination
puts "TRI_ORACLE_MEMORY_MEASURED_ENDPOINT_CHECKPOINT_WRITTEN"
report_timing -view setup_slow > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
puts "TRI_ORACLE_MEMORY_MEASURED_ENDPOINT_REPAIR_COMMANDS_FINISHED"
exit
