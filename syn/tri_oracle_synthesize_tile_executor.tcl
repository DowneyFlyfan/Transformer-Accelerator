# Load the verified transfer engine before the common flow elaborates its user.
read_hdl -sv verilog/tri_oracle_sparse_weight_dma.sv
source syn/tri_oracle_synthesize.tcl
