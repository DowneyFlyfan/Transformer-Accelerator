# Read-only observation of indexed native pin-list representation.
set_multi_cpu_usage -local_cpu 8
read_db $::env(TRI264_INPUT)
unflatten_ilm
set input [open $::env(TRI264_TREES) r]
gets $input header
set output [open $::env(TRI264_OUT)/name_observations.tsv w]
puts $output "driver\tactual_driver_list\texpected_driver_list\traw_equal\tcanonical_equal\tnet_count\tnet_name_equal\tdriver_ports\tload_ports\tconstant\tpower\tground"
set count 0
while {[gets $input line]>=0} {
    lassign [split $line "\t"] tree controller driver master loads buffers root_id
    set pin [get_db pins $driver]
    if {[llength $pin]!=1 || [get_db $pin .name] ne $driver} {error TRI264_WRONG_PIN}
    set net_name [get_db $pin .net.name]
    set net [get_db nets $net_name]
    set actual [get_db $net .driver_pins.name]
    set expected [list $driver]
    puts $output [join [list $driver $actual $expected [expr {$actual eq $expected}] [expr {[lsort $actual] eq [lsort $expected]}] [llength $net] [expr {[get_db $net .name] eq $net_name}] [get_db $net .driver_ports.name] [get_db $net .load_ports.name] [get_db $net .constant] [get_db $net .is_power] [get_db $net .is_ground]] "\t"]
    incr count
}
close $input
close $output
if {$count!=114} {error TRI264_INCOMPLETE_PLAN}
puts TRI_ORACLE_CONTROLLER264_INDEXED_NAMES_OBSERVED
exit
