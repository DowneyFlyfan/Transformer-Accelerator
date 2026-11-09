# Preserve the design-level optimization flag separately from leaf/hinst flags.
proc tri242_design_snapshot {filename} {
    set stream [open $filename w]
    puts $stream "design\tdont_touch"
    puts $stream "[get_db current_design .name]\t[get_db current_design .dont_touch]"
    close $stream
}
proc tri242_require_design {reference filename} {
    tri242_design_snapshot $filename
    if {[catch {exec cmp -s $reference $filename}]} {error TRI242_DESIGN_PRESERVATION_CHANGED}
}
proc tri242_restore_design {filename} {
    set stream [open $filename r]
    set header [gets $stream]
    set row [gets $stream]
    set tail_count [gets $stream tail]
    close $stream
    if {$header ne "design\tdont_touch" || [llength [split $row "\t"]]!=2 || $tail_count>=0} {error TRI242_BAD_DESIGN_LEDGER}
    lassign [split $row "\t"] name flag
    if {$name ne [get_db current_design .name]} {error TRI242_WRONG_DESIGN_METADATA_TARGET}
    if {$flag ni {none false true}} {error TRI242_UNSUPPORTED_DESIGN_FLAG}
    if {[get_db current_design .dont_touch] ne $flag} {set_db [get_db current_design] .dont_touch $flag}
}
