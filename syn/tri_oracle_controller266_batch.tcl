# Insert a bounded, noninverting tree; preserve every original cell and connection.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI266_OUT)
set_multi_cpu_usage -local_cpu 8
source $root/syn/tri_oracle_name265_lists.tcl
source $root/syn/tri_oracle_unique215_snapshot.tcl
source $root/syn/tri_oracle_preservation233.tcl
source $root/syn/tri_oracle_design242_metadata.tcl
read_db $::env(TRI266_INPUT)
set_multi_cpu_usage -local_cpu 8
unflatten_ilm
set mode $::env(TRI266_MODE)
proc tri266_row {net} {
    return [join [list [get_db $net .constant] [get_db $net .is_power] [get_db $net .is_ground] [lsort [get_db $net .driver_pins.name]] [lsort [get_db $net .driver_ports.name]] [lsort [get_db $net .load_pins.name]] [lsort [get_db $net .load_ports.name]]] "\t"]
}
proc tri266_macros {tag guidance} {
    global out
    set cores [get_db insts -if {.base_cell.name == tri_oracle_sram_memory_compute}]
    set banks [get_db insts -if {.base_cell.name == TS6N28HPCPSVTA16X128M2F}]
    if {[llength $cores]!=20 || [llength $banks]!=40} {error TRI266_WRONG_MACRO_SET}
    set halos [open $out/[set tag]_halos.tsv w]
    puts $halos "instance\tmaster\tlocation\torientation\tstatus\tdont_touch\thas_halo\tleft\tbottom\tright\ttop"
    foreach instance [concat $cores $banks] {
        puts $halos [join [list [get_db $instance .name] [get_db $instance .base_cell.name] [get_db $instance .location] [get_db $instance .orient] [get_db $instance .place_status] [get_db $instance .dont_touch] [get_db $instance .is_place_halo] [get_db $instance .place_halo_left] [get_db $instance .place_halo_bottom] [get_db $instance .place_halo_right] [get_db $instance .place_halo_top]] "\t"]
    }
    close $halos
    set stream [open $out/[set tag]_core_pins.tsv w]
    puts $stream "pin\tdirection\tnet\tconstant"
    foreach core $cores {
        set count 0
        set internal 0
        set name [get_db $core .name]
        foreach pin [get_db $core .pins] {
            set pname [get_db $pin .name]
            set direction [get_db $pin .direction]
            set net [get_db $pin .net.name]
            set constant [get_db $pin .constant]
            if {$direction eq "internal"} {
                if {!$guidance || $pname ne "$name/_INT_clk_src_data_check_clk" || $net ne "" || $constant ne "no_constant"} {error TRI266_UNEXPECTED_INTERNAL_PIN}
                incr internal
            } else {incr count}
            puts $stream "$pname\t$direction\t$net\t$constant"
        }
        if {$count!=3158 || $internal!=$guidance} {error "TRI266_ORIGINAL_CORE_INTERFACE_CHANGED $name $count $internal"}
    }
    close $stream
}
proc tri266_reset_check {filename} {
    global root
    source $root/syn/tri_oracle_registered_reset_trace102.tcl
    source $root/syn/tri_oracle_check_registered_reset_fabric.tcl
    set masters [exec python3 -B -c {import json,sys; print(" ".join(json.load(open(sys.argv[1]))["flip_flop_cells"]))} $root/records/registered_reset34_sequential_masters.json]
    tri_oracle_require_parent_registered_resets $masters $filename
}

