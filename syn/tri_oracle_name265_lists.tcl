# Compare physical pin-name lists without depending on their string spelling.
proc tri265_names_equal {actual expected} {
    return [expr {[lsort $actual] eq [lsort $expected]}]
}
