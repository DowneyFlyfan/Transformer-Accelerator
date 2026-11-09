# Run in an empty Innovus process. The actual design export/read is checked by
# the routed repair, while this probe checks engine reset and stale-file refusal.
if {[catch {
    source syn/tri_oracle_router_timing_interface.tcl
    set_multi_cpu_usage -local_cpu 20
    set root [file normalize .cache/router_timing_native_test_[pid]]
    if {[file exists $root]} {error "Refusing an existing probe directory"}
    file mkdir $root
    try {
        eval_legacy [list setNanoRouteMode -timingEngine $root/nonexistent.tif]
        tri_oracle_reset_router_timing
        if {[eval_legacy {getNanoRouteMode -timingEngine}] ne {CTE}} {error "Default engine was not restored"}
        set path $root/existing.tif
        set channel [open $path w];puts -nonewline $channel "preserved timing fixture";close $channel
        if {![catch {tri_oracle_export_router_timing $path} refusal] || ![string match {Refusing existing router timing file:*} $refusal]} {error "Existing timing export was not explicitly refused: $refusal"}
        set channel [open $path r];set text [read $channel];close $channel
        if {$text ne {preserved timing fixture}} {error "Timing export overwrote an existing file"}
        file link -symbolic $root/dangling.tif $path
        file delete $path
        if {![catch {tri_oracle_export_router_timing $root/dangling.tif} refusal] || ![string match {Refusing existing router timing file:*} $refusal]} {error "Dangling timing link was not explicitly refused: $refusal"}
        if {![catch {file lstat $path ignored}]} {error "Dangling timing target was created"}
        puts "TRI_ORACLE_ROUTER_TIMING_NATIVE_PROBE_FINISHED"
    } finally {file delete -force $root}
} message]} {puts stderr $message;exit 1}
exit
