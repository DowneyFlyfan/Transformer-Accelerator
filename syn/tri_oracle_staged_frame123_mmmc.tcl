# Physical analysis uses real standard-cell/memory libraries and complete core ILMs.
# The provisional extracted core timing library is deliberately absent here.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_predicted_feedforward_frame
foreach {corner suffix qrc temperature} {
    typ tt1v25c qrc_typical 25
    slow ssg0p9v125c qrc_rcworst 125
    fast ffg1p05vm40c qrc_rcbest -40
} {
    set libraries [list \
        $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140${suffix}.lib \
        $root/.cache/physical/sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/NLDM/ts5n28hpcpsvta32x128m2fw_130a_${suffix}.lib \
        $root/.cache/physical/sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/NLDM/ts6n28hpcpsvta16x128m2f_130a_${suffix}.lib \
        $root/.cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/NLDM/ts5n28hpcpsvta512x64m4f_130a_${suffix}.lib]
    foreach library $libraries {
        if {![file isfile $library]} {error "Missing physical library: $library"}
    }
    create_library_set -name ls_$corner -timing $libraries
    create_rc_corner -name rc_$corner -qrc_tech $root/.cache/physical/rc/$qrc -temperature $temperature
    create_timing_condition -name tc_$corner -library_sets [list ls_$corner]
    create_delay_corner -name dc_$corner -timing_condition tc_$corner -rc_corner rc_$corner
}
set constraints $root/.cache/physical/synthesis/tri_oracle_predicted_feedforward_staged122/constraints.sdc
create_constraint_mode -name functional -sdc_files [list $constraints]
update_constraint_mode -name functional -ilm_sdc_files [list $constraints]
create_analysis_view -name setup_typ -constraint_mode functional -delay_corner dc_typ
create_analysis_view -name setup_slow -constraint_mode functional -delay_corner dc_slow
create_analysis_view -name hold_fast -constraint_mode functional -delay_corner dc_fast
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
