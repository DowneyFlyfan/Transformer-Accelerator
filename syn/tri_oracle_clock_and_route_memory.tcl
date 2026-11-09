source syn/tri_oracle_memory_physical_config.tcl
set_multi_cpu_usage -local_cpu 20
read_db $out/placed.db
tri_oracle_require_memory_design
source syn/tri_oracle_release_memory_core.tcl
tri_oracle_release_memory_core
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db cts_buffer_cells {CKBD1BWP12T40P140 CKBD2BWP12T40P140 CKBD4BWP12T40P140 CKBD8BWP12T40P140 CKBD12BWP12T40P140}
set_db cts_inverter_cells {CKND1BWP12T40P140 CKND2BWP12T40P140 CKND4BWP12T40P140 CKND8BWP12T40P140}
# place_opt_design V2 requires clock_opt_design, as documented by Cadence.
clock_opt_design -report_dir $out/clock_reports
write_db $out/clocked.db
report_timing > $out/postcts_setup.rpt
report_timing -early > $out/postcts_hold.rpt
route_design
write_db $out/routed_before_optimization.db
# Keep initial routing separate from memory-heavy post-route repair.
puts "TRI_ORACLE_MEMORY_INITIAL_ROUTE_FINISHED"
exit
