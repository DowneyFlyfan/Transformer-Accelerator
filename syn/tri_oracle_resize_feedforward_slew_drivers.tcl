# Resize only four freshly measured, unique, unprotected data drivers.
source syn/tri_oracle_physical_config.tcl
read_db $out/routed.db
source syn/tri_oracle_feedforward_postroute_settings.tcl
source syn/tri_oracle_signal_repair_targets.tcl
source syn/tri_oracle_slew_resize_policy.tcl
source syn/tri_oracle_require_clean_placement.tcl
set tag postroute_driver_slew_fix
if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ni {postroute_driver_slew_fix postroute_driver_slew_local}} {error "Unexpected driver-resize stage"}
set tag $::env(TRI_ORACLE_PHYSICAL_STAGE)
if {![file isdirectory $out/${tag}_input_exact.db]} {error "Exact independent predecessor backup required"}

proc tri_oracle_capture_resize_inventory {filename} {
    set instances [get_db insts]
    if {[llength $instances] == 0 || [llength $instances] > 1000000} {error "Unexpected physical inventory size"}
    set channel [open $filename {WRONLY CREAT EXCL}]
    set inventory [dict create]
    try {
        puts $channel "instance\tbase_cell\tlocation\torientation"
        foreach inst $instances {
            set name [get_db $inst .name]
            if {[dict exists $inventory $name] || [regexp {[\t\r\n]} $name]} {error "Ambiguous physical instance name"}
            set row [list [get_db $inst .base_cell.name] [get_db $inst .location] [get_db $inst .orient]]
            dict set inventory $name $row
            puts $channel [join [list $name {*}$row] \t]
        }
    } finally {close $channel}
    return $inventory
}

set protected [get_db insts *TRI_ENDPOINT_HOLD_*]
if {[llength $protected] != 74} {error "All74 endpoint delays must be preserved"}
foreach inst $protected {
    if {![get_db $inst .dont_touch]} {error "Endpoint-delay protection missing"}
}
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
time_design -post_route -drv_report -expanded_views -report_dir $out/${tag}_before -report_prefix $tag
set victims [tri_oracle_route_slew_targets [exec gzip -dc $out/${tag}_before/${tag}.tran.gz]]
set measured [dict create \
    FE_DBTN35038_n_34794 {FE_OFC1809_n_34794 INVD1P25BWP12T40P140} \
    FE_OFN37796_core_result_data_864 {FE_OFC3210_core_result_data_864 BUFFD1BWP12T40P140} \
    {core/bank_mask[116]} {{core/auxiliary[1].masks/g6788} OR4D0BWP12T40P140} \
    d_engine/FE_OFN692568_n_34806 {d_engine/FE_OFC10650_n_34806 INVD1P25BWP12T40P140}]
