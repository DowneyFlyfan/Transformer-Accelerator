# Compare the cold graphs after independently checking the grouped_active tree.
proc active_graph_ignore {ignored_var driver targets} {
    upvar 1 $ignored_var ignored
    set pin [get_db pins $driver]
    set net [get_db $pin .net]
    set loads [lsort $targets]
    if {[llength $pin] != 1 || [llength $net] != 1 || [dict exists $ignored $driver] ||
        [get_db $net .driver_pins.name] ne $driver || [get_db $net .driver_ports.name] ne {} ||
        [get_db $net .load_ports.name] ne {} || [get_db $net .constant] ne "no_constant" ||
        [get_db $net .is_clock] || [get_db $net .is_power] || [get_db $net .is_ground] ||
        [lsort [get_db $net .load_pins.name]] ne $loads} {
        error "Unexpected grouped_active topology at $driver"
    }
    dict set ignored $driver $loads
}

if {[catch {
    set mode $::env(TRI_ORACLE_RESET_MODE)
    set_multi_cpu_usage -local_cpu 8
    read_db $::env(TRI_ORACLE_RESET_CHECKPOINT)
    if {$mode ni {parent candidate} ||
        [get_db current_design .name] ne "tri_oracle_chip_command_layer_parallel_chip"} {
        error "Wrong grouped_active graph input"
    }
    set source [open $::env(TRI_ORACLE_RESET_PLAN)]
    if {[gets $source] ne "id\tmaster\tx_um\ty_um\tchildren\tpins"} {error "Wrong active plan format"}
    set ledger [open $::env(TRI_ACTIVE_DRIVER_LEDGER)]
    set ids [dict create]
    while {[gets $ledger row] >= 0} {
        lassign [split $row \t] driver count
        if {$driver eq "batch/g166179/Z"} {continue}
        if {![regexp {(^|/)TRI_GROUPED_ACTIVE_([0-9]+)/Z$} $driver -> prefix id] ||
            [dict exists $ids $id]} {error "Invalid active buffer ledger: $driver"}
        dict set ids $id [file dirname $driver]
    }
    close $ledger
    if {[dict size $ids] != 712} {error "Wrong active buffer ledger size"}
    set original [dict create]
    set parents [dict create]
    set ignored [dict create]
    set next 0
    while {[gets $source row] >= 0} {
        lassign [split $row \t] id master x y children pins
        if {$id != $next || ($children eq "") == ($pins eq "")} {error "Invalid active plan row $id"}
        incr next
        set name [dict get $ids $id]
        set targets $pins
        foreach pin $pins {
            if {[dict exists $original $pin]} {error "Repeated active terminal: $pin"}
            dict set original $pin 1
        }
        foreach child $children {
            if {$child < 0 || $child >= $id || [dict exists $parents $child]} {error "Bad child $child"}
            dict set parents $child $id
            lappend targets "[dict get $ids $child]/I"
        }
        if {$mode eq "candidate"} {
            set cell [get_db insts $name]
            if {[get_db $cell .name] ne $name || [get_db $cell .base_cell.name] ne $master ||
                ![get_db $cell .base_cell.is_buffer]} {error "Wrong active buffer $name"}
            active_graph_ignore ignored "$name/Z" $targets
        }
    }
    close $source
    if {$next != 712 || [dict size $parents] != 711 || [dict size $original] != 17013} {
        error "Incomplete grouped_active plan"
    }
    set root batch/g166179/Z
    if {$mode eq "parent"} {
        active_graph_ignore ignored $root [dict keys $original]
    } else {
        active_graph_ignore ignored $root [list "[dict get $ids 711]/I"]
    }

    set out [open graph.tsv {WRONLY CREAT EXCL}]
    fconfigure $out -buffersize 1048576
    foreach port [get_db ports] {
        puts $out [join [list port [get_db $port .name] [get_db $port .direction]] \t]
    }
    set count 0
    set removed [dict create]
    foreach net [get_db nets] {
        # An inserted hierarchical repeater's output can have different
        # database objects in pin lookup and flat net enumeration.
        set drivers [get_db $net .driver_pins.name]
        set driver [lindex $drivers 0]
        if {[llength $drivers] == 1 && [dict exists $ignored $driver]} {
            if {[dict exists $removed $driver] || [get_db $net .constant] ne "no_constant" ||
                [get_db $net .is_power] || [get_db $net .is_ground] || [get_db $net .is_clock] ||
                [get_db $net .driver_ports.name] ne {} || [get_db $net .load_ports.name] ne {} ||
                [lsort [get_db $net .load_pins.name]] ne [dict get $ignored $driver]} {
                error "Unexpected flat grouped_active net at $driver"
            }
            dict set removed $driver 1
            continue
        }
        puts $out [join [list net [get_db $net .constant] [get_db $net .is_power] [get_db $net .is_ground] \
            [lsort $drivers] [lsort [get_db $net .driver_ports.name]] \
            [lsort [get_db $net .load_pins.name]] [lsort [get_db $net .load_ports.name]]] \t]
        incr count
        if {$count % 500000 == 0} {puts "GROUPED_ACTIVE_GRAPH_NETS $mode $count"}
    }
    foreach pin [get_db pins -if {.constant != no_constant}] {
        puts $out [join [list constant_pin [get_db $pin .name] [get_db $pin .constant]] \t]
    }
    close $out
    if {[dict size $removed] != [dict size $ignored]} {error "Missing active nets during graph enumeration"}
    puts "GROUPED_ACTIVE_GRAPH_COMPLETE $mode $count [dict size $removed] [dict size $original]"
    puts "TRI_ORACLE_GROUPED_RESET_${mode}_PASS"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
