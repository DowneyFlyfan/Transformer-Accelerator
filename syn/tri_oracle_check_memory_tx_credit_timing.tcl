# Check the mapped request link without placement or routing.
set root [file dirname [file dirname [file normalize [info script]]]]
set out [file normalize $::env(TRI_ORACLE_TX_CREDIT_OUTPUT)]
set library $root/.cache/physical/library
# Express the peer's target phase as the falling edge of the source clock.
set source_sdc [open $out/constraints.sdc r]
set phase_sdc [open $out/peer_phase.sdc w]
while {[gets $source_sdc line] >= 0} {
    if {![string match *pad_sample_clock* $line]} {puts $phase_sdc $line}
}
close $source_sdc
puts $phase_sdc {set_clock_uncertainty 0.05 [get_clocks core_clock]}
puts $phase_sdc {set_output_delay -max 0.20 -clock [get_clocks core_clock] -clock_fall [get_ports {pad_data* pad_valid}]}
puts $phase_sdc {set_output_delay -min -0.10 -clock [get_clocks core_clock] -clock_fall [get_ports {pad_data* pad_valid}]}
close $phase_sdc
set mmmc [open $out/tx_credit_mmmc.tcl w]
foreach {name lib rc t} {
    slow tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib qrc_rcworst 125
    fast tcbn28hpcplusbwp12t40p140ffg1p05vm40c.lib qrc_rcbest -40
} {
    puts $mmmc [list create_library_set -name ls_$name -timing [list $library/$lib]]
    puts $mmmc [list create_rc_corner -name rc_$name -qrc_tech $root/.cache/physical/rc/$rc -temperature $t]
    puts $mmmc [list create_timing_condition -name tc_$name -library_sets [list ls_$name]]
    puts $mmmc [list create_delay_corner -name dc_$name -timing_condition tc_$name -rc_corner rc_$name]
}
puts $mmmc [list create_constraint_mode -name functional -sdc_files [list $out/peer_phase.sdc]]
puts $mmmc {create_analysis_view -name setup_slow -constraint_mode functional -delay_corner dc_slow}
puts $mmmc {create_analysis_view -name hold_fast -constraint_mode functional -delay_corner dc_fast}
puts $mmmc {set_analysis_view -setup {setup_slow} -hold {hold_fast}}
close $mmmc

set_multi_cpu_usage -local_cpu 4
set_db design_process_node 28
set_db init_power_nets {VDD}
set_db init_ground_nets {VSS}
read_mmmc $out/tx_credit_mmmc.tcl
read_physical -lefs [list \
    $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
    $library/tcbn28hpcplusbwp12t40p140.lef]
read_netlist $out/netlist.v -top tri_oracle_memory_tx_credit
init_design
set outputs [get_ports {pad_data* pad_valid}]
if {[sizeof_collection $outputs] != 9} {error "REQUEST_LINK_PAD_COUNT"}
report_timing -view setup_slow -to $outputs -max_paths 12 > $out/native_pad_setup.rpt
report_timing -early -view hold_fast -to $outputs -max_paths 12 > $out/native_pad_hold.rpt
report_timing -early -view hold_fast -from [get_ports pad_credit] -max_paths 2 > $out/native_return_hold.rpt
puts TRI_ORACLE_MEMORY_TX_CREDIT_TIMING_FINISHED
exit
