`timescale 1ns/1ps
module tri_oracle_packed_tensor_tb;
  localparam int FEATURE_WORDS = 704, FIRST_ROW = 1760, ROWS = 160;
  localparam int SCALAR_WORDS = ROWS * FEATURE_WORDS, PACKED_BEATS = SCALAR_WORDS / 8;
  localparam logic [63:0] ACT_BASE = 64'h10000000, WEIGHT_BASE = 64'h20000000;
  localparam logic [63:0] TILE_BASE = WEIGHT_BASE + 64'(FIRST_ROW * FEATURE_WORDS * 8);
  logic clk = 0, rst_n = 0, cfg_valid = 0, cfg_packed_weights;
  always #5 clk = ~clk;
  logic [2559:0] cfg_channels = '0;
  wire cfg_ready, out_valid, out_last, done_valid, done_error;
  logic out_ready = 0, done_ready = 0;
  wire [31:0] out_tag, done_tag;
  wire [3:0] out_token;
  wire [7:0] out_count;
  wire [2559:0] out_channels;
  wire [5119:0] out_data;

  wire req_valid, rsp_ready, wide_req_valid, wide_rsp_ready;
  wire [63:0] req_address, wide_req_address;
  wire [4:0] req_length;
  wire [5:0] wide_req_length;
  logic req_ready, rsp_valid, rsp_last, wide_req_ready, wide_rsp_valid, wide_rsp_last, wide_rsp_error;
  logic [63:0] rsp_data;
  logic [511:0] wide_rsp_data;

  tri_oracle_batched_tensor390 #(
    .AGGREGATOR_SIGN_BANK(1), .AGGREGATOR_MERGE_TABLE(1), .LOCAL_TOKEN_SIZES(1),
    .LOCAL_TOKEN_MERGE(1), .CORE_STRIP_PREDICTOR(1), .CORE_HEAD_PREDICTOR(1)
  ) dut (
    .clk,.rst_n,.cfg_valid,.cfg_ready,.cfg_packed_weights,.cfg_paired(1'b0),
    .cfg_tag(32'h70ad),.cfg_tokens(5'd1),.cfg_feature_words(10'(FEATURE_WORDS)),
    .cfg_dense_rows(17'd2048),.cfg_count(8'(ROWS)),.cfg_channels,.cfg_keep('1),
    .cfg_activation_base(ACT_BASE),.cfg_weight_base(WEIGHT_BASE),.cfg_up_weight_base('0),
    .cfg_activation_stride(32'(FEATURE_WORDS * 8)),.out_valid,.out_ready,.out_tag,.out_token,.out_last,
    .out_count,.out_channels,.out_data,.done_valid,.done_ready,.done_error,.done_tag,
    .req_valid,.req_ready,.req_address,.req_length,.rsp_valid,.rsp_ready,.rsp_last,.rsp_error(1'b0),.rsp_data,
    .wide_req_valid,.wide_req_ready,.wide_req_address,.wide_req_length,
    .wide_rsp_valid,.wide_rsp_ready,.wide_rsp_last,.wide_rsp_error,.wide_rsp_data,
    .merge_sign_data('0),.merge_sign_control('0),.merge_sign_counts(),
    .merge_table_request('0),.merge_table_word(),.softmax_request('0),.softmax_response(),
    .token_sizes_request('0),.token_sizes_response(),.merge_request('0),.merge_response(),
    .strip_request('0),.strip_response(),.head_request('0),.head_response()
  );

  logic [63:0] activation[FEATURE_WORDS], scalar_weights[SCALAR_WORDS];
  logic [511:0] packed_weights[PACKED_BEATS];
  logic [31:0] expected[ROWS];
  bit packed_mode, bad_channel, fault_mode, fault_sent = 0;
  bit wide_owned = 0, activation_owned = 0;
  int remaining = 0, word = 0, cycle = 0;
  int weight_bursts = 0, weight_beats = 0, activation_beats = 0;

  assign req_ready = remaining == 0 && cycle % 4 != 0;
  assign wide_req_ready = req_ready;
  assign rsp_valid = remaining != 0 && !wide_owned;
  assign wide_rsp_valid = remaining != 0 && wide_owned;
  assign rsp_last = remaining == 1;
  assign wide_rsp_last = rsp_last;
  assign wide_rsp_error = fault_mode && wide_rsp_valid && !fault_sent;
  assign rsp_data = rsp_valid ? (activation_owned ? activation[word] : scalar_weights[word]) : '0;
  assign wide_rsp_data = wide_rsp_valid ? packed_weights[word] : '0;

  always @(posedge clk) if (rst_n) begin
    cycle <= cycle + 1;
    if ((req_valid && wide_req_valid) || (remaining != 0 && (req_valid || wide_req_valid)))
      $fatal(1, "Tensor offered an overlapping memory transaction");
    if (req_valid && req_ready) begin
      if (req_address >= ACT_BASE && req_address < ACT_BASE + 64'(FEATURE_WORDS * 8)) begin
        word <= int'((req_address - ACT_BASE) >> 3);
        activation_owned <= 1;
        if (int'((req_address - ACT_BASE) >> 3) + int'(req_length) > FEATURE_WORDS)
          $fatal(1, "Activation burst exceeds the trained vector");
      end else begin
        if (packed_mode || req_address < TILE_BASE || req_address >= TILE_BASE + 64'(SCALAR_WORDS * 8) ||
            int'((req_address - TILE_BASE) >> 3) % FEATURE_WORDS + int'(req_length) > FEATURE_WORDS)
          $fatal(1, "Invalid scalar weight address %h", req_address);
        word <= int'((req_address - TILE_BASE) >> 3);
        activation_owned <= 0;
        weight_bursts <= weight_bursts + 1;
      end
      if (req_length == 0 || req_address[2:0] != 0) $fatal(1, "Malformed scalar burst");
      wide_owned <= 0;
      remaining <= int'(req_length);
    end else if (wide_req_valid && wide_req_ready) begin
      if (!packed_mode || wide_req_length == 0 || wide_req_address[5:0] != 0 ||
          wide_req_address < TILE_BASE || wide_req_address >= TILE_BASE + 64'(PACKED_BEATS * 64) ||
          int'((wide_req_address - TILE_BASE) >> 6) % FEATURE_WORDS + int'(wide_req_length) > FEATURE_WORDS)
        $fatal(1, "Invalid packed weight address %h", wide_req_address);
      word <= int'((wide_req_address - TILE_BASE) >> 6);
      wide_owned <= 1;
      activation_owned <= 0;
      remaining <= int'(wide_req_length);
      weight_bursts <= weight_bursts + 1;
    end else if ((rsp_valid && rsp_ready) || (wide_rsp_valid && wide_rsp_ready)) begin
      if (activation_owned) activation_beats <= activation_beats + 1;
      else weight_beats <= weight_beats + 1;
      if (wide_rsp_error) fault_sent <= 1;
      remaining <= remaining - 1;
      word <= word + 1;
    end
  end

  initial begin
    string fixture;
    if (!$value$plusargs("FIXTURE=%s", fixture)) $fatal(1, "Missing trained projection fixture");
    packed_mode = !$test$plusargs("SCALAR");
    bad_channel = $test$plusargs("BAD_CHANNEL");
    fault_mode = $test$plusargs("FAULT");
    cfg_packed_weights = packed_mode;
    $readmemh({fixture, "/activation.hex"}, activation);
    if (packed_mode) $readmemh({fixture, "/packed.hex"}, packed_weights);
    else $readmemh({fixture, "/scalar.hex"}, scalar_weights);
    $readmemh({fixture, "/expected.hex"}, expected);
    for (int row = 0; row < ROWS; row++) cfg_channels[row*16+:16] = 16'(FIRST_ROW + row);
    if (bad_channel) cfg_channels[19*16+:16] = 16'(FIRST_ROW + 20);
    repeat (3) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    if (!cfg_ready) $fatal(1, "Tensor did not accept trained configuration");
    cfg_valid = 1;
    @(negedge clk);
    cfg_valid = 0;
    wait (out_valid || done_valid);
    @(negedge clk);
    if (bad_channel || fault_mode) begin
      if (!done_valid || !done_error || out_valid || remaining != 0 ||
          (bad_channel && (activation_beats != 0 || weight_bursts != 0)) ||
          (fault_mode && (!fault_sent || weight_bursts != 1 || weight_beats < 2)))
        $fatal(1, "Packed tensor did not reject or drain the bad transaction");
      $display("PACKED_TENSOR_ERROR_PASS channel=%0d response=%0d drained=%0d",
               bad_channel, fault_mode, weight_beats);
    end else begin
      repeat (3) begin
        if (!out_valid || !out_last || out_tag !== 32'h70ad || out_token !== 0 ||
            out_count !== 8'(ROWS) || out_channels !== cfg_channels)
          $fatal(1, "Packed tensor result descriptor differs");
        for (int row = 0; row < ROWS; row++)
          if (out_data[row*32+:32] !== expected[row])
            $fatal(1, "PACKED_TENSOR_OUTPUT_MISMATCH packed=%0d row=%0d got=%h expected=%h",
                   packed_mode, FIRST_ROW + row, out_data[row*32+:32], expected[row]);
        @(negedge clk);
      end
      out_ready = 1;
      @(negedge clk);
      out_ready = 0;
      wait (done_valid);
      @(negedge clk);
      if (done_error || done_tag !== 32'h70ad || activation_beats != FEATURE_WORDS ||
          weight_beats <= 0 || weight_bursts <= 0)
        $fatal(1, "Trained tensor completed with incorrect inventory");
      $display("PACKED_TENSOR_PASS packed=%0d rows=%0d activations=%0d bursts=%0d beats=%0d cycles=%0d",
               packed_mode, ROWS, activation_beats, weight_bursts, weight_beats, cycle);
    end
    done_ready = 1;
    @(negedge clk);
    if (!cfg_ready) $fatal(1, "Completed tensor did not return to idle");
    $finish;
  end

  initial begin #5000000; $fatal(1, "Packed tensor watchdog"); end
endmodule
