set status [catch {
    source syn/tri_oracle_slew_resize_policy.tcl
    set before [dict create \
        inv_a {INVD1P25BWP12T40P140 {1 2} r0} \
        inv_b {INVD1P25BWP12T40P140 {3 4} my} \
        buffer {BUFFD1BWP12T40P140 {5 6} r0} \
        mask {OR4D0BWP12T40P140 {7 8} my} \
        protected {DEL025D1BWP12T40P140 {9 10} r0}]
    set expected [dict create inv_a INVD2BWP12T40P140 inv_b INVD2BWP12T40P140 \
        buffer BUFFD2BWP12T40P140 mask OR4D1BWP12T40P140]
    set good $before
    dict for {name cell} $expected {dict set good $name [lreplace [dict get $good $name] 0 0 $cell]}
    dict set good inv_a {INVD2BWP12T40P140 {2 3} r0}
    set result [tri_oracle_require_slew_resize_inventory $before $good $expected]
    if {[dict get $result resized_instances] != 4} {error "Wrong resize scope"}
    set mutants {}
    set bad $good;dict set bad inv_a [dict get $before inv_a];lappend mutants $bad
    set bad $good;dict set bad protected {DEL050D1BWP12T40P140 {9 10} r0};lappend mutants $bad
    set bad $good;dict set bad protected {DEL025D1BWP12T40P140 {10 10} r0};lappend mutants $bad
    set bad $good;dict unset bad protected;lappend mutants $bad
    set bad $good;dict set bad extra {BUFFD2BWP12T40P140 {10 20} r0};lappend mutants $bad
    set bad $good;dict set bad inv_a {INVD2BWP12T40P140 {100 100} r0};lappend mutants $bad
    set bad $good;dict set bad inv_a {INVD2BWP12T40P140 {NaN 3} r0};lappend mutants $bad
    foreach bad $mutants {
        if {![catch {tri_oracle_require_slew_resize_inventory $before $bad $expected}]} {error "Unintended physical change admitted"}
    }
    set native_before $before
    set native_after $good
    dict set native_before inv_b [list INVD1P25BWP12T40P140 [list {1184.585 276.4}] my]
    dict set native_after inv_b [list INVD2BWP12T40P140 [list {780.405 298.0}] my]
    if {![catch {tri_oracle_require_slew_resize_inventory $native_before $native_after $expected}]} {error "Actual404um relocation was admitted"}
    dict set native_after inv_b [list INVD2BWP12T40P140 [list {1184.725 276.4}] my]
    tri_oracle_require_slew_resize_inventory $native_before $native_after $expected
    set with_antenna $good
    dict set with_antenna new_antenna {ANTENNABWP12T40P140 {10 20} r0}
    if {![catch {tri_oracle_require_slew_resize_inventory $before $with_antenna $expected}]} {error "Antenna insertion admitted before routing"}
    set result [tri_oracle_require_slew_resize_inventory $before $with_antenna $expected true]
    if {[dict get $result added_antenna_instances] != 1} {error "Expected controlled antenna insertion"}
    for {set index 0} {$index < 8} {incr index} {dict set with_antenna ant_$index {ANTENNABWP12T40P140 {0 0} r0}}
    if {![catch {tri_oracle_require_slew_resize_inventory $before $with_antenna $expected true}]} {error "Unbounded antenna insertion admitted"}
    set wrong $expected;dict set wrong mask OR4D2BWP12T40P140
    if {![catch {tri_oracle_require_slew_resize_inventory $before $good $wrong}]} {error "Unverified replacement cell admitted"}
    puts "PASS: exactly four admitted type changes; all other cells/positions retained; only bounded routing antennas allowed"
} message options]
if {$status} {puts stderr $message;exit 1}
