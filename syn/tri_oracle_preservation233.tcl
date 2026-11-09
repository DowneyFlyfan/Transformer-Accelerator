# Preserve exact objects independently of timing-only write_sdc exports.
proc tri233_preservation {source_sdc filename expected_count} {
    set input [open $source_sdc r]
    set targets [dict create]
    while {[gets $input line]>=0} {
        set line [string trim $line]
        if {![string match {set_dont_touch *} $line]} {continue}
        if {![regexp {^set_dont_touch \[get_cells \{([^{}]+)\}\]$} $line -> name] &&
            ![regexp {^set_dont_touch \[get_cells ([A-Za-z0-9_/]+)\]$} $line -> name]} {
            close $input;error "TRI223_UNSUPPORTED_PRESERVATION_SELECTOR $line"
        }
        if {[dict exists $targets $name]} {close $input;error "TRI223_DUPLICATE_PRESERVATION_TARGET $name"}
        dict set targets $name 1
    }
    close $input
    if {[dict size $targets]!=$expected_count || $expected_count<1} {error TRI223_PRESERVATION_TARGET_COUNT}
    set stream [open $filename w]
    puts $stream "expected_object\tactual_object\tdont_touch"
    foreach name [lsort [dict keys $targets]] {
        # Protection is physical metadata. Use database objects in placement
        # view; timing collections are unsupported in that view.
        set physical [get_db insts $name]
        set hierarchical [get_db hinsts $name]
        if {[llength $physical]+[llength $hierarchical]!=1} {close $stream;error "TRI223_PRESERVATION_TARGET_NOT_UNIQUE $name"}
        if {[llength $physical]==1} {set object [lindex $physical 0]} else {set object [lindex $hierarchical 0]}
        set actual [get_db $object .name]
        set protected [get_db $object .dont_touch]
        puts $stream "$name\t$actual\t$protected"
        if {$actual ne $name} {close $stream;error "TRI223_PRESERVATION_TARGET_NAME_CHANGED $name $actual"}
        if {![string is boolean -strict $protected]} {close $stream;error "TRI233_UNSUPPORTED_PRESERVATION_VALUE $name $protected"}
        if {!$protected} {close $stream;error "TRI223_PRESERVATION_TARGET_NOT_PROTECTED $name"}
    }
    close $stream
}
