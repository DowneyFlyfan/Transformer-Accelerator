# Re-read the actual mapped netlist with another supplied timing corner.
set_db max_cpus 18
set top tri_oracle_pe_array
set output .cache/physical/corner_checks/$::env(TRI_ORACLE_CORNER)
file mkdir $output
read_libs $::env(TRI_ORACLE_LIBS)
read_hdl -sv .cache/physical/synthesis/${top}/netlist.v
elaborate $top
check_design -unresolved
read_sdc .cache/physical/synthesis/${top}/constraints.sdc
check_timing_intent -verbose > ${output}/timing_intent.rpt
report_timing > ${output}/setup.rpt
report_area > ${output}/area.rpt
puts "TRI_ORACLE_CORNER_CHECK_PASS $::env(TRI_ORACLE_CORNER)"
exit
