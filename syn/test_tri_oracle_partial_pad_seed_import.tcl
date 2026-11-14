# Verify partial pad seed import and fresh-session restore with the installed libraries.
proc require_pose {name location status} {
    set object [get_db insts $name]
    if {[llength $object] != 1 ||
        [concat {*}[get_db $object .location]] ne $location ||
        [get_db $object .place_status] ne $status} {
        error "Wrong pose for $name: [get_db $object .location] [get_db $object .place_status]"
    }
}
proc verify_db {} {
    require_pose memory {40.0 40.4} fixed
    require_pose buf_cell {78.8 69.2} placed
    set memory [get_db insts memory]
    if {![get_db $memory .is_place_halo]} {error "Memory halo missing"}
    set sides {}
    foreach side {left bottom right top} {lappend sides [get_db $memory .place_halo_$side]}
    if {$sides ne {2.0 3.0 4.0 5.0}} {error "Memory halo changed: $sides"}
    set block [get_db place_blockages PAD_RESERVE]
    set rectangles [get_db $block .rects]
    if {[get_db $block .type] ne "hard" || $rectangles ne {{20.0 20.0 33.86 98.0}}} {
        error "Incorrect reservation $rectangles"
    }
}
proc require_fixture_report {report} {
    set stream [open $report]
    set text [read $stream]
    close $stream
    # A single buffer rounds to a displayed density of 0.00%.
    if {![regexp -line {^\*info: Placed = 2[ \t]+\(Fixed = 1\)} $text] ||
        ![regexp -line {^\*info: Unplaced = 0[ \t]*$} $text] ||
        ![regexp -line {^Finished check_place\y} $text] ||
        [regexp -nocase -line {\m(violations?|overlap(s|ped|ping)?|illegal|errors?|warnings?)\M} $text]} {
        error "Unexpected placement report: $text"
    }
}
if {[catch {
    set_multi_cpu_usage -local_cpu 1
    if {$::env(TRI_PAD_SEED_FIXTURE_PHASE) eq "place"} {
        set lib $::env(CHECKPOINT_LIBS)/lef
        read_physical -lef [list $lib/tsmcn28_10lm5X2Y2ZUTRDL.tlef         $lib/tcbn28hpcplusbwp12t40p140.lef $lib/ts5n28hpcpsvta16x80m2fw_130a.lef]
        set stream [open fixture.v w]
        puts $stream {module probe(input clk, input a, output z);
          wire [79:0] q;
          TS5N28HPCPSVTA16X80M2FW memory(.CLK(clk), .Q(q));
          BUFFD1BWP12T40P140 buf_cell(.I(a), .Z(z));
        endmodule}
        close $stream
        read_netlist fixture.v
        init_design
        create_floorplan -site core12T -no_snap_to_grid -die_size {200 200 20 20 20 20}
        edit_pin -pin [get_db ports .name] -side left -spread_type side -layer M4 -snap track
        create_place_blockage -name PAD_RESERVE -type hard -rects {{20 20 33.86 98}} -no_cut_by_core
        set stream [open seed.def w]
        puts $stream {VERSION 5.8 ;
    DIVIDERCHAR "/" ;
    BUSBITCHARS "[]" ;
    DESIGN probe ;
    UNITS DISTANCE MICRONS 2000 ;
    COMPONENTS 2 ;
    - memory TS5N28HPCPSVTA16X80M2FW + FIXED ( 80000 80800 ) N
      + HALO 4000 6000 8000 10000
     ;
    - buf_cell BUFFD1BWP12T40P140 + PLACED ( 157600 138400 ) N ;
    END COMPONENTS
    END DESIGN}
        close $stream
        read_def -components seed.def
        verify_db
        check_place > placement.rpt
        require_fixture_report placement.rpt
        write_db placed.db
        write_def placed.def
        puts PAD_SEED_NATIVE_FIXTURE_IMPORT_PASS
    } elseif {$::env(TRI_PAD_SEED_FIXTURE_PHASE) eq "cold"} {
        read_db placed.db
        verify_db
        check_place > cold.rpt
        require_fixture_report cold.rpt
        write_def cold.def
        puts PAD_SEED_NATIVE_FIXTURE_PASS
    } else {
        error "Unknown placement seed fixture phase"
    }
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
