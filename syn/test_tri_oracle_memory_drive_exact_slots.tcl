set checks 0
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error $message}
    incr ::checks
}
proc rejects {script} {require {[catch {uplevel 1 $script}]} "Unsafe exact-slot target admitted"}
try {
    source syn/tri_oracle_memory_route_scope.tcl
    source syn/tri_oracle_memory_wire_scope.tcl
    source syn/tri_oracle_memory_drive_resize_policy.tcl
    set policy [lindex $argv 0]
    if {$policy eq {}} {set policy syn/tri_oracle_memory_drive_exact_slots.tcl}
    source $policy
    set fixtures [dict create \
    {core/cache/g257794} {{{NR2D1BWP12T40P140} {{491770} {951200}} {mx} {placed} {unset} {placed} {none}} {{NR2D2BWP12T40P140} {{491210} {951200}} {mx} {placed} {unset} {placed} {none}}} \
    {core/execution/core/FE_OFC25833_n_34952} {{{BUFFD1BWP12T40P140} {{2768730} {1397600}} {mx} {placed} {unset} {placed} {none}} {{BUFFD2BWP12T40P140} {{2768730} {1397600}} {mx} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/g7687} {{{AOI22D1BWP12T40P140} {{1039730} {348800}} {my} {placed} {unset} {placed} {none}} {{AOI22D2BWP12T40P140} {{972250} {372800}} {my} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/g7262} {{{AOI22D1BWP12T40P140} {{1059050} {646400}} {r0} {placed} {unset} {placed} {none}} {{AOI22D2BWP12T40P140} {{1027130} {660800}} {r0} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[12].inputs/words_reg[17][54]} {{{SDFQD0BWP12T40P140} {{2115490} {682400}} {mx} {placed} {unset} {placed} {none}} {{SDFQD1BWP12T40P140} {{2115490} {682400}} {mx} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[18].inputs/words_reg[0][25]} {{{SDFQD0BWP12T40P140} {{1679250} {497600}} {r0} {placed} {unset} {placed} {none}} {{SDFQD1BWP12T40P140} {{1679250} {497600}} {r0} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[18].inputs/words_reg[19][54]} {{{SDFQD0BWP12T40P140} {{1559970} {454400}} {r0} {placed} {unset} {placed} {none}} {{SDFQD1BWP12T40P140} {{1559970} {454400}} {r0} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[18].inputs/words_reg[1][53]} {{{SDFQD0BWP12T40P140} {{1673930} {500000}} {mx} {placed} {unset} {placed} {none}} {{SDFQD1BWP12T40P140} {{1673930} {500000}} {mx} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[18].inputs/words_reg[21][18]} {{{SDFQD0BWP12T40P140} {{1568090} {507200}} {r0} {placed} {unset} {placed} {none}} {{SDFQD1BWP12T40P140} {{1568090} {507200}} {r0} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[24].inputs/words_reg[17][29]} {{{SDFQD0BWP12T40P140} {{1503690} {413600}} {mx} {placed} {unset} {placed} {none}} {{SDFQD1BWP12T40P140} {{1503690} {413600}} {mx} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[9].inputs/words_reg[16][14]} {{{SDFQD0BWP12T40P140} {{1898210} {442400}} {mx} {placed} {unset} {placed} {none}} {{SDFQD1BWP12T40P140} {{1898210} {442400}} {mx} {placed} {unset} {placed} {none}}} \
    {core/execution/core/core/storage[9].inputs/words_reg[21][42]} {{{SDFQD0BWP12T40P140} {{1897930} {464000}} {r0} {placed} {unset} {placed} {none}} {{SDFQD1BWP12T40P140} {{1897930} {464000}} {r0} {placed} {unset} {placed} {none}}} \
    {core/execution/core/g35323} {{{CKND2D1BWP12T40P140} {{2762850} {1380800}} {r0} {placed} {unset} {placed} {none}} {{CKND2D2BWP12T40P140} {{2762850} {1380800}} {r0} {placed} {unset} {placed} {none}}} \
    {core/execution/core/g35548} {{{INR2D1BWP12T40P140} {{2107650} {1280000}} {r0} {placed} {unset} {placed} {none}} {{INR2D2BWP12T40P140} {{2105410} {1304000}} {r0} {placed} {unset} {placed} {none}}} \
    {FE_OFC13350_req_address_44} {{{INVD1BWP12T40P140} {{252370} {327200}} {mx} {placed} {unset} {placed} {none}} {{INVD2BWP12T40P140} {{259370} {327200}} {mx} {placed} {unset} {placed} {none}}} \
    {FE_OFC13352_req_address_43} {{{INVD1BWP12T40P140} {{474970} {569600}} {r0} {placed} {unset} {placed} {none}} {{INVD2BWP12T40P140} {{474970} {569600}} {r0} {placed} {unset} {placed} {none}}} \
]
    set slots [dict create]
    dict for {name pair} $fixtures {
        dict set slots $name [tri_oracle_memory_drive_canonical_row [lindex $pair 1]]
    }
    set scans 0
    set beyond_old_limit 0
    dict for {name pair} $fixtures {
        set before [tri_oracle_memory_drive_canonical_row [lindex $pair 0]]
        set after [tri_oracle_memory_drive_canonical_row [lindex $pair 1]]
        set replacement [lindex $after 0]
        set result [tri_oracle_memory_drive_exact_slot_row $name $before $after $replacement $slots]
        require {[dict get $result displacement_squared_dbu2] >= 0} "Exact target rejected"
        incr scans [dict get $result scan_clock_load]
        if {[dict get $result displacement_squared_dbu2] > 400000000} {incr beyond_old_limit}
        lassign [lindex $after 1] x y
        rejects [list tri_oracle_memory_drive_exact_slot_row $name $before \
            [lreplace $after 1 1 [list [expr {$x+1}] $y]] $replacement $slots]
        rejects [list tri_oracle_memory_drive_exact_slot_row $name $before \
            [lreplace $after 1 1 [list $x [expr {$y-1}]]] $replacement $slots]
        foreach {index value} {3 fixed 4 placed 5 fixed 6 true} {
            set bad [lreplace $after $index $index $value]
            set changed $slots
            dict set changed $name $bad
            rejects [list tri_oracle_memory_drive_exact_slot_row $name $before $bad $replacement $changed]
        }
        set bad [lreplace $after 0 0 [lindex $before 0]]
        set changed $slots
        dict set changed $name $bad
        rejects [list tri_oracle_memory_drive_exact_slot_row $name $before $bad $replacement $changed]
        set bad [lreplace $after 2 2 arbitrary_orientation]
        set changed $slots
        dict set changed $name $bad
        rejects [list tri_oracle_memory_drive_exact_slot_row $name $before $bad $replacement $changed]
        set incomplete $slots
        dict unset incomplete $name
        rejects [list tri_oracle_memory_drive_exact_slot_row $name $before $after $replacement $incomplete]
        if {[dict get $result scan_clock_load]} {
            set moved [lreplace $after 1 1 [list [expr {$x+280}] $y]]
            set changed $slots
            dict set changed $name $moved
            rejects [list tri_oracle_memory_drive_exact_slot_row $name $before $moved $replacement $changed]
            require {[dict get $result displacement_squared_dbu2] == 0} "Scan placement changed"
        }
    }
    require {$scans == 8} "Eight scan targets missing"
    require {$beyond_old_limit == 3} "Measured wider-cell geometry is not represented"
    set name [lindex [dict keys $fixtures] 0]
    lassign [dict get $fixtures $name] before after
    set before [tri_oracle_memory_drive_canonical_row $before]
    set after [tri_oracle_memory_drive_canonical_row $after]
    set replacement [lindex $after 0]
    rejects [list tri_oracle_memory_drive_exact_slot_row unknown_driver $before $after $replacement $slots]
    set incomplete_other $slots
    dict unset incomplete_other [lindex [dict keys $fixtures] 1]
    rejects [list tri_oracle_memory_drive_exact_slot_row $name $before $after $replacement $incomplete_other]
    set extra_target $slots
    dict set extra_target unexpected_driver $after
    rejects [list tri_oracle_memory_drive_exact_slot_row $name $before $after $replacement $extra_target]
    set malformed $slots
    dict set malformed $name [lrange $after 0 5]
    rejects [list tri_oracle_memory_drive_exact_slot_row $name $before $after $replacement $malformed]
    rejects [list tri_oracle_memory_drive_exact_slot_row $name $before \
        [lreplace $after 1 1 {1.25 2}] $replacement $slots]
    puts "MEMORY_DRIVER_EXACT_SLOTS_PASS checks=$checks"
} on error {message options} {puts stderr $message;exit 1}
