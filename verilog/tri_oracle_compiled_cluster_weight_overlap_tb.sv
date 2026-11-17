`timescale 1ns/1ps
module tri_oracle_compiled_cluster_weight_overlap_tb;
  localparam logic [63:0] INDEX = 64'h7fffff000, PAYLOAD = 64'hf00000000;
  localparam int ReadsPerTile = 512;
  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic serial, ignore_reservation, single_port;
  int hold_issue_cycles;
  initial begin
    int serial_flag, bypass_flag, single_flag;
    serial = $value$plusargs("SERIAL=%d", serial_flag) && serial_flag != 0;
    ignore_reservation = $value$plusargs("IGNORE_RESERVATION=%d", bypass_flag) && bypass_flag != 0;
    single_port = $value$plusargs("SINGLE_PORT=%d", single_flag) && single_flag != 0;
    if (!$value$plusargs("HOLD_ISSUE=%d", hold_issue_cycles)) hold_issue_cycles = 0;
  end

  logic transport_valid = 0, transport_ready, transport_done, transport_done_ready, transport_error;
  logic stage_done, stage_error, stage_done_ready = 0;
  logic [1:0] req_valid, req_ready, rsp_valid, rsp_ready, rsp_last;
  logic [1:0][63:0] req_address;
  logic [1:0][5:0] req_length;
  logic [1:0][511:0] rsp_data;
  logic [1:0] load_valid, load_ready, staged_pending, staged_valid, write_ready;
  logic [1:0][4:0] load_core, staged_core;
  logic [1:0][9:0] load_addr, staged_addr;
  logic [1:0][31:0] load_rows, staged_rows;
  logic [1:0][1023:0] load_payload, staged_payload;
  byte unsigned indices[1536*64], payload[1536*8192];
  logic [2047:0] initial_weights[128];
  logic [63:0] activations[4096];
  logic [255:0] masks[16];
  logic [1023:0] expected[1024];

  logic in_valid = 0, in_ready, append_tile = 0, allow_issue = 0;
  logic cmd_valid, cmd_ready, cmd_accumulate, cmd_accepted;
  logic [4:0] cmd_weight, cmd_mask;
  logic [9:0] cmd_activation;
  logic [3:0] cmd_output;
  logic projection_done, projection_error, projection_done_ready = 0, projection_rst_n;
  logic out_valid, out_last, out_ready;
  logic [31:0] out_tag;
  logic [3:0] out_token;
  logic [5119:0] out_data;
  logic [4:0] backend_out_ready;

  logic init_valid = 0, reload = 0;
  logic [1:0] init_core = '0, init_kind = '0;
  logic [9:0] init_addr = '0;
  logic [2047:0] init_data = '0;
  logic cluster_load_valid, cluster_load_error, cluster_cmd_ready, cluster_out_valid;
  logic [1:0] cluster_load_core, cluster_load_kind;
  logic [9:0] cluster_load_addr;
  logic [2047:0] cluster_load_data;
  logic [31:0] cluster_load_rows;
  logic [1023:0] cluster_out_data;
  logic [3:0] cluster_out_slot;
  bit [31:0] unread_words;
  int cycle = 0, start_cycle, reads = 0, retired = 0, final_outputs = 0, staged_writes = 0;
  int concurrent_writes = 0, blocked_cycles = 0, output_stall_cycles = 0, request_count[2];
  always @(negedge clk) cycle <= cycle + 1;

  tri_oracle_backpressured_weight_transport transport (
    .clk, .rst_n, .cfg_valid(transport_valid), .cfg_ready(transport_ready),
    .cfg_paired(1'b0), .cfg_indexed(1'b1), .cfg_base(INDEX), .cfg_up_base(64'd0),
    .cfg_first_row(16'd0), .cfg_dense_rows(17'd2048), .cfg_feature_words(10'd704),
    .cfg_count(8'd96), .cfg_tile_start(8'd32), .cfg_keep(160'hffff_ffff << 64),
    .cfg_active_words({128{1'b1}}),
    .req_valid, .req_ready, .req_address, .req_length, .rsp_valid, .rsp_last, .rsp_error(2'b00),
    .rsp_ready, .rsp_data, .load_valid, .load_ready, .load_core, .load_addr,
    .load_row_enable(load_rows), .load_payload, .done_valid(transport_done),
    .done_error(transport_error), .done_ready(transport_done_ready)
  );

  tri_oracle_weight_write_buffer buffer (
    .clk, .rst_n, .load_valid, .load_ready, .pending(staged_pending), .load_core, .load_addr,
    .load_row_enable(load_rows), .load_payload, .write_ready, .write_valid(staged_valid),
    .write_core(staged_core), .write_addr(staged_addr), .write_row_enable(staged_rows),
    .write_payload(staged_payload), .loader_done_valid(transport_done),
    .loader_done_error(transport_error), .loader_done_ready(transport_done_ready),
    .done_valid(stage_done), .done_error(stage_error), .done_ready(stage_done_ready)
  );

  for (genvar lane = 0; lane < 2; lane++) begin : gen_lane
    logic reserved_address_safe, request_active, response_held;
    logic [63:0] address;
    logic [5:0] length, beat;

    tri_oracle_projection_weight_reuse guard (
      .clk, .rst_n, .discard(!projection_rst_n), .reserve(in_valid && in_ready),
      .reserve_base(5'd0), .reserve_strips(6'd32), .last_read(cmd_accepted && cmd_output == 15),
      .read_word(cmd_weight), .write_word(staged_addr[lane][4:0]),
      .write_allowed(reserved_address_safe)
    );
    assign write_ready[lane] = (ignore_reservation || reserved_address_safe) && !init_valid;
    assign req_ready[lane] = !request_active && cycle%5 != lane;
    assign rsp_valid[lane] = request_active && (response_held || cycle%4 != lane);
    assign rsp_last[lane] = beat + 6'd1 == length;

    always @(request_active or address or beat) begin
      int offset;
      rsp_data[lane] = '0;
      if (request_active && address < PAYLOAD) begin
        offset = int'(address - INDEX);
        for (int byte_id = 0; byte_id < 64; byte_id++)
          rsp_data[lane][8*byte_id+:8] = indices[offset+byte_id];
      end else if (request_active) begin
        offset = int'(address - PAYLOAD) + 64*int'(beat);
        for (int byte_id = 0; byte_id < 64; byte_id++)
          rsp_data[lane][8*byte_id+:8] = payload[offset+byte_id];
      end
    end

    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        request_active <= 0;
        response_held <= 0;
        address <= 0;
        length <= 0;
        beat <= 0;
        request_count[lane] <= 0;
      end else begin
        response_held <= rsp_valid[lane] && !rsp_ready[lane];
        if (req_valid[lane] && req_ready[lane]) begin
          if (req_address[lane] < INDEX || req_address[lane][5:0] != 0 || req_length[lane] == 0)
            $fatal(1, "CLUSTER_WEIGHT_BAD_REQUEST lane=%0d", lane);
          request_count[lane] <= request_count[lane] + 1;
          request_active <= 1;
          address <= req_address[lane];
          length <= req_length[lane];
          beat <= 0;
        end else if (rsp_valid[lane] && rsp_ready[lane]) begin
          if (rsp_last[lane]) request_active <= 0;
          else beat <= beat + 6'd1;
        end
      end
    end
  end

  assign cluster_load_valid = init_valid || (|staged_valid);
  assign cluster_load_core = init_valid ? init_core :
      staged_valid[0] ? staged_core[0][1:0] : staged_core[1][1:0];
  assign cluster_load_addr = init_valid ? init_addr :
      staged_valid[0] ? staged_addr[0] : staged_addr[1];
  assign cluster_load_kind = init_valid ? init_kind : 2'd0;
  assign cluster_load_rows = init_valid ? '1 : staged_valid[0] ? staged_rows[0] : staged_rows[1];
  assign cluster_load_data = init_valid ? init_data :
      {2{staged_valid[0] ? staged_payload[0] : staged_payload[1]}};
  assign cmd_ready = allow_issue && cluster_cmd_ready;
  assign cmd_accepted = cmd_valid && cmd_ready;
  assign out_ready = cycle%19 >= 4;

  tri_oracle_batched_projection356 projection (
    .clk, .rst_n, .in_valid, .in_ready, .in_tag(32'd201), .in_tokens(5'd16),
    .in_weight_base(5'd0), .in_mask_base(5'd0), .in_strips(6'd32),
    .in_activation_base(append_tile ? 10'd512 : 10'd0), .in_activation_stride(11'd32),
    .in_accumulate(append_tile), .in_publish(append_tile),
    .out_valid, .out_ready, .out_tag, .out_token, .out_last, .out_data,
    .done_valid(projection_done), .done_ready(projection_done_ready),
    .done_error(projection_error), .done_tag(), .backend_rst_n(projection_rst_n),
    .backend_cmd_valid(cmd_valid), .backend_cmd_ready(cmd_ready), .backend_cmd_weight(cmd_weight),
    .backend_cmd_mask(cmd_mask), .backend_cmd_activation(cmd_activation),
    .backend_cmd_output(cmd_output), .backend_cmd_accumulate(cmd_accumulate),
    .backend_out_valid({5{cluster_out_valid}}), .backend_out_ready,
    .backend_out_output({5{cluster_out_slot}}), .backend_out_data({4096'b0, cluster_out_data})
  );

  tri_oracle_sram_compute_cluster cluster (
    .clk, .rst_n(projection_rst_n), .load_valid(cluster_load_valid), .load_core(cluster_load_core),
    .load_kind(cluster_load_kind), .load_addr(cluster_load_addr), .load_data(cluster_load_data),
    .load_row_enable(cluster_load_rows), .load_error(cluster_load_error),
    .cmd_valid(allow_issue && cmd_valid), .cmd_ready(cluster_cmd_ready), .cmd_weight, .cmd_mask,
    .cmd_activation, .cmd_output, .cmd_accumulate, .cmd_reduce(2'd0),
    .out_valid(cluster_out_valid), .out_ready(backend_out_ready[0]),
    .out_output(cluster_out_slot), .out_data(cluster_out_data),
    .merge_sign_data('0), .merge_sign_control('0), .merge_sign_counts(),
    .merge_table_request('0), .merge_table_word(),
    .token_size_bank_command('0), .token_size_bank_result(),
    .softmax_request('0), .softmax_response(), .activation_reloaded(reload), .core_score_select('0),
    .merge_range_command('0), .merge_range_result(),
    .global_merge_word('0), .global_sign_counts('0),
    .strip_rst_n(rst_n), .strip_request('0), .strip_response(), .head_request('0), .head_response()
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) unread_words <= '0;
    else if (in_valid && in_ready) unread_words <= '1;
    else if (cmd_accepted && cmd_output == 15) unread_words[cmd_weight] <= 0;
  end

  always @(posedge clk) if (rst_n) begin
    if (cluster_load_error || (| (load_valid & ~load_ready)) || (&staged_valid) ||
        (stage_done && ((|staged_pending) || stage_error)) || (projection_done && projection_error))
      $fatal(1, "CLUSTER_WEIGHT_PROTOCOL");
    if (| (staged_pending & ~write_ready)) blocked_cycles++;
    if (cmd_accepted) begin
      reads++;
      if (|staged_valid) concurrent_writes++;
    end
    for (int lane = 0; lane < 2; lane++) begin
      if (staged_valid[lane]) begin
        if (staged_core[lane] < 8 || staged_core[lane] > 11 || staged_addr[lane] >= 32)
          $fatal(1, "CLUSTER_WEIGHT_WRITE_TARGET lane=%0d", lane);
        if (unread_words[staged_addr[lane][4:0]])
          $fatal(1, "CLUSTER_WEIGHT_PREMATURE_OVERWRITE lane=%0d word=%0d",
                 lane, staged_addr[lane]);
        staged_writes++;
      end
    end
    if (cluster_out_valid && backend_out_ready[0]) begin
      if (retired >= 2*ReadsPerTile || cluster_out_slot !== 4'(retired%16) ||
          cluster_out_data !== expected[retired]) begin
        for (int row = 0; row < 32 && retired < 2*ReadsPerTile; row++)
          if (cluster_out_data[32*row+:32] !== expected[retired][32*row+:32])
            $fatal(1, "CLUSTER_WEIGHT_ACCUMULATOR result=%0d row=%0d got=%h expected=%h",
                   retired, row, cluster_out_data[32*row+:32], expected[retired][32*row+:32]);
        $fatal(1, "CLUSTER_WEIGHT_RESULT_ORDER result=%0d slot=%0d", retired, cluster_out_slot);
      end
      retired++;
    end
    if (out_valid) begin
      if (final_outputs >= 16 || out_tag !== 201 || out_token !== 4'(final_outputs) ||
          out_last !== (final_outputs == 15) || out_data[1023:0] !== expected[1008+final_outputs])
        $fatal(1, "CLUSTER_WEIGHT_FINAL_OUTPUT token=%0d", final_outputs);
      if (out_ready) final_outputs++;
      else output_stall_cycles++;
    end
  end

  task automatic initialize_word(input int kind, input int core, input int address,
                                 input logic [2047:0] data);
    @(negedge clk);
    init_valid = 1;
    init_kind = 2'(kind);
    init_core = 2'(core);
    init_addr = 10'(address);
    init_data = data;
  endtask

  initial begin
    int file;
    $readmemh("initial_weights.hex", initial_weights);
    $readmemh("activations.hex", activations);
    $readmemh("masks.hex", masks);
    $readmemh("accumulators.hex", expected);
    file = $fopen("down_index.bin", "rb");
    if (!file || $fread(indices, file) != 1536*64) $fatal(1, "CLUSTER_WEIGHT_INDEX_FIXTURE");
    $fclose(file);
    file = $fopen("down_payload.bin", "rb");
    if (!file || $fread(payload, file) != 1536*8192) $fatal(1, "CLUSTER_WEIGHT_PAYLOAD_FIXTURE");
    $fclose(file);
    repeat (2) @(negedge clk);
    rst_n = 1;
    for (int core = 0; core < 4; core++) begin
      for (int word = 0; word < 32; word++)
        initialize_word(0, core, word, initial_weights[32*core+word]);
      for (int tile = 0; tile < 2; tile++)
        for (int token = 0; token < 16; token++)
          for (int word = 0; word < 32; word++)
            initialize_word(1, core, tile*512+token*32+word,
                            2048'(activations[((tile*32+word)*16+token)*4+core]));
      for (int token = 0; token < 16; token++)
        initialize_word(2, core, token, 2048'(masks[token]));
    end
    @(negedge clk);
    init_valid = 0;
    reload = 1;
    @(negedge clk);
    reload = 0;
    if (!in_ready || !transport_ready) $fatal(1, "CLUSTER_WEIGHT_NOT_READY");
    in_valid = 1;
    transport_valid = !serial;
    start_cycle = cycle;
    @(negedge clk);
    in_valid = 0;
    transport_valid = 0;
    repeat (hold_issue_cycles) @(negedge clk);
    allow_issue = 1;
    wait (projection_done);
    @(negedge clk);
    if (serial) begin
      transport_valid = 1;
      @(negedge clk);
      transport_valid = 0;
    end
    wait (stage_done);
    @(negedge clk);
    if (stage_error || retired != ReadsPerTile) $fatal(1, "CLUSTER_WEIGHT_FIRST_TILE");
    stage_done_ready = 1;
    projection_done_ready = 1;
    @(negedge clk);
    stage_done_ready = 0;
    projection_done_ready = 0;
    append_tile = 1;
    in_valid = 1;
    if (!in_ready) $fatal(1, "CLUSTER_WEIGHT_APPEND_BUSY");
    @(negedge clk);
    in_valid = 0;
    wait (projection_done);
    @(negedge clk);
    if (reads != 1024 || retired != 1024 || final_outputs != 16 || staged_writes != 256 ||
        request_count[0] == 0 || request_count[1] == 0 || output_stall_cycles == 0 ||
        (serial ? blocked_cycles != 0 : blocked_cycles == 0) ||
        ((serial || single_port) ? concurrent_writes != 0 : concurrent_writes == 0))
      $fatal(1, "CLUSTER_WEIGHT_COUNTS reads=%0d retired=%0d finals=%0d writes=%0d",
             reads, retired, final_outputs, staged_writes);
    $display("COMPILED_CLUSTER_WEIGHT_PASS serial=%0d cycles=%0d reads=%0d",
             serial, cycle-start_cycle, reads);
    $display("COMPILED_CLUSTER_WEIGHT_MODE single_port=%0d hold_issue=%0d",
             single_port, hold_issue_cycles);
    $display("COMPILED_CLUSTER_WEIGHT_VALUES exact=%0d published=%0d",
             32*retired, 32*final_outputs);
    $display("COMPILED_CLUSTER_WEIGHT_TRAFFIC write_beats=%0d overlap=%0d blocked=%0d",
             staged_writes, concurrent_writes, blocked_cycles);
    $display("COMPILED_CLUSTER_WEIGHT_FLOW out_stall=%0d requests=%0d,%0d",
             output_stall_cycles, request_count[0], request_count[1]);
    $finish;
  end

  initial begin
    #100us;
    $fatal(1, "COMPILED_CLUSTER_WEIGHT_TIMEOUT reads=%0d retired=%0d writes=%0d",
           reads, retired, staged_writes);
  end
endmodule
