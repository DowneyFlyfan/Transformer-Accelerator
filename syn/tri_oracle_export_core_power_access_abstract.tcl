# Recompute antenna data before exporting the unchanged signal interface.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI_ORACLE_PLACEMENT_PROBE_DIRECTORY)
read_db $root/.cache/physical/pnr/tri_oracle_core_power_access41/power_terminal_candidate.db
set_multi_cpu_usage -local_cpu 4
if {[get_db current_design .name] ne "tri_oracle_sram_memory_compute" ||
    [llength [get_db insts]] != 94471} {error "CORE_POWER42_WRONG_PHYSICAL_REFERENCE"}
check_antenna -out_file $out/antenna.rpt
write_lef_abstract $out/core.lef -top_layer 10 -stripe_pins \
    -pg_pin_layers {8 9} -port_for_each_stripe_pin -extract_block_obs
puts TRI_ORACLE_CORE_POWER_ACCESS42_ABSTRACT_EXPORTED
exit
