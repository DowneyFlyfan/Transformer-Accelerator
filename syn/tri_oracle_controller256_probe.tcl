# Capability control: add one transparent buffer to32 loads in a protected block.
# No placement, timing optimization or database save is performed in this probe.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI256_OUT)
set controller {numeric/engine/gated/implementation}
set net_name $controller/n_96
set driver $controller/g434445/ZN
set_multi_cpu_usage -local_cpu 4
source $root/syn/tri_oracle_unique215_snapshot.tcl
source $root/syn/tri_oracle_preservation233.tcl
source $root/syn/tri_oracle_design242_metadata.tcl
read_db $::env(TRI256_INPUT)
set_multi_cpu_usage -local_cpu 4
proc tri256_row {net} {
    return [join [list [get_db $net .constant] [get_db $net .is_power] [get_db $net .is_ground] [lsort [get_db $net .driver_pins.name]] [lsort [get_db $net .driver_ports.name]] [lsort [get_db $net .load_pins.name]] [lsort [get_db $net .load_ports.name]]] "\t"]
}
proc tri256_metadata {tag} {
    global out root
    tri242_design_snapshot $out/[set tag]_design.tsv
    tri233_preservation $root/.cache/physical/synthesis/tri_oracle_predicted_feedforward_finish213/constraints.sdc $out/[set tag]_preservation.tsv 86
    set stream [open $out/[set tag]_hierarchy.tsv w]
    foreach instance [get_db hinsts] {
        puts $stream "[get_db $instance .name]\t[get_db $instance .module.name]\t[get_db $instance .dont_touch]\t[get_db $instance .module.dont_touch]\t[get_db $instance .dont_touch_hports]\t[get_db $instance .module.dont_touch_hports]"
    }
    close $stream
}
set net [get_db nets $net_name]
if {[llength $net]!=1 || [get_db $net .name] ne $net_name || [get_db $net .driver_pins.name] ne [list $driver] || [get_db $net .driver_ports.name] ne {} || [get_db $net .load_ports.name] ne {} || [get_db $net .constant] ne "no_constant" || [get_db $net .is_power] || [get_db $net .is_ground]} {error TRI256_UNEXPECTED_TARGET_NET}
set original_loads [lsort [get_db $net .load_pins.name]]
if {[llength $original_loads]!=998} {error TRI256_UNEXPECTED_TARGET_FANOUT}
set selected {}
foreach name $original_loads {
    if {[string match "$controller/*/E" $name] && [llength $selected]<32} {lappend selected $name}
}
if {[llength $selected]!=32} {error TRI256_MISSING_SELECTED_ENABLE_LOADS}
set original_row [tri256_row $net]
tri215_snapshot $out before
tri256_metadata before
set old_settings [dict create]
foreach setting {eco_honor_dont_touch eco_refine_place eco_update_timing eco_batch_mode} {dict set old_settings $setting [get_db $setting]}
set_db eco_update_timing false
set_db eco_refine_place false
set_db eco_honor_dont_touch false
set_db eco_batch_mode true
set edit [eco_add_repeater -pins [join $selected " "] -cells BUFFD4BWP12T40P140 -name TRI256_BUFFER -hinst_guide $controller -logical_change_only]
set buffer_name [lindex $edit 0]
set buffer [get_db insts $buffer_name]
if {[llength $buffer]!=1 || [get_db $buffer .name] ne $buffer_name || [get_db $buffer .base_cell.name] ne "BUFFD4BWP12T40P140" || ![get_db $buffer .base_cell.is_buffer]} {error "TRI256_WRONG_INSERTED_BUFFER $edit"}
set in_pin [get_db pins $buffer_name/I]
set out_pin [get_db pins $buffer_name/Z]
if {[llength $in_pin]!=1 || [llength $out_pin]!=1} {error TRI256_WRONG_BUFFER_INTERFACE}
set input_net [get_db $in_pin .net]
set output_net [get_db $out_pin .net]
if {[string first "$controller/" $buffer_name]!=0 || [get_db $input_net .name] ne $net_name} {error "TRI256_BUFFER_SCOPE_OR_INPUT_NET_CHANGED $buffer_name [get_db $input_net .name]"}
if {$input_net eq $output_net || [get_db $input_net .driver_pins.name] ne [list $driver] || [get_db $output_net .driver_pins.name] ne [list $buffer_name/Z] || [lsort [get_db $output_net .load_pins.name]] ne $selected} {error TRI256_BUFFER_BRANCH_CONNECTIVITY_CHANGED}
set expected_input_loads [list $buffer_name/I]
foreach name $original_loads {if {$name ni $selected} {lappend expected_input_loads $name}}
if {[lsort [get_db $input_net .load_pins.name]] ne [lsort $expected_input_loads]} {error TRI256_UNSELECTED_LOADS_CHANGED}
foreach net_object [list $input_net $output_net] {
    if {[get_db $net_object .constant] ne "no_constant" || [get_db $net_object .is_power] || [get_db $net_object .is_ground] || [get_db $net_object .driver_ports.name] ne {} || [get_db $net_object .load_ports.name] ne {}} {error TRI256_NET_ROLE_CHANGED}
}
set input_row [tri256_row $input_net]
set output_row [tri256_row $output_net]
set_db eco_batch_mode [dict get $old_settings eco_batch_mode]
foreach setting {eco_honor_dont_touch eco_refine_place eco_update_timing} {set_db $setting [dict get $old_settings $setting]}
tri215_snapshot $out after
tri256_metadata after
# Remove the verified transparent branch before comparing the complete graph.
foreach tag {before after} rows [list [list $original_row] [list $input_row $output_row]] {
    set input [open $out/[set tag]_nets.tsv r]
    set output [open $out/[set tag]_other_nets.tsv w]
    set removed 0
    while {[gets $input line]>=0} {
        if {$line in $rows} {incr removed} else {puts $output $line}
    }
    close $input
    close $output
    if {$removed!=[llength $rows]} {error TRI256_AMBIGUOUS_NET_ROW}
}
set input [open $out/after_cells.tsv r]
set output [open $out/after_original_cells.tsv w]
set removed 0
while {[gets $input line]>=0} {
    if {[lindex [split $line "\t"] 0] eq $buffer_name} {incr removed} else {puts $output $line}
}
close $input
close $output
if {$removed!=1} {error TRI256_WRONG_ADDED_CELL_COUNT}
set stream [open $out/probe_summary.tsv w]
puts $stream "buffer\t$buffer_name"
puts $stream "master\t[get_db $buffer .base_cell.name]"
puts $stream "original_loads\t[llength $original_loads]"
puts $stream "buffered_loads\t[llength $selected]"
puts $stream "input_loads_after\t[llength [get_db $input_net .load_pins.name]]"
puts $stream "noninverting\t[get_db $buffer .base_cell.is_buffer]"
close $stream
puts TRI_ORACLE_CONTROLLER256_BUFFER_BRANCH_AND_PROTECTION_VERIFIED
exit
