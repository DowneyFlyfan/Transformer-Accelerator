# Check the receiver clock in the same timing harness as the loaded-pad study.
set root [file dirname [file dirname [file normalize [info script]]]]
set input $root/.cache/physical/whole_chip_xcelium_speed/loaded_forwarded_pads
set out [file normalize $::env(TRI_ORACLE_FORWARDED_CLOCK_OUTPUT)]
set_multi_cpu_usage -local_cpu 4
set_db design_process_node 28
set_db init_power_nets {VDD VDDPST}
set_db init_ground_nets {VSS VSSPST}
read_mmmc $input/tx_load_mmmc.tcl
read_physical -lefs [list \
    $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
    $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef $input/pads.lef]
read_netlist $input/netlist.v -top tri_oracle_loaded_request_pads
init_design
set receiver peer_capture_0/CP
if {[sizeof_collection [get_pins $receiver]] != 1} {error "FORWARDED_CLOCK_RECEIVER_MISSING"}
set setup_views {}
set hold_views {}
foreach id {c5_d5 c5_d10 c10_d5 c10_d10 c5_d25 c25_d5} {
    lappend setup_views setup_$id
    lappend hold_views hold_$id
}
# Innovus computes the minimum pulse-width check in late analysis at each corner.
set_analysis_view -setup [concat $setup_views $hold_views] -hold $hold_views
foreach view [concat $setup_views $hold_views] {
    report_min_pulse_width -pins $receiver -path_type full_clock -view $view > $out/${view}.rpt
}
puts TRI_ORACLE_FORWARDED_CLOCK_PULSE_FINISHED
exit
