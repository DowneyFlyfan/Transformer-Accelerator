# Read-only admission measurements for residual timing/electrical repairs.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set checkpoint_root $root/.cache/physical/pnr/$top
set out $checkpoint_root/residual_probe_04
if {[file exists $out]} {error "Refusing existing residual probe"}
file mkdir $out
source syn/tri_oracle_signal_repair_targets.tcl
set_multi_cpu_usage -local_cpu 19
read_db $checkpoint_root/routed_power_trim_02.db
if {[get_db current_design .name] ne $top} {error "Wrong SRAM core"}
if {[llength [get_db insts]] != 95134} {error "Wrong source instance count"}
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db delaycal_enable_si true
set_db si_delay_enable_report true
proc emit {f fields} {puts $f [join $fields \t]}
set hold [report_timing -early -view hold_fast -collection -max_paths 10000 -nworst 1 -max_slack 0]
if {[sizeof_collection $hold] != 13} {error "Negative hold endpoint set differs"}
set hold_targets [copy_collection [get_property $hold capturing_point]]
set hf [open $out/hold_endpoints.tsv w]
emit $hf {launch endpoint slack_ns cell net driver_pins driver_ports}
foreach_in_collection p $hold {
    set pin [get_db [get_property $p capturing_point]]
    set inst [get_db $pin .inst]
    set net [get_db $pin .net]
    emit $hf [list [get_object_name [get_property $p launching_point]] \
        [get_object_name [get_property $p capturing_point]] [get_property $p slack] \
        [get_db $inst .base_cell.name] [get_db $net .name] \
        [get_db $net .driver_pins.name] [get_db $net .driver_ports.name]]
}
close $hf
set mf [open $out/hold_setup_margins.tsv w]
emit $mf {view endpoint setup_slack_ns}
foreach view {setup_slow setup_typ} {
    set paths [report_timing -view $view -check_type setup -to $hold_targets \
        -max_paths 10000 -nworst 1 -collection]
    if {[sizeof_collection $paths] != 13} {error "Incomplete hold-target setup margins"}
    foreach_in_collection p $paths {
        emit $mf [list $view [get_object_name [get_property $p capturing_point]] \
            [get_property $p slack]]
    }
}
close $mf
set setup [report_timing -view setup_slow -check_type setup -collection \
    -max_paths 10000 -nworst 1 -max_slack 0]
if {[sizeof_collection $setup] != 20} {error "Negative setup endpoint set differs"}
set sf [open $out/setup_endpoints.tsv w]
emit $sf {launch endpoint slack_ns endpoint_cell endpoint_net endpoint_driver_pins}
set launch_insts [dict create]
foreach_in_collection p $setup {
    set launch [get_object_name [get_property $p launching_point]]
    set pin [get_db [get_property $p capturing_point]]
    set capture [get_object_name [get_property $p capturing_point]]
    set net [get_db $pin .net]
    if {[string first / $capture] >= 0} {
        set inst [get_db $pin .inst]
        set cell [get_db $inst .base_cell.name]
    } else {
        set cell external_port
    }
    emit $sf [list $launch $capture [get_property $p slack] $cell \
        [get_db $net .name] [get_db $net .driver_pins.name]]
    if {[string first / $launch] >= 0} {
        set lp [get_db [get_property $p launching_point]]
        set li [get_db $lp .inst]
        dict set launch_insts [get_db $li .name] $li
    }
}
close $sf
set net_index [dict create]
foreach n [get_db nets] {dict set net_index [get_db $n .name] $n}
set noisy [tri_oracle_route_slew_targets [exec gzip -dc \
    $checkpoint_root/qualification_power_trim_02/qualification_si_reports/qualification_si.tran.gz]]
set cap [tri_oracle_route_drv_targets [exec gzip -dc \
    $checkpoint_root/qualification_power_trim_02/qualification_si_reports/qualification_si.cap.gz] max_cap]
if {[llength $noisy] < 1 || [llength $noisy] > 461 || [llength $cap] != 2} {
    error "Unexpected complete electrical target inventory"
}
set f [open $out/electrical_drivers.tsv w]
emit $f {role net clock connections wires driver instance cell location orient status dont_touch}
foreach role {noisy cap} {
    foreach name [set $role] {
        set net [dict get $net_index $name]
        foreach pin [get_db $net .driver_pins] {
            set inst [get_db $pin .inst]
            emit $f [list $role $name [get_db $net .is_clock] [get_db $net .num_connections] \
                [llength [get_db $net .wires]] [get_db $pin .name] [get_db $inst .name] \
                [get_db $inst .base_cell.name] [get_db $inst .location] [get_db $inst .orient] \
                [get_db $inst .place_status] [get_db $inst .dont_touch]]
        }
        foreach port [get_db $net .driver_ports] {
            emit $f [list $role $name [get_db $net .is_clock] [get_db $net .num_connections] \
                [llength [get_db $net .wires]] [get_db $port .name] external_port {} {} {} {} {}]
        }
    }
}
close $f
set f [open $out/setup_launch_cells.tsv w]
emit $f {instance cell location orient status output_pin net load_count}
dict for {name inst} $launch_insts {
    foreach pin [get_db $inst .pins] {
        if {[get_db $pin .direction] eq "out"} {
            set net [get_db $pin .net]
            emit $f [list $name [get_db $inst .base_cell.name] [get_db $inst .location] \
                [get_db $inst .orient] [get_db $inst .place_status] [get_db $pin .name] \
                [get_db $net .name] [llength [get_db $net .load_pins]]]
        }
    }
}
close $f
set f [open $out/complete.rpt w]
puts $f "hold_endpoints: 13"
puts $f "setup_endpoints: 20"
puts $f "noisy_unique_nets: [llength $noisy]"
puts $f "cap_unique_nets: [llength $cap]"
puts $f "physical_mutation_requested: false"
close $f
puts TRI_ORACLE_SRAM_CORE_RESIDUAL_PROBE_FINISHED
exit
