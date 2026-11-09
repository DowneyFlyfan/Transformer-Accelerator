# Read-only measured admission data for current residual timing/noise repair.
# This entry never writes the input database or changes cells, placement or routes.
source syn/tri_oracle_memory_physical_config.tcl
source syn/tri_oracle_endpoint_hold_policy.tcl
source syn/tri_oracle_memory_route_scope.tcl
source syn/tri_oracle_memory_wire_scope.tcl
source syn/tri_oracle_memory_point_dbu.tcl
source syn/tri_oracle_memory_native_route_checks.tcl
source syn/tri_oracle_signal_repair_targets.tcl
set tag postroute_memory_residual_probe
if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ne $tag} {error "Unexpected residual probe stage"}
set stem $out/$tag
foreach suffix {hold_margins.tsv endpoint_cells.tsv drivers.tsv complete.rpt} {
    if {![catch {file lstat $stem.$suffix ignored}]} {error "Refusing an existing residual probe output"}
}
if {[lindex [exec sha256sum records/memory_cold_geometry_qualification_result.json] 0] ne {314983fdd1aa175e260b726eb8426405e7e51a8500302b2f1f2cbc393998d6f2}} {
    error "Exact independent cold result changed"
}
set cold_reports $out/qualification_postroute_qualify_after_geometry_markers
set noisy_file $cold_reports/qualification_si_reports/qualification_si.tran.gz
if {[lindex [exec sha256sum $noisy_file] 0] ne {11ae4b482bff24973845d830aefd47458ed7863b65e436a44a8a085f1edd4aad}} {error "Cold noisy-slew report changed"}
set expected_hold [dict create {core/preparation/shift_reg[1]/D} {{cfg_activation_shift[1]} -0.010081} {core/preparation/shift_reg[4]/D} {{cfg_activation_shift[4]} -0.012709} {reader/gamma_word_reg[127]/D} {{rsp_data[63]} -0.006388} {reader/gamma_word_reg[63]/D} {{rsp_data[63]} -0.000562} {reader/gamma_word_reg[80]/D} {{rsp_data[16]} -0.000212} {reader/raw_word_reg[127]/D} {{rsp_data[63]} -0.003103}]
set expected_noisy [list {core/cache/n_687} {core/execution/core/FE_OFN52531_n_34952} {core/execution/core/core/n_31175} {core/execution/core/core/n_36914} {core/execution/core/core/storage[12].inputs/words[17][54]} {core/execution/core/core/storage[18].inputs/words[0][25]} {core/execution/core/core/storage[18].inputs/words[19][54]} {core/execution/core/core/storage[18].inputs/words[1][53]} {core/execution/core/core/storage[18].inputs/words[21][18]} {core/execution/core/core/storage[24].inputs/words[17][29]} {core/execution/core/core/storage[9].inputs/words[16][14]} {core/execution/core/core/storage[9].inputs/words[21][42]} {core/execution/core/n_35502} {core/execution/core_out_data[766]}]
set expected_setup_outputs [list {req_address[44]} {req_address[43]}]
set noisy [tri_oracle_route_slew_targets [exec gzip -dc $noisy_file]]
if {$noisy ne $expected_noisy || [llength $noisy] != 14} {error "Complete current noisy-net list changed"}
proc tri_oracle_residual_row {channel fields} {
    foreach field $fields {
        if {[regexp {[\t\r\n]} $field]} {error "Unsupported native inventory delimiter"}
    }
    puts $channel [join $fields \t]
}
set_multi_cpu_usage -local_cpu 20
read_db $out/postroute_memory_geometry_markers.db
tri_oracle_require_memory_design
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db delaycal_enable_si true
set_db si_delay_enable_report true
tri_oracle_memory_native_require_delays 6568
if {[llength [get_db insts]] != 906420} {error "Exact cold cell count changed"}
set paths [report_timing -early -view hold_fast -collection -max_paths 10000 -nworst 1 -max_slack 0]
set count [sizeof_collection $paths]
if {$count != 6 || $count != [dict size $expected_hold]} {error "Complete six-endpoint hold set changed"}
set targets [copy_collection [get_property $paths capturing_point]]
set rows [dict create]
set cell_channel [open $stem.endpoint_cells.tsv {WRONLY CREAT EXCL}]
try {
    tri_oracle_residual_row $cell_channel {launch endpoint hold_fast_ns base_cell net native_use connections wire_count driver_pins driver_ports inst_x_dbu inst_y_dbu orient place_status place_status_cts place_status_effective dont_touch dont_touch_effective}
    foreach_in_collection path $paths {
        set launch [get_object_name [get_property $path launching_point]]
        set capture [get_object_name [get_property $path capturing_point]]
        set slack [get_property $path slack]
        tri_oracle_finite_timing_value $slack
        if {![dict exists $expected_hold $capture] || [dict exists $rows $capture]} {error "Unexpected/repeated hold endpoint"}
        lassign [dict get $expected_hold $capture] expected_launch expected_slack
        if {$launch ne $expected_launch || abs($slack-$expected_slack) > 0.000001 || $slack >= 0 || $slack < -0.050} {
            error "Fresh hold identity/slack differs from complete cold report"
        }
        set pin [get_db [get_property $path capturing_point]]
        if {[llength $pin] != 1 || [get_db $pin .name] ne $capture || [get_db $pin .direction] ne {in} ||
            ![string match */D $capture]} {error "Expected exact ordinary D input"}
        set inst [get_db $pin .inst]
        if {[llength $inst] != 1 || [get_db $inst .name] ne [string range $capture 0 end-2]} {error "Endpoint instance identity differs"}
        set net [get_db $pin .net]
        if {[llength $net] != 1} {error "Endpoint must have exactly one data net"}
        set name [get_db $net .name]
        tri_oracle_memory_native_data_net $name
        set state [tri_oracle_memory_native_cell_row $inst]
        lassign [lindex $state 1] x y
        tri_oracle_residual_row $cell_channel [list $launch $capture $slack [lindex $state 0] $name [get_db $net .use] \
            [get_db $net .num_connections] [llength [get_db $net .wires]] \
            [tri_oracle_memory_native_names [get_db $net .driver_pins]] [tri_oracle_memory_native_names [get_db $net .driver_ports]] \
            $x $y {*}[lrange $state 2 end] [get_db $inst .dont_touch_effective]]
        dict set rows $capture [list $launch $slack]
    }
} finally {close $cell_channel}
unset paths
if {[dict size $rows] != 6} {error "Incomplete actual endpoint inventory"}
set setup_slacks [dict create]
foreach view {setup_slow setup_typ} {
    set setup [report_timing -view $view -check_type setup -to $targets -max_paths 10000 -nworst 1 -collection]
    if {[sizeof_collection $setup] < 1 || [sizeof_collection $setup] >= 10000} {error "Missing/truncated setup margin coverage"}
    set observed [dict create]
    foreach_in_collection path $setup {
        set capture [get_object_name [get_property $path capturing_point]]
        set slack [get_property $path slack]
        tri_oracle_finite_timing_value $slack
        if {![dict exists $rows $capture]} {error "Unexpected setup-margin endpoint"}
        if {![dict exists $observed $capture] || $slack < [dict get $observed $capture]} {dict set observed $capture $slack}
    }
    unset setup
    if {[dict size $observed] != 6} {error "Incomplete six-endpoint setup margin coverage"}
    foreach capture [dict keys $rows] {
        if {![dict exists $observed $capture]} {error "Missing setup margin"}
        dict set setup_slacks $capture $view [dict get $observed $capture]
    }
    puts "TRI_ORACLE_MEMORY_RESIDUAL_MARGIN_VIEW $view ENDPOINTS 6"
}
set margin_channel [open $stem.hold_margins.tsv {WRONLY CREAT EXCL}]
try {
    tri_oracle_residual_row $margin_channel {launch endpoint hold_fast_ns setup_slow_ns setup_typ_ns}
    foreach capture [lsort [dict keys $rows]] {
        lassign [dict get $rows $capture] launch hold
        tri_oracle_residual_row $margin_channel [list $launch $capture $hold \
            [dict get $setup_slacks $capture setup_slow] [dict get $setup_slacks $capture setup_typ]]
    }
} finally {close $margin_channel}
# Observe all actual driver identities and cell/protection/placement states.
# No replacement cell or resize admission is inferred from this inventory.
set requests {}
foreach name $noisy {lappend requests [list noisy_slew $name $name]}
foreach name $expected_setup_outputs {
    if {[regexp {[*?]} $name]} {error "Ambiguous setup port pattern"}
    set port [get_db ports $name]
    if {[llength $port] != 1 || [get_db $port .name] ne $name || [get_db $port .direction] ne {out}} {
        error "Missing exact failing setup output port"
    }
    set net [get_db $port .net]
    if {[llength $net] != 1} {error "Failing output requires exactly one net"}
    lappend requests [list slow_setup_output $name [get_db $net .name]]
}
if {[llength $requests] != 16} {error "Incomplete driver requests"}
set driver_channel [open $stem.drivers.tsv {WRONLY CREAT EXCL}]
set driver_rows 0
try {
    tri_oracle_residual_row $driver_channel {role requested_object net native_use connections wire_count net_dont_touch driver_kind driver_name driver_direction instance base_cell dont_touch dont_touch_effective x_dbu y_dbu orient place_status place_status_cts place_status_effective parent module_instances}
    foreach request $requests {
        lassign $request role requested name
        set net [tri_oracle_memory_native_data_net $name]
        set prefix [list $role $requested $name [get_db $net .use] [get_db $net .num_connections] \
            [llength [get_db $net .wires]] [get_db $net .dont_touch]]
        set pins [get_db $net .driver_pins]
        set ports [get_db $net .driver_ports]
        if {[llength $pins]+[llength $ports] < 1 || [llength $pins]+[llength $ports] > 8} {error "Unexpected data driver cardinality"}
        foreach pin $pins {
            set inst [get_db $pin .inst]
            if {[llength $inst] != 1} {error "Missing driver instance"}
            set state [tri_oracle_memory_native_cell_row $inst]
            lassign [lindex $state 1] x y
            set parent [get_db $inst .parent]
            if {[get_db $parent .name] eq $top} {set sharing 1} else {
                set sharing [llength [get_db [get_db $parent .module] .hinsts]]
            }
            tri_oracle_residual_row $driver_channel [list {*}$prefix pin [get_db $pin .name] [get_db $pin .direction] \
                [get_db $inst .name] [lindex $state 0] [lindex $state 6] [get_db $inst .dont_touch_effective] \
                $x $y {*}[lrange $state 2 5] [get_db $parent .name] $sharing]
            incr driver_rows
        }
        foreach port $ports {
            tri_oracle_residual_row $driver_channel [list {*}$prefix port [get_db $port .name] [get_db $port .direction] \
                {} {} {} {} {} {} {} {} {} {} {} {}]
            incr driver_rows
        }
    }
} finally {close $driver_channel}
if {$driver_rows < 16 || $driver_rows > 128} {error "Incomplete/unbounded driver inventory"}
tri_oracle_memory_native_require_delays 6568
set file [open $stem.complete.rpt {WRONLY CREAT EXCL}]
try {
    puts $file "negative_hold_endpoints: 6"
    puts $file "setup_margin_views: 2"
    puts $file "noisy_net_requests: 14"
    puts $file "slow_setup_output_requests: 2"
    puts $file "driver_inventory_rows: $driver_rows"
    puts $file "protected_memory_endpoint_delays: 6568"
    puts $file "physical_mutation_requested: false"
} finally {close $file}
puts "TRI_ORACLE_MEMORY_RESIDUAL_PROBE_COMMANDS_FINISHED"
exit
