# The measured remaining RV failures each have 0.760um^2 diode area, giving
# allowed ratio463.0800 below489.1304. Add one real diode at each failing pin;
# keep the foundry ratios and repair the measured local M1 spacing conflict.
source syn/tri_oracle_physical_config.tcl
source syn/tri_oracle_require_clean_placement.tcl
if {$top ne "tri_oracle_memory_compute"} {error "Core-only antenna touch-up"}
set_multi_cpu_usage -local_cpu 18
read_db $out/routed.db
set tag $::env(TRI_ORACLE_PHYSICAL_STAGE)
if {[file exists $out/${tag}_input.db]} {error "Refusing to overwrite input backup"}
write_db -rc_extract $out/${tag}_input.db
set diode ANTENNABWP12T40P140
if {[llength [get_db base_cells $diode]] != 1} {error "Required real antenna cell absent"}
if {[llength [get_db insts *TRI_ANTENNA_RV_*]] != 0} {error "Touch-up diode prefix already exists"}
set before [llength [get_db insts -if {.base_cell.name == ANTENNABWP12T40P140}]]
set targets [list \
    [list {storage[10].weights/words_reg[23][4]} SI {storage[10].weights/FE_PHN241892_words_23_4}] \
    [list {storage[4].inputs/FE_PHC445041_words_12_28} I {storage[4].inputs/FE_PHN445041_words_12_28}] \
    [list {storage[4].inputs/FE_PHC439326_words_6_15} I {storage[4].inputs/FE_PHN52622_words_6_15}]]
foreach target $targets {
    lassign $target inst_name terminal net_name
    set inst [get_db insts $inst_name]
    if {[llength $inst] != 1 || [get_db $inst .name] ne $inst_name} {error "Missing antenna receiver $inst_name"}
    set pin [get_db $inst .pins -if {.base_name == $terminal}]
    if {[llength $pin] != 1 || [get_db $pin .net.name] ne $net_name} {error "Antenna receiver/net mismatch"}
    # Native create_diode.1 documents two arguments after -pin: instance, pin.
    create_diode -prefix TRI_ANTENNA_RV_ -diode_cell $diode -pin $inst_name $terminal
}
set after [llength [get_db insts -if {.base_cell.name == ANTENNABWP12T40P140}]]
if {$after != $before + 3} {error "Expected exactly three additional diode cells"}
# create_diode preplaces cells even when those sites overlap occupied rows.
# place_eco otherwise skips them as already placed. Explicitly unplace only the
# three new diodes, so the placer can find legal sites with existing cells fixed.
set new_diodes [get_db insts *TRI_ANTENNA_RV_*]
if {[llength $new_diodes] != 3} {error "Unexpected new diode identity count"}
foreach inst $new_diodes {
    if {[get_db $inst .base_cell.name] ne $diode} {error "New diode identity mismatch"}
    set_db $inst .place_status unplaced
    if {[get_db $inst .place_status] ne "unplaced"} {error "Failed to unplace new diode"}
}
place_eco -fix_placed_insts true
check_place > $out/${tag}_preroute_placement.rpt
puts "TRI_ORACLE_ANTENNA_TOUCHUP_PLACEMENT_PASS [tri_oracle_require_clean_placement $out/${tag}_preroute_placement.rpt]"
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
route_eco
# The preceding check_drc located the wire-versus-diode-pin M1 spacing violation
# at(373.365,208.275)-(373.395,208.755). Existing placed instances are fixed above.
route_detail {372.8 207.7 374.0 209.4}
check_place > $out/${tag}_placement.rpt
puts "TRI_ORACLE_ANTENNA_TOUCHUP_FINAL_PLACEMENT_PASS [tri_oracle_require_clean_placement $out/${tag}_placement.rpt]"
check_antenna -out_file $out/${tag}_antenna.rpt
check_drc -out_file $out/${tag}_drc.rpt
check_connectivity -type all -out_file $out/${tag}_connectivity.rpt
report_timing -view setup_slow -check_type setup > $out/${tag}_setup_slow.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_CORE_ANTENNA_TOUCHUP_COMMANDS_FINISHED"
exit