proc tri266_port_poses {filename} {
    set stream [open $filename w]
    puts $stream "port\tdirection\tlocation\tlayer\tstatus\tphysical_pins"
    foreach port [get_db ports] {
        puts $stream [join [list [get_db $port .name] [get_db $port .direction] [get_db $port .location] [get_db $port .layer.name] [get_db $port .place_status] [llength [get_db $port .physical_pins]]] "\t"]
    }
    close $stream
}
proc tri266_metadata {tag} {
    global out root
    tri242_design_snapshot $out/[set tag]_design.tsv
    tri266_macros $tag 0
    tri266_port_poses $out/[set tag]_port_poses.tsv
    tri266_reset_check $out/[set tag]_reset_roots.tsv
    tri233_preservation $root/.cache/physical/synthesis/tri_oracle_predicted_feedforward_finish213/constraints.sdc $out/[set tag]_preservation.tsv 86
    set stream [open $out/[set tag]_hierarchy.tsv w]
    foreach instance [get_db hinsts] {
        puts $stream "[get_db $instance .name]\t[get_db $instance .module.name]\t[get_db $instance .dont_touch]\t[get_db $instance .module.dont_touch]\t[get_db $instance .dont_touch_hports]\t[get_db $instance .module.dont_touch_hports]"
    }
    close $stream
}
proc tri266_full_evidence {} {
    global out
    set_ilm_type -model si
    flatten_ilm
    set input [open $::env(TRI266_PREFIXES) r]
    set prefixes [split [string trim [read $input]] "\n"]
    close $input
    set counts [dict create]
    foreach prefix $prefixes {dict set counts $prefix 0}
    if {[dict size $counts]!=20} {error TRI266_WRONG_CORE_PREFIXES}
    set stream [open $out/core_cells.tsv w]
    puts $stream "instance\tmaster\tlocation\torientation"
    foreach instance [get_db insts] {
        set name [get_db $instance .name]
        if {![regexp {^(.*clusters\[[0-9]+\]\.cluster/cores\[[0-9]+\])/(.+)$} $name -> prefix local]} {continue}
        if {![dict exists $counts $prefix]} {error TRI266_UNEXPECTED_CORE}
        dict incr counts $prefix
        puts $stream "$name\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]"
    }
    close $stream
    dict for {prefix count} $counts {if {$count!=94471} {error "TRI266_INCOMPLETE_ORIGINAL_CORE $prefix $count"}}
    foreach master {TS5N28HPCPSVTA32X128M2FW TS5N28HPCPSVTA512X64M4F TS6N28HPCPSVTA16X128M2F} expected {360 40 200} {
        if {[llength [get_db insts -if ".base_cell.name == $master"]]!=$expected} {error TRI266_WRONG_FULL_MEMORY_COUNT}
    }
    report_ilm_status > $out/full_model_status.rpt
    foreach view {setup_slow setup_typ hold_fast} {
        set_analysis_view -setup [list $view] -hold [list $view]
        if {[sizeof_collection [get_clocks core_clock]]!=1} {error TRI266_MISSING_ORIGINAL_CLOCK}
        write_sdc -view $view $out/[set view].sdc
    }
    set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
}
proc tri266_tree {tree controller driver driver_master expected_count expected_buffers root_id plan_rows} {
    global out sink_stream buffer_stream all_original_rows all_final_rows
set driver_pin [get_db pins $driver]
if {[llength $driver_pin]!=1 || [get_db $driver_pin .name] ne $driver || [get_db $driver_pin .direction] ne "out" || [get_db $driver_pin .inst.base_cell.name] ne $driver_master || [get_db $driver_pin .inst.base_cell.is_tristate] || ![get_db $driver_pin .inst.base_cell.is_inverter]} {error TRI266_INVALID_OR_TRISTATE_DRIVER}
set owner [get_db hinsts $controller]
if {[llength $owner]!=1 || [get_db $owner .name] ne $controller || ![get_db $owner .dont_touch]} {error TRI266_WRONG_PROTECTED_CONTROLLER}
set net_name [get_db $driver_pin .net.name]
set net [get_db nets $net_name]
if {[llength $net]!=1 || [get_db $net .name] ne $net_name || ![tri265_names_equal [get_db $net .driver_pins.name] [list $driver]] || [get_db $net .driver_ports.name] ne {} || [get_db $net .load_ports.name] ne {} || [get_db $net .constant] ne "no_constant" || [get_db $net .is_power] || [get_db $net .is_ground]} {error TRI266_UNEXPECTED_TARGET_NET}
set original_loads [lsort [get_db $net .load_pins.name]]
if {[llength $original_loads]!=$expected_count} {error TRI266_UNEXPECTED_TARGET_FANOUT}
set original_row [tri266_row $net]
set stream $sink_stream
foreach name $original_loads {
    set pin [get_db pins $name]
    if {[llength $pin]!=1 || [get_db $pin .name] ne $name || [get_db $pin .direction] ne "in"} {error TRI266_UNEXPECTED_SINK}
    if {[file dirname [file dirname $name]] ne $controller || ![regexp {/(E|[ABCDIS][0-4]?)$} $name]} {error TRI266_ASYNC_CLOCK_OR_BOUNDARY_LOAD}
    puts $stream "$tree\t$name\t[get_db $pin .inst.location]"
}
set inputs [dict create]
set buffers [dict create]
set expected_sinks [dict create]
set parents [dict create]
set leaf_seen [dict create]
set levels [dict create]
foreach line $plan_rows {
    set fields [split $line "\t"]
    if {[llength $fields]!=7} {error TRI266_BAD_PLAN_ROW}
    lassign $fields id level master x y kind targets
    if {![string is integer -strict $id] || $id!=[dict size $buffers] || ![string is integer -strict $level] || $level<0 || $master ni {BUFFD4BWP12T40P140 BUFFD8BWP12T40P140 BUFFD16BWP12T40P140} || ![string is double -strict $x] || ![string is double -strict $y]} {error TRI266_BAD_PLAN_VALUE}
    set selected {}
    if {$kind eq "leaf"} {
        set selected [split $targets " "]
        if {$level!=0 || $master ne "BUFFD4BWP12T40P140" || [llength $selected]<1 || [llength $selected]>32} {error TRI266_BAD_LEAF}
        foreach name $selected {
            if {$name ni $original_loads || [dict exists $leaf_seen $name]} {error TRI266_MISSING_OR_DUPLICATE_LOAD}
            dict set leaf_seen $name 1
        }
    } elseif {$kind eq "parent"} {
        set children [split $targets " "]
        if {[llength $children]<1 || [llength $children]>4} {error TRI266_BAD_UPPER_FANOUT}
        set child_level -1
        foreach child $children {
            if {![dict exists $inputs $child] || [dict exists $parents $child]} {error TRI266_BAD_CHILD_REFERENCE}
            lappend selected [dict get $inputs $child]
            dict set parents $child $id
            set child_level [expr {max($child_level,[dict get $levels $child])}]
        }
        if {$level!=$child_level+1} {error TRI266_INCONSISTENT_TREE_DEPTH}
    } else {error TRI266_UNKNOWN_NODE_KIND}
    foreach name $selected {
        set pin [get_db pins $name]
        if {[llength $pin]!=1 || [get_db $pin .net.name] ne $net_name} {error TRI266_INPUT_NOT_ON_ORIGINAL_NET}
    }
    set edit [eco_add_repeater -pins [join $selected " "] -cells $master -name TRI266_T${tree}_BUFFER_$id -hinst_guide $controller -no_place]
    set name [lindex $edit 0]
    set buffer [get_db insts $name]
    if {[llength $buffer]!=1 || [string first "$controller/" $name]!=0 || [get_db $buffer .base_cell.name] ne $master || ![get_db $buffer .base_cell.is_buffer] || [dict exists $buffers $id]} {error TRI266_WRONG_NEW_BUFFER}
    set_db $buffer .location [list $x $y]
    set_db $buffer .place_status unplaced
    dict set inputs $id $name/I
    dict set buffers $id $name
    dict set expected_sinks $id $selected
    dict set levels $id $level
}
if {[dict size $buffers]!=$expected_buffers || [dict size $leaf_seen]!=$expected_count || [dict size $parents]!=$expected_buffers-1 || [dict exists $parents $root_id] || $root_id!=$expected_buffers-1} {error TRI266_INCOMPLETE_TREE}
set final_net [get_db nets $net_name]
if {![tri265_names_equal [get_db $final_net .driver_pins.name] [list $driver]] || ![tri265_names_equal [get_db $final_net .load_pins.name] [list [dict get $inputs $root_id]]] || [get_db $final_net .driver_ports.name] ne {} || [get_db $final_net .load_ports.name] ne {} || [get_db $final_net .constant] ne "no_constant" || [get_db $final_net .is_power] || [get_db $final_net .is_ground]} {error TRI266_WRONG_ROOT_CONNECTION}
set final_rows [list [tri266_row $final_net]]
set stream $buffer_stream
dict for {id name} $buffers {
    set input_pin [get_db pins $name/I]
    set output_pin [get_db pins $name/Z]
    set output_net [get_db $output_pin .net]
    if {[llength $input_pin]!=1 || [llength $output_pin]!=1 || ![tri265_names_equal [get_db $output_net .driver_pins.name] [list $name/Z]] || [lsort [get_db $output_net .load_pins.name]] ne [lsort [dict get $expected_sinks $id]] || [get_db $output_net .driver_ports.name] ne {} || [get_db $output_net .load_ports.name] ne {} || [get_db $output_net .constant] ne "no_constant" || [get_db $output_net .is_power] || [get_db $output_net .is_ground]} {error TRI266_TREE_BRANCH_CONNECTIVITY_CHANGED}
    lappend final_rows [tri266_row $output_net]
    puts $stream "$tree\t$id\t$name\t[get_db [get_db insts $name] .base_cell.name]\t[dict get $levels $id]\t[llength [dict get $expected_sinks $id]]"
}
if {[llength [lsort -unique $final_rows]]!=$expected_buffers+1} {error TRI266_AMBIGUOUS_TREE_NETS}
lappend all_original_rows $original_row
set all_final_rows [concat $all_final_rows $final_rows]
return [dict values $buffers]

}
if {$mode eq "cold"} {
    tri215_snapshot $out cold
    tri266_metadata cold
    check_place > $out/placement.rpt
    tri266_full_evidence
    puts TRI_ORACLE_CONTROLLER266_COLD_TREE_AND_ORIGINAL_CORES_EXPORTED
    exit
}
if {$mode ne "warm"} {error TRI266_UNKNOWN_MODE}
set plans [dict create]
set stream [open $::env(TRI266_PLAN) r]
gets $stream header
if {$header ne "tree\tid\tlevel\tmaster\tx\ty\tkind\ttargets"} {error TRI266_BAD_BATCH_PLAN_HEADER}
while {[gets $stream line]>=0} {
    set fields [split $line "\t"]
    if {[llength $fields]!=8} {error TRI266_BAD_BATCH_PLAN_ROW}
    dict lappend plans [lindex $fields 0] [join [lrange $fields 1 end] "\t"]
}
close $stream
tri215_snapshot $out before
tri266_metadata before
set old_settings [dict create]
foreach setting {eco_honor_dont_touch eco_refine_place eco_update_timing eco_batch_mode} {dict set old_settings $setting [get_db $setting]}
set_db eco_update_timing false
set_db eco_refine_place false
set_db eco_honor_dont_touch false
set_db eco_batch_mode true
set sink_stream [open $out/actual_sinks.tsv w]
puts $sink_stream "tree\tpin\tlocation"
set buffer_stream [open $out/buffers.tsv w]
puts $buffer_stream "tree\tid\tinstance\tmaster\tlevel\tloads"
set all_original_rows {}
set all_final_rows {}
set all_buffers {}
set stream [open $::env(TRI266_TREES) r]
gets $stream header
if {$header ne "tree\tcontroller\tdriver\tdriver_master\tloads\tbuffers\troot"} {error TRI266_BAD_BATCH_TREE_HEADER}
set tree_count 0
while {[gets $stream line]>=0} {
    set fields [split $line "\t"]
    if {[llength $fields]!=7} {error TRI266_BAD_BATCH_TREE_ROW}
    lassign $fields tree controller driver master loads count root_id
    if {$tree!=$tree_count || ![dict exists $plans $tree]} {error TRI266_BATCH_TREE_ORDER}
    set added [tri266_tree $tree $controller $driver $master $loads $count $root_id [dict get $plans $tree]]
    set all_buffers [concat $all_buffers $added]
    incr tree_count
}
close $stream
close $sink_stream
close $buffer_stream
if {$tree_count!=114 || [dict size $plans]!=114 || [llength $all_buffers]!=1989 || [llength [lsort -unique $all_buffers]]!=1989 || [llength [lsort -unique $all_original_rows]]!=114 || [llength [lsort -unique $all_final_rows]]!=2103} {error TRI266_INCOMPLETE_BATCH}
set_db eco_batch_mode [dict get $old_settings eco_batch_mode]
unflatten_ilm
place_eco -fix_placed_insts true -timing_driven false
unflatten_ilm
foreach setting {eco_honor_dont_touch eco_refine_place eco_update_timing} {set_db $setting [dict get $old_settings $setting]}
tri215_snapshot $out after
tri266_metadata after
check_place > $out/placement.rpt
set stream [open $out/placed_buffers.tsv w]
puts $stream "instance\tmaster\tlocation\torientation\tstatus\tdont_touch"
foreach name $all_buffers {
    set instance [get_db insts $name]
    puts $stream "[get_db $instance .name]\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]\t[get_db $instance .place_status]\t[get_db $instance .dont_touch]"
}
close $stream
# Collapse only the complete, verified noninverting tree for comparison.
foreach tag {before after} rows [list $all_original_rows $all_final_rows] {
    set input [open $out/[set tag]_nets.tsv r]
    set output [open $out/[set tag]_other_nets.tsv w]
    set excluded [dict create]
    foreach row $rows {dict set excluded $row 1}
    set removed 0
    while {[gets $input line]>=0} {if {[dict exists $excluded $line]} {incr removed} else {puts $output $line}}
    close $input
    close $output
    if {$removed!=[llength $rows]} {error TRI266_AMBIGUOUS_CANONICAL_NET_ROW}
}
set added_names [dict create]
foreach name $all_buffers {dict set added_names $name 1}
set input [open $out/after_cells.tsv r]
set output [open $out/after_original_cells.tsv w]
set removed 0
while {[gets $input line]>=0} {
    if {[dict exists $added_names [lindex [split $line "\t"] 0]]} {incr removed} else {puts $output $line}
}
close $input
close $output
if {$removed!=1989} {error TRI266_WRONG_ADDED_CELL_SET}
write_netlist $out/parent.v -exclude_leaf_cells
write_def $out/parent.def
tri266_full_evidence
write_db $out/tree_full.db
puts TRI_ORACLE_CONTROLLER266_TREE_PLACED_AND_ORIGINAL_CORES_EXPORTED
exit
