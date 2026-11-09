source syn/tri_oracle_name265_lists.tcl
set failures 0
set count 0
proc check {label actual expected wanted} {
    global failures count
    incr count
    set got [tri265_names_equal $actual $expected]
    if {$got!=$wanted} {puts "FAIL $label expected=$wanted actual=$got";incr failures}
}
set first {numeric/engine/backend/clusters[0].control/down/engines[0]/implementation/g217507/ZN}
set second {numeric/engine/backend/clusters[1].control/down/engines[0]/implementation/g217507/ZN}
check raw_indexed_name_and_canonical_list $first [list $first] 1
check canonical_list_and_raw_indexed_name [list $first] $first 1
check same_names_different_order [list $first $second] [list $second $first] 1
check wrong_index $first $second 0
check extra_duplicate [list $first $first] [list $first] 0
check extra_driver [list $first $second] [list $first] 0
check both_empty {} {} 1
check missing_name {} [list $first] 0
if {$failures} {puts "FAILED $failures/$count";exit 1}
puts "NAME_LIST_TESTS_PASS cases=$count"
