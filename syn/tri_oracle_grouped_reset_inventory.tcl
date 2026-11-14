# Export the actual flattened reset loads and their placed coordinates.
if {[catch {
    set_multi_cpu_usage -local_cpu 1
    read_db $::env(TRI_ORACLE_RESET_CHECKPOINT)
    if {[get_db current_design .name] ne "tri_oracle_chip_command_layer_parallel_chip"} {
        error "Unexpected grouped reset design"
    }
    set stream [open reset_sinks.tsv {WRONLY CREAT EXCL}]
    puts $stream "group\tpin\tmaster\tterminal\tx_um\ty_um"
    for {set group 0} {$group < 5} {incr group} {
        set name "grouped_$group/n_9508"
        set net [get_db nets $name]
        set driver [get_db $net .driver_pins]
        set sinks [get_db $net .load_pins]
        if {[get_db $net .name] ne $name || [get_db $driver .name] ne "grouped_$group/g83737/ZN" ||
            [get_db $driver .inst.base_cell.name] ne "INR2D0BWP12T40P140" ||
            [get_db $net .num_drivers] != 1 || [get_db $net .num_loads] != 18484 ||
            [llength $sinks] != 18484 || [get_db $net .constant] ne "no_constant" || [get_db $net .is_clock]} {
            error "Unexpected original reset network $group"
        }
        set names [get_db $sinks .name]
        set masters [get_db $sinks .inst.base_cell.name]
        set terminals [get_db $sinks .base_pin.name]
        set directions [get_db $sinks .direction]
        set coordinates [get_db $sinks .inst.location]
        foreach values [list $names $masters $terminals $directions $coordinates] {
            if {[llength $values] != 18484} {error "Incomplete reset sink attributes $group"}
        }
        foreach pin $names master $masters terminal $terminals direction $directions xy $coordinates {
            if {$direction ne "in" || [string first "grouped_$group/" $pin] != 0 || [llength $xy] != 2} {
                error "Unexpected reset sink $pin"
            }
            puts $stream [join [list $group $pin $master [file tail $terminal] {*}$xy] \t]
        }
        puts "TRI_ORACLE_GROUPED_RESET_INVENTORY $group [llength $sinks]"
    }
    close $stream
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
