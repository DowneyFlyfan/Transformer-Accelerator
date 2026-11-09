# Diagnose the exact new29supply site; no optimizer or signoff claim.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set checkpoint_root $root/.cache/physical/pnr/$top
set out $checkpoint_root/qualification_supply_diagnosis_32
if {[file exists $out]} {error "Existing supply diagnosis"}
file mkdir $out
set_multi_cpu_usage -local_cpu 1
read_db $checkpoint_root/routed_routed_electrical_29.db
set_multi_cpu_usage -local_cpu 19
if {[llength [get_db insts]] != 94470} {error "Wrong native supply candidate"}
set_db route_detail_end_iteration 20
set site {190 312 197 319}
proc supply_snapshot {out label} {
    set file [open [format {%s/%s_shapes.tsv} $out $label] w]
    puts $file "special_wires: net layer shape rect path width"
    foreach w [get_obj_in_area -obj_type special_wire -areas {{185 310 200 322}}] {
        if {[get_db $w .net.name] ni {VDD VSS}} {continue}
        puts $file [list [get_db $w .net.name] [get_db $w .layer.name] [get_db $w .shape] [get_db $w .rect] [get_db $w .path] [get_db $w .width]]
    }
    puts $file "special_vias: net lower upper rect"
    foreach v [get_obj_in_area -obj_type special_via -areas {{185 310 200 322}}] {
        if {[get_db $v .net.name] ni {VDD VSS}} {continue}
        puts $file [list [get_db $v .net.name] [get_db $v .via_def.bottom_layer.name] [get_db $v .via_def.top_layer.name] [get_db $v .rect]]
    }
    close $file
    check_connectivity -type all -error 100000 -warning 100000 -check_pg_ports -out_file [format {%s/%s_connectivity.rpt} $out $label]
    check_drc -out_file [format {%s/%s_drc.rpt} $out $label]
}
supply_snapshot $out before
route_special -nets {VDD VSS} -connect core_pin -area $site -core_pin_target {stripe ring} -allow_layer_change 1 -allow_jogging 1 -layer_change_range {M1 M7}
supply_snapshot $out corepin_before_trim
edit_trim_routes -nets {VDD VSS}
supply_snapshot $out corepin_after_trim
# Explicitly connect floating stripes as a separate documented source class.
route_special -nets VSS -connect floating_stripe -area $site -floating_stripe_target {stripe ring} -stripe_layer_range {M1 M7} -allow_layer_change 1 -allow_jogging 1 -layer_change_range {M1 M7}
supply_snapshot $out after_floating_stripe
puts TRI_ORACLE_SRAM_CORE_SUPPLY_DIAGNOSIS32_FINISHED
exit
