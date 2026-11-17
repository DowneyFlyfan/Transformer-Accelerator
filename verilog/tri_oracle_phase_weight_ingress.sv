`timescale 1ns/1ps
// Adapt the command layer's scalar and packed weight beats to the two
// registered lanes. A beat stays resident until the destination banks write it.
module tri_oracle_phase_weight_ingress (
  input logic clk, memory_clk, rst_n,
  input logic [4:0][3:0] read_cores,
  input logic [4:0] read_address,
  input logic scalar_valid,
  input logic [4:0] scalar_core,
  input logic [9:0] scalar_address,
  input logic [31:0] scalar_rows,
  input logic [63:0] scalar_data,
  input logic [1:0] wide_valid,
  input logic [1:0][4:0] wide_core,
  input logic [1:0][9:0] wide_address,
  input logic [1:0][1:0] wide_group,
  input logic [1:0][31:0] wide_rows,
  input logic [1:0][511:0] wide_data,
  output logic error,
  output logic [4:0][4:0] phase_address,
  output logic [4:0][63:0] phase_ce_n,
  output logic [4:0] phase_we_n,
  output logic [4:0][31:0] phase_rows,
  output logic [4:0][2047:0] phase_data
);
  logic [1:0] malformed_wide, load_valid, load_ready, pending, retired;
  logic malformed;
  logic [1:0][4:0] staged_core;
  logic [1:0][9:0] staged_address;
  logic [1:0][31:0] staged_rows;
  logic [1:0][1023:0] staged_data;

  for (genvar lane = 0; lane < 2; lane++) begin : check_wide
    assign malformed_wide[lane] = wide_valid[lane] &&
        (wide_core[lane] >= 20 || wide_address[lane] >= 32
         || (|(wide_rows[lane] & ~(32'hff << (8*wide_group[lane])))));
  end
  assign malformed = (|malformed_wide)
      || ((&wide_valid) && wide_core[0][4:2] == wide_core[1][4:2])
      || (scalar_valid && ((|wide_valid) || scalar_core >= 20 || scalar_address >= 32));
  assign load_valid[0] = !malformed && ((scalar_valid && (|scalar_rows))
                                        || (wide_valid[0] && (|wide_rows[0])));
  assign load_valid[1] = !malformed && wide_valid[1] && (|wide_rows[1]);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) error <= 0;
    else error <= malformed || (|(load_valid & ~load_ready));
  end

  tri_oracle_weight_write_buffer buffer (
    .clk, .rst_n, .load_valid, .load_ready, .pending,
    .load_core({wide_core[1], scalar_valid ? scalar_core : wide_core[0]}),
    .load_addr({wide_address[1], scalar_valid ? scalar_address : wide_address[0]}),
    .load_row_enable({wide_rows[1], scalar_valid ? scalar_rows : wide_rows[0]}),
    .load_payload({{2{wide_data[1]}}, scalar_valid ? {16{scalar_data}} : {2{wide_data[0]}}}),
    .write_ready(retired), .write_valid(),
    .write_core(staged_core), .write_addr(staged_address),
    .write_row_enable(staged_rows), .write_payload(staged_data),
    .loader_done_valid(1'b0), .loader_done_error(1'b0), .loader_done_ready(),
    .done_ready(1'b0), .done_valid(), .done_error()
  );
  tri_oracle_weight_phase_fabric weight_port (
    .memory_clk, .core_clk(clk), .rst_n, .read_cores, .read_address,
    .write_pending(pending), .write_allowed(2'b11), .write_core(staged_core),
    .write_address(staged_address), .write_rows(staged_rows), .write_payload(staged_data),
    .write_retired(retired), .memory_address(phase_address), .memory_ce_n(phase_ce_n),
    .memory_we_n(phase_we_n), .memory_rows(phase_rows), .memory_data(phase_data)
  );
endmodule
