# A mapped hpin may have no local hierarchical segment while retaining a flat
# connection through a merged alias. Constants are also represented directly.
proc tri_oracle_boundary199_prepare {control} {
    global boundary199_inputs
    set name [get_db $control .name]
    if {[dict exists $boundary199_inputs $name]} {return}
    set inputs [dict create]
    set prefix "${name}/"
    foreach pin [get_db $control .hpins] {
        set relative [string range [get_db $pin .name] [string length $prefix] end]
        if {[string first / $relative]>=0 || [get_db $pin .direction] ne "in"} {continue}
        set net [get_db $pin .net]
        if {[llength $net]==1} {dict set inputs [get_db $net .name] [get_db $pin .name]}
    }
    dict set boundary199_inputs $name $inputs
}

proc tri_oracle_boundary199_connection {pin control} {
    global boundary199_inputs boundary199_stream
    tri_oracle_boundary199_prepare $control
    set control_name [get_db $control .name]
    set prefix "${control_name}/"
    set name [get_db $pin .name]
    set direction [get_db $pin .direction]
    set hnet [get_db $pin .hnet]
    set constant [get_db $pin .constant]
    set source {}
    set external_loads 0
    set drivers {}
    set net [get_db $pin .net]
    if {[llength $hnet]==1} {
        set kind hierarchical
        set description [get_db $hnet .name]
    } elseif {[llength $hnet]!=0} {
        error "FRAME199_MULTIPLE_HIERARCHICAL_NETS: $name"
    } elseif {$direction eq "in" && $constant in {0 1}} {
        set kind constant_input
        set description "constant_input:$constant"
    } elseif {$direction eq "out"} {
        set port_constant [get_db $pin .hport.constant]
        set inner_constant [get_db $pin .hport.hnet.constant]
        if {$port_constant in {0 1} || $inner_constant in {0 1}} {
            if {$port_constant in {0 1} && $inner_constant in {0 1} && $port_constant ne $inner_constant} {error FRAME199_CONFLICTING_CONSTANTS}
            set constant [expr {$port_constant in {0 1} ? $port_constant : $inner_constant}]
            set kind constant_output
            set description "constant_output:$constant"
        } else {
            if {[llength $net]!=1} {error "FRAME199_MISSING_FLAT_NET: $name"}
            set drivers [get_db $net .driver_pins]
            set driver_ports [get_db $net .driver_ports]
            if {[llength $drivers]+[llength $driver_ports]!=1} {error "FRAME199_NONUNIQUE_FLAT_DRIVER: $name"}
            foreach load [get_db $net .load_pins] {
                if {[string first $prefix [get_db $load .name]]!=0} {incr external_loads}
            }
            foreach load [get_db $net .load_ports] {
                if {[get_db $load .direction] eq "out"} {incr external_loads}
            }
            if {$external_loads==0} {error "FRAME199_NO_EXTERNAL_FLAT_LOAD: $name"}
            if {[llength $drivers]==1 && [string first $prefix [get_db $drivers .name]]==0} {
                set kind flat_output
                set source [get_db $drivers .name]
            } elseif {[dict exists $boundary199_inputs $control_name [get_db $net .name]]} {
                set kind feedthrough_output
                set source [dict get $boundary199_inputs $control_name [get_db $net .name]]
            } else {
                error "FRAME199_UNEXPLAINED_EXTERNAL_DRIVER: $name"
            }
            set description "${kind}:[get_db $net .name]"
        }
    } else {
        error "FRAME199_UNEXPLAINED_BOUNDARY: $name"
    }
    puts $boundary199_stream "$control_name\t$name\t$direction\t$kind\t$constant\t[get_db $net .name]\t$source\t$external_loads"
    return $description
}

proc tri_oracle_control_boundaries199 {controls filename} {
    set stream [open $filename w]
    puts $stream "instance\thpin\thnet"
    foreach control $controls {
        foreach pin [get_db $control .hpins] {
            set description [tri_oracle_boundary199_connection $pin $control]
            puts $stream "[get_db $control .name]\t[get_db $pin .name]\t$description"
        }
    }
    close $stream
}

proc tri_oracle_boundary199_open {filename} {
    global boundary199_inputs boundary199_stream
    set boundary199_inputs [dict create]
    set boundary199_stream [open $filename w]
    puts $boundary199_stream "instance\tpin\tdirection\tkind\tconstant\tflat_net\tsource\texternal_loads"
}

proc tri_oracle_boundary199_close {} {
    global boundary199_stream
    close $boundary199_stream
}
