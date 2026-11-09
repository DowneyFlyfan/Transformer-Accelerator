# Native parent power-grid experiment using the validated clocked core model.
# Special-route checks operate on the parent and original macro PG contacts;
# the unchanged internal core grid is covered by core44 qualification.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI_ORACLE_PLACEMENT_PROBE_DIRECTORY)
read_db $root/.cache/physical/pnr/tri_oracle_clock_probe35_green6/clocked_probe.db
set_multi_cpu_usage -local_cpu 4
unflatten_ilm
if {[get_db current_design .name] ne "tri_oracle_preserved_placement_probe21"} {
    error "PARENT_POWER37_WRONG_INPUT_DESIGN"
}
set block [get_db insts core0]
if {[get_db $block .place_status] ne "fixed" || ![get_db $block .dont_touch]} {
    error "PARENT_POWER37_UNPROTECTED_CORE"
}
set original_pose [list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]]
source $root/syn/tri_oracle_parent_power_grid.tcl
tri_oracle_add_parent_power_grid37 799.955 750 \
    {{20 20 779.955 40} {20 710 779.955 730}} $out/power_shapes.tsv
write_db $out/power_candidate.db
check_drc -check_only special -limit 100000 -out_file $out/special_drc.rpt
check_connectivity -type special -nets {VDD VSS} -check_pg_ports \
    -error 100000 -warning 100000 -out_file $out/power_connectivity.rpt
check_place > $out/placement.rpt
source $root/syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/placement.rpt
set block [get_db insts core0]
if {[list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]] ne $original_pose || ![get_db $block .dont_touch]} {
    error "PARENT_POWER37_ORIGINAL_CORE_MOVED"
}
write_def $out/power_parent.def -routing
set_ilm_type -model si
flatten_ilm
set file [open $out/core_after.tsv w]
puts $file "instance\tmaster\tlocation\torientation"
set count 0
foreach instance [get_db insts] {
    set name [get_db $instance .name]
    if {![string match {core0/*} $name]} {continue}
    puts $file "$name\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]"
    incr count
}
close $file
if {$count != 94471} {error "PARENT_POWER37_CHANGED_OR_INCOMPLETE_CORE"}
set file [open $out/core_prefixes.txt w]; puts $file core0; close $file
exec python3 -B $root/syn/tri_oracle_core_preservation.py \
    $root/.cache/physical/pnr/tri_oracle_clock_probe35_green6/core_after.tsv \
    $out/core_after.tsv $out/core_prefixes.txt > $out/core_preservation.json
puts TRI_ORACLE_PARENT_POWER37_CANDIDATE_CONSTRUCTED
exit
