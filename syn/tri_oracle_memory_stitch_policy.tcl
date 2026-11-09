# A stitch pass is explicitly geometric and may retain bounded DRC failures.
# Only command completion is admitted here; this is never physical closure.
proc tri_oracle_memory_stitch_evidence {text} {
    if {$text eq {} || [string length $text] > 67108864 ||
        [regexp -nocase {NRIF-78|NRIG-87|NRCM-25|NRDB-187|NRDB-121|\*\*ERROR|\*\*FATAL} $text]} {
        error "Missing or erroneous geometric stitch evidence"
    }
    if {[regexp -all -line {^TRI_ORACLE_MEMORY_GEOSTITCH_MODE false false true true$} $text] != 1 ||
        [regexp -all -line {^TRI_ORACLE_MEMORY_GEOSTITCH_CLOCK_MODE true false$} $text] != 1 ||
        [regexp -line {^route_with_(timing|si)_driven[ \t]+true[ \t]*$} $text]} {
        error "Geometric stitch mode was not verified"
    }
    set result [dict create commands_completed true timing_driven false physical_closure_passed false]
    foreach {label key} {{DRC violations} geometry_violations {process antenna violations} antenna_violations {net violated process antenna rule} antenna_nets} {
        set values [regexp -all -line -inline [format {^#Total number of %s = ([0-9]+)$} $label] $text]
        if {[llength $values] < 2 || [lindex $values end] > 1000} {error "Missing/unbounded intermediate stitch diagnostic"}
        dict set result $key [lindex $values end]
    }
    set fails [regexp -all -line -inline {^#Total number of fails = ([0-9]+)$} $text]
    if {[llength $fails] != 2 || [lindex $fails 1] != 0 ||
        [regexp -all -line {^#Complete route_global_detail on .+$} $text] != 1 ||
        ![regexp -line {^#route_global_detail [Ss]tatistics:$} $text] ||
        ![regexp -line {^# +Entire Command +\|[ 0-9:]+\|[ 0-9:]+\|[ 0-9.]+\|$} $text]} {
        error "Incomplete or failed geometric stitch execution"
    }
    return $result
}
proc tri_oracle_memory_connected_evidence {text} {
    if {$text eq {} || [string length $text] > 2097152 ||
        [regexp -nocase {\*\*(ERROR|WARN|FATAL)} $text] ||
        [regexp -nocase -line {^[ \t]*#?[ \t]*(ERROR|WARN|WARNING|FATAL)(:|[ \t])} $text]} {
        error "Missing or diagnostic-bearing connectivity report"
    }
    set designs [regexp -all -line -inline {^#[ \t]*Design:[ \t]*(\S+)[ \t]*$} $text]
    set summaries [regexp -all -inline {Begin Summary\s*(.*?)\s*End Summary} $text]
    if {[llength $designs] != 2 || [lindex $designs 1] ne {tri_oracle_memory_feedforward_core} ||
        [llength $summaries] != 2 || [string trim [lindex $summaries 1]] ne {Found no problems or warnings.}} {
        error "Open, incomplete or conflicting connectivity result"
    }
    return 1
}
