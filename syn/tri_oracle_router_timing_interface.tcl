# Saved databases may retain an earlier process's transient timing filename.
# CTE is the installed router's verified default engine token; an empty string
# is read back as literal braces and does not reset this setting.
proc tri_oracle_reset_router_timing {} {
    set previous [eval_legacy {getNanoRouteMode -timingEngine}]
    eval_legacy {setNanoRouteMode -timingEngine CTE}
    if {[eval_legacy {getNanoRouteMode -timingEngine}] ne {CTE}} {
        error "Router timing engine did not reset to its verified default"
    }
    puts "TRI_ORACLE_ROUTER_TIMING_RESET [list $previous] CTE"
}

# The native timing file is opaque. Generate it afresh and never modify it.
# This installed release maps no Common UI command for writeDesignTiming;
# eval_legacy is the documented bridge to its separate legacy interpreter.
proc tri_oracle_export_router_timing {filename} {
    if {![catch {file lstat $filename ignored}]} {
        error "Refusing existing router timing file: $filename"
    }
    set filename [file normalize $filename]
    if {![catch {file lstat $filename ignored}]} {
        error "Refusing existing router timing file: $filename"
    }
    tri_oracle_reset_router_timing
    set started [clock seconds]
    if {[llength [info commands write_design_timing]]} {
        write_design_timing $filename
    } else {
        set mapping [get_common_ui_map writeDesignTiming]
        if {$mapping ne {}} {error "Unexpected timing-export command mapping: $mapping"}
        eval_legacy [list writeDesignTiming $filename]
    }
    file lstat $filename generated
    if {$generated(type) ne {file} || $generated(size) <= 0 || $generated(mtime) < $started} {
        error "Native timing export is missing, empty, linked or stale: $filename"
    }
    eval_legacy [list setNanoRouteMode -timingEngine $filename]
    set engine [eval_legacy {getNanoRouteMode -timingEngine}]
    if {$engine ne $filename} {error "Router timing filename readback disagrees: $engine"}
    puts "TRI_ORACLE_ROUTER_TIMING_EXPORTED [list $filename] $generated(size)"
    return $filename
}

# Require the native router to finish reading the exact timing file supplied
# for this process. A saved setting or a start-reading message is insufficient.
proc tri_oracle_require_router_timing_trace {report timing} {
    foreach path [list $report $timing] {
        if {![file isfile $path] || [file size $path] == 0} {
            error "Missing nonempty router timing evidence: $path"
        }
    }
    if {[file size $report] > 67108864} {error "Router timing trace exceeds the bounded reader"}
    set channel [open $report r]
    try {set text [read $channel]} finally {close $channel}
    if {[regexp -nocase {NRIG-87|NRCM-25|NRDB-187|NRDB-121|SI driven not effective|No slack were found|\*\*ERROR|\*\*FATAL} $text]} {
        error "Router timing guidance failed in $report"
    }
    set timing [file normalize $timing]
    set pending false
    set completed {}
    foreach line [split $text \n] {
        if {[regexp {^#Start reading timing information from file (.+) \.\.\.$} $line -> requested]} {
            if {$requested ne $timing || $pending} {error "Mismatched or overlapping router timing reads"}
            set pending true
        }
        if {[regexp {^#Read in timing information for ([0-9]+) ports, ([0-9]+) instances from timing file (.+)\.$} $line -> ports instances consumed]} {
            if {$consumed ne $timing || !$pending || $ports <= 0 || $instances <= 0} {
                error "Router consumed missing, empty or different timing data"
            }
            set completed [dict create ports $ports instances $instances timing_file $timing]
            set pending false
        }
    }
    if {$pending || $completed eq {}} {error "No completed exact-file router timing read in $report"}
    return $completed
}

# Local geometric ECO completes only the changed connections. Its acceptance
# requires native completion/geometry evidence; full signal-integrity and
# timing qualification remain separate. It makes no timing-file-read claim.
proc tri_oracle_require_geometric_eco_trace {report} {
    if {![file isfile $report] || [file size $report] == 0 || [file size $report] > 67108864} {
        error "Missing or oversized geometric ECO evidence: $report"
    }
    set channel [open $report r]
    try {set text [read $channel]} finally {close $channel}
    if {[regexp -nocase {NRIF-78|NRIG-87|NRCM-25|NRDB-187|NRDB-121|\*\*ERROR|\*\*FATAL} $text]} {
        error "Native geometric ECO diagnostics require investigation"
    }
    if {[regexp -all -line {^TRI_ORACLE_LOCAL_ECO_MODE false false$} $text] != 1 ||
        [regexp -line {^route_with_(timing|si)_driven[ \t]+true[ \t]*$} $text]} {
        error "Geometric ECO routing mode was not verified"
    }
    foreach label {{DRC violations} {process antenna violations} {net violated process antenna rule}} {
        set pattern [format {^#Total number of %s = ([0-9]+)$} $label]
        set totals [regexp -all -line -inline $pattern $text]
        if {[llength $totals] == 0 || [lindex $totals end] != 0} {
            error "Missing or nonzero final geometric ECO count: $label"
        }
    }
    if {![regexp -line {^#route_detail Statistics:$} $text] ||
        ![regexp -line {^# +Entire Command +\|[ 0-9:]+\|[ 0-9:]+\|[ 0-9.]+\|$} $text]} {
        error "Incomplete geometric ECO router execution"
    }
    return [dict create timing_driven false geometry_violations 0 antenna_violations 0]
}
