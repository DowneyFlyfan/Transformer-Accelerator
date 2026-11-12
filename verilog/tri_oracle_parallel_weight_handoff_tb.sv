`timescale 1ns/1ps
module tri_oracle_parallel_weight_handoff_tb #(
  parameter int EXPECTED_GAP = 1
);
  localparam logic [63:0] BASE = 64'h1000;
  logic clk = 0, rst_n = 0, cfg_valid = 0;
  wire cfg_ready, done_valid, done_error;
  wire [1:0] req_valid, rsp_ready, load_valid;
  wire [1:0][63:0] req_address;
  wire [1:0][5:0] req_length;
  wire [1:0][4:0] load_core;
  wire [1:0][9:0] load_addr;
  wire [1:0][31:0] load_row_enable;
  logic [1:0][63:0] address = '0;
  logic [1:0][5:0] remaining = '0;
  wire [1:0] rsp_valid = {remaining[1] != 0, remaining[0] != 0};
  wire [1:0] rsp_last = {remaining[1] == 1, remaining[0] == 1};
  int cycle = 0, overlaps = 0;
  int requests[2] = '{default:0};
  int writes[2] = '{default:0};
  int handoffs[2] = '{default:0};
  int previous_cycle[2], previous_group[2];
  bit seen[20][128];

  always #5 clk = ~clk;

  tri_oracle_parallel_weight_loader dut (
    .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_paired(1'b0),
    .cfg_base(BASE), .cfg_up_base(64'd0), .cfg_first_row(16'd0),
    .cfg_dense_rows(17'd160), .cfg_feature_words(10'd128), .cfg_count(8'd160),
    .cfg_tile_start(8'd0), .cfg_keep('1), .cfg_active_words('1),
    .req_valid, .req_ready(~rsp_valid), .req_address, .req_length,
    .rsp_valid, .rsp_last, .rsp_error(2'b0), .rsp_ready,
    .load_valid, .load_core, .load_addr, .load_row_enable,
    .done_valid, .done_ready(1'b1), .done_error
  );

  always @(posedge clk) if (rst_n) begin
    cycle++;
    if (&load_valid) overlaps++;
    for (int lane = 0; lane < 2; lane++) begin
      if (req_valid[lane] && !rsp_valid[lane]) begin
        if (req_length[lane] !== 6'd32 || req_address[lane] < BASE ||
            req_address[lane] >= BASE + 64'(20*128*64) || req_address[lane][10:0] != 0)
          $fatal(1, "Unexpected dense request lane=%0d address=%h length=%0d", lane, req_address[lane], req_length[lane]);
        requests[lane]++;
        address[lane] <= req_address[lane];
        remaining[lane] <= req_length[lane];
      end
      if (rsp_valid[lane] && rsp_ready[lane]) begin
        int offset, group, word, core;
        offset = int'((address[lane] - BASE) >> 6);
        group = offset / 128;
        word = offset % 128;
        core = 4 * (group / 4) + word / 32;
        if (load_valid[lane] !== 1'b1 || group >= 20 || seen[group][word] ||
            ((core < 10) != (lane == 0)) || load_core[lane] !== 5'(core) ||
            load_addr[lane] !== 10'(word % 32) || load_row_enable[lane] !== (32'hff << (8 * (group % 4))))
          $fatal(1, "Wrong or duplicate dense write lane=%0d group=%0d word=%0d", lane, group, word);
        if (word % 32 == 0 && writes[lane] != 0 && group == previous_group[lane]) begin
          int gap;
          gap = cycle - previous_cycle[lane] - 1;
          if (gap != EXPECTED_GAP)
            $fatal(1, "DENSE_HANDOFF_GAP lane=%0d group=%0d expected=%0d actual=%0d", lane, group, EXPECTED_GAP, gap);
          handoffs[lane]++;
        end
        seen[group][word] = 1;
        writes[lane]++;
        previous_cycle[lane] = cycle;
        previous_group[lane] = group;
        address[lane] <= address[lane] + 64;
        remaining[lane] <= remaining[lane] - 1'b1;
      end else if (load_valid[lane] !== 1'b0) $fatal(1, "Write without an accepted response");
    end
    if (done_valid) begin
      if (done_error !== 1'b0 || rsp_valid != 0 || overlaps == 0)
        $fatal(1, "Dense dual-lane completion or overlap failed");
      for (int lane = 0; lane < 2; lane++)
        if (requests[lane] != 40 || writes[lane] != 1280 || handoffs[lane] != 28)
          $fatal(1, "Missing dense coverage lane=%0d requests=%0d writes=%0d handoffs=%0d",
                 lane, requests[lane], writes[lane], handoffs[lane]);
      $display("DENSE_PARALLEL_HANDOFF_PASS requests_per_lane=40 writes_per_lane=1280 handoffs_per_lane=28 gap=%0d overlap=%0d cycles=%0d",
               EXPECTED_GAP, overlaps, cycle);
      $finish;
    end
  end

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    cfg_valid = 1;
    @(negedge clk);
    cfg_valid = 0;
    #30000;
    $fatal(1, "Dense dual-lane test timed out");
  end
endmodule
