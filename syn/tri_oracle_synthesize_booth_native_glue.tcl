set root [file dirname [file dirname [file normalize [info script]]]]
set trial $::env(TRI_ORACLE_GLUE_WORK)
set_db auto_super_thread false
set_db auto_ungroup none
read_libs "$root/.cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib"
read_hdl "$trial/before/source.v"
elaborate tri_oracle_boundary_control
check_design -unresolved
syn_generic
syn_map
syn_opt
check_design -unresolved > "$trial/mapped/check.rpt"
write_hdl > "$trial/mapped/netlist.v"
puts TRI_ORACLE_GLUE_GENUS_PASS
exit
