# Exact native cell inventory supersedes the first attempt's model assumptions.
# All three models' data/control pins and flop functions were inspected in all
# three bound libraries; original measured path/margin policy stays unchanged.
source syn/tri_oracle_memory_endpoint_policy.tcl

proc tri_oracle_memory_endpoint_typed_cell {kind model} {
    switch -- $kind {
        cache/DA - cache/DB - inputs/DB - weights/DB {set expected DFMQD1BWP12T40P140}
        inputs/SI - weights/SI {set expected SDFQD0BWP12T40P140}
        external_input {set expected SDFCNQD0BWP12T40P140}
        default {error "Unobserved native endpoint class: $kind"}
    }
    if {$model ne $expected} {error "Unobserved native $kind cell: $model"}
}

proc tri_oracle_memory_endpoint_cells_inventory {text measured} {
    set lines [split [string trimright $text \n] \n]
    if {[lindex $lines 0] ne "launch\tendpoint\thold_fast_ns\tkind\tbase_cell\tnet\tdirection"} {
        error "Missing native endpoint cell inventory header"
    }
    set rows [dict create]
    foreach line [lrange $lines 1 end] {
        set fields [split $line \t]
        if {[llength $fields] != 7} {error "Incomplete native endpoint cell inventory row"}
        lassign $fields launch capture hold kind model net direction
        if {![dict exists $measured $capture] || [dict exists $rows $capture]} {
            error "Unexpected or duplicate native endpoint: $capture"
        }
        lassign [dict get $measured $capture] expected_launch expected_hold slow typical expected_kind
        tri_oracle_finite_timing_value $hold
        if {$launch ne $expected_launch || $hold != $expected_hold || $kind ne $expected_kind ||
            $direction ne {in} || ![regexp {^\S+$} $net]} {
            error "Native endpoint model/net inventory differs from measured timing"
        }
        tri_oracle_memory_endpoint_typed_cell $kind $model
        dict set rows $capture [list $model $net]
    }
    if {[dict size $rows] != 6568 || [dict size $rows] != [dict size $measured]} {
        error "Incomplete native endpoint model/net inventory"
    }
    return $rows
}
