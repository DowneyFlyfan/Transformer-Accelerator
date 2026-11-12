`timescale 1ns/1ps
module tri_oracle_weight_handoff_tb #(
  parameter bit STALL_COMPLETIONS = 0
);
  logic clk = 0;
  logic rst_n = 0;
  logic cfg_valid = 0;
  logic cfg_ready, done_valid, done_error;
  logic load_cfg_valid, load_cfg_ready, load_done_valid, load_done_error, load_done_ready;
  logic [63:0] load_cfg_address;
  logic [4:0] load_cfg_core, load_cfg_first_word;
  logic [1:0] load_cfg_row_group;
  logic [7:0] load_cfg_row_enable;
  logic [5:0] load_cfg_words;
  logic loader_done_valid;
  logic req_valid, rsp_ready, load_valid;
  logic [63:0] req_address;
  logic [5:0] req_length;
  logic [4:0] load_core;
  logic [9:0] load_addr;
  logic [31:0] load_row_enable;
  logic [2047:0] load_data;

  int remaining = 0;
  int requests = 0;
  int writes = 0;
  int cycles = 0;
  int last_write = -1;
  int worst_gap = 0;
  int completion_hold = 0;
  int held_completion_cycles = 0;
  logic rsp_valid, rsp_last;

  always #5 clk = ~clk;
  assign rsp_valid = remaining != 0;
  assign rsp_last = remaining == 1;
  assign load_done_valid = loader_done_valid && completion_hold == 0;

  tri_oracle_packed_weight_schedule schedule (
    .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_base(64'h1000),
    .cfg_first_row(16'd0), .cfg_dense_rows(17'd8), .cfg_feature_words(10'd128),
    .cfg_count(8'd8), .cfg_tile_start(8'd0), .cfg_keep(160'hff), .cfg_active_words('1),
    .load_cfg_valid, .load_cfg_ready, .load_cfg_address, .load_cfg_core,
    .load_cfg_first_word, .load_cfg_row_group, .load_cfg_row_enable, .load_cfg_words,
    .load_done_valid, .load_done_error, .load_done_ready,
    .done_valid, .done_ready(1'b1), .done_error
  );
  tri_oracle_wide_weight_loader loader (
    .clk, .rst_n, .cfg_valid(load_cfg_valid), .cfg_ready(load_cfg_ready),
    .cfg_address(load_cfg_address), .cfg_core(load_cfg_core), .cfg_first_word(load_cfg_first_word),
    .cfg_row_group(load_cfg_row_group), .cfg_row_enable(load_cfg_row_enable), .cfg_words(load_cfg_words),
    .done_valid(loader_done_valid), .done_ready(load_done_ready && completion_hold == 0),
    .done_error(load_done_error),
    .req_valid, .req_ready(1'b1), .req_address, .req_length,
    .rsp_valid, .rsp_ready, .rsp_last, .rsp_error(1'b0), .rsp_data({8{req_address}}),
    .load_valid, .load_ready(1'b1), .load_core, .load_addr, .load_row_enable, .load_data
  );

  always @(posedge clk) if (rst_n) begin
    cycles++;
    if (completion_hold != 0) begin
      if (!loader_done_valid || load_done_error)
        $fatal(1, "Pending burst completion changed while stalled");
      completion_hold <= completion_hold - 1;
      held_completion_cycles++;
    end
    if (req_valid) begin
      if (remaining != 0 || requests >= 4 || req_length != 32 ||
          req_address != 64'h1000 + 64'(requests)*64'd2048)
        $fatal(1, "Unexpected packed request sequence");
      requests++;
      remaining <= int'(req_length);
    end
    if (rsp_valid) begin
      if (!rsp_ready || !load_valid || load_core != 5'(writes / 32) ||
          load_addr != 10'(writes % 32) || load_row_enable != 32'hff ||
          load_data !== {{1536{1'b0}}, {8{req_address}}})
        $fatal(1, "A packed weight write was lost or changed");
      if (last_write >= 0 && cycles - last_write - 1 > worst_gap)
        worst_gap = cycles - last_write - 1;
      last_write = cycles;
      writes++;
      if (STALL_COMPLETIONS && writes == 32) completion_hold <= 3;
      remaining <= remaining - 1;
    end
    if (done_valid) begin
      if (done_error || requests != 4 || writes != 128)
        $fatal(1, "Incomplete packed transfer");
      if (worst_gap != 1)
        $fatal(1, "WEIGHT_HANDOFF_GAP expected=1 actual=%0d", worst_gap);
      if (held_completion_cycles != (STALL_COMPLETIONS ? 3 : 0))
        $fatal(1, "Completion stall coverage did not match the selected case");
      if (STALL_COMPLETIONS)
        $display("WEIGHT_HANDOFF_COMPLETION_STALL_PASS cycles=%0d", held_completion_cycles);
      $display("WEIGHT_HANDOFF_PASS requests=4 writes=128 worst_gap=%0d", worst_gap);
      $finish;
    end
  end

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    cfg_valid = 1;
    @(negedge clk);
    cfg_valid = 0;
    #3000;
    $fatal(1, "Packed handoff test timed out");
  end
endmodule
