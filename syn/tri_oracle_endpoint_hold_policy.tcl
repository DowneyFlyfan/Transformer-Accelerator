# Pure admission checks shared by the physical repair and ordinary Tcl tests.
proc tri_oracle_finite_timing_value {value} {
    if {![string is double -strict $value]} {error "Non-numeric timing value: $value"}
    if {[catch {expr {abs($value) < 1000000}} finite] || !$finite} {
        error "Non-finite or out-of-range timing value: $value"
    }
}

proc tri_oracle_endpoint_hold_kind {launch capture slack} {
    tri_oracle_finite_timing_value $slack
    if {$slack >= 0 || $slack < -0.050} {
        error "Endpoint delay policy covers only negative hold deficits up to 0.050ns"
    }
    if {[regexp {^(.+)/CP$} $launch -> launch_cell] &&
        [regexp {^(.+)/(D|DB|SI)$} $capture -> capture_cell data_pin] &&
        $launch_cell eq $capture_cell} {
        return feedback
    }
    # Exact non-feedback paths measured in the two cold routed reports.
    if {$launch eq {cfg_weight_base[57]} && $capture eq {gate_base_reg[57]/D}} {
        return configuration
    }
    if {$launch eq {cfg_output_count[4]} && $capture eq {output_count_reg[4]/D}} {
        return configuration
    }
    if {$launch eq {cfg_dense_features[13]} && $capture eq {dense_features_reg[13]/D}} {
        return configuration
    }
    if {$launch eq {norm_activations[92]} && $capture eq {prediction/predictor/outlier_acc_reg[0]/D}} {
        return activation
    }
    error "Unmeasured hold path: $launch -> $capture"
}

proc tri_oracle_endpoint_hold_next_index {existing_names} {
    set next_index 0
    foreach name $existing_names {
        if {![regexp {(^|/)TRI_ENDPOINT_HOLD_(0|[1-9][0-9]*)$} $name -> prefix index]} {
            error "Unrecognized existing endpoint-delay instance: $name"
        }
        if {$index >= $next_index} {set next_index [expr {$index + 1}]}
    }
    return $next_index
}

proc tri_oracle_endpoint_hold_headroom {endpoint slacks {delay_cell DEL100D1BWP12T40P140}} {
    # DEL025 characterization: all slow I-to-Z table delays <=0.284924ns.
    # Its threshold retains >0.065ns admission reserve; actual routed timing
    # is still required. This is not a replacement for setup qualification.
    switch -- $delay_cell {
        DEL100D1BWP12T40P140 {set minimum 0.400}
        DEL025D1BWP12T40P140 {set minimum 0.350}
        default {error "Unsupported characterized endpoint-delay cell: $delay_cell"}
    }
    foreach view {setup_slow setup_typ} {
        if {![dict exists $slacks $view]} {error "Missing $view setup headroom at $endpoint"}
        set slack [dict get $slacks $view]
        tri_oracle_finite_timing_value $slack
        if {$slack < $minimum} {error "Insufficient $view setup headroom at $endpoint for $delay_cell: $slack"}
    }
}
