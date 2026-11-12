set entries $::env(TRI_ORACLE_CACHE_ENTRIES)
if {$entries ni {128 256}} {error "Unexpected sign-line cache depth"}
set_db max_cpus 2
set_db fail_on_error_mesg true
read_libs [list $::env(TRI_ORACLE_STD_LIB) $::env(TRI_ORACLE_CACHE_LIB)]
read_hdl -sv $::env(TRI_ORACLE_CACHE_RTL)
elaborate -parameters [list [list ENTRIES $entries]] tri_oracle_dual_port_sign_line_cache
set macros [get_db insts -if {.base_cell.name == TS5N28HPCPSVTA32X128M2FW}]
set expected [expr {$entries / 8}]
if {[llength $macros] != $expected} {error "Sign-line cache macro count mismatch"}
set area 0.0
foreach macro $macros {
    set cell_area [get_db $macro .base_cell.area]
    if {$cell_area <= 0} {error "Missing compiled memory area"}
    set area [expr {$area + $cell_area}]
}
puts "SIGN_LINE_CACHE_MACROS entries=$entries macros=$expected data_bytes=[expr {$entries*64}] area_um2=$area"
exit
