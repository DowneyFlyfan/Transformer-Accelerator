`timescale 1ns/1ps

// Both formats use the same registered 512-bit-per-lane fabric write stage.
// The owner selects the format when it submits a packed weight descriptor.
module tri_oracle_controlled_weight_transport (
  input logic clk, rst_n, cfg_valid, cfg_paired, cfg_indexed,
  output logic cfg_ready,
  input logic [63:0] cfg_base, cfg_up_base,
  input logic [15:0] cfg_first_row,
  input logic [16:0] cfg_dense_rows,
  input logic [9:0] cfg_feature_words,
  input logic [7:0] cfg_count, cfg_tile_start,
  input logic [159:0] cfg_keep,
  input logic [127:0] cfg_active_words,
  output logic [1:0] req_valid,
  input logic [1:0] req_ready,
  output logic [1:0][63:0] req_address,
  output logic [1:0][5:0] req_length,
  input logic [1:0] rsp_valid, rsp_last, rsp_error,
  input logic [1:0][511:0] rsp_data,
  output logic [1:0] rsp_ready,
  output logic [1:0] load_valid,
  output logic [1:0][4:0] load_core,
  output logic [1:0][9:0] load_addr,
  output logic [1:0][31:0] load_row_enable,
  output logic [1:0][511:0] load_payload,
  output logic done_valid, done_error,
  input logic done_ready
);
  typedef enum logic [1:0] {Idle, Raw, Indexed, Invalid} state_t;
  state_t state;
  logic indexed_supported, accept_cfg;
  logic raw_ready, raw_done, raw_error, indexed_done;
  logic [1:0] raw_req, raw_rsp_ready, raw_load;
  logic [1:0] stream_ready, stream_done, stream_error, stream_req, stream_rsp_ready;
  logic [1:0] stream_offered, stream_granted;
  logic [1:0][4:0] raw_core, stream_core;
  logic [1:0][9:0] raw_addr, stream_addr;
  logic [1:0][31:0] raw_rows, stream_rows;
  logic [1:0][63:0] raw_req_address, stream_req_address;
  logic [1:0][5:0] raw_req_length, stream_req_length;
  logic [1:0][511:0] stream_payload;

  assign indexed_supported = cfg_paired
      ? (cfg_feature_words == 256 && cfg_dense_rows == 5632)
      : (cfg_feature_words == 704 && cfg_dense_rows == 2048);
  assign cfg_ready = rst_n && state == Idle &&
      (cfg_indexed ? (!indexed_supported || (&stream_ready)) : raw_ready);
  assign accept_cfg = cfg_valid && cfg_ready;

  assign indexed_done = state == Indexed && (&stream_done);
  assign done_valid = state == Invalid || indexed_done || (state == Raw && raw_done);
  assign done_error = state == Invalid || (indexed_done && (|stream_error)) ||
      (state == Raw && raw_done && raw_error);
  assign req_valid = state == Raw ? raw_req : state == Indexed ? stream_req : 2'b00;
  assign rsp_ready = state == Raw ? raw_rsp_ready : state == Indexed ? stream_rsp_ready : 2'b00;
  assign load_valid = state == Raw ? raw_load :
      state == Indexed ? (stream_offered & stream_granted) : 2'b00;
  assign req_address = state == Indexed ? stream_req_address : raw_req_address;
  assign req_length = state == Indexed ? stream_req_length : raw_req_length;
  assign load_core = state == Indexed ? stream_core : raw_core;
  assign load_addr = state == Indexed ? stream_addr : raw_addr;
  assign load_row_enable = state == Indexed ? stream_rows : raw_rows;
  assign load_payload = state == Indexed ? stream_payload : rsp_data;

  tri_oracle_parallel_weight_loader raw_loader (
    .clk,.rst_n,.cfg_valid(accept_cfg && !cfg_indexed),.cfg_ready(raw_ready),
    .cfg_paired,.cfg_base,.cfg_up_base,.cfg_first_row,.cfg_dense_rows,.cfg_feature_words,
    .cfg_count,.cfg_tile_start,.cfg_keep,.cfg_active_words,
    .req_valid(raw_req),.req_ready(req_ready & {2{state == Raw}}),
    .req_address(raw_req_address),.req_length(raw_req_length),
    .rsp_valid(rsp_valid & {2{state == Raw}}),.rsp_last,.rsp_error,.rsp_ready(raw_rsp_ready),
    .load_valid(raw_load),.load_core(raw_core),.load_addr(raw_addr),.load_row_enable(raw_rows),
    .done_valid(raw_done),.done_ready(state == Raw && done_ready),.done_error(raw_error)
  );

  for (genvar lane=0; lane<2; lane++) begin : indexed_lane
    tri_oracle_early_pair_lane #(.LANE(1'(lane))) loader (
      .clk,.rst_n,.cfg_valid(accept_cfg && cfg_indexed && indexed_supported),.cfg_ready(stream_ready[lane]),
      .cfg_index_base(cfg_base),.cfg_first_row,.cfg_count,.cfg_tile_start,
      .cfg_down(!cfg_paired),.cfg_keep,.cfg_active_words,
      .req_valid(stream_req[lane]),.req_ready(state == Indexed && req_ready[lane]),
      .req_address(stream_req_address[lane]),.req_length(stream_req_length[lane]),
      .rsp_valid(state == Indexed && rsp_valid[lane]),.rsp_last(rsp_last[lane]),.rsp_error(rsp_error[lane]),
      .rsp_data(rsp_data[lane]),.rsp_ready(stream_rsp_ready[lane]),
      .load_valid(stream_offered[lane]),.load_ready(state == Indexed && stream_granted[lane]),
      .load_core(stream_core[lane]),.load_addr(stream_addr[lane]),
      .load_row_enable(stream_rows[lane]),.load_data(stream_payload[lane]),
      .done_valid(stream_done[lane]),.done_error(stream_error[lane]),
      .done_ready(indexed_done && done_ready)
    );
  end

  weight_stream_write_arbiter arbiter (
    .clk,.rst_n,.offered(stream_offered),.core(stream_core),.memory_ready(2'b11),.granted(stream_granted)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) state <= Idle;
    else if (accept_cfg) state <= cfg_indexed ? (indexed_supported ? Indexed : Invalid) : Raw;
    else if (done_valid && done_ready) state <= Idle;
  end
endmodule
