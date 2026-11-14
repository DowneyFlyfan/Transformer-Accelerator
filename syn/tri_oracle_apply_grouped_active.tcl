proc active_loads {driver expected} {
    set net [get_db [get_db pins $driver] .net]
    if {[llength $net] != 1 || [get_db $net .driver_pins.name] ne $driver ||
        [get_db $net .driver_ports.name] ne {} || [get_db $net .load_ports.name] ne {} ||
        [get_db $net .constant] ne "no_constant" || [get_db $net .is_clock] ||
        [lsort [get_db $net .load_pins.name]] ne [lsort $expected]} {
        error "Unexpected active-net connectivity at $driver"
    }
}

if {[catch {
    set mode $::env(TRI_ACTIVE_MODE)
    set_multi_cpu_usage -local_cpu 8
    read_db $::env(TRI_ORACLE_RESET_CHECKPOINT)
    set top tri_oracle_chip_command_layer_parallel_chip
    if {$mode ni {apply cold} || [get_db current_design .name] ne $top} {
        error "Wrong grouped_active input"
    }
    set plan [open $::env(TRI_ACTIVE_PLAN)]
    if {[gets $plan] ne "id\tmaster\tx_um\ty_um\tchildren\tpins"} {error "Invalid grouped_active plan"}
    set rows {}
    set covered [dict create]
    set parents [dict create]
    while {[gets $plan row] >= 0} {
        lassign [split $row \t] id master x y children pins
        if {$id != [llength $rows] || $master ni {BUFFD4BWP12T40P140 BUFFD8BWP12T40P140 BUFFD16BWP12T40P140} ||
            ![string is double -strict $x] || ![string is double -strict $y] ||
            ($children eq "") == ($pins eq "")} {error "Invalid buffer plan row $id"}
        if {$children eq ""} {
            foreach pin $pins {
                if {[dict exists $covered $pin]} {error "Repeated grouped_active load $pin"}
                dict set covered $pin 1
            }
        } else {
            foreach child $children {
                if {$child < 0 || $child >= $id || [dict exists $parents $child]} {error "Bad branch $child"}
                dict set parents $child $id
            }
        }
        lappend rows [list $master $x $y $children $pins]
    }
    close $plan
    if {[llength $rows] != 712 || [dict size $parents] != 711 || [dict size $covered] != 17013} {
        error "Incomplete grouped_active tree"
    }
    if {$mode eq "apply"} {
        active_loads batch/g166179/Z [dict keys $covered]
        foreach setting {eco_update_timing eco_refine_place eco_honor_dont_touch eco_batch_mode} {
            dict set original $setting [get_db $setting]
        }
        set_db eco_update_timing false
        set_db eco_refine_place false
        set_db eco_honor_dont_touch false
        set_db eco_batch_mode true
    }
    set ids [dict create]
    if {$mode eq "cold"} {
        # Exact instance paths recorded by Innovus during insertion avoid
        # scanning the entire chip once per buffer.
        set names [open $::env(TRI_ACTIVE_DRIVER_LEDGER)]
        while {[gets $names line] >= 0} {
            lassign [split $line \t] driver count
            if {![regexp {(^|/)TRI_GROUPED_ACTIVE_([0-9]+)/Z$} $driver -> prefix id]} {continue}
            if {[dict exists $ids $id]} {error "Repeated inserted buffer $id"}
            dict set ids $id [file dirname $driver]
        }
        close $names
        if {[dict size $ids] != 712} {error "Wrong inserted buffer count"}
    }
    set expected [dict create]
    set id 0
    foreach row $rows {
        lassign $row master x y children pins
        set targets $pins
        foreach child $children {lappend targets "[dict get $ids $child]/I"}
        set name TRI_GROUPED_ACTIVE_$id
        if {$mode eq "apply"} {
            set edit [eco_add_repeater -pins [join $targets " "] -cells $master -name $name -no_place]
            set full [lindex $edit 0]
            if {[file tail $full] ne $name} {error "Invalid grouped_active buffer $id: $edit"}
        } else {
            set full [dict get $ids $id]
        }
        set instance [get_db insts $full]
        if {[get_db $instance .base_cell.name] ne $master || ![get_db $instance .base_cell.is_buffer]} {
            error "Unexpected buffer master: $full"
        }
        if {$mode eq "apply"} {
            set_db $instance .location [list $x $y]
            set_db $instance .place_status unplaced
        } elseif {[get_db $instance .place_status] ni {placed fixed}} {
            error "Unplaced buffer $full"
        }
        dict set expected "$full/Z" $targets
        dict set ids $id $full
        incr id
    }
    dict set expected batch/g166179/Z [list "[dict get $ids 711]/I"]
    dict for {driver targets} $expected {active_loads $driver $targets}
    set receipt [open drivers.tsv {WRONLY CREAT EXCL}]
    dict for {driver targets} $expected {puts $receipt "$driver\t[llength $targets]"}
    close $receipt
    puts "GROUPED_ACTIVE_TREE $mode 712 17013"
    if {$mode eq "cold"} {
        set report [open active_loads.tsv {WRONLY CREAT EXCL}]
        puts $report "view\tdriver\tsinks\tpin_load_pf\tlimit_pf"
        foreach name {setup_slow setup_typ hold_fast} {
            set_analysis_view -setup [list $name] -hold [list $name]
            set view [get_db analysis_views $name]
            if {[llength $view] != 1} {error "Missing active-load analysis view $name"}
            dict for {driver targets} $expected {
                set pin [get_db pins $driver]
                set sinks [get_db [get_db $pin .net] .load_pins]
                set caps [get_db $sinks .capacitance_max -index $view]
                set limit [get_db $pin .max_capacitance -index $view]
                if {[llength $caps] != [llength $targets] || ![string is double -strict $limit] || $limit <= 0} {
                    error "Missing active-load model for $driver"
                }
                set load 0.0
                foreach cap $caps {
                    if {![string is double -strict $cap] || $cap < 0} {error "Invalid capacitance: $driver"}
                    set load [expr {$load + $cap}]
                }
                if {$load <= 0 || $load >= $limit} {error "Active branch exceeds its pin-load budget: $driver $load $limit"}
                puts $report [join [list $name $driver [llength $targets] $load $limit] \t]
            }
        }
        close $report
        puts GROUPED_ACTIVE_PIN_LOAD_PASS
    }
    if {$mode eq "apply"} {
        set_db eco_batch_mode [dict get $original eco_batch_mode]
        place_eco -fix_placed_insts true -timing_driven false
        dict for {setting value} $original {set_db $setting $value}
        check_place > placement.rpt
        write_netlist active.v
        write_def active.def
        write_db active.db
    }
    puts "GROUPED_ACTIVE_${mode}_PASS"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
