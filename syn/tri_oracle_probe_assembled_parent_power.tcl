# Verify supplies using the real routed physical core, including internal
# power metal, rather than using interface-model power fragments as a layout.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI_ORACLE_PLACEMENT_PROBE_DIRECTORY)
if {![info exists ::env(TRI_ORACLE_ASSEMBLY_PARENT_DATABASE)] ||
        ![file isdirectory $::env(TRI_ORACLE_ASSEMBLY_PARENT_DATABASE)]} {
    error "PARENT_POWER48_REQUIRES_COMPLETED_PARENT_GRID_DATABASE"
}
read_db $::env(TRI_ORACLE_ASSEMBLY_PARENT_DATABASE)
set_multi_cpu_usage -local_cpu 4
unflatten_ilm
if {[get_db current_design .name] ne "tri_oracle_preserved_placement_probe21"} {
    error "PARENT_POWER48_WRONG_INPUT_PARENT"
}
write_def $out/before_assembly.def -routing
assemble_design -block_data \
    $root/.cache/physical/pnr/tri_oracle_core_power_access41/after.def \
    $root/.cache/physical/pnr/tri_oracle_sram_memory_compute/qualification_typical_repair_44/routed_netlist.v \
    -keep_pg_pin_geometry -keep_pin_geometry -dont_merge_block_pg_nets \
    -out_file $out/assembly.rpt
puts TRI_ORACLE_PARENT_POWER48_PHYSICAL_CORE_ASSEMBLED

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
if {$count != 94471} {error "PARENT_POWER48_INCOMPLETE_ASSEMBLED_CORE: $count"}
set file [open $out/core_prefixes.txt w]; puts $file core0; close $file
exec python3 -B $root/syn/tri_oracle_core_preservation.py \
    $root/.cache/physical/pnr/tri_oracle_clock_probe35_green6/core_after.tsv \
    $out/core_after.tsv $out/core_prefixes.txt > $out/core_preservation.json
write_db $out/assembled_before_trim.db
check_connectivity -type special -nets {VDD VSS} -check_pg_ports \
    -error 100000 -warning 100000 -out_file $out/supply_before_trim.rpt
edit_trim_routes -nets {VDD VSS}
check_connectivity -type special -nets {VDD VSS} -check_pg_ports \
    -error 100000 -warning 100000 -out_file $out/supply_after_trim.rpt
check_drc -check_only special -limit 100000 -out_file $out/special_drc.rpt
check_place > $out/placement.rpt
source $root/syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/placement.rpt
write_def $out/assembled_parent.def -routing
write_db $out/assembled_parent.db
puts TRI_ORACLE_PARENT_POWER48_ASSEMBLED_GRID_CHECKED
exit
