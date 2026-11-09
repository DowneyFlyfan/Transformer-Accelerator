# =============================================================
# DC Synthesis Script for Softmax Module
# Target: FreePDK45 (NangateOpenCellLibrary)
# =============================================================

# ---- Library Setup ----
set LIB_DIR "~/Documents/pdks/tsmc65_OA"

set search_path [list $LIB_DIR ../verilog/reference .]
set target_library [list stdcells.db]
set link_library [list * stdcells.db]

# ---- Design Parameters ----
set TOP_MODULE softmax
set CLK_NAME clk
set OUT_CAP 0.01
set CLK_UNCERTAINTY_RATIO 0.05
set IO_DELAY_RATIO 0.1
set CLK_PERIOD 0.5 ;# 2 GHz target

# ---- Read RTL ----
analyze -format sverilog {
    ../verilog/reference/int_multiplier.sv
    ../verilog/reference/adder_tree.sv
    softmax_syn.sv
}

elaborate $TOP_MODULE
current_design $TOP_MODULE

link

# ---- Check Design ----
check_design

# ---- Clock Constraints ----
create_clock -name $CLK_NAME -period $CLK_PERIOD [get_ports $CLK_NAME]
set_clock_uncertainty [expr $CLK_PERIOD * $CLK_UNCERTAINTY_RATIO] [get_clocks $CLK_NAME]
set_clock_transition [expr $CLK_PERIOD * $CLK_UNCERTAINTY_RATIO] [get_clocks $CLK_NAME]

# ---- IO Constraints ----
set_input_delay [expr $CLK_PERIOD * $IO_DELAY_RATIO] -clock $CLK_NAME [remove_from_collection [all_inputs] [get_ports $CLK_NAME]]
set_output_delay [expr $CLK_PERIOD * $IO_DELAY_RATIO] -clock $CLK_NAME [all_outputs]

# NOTE: CLKBUF_X1 is a buffer in freepdk-45nm
set_driving_cell -lib_cell CLKBUF_X1 [remove_from_collection [all_inputs] [get_ports $CLK_NAME]]
set_load $OUT_CAP [all_outputs]

# ---- Reset ----
set_false_path -from [get_ports rst_n]

# ---- Compile ----
compile_ultra -no_autoungroup -retime
compile_ultra -no_autoungroup -retime -incremental

# ---- Reports ----
set RPT_DIR "./reports"
file mkdir $RPT_DIR

report_timing -nworst 10 > ${RPT_DIR}/timing.rpt
report_area -hierarchy > ${RPT_DIR}/area.rpt
report_power -analysis_effort high > ${RPT_DIR}/power.rpt
# Quality of Results (QoR)
report_qor > ${RPT_DIR}/qor.rpt
report_design > ${RPT_DIR}/design.rpt

# ---- Export Netlist ----
set OUT_DIR "./output"
file mkdir $OUT_DIR

change_names -rules verilog -hierarchy
write_file -format verilog -hierarchy -output ${OUT_DIR}/softmax_netlist.v
write_sdc ${OUT_DIR}/softmax.sdc
write_file -format ddc -hierarchy -output ${OUT_DIR}/softmax.ddc

puts "============================================"
puts " Synthesis complete for: $TOP_MODULE"
puts " Clock period: $CLK_PERIOD ns"
puts "============================================"

exit
