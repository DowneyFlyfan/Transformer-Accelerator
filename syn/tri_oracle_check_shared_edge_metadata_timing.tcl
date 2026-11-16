# Analyze the mapped receiver at both corners without placement or routing.
set root [file dirname [file dirname [file normalize [info script]]]]
set out [file normalize $::env(TRI_ORACLE_METADATA_OUTPUT)]
set library $root/.cache/physical/library
set mmmc [open $out/metadata_mmmc.tcl w]
foreach {name lib rc t} {
    slow tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib qrc_rcworst 125
    fast tcbn28hpcplusbwp12t40p140ffg1p05vm40c.lib qrc_rcbest -40
} {
    puts $mmmc [list create_library_set -name ls_$name -timing [list $library/$lib]]
    puts $mmmc [list create_rc_corner -name rc_$name -qrc_tech $root/.cache/physical/rc/$rc -temperature $t]
    puts $mmmc [list create_timing_condition -name tc_$name -library_sets [list ls_$name]]
    puts $mmmc [list create_delay_corner -name dc_$name -timing_condition tc_$name -rc_corner rc_$name]
}
puts $mmmc [list create_constraint_mode -name functional -sdc_files [list $out/constraints.sdc]]
puts $mmmc {create_analysis_view -name setup_slow -constraint_mode functional -delay_corner dc_slow}
puts $mmmc {create_analysis_view -name hold_fast -constraint_mode functional -delay_corner dc_fast}
puts $mmmc {set_analysis_view -setup {setup_slow} -hold {hold_fast}}
close $mmmc

set_multi_cpu_usage -local_cpu 4
set_db design_process_node 28
set_db init_power_nets {VDD}
set_db init_ground_nets {VSS}
read_mmmc $out/metadata_mmmc.tcl
read_physical -lefs [list \
    $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
    $library/tcbn28hpcplusbwp12t40p140.lef]
read_netlist $out/netlist.v -top tri_oracle_credit_metadata_ingress
init_design
if {[sizeof_collection [get_ports pad_metadata*]] != 7} {error "SHARED_METADATA_PORT_COUNT"}
set cases [list \
    {6 rising_valid_reg falling_valid_reg} \
    {5 out_words_reg[2] out_words_reg[5]} \
    {4 out_words_reg[1] out_words_reg[4]} \
    {3 out_words_reg[0] out_words_reg[3]} \
    {2 out_compact_reg[0] out_compact_reg[1]} \
    {1 out_last_reg[0] out_last_reg[1]} \
    {0 out_error_reg[0] out_error_reg[1]}]
foreach entry $cases {
    lassign $entry bit rise fall
    set source [get_ports [format {pad_metadata[%d]} $bit]]
    foreach {edge instance} [list rise $rise fall $fall] {
        set endpoint [get_cells receiver/capture/$instance]
        if {[sizeof_collection $source] != 1 || [sizeof_collection $endpoint] != 1} {
            error "METADATA_ENDPOINT_MISSING $bit $edge $instance"
        }
        report_timing -view setup_slow -from $source -to $endpoint -max_paths 1 > $out/setup_metadata_${bit}_${edge}.rpt
        report_timing -early -view hold_fast -from $source -to $endpoint -max_paths 1 > $out/hold_metadata_${bit}_${edge}.rpt
    }
}
puts TRI_ORACLE_SHARED_EDGE_CORNERS_FINISHED
exit
