set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set output $::env(TRI_ORACLE_POSTOPT204_OUTPUT)
set_db fail_on_error_mesg true
read_db $root/.cache/physical/synthesis/tri_oracle_predicted_feedforward_resume199/postopt_candidate.db
set_db max_cpus_per_server 20
check_design -unresolved > $output/unresolved.rpt
check_design -undriven -multiple_driver -cross_hier > $output/wiring.rpt
check_design -undriven > $output/undriven.rpt
check_design -multiple_driver > $output/multiple_driver.rpt
check_design -cross_hier > $output/cross_hier.rpt
puts "POSTOPT204_STATUS unresolved=[check_design -unresolved -status] undriven=[check_design -undriven -status] multiple_driver=[check_design -multiple_driver -status] cross_hier=[check_design -cross_hier -status]"
write_sdc > $output/restored.sdc
write_hdl > $output/mapped.v
report_timing -max_paths 20 > $output/timing.rpt
report_area > $output/area.rpt
puts TRI_ORACLE_POSTOPT204_PROBE_COMPLETED
exit
