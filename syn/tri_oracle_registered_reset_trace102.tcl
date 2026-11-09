# Version102 additionally admits the five all-corner/Verilog-proven BUFFXD identities.
# Follow actual native reset connectivity through buffers and flip-flop outputs.
# Sequential master names come from the supplied Liberty/Verilog cross-check.
namespace eval tri_oracle_registered_reset34 {
    variable masters
    variable memo
    variable busy
    variable edges
    variable root_port
}

proc tri_oracle_registered_reset34::walk {net} {
    variable masters
    variable memo
    variable busy
    variable edges
    variable root_port
    if {[llength $net] != 1} {error "REGISTERED_RESET34_MISSING_NET"}
    set name [get_db $net .name]
    if {[dict exists $memo $name]} {return [dict get $memo $name]}
    if {[dict exists $busy $name]} {error "REGISTERED_RESET34_CYCLE: $name"}
    dict set busy $name 1
    set pins [get_db $net .driver_pins]
    set ports [get_db $net .driver_ports]
    if {[llength $ports] != 0} {
        if {[llength $ports] != 1 || [llength $pins] != 0 || [lindex $ports 0] ne $root_port} {
            error "REGISTERED_RESET34_UNEXPECTED_EXTERNAL_ROOT: $name"
        }
        set result {}
        lappend edges [list $name external_port rst_n {}]
    } else {
        if {[llength $pins] != 1} {error "REGISTERED_RESET34_NONUNIQUE_DRIVER: $name"}
        set instance [get_db $pins .inst]
        set kind [get_db $instance .base_cell.name]
        set output [file tail [get_db $pins .base_pin.name]]
        if {[dict exists $masters $kind]} {
            if {$output ni {Q QN}} {error "REGISTERED_RESET34_UNSUPPORTED_REGISTER_OUTPUT: $name $kind $output"}
            set asynchronous {}
            set clocks {}
            foreach pin [get_db $instance .pins] {
                set base [file tail [get_db $pin .base_pin.name]]
                if {$base in {CDN SDN}} {lappend asynchronous $pin}
                if {$base eq "CP"} {lappend clocks $pin}
            }
            if {[llength $asynchronous] != 1 || [llength $clocks] != 1} {
                error "REGISTERED_RESET34_UNSUPPORTED_REGISTER_CONTROLS: $name $kind"
            }
            set parent_net [get_db $asynchronous .net]
            set clock_net [get_db $clocks .net]
            if {[llength $clock_net] != 1} {error "REGISTERED_RESET34_MISSING_REGISTER_CLOCK: $name"}
            set parent [walk $parent_net]
            set record [list [get_db $instance .name] $kind [get_db $clock_net .name]]
            set result [linsert $parent 0 $record]
            lappend edges [list $name $kind [get_db $pins .name] [get_db $parent_net .name]]
        } elseif {[regexp {^(BUFFD|CKBD|INVD|CKND)[0-9]+(P[0-9]+)?BWP12T40P140$} $kind] ||
                  $kind in {BUFFXD12BWP12T40P140 BUFFXD16BWP12T40P140 BUFFXD3BWP12T40P140 BUFFXD6BWP12T40P140 BUFFXD8BWP12T40P140}} {
            if {$output ni {Z ZN} || ($kind in {BUFFXD12BWP12T40P140 BUFFXD16BWP12T40P140 BUFFXD3BWP12T40P140 BUFFXD6BWP12T40P140 BUFFXD8BWP12T40P140} && $output ne "Z")} {
                error "REGISTERED_RESET34_UNSUPPORTED_BUFFER_OUTPUT: $name $kind $output"
            }
            set inputs {}
            foreach pin [get_db $instance .pins] {
                if {[file tail [get_db $pin .base_pin.name]] eq "I"} {lappend inputs $pin}
            }
            if {[llength $inputs] != 1} {error "REGISTERED_RESET34_MISSING_BUFFER_INPUT: $name"}
            set parent_net [get_db $inputs .net]
            set result [walk $parent_net]
            lappend edges [list $name $kind [get_db $pins .name] [get_db $parent_net .name]]
        } else {
            error "REGISTERED_RESET34_COMBINATIONAL_DRIVER: $name $kind [get_db $pins .name]"
        }
    }
    dict unset busy $name
    dict set memo $name $result
    return $result
}

proc tri_oracle_registered_reset_tree {endpoint_pins sequential_masters report_path} {
    if {[llength $endpoint_pins] == 0 || [llength $sequential_masters] == 0} {
        error "REGISTERED_RESET34_EMPTY_OBLIGATION"
    }
    namespace eval tri_oracle_registered_reset34 {
        set masters [dict create]
        set memo [dict create]
        set busy [dict create]
        set edges {}
        set root_port [get_db [get_ports rst_n]]
        if {[llength $root_port] != 1} {error "REGISTERED_RESET34_MISSING_EXTERNAL_RESET_PORT"}
        set root_port [lindex $root_port 0]
    }
    foreach master $sequential_masters {dict set tri_oracle_registered_reset34::masters $master 1}
    set minimum 2147483647
    set maximum 0
    set roots [dict create]
    set file [open $report_path w]
    puts $file "endpoint\tregistered_depth\tregistered_sources\tmasters\tclock_nets"
    foreach pin $endpoint_pins {
        set chain [tri_oracle_registered_reset34::walk [get_db $pin .net]]
        set depth [llength $chain]
        if {$depth == 0} {error "REGISTERED_RESET34_NO_REGISTERED_SOURCE: [get_db $pin .name]"}
        set names {}
        set kinds {}
        set clocks {}
        foreach ancestor $chain {
            lassign $ancestor name master clock
            lappend names $name
            lappend kinds $master
            lappend clocks $clock
            dict set roots $name $master
        }
        set minimum [expr {min($minimum,$depth)}]
        set maximum [expr {max($maximum,$depth)}]
        puts $file "[get_db $pin .name]\t$depth\t[join $names ,]\t[join $kinds ,]\t[join $clocks ,]"
    }
    close $file
    set file [open ${report_path}.edges.tsv w]
    puts $file "net\tdriver_master\tdriver_pin\tparent_reset_net"
    foreach edge $tri_oracle_registered_reset34::edges {puts $file [join $edge \t]}
    close $file
    return [dict create endpoint_count [llength $endpoint_pins] minimum_registered_depth $minimum \
        maximum_registered_depth $maximum registered_sources $roots \
        traced_nets [dict size $tri_oracle_registered_reset34::memo]]
}
