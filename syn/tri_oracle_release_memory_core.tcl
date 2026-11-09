# Genus preservation avoids resynthesizing the imported core. Its exported
# set_dont_touch also prevents physical buffering; release only that hierarchy.
proc tri_oracle_release_memory_core {} {
    set core [get_cells core]
    if {[sizeof_collection $core] != 1} {error "Expected one core hierarchy"}
    set before [get_property $core dont_touch]
    puts "TRI_ORACLE_CORE_PHYSICAL_PRESERVATION_BEFORE $before"
    set_dont_touch $core false
    set after [get_property $core dont_touch]
    if {![string is boolean -strict $after] || $after} {
        error "Core physical preservation was not released: $after"
    }
    puts "TRI_ORACLE_CORE_PHYSICAL_PRESERVATION_AFTER $after"
}
