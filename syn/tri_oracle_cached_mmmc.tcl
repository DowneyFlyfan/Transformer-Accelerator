# Multiple-mode, multiple-corner setup for the selected physical block.
source syn/tri_oracle_cached_physical_config.tcl
set libroot $root/.cache/physical/library
create_library_set -name ls_typ -timing [list $libroot/tcbn28hpcplusbwp12t40p140tt1v25c.lib]
create_library_set -name ls_slow -timing [list $libroot/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib]
create_library_set -name ls_fast -timing [list $libroot/tcbn28hpcplusbwp12t40p140ffg1p05vm40c.lib]
create_rc_corner -name rc_typ -qrc_tech $root/.cache/physical/rc/qrc_typical -temperature 25
create_rc_corner -name rc_slow -qrc_tech $root/.cache/physical/rc/qrc_rcworst -temperature 125
create_rc_corner -name rc_fast -qrc_tech $root/.cache/physical/rc/qrc_rcbest -temperature -40
create_timing_condition -name tc_typ -library_sets {ls_typ}
create_timing_condition -name tc_slow -library_sets {ls_slow}
create_timing_condition -name tc_fast -library_sets {ls_fast}
create_delay_corner -name dc_typ -timing_condition tc_typ -rc_corner rc_typ
create_delay_corner -name dc_slow -timing_condition tc_slow -rc_corner rc_slow
create_delay_corner -name dc_fast -timing_condition tc_fast -rc_corner rc_fast
create_constraint_mode -name functional -sdc_files [list $root/.cache/physical/synthesis/$top/constraints.sdc]
create_analysis_view -name setup_typ -constraint_mode functional -delay_corner dc_typ
create_analysis_view -name setup_slow -constraint_mode functional -delay_corner dc_slow
create_analysis_view -name hold_fast -constraint_mode functional -delay_corner dc_fast
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
