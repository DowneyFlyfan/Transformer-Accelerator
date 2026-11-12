set top tri_oracle_packed_outlier_replay
set_db max_cpus 4
set_db auto_super_thread false
set_db fail_on_error_mesg true
read_libs [list $::env(TRI_ORACLE_STD_LIB) $::env(TRI_ORACLE_CACHE_LIB) $::env(TRI_ORACLE_METADATA_LIB)]
read_hdl -sv [list \
    $::env(TRI_ORACLE_RANKED_ALLOCATOR) $::env(TRI_ORACLE_PACKED_SIGN_FETCH) \
    $::env(TRI_ORACLE_RANKED_SIGN_CACHE) $::env(TRI_ORACLE_RANKED_PREDICTOR)]
elaborate -parameters {{CORE_STRIP_PREDICTOR 1}} $top

proc require_ranked_memories {} {
    set cache [get_db insts -if {.base_cell.name == TS5N28HPCPSVTA32X128M2FW}]
    set metadata [get_db insts -if {.base_cell.name == TS5N28HPCPSVTA512X64M4F}]
    if {[llength $cache] != 4 || [llength $metadata] != 2} {
        error "Unexpected ranked predictor memory inventory"
    }
    return [concat $cache $metadata]
}
foreach macro [require_ranked_memories] {
    set_db $macro .preserve true
}

create_clock -name core_clock -period 1.72414 [get_ports clk]
set_clock_uncertainty 0.05 [get_clocks core_clock]
set inputs [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_input_delay 0.2 -clock core_clock $inputs
set_input_transition 0.05 $inputs
set_output_delay 0.2 -clock core_clock [all_outputs]
set_load 0.005 [all_outputs]
set_false_path -from [get_ports rst_n]
set_db syn_generic_effort low
syn_generic
syn_map
syn_opt
require_ranked_memories
check_design -unresolved > check.rpt
report_area > area.rpt
report_timing -max_paths 15 > timing.rpt
write_hdl > netlist.v
write_sdc > constraints.sdc
puts "TRI_ORACLE_RANKED_SIGN_PREDICTOR_MAPPED data_macros=4 metadata_macros=2"
exit
