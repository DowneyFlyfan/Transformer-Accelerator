# Read-only current power-shape and residual data-driver measurements.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set checkpoint_root $root/.cache/physical/pnr/$top
set out $checkpoint_root/power_shape_probe_07
if {[file exists $out]} {error "Refusing existing power-shape probe"}
file mkdir $out
source syn/tri_oracle_sram_core_report_targets.tcl
set_multi_cpu_usage -local_cpu 19
read_db $checkpoint_root/routed_si_opt_06.db
if {[get_db current_design .name] ne $top || [llength [get_db insts]] != 94272} {
    error "Wrong current core checkpoint"
}
set regions {
    {29.5 462.4 31.5 464.8}
    {430.3 232.8 431.1 233.6}
    {430.3 213.6 431.1 214.4}
    {430.3 55.2 431.1 56.0}
    {430.3 50.4 431.1 51.2}
    {192.7 594.8 194.2 596.3}
}
set f [open $out/power_shapes.tsv w]
puts $f "region\ttype\tnet\tobject\tlayer_or_via\tpoint_or_rect\tbottom\ttop\tcut_count\trows\tcolumns\tcut_rects"
foreach region $regions {
    set objects [get_obj_in_area -obj_type {special_via special_wire} -areas [list $region]]
    if {[llength $objects] > 1000} {error "Unbounded local power-shape inventory"}
    foreach obj $objects {
        set kind [get_db $obj .obj_type]
        set net [get_db $obj .net.name]
        if {$net ni {VDD VSS}} {error "Unexpected supply in local probe"}
        if {$kind eq "special_via"} {
            set def [get_db $obj .via_def]
            puts $f [join [list $region $kind $net $obj [get_db $def .name] \
                [get_db $obj .point] [get_db $def .bottom_layer.name] \
                [get_db $def .top_layer.name] [llength [get_db $obj .cut_rects]] \
                [get_db $def .cut_rows] [get_db $def .cut_columns] \
                [get_db $obj .cut_rects]] \t]
        } elseif {$kind eq "special_wire"} {
            puts $f [join [list $region $kind $net $obj [get_db $obj .layer.name] \
                [get_db $obj .rect] {} {} {} {} {} {}] \t]
        } else {error "Unexpected local object type"}
    }
}
close $f
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
report_timing -view setup_slow -check_type setup -max_paths 1 -path_type full_clock \
    > $out/worst_setup_path.rpt
set noisy [tri_oracle_sram_core_drv_targets [exec gzip -dc \
    $checkpoint_root/qualification_si_opt_06/qualification_si_reports/qualification_si.tran.gz] max_tran 36]
if {[llength $noisy] != 25} {error "Current complete noisy-net inventory differs"}
set index [dict create]
foreach n [get_db nets] {dict set index [get_db $n .name] $n}
set f [open $out/noisy_drivers.tsv w]
puts $f "net\tclock\tdriver\tcell\tinstance\tlocation\torient\tload_count"
foreach name $noisy {
    set net [dict get $index $name]
    foreach pin [get_db $net .driver_pins] {
        set inst [get_db $pin .inst]
        puts $f [join [list $name [get_db $net .is_clock] [get_db $pin .name] \
            [get_db $inst .base_cell.name] [get_db $inst .name] [get_db $inst .location] \
            [get_db $inst .orient] [llength [get_db $net .load_pins]]] \t]
    }
}
close $f
puts TRI_ORACLE_SRAM_CORE_POWER_SHAPES_PROBE_FINISHED
exit
