`timescale 1ns/1ps
module tri_oracle_packed_weight_schedule_tb;
  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic cfg_valid = 0;
  logic [63:0] cfg_base = 0;
  logic [15:0] cfg_first_row = 0;
  logic [16:0] cfg_dense_rows = 0;
  logic [9:0] cfg_feature_words = 0;
  logic [7:0] cfg_count = 0, cfg_tile_start = 0;
  logic [159:0] cfg_keep = 0;
  logic [127:0] cfg_active_words = 0;
  logic load_cfg_ready = 0, load_done_valid = 0, load_done_error = 0, done_ready = 0;
  wire cfg_ready, load_cfg_valid, load_done_ready, done_valid, done_error;
  wire [63:0] load_cfg_address;
  wire [4:0] load_cfg_core, load_cfg_first_word;
  wire [1:0] load_cfg_row_group;
  wire [7:0] load_cfg_row_enable;
  wire [5:0] load_cfg_words;
  int checked = 0, errors = 0;
  bit mutate_address;
  tri_oracle_packed_weight_schedule dut (.*);

  task automatic start();
    if (!cfg_ready) $fatal(1, "Scheduler did not accept a new tile");
    cfg_valid = 1;
    @(negedge clk);
    cfg_valid = 0;
  endtask

  task automatic descriptor(input logic [63:0] address, input int core, input int group,
                            input int first, input int words, input logic [7:0] mask,
                            input bit fault = 0);
    wait (load_cfg_valid);
    @(negedge clk);
    repeat (3) begin
      if (!load_cfg_valid || load_cfg_address !== address || load_cfg_core !== 5'(core) ||
          load_cfg_row_group !== 2'(group) || load_cfg_first_word !== 5'(first) ||
          load_cfg_words !== 6'(words) || load_cfg_row_enable !== mask)
        $fatal(1, "PACKED_WEIGHT_DESCRIPTOR_MISMATCH core=%0d group=%0d start=%0d got=%h expected=%h",
               core, group, first, load_cfg_address, address);
      @(negedge clk);
    end
    load_cfg_ready = 1;
    @(negedge clk);
    load_cfg_ready = 0;
    repeat (2) begin
      if (load_cfg_valid || !load_done_ready || done_valid)
        $fatal(1, "Scheduler advanced before burst completion");
      @(negedge clk);
    end
    load_done_valid = 1;
    load_done_error = fault;
    @(negedge clk);
    load_done_valid = 0;
    load_done_error = 0;
    checked++;
  endtask

  task automatic finish_tile(input bit error);
    wait (done_valid);
    @(negedge clk);
    repeat (2) begin
      if (!done_valid || done_error !== error || load_cfg_valid || cfg_ready)
        $fatal(1, "Invalid tile completion");
      @(negedge clk);
    end
    done_ready = 1;
    @(negedge clk);
    done_ready = 0;
    if (error) errors++;
  endtask

  function automatic logic [63:0] address(input logic [63:0] base, input int row,
                                         input int part, input int word);
    return base + 64'((row / 8 * 704 + part * 176 + word) * 64);
  endfunction

  initial begin
    mutate_address = $test$plusargs("MUTATE_ADDRESS");
    repeat (2) @(negedge clk);
    rst_n = 1;
    @(negedge clk);

    // A complete trained down-projection tile across all 20 cores.
    cfg_base = 64'hffffffc0; cfg_first_row = 1760; cfg_dense_rows = 2048;
    cfg_feature_words = 704; cfg_count = 160; cfg_tile_start = 32; cfg_keep = '1;
    cfg_active_words = '1;
    start();
    for (int group = 0; group < 20; group++)
      for (int part = 0; part < 4; part++)
        descriptor(address(64'hffffffc0, 1760 + group * 8, part, 32) +
                   (mutate_address ? 64'd64 : 64'd0), group / 4 * 4 + part, group % 4, 0, 32, 8'hff);
    finish_tile(0);

    // Truncate the final feature tile and row group, even with extra keep bits.
    cfg_base = 64'h10000000; cfg_first_row = 2032; cfg_count = 11; cfg_tile_start = 160;
    cfg_keep = 160'hffff_a500_0000_0000_0000_0000_0000_0000_0000_ff80;
    cfg_active_words = {32'h00004001, 32'h00000000, 32'hfffc0040, 32'hfffe0130};
    start();
    for (int group = 0; group < 2; group++) begin
      logic [7:0] mask;
      mask = group == 0 ? 8'h80 : 8'h07;
      descriptor(address(64'h10000000, 2032 + group * 8, 0, 164), 0, group, 4, 2, mask);
      descriptor(address(64'h10000000, 2032 + group * 8, 0, 168), 0, group, 8, 1, mask);
      descriptor(address(64'h10000000, 2032 + group * 8, 1, 166), 1, group, 6, 1, mask);
      descriptor(address(64'h10000000, 2032 + group * 8, 3, 160), 3, group, 0, 1, mask);
      descriptor(address(64'h10000000, 2032 + group * 8, 3, 174), 3, group, 14, 1, mask);
    end
    finish_tile(0);

    // A tile with no live rows makes no request.
    cfg_keep = 0;
    start();
    finish_tile(0);

    // Fail early on misalignment, an out-of-range group, or address overflow.
    cfg_keep = '1;
    cfg_first_row = 2033;
    start(); finish_tile(1);
    cfg_first_row = 2040;
    start(); finish_tile(1);
    cfg_first_row = 2032; cfg_base = 64'hffff_ffff_ffff_ffc0;
    start(); finish_tile(1);
    cfg_base = 64'h10000000; cfg_tile_start = 176;
    start(); finish_tile(1);
    cfg_tile_start = 160; cfg_base = 64'h10000008;
    start(); finish_tile(1);

    cfg_base = 64'h10000000;
    start();
    descriptor(address(64'h10000000, 2032, 0, 164), 0, 0, 4, 2, 8'hff, 1);
    finish_tile(1);

    if (checked != 91 || errors != 6) $fatal(1, "Scheduler verification count differs");
    $display("PACKED_WEIGHT_SCHEDULE_PASS descriptors=%0d rejected_tiles=%0d", checked, errors);
    $finish;
  end
  initial begin #30000; $fatal(1, "Packed scheduler test timed out"); end
endmodule
