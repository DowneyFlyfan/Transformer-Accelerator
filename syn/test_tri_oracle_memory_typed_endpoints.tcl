# Catch a scan-control/data-pin mix-up, an unobserved cell, or a mismatch
# between a measured endpoint and its native model/net inventory.
set checks 0
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error $message}
    incr ::checks
}
proc rejects {script} {
    require {[catch {uplevel 1 $script}]} "Unsafe typed endpoint admitted by [lindex $script 0]"
}
try {
    set policy [lindex $argv 0]
    if {$policy eq {}} {set policy syn/tri_oracle_memory_typed_endpoint_policy.tcl}
    source $policy
    foreach kind {cache/DA cache/DB inputs/DB weights/DB} {
        tri_oracle_memory_endpoint_typed_cell $kind DFMQD1BWP12T40P140
        incr checks
    }
    foreach kind {inputs/SI weights/SI} {
        tri_oracle_memory_endpoint_typed_cell $kind SDFQD0BWP12T40P140
        incr checks
    }
    tri_oracle_memory_endpoint_typed_cell external_input SDFCNQD0BWP12T40P140
    incr checks
    foreach pair {
        {inputs/SI SDFCNQD0BWP12T40P140}
        {weights/SI SDFQD1BWP12T40P140}
        {cache/DA DFMQD2BWP12T40P140}
        {cache/DB SDFQD0BWP12T40P140}
        {inputs/DB SDFQD0BWP12T40P140}
        {external_input SDFQD0BWP12T40P140}
        {external_input SDFCNQD1BWP12T40P140}
        {inputs/SE SDFQD0BWP12T40P140}
    } {rejects [list tri_oracle_memory_endpoint_typed_cell {*}$pair]}
    set root .cache/physical/pnr/tri_oracle_memory_feedforward_core
    set channel [open $root/postroute_endpoint_margin_probe.tsv r]
    try {set measured [tri_oracle_memory_endpoint_inventory [read $channel]]} finally {close $channel}
    set channel [open $root/postroute_endpoint_cell_probe.tsv r]
    try {set text [read $channel]} finally {close $channel}
    set rows [tri_oracle_memory_endpoint_cells_inventory $text $measured]
    require {[dict size $rows] == 6568} "Complete typed endpoint inventory was lost"
    require {[lindex [dict get $rows {core/cache/memory_reg[0][50]/DA}] 0] eq \
        {DFMQD1BWP12T40P140}} "Actual cache data cell was misclassified"
    require {[lindex [dict get $rows {core/activation_base_reg[0]/D}] 0] eq \
        {SDFCNQD0BWP12T40P140}} "External configuration flip-flop was misclassified"
    set lines [split [string trimright $text \n] \n]
    foreach {field value} {0 cfg_activation_base 1 wrong/endpoint 2 -0.0252 \
        3 inputs/SI 4 SDFQD0BWP12T40P140 5 {} 6 out} {
        set bad $lines
        set row [split [lindex $bad 1] \t]
        lset row $field $value
        lset bad 1 [join $row \t]
        rejects [list tri_oracle_memory_endpoint_cells_inventory [join $bad \n] $measured]
    }
    rejects [list tri_oracle_memory_endpoint_cells_inventory \
        [join [lrange $lines 0 end-1] \n] $measured]
    rejects [list tri_oracle_memory_endpoint_cells_inventory "$text[lindex $lines 1]\n" $measured]
    rejects [list tri_oracle_memory_endpoint_cells_inventory \
        [string map {base_cell invalid_column} $text] $measured]
    puts "MEMORY_TYPED_ENDPOINT_POLICY_PASS checks=$checks endpoints=[dict size $rows]"
} on error {message options} {
    puts stderr $message
    exit 1
}
