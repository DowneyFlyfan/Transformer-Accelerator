# Read-only measurement of all current clean-baseline noisy victims.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set checkpoint_root $root/.cache/physical/pnr/$top
set out $checkpoint_root/driver_measure_37
if {[file exists $out]} {error "Refusing existing driver measurement"}
file mkdir $out
source syn/tri_oracle_sram_core_report_targets.tcl
set_multi_cpu_usage -local_cpu 1
read_db $checkpoint_root/routed_supply_bridge_35.db
set_multi_cpu_usage -local_cpu 19
if {[llength [get_db insts]] != 94470} {error "Wrong clean-baseline inventory"}
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db delaycal_enable_si true
set_db timing_max_transition_use_si_transition true
set_db opt_post_route_report_si_transitions true
time_design -post_route -drv_report -expanded_views -report_dir $out/fresh -report_prefix fresh
set names [tri_oracle_sram_core_drv_targets [exec gzip -dc $out/fresh/fresh.tran.gz] max_tran 9]
if {[llength $names] != 8} {error "Complete9-row/8-net victim inventory differs"}
set f [open $out/drivers.tsv w]
puts $f "net\tdriver_pin\tinstance\tmaster\tlocation\tprotected\tnet_protected\tloads\tfast_hold_slack_ns\tslow_setup_slack_ns"
foreach name $names {
    set n [get_db nets $name]
    foreach p [get_db $n .driver_pins] {
        set inst [get_db $p .inst]
        set p_name [get_db $p .name]
        set path [report_timing -early -view hold_fast -through [get_pins $p_name] -max_paths 1 -collection]
        set slack {}
        if {[sizeof_collection $path]} {set slack [get_property $path slack]}
        set setup_path [report_timing -view setup_slow -check_type setup -through [get_pins $p_name] -max_paths 1 -collection]
        set setup_slack {}
        if {[sizeof_collection $setup_path]} {set setup_slack [get_property $setup_path slack]}
        puts $f [join [list $name $p_name [get_db $inst .name] [get_db $inst .base_cell.name] \
            [get_db $inst .location] [get_db $inst .dont_touch_effective] [get_db $n .dont_touch] \
            [llength [get_db $n .load_pins]] $slack $setup_slack] \t]
    }
    foreach p [get_db $n .driver_ports] {puts $f [join [list $name [get_db $p .name] external {} {} {} [get_db $n .dont_touch] [llength [get_db $n .load_pins]] {}] \t]}
}
close $f
set f [open $out/hold_policy.rpt w]
foreach a {opt_hold_allow_resize opt_hold_cells opt_hold_target_slack opt_setup_target_slack} {puts $f "$a: [get_db $a]"}
puts $f "available_delay_masters: [get_db [get_db base_cells DEL*] .name]"
close $f
puts TRI_ORACLE_SRAM_CORE_DRIVER_MEASUREMENT37_FINISHED
exit
