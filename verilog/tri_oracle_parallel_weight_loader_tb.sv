`timescale 1ns/1ps
module tri_oracle_parallel_weight_loader_tb;
  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;
  localparam logic [63:0] GATE = 64'h10000000, UP = 64'h30000000;
  localparam int FIRST_GROUP = 1, FEATURE_WORDS = 16;

  logic cfg_valid = 0, cfg_paired;
  wire cfg_ready;
  logic [63:0] cfg_base, cfg_up_base;
  logic [15:0] cfg_first_row;
  logic [16:0] cfg_dense_rows;
  logic [9:0] cfg_feature_words;
  logic [7:0] cfg_count, cfg_tile_start;
  logic [159:0] cfg_keep;
  logic [127:0] cfg_active_words;
  wire done_valid, done_error;
  logic done_ready = 0;
  wire [1:0] req_valid, rsp_ready, load_valid;
  wire [1:0][63:0] req_address;
  wire [1:0][5:0] req_length;
  logic [1:0] req_ready, rsp_valid, rsp_last, rsp_error;
  logic [1:0][511:0] rsp_data;
  wire [1:0][4:0] load_core;
  wire [1:0][9:0] load_addr;
  wire [1:0][31:0] load_row_enable;

  logic paired, inject_fault, force_collision, lane_one_released, fault_sent;
  logic [1:0] pending = 0;
  logic [1:0][63:0] address;
  logic [1:0][5:0] remaining;
  int count, responses, overlaps, conflicts, faults, both_live;
  bit seen[2][20][FEATURE_WORDS];
  tri_oracle_parallel_weight_loader dut (.*);

  function automatic int response_offset(input logic [63:0] addr);
    return int'((addr - (addr >= UP ? UP : GATE)) >> 6);
  endfunction

  function automatic int response_cluster(input logic [63:0] addr);
    return (response_offset(addr) / FEATURE_WORDS - FIRST_GROUP) / (paired ? 2 : 4);
  endfunction

  function automatic logic [7:0] expected_mask(input int group);
    logic [7:0] mask;
    for (int row = 0; row < 8; row++) mask[row] = 8*group + row < count;
    return mask & 8'hb7;
  endfunction

  always_comb begin
    req_ready = ~pending;
    rsp_valid = pending;
    if (force_collision && !lane_one_released &&
        !(pending[0] && response_cluster(address[0]) == 2))
      rsp_valid[1] = 0;
    rsp_last = {remaining[1] == 1, remaining[0] == 1};
    rsp_error = {1'b0, inject_fault && (&pending) && !fault_sent};
    for (int lane = 0; lane < 2; lane++) rsp_data[lane] = {8{address[lane]}};
  end

  always @(posedge clk) if (rst_n) begin
    if (rsp_valid[1]) lane_one_released <= 1;
    if (&pending) both_live++;
    if (&load_valid) begin
      overlaps++;
      if (load_core[0][4:2] == load_core[1][4:2]) $fatal(1, "PARALLEL_CLUSTER_DOUBLE_WRITE");
    end
    if ((&rsp_valid) && !inject_fault && response_cluster(address[0]) == response_cluster(address[1])) begin
      conflicts++;
      if (!(^rsp_ready) || !(^load_valid)) $fatal(1, "PARALLEL_CLUSTER_ARBITRATION");
    end
    for (int lane = 0; lane < 2; lane++) begin
      if (req_valid[lane] && req_ready[lane]) begin
        int word_index;
        word_index = response_offset(req_address[lane]) % 4;
        if (req_address[lane][5:0] != 0 ||
            !((word_index == 0 && req_length[lane] == 2) ||
              (word_index == 3 && req_length[lane] == 1)))
          $fatal(1, "PARALLEL_WRONG_BURST");
        pending[lane] <= 1;
        address[lane] <= req_address[lane];
        remaining[lane] <= req_length[lane];
      end
      if (rsp_valid[lane] && rsp_ready[lane]) begin
        if (rsp_error[lane]) begin
          faults++;
          fault_sent <= 1;
        end
        if (remaining[lane] == 1) pending[lane] <= 0;
        remaining[lane] <= remaining[lane] - 1'b1;
        address[lane] <= address[lane] + 64;
      end
      if (load_valid[lane]) begin
        int branch, group, feature_word, part, cluster, physical_group;
        logic [31:0] row_mask;
        branch = int'(address[lane] >= UP);
        group = response_offset(address[lane]) / FEATURE_WORDS - FIRST_GROUP;
        feature_word = response_offset(address[lane]) % FEATURE_WORDS;
        part = feature_word / 4;
        cluster = group / (paired ? 2 : 4);
        physical_group = paired ? group % 2 + 2*branch : group % 4;
        row_mask = 32'(expected_mask(group)) << (8*physical_group);
        if (!rsp_valid[lane] || !rsp_ready[lane] || rsp_error[lane] ||
            (cluster < 2 && lane != 0) || (cluster > 2 && lane != 1) ||
            (cluster == 2 && lane != part / 2) || (!paired && branch != 0) ||
            group < 0 || group*8 >= count || feature_word%4 == 2 ||
            load_core[lane] !== 5'(4*cluster+part) ||
            load_addr[lane] !== 10'(feature_word%4) || load_row_enable[lane] !== row_mask)
          $fatal(1, "PARALLEL_WRONG_WRITE lane=%0d address=%h core=%0d", lane, address[lane], load_core[lane]);
        if (seen[branch][group][feature_word]) $fatal(1, "PARALLEL_DUPLICATE_WRITE");
        seen[branch][group][feature_word] = 1;
        responses++;
      end
    end
  end

  task automatic run_tile(input bit is_paired, input int rows,
                          input bit collide = 0, input bit fault = 0);
    int expected;
    if (!cfg_ready) $fatal(1, "PARALLEL_CONFIG_BUSY");
    paired = is_paired;
    count = rows;
    force_collision = collide;
    inject_fault = fault;
    lane_one_released = 0;
    fault_sent = 0;
    responses = 0;
    overlaps = 0;
    conflicts = 0;
    faults = 0;
    both_live = 0;
    foreach (seen[branch, group, word_index]) seen[branch][group][word_index] = 0;
    cfg_paired = paired;
    cfg_base = GATE;
    cfg_up_base = UP;
    cfg_first_row = 8*FIRST_GROUP;
    cfg_dense_rows = 176;
    cfg_feature_words = FEATURE_WORDS;
    cfg_count = 8'(count);
    cfg_tile_start = 0;
    cfg_keep = {20{8'hb7}};
    cfg_active_words = {4{32'hb}};
    cfg_valid = 1;
    @(negedge clk);
    cfg_valid = 0;
    cfg_paired = 'x;
    cfg_base = 'x;
    cfg_up_base = 'x;
    cfg_count = 'x;
    cfg_keep = 'x;
    cfg_active_words = 'x;
    wait (done_valid);
    @(negedge clk);
    repeat (3) begin
      if (!done_valid || cfg_ready || done_error !== fault || pending != 0)
        $fatal(1, "PARALLEL_INCORRECT_TILE_COMPLETION done=%b ready=%b error=%b expected=%b pending=%b",
          done_valid, cfg_ready, done_error, fault, pending);
      @(negedge clk);
    end
    if (!fault) begin
      expected = ((count+7)/8)*12*(paired ? 2 : 1);
      if (responses != expected) $fatal(1, "PARALLEL_INCOMPLETE_WRITES actual=%0d expected=%0d", responses, expected);
      if (count > 64 && (both_live == 0 || (!collide && overlaps == 0)))
        $fatal(1, "PARALLEL_NO_CONCURRENT_RESPONSES");
      if (collide && conflicts == 0) $fatal(1, "PARALLEL_MISSING_CONFLICT_COVERAGE");
    end else if (faults != 1 || both_live == 0) $fatal(1, "PARALLEL_FAULT_COVERAGE");
    $display("PARALLEL_WEIGHT_TILE paired=%0d rows=%0d responses=%0d overlaps=%0d conflicts=%0d fault=%0d",
      paired, count, responses, overlaps, conflicts, fault);
    done_ready = 1;
    @(negedge clk);
    done_ready = 0;
  endtask

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    run_tile(1, 75, 1);
    run_tile(0, 155, 1);
    run_tile(1, 75, 0, 1);
    run_tile(1, 75);
    run_tile(0, 155);
    run_tile(0, 8);
    $display("PARALLEL_WEIGHT_LOADER_PASS tiles=6");
    $finish;
  end
  initial begin #100000; $fatal(1, "PARALLEL_WEIGHT_LOADER_TIMEOUT"); end
endmodule
