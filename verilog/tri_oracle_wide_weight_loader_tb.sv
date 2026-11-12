`timescale 1ns/1ps
module tri_oracle_wide_weight_loader_tb;
  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic cfg_valid = 0, done_ready = 0, req_ready = 0, rsp_valid = 0;
  logic rsp_last = 0, rsp_error = 0, load_ready = 1;
  logic [63:0] cfg_address = 0;
  logic [4:0] cfg_core = 0, cfg_first_word = 0;
  logic [1:0] cfg_row_group = 0;
  logic [7:0] cfg_row_enable = 0;
  logic [5:0] cfg_words = 0;
  logic [511:0] rsp_data = 0;
  wire cfg_ready, done_valid, done_error, req_valid, rsp_ready, load_valid;
  wire [63:0] req_address;
  wire [5:0] req_length;
  wire [4:0] load_core;
  wire [9:0] load_addr;
  wire [31:0] load_row_enable;
  wire [2047:0] load_data;
  tri_oracle_wide_weight_loader loader (.*);

  logic init_valid = 0, cmd_valid = 0, read_valid = 0;
  logic [1:0] init_kind = 0;
  logic [9:0] init_address = 0;
  logic [2047:0] init_data = 0;
  logic [4:0] cmd_weight = 0;
  wire load_error, cmd_ready, core_done, result_valid;
  wire [1023:0] result_data;
  tri_oracle_sram_memory_compute core (
    .clk, .rst_n,
    .load_valid(init_valid || (load_valid && load_ready)),
    .load_kind(init_valid ? init_kind : 2'b00),
    .load_addr(init_valid ? init_address : load_addr),
    .load_data(init_valid ? init_data : load_data),
    .load_row_enable(init_valid ? 32'hffffffff : load_row_enable), .load_error,
    .cmd_valid, .cmd_ready, .cmd_weight, .cmd_activation(10'd0), .cmd_mask(5'd0),
    .cmd_output(4'd0), .cmd_accumulate(1'b0), .done_valid(core_done), .done_output(),
    .read_valid, .read_output(4'd0), .result_valid, .result_data
  );

  int writes = 0, cycle = 0, last_write = -1;
  bit check_consecutive = 0;
  always @(posedge clk) if (rst_n) begin
    cycle++;
    if (load_valid && load_ready) begin
      if (load_core !== 5'd7 || load_row_enable !== (32'(cfg_row_enable) << {cfg_row_group, 3'b000}))
        $fatal(1, "Incorrect core or row mask");
      if (check_consecutive && writes != 0 && cycle != last_write + 1)
        $fatal(1, "An available wide response was serialized");
      if (check_consecutive && load_addr !== 10'(writes))
        $fatal(1, "Incorrect sequential SRAM address");
      last_write = cycle;
      writes++;
    end
  end

  task automatic initialize(input logic [1:0] kind, input logic [9:0] address,
                            input logic [2047:0] data);
    init_valid = 1; init_kind = kind; init_address = address; init_data = data;
    @(negedge clk);
    init_valid = 0;
    if (load_error !== 0) $fatal(1, "Initial core load failed");
  endtask

  task automatic configure(input logic [4:0] first, input logic [5:0] words,
                           input bit expect_request = 1, input logic [7:0] mask = 8'ha5,
                           input logic [1:0] group = 2, input logic [63:0] address = 64'h8000,
                           input logic [4:0] core_id = 7);
    if (cfg_ready !== 1) $fatal(1, "Configuration interface busy");
    cfg_valid = 1; cfg_address = address; cfg_core = core_id; cfg_row_group = group;
    cfg_row_enable = mask; cfg_first_word = first; cfg_words = words;
    @(negedge clk);
    cfg_valid = 0;
    if (expect_request) begin
      repeat (2) begin
        if (!req_valid || req_address !== address || req_length !== words)
          $fatal(1, "Request changed while stalled");
        @(negedge clk);
      end
      req_ready = 1;
      @(negedge clk);
      req_ready = 0;
    end else if (req_valid !== 0) $fatal(1, "Invalid range produced a request");
  endtask

  function automatic logic signed [7:0] weight(input int beat, input int lane);
    return 8'(-32 + 9 * beat + 3 * lane);
  endfunction

  task automatic offer(input int beat, input bit last, input bit fault = 0);
    rsp_valid = 1; rsp_last = last; rsp_error = fault;
    for (int lane = 0; lane < 8; lane++) rsp_data[lane*64+:64] = {8{weight(beat, lane)}};
  endtask

  task automatic accept_beat();
    @(posedge clk);
    if (rsp_ready !== 1) $fatal(1, "Offered beat failed to transfer");
    @(negedge clk);
    rsp_valid = 0;
  endtask

  task automatic complete(input bit error);
    repeat (2) begin
      if (!done_valid || done_error !== error || cfg_ready || req_valid || load_valid)
        $fatal(1, "Incorrect or unstable completion");
      @(negedge clk);
    end
    done_ready = 1;
    @(negedge clk);
    done_ready = 0;
  endtask

  task automatic check_word(input int address);
    cmd_weight = 5'(address); cmd_valid = 1;
    @(posedge clk);
    if (!cmd_ready) $fatal(1, "Core failed to accept readback computation");
    @(negedge clk);
    cmd_valid = 0;
    wait (core_done);
    @(negedge clk);
    read_valid = 1;
    @(posedge clk); #1;
    if (!result_valid) $fatal(1, "Missing core readback result");
    for (int row = 0; row < 32; row++) begin
      int expected;
      expected = 16;
      if (address == 3 || (row >= 16 && row < 24 && ((8'ha5 >> (row - 16)) & 1) != 0))
        expected = 8 * int'(weight(address, row % 8));
      if ($signed(result_data[row*32+:32]) !== expected)
        $fatal(1, "Incorrect masked readback address=%0d row=%0d expected=%0d", address, row, expected);
    end
    @(negedge clk);
    read_valid = 0;
  endtask

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    initialize(1, 0, 2048'h0101010101010101);
    initialize(2, 0, {{1792{1'b0}}, {256{1'b1}}});
    for (int address = 0; address < 4; address++) initialize(0, 10'(address), {256{8'd2}});

    configure(0, 3);
    check_consecutive = 1;
    load_ready = 0;
    offer(0, 0);
    repeat (2) begin
      @(posedge clk);
      if (!load_valid || rsp_ready || load_addr !== 0 || writes != 0)
        $fatal(1, "Backpressure changed or consumed the first write");
      @(negedge clk);
    end
    load_ready = 1;
    accept_beat();
    offer(1, 0); accept_beat();
    offer(2, 1); accept_beat();
    check_consecutive = 0;
    complete(0);
    for (int group = 0; group < 4; group++) begin
      configure(3, 1, 1, 8'hff, 2'(group));
      offer(3, 1); accept_beat(); complete(0);
    end
    for (int address = 0; address < 4; address++) check_word(address);

    configure(31, 2, 0); complete(1);
    configure(0, 0, 0); complete(1);
    configure(0, 2, 0, 8'hff, 2, 64'hffffffffffffffc0); complete(1);
    configure(0, 1, 0, 8'hff, 2, 64'h8008); complete(1);
    configure(0, 1, 0, 8'hff, 2, 64'h8000, 20); complete(1);
    configure(4, 2);
    offer(0, 1); accept_beat(); complete(1);
    configure(6, 1);
    offer(0, 0); accept_beat();
    load_ready = 0;
    offer(1, 1); accept_beat(); complete(1);
    load_ready = 1;
    configure(7, 1);
    offer(0, 1, 1); accept_beat(); complete(1);
    if (writes != 7) $fatal(1, "Malformed responses altered the write count");
    $display("WIDE_WEIGHT_SRAM_PASS writes=7 lanes_per_write=8 groups=4 checked_rows=128 failures=8");
    $finish;
  end

  initial begin #10000; $fatal(1, "Wide weight test timed out"); end
endmodule
