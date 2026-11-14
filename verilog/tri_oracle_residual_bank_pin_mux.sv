module tri_oracle_residual_bank_pin_mux (
    input logic rst_n, lease,
    input logic native_ce_n, native_we_n,
    input logic [8:0] native_addr,
    input logic [63:0] native_data,
    input logic residual_ce_n, residual_we_n,
    input logic [8:0] residual_addr,
    input logic [63:0] residual_data,
    output logic memory_ce_n, memory_we_n,
    output logic [8:0] memory_addr,
    output logic [63:0] memory_data
);
    assign memory_ce_n = lease ? (!rst_n || residual_ce_n) : native_ce_n;
    assign memory_we_n = lease ? residual_we_n : native_we_n;
    assign memory_addr = lease ? residual_addr : native_addr;
    assign memory_data = lease ? residual_data : native_data;
endmodule
