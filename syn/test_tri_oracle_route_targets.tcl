# Run with ordinary Tcl: the parser must reject unsupported repair reports.
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error $message}
}
try {
    source syn/tri_oracle_route_repair_targets.tcl
    set violation {CUTSPACING: ( Cut EolSpacing ) Regular Wire of Net core/words[7][25] & Regular Wire of Net core/n_55  ( VIA2 )}
    set bounds {Bounds : ( 723.750, 1182.925 ) ( 723.810, 1182.975 )}
    set report "$violation\n$bounds\n$violation\n$bounds\n"
    set names [tri_oracle_route_drc_targets $report]
    require {$names eq [list core/n_55 {core/words[7][25]}]} "Wrong or duplicated routed-net targets"
    require {[llength [tri_oracle_route_drc_targets {No DRC violations were found}]] == 0} "Clean report rejected"
    foreach bad [list {} $violation "SPACING: other violation\n$bounds" \
        [string map {VIA2 VIA9} "$violation\n$bounds"] \
        [string repeat "$violation\n$bounds\n" 200]] {
        require {[catch {tri_oracle_route_drc_targets $bad}]} "Unsupported or incomplete report admitted"
    }
    puts "PASS: bounded actual cut-spacing target extraction and unsupported-report rejection"
} on error {message options} {
    puts stderr $message
    exit 1
}
