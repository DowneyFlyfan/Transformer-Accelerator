# Observe full-model collection properties without changing any design flag.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI232_OUT)
read_db $::env(TRI232_INPUT)
set_multi_cpu_usage -local_cpu 8
unflatten_ilm
set stream [open $out/raw_preservation.tsv w]
puts $stream "expected_object\tactual_object\tget_db_dont_touch\tis_boolean\tphysical_count\thierarchical_count\tkind"
set input [open $root/.cache/physical/synthesis/tri_oracle_predicted_feedforward_finish213/constraints.sdc r]
set count 0
while {[gets $input line]>=0} {
    set line [string trim $line]
    if {![string match {set_dont_touch *} $line]} {continue}
    if {![regexp {^set_dont_touch \[get_cells \{([^{}]+)\}\]$} $line -> name] &&
        ![regexp {^set_dont_touch \[get_cells ([A-Za-z0-9_/]+)\]$} $line -> name]} {error RAW232_UNSUPPORTED_SELECTOR}
    set physical [get_db insts $name]
    set hierarchical [get_db hinsts $name]
    if {[llength $physical]+[llength $hierarchical]!=1} {error "RAW232_AMBIGUOUS_OBJECT $name"}
    if {[llength $physical]==1} {set object [lindex $physical 0];set kind physical} else {set object [lindex $hierarchical 0];set kind hierarchical}
    set raw [get_db $object .dont_touch]
    puts $stream [join [list $name [get_db $object .name] $raw [string is boolean -strict $raw] [llength $physical] [llength $hierarchical] $kind] "\t"]
    flush $stream
    incr count
}
close $input
close $stream
if {$count!=86} {error RAW232_WRONG_TARGET_COUNT}
puts TRI_ORACLE_RAW232_PROPERTIES_COLLECTED
exit
