# Use the supplied process-antenna rules and actual library diode cell. Keep the
# original rule deck and operating constraints; route only violating nets.
source syn/tri_oracle_physical_config.tcl
source syn/tri_oracle_require_clean_placement.tcl
if {$top ne "tri_oracle_memory_compute"} {error "Core-only antenna repair"}
set_multi_cpu_usage -local_cpu 18
read_db $out/routed.db
set tag $::env(TRI_ORACLE_PHYSICAL_STAGE)
set backup $out/${tag}_input.db
if {[file exists $backup]} {error "Refusing to overwrite antenna input backup"}
write_db -rc_extract $backup
check_antenna -out_file $out/${tag}_antenna_before.rpt
set file [open $out/${tag}_antenna_before.rpt r]
set text [read $file]
close $file
set names {}
foreach line [split $text \n] {
    if {[regexp {^Net (.+)$} $line -> name]} {lappend names $name}
}
set names [lsort -unique $names]
if {[llength $names] == 0 || [llength $names] > 100} {error "Expected a bounded nonempty antenna failing-net set"}
set diode ANTENNABWP12T40P140
if {[llength [get_db base_cells $diode]] != 1} {error "Required library antenna diode is absent"}
set_db route_detail_fix_antenna true
set_db route_antenna_diode_insertion true
set_db route_antenna_cell_name $diode
set file [open $out/${tag}_settings.rpt w]
foreach attribute {route_detail_fix_antenna route_antenna_diode_insertion route_antenna_cell_name} {
    puts $file "$attribute: [get_db $attribute]"
}
puts $file "selected_failing_nets: [llength $names]"
close $file
deselect_obj -all
foreach name $names {
    # The documented native simple pattern supports only * and ?. These report
    # names contain neither, so [] in indexed hierarchy remains literal.
    if {[regexp {[*?]} $name]} {error "Ambiguous antenna net pattern: $name"}
    set net [get_db nets $name]
    if {[llength $net] != 1 || [get_db $net .name] ne $name} {error "Missing or ambiguous antenna net: $name"}
    select_obj $net
}
puts "TRI_ORACLE_CORE_ANTENNA_SELECTED_NETS [llength $names]"
route_detail -selected
deselect_obj -all
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
check_place > $out/${tag}_placement.rpt
puts "TRI_ORACLE_CORE_ANTENNA_PLACEMENT_PASS [tri_oracle_require_clean_placement $out/${tag}_placement.rpt]"
check_antenna -out_file $out/${tag}_antenna_after.rpt
check_drc -out_file $out/${tag}_drc.rpt
check_connectivity -type all -out_file $out/${tag}_connectivity.rpt
report_timing -view setup_slow -check_type setup > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ -check_type setup > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_slow > $out/${tag}_electrical.rpt
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_CORE_ANTENNA_REPAIR_COMMANDS_FINISHED"
exit
