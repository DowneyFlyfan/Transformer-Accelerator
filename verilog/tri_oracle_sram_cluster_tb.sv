`timescale 1ns/1ps
// Arithmetic and ordered-transaction oracle, independent of cluster internals.
module tri_oracle_compute_cluster_tb;
  logic clk = 0;
  always #5 clk = ~clk;
  logic rst_n = 0, load_valid = 0, cmd_valid = 0, cmd_accumulate = 0;
  logic [1:0] load_core = 0, load_kind = 0, cmd_reduce = 0;
  logic [9:0] load_addr = 0, cmd_activation = 0;
  logic [2047:0] load_data = 0;
  logic [31:0] load_row_enable = '1;
  logic [4:0] cmd_weight = 0, cmd_mask = 0;
  logic [3:0] cmd_output = 0, out_output;
  logic load_error, cmd_ready, out_valid, out_ready;
  logic [1023:0] out_data;
  integer ready_mode = 0, cycle = 0;
  integer dots[2][4][32], memory_model[4][16][32], queued[64][32], tags[64];
  integer accepted = 0, retired = 0, target = 0, held_cycles = 0;
  logic held = 0, require_full_rate = 0;
  logic [1023:0] held_data;
  logic [3:0] held_tag;
  tri_oracle_compute_cluster dut (.merge_sign_data('0), .merge_sign_control('0), .merge_sign_counts(), .merge_table_request('0), .merge_table_word(), .strip_rst_n(1'b0), .strip_request('0), .strip_response(), .head_request('0), .head_response(), .*);

  always @(out_valid or out_output or out_data)
    if (rst_n && held && !out_ready
        && (!out_valid || out_output !== held_tag || out_data !== held_data))
      $fatal(1, "CLUSTER_OUTPUT_CHANGED_WHILE_STALLED");

  always_comb out_ready = ready_mode == 1 || (ready_mode == 2 && cycle % 7 < 2);
  function automatic integer weight(input integer c, r, lane, phase);
    return (r*7+c*13+lane*5+phase*3) % 29 - 14;
  endfunction
  function automatic integer activation(input integer c, lane, phase);
    return (lane*11+c*3+phase*5) % 23 - 11;
  endfunction
  function automatic logic enabled(input integer c, r, lane, phase);
    return (r+lane+c+phase) % 3 != 0;
  endfunction
  function automatic integer reference_reduce(input integer a, b, c, d, mode);
    longint signed total;
    integer maximum;
    total = longint'(a) + longint'(b) + longint'(c) + longint'(d);
    maximum = 32'sh80000000;
    if (a > maximum) maximum = a;
    if (b > maximum) maximum = b;
    if (c > maximum) maximum = c;
    if (d > maximum) maximum = d;
    case (mode)
      1: return maximum;
      2: return 32'(total >>> 2);
      default: return 32'(total);
    endcase
  endfunction
  task automatic check_reduction(input integer a, b, c, d);
    for (integer mode = 0; mode < 3; mode++)
      if (dut.reduce_four(a, b, c, d, 2'(mode)) !== reference_reduce(a, b, c, d, mode))
        $fatal(1, "CLUSTER_REDUCTION_BOUNDARY");
  endtask
`ifdef TRI_ORACLE_CHECK_CLUSTER_MEMORY
  always @(posedge clk)
    if (rst_n && !dut.aggregate_memory[0].WEB && !dut.aggregate_memory[0].REB
        && dut.aggregate_memory[0].AA === dut.aggregate_memory[0].AB)
      $fatal(1, "CLUSTER_NATIVE_READ_WRITE_COLLISION");
