# Require native protected core-clock roots and actual model insertion latency.
proc tri_oracle_require_preserved_clock_boundaries {filename prefixes} {
    set file [open $filename w]
    puts $file "core\toriginal_clock_root\tsink_type\treasons\tinsertion_delay_sources"
    if {[lsearch -exact [get_db clock_trees .name] core_clock] < 0} {
        error "PARENT_CLOCK36_MISSING_CLOCK_TREE"
    }
    foreach prefix [dict keys $prefixes] {
        # The native probe35 spec identifies this original core44 buffer as
        # the protected model boundary and derives its downstream latency.
        set name $prefix/CTS_ccl_buf_00324/I
        set pin pin:$name
        set type [get_db $pin .cts_sink_type]
        set reasons [get_db $pin .cts_sink_type_reasons]
        set insertion [get_db $pin .cts_pin_insertion_delay_sources]
        if {$type ne "stop" || [lsearch -exact $reasons ilm] < 0 ||
            [lsearch -exact $insertion ilm] < 0 ||
            ![string is double -strict [lindex $insertion end]] ||
            [lindex $insertion end] <= 0} {
            error "PARENT_CLOCK36_UNPROTECTED_OR_UNMODELED_CLOCK: $name"
        }
        puts $file "$prefix\t$name\t$type\t$reasons\t$insertion"
    }
    close $file
}

