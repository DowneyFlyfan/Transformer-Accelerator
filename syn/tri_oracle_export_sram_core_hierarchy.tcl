# Export hierarchy artifacts from the unchanged qualified routed core44.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set checkpoint_root $root/.cache/physical/pnr/$top
set out $checkpoint_root/hierarchy_export_55
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

# Classify asynchronous timing endpoints using actual native timing fanin,
# including disabled arcs. Every unconstrained CDN must come only from rst_n.
set reset_pins [get_pins -hierarchical */CDN]
if {[sizeof_collection $reset_pins] != 4751} {error "Unexpected reset endpoint count"}
set reset_starts [all_fanin -to $reset_pins -startpoints_only -trace_through all -view setup_slow]
set reset_start_names [lsort -unique [get_object_name $reset_starts]]
set file [open $out/reset_coverage.rpt w]
puts $file "reset_endpoints: [sizeof_collection $reset_pins]"
puts $file "native_startpoints: $reset_start_names"
close $file
if {$reset_start_names ne {rst_n}} {error "Reset coverage includes another startpoint"}

time_design -post_route -drv_report -expanded_views -report_dir $out/source_si -report_prefix source_si
check_antenna -out_file $out/source_antenna.rpt
write_netlist $out/source_netlist_before.v -exclude_leaf_cells
# M10 contains actual signal routes. M8/M9 are actual connected power stripes.
write_lef_abstract $out/core.lef -top_layer 10 -stripe_pins -pg_pin_layers {8 9} -port_for_each_stripe_pin -extract_block_obs
write_ilm -to_dir $out/ilm -model_type all -opt_stage postcts
write_netlist $out/source_netlist_after.v -exclude_leaf_cells
puts TRI_ORACLE_SRAM_CORE_HIERARCHY55_EXPORTED
exit
