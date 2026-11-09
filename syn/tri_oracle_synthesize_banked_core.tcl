# Keep bank hierarchy; bound remote worker count instead of automatic fanout.
# Documented Genus25.10 root attributes; container caps all workers at18 CPUs.
set_db auto_ungroup none
set_db auto_super_thread false
set_db super_thread_servers {localhost localhost}
set_db max_cpus_per_server 8
source syn/tri_oracle_synthesize.tcl
