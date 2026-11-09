source syn/tri_oracle_physical_config.tcl
read_db $out/postroute_hold_pass.db
source syn/tri_oracle_feedforward_postroute_settings.tcl
set tag postroute_setup_pass
# Without -hold, post-route optimization performs setup/design-rule recovery.
# Explicit -setup belongs only to the combined post-route -setup -hold form.
opt_design -post_route -report_dir $out/${tag}_reports -report_prefix $tag
check_place > $out/${tag}_placement.rpt
source syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/${tag}_placement.rpt
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_FEEDFORWARD_SETUP_CHECKPOINT_WRITTEN"
report_timing -view setup_slow > $out/${tag}_setup_slow.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
# No timing-closure verdict follows from this completion marker. The separate
# qualifier restores all original views and checks every physical report.
puts "TRI_ORACLE_FEEDFORWARD_SETUP_PASS_COMMANDS_FINISHED"
exit
