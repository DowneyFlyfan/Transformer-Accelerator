proc tri_oracle_joined_name {raw} {
    return [string map [list "\\" "" " " "" "/" "."] $raw]
}

proc tri_oracle_joined_memories {} {
    set result [dict create]
    foreach inst [get_db insts -if {.base_cell.name =~ TS*N28HPCPSVTA*}] {
        set name [tri_oracle_joined_name [get_db $inst .name]]
        if {[dict exists $result $name]} {error "Duplicate memory instance $name"}
        dict set result $name $inst
    }
    return $result
}

proc tri_oracle_joined_check_macros {insts poses report} {
    set stream [open $report w]
    try {
        foreach name [lsort [dict keys $poses]] {
            lassign [dict get $poses $name] master x y orient
            set inst [dict get $insts $name]
            lassign [join [get_db $inst .location] " "] native_x native_y
            if {[get_db $inst .base_cell.name] ne $master ||
                [get_db $inst .place_status] ne "fixed" || ![get_db $inst .is_place_halo] ||
                [get_db $inst .orient] ne $orient || abs($native_x - $x) > 0.0001 || abs($native_y - $y) > 0.0001} {
                error "Memory pose or halo differs from the verified seed: $name"
            }
            puts $stream "$name\t$master\t$native_x\t$native_y\t$orient"
        }
    } finally {
        close $stream
    }
}

proc tri_oracle_joined_floorplan {seed site} {
    lassign [dict get $seed die] width height
    set margin [dict get $seed margin]
    set halo [dict get $seed halo]
    if {$width != 3600 || $height != 3600 || $margin != 20 || $halo != 5} {error "Unexpected die or macro margins"}
    create_floorplan -site $site -no_snap_to_grid -die_size [list $width $height $margin $margin $margin $margin]
    set insts [tri_oracle_joined_memories]
    set poses [dict get $seed poses]
    if {[dict size $poses] != 631 || [lsort [dict keys $insts]] ne [lsort [dict keys $poses]]} {
        error "Native memory inventory differs from the replay-bound seed"
    }
    set masters [dict create]
    dict for {name pose} $poses {
        lassign $pose master x y orient
        set inst [dict get $insts $name]
        if {[get_db $inst .base_cell.name] ne $master || $orient ne "r0"} {error "Wrong macro master or orientation: $name"}
        place_inst $inst $x $y $orient -fixed
        dict set masters $master 1
    }
    if {[dict size $masters] != 6} {error "Unexpected set of compiled memory masters"}
    foreach master [dict keys $masters] {
        create_place_halo -halo_deltas [list $halo $halo $halo $halo] -snap_to_site -cell $master
    }
    tri_oracle_joined_check_macros $insts $poses floorplan_macros.tsv

    connect_global_net VDD -type pg_pin -pin_base_name VDD -all
    connect_global_net VSS -type pg_pin -pin_base_name VSS -all
    set pins [lsort -unique [get_db ports .name]]
    if {[llength $pins] != 12365} {error "Unexpected boundary pin count"}
    for {set index 0} {$index < 4} {incr index} {
        set first [expr {$index * [llength $pins] / 4}]
        set last [expr {($index + 1) * [llength $pins] / 4 - 1}]
        edit_pin -pin [lrange $pins $first $last] -side [lindex {left right top bottom} $index] \
            -spread_type side -layer [lindex {M4 M4 M5 M5} $index] -snap track
    }
}

if {[catch {
    set inputs [source $::env(TRI_ORACLE_JOINED_PLACEMENT_INPUTS)]
    set top [dict get $inputs top]
    set_multi_cpu_usage -local_cpu [dict get $inputs cpus]
    set_db design_process_node 28
    set_db init_power_nets {VDD}
    set_db init_ground_nets {VSS}
    read_mmmc [dict get $inputs timing]
    read_physical -lefs [dict get $inputs abstracts]
    read_netlist [dict get $inputs netlist] -top $top
    init_design
    if {[get_db current_design .name] ne $top} {error "Wrong mapped design imported"}
    set_db delaycal_enable_high_fanout false
    set_db ui_precision_timing 6
    set seed [source [dict get $inputs macro_seed]]
    tri_oracle_joined_floorplan $seed [dict get $inputs site]

    set_db place_global_timing_effort medium
    set_db place_design_floorplan_mode true
    place_design -no_pre_place_opt
    set_db place_design_floorplan_mode false
    place_detail
    tri_oracle_joined_check_macros [tri_oracle_joined_memories] [dict get $seed poses] placed_macros.tsv
    check_place > placement.rpt
    source [dict get $inputs placement_checker]
    tri_oracle_require_clean_placement placement.rpt
    if {[get_db delaycal_enable_high_fanout]} {error "High fanout delay substitution enabled"}
    report_timing -view setup_slow -check_type setup -max_paths 15 > setup_slow.rpt
    report_timing -view setup_typ -check_type setup -max_paths 15 > setup_typ.rpt
    report_timing -view hold_fast -early -max_paths 15 > hold_fast.rpt
    write_netlist placed.v -exclude_leaf_cells
    write_def placed.def
    write_db placed.db
    puts TRI_ORACLE_JOINED_PLACEMENT_PASS
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
