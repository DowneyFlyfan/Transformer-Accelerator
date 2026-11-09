# Validate the vendor routing header and standard-cell abstracts in Innovus.
set_multi_cpu_usage -local_cpu 18
read_physical -lef [list \
    .cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
    .cache/physical/library/tcbn28hpcplusbwp12t40p140.lef]
puts "TRI_ORACLE_PHYSICAL_LIBRARY_READ_FINISHED"
exit
