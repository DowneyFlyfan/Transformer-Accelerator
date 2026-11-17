`timescale 1ns/1ps
// The two loader lanes remain held until their destination SRAM commits.
// Each cluster owns its address and can write independently in its write phase.
module tri_oracle_weight_phase_fabric (
  input logic memory_clk, core_clk, rst_n,
  input logic [4:0][3:0] read_cores,
  input logic [4:0] read_address,
  input logic [1:0] write_pending, write_allowed,
  input logic [1:0][4:0] write_core,
  input logic [1:0][9:0] write_address,
  input logic [1:0][31:0] write_rows,
  input logic [1:0][1023:0] write_payload,
  output logic [1:0] write_retired,
  output logic [4:0][4:0] memory_address,
  output logic [4:0][63:0] memory_ce_n,
  output logic [4:0] memory_we_n,
  output logic [4:0][31:0] memory_rows,
  output logic [4:0][2047:0] memory_data
);
  logic [1:0][4:0] retired_by_lane;
  for (genvar cluster = 0; cluster < 5; cluster++) begin : phase_cluster
    logic [1:0] retired;
    tri_oracle_cluster_weight_phase #(.CLUSTER_ID(3'(cluster))) port_control (
      .memory_clk, .core_clk, .rst_n, .read_cores(read_cores[cluster]), .read_address,
      .write_pending, .write_allowed, .write_core, .write_address, .write_rows, .write_payload,
      .write_retired(retired), .memory_address(memory_address[cluster]), .memory_ce_n(memory_ce_n[cluster]),
      .memory_we_n(memory_we_n[cluster]), .memory_rows(memory_rows[cluster]), .memory_data(memory_data[cluster])
    );
    assign retired_by_lane[0][cluster] = retired[0];
    assign retired_by_lane[1][cluster] = retired[1];
  end
  assign write_retired = {|retired_by_lane[1], |retired_by_lane[0]};
endmodule
