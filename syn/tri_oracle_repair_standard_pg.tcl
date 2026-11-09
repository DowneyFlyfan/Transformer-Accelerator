# Parse actual Innovus25.10 unconnected standard-cell supply pin rectangles.
# Coordinates are micrometers; every repair stays within2umof measured pins.
proc tri_oracle_standard_pg_areas {text} {
    set areas [dict create]
    set observed 0
    set parsed 0
    foreach line [split $text "\n"] {
        if {[string match {*Pin Pin:*has an unconnected terminal*} $line]} {incr observed}
        if {![regexp {^Net (VDD|VSS), Pin Pin: ([^;]+)/(VDD|VSS);.*has an unconnected terminal at \(([-+0-9.eE]+), ([-+0-9.eE]+)\) \(([-+0-9.eE]+), ([-+0-9.eE]+)\)$} $line all net inst pin x0 y0 x1 y1]} {continue}
        incr parsed
        if {$net ne $pin || ![regexp {^[A-Za-z_][A-Za-z0-9_$]*$} $inst]} {error "Unsupported supply terminal identity"}
        foreach x [list $x0 $y0 $x1 $y1] {if {![string is double -strict $x]} {error "Invalid supply coordinate"}}
        if {$x0 < 2 || $y0 < 2 || $x1 <= $x0 || $y1 <= $y0 || $x1-$x0 > 10 || $y1-$y0 > 10} {error "Supply repair is not a small interior standard-cell pin"}
        set area [list [expr {$x0-2.0}] [expr {$y0-2.0}] [expr {$x1+2.0}] [expr {$y1+2.0}]]
        if {[dict exists $areas $inst]} {
            lassign [dict get $areas $inst] a b c d
            lassign $area x y z w
            set area [list [expr {min($a,$x)}] [expr {min($b,$y)}] [expr {max($c,$z)}] [expr {max($d,$w)}]]
        }
        dict set areas $inst $area
    }
    if {$observed != $parsed || [dict size $areas] > 16} {error "Unclassified or excessive supply repair targets"}
    return $areas
}
proc tri_oracle_repair_measured_standard_pg {out label} {
    set before [format {%s/%s_before_connectivity.rpt} $out $label]
    check_connectivity -type all -error 100000 -warning 100000 -check_pg_ports -out_file $before
    set f [open $before r];set text [read $f];close $f
    set areas [tri_oracle_standard_pg_areas $text]
    set inventory [dict create]
    foreach i [get_db insts] {dict set inventory [get_db $i .name] $i}
    set log [open [format {%s/%s_power_repairs.rpt} $out $label] w]
    dict for {name area} $areas {
        if {![dict exists $inventory $name]} {error "Measured supply target not in design"}
        set i [dict get $inventory $name]
        set master [get_db $i .base_cell.name]
        if {![regexp {BWP12T40P140$} $master] || [regexp {^TS[56]} $master]} {error "Supply repair target is not a characterized standard cell"}
        puts $log [list instance $name master $master measured_pin_union_plus2um $area]
        route_special -nets {VDD VSS} -connect core_pin -area $area -core_pin_target {stripe ring} -allow_layer_change 1 -allow_jogging 1 -layer_change_range {M1 M7}
    }
    puts $log "repaired_standard_cell_instances: [dict size $areas]"
    close $log
    edit_trim_routes -nets {VDD VSS}
    set after [format {%s/%s_after_connectivity.rpt} $out $label]
    check_connectivity -type all -error 100000 -warning 100000 -check_pg_ports -out_file $after
    set f [open $after r];set checked [read $f];close $f
    if {![regexp {Begin Summary\s+Found no problems or warnings\.\s+End Summary} $checked]} {error "Supply repair did not restore complete native connectivity"}
    return [dict size $areas]
}
