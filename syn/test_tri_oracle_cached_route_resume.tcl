# Removing the loaded-top guard must admit a foreign checkpoint and fail this
# test. Native database/optimization commands are isolated because this test
# exercises admission ordering without allocating another physical database.
set test_status [catch {
    foreach {loaded_top override admitted} {
        tri_oracle_normalized_feedforward_core 1 0
        {} 1 0
        tri_oracle_cached_feedforward_core 1 1
        tri_oracle_cached_feedforward_core 0 1
    } {
        set child [interp create]
        try {
            interp eval $child [list set fixture_top $loaded_top]
            interp eval $child [list set fixture_override $override]
            interp eval $child {
                unset -nocomplain ::env(TRI_ORACLE_TOP) ::env(TRI_ORACLE_ROUTED_CHECKPOINT)
                if {$fixture_override} {
                    set ::env(TRI_ORACLE_ROUTED_CHECKPOINT) /controlled/foreign.db
                }
                set events {}
                set preserved true
                rename source actual_source
                proc source {path} {
                    if {[file tail $path] eq "tri_oracle_finish_route.tcl"} {
                        lappend ::events optimize
                        return
                    }
                    uplevel 1 [list actual_source $path]
                }
                proc set_multi_cpu_usage {args} {}
                proc read_db {path} {
                    if {$::fixture_override && $path ne "/controlled/foreign.db"} {
                        error "Checkpoint override was ignored"
                    }
                    if {!$::fixture_override && [file tail $path] ne "routed_before_optimization.db"} {
                        error "Wrong default checkpoint"
                    }
                    lappend ::events read
                }
                proc get_db {args} {
                    if {$args ne {current_design .name}} {error "Unexpected database query: $args"}
                    if {$::events ne {read}} {error "Loaded-top query must precede hierarchy changes"}
                    return $::fixture_top
                }
                proc get_cells {name} {
                    if {$name ne "execution/core"} {error "Wrong preserved hierarchy"}
                    lappend ::events release
                    return core
                }
                proc sizeof_collection {collection} {return 1}
                proc get_property {object property} {return $::preserved}
                proc set_dont_touch {object value} {set ::preserved $value}
                proc exit {args} {lappend ::events exit}
                set run_status [catch {source syn/tri_oracle_resume_cached_route.tcl} run_message]
            }
            set run_status [interp eval $child {set run_status}]
            set events [interp eval $child {set events}]
            if {$admitted} {
                if {$run_status || $events ne {read release optimize exit}} {
                    error "Valid checkpoint did not reach optimization: $events; [interp eval $child {set run_message}]"
                }
            } elseif {!$run_status || $events ne {read}} {
                error "Foreign/empty loaded design reached hierarchy release or optimization: $loaded_top; events=$events"
            } elseif {![string match "Loaded checkpoint top*" [interp eval $child {set run_message}]]} {
                error "Checkpoint rejected for an unrelated error: [interp eval $child {set run_message}]"
            }
        } finally {
            interp delete $child
        }
    }
    puts "PASS: foreign and empty database tops rejected before hierarchy release; valid default/override checkpoints proceed"
} test_message test_options]
if {$test_status} {puts stderr $test_message;exit 1}
