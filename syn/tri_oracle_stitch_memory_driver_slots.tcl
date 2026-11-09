# Geometric reconnection of16 proved driver replacements at exact reviewed points.
# This stage makes no timing-driven routing or timing-file-consumption claim.
source syn/tri_oracle_memory_physical_config.tcl
source syn/tri_oracle_memory_route_scope.tcl
source syn/tri_oracle_memory_wire_scope.tcl
source syn/tri_oracle_memory_point_dbu.tcl
source syn/tri_oracle_memory_native_route_checks.tcl
source syn/tri_oracle_memory_drive_resize_policy.tcl
source syn/tri_oracle_memory_drive_exact_slots.tcl
source syn/tri_oracle_memory_stitch_policy.tcl
source syn/tri_oracle_require_clean_placement.tcl
set tag postroute_memory_driver_stitch_slots_03
if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ne $tag} {error "Unexpected driver resize stage"}
set stem $out/$tag
foreach path [list $stem.db $stem.router.rpt $stem.router.tif $stem.admission.tsv] {
    if {![catch {file lstat $path ignored}]} {error "Refusing an existing driver-repair output"}
}
foreach {path checksum} {
    records/memory_driver_resize_candidates.json 557b27c472cbb99a554cfce19de23d81dd863350c48aebd6b6e0ad81c500b95e
    records/memory_driver_resize_exact_slot_candidates.json 33c5bba0941b2fa497db4f5c0069839cbc64d2ff967728f824011b00ec249f62
    records/memory_driver_resize_nearest_slots.json 3edebee63557f0d56f0e8bcf9a15abd02277577243ed15bd1d298cdd5c4279fb
    records/memory_drive_pairs_iverilog_validation.json ba18098d56c88c3ead6d58b6a15191c0ad90c03d00cd49e0965379213cff34b9
    records/memory_drive_pairs_geometry_validation.json 90a08c39388525e92eeb47b5120ff25faf6ac4eec83a1c38b19ea4540102f1c7
    records/memory_residual_probe_result.json f4ddd5a90450dd569628fe96017d5b98fbc3f846081f8006bf020d7a430a3c35
} {
    if {[lindex [exec sha256sum $path] 0] ne $checksum} {error "Exact measured driver evidence changed"}
}
set candidates [dict create \
    {core/cache/g257794} {{core/cache/n_687} {core/cache/g257794/ZN} {noisy_slew} {core/cache/n_687} {NR2D2BWP12T40P140} {{NR2D1BWP12T40P140} {{491770} {951200}} {mx} {placed} {unset} {placed} {none}}} \
    {core/execution/core/FE_OFC25833_n_34952} {{core/execution/core/FE_OFN52531_n_34952} {core/execution/core/FE_OFC25833_n_34952/Z} {noisy_slew} {core/execution/core/FE_OFN52531_n_34952} {BUFFD2BWP12T40P140} {{BUFFD1BWP12T40P140} {{2768730} {1397600}} {mx} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/g7687} {{core/execution/core/core/n_31175} {core/execution/core/core/g7687/ZN} {noisy_slew} {core/execution/core/core/n_31175} {AOI22D2BWP12T40P140} {{AOI22D1BWP12T40P140} {{1039730} {348800}} {my} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/g7262} {{core/execution/core/core/n_36914} {core/execution/core/core/g7262/ZN} {noisy_slew} {core/execution/core/core/n_36914} {AOI22D2BWP12T40P140} {{AOI22D1BWP12T40P140} {{1059050} {646400}} {r0} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[12].inputs/words_reg[17][54]} {{core/execution/core/core/storage[12].inputs/words[17][54]} {core/execution/core/core/storage[12].inputs/words_reg[17][54]/Q} {noisy_slew} {core/execution/core/core/storage[12].inputs/words[17][54]} {SDFQD1BWP12T40P140} {{SDFQD0BWP12T40P140} {{2115490} {682400}} {mx} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[18].inputs/words_reg[0][25]} {{core/execution/core/core/storage[18].inputs/words[0][25]} {core/execution/core/core/storage[18].inputs/words_reg[0][25]/Q} {noisy_slew} {core/execution/core/core/storage[18].inputs/words[0][25]} {SDFQD1BWP12T40P140} {{SDFQD0BWP12T40P140} {{1679250} {497600}} {r0} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[18].inputs/words_reg[19][54]} {{core/execution/core/core/storage[18].inputs/words[19][54]} {core/execution/core/core/storage[18].inputs/words_reg[19][54]/Q} {noisy_slew} {core/execution/core/core/storage[18].inputs/words[19][54]} {SDFQD1BWP12T40P140} {{SDFQD0BWP12T40P140} {{1559970} {454400}} {r0} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[18].inputs/words_reg[1][53]} {{core/execution/core/core/storage[18].inputs/words[1][53]} {core/execution/core/core/storage[18].inputs/words_reg[1][53]/Q} {noisy_slew} {core/execution/core/core/storage[18].inputs/words[1][53]} {SDFQD1BWP12T40P140} {{SDFQD0BWP12T40P140} {{1673930} {500000}} {mx} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[18].inputs/words_reg[21][18]} {{core/execution/core/core/storage[18].inputs/words[21][18]} {core/execution/core/core/storage[18].inputs/words_reg[21][18]/Q} {noisy_slew} {core/execution/core/core/storage[18].inputs/words[21][18]} {SDFQD1BWP12T40P140} {{SDFQD0BWP12T40P140} {{1568090} {507200}} {r0} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[24].inputs/words_reg[17][29]} {{core/execution/core/core/storage[24].inputs/words[17][29]} {core/execution/core/core/storage[24].inputs/words_reg[17][29]/Q} {noisy_slew} {core/execution/core/core/storage[24].inputs/words[17][29]} {SDFQD1BWP12T40P140} {{SDFQD0BWP12T40P140} {{1503690} {413600}} {mx} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[9].inputs/words_reg[16][14]} {{core/execution/core/core/storage[9].inputs/words[16][14]} {core/execution/core/core/storage[9].inputs/words_reg[16][14]/Q} {noisy_slew} {core/execution/core/core/storage[9].inputs/words[16][14]} {SDFQD1BWP12T40P140} {{SDFQD0BWP12T40P140} {{1898210} {442400}} {mx} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[9].inputs/words_reg[21][42]} {{core/execution/core/core/storage[9].inputs/words[21][42]} {core/execution/core/core/storage[9].inputs/words_reg[21][42]/Q} {noisy_slew} {core/execution/core/core/storage[9].inputs/words[21][42]} {SDFQD1BWP12T40P140} {{SDFQD0BWP12T40P140} {{1897930} {464000}} {r0} {placed} {unset} {placed} {none}}} \
    {core/execution/core/g35323} {{core/execution/core/n_35502} {core/execution/core/g35323/ZN} {noisy_slew} {core/execution/core/n_35502} {CKND2D2BWP12T40P140} {{CKND2D1BWP12T40P140} {{2762850} {1380800}} {r0} {placed} {unset} {placed} {none}}} \
    {core/execution/core/g35548} {{core/execution/core_out_data[766]} {core/execution/core/g35548/ZN} {noisy_slew} {core/execution/core_out_data[766]} {INR2D2BWP12T40P140} {{INR2D1BWP12T40P140} {{2107650} {1280000}} {r0} {placed} {unset} {placed} {none}}} \
    {FE_OFC13350_req_address_44} {{req_address[44]} {FE_OFC13350_req_address_44/ZN} {slow_setup_output} {req_address[44]} {INVD2BWP12T40P140} {{INVD1BWP12T40P140} {{252370} {327200}} {mx} {placed} {unset} {placed} {none}}} \
    {FE_OFC13352_req_address_43} {{req_address[43]} {FE_OFC13352_req_address_43/ZN} {slow_setup_output} {req_address[43]} {INVD2BWP12T40P140} {{INVD1BWP12T40P140} {{474970} {569600}} {r0} {placed} {unset} {placed} {none}}} \
]
if {[dict size $candidates] != 16} {error "Expected exactly16 measured unique drivers"}
set exact_slot_rows [dict create \
    {core/cache/g257794} {{NR2D2BWP12T40P140} {{491210} {951200}} {mx} {placed} {unset} {placed} {none}} \
    {core/execution/core/FE_OFC25833_n_34952} {{BUFFD2BWP12T40P140} {{2768730} {1397600}} {mx} {placed} {unset} {placed} {none}} \
    {core/execution/core/core/g7687} {{AOI22D2BWP12T40P140} {{972250} {372800}} {my} {placed} {unset} {placed} {none}} \
    {core/execution/core/core/g7262} {{AOI22D2BWP12T40P140} {{1027130} {660800}} {r0} {placed} {unset} {placed} {none}} \
    {core/execution/core/core/storage[12].inputs/words_reg[17][54]} {{SDFQD1BWP12T40P140} {{2115490} {682400}} {mx} {placed} {unset} {placed} {none}} \
    {core/execution/core/core/storage[18].inputs/words_reg[0][25]} {{SDFQD1BWP12T40P140} {{1679250} {497600}} {r0} {placed} {unset} {placed} {none}} \
    {core/execution/core/core/storage[18].inputs/words_reg[19][54]} {{SDFQD1BWP12T40P140} {{1559970} {454400}} {r0} {placed} {unset} {placed} {none}} \
    {core/execution/core/core/storage[18].inputs/words_reg[1][53]} {{SDFQD1BWP12T40P140} {{1673930} {500000}} {mx} {placed} {unset} {placed} {none}} \
    {core/execution/core/core/storage[18].inputs/words_reg[21][18]} {{SDFQD1BWP12T40P140} {{1568090} {507200}} {r0} {placed} {unset} {placed} {none}} \
    {core/execution/core/core/storage[24].inputs/words_reg[17][29]} {{SDFQD1BWP12T40P140} {{1503690} {413600}} {mx} {placed} {unset} {placed} {none}} \
    {core/execution/core/core/storage[9].inputs/words_reg[16][14]} {{SDFQD1BWP12T40P140} {{1898210} {442400}} {mx} {placed} {unset} {placed} {none}} \
    {core/execution/core/core/storage[9].inputs/words_reg[21][42]} {{SDFQD1BWP12T40P140} {{1897930} {464000}} {r0} {placed} {unset} {placed} {none}} \
    {core/execution/core/g35323} {{CKND2D2BWP12T40P140} {{2762850} {1380800}} {r0} {placed} {unset} {placed} {none}} \
    {core/execution/core/g35548} {{INR2D2BWP12T40P140} {{2105410} {1304000}} {r0} {placed} {unset} {placed} {none}} \
    {FE_OFC13350_req_address_44} {{INVD2BWP12T40P140} {{259370} {327200}} {mx} {placed} {unset} {placed} {none}} \
    {FE_OFC13352_req_address_43} {{INVD2BWP12T40P140} {{474970} {569600}} {r0} {placed} {unset} {placed} {none}} \
]

proc tri_oracle_memory_drive_logical {net} {
    set ports [lsort -unique [concat [get_db $net .driver_ports] [get_db $net .load_ports]]]
    return [tri_oracle_memory_drive_net_inventory [get_db $net .num_connections] \
        [tri_oracle_memory_native_names [get_db $net .pins]] [tri_oracle_memory_native_names $ports]]
}
proc tri_oracle_memory_drive_native_scope {before replacements allow_diodes {exact_rows {}}} {
    set seen 0
    set resized 0
    set scans 0
    set untouched 0
    set maximum_squared 0
    set additions {}
    set diode_pins {}
    foreach inst [get_db insts] {
        set name [get_db $inst .name]
        set row [tri_oracle_memory_native_cell_row $inst]
        if {[dict exists $before $name]} {
            if {[dict exists $replacements $name]} {
                if {$exact_rows eq {}} {
                    set result [tri_oracle_memory_drive_resize_row $name [dict get $before $name] \
                        $row [dict get $replacements $name]]
                } else {
                    set result [tri_oracle_memory_drive_exact_slot_row $name [dict get $before $name] \
                        $row [dict get $replacements $name] $exact_rows]
                }
                incr resized
                incr scans [dict get $result scan_clock_load]
                set maximum_squared [expr {max($maximum_squared,[dict get $result displacement_squared_dbu2])}]
            } else {
                tri_oracle_memory_route_original_row $name [dict get $before $name] $row
                incr untouched
            }
            incr seen
        } else {
            if {!$allow_diodes} {error "Unexpected addition before routing: $name"}
            tri_oracle_memory_route_added_row $name $row
            lappend additions [list $name $row]
            set diode_pins [concat $diode_pins [tri_oracle_memory_native_names [get_db $inst .pins]]]
        }
    }
    tri_oracle_memory_drive_resize_scope_counts $seen [dict size $before] $resized $scans [llength $additions]
    if {$seen != 906420 || $untouched != 906404} {error "Exact original/nontarget preservation changed"}
    return [dict create original_cells $seen untouched_cells $untouched resized_targets $resized \
        exact_placement_scan_targets $scans maximum_displacement_squared_dbu2 $maximum_squared \
        added_antenna_diodes $additions allowed_diode_pins $diode_pins]
}
proc tri_oracle_memory_drive_logical_exact {logical} {
    foreach name [dict keys $logical] {
        set net [get_db nets $name]
        if {[llength $net] != 1 || [get_db $net .name] ne $name ||
            [tri_oracle_memory_drive_logical $net] ne [dict get $logical $name]} {
            error "Cell update/legalization changed original incident logical connections: $name"
        }
    }
}

set_multi_cpu_usage -local_cpu 20
read_db $out/postroute_memory_geometry_markers.db
tri_oracle_require_memory_design
source syn/tri_oracle_memory_postroute_settings.tcl
set_db delaycal_enable_si true
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
tri_oracle_memory_native_require_delays 6568
set before [tri_oracle_memory_native_cells_snapshot 906420]
set clocks [tri_oracle_memory_native_clocks_snapshot]
set clock_wires 0
foreach name [dict keys $clocks] {incr clock_wires [llength [dict get $clocks $name]]}
if {[dict size $clocks] != 4250 || $clock_wires != 593878} {error "Exact producer clock baseline changed"}
check_place > $stem.before_placement.rpt
tri_oracle_require_clean_placement $stem.before_placement.rpt
set replacements [dict create]
set comb_targets {}
set incident [dict create]
set route_names {}
set admission [open $stem.admission.tsv {WRONLY CREAT EXCL}]
try {
    puts $admission "instance\tnet\tdriver_pin\trole\toriginal_cell\tcandidate_cell\tscan_clock_load"
    dict for {name descriptor} $candidates {
        lassign $descriptor net_name pin_name role requested replacement expected_row
        # Canonicalize the nested point/list representation from the literal.
        set expected_row [list [lindex $expected_row 0] [list {*}[lindex $expected_row 1]] {*}[lrange $expected_row 2 end]]
        if {[regexp {[*?]} $name]} {error "Ambiguous target instance"}
        set inst [get_db insts $name]
        if {[llength $inst] != 1 || [get_db $inst .name] ne $name ||
            ![dict exists $before $name] || [dict get $before $name] ne $expected_row} {
            error "Actual target differs from exact measured native row: $name"
        }
        if {[get_db $inst .dont_touch_effective] ne {false}} {error "Protected target cannot be resized"}
        set parent [get_db $inst .parent]
        if {[get_db $parent .name] eq $top} {set sharing 1} else {
            set sharing [llength [get_db [get_db $parent .module] .hinsts]]
        }
        if {$sharing != 1} {error "Shared-module target is outside bounded repair"}
        set net [tri_oracle_memory_native_data_net $net_name]
        set dt [get_db $net .dont_touch]
        if {![string is boolean -strict $dt] || $dt || [llength [get_db $net .driver_ports]] != 0} {
            error "Protected or external target-driver net"
        }
        set driver [get_db $net .driver_pins]
        if {[llength $driver] != 1 || [get_db $driver .name] ne $pin_name ||
            [get_db $driver .direction] ne {out} || [get_db [get_db $driver .inst] .name] ne $name} {
            error "Actual unique driver identity changed"
        }
        set original [lindex $expected_row 0]
        if {[tri_oracle_memory_drive_resize_cell $original] ne $replacement} {error "Unproved replacement pair"}
        set master [get_db base_cells $replacement]
        if {[llength $master] != 1} {error "Replacement master missing"}
        set disabled [get_db $master .dont_use]
        if {![string is boolean -strict $disabled] || $disabled} {error "Replacement master disallowed"}
        dict set replacements $name $replacement
        set scan [expr {$original eq {SDFQD0BWP12T40P140}}]
        if {!$scan} {lappend comb_targets $name}
        puts $admission "$name\t$net_name\t$pin_name\t$role\t$original\t$replacement\t$scan"
        foreach pin [get_db $inst .pins] {
            set connected [get_db $pin .net]
            if {[llength $connected] != 1} {error "Target pin lacks an exact connected net"}
            set key [get_db $connected .name]
            foreach flag {is_clock is_power is_ground} {
                set value [get_db $connected .$flag]
                if {![string is boolean -strict $value]} {error "Unknown incident-net classification"}
                set flags($flag) $value
            }
            if {$flags(is_power) || $flags(is_ground)} {error "Unexpected signal pin on supply net"}
            if {![dict exists $incident $key]} {dict set incident $key [tri_oracle_memory_drive_logical $connected]}
            if {!$flags(is_clock) && [get_db $connected .num_connections] >= 2} {
                tri_oracle_memory_native_data_net $key
                lappend route_names $key
            }
        }
    }
} finally {close $admission}
set route_names [lsort -unique $route_names]
if {[dict size $replacements] != 16 || [llength $comb_targets] != 8 ||
    [llength $route_names] < 16 || [llength $route_names] > 256} {error "Incomplete/unbounded driver/incident route scope"}
set eco_saved [dict create]
foreach attribute {eco_honor_dont_touch eco_honor_dont_use eco_honor_fixed_status eco_check_logical_equivalence \
    eco_update_timing eco_refine_place eco_batch_mode} {dict set eco_saved $attribute [get_db $attribute]}
set route_saved [dict create]
foreach attribute {route_with_timing_driven route_with_si_driven route_selected_net_only route_with_eco \
    route_fix_clock_nets route_route_clock_nets_first route_detail_fix_antenna route_antenna_diode_insertion \
    route_antenna_cell_name route_detail_search_and_repair route_detail_end_iteration} {
    dict set route_saved $attribute [get_db $attribute]
}
set saved_check_type [get_db timing_analysis_check_type]
try {
    foreach attribute {eco_honor_dont_touch eco_honor_dont_use eco_honor_fixed_status eco_check_logical_equivalence} {
        set_db $attribute true
        if {[get_db $attribute] ne {true}} {error "Native equivalence/protection mode not honored"}
    }
    set_db eco_update_timing false
    set_db eco_refine_place false
    set_db eco_batch_mode true
    try {
        dict for {name replacement} $replacements {eco_update_cell -insts $name -cells $replacement}
    } finally {set_db eco_batch_mode false}
    set resized [tri_oracle_memory_drive_native_scope $before $replacements false]
    tri_oracle_memory_drive_logical_exact $incident
    tri_oracle_memory_native_clocks_preserved $clocks
    # Measured row slots avoid all original and planned peer footprints.
    # No automatic legalization or temporary unplacement is requested.
    foreach name $comb_targets {
        set expected [tri_oracle_memory_drive_canonical_row [dict get $exact_slot_rows $name]]
        lassign [lindex $expected 1] x y
        set orient [lindex $expected 2]
        place_inst $name [list [expr {$x/2000.0}] [expr {$y/2000.0}]] $orient -placed
        set inst [get_db insts $name]
        if {[llength $inst] != 1 || [get_db $inst .name] ne $name} {error "Exact slot target disappeared"}
        tri_oracle_memory_drive_exact_slot_row $name [dict get $before $name] \
            [tri_oracle_memory_native_cell_row $inst] [dict get $replacements $name] $exact_slot_rows
    }
    set legalized [tri_oracle_memory_drive_native_scope $before $replacements false $exact_slot_rows]
    tri_oracle_memory_drive_logical_exact $incident
    tri_oracle_memory_native_clocks_preserved $clocks
    check_place > $stem.legalized_placement.rpt
    tri_oracle_require_clean_placement $stem.legalized_placement.rpt
    connect_global_net VDD -type pg_pin -pin_base_name VDD -all
    connect_global_net VSS -type pg_pin -pin_base_name VSS -all
    check_drc -out_file $stem.before_route_drc.rpt
    set_db route_with_timing_driven false
    set_db route_with_si_driven false
    set_db route_with_eco true
    set_db route_fix_clock_nets true
    set_db route_route_clock_nets_first false
    set_db route_detail_fix_antenna true
    set_db route_antenna_diode_insertion true
    set_db route_antenna_cell_name ANTENNABWP12T40P140
    reset_db route_detail_end_iteration
    set_db route_detail_search_and_repair true
    tri_oracle_reset_router_timing
    deselect_obj -all
    foreach name $route_names {select_obj [tri_oracle_memory_native_data_net $name]}
    set_db route_selected_net_only true
    set file [open $stem.settings.rpt {WRONLY CREAT EXCL}]
    try {
        foreach attribute [dict keys $eco_saved] {puts $file "$attribute: [get_db $attribute]"}
        foreach attribute [dict keys $route_saved] {puts $file "$attribute: [get_db $attribute]"}
        puts $file "resized_driver_instances: 16"
        puts $file "exact_placement_scan_instances: 8"
        puts $file "exact_slot_combinational_instances: 8"
        puts $file "incident_nets: [dict size $incident]"
        puts $file "selected_incident_data_nets: [llength $route_names]"
    } finally {close $file}
    redirect $stem.router.rpt {
        foreach attribute {route_selected_net_only route_with_eco route_fix_clock_nets} {
            if {[get_db $attribute] ne {true}} {error "Native geometric ECO routing mode changed"}
        }
        foreach attribute {route_with_timing_driven route_with_si_driven} {
            if {[get_db $attribute] ne {false}} {error "Geometric routing must not claim timing/SI optimization"}
        }
        if {[get_db route_route_clock_nets_first] ne {false}} {error "Clock ECO-first mode must stay disabled"}
        puts "TRI_ORACLE_MEMORY_GEOSTITCH_MODE false false true true"
        puts "TRI_ORACLE_MEMORY_GEOSTITCH_CLOCK_MODE true false"
        puts "TRI_ORACLE_MEMORY_GEOSTITCH_TARGETS 16"
        puts "TRI_ORACLE_MEMORY_GEOSTITCH_DATA_NETS [llength $route_names]"
        route_eco -target
    } -tee
} finally {
    set_db eco_batch_mode false
    foreach attribute [dict keys $eco_saved] {set_db $attribute [dict get $eco_saved $attribute]}
    foreach attribute [dict keys $route_saved] {set_db $attribute [dict get $route_saved $attribute]}
    set_db timing_analysis_check_type $saved_check_type
    deselect_obj -all
    tri_oracle_reset_router_timing
}
set channel [open $stem.router.rpt r]
try {set stitch_evidence [tri_oracle_memory_stitch_evidence [read $channel]]} finally {close $channel}
set scope [tri_oracle_memory_drive_native_scope $before $replacements true $exact_slot_rows]
unset before
tri_oracle_memory_native_require_delays 6568
set clock_result [tri_oracle_memory_native_clocks_preserved $clocks]
unset clocks
if {[dict get $clock_result nets] != 4250 || [dict get $clock_result wires] != 593878} {error "Exact clock preservation changed"}
set logical_count 0
foreach name [dict keys $incident] {
    set net [get_db nets $name]
    if {[llength $net] != 1 || [get_db $net .name] ne $name} {error "Original incident net missing"}
    set actual [tri_oracle_memory_drive_logical $net]
    if {[lindex [dict get $incident $name] 0] == 1} {
        if {$actual ne [dict get $incident $name]} {error "Inactive incident net changed"}
    } else {
        tri_oracle_memory_wire_routed $name [dict get $incident $name] $actual \
            [dict get $scope allowed_diode_pins] [llength [get_db $net .wires]]
    }
    incr logical_count
}
set file [open $stem.preservation.rpt {WRONLY CREAT EXCL}]
try {
    foreach key {original_cells untouched_cells resized_targets exact_placement_scan_targets maximum_displacement_squared_dbu2} {
        puts $file "$key: [dict get $scope $key]"
    }
    puts $file "all_driver_targets_at_exact_verified_points: 16"
    puts $file "protected_endpoint_delays: 6568"
    puts $file "added_antenna_diodes: [llength [dict get $scope added_antenna_diodes]]"
    puts $file "added_cell_inventory: [dict get $scope added_antenna_diodes]"
    puts $file "incident_logical_inventories_preserved: $logical_count"
    puts $file "clock_nets_wire_statuses_preserved: [dict get $clock_result nets]"
    puts $file "clock_wires_statuses_preserved: [dict get $clock_result wires]"
    puts $file "timing_driven_routing_claimed: false"
    puts $file "geometric_stitch_evidence: $stitch_evidence"
} finally {close $file}
set target_file [open $stem.target_rows.tsv {WRONLY CREAT EXCL}]
try {
    puts $target_file "instance\tbase_cell\tx_dbu\ty_dbu\torient\tplace_status\tplace_status_cts\tplace_status_effective\tdont_touch"
    foreach name [lsort [dict keys $replacements]] {
        set row [tri_oracle_memory_drive_canonical_row [tri_oracle_memory_native_cell_row [get_db insts $name]]]
        lassign [lindex $row 1] x y
        puts $target_file [join [list $name [lindex $row 0] $x $y {*}[lrange $row 2 end]] \t]
    }
} finally {close $target_file}
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
check_place > $stem.placement.rpt
tri_oracle_require_clean_placement $stem.placement.rpt
check_connectivity -type all -out_file $stem.connected_before_save.rpt
set channel [open $stem.connected_before_save.rpt r]
try {tri_oracle_memory_connected_evidence [read $channel]} finally {close $channel}
puts "TRI_ORACLE_MEMORY_GEOSTITCH_CONNECTED_BEFORE_SAVE"
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
write_db -rc_extract $stem.db
puts "TRI_ORACLE_MEMORY_GEOSTITCH_CHECKPOINT_WRITTEN"
report_timing -view setup_slow -check_type setup > $stem.setup_slow.rpt
report_timing -view setup_typ -check_type setup > $stem.setup_typ.rpt
report_timing -early -view hold_fast > $stem.hold_fast.rpt
check_drc -out_file $stem.drc.rpt
check_antenna -out_file $stem.antenna.rpt
check_connectivity -type all -out_file $stem.connectivity.rpt
time_design -post_route -drv_report -expanded_views -report_dir $stem.after -report_prefix $tag
puts "TRI_ORACLE_MEMORY_GEOSTITCH_COMMANDS_FINISHED"
exit
