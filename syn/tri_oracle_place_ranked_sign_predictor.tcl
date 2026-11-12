# Geometric placement and cold pre-route timing for the verified predictor.
set inputs [source $::env(TRI_RANKED_PHYSICAL_INPUTS)]
dict with inputs {}
source $checker
set_multi_cpu_usage -local_cpu 4

proc ranked_memory_poses {} {
    set inventory [dict create]
    foreach inst [get_db insts -if {.base_cell.name =~ TS*N28HPCPSVTA*}] {
        if {[get_db $inst .place_status] ne "fixed" || ![get_db $inst .is_place_halo]} {
            error "Ranked predictor macro lost its fixed pose or halo"
        }
        lassign [join [get_db $inst .location] " "] x y
        dict set inventory [get_db $inst .name] [list [get_db $inst .base_cell.name] $x $y [get_db $inst .orient]]
    }
    if {[dict size $inventory] != 6} {error "Ranked predictor requires six compiled memory instances"}
    return $inventory
}

proc ranked_export_geometry {} {
    set stream [open macro_poses.tsv w]
    dict for {name pose} [ranked_memory_poses] {
        puts $stream [join [linsert $pose 0 $name] "\t"]
    }
    close $stream
    check_place > placement.rpt
    puts "RANKED_PREDICTOR_PLACEMENT [tri_oracle_require_clean_placement placement.rpt]"
}

proc ranked_place_signal_pins {} {
    set sides [dict create left {} right {} top {} bottom {}]
    foreach port [lsort -dictionary [get_db ports .name]] {
        set name [string map [list "\\" "" " " ""] $port]
        if {[regexp {^rsp_data\[([01])\]\[[0-9]+\]$} $name -> lane]} {
            set side [lindex {left right} $lane]
        } elseif {[regexp {^strip_(request|response)\[} $name]} {
            set side top
        } else {
            set side bottom
        }
        dict lappend sides $side $port
    }
    foreach side {left right top} expected {512 512 646} {
        if {[llength [dict get $sides $side]] != $expected} {
            error "Unexpected ranked predictor signal count on $side: [llength [dict get $sides $side]]"
        }
    }
    foreach side {left right top bottom} layer {M4 M4 M5 M5} {
        edit_pin -pin [dict get $sides $side] -side $side -spread_type side -layer $layer -snap track
    }
    foreach port [get_db ports] {
        if {[llength [get_db $port .physical_pins]] != 1 ||
            [get_db $port .place_status] ni {placed fixed}} {
            error "Ranked predictor signal pin is missing: [get_db $port .name]"
        }
    }
    puts "RANKED_PREDICTOR_PINS [llength [get_db ports]]"
}

set stage $::env(TRI_RANKED_PHYSICAL_STAGE)
if {$stage eq "place"} {
    set_db design_process_node 28
    set_db init_power_nets {VDD}
    set_db init_ground_nets {VSS}
    read_mmmc $mmmc
    read_physical -lefs $lefs
    read_netlist $netlist -top $top
    init_design
    if {[get_db current_design .name] ne $top} {error "Wrong ranked predictor import"}
    create_floorplan -site core12T -no_snap_to_grid -die_size {410 320 10 10 10 10}

    set cache TS5N28HPCPSVTA32X128M2FW
    set metadata TS5N28HPCPSVTA512X64M4F
    set layouts [dict create \
        lower_metadata [list $metadata 20 60 r0] \
        upper_metadata [list $metadata 128 60 my] \
        {sign_cache_storage_banks[0].slices[0].data_memory} [list $cache 208 60 r0] \
        {sign_cache_storage_banks[0].slices[1].data_memory} [list $cache 263 60 my] \
        {sign_cache_storage_banks[0].slices[2].data_memory} [list $cache 297 60 r0] \
        {sign_cache_storage_banks[0].slices[3].data_memory} [list $cache 352 60 my]]
    foreach inst [get_db insts -if {.base_cell.name =~ TS*N28HPCPSVTA*}] {
        set key [string map [list "\\" "" " " ""] [get_db $inst .name]]
        lassign [dict get $layouts $key] master x y orient
        if {[get_db $inst .base_cell.name] ne $master} {error "Unexpected memory master: $key"}
        place_inst $inst $x $y $orient -fixed
    }
    foreach master [list $cache $metadata] {
        create_place_halo -halo_deltas {4 4 4 4} -snap_to_site -cell $master
    }
    connect_global_net VDD -type pg_pin -pin_base_name VDD -all
    connect_global_net VSS -type pg_pin -pin_base_name VSS -all
    set poses [ranked_memory_poses]
    ranked_place_signal_pins

    set_analysis_view -setup {setup_slow} -hold {setup_slow}
    set_db place_global_timing_effort medium
    set_db place_design_floorplan_mode true
    place_design -no_pre_place_opt
    set_db place_design_floorplan_mode false
    place_detail
    if {[ranked_memory_poses] ne $poses} {error "A fixed macro moved during placement"}
    ranked_export_geometry
    set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
    report_area > area.rpt
    write_netlist placed.v -exclude_leaf_cells
    write_def placed.def
    write_db placed.db
    puts RANKED_PREDICTOR_PLACED
    exit
}

if {$stage ni {extract report}} {error "Unknown ranked predictor stage: $stage"}
read_db $out/place/placed.db
set_multi_cpu_usage -local_cpu 4
if {[get_db current_design .name] ne $top} {error "Wrong cold ranked predictor database"}
ranked_export_geometry
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db timing_analysis_type single
set_db delaycal_enable_high_fanout false
puts "RANKED_PREDICTOR_TIMING_MODE [get_db timing_analysis_type] [get_db delaycal_enable_high_fanout]"
if {$stage eq "extract"} {
    set_db route_early_global_effort_level low
    route_early_global
}
foreach view {setup_slow setup_typ hold_fast} corner {rc_slow rc_typ rc_fast} {
    set_analysis_view -setup [list $view] -hold [list $view]
    if {$stage eq "extract"} {
        extract_rc
        write_parasitics -spef_file $view.spef -rc_corner $corner
        puts "RANKED_PREDICTOR_EXTRACTED $view"
    } else {
        read_spef $out/extract/$view.spef -rc_corner $corner
        report_annotated_parasitics -view $view > ${view}_annotation.rpt
        if {$view eq "hold_fast"} {
            report_timing -view $view -early -max_paths 15 > $view.rpt
        } else {
            report_timing -view $view -check_type setup -max_paths 15 > $view.rpt
        }
        puts "RANKED_PREDICTOR_REPORTED $view"
    }
}
exit
