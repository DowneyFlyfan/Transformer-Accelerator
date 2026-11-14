# Measure library pin loads from the saved placement. No wire extraction.
proc measure_load {out view label driver} {
    set net [get_db $driver .net]
    if {[llength $net] != 1 || [get_db $net .num_drivers] != 1 ||
        [llength [get_db $net .driver_ports]] != 0} {error "Unexpected driver: $label"}
    set sinks [get_db $net .load_pins]
    set caps [get_db $sinks .capacitance_max -index $view]
    set limit [get_db $driver .max_capacitance -index $view]
    if {[llength $sinks] == 0 || [llength $caps] != [llength $sinks] ||
        ![string is double -strict $limit] || $limit <= 0} {error "Incomplete pin model: $label"}
    set total 0.0
    foreach cap $caps {
        if {![string is double -strict $cap] || $cap <= 0} {error "Missing sink model: $label"}
        set total [expr {$total + $cap}]
    }
    puts $out [join [list [get_db $view .name] $label [get_db $driver .name] [llength $sinks] \
        [format %.12g $total] [format %.12g $limit]] \t]
}

if {[catch {
    set_multi_cpu_usage -local_cpu 1
    read_db $::env(TRI_ORACLE_RESET_CHECKPOINT)
    if {[get_db current_design .name] ne "tri_oracle_chip_command_layer_parallel_chip"} {
        error "Wrong reset load checkpoint"
    }
    set_db enable_ui_precision true
    set_db ui_precision_timing 8
    if {[get_db ui_precision_timing] != 8} {error "Could not set timing display precision"}
    set active [get_db nets grouped_active]
    set active_driver [get_db $active .driver_pins]
    if {[get_db $active_driver .name] ne "batch/g166179/Z"} {error "Unexpected grouped_active driver"}
    set inventory [open grouped_active_sinks.tsv {WRONLY CREAT EXCL}]
    puts $inventory "pin\tmaster\tterminal\tx_um\ty_um"
    set sinks [get_db $active .load_pins]
    if {[llength $sinks] != 17013} {error "Unexpected grouped_active fanout"}
    foreach sink $sinks {
        puts $inventory [join [list [get_db $sink .name] [get_db $sink .inst.base_cell.name] \
            [file tail [get_db $sink .base_pin.name]] {*}[get_db $sink .inst.location]] \t]
    }
    close $inventory
    set out [open loads.tsv {WRONLY CREAT EXCL}]
    puts $out "view\tpath\tdriver\tsinks\tpin_load_pf\tlimit_pf"
    foreach name {setup_slow setup_typ hold_fast} {
        set_analysis_view -setup [list $name] -hold [list $name]
        set view [get_db analysis_views $name]
        if {[llength $view] != 1} {error "Missing analysis view $name"}
        for {set group 0} {$group < 5} {incr group} {
            set owner grouped_$group
            set pin [get_db pins "$owner/g83737/ZN"]
            measure_load $out $view "$owner/root" $pin
            for {set id 0} {$id < 774} {incr id} {
                set path "$owner/TRI_GROUPED_RESET_${group}_$id"
                set pin [get_db pins "$path/Z"]
                if {[llength $pin] != 1} {error "Missing placed buffer $path"}
                measure_load $out $view $path $pin
            }
        }
        measure_load $out $view grouped_active $active_driver
        flush $out
        puts "GROUPED_RESET_LOADS_VIEW $name"
    }
    close $out
    puts TRI_ORACLE_GROUPED_RESET_load_PASS
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
