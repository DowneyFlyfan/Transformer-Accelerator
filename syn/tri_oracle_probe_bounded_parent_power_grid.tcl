# Complete the parent grid around the physically checked core supply exits.
# Full internal supply verification follows actual physical block assembly;
# the timing model's internal power fragments are not a complete power layout.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI_ORACLE_PLACEMENT_PROBE_DIRECTORY)
read_db $root/.cache/physical/pnr/tri_oracle_parent_macro_power46/macro_contacts.db
set_multi_cpu_usage -local_cpu 4
unflatten_ilm
if {[get_db current_design .name] ne "tri_oracle_preserved_placement_probe21"} {
    error "PARENT_POWER47_WRONG_PARENT"
}
set block [get_db insts core0]
if {[get_db $block .place_status] ne "fixed" || ![get_db $block .dont_touch]} {
    error "PARENT_POWER47_UNPROTECTED_CORE"
}
set original_pose [list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]]
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all

# Connect the existing horizontal metal-ten stripes to the outer top-metal
# ring before constructing lower stripes and row connections.
redirect $out/upper_stripes.rpt {
    route_special -nets {VDD VSS} -connect floating_stripe \
        -stripe_layer_range {M10 M10} -floating_stripe_target ring \
        -allow_layer_change 1 -allow_jogging 1 -layer_change_range {M10 AP} \
        -target_via_layer_range {M10 AP} -crossover_via_layer_range {M10 AP}
} -tee
puts TRI_ORACLE_PARENT_POWER47_UPPER_STRIPES_FINISHED

# A twenty-micron pitch gives both narrow side channels a supply pair in this
# one-core control. The macro's original lower-metal obstructions remain.
add_stripes -nets {VDD VSS} -layer M7 -direction vertical \
    -area {20 20 779.955 730} -width 1 -spacing 1 \
    -set_to_set_distance 20 -start_offset 5
puts TRI_ORACLE_PARENT_POWER47_LOWER_STRIPES_FINISHED
redirect $out/standard_cell_rows.rpt {
    route_special -nets {VDD VSS} -connect core_pin -core_pin_target stripe \
        -allow_layer_change 1 -allow_jogging 1 -layer_change_range {M1 M7} \
        -target_via_layer_range {M1 M7} -crossover_via_layer_range {M1 M7}
} -tee
puts TRI_ORACLE_PARENT_POWER47_STANDARD_ROWS_FINISHED
redirect $out/lower_stripe_connections.rpt {
    route_special -nets {VDD VSS} -connect floating_stripe \
        -stripe_layer_range {M7 M7} -floating_stripe_target stripe \
        -allow_layer_change 1 -allow_jogging 1 -layer_change_range {M7 M10} \
        -target_via_layer_range {M7 M10} -crossover_via_layer_range {M7 M10}
} -tee
puts TRI_ORACLE_PARENT_POWER47_LOWER_CONNECTIONS_FINISHED
fix_via -min_cut
check_drc -check_only special -limit 100000 -out_file $out/special_drc.rpt
check_connectivity -type special -nets {VDD VSS} -check_pg_ports \
    -error 100000 -warning 100000 -out_file $out/diagnostic_power_connectivity.rpt
check_place > $out/placement.rpt
source $root/syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/placement.rpt
set block [get_db insts core0]
if {[list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]] ne $original_pose ||
        ![get_db $block .dont_touch]} {error "PARENT_POWER47_CORE_CHANGED"}
write_def $out/parent_power_grid.def -routing
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
if {$count != 94471} {error "PARENT_POWER47_CHANGED_OR_INCOMPLETE_CORE"}
set file [open $out/core_prefixes.txt w]; puts $file core0; close $file
exec python3 -B $root/syn/tri_oracle_core_preservation.py \
    $root/.cache/physical/pnr/tri_oracle_clock_probe35_green6/core_after.tsv \
    $out/core_after.tsv $out/core_prefixes.txt > $out/core_preservation.json
write_db $out/parent_power_grid.db
puts TRI_ORACLE_PARENT_POWER47_BOUNDED_GRID_CONSTRUCTED
exit
