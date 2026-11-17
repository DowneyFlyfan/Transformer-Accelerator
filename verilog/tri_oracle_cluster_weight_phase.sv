`timescale 1ns/1ps
module tri_oracle_cluster_weight_phase #(
  parameter logic [2:0] CLUSTER_ID = 0
) (
  input logic memory_clk, core_clk, rst_n,
  input logic [3:0] read_cores,
  input logic [4:0] read_address,
  input logic [1:0] write_pending, write_allowed,
  input logic [1:0][4:0] write_core,
  input logic [1:0][9:0] write_address,
  input logic [1:0][31:0] write_rows,
  input logic [1:0][1023:0] write_payload,
  output logic [1:0] write_retired,
  output logic [4:0] memory_address,
  output logic [63:0] memory_ce_n,
  output logic memory_we_n,
  output logic [31:0] memory_rows,
  output logic [2047:0] memory_data
);
  localparam int BanksPerCore = 16;
  logic [1:0] local_pending, selected, active_lane;
  logic [63:0] read_banks, write_banks;
  logic selected_lane;

  for (genvar lane = 0; lane < 2; lane++) begin : local_write
    assign local_pending[lane] = write_pending[lane]
        && write_core[lane][4:2] == CLUSTER_ID
        && write_address[lane][9:5] == 0
        && (|write_rows[lane]);
  end

  weight_stream_write_arbiter select_write (
    .clk(core_clk), .rst_n, .offered(local_pending), .core(write_core),
    .memory_ready(local_pending & write_allowed), .granted(selected)
  );
  assign selected_lane = selected[1];
  for (genvar core = 0; core < 4; core++) begin : bank_core
    assign read_banks[core*BanksPerCore+:BanksPerCore] = {BanksPerCore{read_cores[core]}};
    for (genvar bank = 0; bank < BanksPerCore; bank++) begin : bank_row
      assign write_banks[core*BanksPerCore+bank] =
          write_core[selected_lane][1:0] == 2'(core)
          && (|write_rows[selected_lane][2*bank+:2]);
    end
  end

  tri_oracle_weight_phase_port #(.BANKS(4*BanksPerCore)) port_control (
    .memory_clk, .core_clk, .rst_n, .read_valid(|read_cores), .read_address, .read_banks,
    .write_select(selected), .write_address(write_address[selected_lane][4:0]), .write_banks,
    .active_write_lane(active_lane), .write_retired,
    .memory_address, .memory_ce_n, .memory_we_n
  );

  assign memory_rows = write_rows[active_lane[1]];
  assign memory_data = {2{write_payload[active_lane[1]]}};
endmodule
