set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set output $::env(TRI_ORACLE_POSTOPT205_OUTPUT)
set_db fail_on_error_mesg true
read_db $root/.cache/physical/synthesis/tri_oracle_predicted_feedforward_resume199/postopt_candidate.db
set_db max_cpus_per_server 20
set input [open $root/.cache/physical/synthesis/tri_oracle_postopt204_probe/undriven.rpt r]
set report [read $input];close $input
set rows [open $output/wrapper_cones.tsv w]
puts $rows "pin\tdirection\touter_net\touter_constant\touter_leaf_loads\touter_top_loads\touter_leaf_drivers\touter_top_drivers\tinner_net\tinner_constant\tinner_leaf_loads\tinner_top_loads\tinner_leaf_drivers\tinner_top_drivers"
set count 0
foreach line [split $report "\n"] {
    if {![regexp {^(hpin:[^[:space:]]+)[[:space:]]+\(fanout[[:space:]]*:[[:space:]]*([0-9]+)\)[[:space:]]*$} $line -> pin fanout]} {continue}
    if {$fanout!=0} {error POSTOPT205_LIVE_HIERARCHICAL_FANOUT}
    set fields [list [get_db $pin .name] [get_db $pin .direction]]
    foreach net [list [get_db $pin .net] [get_db $pin .hport.net]] {
        if {[llength $net]>1} {error POSTOPT205_NONUNIQUE_FLAT_NET}
        lappend fields [get_db $net .name] [get_db $net .constant] \
            [llength [get_db $net .load_pins]] [llength [get_db $net .load_ports]] \
            [llength [get_db $net .driver_pins]] [llength [get_db $net .driver_ports]]
    }
    puts $rows [join $fields "\t"]
    incr count
}
close $rows
if {$count!=32106} {error "POSTOPT205_WRONG_UNDRIVEN_OBLIGATIONS $count"}
puts "POSTOPT205_AUDITED_WRAPPER_PINS $count"
check_design -unresolved > $output/unresolved.rpt
check_design -undriven -multiple_driver -cross_hier > $output/wiring.rpt
write_sdc > $output/restored.sdc
write_hdl > $output/mapped.v
puts TRI_ORACLE_POSTOPT205_PROBE_COMPLETED
exit
