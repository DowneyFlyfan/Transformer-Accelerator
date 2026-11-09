# Signal-net names may change; endpoint roles and leaf identities may not.
proc tri215_snapshot {directory tag} {
    set cells [open $directory/[set tag]_cells.tsv w]
    puts $cells "instance\tmaster\tlocation\torientation\tstatus\tdont_touch"
    set count 0
    foreach instance [get_db insts] {
        puts $cells [join [list [get_db $instance .name] [get_db $instance .base_cell.name] \
            [get_db $instance .location] [get_db $instance .orient] \
            [get_db $instance .place_status] [get_db $instance .dont_touch]] "\t"]
        incr count
    }
    close $cells
    set ports [open $directory/[set tag]_ports.tsv w]
    puts $ports "port\tdirection"
    foreach port [get_db ports] {
        if {[get_db $port .direction] eq "out" && [llength [get_db $port .net]] != 1} {
            error "TRI215_UNSUPPORTED_OUTPUT_WITHOUT_NET [get_db $port .name]"
        }
        puts $ports "[get_db $port .name]\t[get_db $port .direction]"
    }
    close $ports
    set nets [open $directory/[set tag]_nets.tsv w]
    puts $nets "constant\tpower\tground\tdriver_pins\tdriver_ports\tload_pins\tload_ports"
    foreach net [get_db nets] {
        puts $nets [join [list [get_db $net .constant] [get_db $net .is_power] [get_db $net .is_ground] \
            [lsort [get_db $net .driver_pins.name]] \
            [lsort [get_db $net .driver_ports.name]] \
            [lsort [get_db $net .load_pins.name]] \
            [lsort [get_db $net .load_ports.name]]] "\t"]
    }
    close $nets
    set pins [open $directory/[set tag]_pins.tsv w]
    puts $pins "pin\tdirect_constant"
    foreach pin [get_db pins -if {.constant != no_constant}] {
        puts $pins "[get_db $pin .name]\t[get_db $pin .constant]"
    }
    close $pins
    return $count
}
proc tri215_require_equal {directory reference candidate} {
    foreach kind {cells ports nets pins} {
        foreach tag [list $reference $candidate] {
            set filename $directory/[set tag]_[set kind].tsv
            exec env LC_ALL=C sort -S 64M -T $directory -o $filename.sorted $filename
        }
        if {[catch {exec cmp -s $directory/[set reference]_[set kind].tsv.sorted \
                $directory/[set candidate]_[set kind].tsv.sorted}]} {
            error "TRI215_SIGNAL_GRAPH_CHANGED $kind"
        }
    }
}
