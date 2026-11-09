# Read-only geometry audit of possible M9 supply exits in the real core44.
# Occupancy is queried from routed physical data, not inferred from the LEF.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI_ORACLE_PLACEMENT_PROBE_DIRECTORY)
set core $root/.cache/physical/pnr/tri_oracle_sram_memory_compute/routed_typical_repair_44.db
read_db $core
set_multi_cpu_usage -local_cpu 4
if {[get_db current_design .name] ne "tri_oracle_sram_memory_compute" ||
    [llength [get_db insts]] != 94471} {error "POWER_ACCESS38_WRONG_OR_INCOMPLETE_PHYSICAL_CORE"}
set regions {
    {vdd_left_bottom VDD {5.49 0 8.49 6.5}}
    {vdd_right_bottom VDD {711.35 0 714.35 6.5}}
    {vss_left_bottom VSS {1.49 0 4.49 2.5}}
    {vss_right_bottom VSS {715.35 0 718.35 2.5}}
    {vdd_left_top VDD {5.49 662.7 8.49 670}}
    {vdd_right_top VDD {711.35 662.7 714.35 670}}
    {vss_left_top VSS {1.49 666.7 4.49 670}}
    {vss_right_top VSS {715.35 666.7 718.35 670}}
}
set summary [open $out/access_summary.tsv w]
set shapes [open $out/access_shapes.tsv w]
puts $summary "region\tsupply\trectangle\texpected_m9_objects\tdifferent_net_m9_objects\tadjacent_signal_objects"
puts $shapes "region\tkind\tnet\tlayers\tgeometry"
set checked_areas {}
foreach candidate $regions {
    lassign $candidate name expected region
    lappend checked_areas $region
    set own 0
    set other 0
    set adjacent 0
    set objects [get_obj_in_area -obj_type {wire via special_wire special_via} -areas [list $region]]
    if {[llength $objects] > 1000} {error "POWER_ACCESS38_UNBOUNDED_LOCAL_INVENTORY: $name"}
    foreach object $objects {
        set kind [get_db $object .obj_type]
        set net [get_db $object .net.name]
        if {$kind in {wire special_wire}} {
            set layers [list [get_db $object .layer.name]]
            set geometry [get_db $object .rect]
        } elseif {$kind in {via special_via}} {
            set layers [list [get_db $object .via_def.bottom_layer.name] [get_db $object .via_def.top_layer.name]]
            set geometry [get_db $object .bottom_rects]
        } else {error "POWER_ACCESS38_UNEXPECTED_OBJECT: $kind"}
        puts $shapes "$name\t$kind\t$net\t$layers\t$geometry"
        if {[lsearch -exact $layers M9] >= 0} {
            if {$net eq $expected} {incr own} else {incr other}
        }
        if {$kind in {wire via} && $net ni {VDD VSS} &&
            ([lsearch -exact $layers M8] >= 0 || [lsearch -exact $layers M10] >= 0)} {
            incr adjacent
        }
    }
    if {$own == 0} {error "POWER_ACCESS38_EXPECTED_REAL_SUPPLY_METAL_MISSING: $name"}
    puts $summary "$name\t$expected\t$region\t$own\t$other\t$adjacent"
}
close $summary
close $shapes
check_drc -area $checked_areas -limit 100000 -out_file $out/baseline_area_drc.rpt
puts TRI_ORACLE_CORE_POWER_ACCESS38_INSPECTED
exit
