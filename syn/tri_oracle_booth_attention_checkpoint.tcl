proc advance_or_checkpoint {duration slot overwrite} {
    set report [run $duration]
    puts -nonewline $report
    if {[string first {Simulation complete via $finish(1)} $report] == 0} {
        return 1
    }
    if {[string first "Ran until " $report] != 0} {
        error "Native replay stopped before the end of its checkpoint interval"
    }
    if {$overwrite} {
        puts -nonewline [save -simulation $slot -overwrite]
    } else {
        puts -nonewline [save -simulation $slot]
    }
    puts "TRI_UNSEEDED_PACKET_CHECKPOINT $slot"
    return 0
}
set index 1
if {[info exists ::env(TRI_ORACLE_REPLAY_FROM_CHECKPOINT)]} {
    set saved_index $::env(TRI_ORACLE_REPLAY_FROM_CHECKPOINT)
    if {![string is entier -strict $saved_index] || $saved_index < 0 || $saved_index >= 140} {
        error "Invalid saved checkpoint index"
    }
    set index [expr {$saved_index + 1}]
    puts "TRI_UNSEEDED_PACKET_RESTORE $saved_index"
} else {
    if {[advance_or_checkpoint 1200000ns checkpoint_a 0]} {
        exit
    }
}
for {} {$index <= 140} {incr index} {
    set slot [expr {$index % 2 ? "checkpoint_b" : "checkpoint_a"}]
    if {[advance_or_checkpoint 15000000ns $slot 1]} {
        exit
    }
}
error "Checkpointed replay exceeded the simulated-time limit"
