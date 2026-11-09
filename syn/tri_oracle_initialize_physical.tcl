source syn/tri_oracle_physical_config.tcl
file mkdir $out
set_multi_cpu_usage -local_cpu 18
set_db design_process_node 28
set_db init_power_nets {VDD}
set_db init_ground_nets {VSS}
read_mmmc $root/syn/tri_oracle_mmmc.tcl
read_physical -lefs [list \
    $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
    $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef]
read_netlist $root/.cache/physical/synthesis/$top/netlist.v -top $top
init_design
create_floorplan -site core12T -stdcell_density_size {1.0 0.55 10 10 10 10}
write_db $out/initialized.db
puts "TRI_ORACLE_PHYSICAL_INITIALIZATION_FINISHED"
exit
