# Import an exact coordinate seed, or verify the saved database in a fresh session.
if {[catch {
    set plan [source $::env(TRI_ORACLE_EXACT_SEED_PLAN)]
    set stage $::env(TRI_ORACLE_EXACT_SEED_STAGE)
    set_multi_cpu_usage -local_cpu [exec nproc]
    set top [dict get $plan top]
    if {$stage eq "import"} {
        set_db design_process_node 28
        set_db init_power_nets {VDD}
        set_db init_ground_nets {VSS}
        read_mmmc [dict get $plan views]
        read_physical -lefs [dict get $plan abstracts]
        read_netlist [dict get $plan netlist] -top $top
        init_design
        puts TRI_ORACLE_EXACT_SEED_NETLIST_INITIALIZED
        flush stdout
        set_db delaycal_enable_high_fanout false
        read_def [dict get $plan seed]
        connect_global_net VDD -type pg_pin -pin_base_name VDD -all
        connect_global_net VSS -type pg_pin -pin_base_name VSS -all
    } elseif {$stage eq "cold"} {
        read_db [dict get $plan database]
    } else {
        error "Expected import or cold stage"
    }
    if {[get_db current_design .name] ne $top || [get_db delaycal_enable_high_fanout]} {
        error "Wrong design or an unexpected high-fanout timing setting"
    }

    set macro_count 0
    foreach macro [get_db insts -if {.base_cell.name =~ TS*N28HPCPSVTA*}] {
        if {[get_db $macro .place_status] ne "fixed" || ![get_db $macro .is_place_halo]} {
            error "Memory placement or halo missing at [get_db $macro .name]"
        }
        incr macro_count
    }
    if {$macro_count != [dict get $plan memories]} {error "Memory count changed: $macro_count"}
    set port_count 0
    foreach port [get_db ports] {
        if {[llength [get_db $port .physical_pins]] != 1 ||
            [get_db $port .place_status] ni {placed fixed}} {
            error "Expected one placed shape for [get_db $port .name]"
        }
        incr port_count
    }
    if {$port_count != [dict get $plan ports]} {error "Port count changed: $port_count"}
    set blockages [get_db place_blockages -if {.type == hard}]
    if {[llength $blockages] != [dict get $plan blockages]} {error "Hard placement blockage count changed"}
    check_place > placement.rpt
    source [dict get $plan placement_checker]
    lassign [tri_oracle_require_clean_placement placement.rpt] components density
    if {$components != [dict get $plan components]} {error "Placed component count changed: $components"}
    foreach view {setup_slow setup_typ hold_fast} {
        write_sdc -view $view $view.sdc
    }
    write_def layout.def
    if {$stage eq "import"} {
        write_db [dict get $plan database]
    } else {
        write_netlist cold.v
    }
    puts [list TRI_ORACLE_EXACT_SEED_NATIVE_PASS $stage $components $macro_count $port_count $density]
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
