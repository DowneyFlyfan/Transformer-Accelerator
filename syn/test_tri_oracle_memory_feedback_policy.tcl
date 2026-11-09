# Native Tool Command Language checks for cache-only feedback admission.
set checks 0
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error $message}
    incr ::checks
}
proc reject {script} {
    require {[catch {uplevel 1 $script}]} "An unmeasured feedback repair was admitted"
}
try {
    set policy [lindex $argv 0]
    if {$policy eq ""} {set policy syn/tri_oracle_memory_feedback_policy.tcl}
    source $policy
    foreach pair {{0 0} {352 17} {511 79}} {
        lassign $pair row bit
        set cell [format {core/cache/memory_reg[%d][%d]} $row $bit]
        foreach kind {DFMQD1BWP12T40P140 DFMQD2BWP12T40P140 DFMQD4BWP12T40P140} {
            require {[tri_oracle_memory_feedback_admit ${cell}/CP ${cell}/DA \
                $kind -0.012628 1] eq "${cell}/DA"} "Measured feedback was rejected"
        }
    }
    set cell {core/cache/memory_reg[352][17]}
    require {[tri_oracle_memory_feedback_admit ${cell}/CP ${cell}/DA \
        DFMQD1BWP12T40P140 -0.020 1] eq "${cell}/DA"} "Inclusive deficit bound failed"
    foreach slack {0 0.001 -0.020001 NaN Inf -Inf invalid {}} {
        reject [list tri_oracle_memory_feedback_admit ${cell}/CP ${cell}/DA \
            DFMQD1BWP12T40P140 $slack 1]
    }
    foreach pair {
        {core/cache/memory_reg[352][17]/CP core/cache/memory_reg[352][18]/DA}
        {core/cache/memory_reg[352][17]/Q core/cache/memory_reg[352][17]/DA}
        {core/cache/memory_reg[352][17]/CP core/cache/memory_reg[352][17]/DB}
        {core/cache/memory_reg[352][17]/CP core/cache/memory_reg[352][17]/SA}
        {core/cache/memory_reg[352][17]/CP core/cache/memory_reg[352][17]/CP}
        {core/cache/memory_reg[512][0]/CP core/cache/memory_reg[512][0]/DA}
        {core/cache/memory_reg[0][80]/CP core/cache/memory_reg[0][80]/DA}
        {core/cache/memory_reg[00][0]/CP core/cache/memory_reg[00][0]/DA}
        {cache/memory_reg[0][0]/CP cache/memory_reg[0][0]/DA}
        {core/storage[0].inputs/words_reg[0][0]/CP core/storage[0].inputs/words_reg[0][0]/D}
    } {
        lassign $pair launch capture
        reject [list tri_oracle_memory_feedback_admit $launch $capture \
            DFMQD1BWP12T40P140 -0.012628 1]
    }
    foreach kind {UNKNOWN DFMQD0BWP12T40P140 SDFCNQD1BWP12T40P140} {
        reject [list tri_oracle_memory_feedback_admit ${cell}/CP ${cell}/DA $kind -0.012628 1]
    }
    foreach direct {0 unknown {} 1.0} {
        reject [list tri_oracle_memory_feedback_admit ${cell}/CP ${cell}/DA \
            DFMQD1BWP12T40P140 -0.012628 $direct]
    }
    tri_oracle_memory_feedback_headroom ${cell}/DA {setup_slow 0.45 setup_typ 0.9}
    incr checks
    foreach slacks {
        {setup_slow 0.449999 setup_typ 0.9}
        {setup_slow 0.9 setup_typ 0.449999}
        {setup_slow 0.9}
        {setup_typ 0.9}
        {setup_slow NaN setup_typ 0.9}
        {setup_slow Inf setup_typ 0.9}
        {setup_slow 0.9 setup_typ invalid}
    } {reject [list tri_oracle_memory_feedback_headroom ${cell}/DA $slacks]}
    foreach count {1 3857 10000 40960} {
        require {[tri_oracle_memory_feedback_count $count] == $count} "Valid capacity was rejected"
    }
    foreach count {0 -1 40961 NaN 1.5 unknown {}} {
        reject [list tri_oracle_memory_feedback_count $count]
    }
    puts "MEMORY_CACHE_FEEDBACK_POLICY_PASS checks=$checks"
} on error {message options} {
    puts stderr $message
    exit 1
}
