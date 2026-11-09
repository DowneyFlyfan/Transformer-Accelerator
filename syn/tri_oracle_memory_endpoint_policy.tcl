# Measured policy for the complete cold inventory. Unlike the older cache-only
# direct-Q policy, this admits same-cell data feedback even through prior
# noninverting routing buffers. Native cell identities and logical-equivalence
# checking are required by the repair; CP, SA, SE and reset are never targets.
source syn/tri_oracle_memory_feedback_policy.tcl

proc tri_oracle_memory_endpoint_kind {launch capture slack} {
    tri_oracle_finite_timing_value $slack
    if {$slack >= 0 || $slack < -0.050} {error "Unmeasured hold deficit: $slack"}
    set family {}
    if {[regexp {^core/cache/memory_reg\[(0|[1-9][0-9]*)\]\[(0|[1-9][0-9]*)\]/CP$} \
        $launch -> row bit]} {
        if {$row >= 512 || $bit >= 80} {error "Cache feedback outside512x80 capacity"}
        set family cache
        set pins {DA DB}
    } elseif {[regexp {^core/execution/core/core/storage\[(0|[1-9][0-9]*)\]\.(inputs|weights)/words_reg\[(0|[1-9][0-9]*)\]\[(0|[1-9][0-9]*)\]/CP$} \
        $launch -> bank family word bit]} {
        if {$bank >= 32 || $word >= 32 || $bit >= 64} {
            error "Storage feedback outside32banks x32words x64bits"
        }
        set pins {DB SI}
    }
    if {$family ne {}} {
        set cell [string range $launch 0 end-3]
        if {![regexp {^(.+)/(DA|DB|SI)$} $capture -> receiver pin] ||
            $receiver ne $cell || $pin ni $pins || $slack < -0.020} {
            error "Unmeasured same-cell memory data feedback: $launch -> $capture"
        }
        return $family/$pin
    }
    foreach pair {
        {cfg_activation_base[0] core/activation_base_reg[0]/D}
        {cfg_up_sign_base[46] core/up_sign_base_reg[46]/D}
        {cfg_raw_base[59] raw_base_reg[59]/D}
        {cfg_tag[9] core/preparation/normalizer/tag_reg[9]/D}
        {cfg_tag[29] core/preparation/normalizer/tag_reg[29]/D}
        {rsp_data[38] reader/gamma_word_reg[38]/D}
        {rsp_data[38] reader/gamma_word_reg[102]/D}
        {rsp_data[47] reader/gamma_word_reg[111]/D}
        {cfg_raw_base[43] raw_base_reg[43]/D}
    } {
        if {$launch eq [lindex $pair 0] && $capture eq [lindex $pair 1]} {
            return external_input
        }
    }
    error "Unmeasured endpoint pair: $launch -> $capture"
}

proc tri_oracle_memory_endpoint_cell {kind base_cell} {
    switch -- $kind {
        cache/DA - cache/DB - inputs/DB - weights/DB {
            set allowed {^DFMQD[124]BWP12T40P140$}
        }
        inputs/SI - weights/SI {set allowed {^SDFCNQD[0124]BWP12T40P140$}}
        external_input {set allowed {^SDFCNQD0BWP12T40P140$}}
        default {error "Unknown measured endpoint class: $kind"}
    }
    if {![regexp $allowed $base_cell]} {error "Uncharacterized $kind cell: $base_cell"}
}

proc tri_oracle_memory_endpoint_insertion {requested result} {
    if {[llength $result] != 3} {error "Expected one buffer and two native nets"}
    lassign $result instance input_net output_net
    set leaf [string range $instance [expr {[string last / $instance]+1}] end]
    if {$leaf ne $requested || $input_net eq {} || $output_net eq {} ||
        $input_net eq $output_net} {error "Native insertion identity/connectivity differs"}
    return $instance
}

proc tri_oracle_memory_endpoint_inventory {text} {
    set lines [split [string trimright $text \n] \n]
    if {[lindex $lines 0] ne "launch\tendpoint\thold_fast_ns\tsetup_slow_ns\tsetup_typ_ns"} {
        error "Missing measured endpoint inventory header"
    }
    set rows [dict create]
    set kinds [dict create]
    foreach line [lrange $lines 1 end] {
        set fields [split $line \t]
        if {[llength $fields] != 5} {error "Incomplete measured endpoint inventory row"}
        lassign $fields launch capture hold slow typical
        if {[dict exists $rows $capture]} {error "Duplicate measured endpoint: $capture"}
        set kind [tri_oracle_memory_endpoint_kind $launch $capture $hold]
        tri_oracle_memory_feedback_headroom $capture [list setup_slow $slow setup_typ $typical]
        dict set rows $capture [list $launch $hold $slow $typical $kind]
        dict incr kinds $kind
    }
    if {[dict size $rows] != 6568 || [dict size $kinds] != 7} {
        error "Measured inventory must contain all6568 endpoints and seven classes"
    }
    foreach {kind expected} {cache/DA 480 cache/DB 52 inputs/DB 841 weights/DB 167 \
        inputs/SI 4137 weights/SI 882 external_input 9} {
        if {![dict exists $kinds $kind] || [dict get $kinds $kind] != $expected} {
            error "Incomplete measured endpoint class: $kind"
        }
    }
    return $rows
}

proc tri_oracle_memory_endpoint_router_evidence {text} {
    # This checkpoint is deliberately diagnostic: it begins with independent
    # geometry/antenna failures. Preserve nonzero router counts for the next
    # repair; they can never establish physical closure, including when zero.
    if {$text eq {} || [string length $text] > 67108864 ||
        [regexp -nocase {NRIF-78|NRIG-87|NRCM-25|NRDB-187|NRDB-121|\*\*ERROR|\*\*FATAL} $text]} {
        error "Native endpoint routing trace requires investigation"
    }
    if {[regexp -all -line {^TRI_ORACLE_LOCAL_ECO_MODE false false$} $text] != 1 ||
        [regexp -line {^route_with_(timing|si)_driven[ \t]+true[ \t]*$} $text]} {
        error "Endpoint geometric routing mode was not verified"
    }
    set result [dict create physical_closure_passed false timing_driven false]
    foreach {label key} {{DRC violations} geometry_violations \
        {process antenna violations} antenna_violations \
        {net violated process antenna rule} antenna_nets} {
        set pattern [format {^#Total number of %s = ([0-9]+)$} $label]
        set totals [regexp -all -line -inline $pattern $text]
        if {[llength $totals] == 0} {error "Missing final routing count: $label"}
        dict set result $key [lindex $totals end]
    }
    if {![regexp -line {^#route_detail Statistics:$} $text] ||
        ![regexp -line {^# +Entire Command +\|[ 0-9:]+\|[ 0-9:]+\|[ 0-9.]+\|$} $text]} {
        error "Incomplete endpoint geometric routing execution"
    }
    return $result
}
