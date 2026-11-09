# Test the trace admission against the real failed router output and the
# successful reader's native format. The tiny timing file is only a fixture.
set root .cache/router_timing_trace_test_[pid]
if {[file exists $root]} {error "Refusing an existing temporary fixture"}
file mkdir $root
set status [catch {
    source syn/tri_oracle_router_timing_interface.tcl
    set timing [file normalize $root/router.tif]
    set file [open $timing w];puts $file "trace-test fixture";close $file
    set good "#Start reading timing information from file $timing ...\n#Read in timing information for 2735 ports, 710619 instances from timing file $timing.\n"
    set report $root/router.rpt
    set file [open $report w];puts -nonewline $file $good;close $file
    set counts [tri_oracle_require_router_timing_trace $report $timing]
    if {[dict get $counts ports] != 2735 || [dict get $counts instances] != 710619} {error "Wrong consumed timing inventory"}
    foreach bad [list \
        "#Start reading timing information from file $timing ...\n" \
        [string map [list $timing ${timing}_wrong] $good] \
        [string map {710619 0} $good] \
        "$good#Start reading timing information from file $timing ...\n" \
        "$good#Start reading timing information from file ${timing}_wrong ...\n" \
        "$good#Read in timing information for 2735 ports, 710619 instances from timing file $timing.\n" \
        "$good#WARNING (NRDB-121) No slack were found on nets, SI driven not effective.\n"] {
        set file [open $report w];puts -nonewline $file $bad;close $file
        if {![catch {tri_oracle_require_router_timing_trace $report $timing}]} {error "Bad timing-consumption trace admitted"}
    }
    set real .cache/physical/pnr/tri_oracle_feedforward_core/postroute_wire_spread_console.log
    if {![catch {tri_oracle_require_router_timing_trace $real $timing}]} {error "Actual missing-file router trace admitted"}
    puts "PASS: completed exact-file timing consumption required; actual failed router trace rejected"
} message options]
file delete -force $root
if {$status} {puts stderr $message;exit 1}
