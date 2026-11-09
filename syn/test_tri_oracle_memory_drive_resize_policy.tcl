set checks 0
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error $message}
    incr ::checks
}
proc rejects {script} {require {[catch {uplevel 1 $script}]} "Unsafe resize scope admitted"}
try {
    source syn/tri_oracle_memory_route_scope.tcl
    source syn/tri_oracle_memory_wire_scope.tcl
    set policy [lindex $argv 0]
    if {$policy eq {}} {set policy syn/tri_oracle_memory_drive_resize_policy.tcl}
    source $policy
    set pairs {
        NR2D1BWP12T40P140 NR2D2BWP12T40P140
        BUFFD1BWP12T40P140 BUFFD2BWP12T40P140
        AOI22D1BWP12T40P140 AOI22D2BWP12T40P140
        SDFQD0BWP12T40P140 SDFQD1BWP12T40P140
        CKND2D1BWP12T40P140 CKND2D2BWP12T40P140
        INR2D1BWP12T40P140 INR2D2BWP12T40P140
        INVD1BWP12T40P140 INVD2BWP12T40P140
    }
    foreach {original replacement} $pairs {
        require {[tri_oracle_memory_drive_resize_cell $original] eq $replacement} "Unproved sizing pair"
        set before [list $original {100000 200000} r0 placed unset placed none]
        set after [lreplace $before 0 0 $replacement]
        set observed [tri_oracle_memory_drive_resize_row driver $before $after $replacement]
        require {[dict get $observed displacement_squared_dbu2] == 0} "In-place row rejected"
        require {[dict get $observed scan_clock_load] == [string match SDFQD0* $original]} "Clock-load class lost"
        rejects [list tri_oracle_memory_drive_resize_row driver $before $before $replacement]
        rejects [list tri_oracle_memory_drive_resize_row driver $before $after ANTENNABWP12T40P140]
        foreach {index value} {2 mx 3 fixed 4 placed 5 fixed 6 true} {
            rejects [list tri_oracle_memory_drive_resize_row driver $before [lreplace $after $index $index $value] $replacement]
        }
        if {[string match SDFQD0* $original]} {
            foreach point {{100001 200000} {100000 200001} {99999 200000}} {
                rejects [list tri_oracle_memory_drive_resize_row driver $before [lreplace $after 1 1 $point] $replacement]
            }
        } else {
            foreach point {{120000 200000} {100000 180000} {114000 214000}} {
                set moved [tri_oracle_memory_drive_resize_row driver $before [lreplace $after 1 1 $point] $replacement]
                require {[dict get $moved displacement_squared_dbu2] <= 400000000} "Legal local boundary rejected"
            }
            foreach point {{120001 200000} {100000 179999} {114143 214143}} {
                rejects [list tri_oracle_memory_drive_resize_row driver $before [lreplace $after 1 1 $point] $replacement]
            }
        }
    }
    rejects {tri_oracle_memory_drive_resize_cell INVD4BWP12T40P140}
    set before {NR2D1BWP12T40P140 {100000 200000} r0 placed unset placed none}
    set after [lreplace $before 0 0 NR2D2BWP12T40P140]
    foreach {index value} {3 fixed 4 placed 5 fixed 6 true} {
        set bad_before [lreplace $before $index $index $value]
        set bad_after [lreplace $after $index $index $value]
        rejects [list tri_oracle_memory_drive_resize_row driver $bad_before $bad_after NR2D2BWP12T40P140]
    }
    rejects [list tri_oracle_memory_drive_resize_row driver $before [lreplace $after 1 1 {100000.1 200000}] NR2D2BWP12T40P140]
    rejects [list tri_oracle_memory_drive_resize_row driver $before [lrange $after 0 5] NR2D2BWP12T40P140]
    foreach {seen expected resized scans added} {
        20 20 16 8 0
        906420 906420 16 8 8
    } {
        tri_oracle_memory_drive_resize_scope_counts $seen $expected $resized $scans $added
        require {true} "Complete target scope rejected"
    }
    foreach args {
        {19 20 16 8 0} {21 20 16 8 0} {20 20 15 8 0} {20 20 17 8 0}
        {20 20 16 7 0} {20 20 16 9 0} {20 20 16 8 9} {20 20 16 8 -1}
        {15 15 16 8 0} {20 20 16.1 8 0} {20 20 16 8.0 0}
    } {
        rejects [list tri_oracle_memory_drive_resize_scope_counts {*}$args]
    }
    require {[tri_oracle_memory_drive_net_inventory 1 {unused/D} {}] eq {1 unused/D {}}} "Single pin lost"
    require {[tri_oracle_memory_drive_net_inventory 1 {} {unused_port}] eq {1 {} unused_port}} "Single port lost"
    require {[tri_oracle_memory_drive_net_inventory 2 {b/D a/Q} {}] eq {2 {a/Q b/D} {}}} "Active incident inventory lost"
    foreach args {
        {1 {} {}} {1 {a/D b/Q} {}} {1 {a/D} {port}} {0 {a/D} {}}
        {2 {a/D} {}} {1.0 {a/D} {}} {1 {{bad name}} {}}
    } {rejects [list tri_oracle_memory_drive_net_inventory {*}$args]}
    puts "MEMORY_DRIVE_RESIZE_POLICY_PASS checks=$checks"
} on error {message options} {puts stderr $message;exit 1}
