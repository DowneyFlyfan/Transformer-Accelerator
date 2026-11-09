# Read-only characterization of this installed Common UI point return shape.
source syn/tri_oracle_memory_physical_config.tcl
set_multi_cpu_usage -local_cpu 20
read_db $out/postroute_measured_endpoint_unplaced.db
tri_oracle_require_memory_design
set report $out/native_endpoint_point_values.rpt
if {![catch {file lstat $report ignored}]} {error "Refusing existing native point evidence"}
set channel [open $report w]
foreach name {{core/activation_base_reg[0]} {core/cache/memory_reg[0][50]} {reader/gamma_word_reg[38]}} {
    set inst [get_db insts $name]
    if {[llength $inst] != 1 || [get_db $inst .name] ne $name} {error "Missing exact point probe target"}
    set point [get_db $inst .location]
    puts $channel [list instance $name point $point outer_length [llength $point] \
        first_element_length [llength [lindex $point 0]]]
}
close $channel
puts "TRI_ORACLE_MEMORY_NATIVE_POINTS_FINISHED"
exit
