# Export hierarchy artifacts from the unchanged qualified routed core44.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set checkpoint_root $root/.cache/physical/pnr/$top
set out $checkpoint_root/hierarchy_export_56
if {[file exists $out]} {error "Existing hierarchy export; use a new trial"}
file mkdir $out
set_multi_cpu_usage -local_cpu 1
read_db $checkpoint_root/routed_typical_repair_44.db
set_multi_cpu_usage -local_cpu 19
if {[llength [get_db insts]] != 94471} {error "Wrong routed core count"}
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
set_db timing_max_transition_use_si_transition true
set_db si_enable_drv_with_delta_slew true
set_db opt_post_route_report_si_transitions true

# Preserve all boundary paths, including asynchronous interface controls.
# No ignored ports, reduced corner set or complete-logic model is requested.
set_db ilm_keep_async true
set file [open $out/model_settings.rpt w]
foreach attribute {ilm_keep_async ilm_keep_high_fanout_ports ilm_keep_loopback ilm_keep_inst_in_sdc timing_analysis_type timing_analysis_cppr} {
    puts $file "$attribute: [get_db $attribute]"
}
puts $file "source_cells: [llength [get_db insts]]"
puts $file "source_ports: [llength [get_db ports]]"
puts $file "setup_views: [get_db [get_db analysis_views -if {.is_setup == true}] .name]"
puts $file "hold_views: [get_db [get_db analysis_views -if {.is_hold == true}] .name]"
close $file
set file [open $out/interface_ports.tsv w]
puts $file "port\tdirection"
foreach port [get_db ports] {
    puts $file "[get_db $port .name]\t[get_db $port .direction]"
}
close $file

# Trace actual physical reset connections. all_fanin -startpoints_only treats
# asynchronous control pins as startpoints, so it cannot prove this obligation.
set reset_pins [get_pins -hierarchical */CDN]
if {[sizeof_collection $reset_pins] != 4751} {error "Unexpected reset endpoint count"}
array set reset_root {}
array set reset_busy {}
set reset_buffer_kinds {}
set reset_edges [open $out/reset_connections.tsv w]
puts $reset_edges "net\tdriver_cell\tinput_net"
proc tri_oracle_physical_reset_root {net} {
    global reset_root reset_busy reset_edges reset_buffer_kinds
    set name [get_db $net .name]
    if {[info exists reset_root($name)]} {return $reset_root($name)}
    if {[info exists reset_busy($name)]} {error "Reset net cycle: $name"}
    set reset_busy($name) 1
    set drivers [get_db $net .driver_pins]
    set ports [get_db $net .driver_ports]
    if {[llength $ports] != 0} {
        if {[llength $ports] != 1 || [llength $drivers] != 0 ||
            [get_db $ports .name] ne {rst_n}} {error "Unexpected reset root: $name"}
        set result rst_n
        puts $reset_edges "$name\texternal_port\trst_n"
    } else {
        if {[llength $drivers] != 1} {error "Reset net lacks one driver: $name"}
        set inst [get_db $drivers .inst]
        set kind [get_db $inst .base_cell.name]
        if {![regexp {^(BUFFD|CKBD)[0-9]+BWP12T40P140$} $kind] ||
            [get_db $drivers .base_pin.name] ne {Z}} {
            error "Unsupported reset logic: $name $kind"
        }
        set inputs [get_db [get_db $inst .pins] -if {.base_pin.name == I}]
        if {[llength $inputs] != 1} {error "Reset buffer input missing: $name"}
        set input_net [get_db $inputs .net]
        if {[llength $input_net] != 1} {error "Reset buffer input net missing: $name"}
        lappend reset_buffer_kinds $kind
        puts $reset_edges "$name\t$kind\t[get_db $input_net .name]"
        set result [tri_oracle_physical_reset_root $input_net]
    }
    unset reset_busy($name)
    set reset_root($name) $result
    return $result
}
set file [open $out/reset_endpoint_sources.tsv w]
puts $file "pin\tnet\troot"
set reset_db_pins [get_db $reset_pins]
if {[llength $reset_db_pins] != 4751} {error "Incomplete physical reset pin conversion"}
foreach pin $reset_db_pins {
    set net [get_db $pin .net]
    set start [tri_oracle_physical_reset_root $net]
    puts $file "[get_db $pin .name]\t[get_db $net .name]\t$start"
}
close $file
close $reset_edges
set file [open $out/reset_coverage.rpt w]
puts $file "reset_endpoints: [llength $reset_db_pins]"
puts $file "native_physical_startpoints: rst_n"
puts $file "reset_buffer_cell_types: [lsort -unique $reset_buffer_kinds]"
puts $file "traced_reset_nets: [array size reset_root]"
close $file

time_design -post_route -drv_report -expanded_views -report_dir $out/source_si -report_prefix source_si
check_antenna -out_file $out/source_antenna.rpt
write_netlist $out/source_netlist_before.v -exclude_leaf_cells
# M10 contains actual signal routes. M8/M9 are actual connected power stripes.
write_lef_abstract $out/core.lef -top_layer 10 -stripe_pins -pg_pin_layers {8 9} -port_for_each_stripe_pin -extract_block_obs
write_ilm -to_dir $out/ilm -model_type all -opt_stage postcts
write_netlist $out/source_netlist_after.v -exclude_leaf_cells
puts TRI_ORACLE_SRAM_CORE_HIERARCHY56_EXPORTED
exit
