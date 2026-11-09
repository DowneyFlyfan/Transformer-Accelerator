# Compare identical boundary timing queries in the full block and cold ILM probe.
proc tri_oracle_record_boundary_paths {out} {
    foreach view {setup_slow setup_typ hold_fast} {
        time_design -post_route -drv_report -expanded_views -report_dir $out/refresh_$view -report_prefix refresh_$view
        foreach boundary {inputs outputs} {
            set command [list report_timing -view $view -max_paths 100000 -nworst 1 -collection]
            if {$view eq {hold_fast}} {
                lappend command -early
            } else {
                lappend command -check_type setup
            }
            if {$boundary eq {inputs}} {
                lappend command -from [all_inputs -no_clocks]
            } else {
                lappend command -to [all_outputs]
            }
            set paths [eval $command]
            set count [sizeof_collection $paths]
            if {$count < 1 || $count >= 100000} {error "Missing or truncated boundary paths: $view $boundary"}
            set file [open $out/[format {boundary_%s_%s.tsv} $view $boundary] w]
            puts $file "start\tendpoint\tslack_ns\tpath_delay_ns\tarrival_ns"
            foreach_in_collection path $paths {
                set start [get_object_name [get_property $path launching_point]]
                set end [get_object_name [get_property $path capturing_point]]
                puts $file "$start\t$end\t[get_property $path slack]\t[get_property $path path_delay]\t[get_property $path arrival]"
            }
            close $file
            puts "TRI_ORACLE_BOUNDARY_PATHS $view $boundary $count"
            unset paths
        }
    }
}
