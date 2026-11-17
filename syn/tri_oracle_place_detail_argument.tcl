# place_detail -inst parses a whitespace-delimited string. Tcl list formatting
# adds literal braces around indexed instance names, which Innovus rejects.
proc tri_oracle_place_detail_argument {instances} {
    if {[llength $instances] == 0} {error "An explicit nonempty placement scope is required"}
    set seen [dict create]
    foreach name $instances {
        if {[regexp {\s|[{}]} $name]} {error "Instance cannot be represented in placement scope: $name"}
        if {[dict exists $seen $name]} {error "Repeated instance in placement scope: $name"}
        dict set seen $name 1
    }
    return [join $instances " "]
}
