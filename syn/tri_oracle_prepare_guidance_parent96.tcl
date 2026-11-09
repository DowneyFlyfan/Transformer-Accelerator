# Persist the guidance view before any optimizer/timing caches are built.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set parent $root/.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30
set base $root/.cache/physical/pnr/tri_oracle_sram_memory_compute
set out $::env(TRI_ORACLE_GUIDANCE_PREPARATION_DIRECTORY)
set cold [expr {[info exists ::env(TRI_ORACLE_GUIDANCE_PREPARATION_COLD)] && $::env(TRI_ORACLE_GUIDANCE_PREPARATION_COLD) eq "1"}]
source $root/syn/tri_oracle_guided_parent_checks.tcl
read_db $::env(TRI_ORACLE_GUIDANCE_PREPARATION_INPUT)
set_multi_cpu_usage -local_cpu 2
if {[get_db current_design .name] ne "tri_oracle_predicted_fabric"} {error "GUIDANCE96_WRONG_PARENT"}
unflatten_ilm
set original_macros [guided85_macros]
set file [open $out/macros.tsv w]; puts $file $original_macros; close $file

proc guidance96_parent_snapshot {filename} {
    set file [open $filename w]
    puts $file "instance\tmaster\tlocation\torientation"
    foreach instance [get_db insts] {
        puts $file "[get_db $instance .name]\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]"
    }
    close $file
    return [llength [get_db insts]]
}
set parent_count [guidance96_parent_snapshot $out/parent_before.tsv]
if {$parent_count != 337515} {error "GUIDANCE96_WRONG_PARENT_INVENTORY: $parent_count"}
if {!$cold} {
    read_ilm -cell tri_oracle_sram_memory_compute -directory $base/hierarchy_export_58/ilm
}
set_ilm_type -model si
flatten_ilm
guided85_snapshot $out/guidance.tsv 33818
report_ilm_status > $out/models.rpt
unflatten_ilm
if {[guided85_macros] ne $original_macros} {error "GUIDANCE96_MACRO_CHANGED"}
if {[guidance96_parent_snapshot $out/parent_after.tsv] != $parent_count} {error "GUIDANCE96_PARENT_COUNT_CHANGED"}
guided85_registered_reset $root $out
if {$cold} {
    puts TRI_ORACLE_GUIDANCE96_FRESH_PROCESS_COMPACT_PARENT_VERIFIED
    exit
}
# Save unflattened parent cells plus the compact-model mapping. The next
# optimization must start in a fresh process and must later restore full68.
write_netlist $out/prepared_parent.v -exclude_leaf_cells
write_db $out/prepared_guidance.db
puts TRI_ORACLE_GUIDANCE96_CHECKPOINT_PREPARED_WITHOUT_OPTIMIZATION
exit
