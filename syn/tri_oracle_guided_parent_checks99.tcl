# Checks shared by guidance optimization and independent full-model restore.
proc guided85_macros {} {
    set component tri_oracle_sram_memory_compute
    set cores [get_db insts -if {.base_cell.name == tri_oracle_sram_memory_compute}]
    set banks [get_db insts -if {.base_cell.name == TS6N28HPCPSVTA16X128M2F}]
    if {[llength $cores] != 20 || [llength $banks] != 40} {error "GUIDED85_WRONG_MACRO_COUNTS"}
    set inventory [dict create]
    set indexes [dict create]
    foreach instance [concat $cores $banks] {
        set name [get_db $instance .name]
        set master [get_db $instance .base_cell.name]
        if {$master eq $component} {
            if {![regexp {clusters\[([0-9]+)\]\.unit/cluster/implementation/cores\[([0-9]+)\]$} $name -> cluster core] ||
                $cluster >= 5 || $core >= 4 || [llength [get_db $instance .pins]] != 3158} {
                error "GUIDED85_WRONG_CORE_INTERFACE: $name"
            }
            set key core:$cluster:$core
        } else {
            if {![regexp {clusters\[([0-9]+)\]\.unit/cluster/implementation/aggregate_memory\[([0-9]+)\]$} $name -> cluster bank] ||
                $cluster >= 5 || $bank >= 8 || [llength [get_db $instance .pins]] != 268} {
                error "GUIDED85_WRONG_AGGREGATE_INTERFACE: $name"
            }
            set key bank:$cluster:$bank
        }
        if {[dict exists $indexes $key]} {error "GUIDED85_DUPLICATE_MACRO: $key"}
        dict set indexes $key 1
        if {[get_db $instance .place_status] ne "fixed" || [get_db $instance .orient] ne "r0" ||
            ![get_db $instance .dont_touch]} {error "GUIDED85_UNPROTECTED_MACRO: $name"}
        dict set inventory $name [join [list $name $master [get_db $instance .location] \
            [get_db $instance .orient] [get_db $instance .place_status] [llength [get_db $instance .pins]]] "\t"]
    }
    set rows [list]
    foreach name [lsort [dict keys $inventory]] {lappend rows [dict get $inventory $name]}
    return [join $rows "\n"]
}

proc guided85_snapshot {filename expected} {
    set counts [dict create]
    set file [open $filename w]
    puts $file "instance\tmaster\tlocation\torientation"
    foreach instance [get_db insts] {
        set name [get_db $instance .name]
        if {![regexp {^(.*clusters\[[0-9]+\]\.unit/cluster/implementation/cores\[[0-9]+\])/(.+)$} $name -> prefix local]} {continue}
        dict incr counts $prefix
        puts $file "$name\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]"
    }
    close $file
    if {[dict size $counts] != 20} {error "GUIDED85_INCOMPLETE_CORE_SET"}
    dict for {prefix count} $counts {
        if {$count != $expected} {error "GUIDED85_WRONG_CORE_CELLS: $prefix $count $expected"}
    }
    foreach master {TS5N28HPCPSVTA32X128M2FW TS5N28HPCPSVTA512X64M4F TS6N28HPCPSVTA16X128M2F} expected_count {360 40 200} {
        if {[llength [get_db insts -if ".base_cell.name == $master"]] != $expected_count} {
            error "GUIDED85_WRONG_MEMORY_COUNT: $master"
        }
    }
    return $counts
}

proc guided85_parent_legal {report} {
    check_place > $report
    foreach instance [get_db insts] {
        if {[get_db $instance .place_status] ni {placed fixed}} {
            error "GUIDED85_UNPLACED_INSTANCE: [get_db $instance .name]"
        }
    }
}

proc guided85_registered_reset {root out} {
    source $root/syn/tri_oracle_registered_reset_trace98.tcl
    source $root/syn/tri_oracle_check_registered_reset_fabric.tcl
    set masters [exec python3 -B -c {import json,sys; print(" ".join(json.load(open(sys.argv[1]))["flip_flop_cells"]))} $root/records/registered_reset34_sequential_masters.json]
    tri_oracle_require_parent_registered_resets $masters $out/registered_reset_roots.tsv
}
