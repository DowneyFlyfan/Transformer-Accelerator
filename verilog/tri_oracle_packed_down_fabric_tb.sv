`timescale 1ns/1ps
module tri_oracle_packed_down_fabric_tb;
  localparam int CLUSTERS = 5, PARTS = 4, GROUPS = 4, WORDS = 2;
  localparam int FIRST_ROW = 1760, FIRST_WORD = 33, PART_WORDS = 176;
  localparam int RESPONSES = CLUSTERS * PARTS * GROUPS * WORDS;
  localparam logic [63:0] BASE = 64'h10000000;
  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic cfg_valid = 0, done_ready = 0, req_ready = 0, rsp_valid = 0, rsp_last = 0;
  logic [63:0] cfg_address = 0;
  logic [4:0] cfg_core = 0;
  logic [1:0] cfg_row_group = 0;
  logic [511:0] rsp_data = 0;
  wire cfg_ready, done_valid, done_error, req_valid, rsp_ready, load_valid;
  wire [63:0] req_address;
  wire [5:0] req_length;
  wire [4:0] load_core;
  wire [9:0] load_addr;
  wire [31:0] load_row_enable;
  wire [2047:0] load_data;

  logic init_valid = 0, cmd_valid = 0;
  logic [4:0] init_core = 0, cmd_weight = 0;
  logic [1:0] init_kind = 0;
  logic [9:0] init_addr = 0;
  logic [2047:0] init_data = 0;
  logic [4:0] out_ready = 0;
  wire load_error, cmd_ready;
  wire [4:0] out_valid;
  wire [19:0] out_output;
  wire [5119:0] out_data;

  tri_oracle_wide_weight_loader loader (
    .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_address, .cfg_core, .cfg_row_group,
    .cfg_first_word(5'd1), .cfg_row_enable(8'hff), .cfg_words(6'(WORDS)),
    .done_valid, .done_ready, .done_error, .req_valid, .req_ready, .req_address, .req_length,
    .rsp_valid, .rsp_ready, .rsp_last, .rsp_error(1'b0), .rsp_data,
    .load_valid, .load_ready(!init_valid), .load_core, .load_addr, .load_row_enable, .load_data
  );

  tri_oracle_compute_fabric fabric (
    .clk, .rst_n, .load_valid(init_valid || load_valid), .load_core(init_valid ? init_core : load_core),
    .load_kind(init_valid ? init_kind : 2'b00), .load_addr(init_valid ? init_addr : load_addr),
    .load_row_enable(init_valid ? '1 : load_row_enable), .load_data(init_valid ? init_data : load_data),
    .load_error, .cmd_valid, .cmd_ready, .cmd_clusters(5'b11111), .cmd_weight, .cmd_mask(5'd0),
    .cmd_activation(10'(cmd_weight)), .cmd_output(4'd0), .cmd_accumulate(1'b0), .cmd_reduce(2'd0),
    .out_valid, .out_ready, .out_output, .out_data,
    .merge_sign_data('0), .merge_sign_control('0), .merge_sign_counts(),
    .merge_table_request('0), .merge_table_word(), .strip_rst_n(1'b0),
    .strip_request('0), .strip_response(), .head_request('0), .head_response()
  );

  logic [511:0] responses[RESPONSES];
  logic [63:0] activation[PARTS * WORDS];
  logic [31:0] expected[WORDS * CLUSTERS * 32];
  int writes = 0, requests = 0, checked_rows = 0;
  bit rotate_lanes;

  always @(posedge clk) if (rst_n) begin
    if (load_error || (init_valid && load_valid)) $fatal(1, "Packed fabric load conflict");
    if (req_valid && req_ready) requests++;
    if (load_valid) writes++;
  end

  task automatic initialize(input int core, input logic [1:0] kind, input int address,
                            input logic [2047:0] data);
    init_valid = 1; init_core = 5'(core); init_kind = kind; init_addr = 10'(address);
    init_data = data;
    @(negedge clk);
    init_valid = 0;
  endtask

  task automatic load_group(input int cluster, input int part, input int group);
    int row, first_response;
    row = FIRST_ROW + cluster * 32 + group * 8;
    first_response = ((cluster * PARTS + part) * GROUPS + group) * WORDS;
    if (!cfg_ready) $fatal(1, "Loader is busy");
    cfg_address = BASE + 64'((row / 8 * PARTS * PART_WORDS + part * PART_WORDS + FIRST_WORD) * 64);
    cfg_core = 5'(cluster * PARTS + part);
    cfg_row_group = 2'(group);
    cfg_valid = 1;
    @(negedge clk);
    cfg_valid = 0;
    if (!req_valid || req_address !== cfg_address || req_length !== 6'(WORDS))
      $fatal(1, "Packed request address or length differs");
    req_ready = 1;
    @(negedge clk);
    req_ready = 0;
    for (int beat = 0; beat < WORDS; beat++) begin
      rsp_valid = 1;
      rsp_last = beat == WORDS - 1;
      rsp_data = responses[first_response + beat];
      if (rotate_lanes) rsp_data = {rsp_data[63:0], rsp_data[511:64]};
      @(posedge clk);
      if (!rsp_ready || !load_valid || load_core !== cfg_core || load_addr !== 10'(1 + beat) ||
          load_row_enable !== (32'hff << (group * 8)))
        $fatal(1, "Packed beat did not reach the selected SRAM rows");
      @(negedge clk);
    end
    rsp_valid = 0;
    if (!done_valid || done_error) $fatal(1, "Packed burst did not complete");
    done_ready = 1;
    @(negedge clk);
    done_ready = 0;
  endtask

  task automatic compare_projection(input int beat);
    cmd_weight = 5'(1 + beat);
    cmd_valid = 1;
    @(posedge clk);
    if (!cmd_ready) $fatal(1, "Compute fabric rejected projection");
    @(negedge clk);
    cmd_valid = 0;
    wait (out_valid === 5'b11111);
    @(negedge clk);
    if (out_output !== '0) $fatal(1, "Unexpected projection output slot");
    for (int row = 0; row < CLUSTERS * 32; row++) begin
      if (out_data[row*32+:32] !== expected[beat * CLUSTERS * 32 + row])
        $fatal(1, "PACKED_DOWN_FABRIC_MISMATCH word=%0d row=%0d actual=%h expected=%h", beat,
               FIRST_ROW + row, out_data[row*32+:32], expected[beat * CLUSTERS * 32 + row]);
      checked_rows++;
    end
    out_ready = '1;
    @(negedge clk);
    out_ready = '0;
  endtask

  initial begin
    string fixture;
    if (!$value$plusargs("FIXTURE=%s", fixture)) $fatal(1, "Missing packed fixture");
    $readmemh({fixture, "/responses.hex"}, responses);
    $readmemh({fixture, "/activations.hex"}, activation);
    $readmemh({fixture, "/expected.hex"}, expected);
    rotate_lanes = $test$plusargs("ROTATE_LANES");
    repeat (2) @(negedge clk);
    rst_n = 1;
    for (int cluster = 0; cluster < CLUSTERS; cluster++) begin
      for (int part = 0; part < PARTS; part++) begin
        initialize(cluster * PARTS + part, 2, 0, {{1792{1'b0}}, {256{1'b1}}});
        for (int beat = 0; beat < WORDS; beat++)
          initialize(cluster * PARTS + part, 1, 1 + beat, {1984'b0, activation[part * WORDS + beat]});
        for (int group = 0; group < GROUPS; group++) load_group(cluster, part, group);
      end
    end
    for (int beat = 0; beat < WORDS; beat++) compare_projection(beat);
    if (writes != RESPONSES || requests != RESPONSES / WORDS || checked_rows != WORDS * CLUSTERS * 32)
      $fatal(1, "Packed transfer or output count differs");
    $display("PACKED_DOWN_FABRIC_PASS requests=%0d responses=%0d exact_partial_outputs=%0d",
             requests, writes, checked_rows);
    $finish;
  end

  initial begin #20000; $fatal(1, "Packed fabric test timed out"); end
endmodule
