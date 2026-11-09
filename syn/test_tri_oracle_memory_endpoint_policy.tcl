# These tests catch delaying control pins, another register, an unmeasured
# interface, a wrong cell model, or a path without both setup margins.
set checks 0
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error $message}
    incr ::checks
}
proc rejects {script} {
    require {[catch {uplevel 1 $script}]} "Unsafe endpoint repair admitted by [lindex $script 0]"
}
proc admits {launch capture slack expected} {
    set status [catch {tri_oracle_memory_endpoint_kind $launch $capture $slack} result]
    require {$status == 0 && $result eq $expected} "Measured endpoint rejected: $result"
}
try {
    set policy [lindex $argv 0]
    if {$policy eq ""} {set policy syn/tri_oracle_memory_endpoint_policy.tcl}
    source $policy
    foreach pair {{0 0} {352 17} {511 79}} {
        lassign $pair row bit
        set cell [format {core/cache/memory_reg[%d][%d]} $row $bit]
        foreach pin {DA DB} {
            admits ${cell}/CP ${cell}/$pin -0.012628 cache/$pin
            foreach model {DFMQD1BWP12T40P140 DFMQD2BWP12T40P140 DFMQD4BWP12T40P140} {
                tri_oracle_memory_endpoint_cell cache/$pin $model
                incr checks
            }
        }
    }
    foreach family {inputs weights} {
        foreach triple {{0 0 0} {17 9 23} {31 31 63}} {
            lassign $triple bank word bit
            set cell [format {core/execution/core/core/storage[%d].%s/words_reg[%d][%d]} \
                $bank $family $word $bit]
            admits ${cell}/CP ${cell}/DB -0.020 $family/DB
            admits ${cell}/CP ${cell}/SI -0.001 $family/SI
            tri_oracle_memory_endpoint_cell $family/DB DFMQD1BWP12T40P140
            tri_oracle_memory_endpoint_cell $family/SI SDFCNQD0BWP12T40P140
            incr checks 2
        }
    }
    set external {
        {cfg_activation_base[0] core/activation_base_reg[0]/D}
        {cfg_up_sign_base[46] core/up_sign_base_reg[46]/D}
        {cfg_raw_base[59] raw_base_reg[59]/D}
        {cfg_tag[9] core/preparation/normalizer/tag_reg[9]/D}
        {cfg_tag[29] core/preparation/normalizer/tag_reg[29]/D}
        {rsp_data[38] reader/gamma_word_reg[38]/D}
        {rsp_data[38] reader/gamma_word_reg[102]/D}
        {rsp_data[47] reader/gamma_word_reg[111]/D}
        {cfg_raw_base[43] raw_base_reg[43]/D}
    }
    foreach pair $external {
        lassign $pair launch capture
        admits $launch $capture -0.025197 external_input
        tri_oracle_memory_endpoint_cell external_input SDFCNQD0BWP12T40P140
        incr checks
    }
    admits {cfg_raw_base[43]} {raw_base_reg[43]/D} -0.050 external_input
    foreach slack {0 0.001 -0.020001 NaN Inf -Inf invalid {}} {
        rejects [list tri_oracle_memory_endpoint_kind {core/cache/memory_reg[0][0]/CP} \
            {core/cache/memory_reg[0][0]/DA} $slack]
    }
    rejects {tri_oracle_memory_endpoint_kind {cfg_raw_base[43]} {raw_base_reg[43]/D} -0.050001}
    foreach pair {
        {core/cache/memory_reg[0][0]/CP core/cache/memory_reg[0][1]/DA}
        {core/cache/memory_reg[0][0]/Q core/cache/memory_reg[0][0]/DA}
        {core/cache/memory_reg[0][0]/CP core/cache/memory_reg[0][0]/SA}
        {core/cache/memory_reg[0][0]/CP core/cache/memory_reg[0][0]/CP}
        {core/cache/memory_reg[0][0]/CP core/cache/memory_reg[0][0]/SI}
        {core/cache/memory_reg[512][0]/CP core/cache/memory_reg[512][0]/DA}
        {core/cache/memory_reg[0][80]/CP core/cache/memory_reg[0][80]/DB}
        {core/cache/memory_reg[00][0]/CP core/cache/memory_reg[00][0]/DA}
        {core/execution/core/core/storage[32].inputs/words_reg[0][0]/CP core/execution/core/core/storage[32].inputs/words_reg[0][0]/DB}
        {core/execution/core/core/storage[0].weights/words_reg[32][0]/CP core/execution/core/core/storage[0].weights/words_reg[32][0]/DB}
        {core/execution/core/core/storage[0].inputs/words_reg[0][64]/CP core/execution/core/core/storage[0].inputs/words_reg[0][64]/SI}
        {core/execution/core/core/storage[0].outputs/words_reg[0][0]/CP core/execution/core/core/storage[0].outputs/words_reg[0][0]/SI}
        {core/execution/core/core/storage[0].inputs/words_reg[0][0]/CP core/execution/core/core/storage[0].inputs/words_reg[0][0]/SE}
        {core/execution/core/core/storage[0].inputs/words_reg[0][0]/CP core/execution/core/core/storage[0].inputs/words_reg[0][0]/DA}
        {cfg_raw_base[42] raw_base_reg[42]/D}
        {rsp_data[38] reader/gamma_word_reg[39]/D}
        {cfg_tag[9] core/preparation/normalizer/tag_reg[29]/D}
    } {
        lassign $pair launch capture
        rejects [list tri_oracle_memory_endpoint_kind $launch $capture -0.001]
    }
    foreach pair {
        {cache/DA SDFCNQD0BWP12T40P140}
        {inputs/DB SDFCNQD0BWP12T40P140}
        {weights/SI DFMQD1BWP12T40P140}
        {inputs/SI SDFCNQNOPTBD1BWP12T40P140}
        {external_input SDFCNQD1BWP12T40P140}
        {cache/DA DFMQD0BWP12T40P140}
        {cache/DB UNKNOWN}
        {unknown DFMQD1BWP12T40P140}
    } {rejects [list tri_oracle_memory_endpoint_cell {*}$pair]}
    tri_oracle_memory_feedback_headroom endpoint {setup_slow 0.450 setup_typ 0.450}
    incr checks
    foreach slacks {
        {setup_slow 0.449999 setup_typ 2}
        {setup_slow 2 setup_typ 0.449999}
        {setup_slow 2}
        {setup_slow Inf setup_typ 2}
        {setup_slow 2 setup_typ NaN}
    } {rejects [list tri_oracle_memory_feedback_headroom endpoint $slacks]}

    set inserted {core/cache/TRI_MEMORY_ENDPOINT_HOLD_0 core/cache/old_net core/cache/new_net}
    require {[tri_oracle_memory_endpoint_insertion TRI_MEMORY_ENDPOINT_HOLD_0 $inserted] eq \
        {core/cache/TRI_MEMORY_ENDPOINT_HOLD_0}} "Native hierarchical insertion identity rejected"
    foreach bad {
        {core/cache/OTHER_0 old_net new_net}
        {core/cache/TRI_MEMORY_ENDPOINT_HOLD_1 old_net new_net}
        {core/cache/TRI_MEMORY_ENDPOINT_HOLD_0 old_net}
        {core/cache/TRI_MEMORY_ENDPOINT_HOLD_0 old_net old_net}
        {core/cache/TRI_MEMORY_ENDPOINT_HOLD_0 {} new_net}
    } {rejects [list tri_oracle_memory_endpoint_insertion TRI_MEMORY_ENDPOINT_HOLD_0 $bad]}

    set inventory .cache/physical/pnr/tri_oracle_memory_feedforward_core/postroute_endpoint_margin_probe.tsv
    set channel [open $inventory r]
    try {set text [read $channel]} finally {close $channel}
    set rows [tri_oracle_memory_endpoint_inventory $text]
    require {[dict size $rows] == 6568} "Actual endpoint inventory was truncated"
    # Independent counts from the complete cold negative-path report.
    set kinds [dict create]
    foreach row [dict values $rows] {dict incr kinds [lindex $row 4]}
    foreach {kind expected} {cache/DA 480 cache/DB 52 inputs/DB 841 weights/DB 167 \
        inputs/SI 4137 weights/SI 882 external_input 9} {
        require {[dict get $kinds $kind] == $expected} "Actual path class was lost: $kind"
    }
    set lines [split [string trimright $text \n] \n]
    rejects [list tri_oracle_memory_endpoint_inventory [join [lrange $lines 0 end-1] \n]]
    rejects [list tri_oracle_memory_endpoint_inventory "$text[lindex $lines 1]\n"]
    rejects [list tri_oracle_memory_endpoint_inventory \
        [string map {hold_fast_ns invalid_column} $text]]
    set fields [split [lindex $lines 1] \t]
    lset fields 3 0.449999
    set bad $lines
    lset bad 1 [join $fields \t]
    rejects [list tri_oracle_memory_endpoint_inventory [join $bad \n]]

    set trace "TRI_ORACLE_LOCAL_ECO_MODE false false\nroute_with_timing_driven false\nroute_with_si_driven false\n#Total number of DRC violations = 96\n#Total number of process antenna violations = 2\n#Total number of net violated process antenna rule = 1\n#route_detail Statistics:\n#  Entire Command         | 00:11:15|     00:02:05|         5.4|\n"
    set evidence [tri_oracle_memory_endpoint_router_evidence $trace]
    require {[dict get $evidence geometry_violations] == 96} "Diagnostic routing count was erased"
    require {[dict get $evidence antenna_violations] == 2} "Antenna count was erased"
    require {![dict get $evidence physical_closure_passed]} "Router diagnostics became signoff"
    foreach bad [list \
        [string map {{route_with_si_driven false} {route_with_si_driven true}} $trace] \
        [string map {{#Total number of DRC violations = 96} {}} $trace] \
        [string range $trace 0 [expr {[string first {#route_detail Statistics:} $trace]-1}]] \
        "$trace**ERROR native failure\n" \
        "$trace#WARNING (NRIF-78) unsupported ECO mode\n"] {
        rejects [list tri_oracle_memory_endpoint_router_evidence $bad]
    }
    puts "MEMORY_MEASURED_ENDPOINT_POLICY_PASS checks=$checks endpoints=[dict size $rows]"
} on error {message options} {
    puts stderr $message
    exit 1
}
