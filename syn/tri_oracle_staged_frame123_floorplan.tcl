# Local coordinates informed by Figure31.6.7, using the actual core44 footprints.
# Four corner clusters contain2-by-2 cores; cluster4 occupies the middle row.
# These are reconstruction coordinates, not the authors' original placement data.
proc tri_oracle_place_staged_frame123_macros {inventory_path} {
    set cores [get_db insts -if {.base_cell.name == tri_oracle_sram_memory_compute}]
    set banks [get_db insts -if {.base_cell.name == TS6N28HPCPSVTA16X128M2F}]
    if {[llength $cores] != 20 || [llength $banks] != 40} {
        error "PREDICTED_FLOORPLAN_INVENTORY: expected20 cores and40 aggregate banks, observed [llength $cores] and[llength $banks]"
    }
    set placements [dict create]
    foreach instance $cores {
        set name [get_db $instance .name]
        if {![regexp {clusters\[([0-9]+)\]\.cluster/cores\[([0-9]+)\]$} $name -> cluster core] ||
            $cluster >= 5 || $core >= 4 || [llength [get_db $instance .pins]] != 3158} {
            error "PREDICTED_FLOORPLAN_INVENTORY: unexpected core interface or instance: $name"
        }
        set key core:$cluster:$core
        if {[dict exists $placements $key]} {
            error "PREDICTED_FLOORPLAN_INVENTORY: duplicated cluster/core index: $name"
        }
        if {$cluster == 4} {
            set column $core
            set row 2
        } else {
            set column [expr {($cluster % 2)*2 + ($core % 2)}]
            set row [expr {($cluster < 2 ? 3 : 0) + 1 - ($core / 2)}]
        }
        set x [expr {210.0 + $column*819.955}]
        set y [expr {45.0 + $row*710.0}]
        dict set placements $key [list $instance $x $y]
    }
    foreach instance $banks {
        set name [get_db $instance .name]
        if {![regexp {clusters\[([0-9]+)\]\.cluster/aggregate_memory\[([0-9]+)\]$} $name -> cluster bank] ||
            $cluster >= 5 || $bank >= 8 || [llength [get_db $instance .pins]] != 268} {
            error "PREDICTED_FLOORPLAN_INVENTORY: unexpected aggregate bank: $name"
        }
        set key bank:$cluster:$bank
        if {[dict exists $placements $key]} {
            error "PREDICTED_FLOORPLAN_INVENTORY: duplicated cluster/bank index: $name"
        }
        if {$cluster == 4} {
            set x [expr {30.0 + ($bank % 4)*41.88}]
            set y [expr {1480.0 + ($bank / 4)*337.515}]
        } else {
            set x [expr {($cluster % 2 == 0 ? 945.0 : 2585.0) + ($bank % 2)*40.0}]
            set y [expr {($cluster < 2 ? 2190.0 : 60.0) + ($bank / 2)*337.515}]
        }
        dict set placements $key [list $instance $x $y]
    }
    if {[dict size $placements] != 60} {
        error "PREDICTED_FLOORPLAN_INVENTORY: incomplete unique placement inventory"
    }
    set file [open $inventory_path w]
    puts $file "instance\tmaster\trequested_x_um\trequested_y_um\tactual_location\torientation\tstatus\tsignal_pins"
    foreach key [lsort [dict keys $placements]] {
        lassign [dict get $placements $key] instance x y
        place_inst $instance $x $y r0 -fixed
        puts $file "[get_db $instance .name]\t[get_db $instance .base_cell.name]\t$x\t$y\t[get_db $instance .location]\t[get_db $instance .orient]\t[get_db $instance .place_status]\t[llength [get_db $instance .pins]]"
    }
    close $file
    return [dict size $placements]
}
