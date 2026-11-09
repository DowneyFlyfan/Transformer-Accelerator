# Catch loss of a saved/pruned timing corner and accidental combined repair.
# Evaluate the real entry/settings/body; only native database/tool boundaries
# are replaced. The existing placement-report contract has its own native tests.
set status [catch {
    foreach {loaded_top admitted} {
        tri_oracle_cached_feedforward_core 0
        tri_oracle_memory_feedforward_core 1
    } {
        set child [interp create]
        try {
            interp eval $child [list set fixture_top $loaded_top]
            interp eval $child {
                unset -nocomplain ::env(TRI_ORACLE_TOP)
                set ::env(TRI_ORACLE_ROUTED_CHECKPOINT) /controlled/saved.db
                set events {}
                set active_views {-setup setup_slow -hold hold_fast}
                set preserved true
                set router_engine /expired/previous_process.tif
                rename source actual_source
                proc source {path} {
                    if {[file tail $path] eq "tri_oracle_require_clean_placement.tcl"} {
                        proc tri_oracle_require_clean_placement {path} {}
                        return
                    }
                    uplevel 1 [list actual_source $path]
                }
                proc set_multi_cpu_usage {args} {}
                proc read_db {path} {
                    if {$path ne "/controlled/saved.db"} {error "Override ignored"}
                    lappend ::events read
                }
                proc get_db {args} {
                    if {$args ne {current_design .name}} {error "Unexpected database query"}
                    return $::fixture_top
                }
                proc get_cells {name} {
                    if {$name ne "core"} {error "Wrong preserved hierarchy"}
                    lappend ::events release
                    return core
                }
                proc sizeof_collection {value} {return 1}
                proc get_property {args} {return $::preserved}
                proc set_dont_touch {object value} {set ::preserved $value}
                proc set_analysis_view {args} {set ::active_views $args}
                proc set_db {args} {}
                proc eval_legacy {script} {
                    if {$script eq {getNanoRouteMode -timingEngine}} {
                        return $::router_engine
                    }
                    if {$script ne {setNanoRouteMode -timingEngine CTE}} {
                        error "Unexpected legacy router command: $script"
                    }
                    set ::router_engine CTE
                }
                proc opt_design {args} {
                    if {[dict get $::active_views -setup] ne {setup_slow setup_typ} ||
                        [dict get $::active_views -hold] ne {hold_fast}} {
                        error "Missing restored analysis views before optimization"
                    }
                    if {[lsearch -exact $args -setup]>=0 ||
                        [lsearch -exact $args -hold]<0} {
                        error "Resume must begin separately checkpointed hold repair"
                    }
                    lappend ::events optimize_hold
                }
                proc check_place {args} {}
                proc connect_global_net {args} {}
                proc report_timing {args} {}
                proc check_drc {args} {}
                proc check_connectivity {args} {}
                proc write_db {args} {lappend ::events write_checkpoint}
                proc exit {args} {lappend ::events exit}
                set run_status [catch {source syn/tri_oracle_resume_memory_route.tcl} run_message]
            }
            set code [interp eval $child {set run_status}]
            set events [interp eval $child {set events}]
            if {$admitted} {
                if {$code || $events ne {read release optimize_hold write_checkpoint exit}} {
                    error "Pruned same-top checkpoint was not safely resumed: $events; [interp eval $child {set run_message}]"
                }
            } elseif {!$code || $events ne {read}} {
                error "Foreign checkpoint reached hierarchy changes: $events"
            }
        } finally {interp delete $child}
    }
    puts "PASS: foreign top rejected; full views restored before separate hold repair and checkpoint"
} message options]
if {$status} {puts stderr $message;exit 1}
