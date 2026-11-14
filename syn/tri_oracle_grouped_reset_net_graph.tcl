# Export the flattened signal graph with the planned reset trees removed.
# These nets are checked independently by the cold tree and original-root checks.
if {[catch {
    set_multi_cpu_usage -local_cpu 8
    read_db $::env(TRI_ORACLE_RESET_CHECKPOINT)
    set mode $::env(TRI_ORACLE_RESET_MODE)
    if {$mode ni {original buffered} ||
        [get_db current_design .name] ne "tri_oracle_chip_command_layer_parallel_chip"} {
        error "Wrong reset graph input"
    }
    set ignored [dict create]
    set tree_loads 0
    for {set group 0} {$group < 5} {incr group} {
        set owner grouped_$group
        set source [open $::env(TRI_ORACLE_RESET_PLAN)/grouped_$group.tsv]
        if {[gets $source] ne "id\tmaster\tx_um\ty_um\tchildren\tpins"} {error "Wrong reset plan header"}
        set loads {}
        set drivers [list "$owner/g83737/ZN"]
        set expected [dict create]
        set next_id 0
        while {[gets $source row] >= 0} {
            lassign [split $row \t] id master x y children pins
            if {$id != $next_id} {error "Out-of-order buffer plan"}
            set name "$owner/TRI_GROUPED_RESET_${group}_$id"
            incr next_id
            lappend drivers "$name/Z"
            if {$children eq ""} {
                set targets [split $pins " "]
                lappend loads {*}$targets
            } else {
                set targets {}
                foreach child $children {
                    if {$child < 0 || $child >= $id} {error "Cyclic or unknown branch"}
                    lappend targets "$owner/TRI_GROUPED_RESET_${group}_$child/I"
                }
            }
            dict set expected "$name/Z" $targets
            if {$mode eq "buffered" &&
                [get_db [get_db insts $name] .base_cell.name] ne $master} {error "Wrong buffer: $name"}
        }
        close $source
        if {$next_id != 774 || [llength $loads] != 18484 || [llength [lsort -unique $loads]] != 18484} {
            error "Wrong planned reset tree size in $owner"
        }
        set root [lindex $drivers 0]
        if {$mode eq "original"} {
            set drivers [list $root]
            set expected [dict create $root $loads]
        } else {
            dict set expected $root [list "$owner/TRI_GROUPED_RESET_${group}_773/I"]
        }
        foreach driver $drivers {
            set net [get_db [get_db pins $driver] .net]
            if {[llength $net] != 1 ||
                [get_db $net .driver_pins.name] ne $driver || [get_db $net .driver_ports.name] ne {} ||
                [get_db $net .load_ports.name] ne {} || [get_db $net .constant] ne "no_constant" ||
                [get_db $net .is_power] || [get_db $net .is_ground] ||
                [lsort [get_db $net .load_pins.name]] ne [lsort [dict get $expected $driver]] ||
                [dict exists $ignored $net]} {error "Unexpected reset net at $driver"}
            dict set ignored $net 1
        }
        incr tree_loads [llength $loads]
    }
    set out [open graph.tsv {WRONLY CREAT EXCL}]
    fconfigure $out -buffersize 1048576
    foreach port [get_db ports] {
        puts $out [join [list port [get_db $port .name] [get_db $port .direction]] \t]
    }
    set count 0
    set removed 0
    foreach net [get_db nets] {
        if {[dict exists $ignored $net]} {
            incr removed
            continue
        }
        puts $out [join [list net [get_db $net .constant] [get_db $net .is_power] [get_db $net .is_ground] \
            [lsort [get_db $net .driver_pins.name]] [lsort [get_db $net .driver_ports.name]] \
            [lsort [get_db $net .load_pins.name]] [lsort [get_db $net .load_ports.name]]] \t]
        incr count
        if {$count % 500000 == 0} {puts "RESET_GRAPH_NETS $mode $count"}
    }
    foreach pin [get_db pins -if {.constant != no_constant}] {
        puts $out [join [list constant_pin [get_db $pin .name] [get_db $pin .constant]] \t]
    }
    close $out
    if {$removed != [dict size $ignored]} {error "Reset nets missing from graph enumeration"}
    puts "RESET_GRAPH_COMPLETE $mode $count $removed $tree_loads"
    puts "TRI_ORACLE_GROUPED_RESET_${mode}_PASS"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
