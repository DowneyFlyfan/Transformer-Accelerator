# Read-only setup-margin inventory for every currently negative hold endpoint.
# This prepares measured repair admission; it never changes cells or routes.
source syn/tri_oracle_memory_physical_config.tcl
source syn/tri_oracle_endpoint_hold_policy.tcl
set_multi_cpu_usage -local_cpu 20
read_db $out/routed.db
tri_oracle_require_memory_design
set_multi_cpu_usage -local_cpu 20
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db delaycal_enable_si true
set_db si_delay_enable_report true

set paths [report_timing -early -view hold_fast -collection \
    -max_paths 10000 -nworst 1 -max_slack 0]
set count [sizeof_collection $paths]
if {$count <= 0 || $count >= 10000} {
    error "Expected a complete bounded nonempty negative-hold endpoint set: $count"
}
# Copy physical pins before changing timing views; do not retain path objects.
set targets [copy_collection [get_property $paths capturing_point]]
set rows [dict create]
foreach_in_collection path $paths {
    set launch [get_object_name [get_property $path launching_point]]
    set capture [get_object_name [get_property $path capturing_point]]
    set slack [get_property $path slack]
    tri_oracle_finite_timing_value $slack
    if {$slack >= 0 || $slack < -0.050} {error "Unexpected negative-hold deficit at $capture"}
    if {![regexp {^\S+$} $launch] || ![regexp {^\S+$} $capture]} {
        error "Unsupported whitespace in native endpoint identity"
    }
    if {[dict exists $rows $capture]} {error "Duplicate negative-hold endpoint: $capture"}
    dict set rows $capture [list $launch $slack]
}
unset paths
if {[dict size $rows] != $count} {error "Hold target inventory changed while collecting pins"}
puts "TRI_ORACLE_MEMORY_ENDPOINT_MARGIN_TARGETS $count"

set setup_slacks [dict create]
foreach view {setup_slow setup_typ} {
    set setup [report_timing -view $view -check_type setup -to $targets \
        -max_paths 10000 -nworst 1 -collection]
    set setup_count [sizeof_collection $setup]
    if {$setup_count <= 0 || $setup_count >= 10000} {
        error "Missing or potentially truncated $view setup endpoint inventory: $setup_count"
    }
    set observed [dict create]
    foreach_in_collection path $setup {
        set capture [get_object_name [get_property $path capturing_point]]
        if {![dict exists $rows $capture]} {error "Unexpected $view endpoint: $capture"}
        set slack [get_property $path slack]
        tri_oracle_finite_timing_value $slack
        if {![dict exists $observed $capture] || $slack < [dict get $observed $capture]} {
            dict set observed $capture $slack
        }
    }
    unset setup
    foreach capture [dict keys $rows] {
        if {![dict exists $observed $capture]} {error "No $view setup path for $capture"}
        dict set setup_slacks $capture $view [dict get $observed $capture]
    }
    if {[dict size $observed] != $count} {error "Incomplete $view setup endpoint coverage"}
    puts "TRI_ORACLE_MEMORY_ENDPOINT_MARGIN_VIEW $view ENDPOINTS [dict size $observed]"
}

set file [open $out/postroute_endpoint_margin_probe.tsv w]
puts $file "launch\tendpoint\thold_fast_ns\tsetup_slow_ns\tsetup_typ_ns"
set below_reserve 0
foreach capture [lsort [dict keys $rows]] {
    lassign [dict get $rows $capture] launch hold
    set slow [dict get $setup_slacks $capture setup_slow]
    set typical [dict get $setup_slacks $capture setup_typ]
    if {$slow < 0.450 || $typical < 0.450} {incr below_reserve}
    puts $file [join [list $launch $capture $hold $slow $typical] \t]
}
close $file
puts "TRI_ORACLE_MEMORY_ENDPOINTS_BELOW_0450NS_RESERVE $below_reserve"
puts "TRI_ORACLE_MEMORY_ENDPOINT_MARGINS_FINISHED"
exit
