# Resume only after the prior job is authoritatively terminal.
# Caller supplies a verified native checkpoint and phase map or opt.
set top tri_oracle_memory_compute
if {$::env(TRI_ORACLE_TOP) ne $top} {error "Wrong resume top"}
set phase $::env(TRI_ORACLE_RESUME_PHASE)
if {$phase ni {map opt}} {error "Resume phase must be map or opt"}
set checkpoint $::env(TRI_ORACLE_CORE_CHECKPOINT)
if {![file isfile $checkpoint]} {error "Native checkpoint missing"}
set output .cache/physical/synthesis/$top
file mkdir $output
read_db $checkpoint
if {[llength [get_db designs $top]] != 1} {error "Checkpoint does not contain the expected core"}
# Apply AFTER read_db; the saved database may contain the old CPU settings.
# Avoid the max_cpus alias: it changes max_cpus_per_server.
set_db auto_super_thread false
set_db super_thread_servers {localhost localhost}
set_db max_cpus_per_server 8
set_db auto_ungroup none
puts "TRI_ORACLE_RESUME_CONFIGURATION phase=$phase servers=[get_db / .super_thread_servers] cpus_per_server=[get_db / .max_cpus_per_server]"
if {$phase eq "map"} {
    syn_map
    write_db ${output}/mapped.db
    puts "TRI_ORACLE_MAPPED_CHECKPOINT_WRITTEN $top"
}
syn_opt
report_area > ${output}/area.rpt
report_timing > ${output}/timing.rpt
report_power > ${output}/power_default_activity.rpt
write_hdl > ${output}/netlist.v
write_sdc > ${output}/constraints.sdc
puts "TRI_ORACLE_SYNTHESIS_PASS $top"
exit
