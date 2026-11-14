# Apply the checked reset-buffer plan, with the original placed cells fixed.
proc grouped_reset_owners {sinks root} {
    # Innovus rejects an edit when any selected pin belongs to a shared
    # descendant, even when the hierarchy chosen for the buffer is unique.
    set owners [dict create $root 1]
    foreach sink $sinks {
        set path [file dirname [file dirname $sink]]
        while {$path ne $root} {
            if {![string match "$root/*" $path]} {error "Unexpected reset load hierarchy: $sink"}
            dict set owners $path 1
            set path [file dirname $path]
        }
    }
    return [lsort [dict keys $owners]]
}

proc grouped_reset_check {group stream} {
    set file [open $::env(TRI_ORACLE_RESET_PLAN)/grouped_$group.tsv]
    if {[gets $file] ne "id\tmaster\tx_um\ty_um\tchildren\tpins"} {error "Invalid reset plan header"}
    set owner "grouped_$group"
    set root "$owner/n_9508"
    set input_pins [dict create]
    set outputs [dict create]
    set coverage [dict create]
    set original [get_db nets $root]
    set driver "$owner/g83737/ZN"
    set original_sinks [lsort [get_db $original .load_pins.name]]
    if {$::env(TRI_ORACLE_RESET_MODE) eq "apply" && [llength $original_sinks] != 18484} {
        error "Unexpected original reset fanout in $owner"
    }
    set id 0
    while {[gets $file line] >= 0} {
        lassign [split $line \t] index master x y children pins
        if {$index != $id || $master ni {BUFFD4BWP12T40P140 BUFFD8BWP12T40P140 BUFFD16BWP12T40P140} ||
            ![string is double -strict $x] || ![string is double -strict $y]} {error "Invalid reset buffer $owner/$id"}
        set targets {}
        if {$children eq ""} {
            set targets [split $pins " "]
            if {[llength $targets] == 0 || [llength $targets] > 32} {error "Invalid leaf fanout"}
            foreach pin $targets {
                if {[dict exists $coverage $pin]} {error "Repeated reset load $pin"}
                dict set coverage $pin 1
            }
        } else {
            if {$pins ne "" || [llength $children] > 4} {error "Invalid upper reset branch"}
            foreach child $children {lappend targets [dict get $input_pins $child]}
        }
        set leaf_name TRI_GROUPED_RESET_${group}_${id}
        set name "$owner/$leaf_name"
        if {$::env(TRI_ORACLE_RESET_MODE) eq "apply"} {
            set edit [eco_add_repeater -pins [join $targets " "] -cells $master -name $leaf_name -hinst_guide $owner -no_place]
            if {[lindex $edit 0] ne $name} {error "Unexpected buffer path: $edit"}
        }
        set instance [get_db insts $name]
        if {[get_db $instance .name] ne $name || [get_db $instance .base_cell.name] ne $master ||
            ![get_db $instance .base_cell.is_buffer]} {error "Unexpected buffer identity: $name"}
        if {$::env(TRI_ORACLE_RESET_MODE) eq "apply"} {
            set_db $instance .location [list $x $y]
            set_db $instance .place_status unplaced
        } elseif {[get_db $instance .place_status] ni {placed fixed}} {
            error "Unplaced reset buffer: $name"
        }
        dict set input_pins $id "$name/I"
        dict set outputs "$name/Z" [lsort $targets]
        incr id
    }
    close $file
    if {$id != 774 || [dict size $coverage] != 18484} {error "Unexpected tree size in $owner"}
    if {$::env(TRI_ORACLE_RESET_MODE) eq "apply" && [lsort [dict keys $coverage]] ne $original_sinks} {
        error "Original reset sinks do not match the plan in $owner"
    }
    set root_input [dict get $input_pins [expr {$id - 1}]]
    dict set outputs $driver [list $root_input]
    dict for {out targets} $outputs {
        set net [get_db [get_db pins $out] .net]
        if {[get_db $net .num_drivers] != 1 || [get_db $net .driver_pins.name] ne $out ||
            [lsort [get_db $net .load_pins.name]] ne $targets || [get_db $net .load_ports.name] ne {} ||
            [get_db $net .is_clock] || [get_db $net .constant] ne "no_constant"} {
            error "Reset connectivity mismatch at $out"
        }
    }
    puts $stream "$group\t$id\t[dict size $coverage]\t$driver\t$root_input"
    flush $stream
    puts "TRI_ORACLE_GROUPED_RESET_TREE $group $id [dict size $coverage]"
}