if {$victims ne [lsort [dict keys $measured]]} {error "Fresh slew victims differ from the four admitted nets"}
set replacements [dict create]
set targets [dict create]
set channel [open $out/${tag}_admission.tsv w]
try {
    puts $channel "net\tinstance\toriginal_cell\treplacement_cell\tmodule_instances\tplacement_status\tclock_tree_placement"
    foreach name $victims {
        set net [get_db nets $name]
        if {[llength $net] != 1 || [get_db $net .name] ne $name} {error "Missing exact victim net: $name"}
        tri_oracle_route_require_data_net $name [get_db $net .is_clock] [get_db $net .is_power] [get_db $net .is_ground]
        if {[get_db $net .dont_touch] || [llength [get_db $net .driver_ports]] != 0} {error "Preserved or external driver net: $name"}
        set driver [get_db $net .driver_pins]
        if {[llength $driver] != 1 || [get_db $driver .direction] ne {out}} {error "Expected one ordinary output driver"}
        set inst [get_db $driver .inst]
        set inst_name [get_db $inst .name]
        set cell [get_db $inst .base_cell.name]
        lassign [dict get $measured $name] expected_inst expected_cell
        if {$inst_name ne $expected_inst || $cell ne $expected_cell} {error "Actual driver differs from cold-qualified measurement"}
        if {[get_db $inst .dont_touch_effective]} {error "Protected driver cannot be resized: $inst_name"}
        if {[get_db $inst .place_status_effective] ne {placed} || [get_db $inst .place_status_cts] ne {unset}} {
            error "Fixed or clock-tree-preserved driver: $inst_name"
        }
        set parent [get_db $inst .parent]
        if {[get_db $parent .name] eq $top} {
            set sharing 1
        } else {
            set sharing [llength [get_db [get_db $parent .module] .hinsts]]
        }
        if {$sharing != 1} {error "Shared-module resize is outside this bounded repair"}
        set replacement [tri_oracle_slew_resize_cell $cell]
        set master [get_db base_cells $replacement]
        if {[llength $master] != 1 || [get_db $master .dont_use]} {error "Replacement master is absent or disallowed"}
        if {[dict exists $targets $inst_name]} {error "Two victims unexpectedly share a driver"}
        dict set targets $inst_name $inst
        dict set replacements $inst_name $replacement
        puts $channel [join [list $name $inst_name $cell $replacement $sharing [get_db $inst .place_status_effective] [get_db $inst .place_status_cts]] \t]
        flush $channel
    }
} finally {close $channel}
set before [tri_oracle_capture_resize_inventory $out/${tag}_before_inventory.tsv]
if {[dict size $before] != 710628} {error "Unexpected predecessor cell count"}
set_db eco_honor_dont_touch true
set_db eco_honor_dont_use true
set_db eco_honor_fixed_status true
set_db eco_check_logical_equivalence true
set_db eco_update_timing false
set_db eco_refine_place false
set_db eco_batch_mode true
set status [catch {
    dict for {name replacement} $replacements {eco_update_cell -insts $name -cells $replacement}
} message options]
set_db eco_batch_mode false
if {$status} {return -options $options $message}
dict for {name replacement} $replacements {
    set inst [get_db insts $name]
    if {[llength $inst] != 1 || [get_db $inst .base_cell.name] ne $replacement} {error "Native resize did not produce the admitted cell"}
    if {[get_db $inst .place_status_effective] ne {placed} || [get_db $inst .place_status_cts] ne {unset}} {
        error "Resize unexpectedly changed the target's placement status"
    }
}
set current [tri_oracle_capture_resize_inventory $out/${tag}_resized_inventory.tsv]
tri_oracle_require_slew_resize_inventory $before $current $replacements
unset current
# These are existing placed cells. Unplacing them caused the ECO placer to
# relocate them50-405um. Detailed placement legalizes only the four named cells
# and leaves legal placements alone; no wire-length optimization is requested.
place_detail -eco true -inst [dict keys $replacements] -wire_length_reclaim false
set current [tri_oracle_capture_resize_inventory $out/${tag}_legalized_inventory.tsv]
tri_oracle_require_slew_resize_inventory $before $current $replacements
unset current
check_place > $out/${tag}_placement.rpt
tri_oracle_require_clean_placement $out/${tag}_placement.rpt
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
set saved_timing [get_db route_with_timing_driven]
set saved_si [get_db route_with_si_driven]
set_db route_with_timing_driven false
set_db route_with_si_driven false
set status [catch {
    redirect $out/${tag}_router.rpt {
        puts "TRI_ORACLE_LOCAL_ECO_MODE [get_db route_with_timing_driven] [get_db route_with_si_driven]"
        route_eco
    } -tee
} message options]
set_db route_with_timing_driven $saved_timing
set_db route_with_si_driven $saved_si
tri_oracle_reset_router_timing
if {$status} {return -options $options $message}
set geometry [tri_oracle_require_geometric_eco_trace $out/${tag}_router.rpt]
set current [tri_oracle_capture_resize_inventory $out/${tag}_after_inventory.tsv]
set scope [tri_oracle_require_slew_resize_inventory $before $current $replacements true]
unset before current
set channel [open $out/${tag}_scope.rpt w]
puts $channel $scope
puts $channel $geometry
close $channel
foreach inst [get_db insts *TRI_ENDPOINT_HOLD_*] {
    if {![get_db $inst .dont_touch]} {error "Routing changed endpoint-delay protection"}
}
if {[llength [get_db insts *TRI_ENDPOINT_HOLD_*]] != 74} {error "Routing changed endpoint-delay inventory"}
check_place > $out/${tag}_placement_after_route.rpt
tri_oracle_require_clean_placement $out/${tag}_placement_after_route.rpt
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_FEEDFORWARD_DRIVER_SIZING_CHECKPOINT_WRITTEN"
report_timing -view setup_slow > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
check_drc -out_file $out/${tag}_drc.rpt
check_antenna -out_file $out/${tag}_antenna.rpt
check_connectivity -type all -out_file $out/${tag}_connectivity.rpt
time_design -post_route -drv_report -expanded_views -report_dir $out/${tag}_after -report_prefix $tag
puts "TRI_ORACLE_FEEDFORWARD_DRIVER_SIZING_COMMANDS_FINISHED"
exit
