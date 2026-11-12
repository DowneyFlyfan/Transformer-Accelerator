`timescale 1ns/1ps
module tri_oracle_weight_burst_budget_tb;
  logic clk = 0;
  logic rst_n = 0;
  logic cfg_ready, req_valid, rsp_ready, load_valid, done_valid, done_error;
  logic [5:0] req_length;
  int descriptors = 0;
  int remaining = 0;
  int completions = 0;
  int requests = 0;
  int responses = 0;
  int cycles = 0;
  int first_last = -1;
  int gap = -1;
  logic cfg_valid, rsp_valid, rsp_last;

  always #5 clk = ~clk;
  assign cfg_valid = descriptors < 3;
  assign rsp_valid = remaining != 0;
  assign rsp_last = remaining == 1;

  tri_oracle_wide_weight_loader dut (
    .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_address(64'h1000),
    .cfg_core(5'd0), .cfg_first_word(5'd0), .cfg_row_group(2'd0),
    .cfg_row_enable(8'hff), .cfg_words(descriptors < 2 ? 6'd32 : 6'd33),
    .done_valid, .done_ready(1'b1), .done_error, .req_valid, .req_ready(1'b1),
    .req_address(), .req_length, .rsp_valid, .rsp_ready, .rsp_last,
    .rsp_error(1'b0), .rsp_data('0), .load_valid, .load_ready(1'b1),
    .load_core(), .load_addr(), .load_row_enable(), .load_data()
  );

  always @(posedge clk) if (rst_n) begin
    cycles++;
    if (cfg_valid && cfg_ready) descriptors <= descriptors + 1;
    if (req_valid) begin
      if (remaining != 0 || req_length != 32 || requests >= 2)
        $fatal(1, "Unexpected request or overlapping burst");
      requests++;
      remaining <= int'(req_length);
    end
    if (rsp_valid) begin
      if (!rsp_ready || !load_valid)
        $fatal(1, "An unstalled payload beat was lost");
      responses++;
      remaining <= remaining - 1;
      if (responses == 32) first_last = cycles;
      if (responses == 33) gap = cycles - first_last - 1;
    end
    if (done_valid) begin
      completions++;
      if (done_error !== (completions == 3))
        $fatal(1, "Unexpected completion status");
      if (completions == 3) begin
        if (requests != 2 || responses != 64 || gap != 3)
          $fatal(1, "Unexpected best-case burst cadence");
        $display("WEIGHT_BURST_BUDGET_PASS max_beats=32 inter_burst_cycles=%0d payload_beats=%0d oversize_rejected=1",
                 gap, responses);
        $finish;
      end
    end
  end

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    #1000;
    $fatal(1, "Weight burst budget test timed out");
  end
endmodule