if {[catch {
    set mode $::env(TRI_ORACLE_RESET_MODE)
    if {$mode ni {prepare apply cold}} {error "Unexpected reset trial mode"}
    set_multi_cpu_usage -local_cpu 8
    read_db $::env(TRI_ORACLE_RESET_CHECKPOINT)
    if {[get_db current_design .name] ne "tri_oracle_chip_command_layer_parallel_chip"} {error "Wrong reset trial design"}
    if {$mode eq "prepare"} {
        # Each tree follows its own sink placement, so the reset branches need
        # separate module definitions. Leave other shared blocks alone.
        set original_sinks [dict create]
        set owners {}
        set roots {}
        for {set group 0} {$group < 5} {incr group} {
            set root grouped_$group
            lappend roots $root
            set sinks [lsort [get_db [get_db nets $root/n_9508] .load_pins.name]]
            dict set original_sinks $group $sinks
            set owners [concat $owners [grouped_reset_owners $sinks $root]]
        }
        foreach root $roots {
            set owner [get_db hinsts $root]
            if {[llength [get_db $owner .module.hinsts]] > 1} {
                uniquify -new_master [list $root]
            }
        }
        # Make repeated children within each grouped controller independent,
        # then resolve any master also shared by separate grouped controllers.
        foreach root $roots {uniquify [get_db [get_db hinsts $root] .module.name]}
        set isolated 0
        foreach name $owners {
            set owner [get_db hinsts $name]
            if {[llength $owner] != 1 || [get_db $owner .name] ne $name} {error "Missing reset hierarchy: $name"}
            if {[get_db $owner .dont_touch_effective] || [get_db $owner .read_only_effective]} {
                error "Protected reset hierarchy: $name"
            }
            set peers [get_db $owner .module.hinsts.name]
            if {[llength $peers] > 1} {
                foreach peer $peers {
                    if {[lindex [split $peer /] 0] ni $roots} {
                        error "Reset module also belongs to unrelated hierarchy: $name -> $peer"
                    }
                }
                puts "TRI_ORACLE_GROUPED_RESET_SHARED_OWNER $name [llength $peers]"
                uniquify_partition -hinst $name
                incr isolated
            }
        }
        foreach name $owners {
            set peers [get_db [get_db hinsts $name] .module.hinsts.name]
            if {[llength $peers] != 1 || [lindex $peers 0] ne $name} {
                error "Reset hierarchy owner mismatch: $name -> $peers"
            }
        }
        for {set group 0} {$group < 5} {incr group} {
            if {[lsort [get_db [get_db nets grouped_${group}/n_9508] .load_pins.name]] ne [dict get $original_sinks $group]} {
                error "Uniquification changed grouped_$group reset connectivity"
            }
        }
        puts "TRI_ORACLE_GROUPED_RESET_UNIQUE_OWNERS [llength $owners] $isolated"
        write_db prepared.db
        puts "TRI_ORACLE_GROUPED_RESET_prepare_PASS"
        exit 0
    }
    if {$mode eq "apply"} {
        foreach setting {eco_update_timing eco_refine_place eco_honor_dont_touch eco_batch_mode} {
            dict set original $setting [get_db $setting]
        }
        set_db eco_update_timing false
        set_db eco_refine_place false
        set_db eco_honor_dont_touch false
        set_db eco_batch_mode true
    }
    set stream [open reset_tree.tsv {WRONLY CREAT EXCL}]
    puts $stream "group\tbuffers\tsinks\tdriver\troot_input"
    foreach group {3 4 0 1 2} {grouped_reset_check $group $stream}
    close $stream
    if {$mode eq "apply"} {
        set_db eco_batch_mode [dict get $original eco_batch_mode]
        place_eco -fix_placed_insts true -timing_driven false
        dict for {setting value} $original {set_db $setting $value}
        check_place > placement.rpt
        write_netlist trial.v
        write_def trial.def
        write_db trial.db
    }
    puts "TRI_ORACLE_GROUPED_RESET_${mode}_PASS"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
