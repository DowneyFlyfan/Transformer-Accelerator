# Native admission check: load a small existing foreign database and verify
# that the real resume entry stops at its loaded-top guard. No database writes
# or placement/routing commands are executed by the passing path.
set ::env(TRI_ORACLE_ROUTED_CHECKPOINT) .cache/physical/pnr/tri_oracle_tile_executor/initialized.db
set ::env(TRI_ORACLE_TOP) tri_oracle_cached_feedforward_core
set status [catch {source syn/tri_oracle_resume_cached_route.tcl} message]
if {!$status || [string first "Loaded checkpoint top 'tri_oracle_tile_executor' differs" $message] != 0} {
    puts stderr "Unexpected native resume result: status=$status message=$message"
    exit 1
}
if {[get_db current_design .name] ne "tri_oracle_tile_executor"} {
    puts stderr "Native current-design query does not identify the loaded checkpoint"
    exit 1
}
puts "TRI_ORACLE_CACHED_FOREIGN_NATIVE_REJECTED tri_oracle_tile_executor"
exit 0
