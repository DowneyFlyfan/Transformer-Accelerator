# Common physical settings for independently checkpointed post-route passes.
# Clock, interface, uncertainty and library/corner constraints are unchanged.
if {$top ne "tri_oracle_feedforward_core"} {error "Feed-forward top required"}
set_multi_cpu_usage -local_cpu 20
source syn/tri_oracle_router_timing_interface.tcl
tri_oracle_reset_router_timing
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
source syn/tri_oracle_release_feedforward_core.tcl
tri_oracle_release_feedforward_core
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db opt_post_route_area_reclaim none
# Keep the original local optimizer target; this is not a clock/hold constraint.
set_db opt_hold_target_slack 0.020
# A separate process will perform setup recovery. Avoid retaining the combined
# flow's second hold graph after it has added hundreds of thousands of cells.
set_db opt_post_route_hold_recovery false
set_db opt_post_route_setup_recovery false
set_db timing_max_transition_use_si_transition true
set_db opt_post_route_report_si_transitions true
set_db opt_post_route_fix_si_transitions true
