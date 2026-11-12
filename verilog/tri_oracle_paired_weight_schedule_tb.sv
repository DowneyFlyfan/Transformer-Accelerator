`timescale 1ns/1ps
module tri_oracle_paired_weight_schedule_tb;
  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;
  localparam logic [63:0] GATE = 64'h10000000, UP = 64'h30000000;

  logic cfg_valid = 0, cfg_paired = 0;
  logic [63:0] cfg_base, cfg_up_base;
  logic [15:0] cfg_first_row;
  logic [16:0] cfg_dense_rows;
  logic [9:0] cfg_feature_words;
  logic [7:0] cfg_count, cfg_tile_start;
  logic [159:0] cfg_keep;
  logic [127:0] cfg_active_words;
  logic load_cfg_ready = 0, load_done_valid = 0, load_done_error = 0, done_ready = 0;
  wire cfg_ready, load_cfg_valid, load_done_ready, done_valid, done_error;
  wire [63:0] load_cfg_address;
  wire [4:0] load_cfg_core, load_cfg_first_word;
  wire [1:0] load_cfg_row_group;
  wire [7:0] load_cfg_row_enable;
  wire [5:0] load_cfg_words;
  int descriptors = 0, errors = 0;
  bit mutate_group;
  tri_oracle_paired_weight_schedule dut (.*);

  task automatic configure(input bit paired, input int count, input logic [63:0] up_base = UP);
    if (!cfg_ready) $fatal(1, "Paired schedule is busy");
    cfg_paired = paired;
    cfg_base = GATE;
    cfg_up_base = up_base;
    cfg_first_row = 16;
    cfg_dense_rows = 96;
    cfg_feature_words = 8;
    cfg_count = 8'(count);
    cfg_tile_start = 0;
    cfg_keep = {20{8'ha5}};
    cfg_active_words = {4{32'h3}};
    cfg_valid = 1;
    @(negedge clk);
    cfg_valid = 0;
    cfg_base = 'x;
    cfg_up_base = 'x;
    cfg_first_row = 'x;
    cfg_dense_rows = 'x;
    cfg_feature_words = 'x;
    cfg_count = 'x;
    cfg_tile_start = 'x;
    cfg_keep = 'x;
    cfg_active_words = 'x;
    cfg_paired = 'x;
  endtask

  task automatic descriptor(input bit paired, input bit up, input int group, input int part,
                            input logic [7:0] mask, input bit fault = 0);
    logic [63:0] address;
    int core, row_group;
    address = (up ? UP : GATE) + 64'(((2 + group) * 8 + part * 2) * 64);
    core = (group / (paired ? 2 : 4)) * 4 + part;
    row_group = (paired ? group % 2 + 2 * int'(up) : group % 4) ^ (mutate_group ? 1 : 0);
    wait (load_cfg_valid);
    @(negedge clk);
    repeat (2) begin
      if (!load_cfg_valid || load_cfg_address !== address || load_cfg_core !== 5'(core) ||
          load_cfg_row_group !== 2'(row_group) || load_cfg_row_enable !== mask ||
          load_cfg_words !== 6'd2 || load_cfg_first_word !== 0)
        $fatal(1, "PACKED_PAIR_DESCRIPTOR_MISMATCH branch=%0d group=%0d part=%0d", up, group, part);
      @(negedge clk);
    end
    load_cfg_ready = 1;
    @(negedge clk);
    load_cfg_ready = 0;
    if (!load_done_ready || load_cfg_valid || done_valid)
      $fatal(1, "Lost ownership before the loader finished");
    load_done_valid = 1;
    load_done_error = fault;
    @(negedge clk);
    load_done_valid = 0;
    load_done_error = 0;
    descriptors++;
  endtask

  task automatic finish_tile(input bit fault);
    wait (done_valid);
    @(negedge clk);
    if (load_cfg_valid || cfg_ready || done_error !== fault) $fatal(1, "Incorrect tile completion");
    done_ready = 1;
    @(negedge clk);
    done_ready = 0;
    if (fault) errors++;
  endtask

  initial begin
    mutate_group = $test$plusargs("MUTATE_GROUP");
    repeat (2) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    configure(1, 75);
    for (int branch = 0; branch < 2; branch++)
      for (int group = 0; group < 10; group++)
        for (int part = 0; part < 4; part++)
          descriptor(1, 1'(branch), group, part, group == 9 ? 8'h05 : 8'ha5);
    finish_tile(0);

    configure(0, 40);
    for (int group = 0; group < 5; group++)
      for (int part = 0; part < 4; part++) descriptor(0, 0, group, part, 8'ha5);
    finish_tile(0);

    configure(1, 8);
    for (int part = 0; part < 4; part++) descriptor(1, 0, 0, part, 8'ha5);
    descriptor(1, 1, 0, 0, 8'ha5, 1);
    finish_tile(1);
    configure(1, 81); finish_tile(1);
    configure(1, 8, UP + 8); finish_tile(1);
    if (descriptors != 105 || errors != 3) $fatal(1, "Paired schedule inventory mismatch");
    $display("PACKED_PAIR_SCHEDULE_PASS descriptors=105 failures=3");
    $finish;
  end

  initial begin #20000; $fatal(1, "Paired schedule timed out"); end
endmodule
