proc reset_root_loads {group} {
    set net [get_db nets grouped_${group}/n_9508]
    if {[get_db $net .num_drivers] != 1 ||
        [get_db $net .driver_pins.name] ne "grouped_$group/g83737/ZN"} {
        error "Unexpected driver in grouped_$group"
    }
    return [lsort [get_db $net .load_pins.name]]
}

if {[catch {
    set_multi_cpu_usage -local_cpu 1
    read_db $::env(TRI_ORACLE_RESET_CHECKPOINT)
    set owner grouped_0
    set peer [get_db hinsts grouped_1]
    set target [get_db hinsts $owner]
    set shared [get_db $target .module.name]
    if {$shared ne [get_db $peer .module.name] || [get_db $target .dont_touch_effective]} {
        error "Expected shared, editable grouped controller"
    }
    for {set group 0} {$group < 5} {incr group} {
        set loads($group) [reset_root_loads $group]
        if {[llength $loads($group)] != 18484} {error "Wrong reset fanout"}
    }
    puts "GROUPED_RESET_SHARED_MODULE $shared"
    flush stdout
    uniquify -new_master [list $owner]
    set unique [get_db [get_db hinsts $owner] .module.name]
    if {$shared eq $unique || $shared ne [get_db $peer .module.name]} {
        error "Scoped controller master was not isolated"
    }
    for {set group 0} {$group < 5} {incr group} {
        if {[reset_root_loads $group] ne $loads($group)} {
            error "Uniquification changed original reset connectivity"
        }
    }
    puts "GROUPED_RESET_UNIQUE_MODULE $unique"
    flush stdout

    set file [open $::env(TRI_ORACLE_RESET_PLAN)/grouped_0.tsv]
    gets $file
    lassign [split [gets $file] \t] id master x y children pins
    close $file
    if {$id ne "0" || $children ne {} || $master ne "BUFFD4BWP12T40P140"} {
        error "Unexpected first planned buffer"
    }
    set expected [lsort [split $pins " "]]
    if {[llength $expected] < 2 || [llength $expected] > 32} {
        error "Unexpected planned buffer fanout"
    }
    set_db eco_update_timing false
    set_db eco_refine_place false
    set_db eco_honor_dont_touch false
    set_db eco_batch_mode true
    set buffer TRI_GROUPED_RESET_0_0
    set edit [eco_add_repeater -pins $pins -cells $master -name $buffer -hinst_guide $owner -no_place]
    if {[lindex $edit 0] ne "$owner/$buffer"} {error "Unexpected ECO result: $edit"}
    set instance [get_db insts $owner/$buffer]
    set stem [get_db [get_db pins $owner/$buffer/I] .net]
    set leaf [get_db [get_db pins $owner/$buffer/Z] .net]
    if {[get_db $instance .base_cell.name] ne $master || ![get_db $instance .base_cell.is_buffer] ||
        [get_db $stem .driver_pins.name] ne "$owner/g83737/ZN" ||
        [get_db $leaf .driver_pins.name] ne "$owner/$buffer/Z" ||
        [lsort [get_db $leaf .load_pins.name]] ne $expected ||
        [lsort [concat $expected [lsearch -all -inline -exact -not [reset_root_loads 0] "$owner/$buffer/I"]]] ne $loads(0)} {
        error "First reset branch failed connectivity checks"
    }
    for {set group 1} {$group < 5} {incr group} {
        if {[reset_root_loads $group] ne $loads($group) ||
            [get_db [get_db hinsts grouped_$group] .module.name] ne $shared} {
            error "Single ECO modified another grouped controller"
        }
    }
    puts "GROUPED_RESET_ISOLATED_REPEATER $owner/$buffer [llength $expected]"
    puts TRI_ORACLE_GROUPED_RESET_probe_PASS
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