`endif

  always @(posedge clk) begin : scoreboard
    integer phase;
    cycle <= cycle + 1;
    if (!rst_n) begin
      accepted = retired;
      held = 0;
      #2;
      if (out_valid) $fatal(1, "CLUSTER_RESET_FLUSH");
    end else begin
      if (held) begin
        held_cycles++;
        if (!out_valid || out_output !== held_tag || out_data !== held_data)
          $fatal(1, "CLUSTER_OUTPUT_CHANGED_WHILE_STALLED");
      end
      held = out_valid && !out_ready;
      if (held) begin
        held_tag = out_output;
        held_data = out_data;
      end
      if (require_full_rate && retired < target && !out_valid)
        $fatal(1, "CLUSTER_COMPLETED_QUEUE_THROUGHPUT");
      if (cmd_valid && cmd_ready) begin
        phase = cmd_weight == 31 ? 1 : 0;
        tags[accepted] = int'(cmd_output);
        for (integer row = 0; row < 32; row++) begin
          for (integer c = 0; c < 4; c++) begin
            if (cmd_accumulate) memory_model[c][cmd_output][row] += dots[phase][c][row];
            else memory_model[c][cmd_output][row] = dots[phase][c][row];
          end
          queued[accepted][row] = reference_reduce(memory_model[0][cmd_output][row],
              memory_model[1][cmd_output][row], memory_model[2][cmd_output][row],
              memory_model[3][cmd_output][row], int'(cmd_reduce));
        end
        accepted++;
      end
      if (out_valid && out_ready) begin
        if (retired >= accepted || out_output !== 4'(tags[retired]))
          $fatal(1, "CLUSTER_OUTPUT_ORDER");
        for (integer row = 0; row < 32; row++)
          if ($signed(out_data[row*32+:32]) !== queued[retired][row])
            $fatal(1, "CLUSTER_ARITHMETIC row=%0d got=%0d expected=%0d", row,
                   $signed(out_data[row*32+:32]), queued[retired][row]);
        retired++;
      end
    end
  end

  task automatic load(input integer c, kind, address, input logic [2047:0] data);
    @(negedge clk);
    load_valid = 1;
    load_core = 2'(c);
    load_kind = 2'(kind);
    load_addr = 10'(address);
    load_data = data;
    @(posedge clk);
    #2;
    if (cmd_ready || load_error) $fatal(1, "CLUSTER_LOAD_CONTRACT");
    @(negedge clk);
    load_valid = 0;
  endtask

  task automatic issue(input integer n, phase, accumulate);
    @(negedge clk);
    cmd_valid = 1;
    cmd_output = 4'(n*5);
    cmd_weight = phase == 1 ? 31 : 0;
    cmd_mask = phase == 1 ? 31 : 0;
    cmd_activation = phase == 1 ? 1023 : 0;
    cmd_accumulate = 1'(accumulate);
    cmd_reduce = 2'((n+phase) % 3);
    @(posedge clk);
    if (!cmd_ready) $fatal(1, "CLUSTER_ISSUE_RATE");
  endtask

  initial begin
    if (reference_reduce(32'sh80000000, 32'sh80000000, 32'sh80000000,
                         32'sh80000000, 1) !== 32'sh80000000)
      $fatal(1, "CLUSTER_REFERENCE_MAX_BOUNDARY");
    check_reduction(32'sh80000000, 32'sh80000000, 32'sh80000000, 32'sh80000000);
    check_reduction(32'sh7fffffff, 32'sh7fffffff, 32'sh7fffffff, 32'sh7fffffff);
    check_reduction(32'sh80000000, 32'sh7fffffff, -1, 0);
    check_reduction(-3, -1, 2, 1);
    for (integer n = 0; n < 64; n++)
      check_reduction(32'h80000000 ^ (n*32'h1f1f0101), n*32'h67123459,
                      ~(n*32'h3456789b), 32'h7fffffff ^ (n*32'h45674567));
    repeat (2) @(negedge clk);
    rst_n = 1;
    for (integer c = 0; c < 4; c++) begin
      for (integer phase = 0; phase < 2; phase++) begin
        load_data = 0;
        for (integer row = 0; row < 32; row++) begin
          dots[phase][c][row] = 0;
          for (integer lane = 0; lane < 8; lane++) begin
            load_data[(row*8+lane)*8+:8] = 8'(weight(c, row, lane, phase));
            if (enabled(c, row, lane, phase))
              dots[phase][c][row] += weight(c, row, lane, phase)*activation(c, lane, phase);
          end
        end
        load(c, 0, phase == 1 ? 31 : 0, load_data);
        load_data = 0;
        for (integer lane = 0; lane < 8; lane++)
          load_data[lane*8+:8] = 8'(activation(c, lane, phase));
        load(c, 1, phase == 1 ? 1023 : 0, load_data);
        load_data = 0;
        for (integer row = 0; row < 32; row++)
          for (integer lane = 0; lane < 8; lane++)
            load_data[row*8+lane] = enabled(c, row, lane, phase);
        load(c, 2, phase == 1 ? 31 : 0, load_data);
      end
    end
    for (integer n = 0; n < 16; n++) issue(n, 0, 0);
    @(negedge clk);
    cmd_valid = 0;
    repeat (20) begin
      @(negedge clk);
      if (cmd_ready) $fatal(1, "CLUSTER_FULL_QUEUE_ADMISSION");
    end
    target = accepted;
    require_full_rate = 1;
    ready_mode = 1;
    while (retired < target) @(negedge clk);
    require_full_rate = 0;
    ready_mode = 2;
    for (integer n = 0; n < 16; n++) issue(n, 1, 1);
    @(negedge clk);
    cmd_valid = 0;
    while (retired < accepted) @(negedge clk);
    ready_mode = 0;
    issue(0, 0, 0);
    issue(1, 0, 0);
    @(negedge clk);
    cmd_output = 0;
    cmd_accumulate = 1;
    cmd_reduce = 0;
    repeat (6) begin
      @(negedge clk);
      if (cmd_ready) $fatal(1, "CLUSTER_DUPLICATE_SLOT_ADMISSION");
    end
    ready_mode = 1;
    do @(posedge clk); while (!cmd_ready);
    @(negedge clk);
    cmd_valid = 0;
    while (retired < accepted) @(negedge clk);
    ready_mode = 0;
    for (integer n = 0; n < 4; n++) issue(n, 0, 0);
    @(negedge clk);
    cmd_valid = 0;
    wait (out_valid);
    repeat (3) @(negedge clk);
    rst_n = 0;
    repeat (2) @(negedge clk);
    rst_n = 1;
    ready_mode = 1;
    issue(3, 1, 0);
    @(negedge clk);
    cmd_valid = 0;
    while (retired < accepted) @(negedge clk);
    if (retired != 36 || held_cycles < 20) $fatal(1, "CLUSTER_TEST_COVERAGE");
    cmd_reduce = 3;
    #2;
    if (cmd_ready) $fatal(1, "CLUSTER_INVALID_REDUCTION_ADMISSION");
    $display("SRAM_CLUSTER_PASS outputs=%0d held_cycles=%0d", retired, held_cycles);
    $finish;
  end
  initial begin
    #5000000;
    $fatal(1, "CLUSTER_WATCHDOG");
  end
endmodule
