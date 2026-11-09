# Complete the parent grid around the physically checked core supply exits.
# Full internal supply verification follows actual physical block assembly;
# the timing model's internal power fragments are not a complete power layout.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI_ORACLE_PLACEMENT_PROBE_DIRECTORY)
read_db $root/.cache/physical/pnr/tri_oracle_parent_macro_power46/macro_contacts.db
set_multi_cpu_usage -local_cpu 4
unflatten_ilm
if {[get_db current_design .name] ne "tri_oracle_preserved_placement_probe21"} {
    error "PARENT_POWER49_WRONG_PARENT"
}
set block [get_db insts core0]
if {[get_db $block .place_status] ne "fixed" || ![get_db $block .dont_touch]} {
    error "PARENT_POWER49_UNPROTECTED_CORE"
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
puts TRI_ORACLE_PARENT_POWER49_UPPER_STRIPES_FINISHED

# A twenty-micron pitch gives both narrow side channels a supply pair in this
# one-core control. The macro's original lower-metal obstructions remain.
add_stripes -nets {VDD VSS} -layer M7 -direction vertical \
    -area {20 20 779.955 730} -width 1 -spacing 1 \
    -set_to_set_distance 20 -start_offset 5
puts TRI_ORACLE_PARENT_POWER49_LOWER_STRIPES_FINISHED
# Verify every measured missing parent terminal against actual standard cells
# and physical pin rectangles before limiting the search to peripheral rows.
set row_regions [dict create bottom {19.5 19.5 780.455 40} \
    top {19.5 710 780.455 730.5} left {19.5 19.5 40 730.5} \
    right {759.955 19.5 780.455 730.5}]
set file [open $root/.cache/physical/pnr/tri_oracle_parent_macro_power46/diagnostic_power_connectivity.rpt r]
set diagnostic [read $file]; close $file
set observed 0; set parsed 0; set parent_count 0; set macro_count 0
set active_regions [dict create]
set file [open $out/row_region_coverage.tsv w]
puts $file "instance\tnet\tmaster\trectangle\tregion"
foreach line [split $diagnostic "\n"] {
    if {[string match {*Pin Pin:*has an unconnected terminal*} $line]} {incr observed}
    if {![regexp {^Net (VDD|VSS), Pin Pin: ([^;]+)/(VDD|VSS);.*has an unconnected terminal at \(([-+0-9.eE]+), ([-+0-9.eE]+)\) \(([-+0-9.eE]+), ([-+0-9.eE]+)\)$} \
            $line -> net name pin x1 y1 x2 y2]} {continue}
    incr parsed
    if {$net ne $pin} {error "PARENT_POWER49_MISMATCHED_SUPPLY"}
    if {$name eq "core0"} {incr macro_count; continue}
    if {![regexp {^[A-Za-z_][A-Za-z_0-9$]*$} $name]} {error "PARENT_POWER49_UNEXPECTED_PARENT_IDENTITY: $name"}
    set instance [get_db insts $name]
    if {[llength $instance] != 1 || ![regexp {BWP12T40P140$} [get_db $instance .base_cell.name]]} {
        error "PARENT_POWER49_NOT_A_REAL_PARENT_STANDARD_CELL: $name"
    }
    set assigned ""
    dict for {label area} $row_regions {
        lassign $area a b c d
        if {$x1 >= $a && $y1 >= $b && $x2 <= $c && $y2 <= $d} {set assigned $label; break}
    }
    if {$assigned eq ""} {error "PARENT_POWER49_UNCOVERED_MEASURED_TERMINAL: $line"}
    dict incr active_regions $assigned
    puts $file "$name\t$net\t[get_db $instance .base_cell.name]\t$x1 $y1 $x2 $y2\t$assigned"
    incr parent_count
}
close $file
if {$observed != 1299 || $parsed != $observed || $parent_count != 210 || $macro_count != 1089} {
    error "PARENT_POWER49_INCOMPLETE_MEASURED_TERMINAL_COVERAGE"
}
write_db $out/lower_stripes.db
# Each completed region gets a real checkpoint before proceeding. The full
# unfiltered connectivity and geometry gates below are still mandatory.
dict for {label area} $row_regions {
    if {![dict exists $active_regions $label]} {continue}
    redirect $out/rows_${label}.rpt [list route_special -nets {VDD VSS} \
        -connect core_pin -area $area -core_pin_target stripe -allow_layer_change 1 \
        -allow_jogging 1 -layer_change_range {M1 M7} \
        -target_via_layer_range {M1 M7} -crossover_via_layer_range {M1 M7}] -tee
    write_db $out/rows_${label}.db
    puts "TRI_ORACLE_PARENT_POWER49_ROWS_REGION_FINISHED $label"
}
puts TRI_ORACLE_PARENT_POWER49_STANDARD_ROWS_FINISHED
redirect $out/lower_stripe_connections.rpt {
    route_special -nets {VDD VSS} -connect floating_stripe \
        -stripe_layer_range {M7 M7} -floating_stripe_target stripe \
        -allow_layer_change 1 -allow_jogging 1 -layer_change_range {M7 M10} \
        -target_via_layer_range {M7 M10} -crossover_via_layer_range {M7 M10}
} -tee
puts TRI_ORACLE_PARENT_POWER49_LOWER_CONNECTIONS_FINISHED
fix_via -min_cut
check_drc -check_only special -limit 100000 -out_file $out/special_drc.rpt
check_connectivity -type special -nets {VDD VSS} -check_pg_ports \
    -error 100000 -warning 100000 -out_file $out/diagnostic_power_connectivity.rpt
check_place > $out/placement.rpt
source $root/syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/placement.rpt
set block [get_db insts core0]
if {[list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]] ne $original_pose ||
        ![get_db $block .dont_touch]} {error "PARENT_POWER49_CORE_CHANGED"}
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
if {$count != 94471} {error "PARENT_POWER49_CHANGED_OR_INCOMPLETE_CORE"}
set file [open $out/core_prefixes.txt w]; puts $file core0; close $file
exec python3 -B $root/syn/tri_oracle_core_preservation.py \
    $root/.cache/physical/pnr/tri_oracle_clock_probe35_green6/core_after.tsv \
    $out/core_after.tsv $out/core_prefixes.txt > $out/core_preservation.json
write_db $out/parent_power_grid.db
puts TRI_ORACLE_PARENT_POWER49_BOUNDED_GRID_CONSTRUCTED
exit
