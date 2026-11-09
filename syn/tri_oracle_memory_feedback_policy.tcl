# Cache-only policy for the directly measured multiplexed-flop feedback path.
source syn/tri_oracle_endpoint_hold_policy.tcl

proc tri_oracle_memory_feedback_admit {launch capture base_cell slack direct_connection} {
    tri_oracle_finite_timing_value $slack
    if {$slack >= 0 || $slack < -0.020} {
        error "Cache feedback policy covers negative deficits no greater than0.020ns"
    }
    if {![regexp {^core/cache/memory_reg\[(0|[1-9][0-9]*)\]\[(0|[1-9][0-9]*)\]/CP$} \
        $launch -> row bit]} {
        error "Unmeasured cache feedback launch: $launch"
    }
    if {$row >= 512 || $bit >= 80} {error "Cache register outside512x80 capacity: $launch"}
    set cell [string range $launch 0 [expr {[string last / $launch]-1}]]
    if {$capture ne "${cell}/DA"} {error "Feedback must reach the same cache cell DA pin"}
    if {![regexp {^DFMQD[124]BWP12T40P140$} $base_cell]} {
        error "Uncharacterized feedback cell: $base_cell"
    }
    if {$direct_connection ne "1"} {error "Direct Q-to-DA net identity is not verified"}
    return $capture
}

proc tri_oracle_memory_feedback_headroom {endpoint slacks} {
    # Largest bound slow DEL100 table delay is0.404781ns. The threshold keeps
    # 0.045219ns admission reserve; routed setup must still be independently checked.
    foreach view {setup_slow setup_typ} {
        if {![dict exists $slacks $view]} {error "Missing $view setup headroom at $endpoint"}
        set slack [dict get $slacks $view]
        tri_oracle_finite_timing_value $slack
        if {$slack < 0.450} {error "Insufficient $view setup reserve at $endpoint: $slack"}
    }
}

proc tri_oracle_memory_feedback_count {count} {
    if {![string is integer -strict $count] || $count < 1 || $count > 40960} {
        error "Expected a nonempty unique cache feedback set within512x80 capacity"
    }
    return $count
}
