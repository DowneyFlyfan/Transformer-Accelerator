source syn/tri_oracle_physical_config.tcl
set_multi_cpu_usage -local_cpu 18
read_db $out/placed_unfrozen.db
# Database reload may reread the original exported constraints. Ensure the
# synthesis-only hierarchy freeze remains released before physical repair.
source syn/tri_oracle_release_feedforward_core.tcl
tri_oracle_release_feedforward_core
set_db cts_buffer_cells {CKBD1BWP12T40P140 CKBD2BWP12T40P140 CKBD4BWP12T40P140 CKBD8BWP12T40P140 CKBD12BWP12T40P140}
set_db cts_inverter_cells {CKND1BWP12T40P140 CKND2BWP12T40P140 CKND4BWP12T40P140 CKND8BWP12T40P140}
# place_opt_design V2 requires clock_opt_design, as documented by Cadence.
clock_opt_design -report_dir $out/clock_reports
write_db $out/clocked.db
report_timing > $out/postcts_setup.rpt
report_timing -early > $out/postcts_hold.rpt
route_design
write_db $out/routed_before_optimization.db
source $root/syn/tri_oracle_finish_route.tcl
exit
