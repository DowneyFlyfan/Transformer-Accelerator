# Parent power routing around the original fixed core abstracts.
# Core44 exposes two connected M9 ring contacts per supply; its M8 stripe
# ports and all internal power routing remain owned by the qualified core.
# This constructs geometry, not a current-density or voltage-drop signoff.
proc tri_oracle_add_parent_power_grid37 {die_width die_height horizontal_channels report_path} {
    if {$die_width <= 40 || $die_height <= 40 || [llength $horizontal_channels] == 0} {
        error "PARENT_POWER37_INVALID_GEOMETRY"
    }
    connect_global_net VDD -type pg_pin -pin_base_name VDD -all
    connect_global_net VSS -type pg_pin -pin_base_name VSS -all
    add_rings -nets {VDD VSS} -type core_rings -follow core \
        -layer {top M10 bottom M10 left AP right AP} -width 4 -spacing 4 -offset 2
    foreach channel $horizontal_channels {
        if {[llength $channel] != 4} {error "PARENT_POWER37_BAD_CHANNEL"}
        lassign $channel x1 y1 x2 y2
        if {$x1 < 20 || $y1 < 20 || $x2 > $die_width-20 ||
            $y2 > $die_height-20 || $x2 <= $x1 || $y2-$y1 < 16} {
            error "PARENT_POWER37_CHANNEL_OUTSIDE_CORE: $channel"
        }
        add_stripes -nets {VDD VSS} -layer M10 -direction horizontal \
            -area $channel -width 4 -spacing 4 -number_of_sets 1 \
            -start_from bottom -start_offset 2
    }
    # Lower vertical stripes serve the parent standard-cell rows. The native
    # router clips them at the original macro obstructions.
    add_stripes -nets {VDD VSS} -layer M7 -direction vertical \
        -area [list 20 20 [expr {$die_width-20}] [expr {$die_height-20}]] \
        -width 1 -spacing 1 -set_to_set_distance 40 -start_offset 20
    # Contact the existing macro ring through its four real M9 shapes.
    route_special -nets {VDD VSS} -connect block_pin -block_pin use_lef \
        -block_pin_layer_range {M9 M9} -block_pin_target {stripe ring} \
        -allow_layer_change 1 -allow_jogging 1 -layer_change_range {M7 AP}
    route_special -nets {VDD VSS} -connect {core_pin floating_stripe} \
        -core_pin_target {stripe ring} -floating_stripe_target {stripe ring} \
        -allow_layer_change 1 -allow_jogging 1 -layer_change_range {M1 AP}

    # Put each top-level supply terminal on an actual vertical AP ring wire.
    # Coordinates are measured from native geometry, rather than assumed.
    set contacts [dict create]
    set file [open $report_path w]
    puts $file "net\tlayer\tshape\trectangle"
    foreach wire [get_obj_in_area -obj_type special_wire \
            -areas [list [list 0 0 $die_width $die_height]]] {
        set net [get_db $wire .net.name]
        if {$net ni {VDD VSS}} {error "PARENT_POWER37_UNEXPECTED_SUPPLY: $net"}
        set layer [get_db $wire .layer.name]
        set rectangle [get_db $wire .rect]
        if {[llength $rectangle] == 1} {set rectangle [lindex $rectangle 0]}
        if {[llength $rectangle] != 4} {error "PARENT_POWER37_INVALID_NATIVE_RECTANGLE"}
        puts $file "$net\t$layer\t[get_db $wire .shape]\t$rectangle"
        if {$layer ne "AP" || [dict exists $contacts $net]} {continue}
        lassign $rectangle x1 y1 x2 y2
        if {$x2-$x1 < 4 || $y2-$y1 < 100} {continue}
        set mid [expr {($y1+$y2)/2.0}]
        create_pg_pin -net $net -geometry AP $x1 [expr {$mid-2}] $x2 [expr {$mid+2}] $net
        dict set contacts $net $rectangle
    }
    close $file
    if {[dict size $contacts] != 2} {error "PARENT_POWER37_MISSING_PHYSICAL_SUPPLY_TERMINAL"}
    fix_via -min_cut
}
