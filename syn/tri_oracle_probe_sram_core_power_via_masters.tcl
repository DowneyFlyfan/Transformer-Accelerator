# Read-only admission for offsetting four power stacks and replacing one jog pad.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set checkpoint_root $root/.cache/physical/pnr/$top
set out $checkpoint_root/via_master_probe_10
if {[file exists $out]} {error "Refusing existing via-master probe"}
file mkdir $out
set_multi_cpu_usage -local_cpu 19
read_db $checkpoint_root/routed_setup_margin_09.db
if {[get_db current_design .name] ne $top || [llength [get_db insts]] != 94272} {
    error "Wrong qualified current core"
}
set f [open $out/m4_m5_masters.tsv w]
puts $f "name\tcut_count\trows\tcolumns\tbottom_rects\ttop_rects\tcut_rects"
foreach def [get_db via_defs] {
    if {[get_db $def .bottom_layer.name] eq "M4" && [get_db $def .top_layer.name] eq "M5"} {
        puts $f [join [list [get_db $def .name] [llength [get_db $def .cut_rects]] \
            [get_db $def .cut_rows] [get_db $def .cut_columns] \
            [get_db $def .bottom_rects] [get_db $def .top_rects] [get_db $def .cut_rects]] \t]
    }
}
close $f
set f [open $out/contact_shapes.tsv w]
puts $f "point\tmaster\tbottom_rects\ttop_rects\tcut_rects\tshape\tstatus"
foreach region {{29.5 462.4 31.5 464.8} {430.3 232.8 431.1 233.6} \
    {430.3 213.6 431.1 214.4} {430.3 55.2 431.1 56.0} {430.3 50.4 431.1 51.2}} {
    foreach v [get_obj_in_area -obj_type special_via -areas [list $region]] {
        if {[get_db $v .net.name] eq "VDD" && [get_db $v .via_def.bottom_layer.name] eq "M4" &&
            [get_db $v .via_def.top_layer.name] eq "M5"} {
            puts $f [join [list [get_db $v .point] [get_db $v .via_def.name] \
                [get_db $v .bottom_rects] [get_db $v .top_rects] [get_db $v .cut_rects] \
                [get_db $v .shape] [get_db $v .status]] \t]
        }
    }
}
close $f
puts TRI_ORACLE_SRAM_CORE_VIA_MASTER_PROBE_FINISHED
exit
