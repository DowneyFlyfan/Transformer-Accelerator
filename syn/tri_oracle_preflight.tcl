# Library-bound elaboration only. This is not mapped synthesis.
set_db max_cpus 18
if {![info exists ::env(TRI_ORACLE_LIBS)] || $::env(TRI_ORACLE_LIBS) eq ""} {
    error "TRI_ORACLE_LIBS must be a Tcl list of real standard-cell Liberty files visible inside the container."
}
foreach lib $::env(TRI_ORACLE_LIBS) {
    if {![file readable $lib]} {error "Unreadable standard-cell library: $lib"}
}
read_libs $::env(TRI_ORACLE_LIBS)
set top $::env(TRI_ORACLE_TOP)
set outdir .cache/physical/preflight/$top
file mkdir $outdir
if {$top in {tri_oracle_memory_compute tri_oracle_compute_cluster tri_oracle_compute_fabric}} {
    read_hdl -sv verilog/tri_oracle_word_bank.sv
    read_hdl -sv verilog/tri_oracle_pe_array.sv
}
if {$top in {tri_oracle_compute_cluster tri_oracle_compute_fabric}} {
    read_hdl -sv verilog/tri_oracle_memory_compute.sv
}
if {$top eq "tri_oracle_compute_fabric"} {
    read_hdl -sv verilog/tri_oracle_compute_cluster.sv
}
read_hdl -sv verilog/${top}.sv
elaborate $top
check_design -unresolved
write_hdl > ${outdir}/elaborated.v
puts "TRI_ORACLE_ELABORATION_PASS $top"
exit
