# A focused parent supply-contact control. Standard-cell supply routing and
# signal routing are deliberately separate later stages with their own gates.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI_ORACLE_PLACEMENT_PROBE_DIRECTORY)
read_db $root/.cache/physical/pnr/tri_oracle_clock_probe35_green6/clocked_probe.db
set_multi_cpu_usage -local_cpu 4
unflatten_ilm
if {[get_db current_design .name] ne "tri_oracle_preserved_placement_probe21"} {
    error "PARENT_POWER43_WRONG_INPUT_DESIGN"
}
set block [get_db insts core0]
set original_pose [list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]]
set location [get_db $block .location]
if {[llength $location] == 1} {set location [lindex $location 0]}
if {[llength $location] != 2} {error "PARENT_POWER43_INVALID_LOCATION: $location"}
lassign $location core_x core_y
if {$core_x != 40 || $core_y != 40 || [get_db $block .orient] ne "r0" ||
        [get_db $block .place_status] ne "fixed"} {
    error "PARENT_POWER43_UNEXPECTED_ORIGINAL_POSE: $original_pose"
}
update_lef_macro -macros {tri_oracle_sram_memory_compute} \
    $root/.cache/physical/pnr/tri_oracle_core_power_access42/core.lef
source $root/syn/tri_oracle_restore_core_m9_signal_guards.tcl
if {[tri_oracle_restore_core_m9_signal_guards core0 $out/signal_guards.tsv] != 7} {
    error "PARENT_POWER43_INCOMPLETE_SIGNAL_PROTECTION"
}
write_def $out/guarded_parent.def -routing
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
add_rings -nets {VDD VSS} -type core_rings -follow core \
    -layer {top M10 bottom M10 left AP right AP} -width 4 -spacing 4 -offset 2
foreach channel {{20 20 779.955 40} {20 710 779.955 730}} {
    add_stripes -nets {VDD VSS} -layer M10 -direction horizontal \
        -area $channel -width 4 -spacing 4 -number_of_sets 1 \
        -start_from bottom -start_offset 2
}
redirect $out/macro_power_route.rpt {
    route_special -nets {VDD VSS} -connect block_pin -block_pin use_lef \
        -block_pin_layer_range {M9 M9} -block_pin_target {stripe ring} \
        -stripe_layer_range {M10 M10} -allow_layer_change 1 -allow_jogging 1 \
        -layer_change_range {M9 M10} -target_via_layer_range {M9 M10} \
        -crossover_via_layer_range {M9 M10}
} -tee
set file [open $out/macro_power_route.rpt r]; set report [read $file]; close $file
if {![regexp -line {^[ \t]*Number of Block ports routed:[ \t]*([0-9]+)([ \t]+open:[ \t]*([0-9]+))?[ \t]*$} \
        $report -> routed open_field open]} {error "PARENT_POWER43_MISSING_MACRO_ROUTE_SUMMARY"}
if {$open eq ""} {set open 0}
if {$routed != 4 || $open != 0} {
    write_def $out/open_macro_contacts.def -routing
    error "PARENT_POWER43_MACRO_SUPPLY_CONTACTS_OPEN"
}
# Physical supply terminals overlap measured, connected outer-ring geometry.
set contacts [dict create]
foreach wire [get_obj_in_area -obj_type special_wire -areas {{0 0 799.955 750}}] {
    set net [get_db $wire .net.name]
    if {$net ni {VDD VSS} || [get_db $wire .layer.name] ne "AP" || [dict exists $contacts $net]} {continue}
    set rectangle [get_db $wire .rect]
    if {[llength $rectangle] == 1} {set rectangle [lindex $rectangle 0]}
    lassign $rectangle x1 y1 x2 y2
    if {$x2-$x1 < 4 || $y2-$y1 < 100} {continue}
    set middle [expr {($y1+$y2)/2.0}]
    create_pg_pin -name $net -net $net -geometry AP $x1 [expr {$middle-2}] $x2 [expr {$middle+2}]
    dict set contacts $net $rectangle
}
if {[dict size $contacts] != 2} {error "PARENT_POWER43_MISSING_OUTER_SUPPLY_TERMINALS"}
check_drc -check_only special -limit 100000 -out_file $out/special_drc.rpt
check_connectivity -type special -nets {VDD VSS} -check_pg_ports \
    -error 100000 -warning 100000 -out_file $out/diagnostic_power_connectivity.rpt
check_place > $out/placement.rpt
source $root/syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/placement.rpt
set block [get_db insts core0]
if {[list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]] ne $original_pose ||
        ![get_db $block .dont_touch]} {error "PARENT_POWER43_ORIGINAL_CORE_CHANGED"}
write_def $out/macro_contacts.def -routing
set_ilm_type -model si
flatten_ilm
set file [open $out/core_after.tsv w]
puts $file "instance\tmaster\tlocation\torientation"
set count 0
foreach instance [get_db insts] {
    set name [get_db $instance .name]
    if {![string match {core0/*} $name]} {continue}
    puts $file "$name\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]"
    incr count
}
close $file
if {$count != 94471} {error "PARENT_POWER43_CHANGED_OR_INCOMPLETE_CORE"}
set file [open $out/core_prefixes.txt w]; puts $file core0; close $file
exec python3 -B $root/syn/tri_oracle_core_preservation.py \
    $root/.cache/physical/pnr/tri_oracle_clock_probe35_green6/core_after.tsv \
    $out/core_after.tsv $out/core_prefixes.txt > $out/core_preservation.json
write_db $out/macro_contacts.db
puts TRI_ORACLE_PARENT_MACRO_POWER43_CONTACTS_CONNECTED
exit
