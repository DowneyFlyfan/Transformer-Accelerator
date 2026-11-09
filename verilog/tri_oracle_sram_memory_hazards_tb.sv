`timescale 1ns/1ps
// Independent command/completion scoreboard; no private implementation signals.
module tri_oracle_memory_compute_tb;
  logic clk = 0;
  always #5 clk = ~clk;
  logic rst_n = 0, load_valid = 0, cmd_valid = 0, cmd_accumulate = 0, read_valid = 0;
  logic [1:0] load_kind = 0;
  logic [9:0] load_addr = 0, cmd_activation = 0;
  logic [2047:0] load_data = 0;
  logic [31:0] load_row_enable = '1;
  logic [4:0] cmd_weight = 0, cmd_mask = 0;
  logic [3:0] cmd_output = 0, read_output = 0;
  logic cmd_ready, load_error, done_valid, result_valid;
  logic [3:0] done_output;
  logic [1023:0] result_data;
  integer expected[16][32];
  integer queued_slot[512], queued_dot[512][32];
  logic queued_acc[512];
  integer issued = 0, completed = 0, reads = 0, row, n, slot;
  integer read_expected[32];
  integer low_weight[32];
  logic [1023:0] last_response = 0;
  logic [15:0] initialized = 0;
  tri_oracle_memory_compute dut (.*);

  always @(posedge clk) begin
    if (rst_n) begin
      if (load_valid && load_kind == 0 && load_addr == 0)
        for (integer r = 0; r < 32; r++)
          if (load_row_enable[r]) low_weight[r] = int'($signed(load_data[r*64+:8]));
      if (cmd_valid && cmd_ready) begin
        queued_slot[issued] = int'(cmd_output);
        queued_acc[issued] = cmd_accumulate;
        for (integer r = 0; r < 32; r++)
          queued_dot[issued][r] = cmd_weight == 31 ? -12 : 8*low_weight[r];
        issued++;
      end
      if (read_valid && initialized[read_output]) begin
        for (integer r = 0; r < 32; r++) read_expected[r] = expected[read_output][r];
      end
      #2;
      if (read_valid && initialized[read_output]) begin
        if (!result_valid) $fatal(1, "CORE_READ_LATENCY");
        for (integer r = 0; r < 32; r++)
          if ($signed(result_data[r*32+:32]) !== read_expected[r])
            $fatal(1, "CORE_READ_OLD_OR_FORWARD row=%0d got=%0d expected=%0d", r,
                   $signed(result_data[r*32+:32]), read_expected[r]);
        reads++;
        last_response = result_data;
      end else if (!read_valid) begin
        if (result_valid || result_data !== last_response) $fatal(1, "CORE_RESPONSE_HOLD");
      end
      // A completed write updates the model after checking this edge's old-data read.
      if (done_valid) begin
        if (completed >= issued || done_output !== 4'(queued_slot[completed]))
          $fatal(1, "CORE_COMPLETION_ORDER");
        for (integer r = 0; r < 32; r++) begin
          if (queued_acc[completed])
            expected[done_output][r] += queued_dot[completed][r];
          else expected[done_output][r] = queued_dot[completed][r];
        end
        initialized[done_output] = 1;
        completed++;
      end
    end else begin
      issued = completed;
      last_response = 0;
      #2;
      if (done_valid || result_valid || result_data !== 0) $fatal(1, "CORE_RESET_FLUSH");
    end
  end

  task automatic load(input logic [1:0] kind, input logic [9:0] address,
                      input logic [2047:0] data);
    @(negedge clk);
    load_valid = 1;
    load_kind = kind;
    load_addr = address;
    load_data = data;
    @(posedge clk);
    #2;
    if (cmd_ready || load_error) $fatal(1, "CORE_LEGAL_LOAD");
    @(negedge clk);
    load_valid = 0;
  endtask

  task automatic drain;
    for (integer t = 0; t < 40 && completed < issued; t++) @(negedge clk);
    if (completed != issued) $fatal(1, "CORE_DRAIN_TIMEOUT");
  endtask

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    load(0, 0, {256{8'd2}});
    load_row_enable = 32'h55555555;
    load(0, 0, {256{8'd4}});
    load_row_enable = '1;
    load(0, 31, {256{8'd3}});
    load(1, 0, {1984'b0, {8{8'd1}}});
    load(1, 1023, {1984'b0, {8{8'hff}}});
    load(2, 0, {1792'b0, {256{1'b1}}});
    load_data = 0;
    for (row = 0; row < 32; row++)
      for (integer lane = 0; lane < 8; lane++) load_data[row*8+lane] = lane % 2 == 0;
    load(2, 31, load_data);
    for (n = 0; n < 16; n++) begin
      @(negedge clk);
      cmd_valid = 1;
      cmd_output = 4'(n);
      @(posedge clk);
      if (!cmd_ready) $fatal(1, "CORE_INITIAL_THROUGHPUT");
    end
    @(negedge clk);
    cmd_valid = 0;
    drain();
    // Force a forwarding chain independently of arbitrary external-read stalls.
    for (n = 0; n < 16; n++) begin
      @(negedge clk);
      cmd_valid = 1;
      cmd_output = 0;
      cmd_accumulate = 1;
      @(posedge clk);
      if (!cmd_ready) $fatal(1, "CORE_ACCUMULATION_THROUGHPUT");
    end
    @(negedge clk);
    cmd_valid = 0;
    drain();
    @(negedge clk);
    read_valid = 1;
    read_output = 0;
    @(negedge clk);
    read_valid = 0;
    for (n = 0; n < 128; n++) begin
      @(negedge clk);
      cmd_valid = 1;
      cmd_accumulate = 1;
      cmd_output = n < 32 ? 0 : 4'(n*5);
      cmd_weight = n % 3 == 0 ? 31 : 0;
      cmd_activation = n % 3 == 0 ? 1023 : 0;
      cmd_mask = n % 3 == 0 ? 31 : 0;
      read_valid = n % 5 != 0;
      read_output = 4'(n*7);
      load_valid = n % 11 == 3;
      load_kind = 0;
      load_addr = 0;
      load_data = n % 2 == 0 ? {256{8'd5}} : {256{8'd6}};
      load_row_enable = 32'hcccc3333;
    end
    // Cluster-style reads follow the most recent completion. They must not
    // reduce steady-state issue throughput after the prior arbitrary reads drain.
    for (n = 0; n < 64; n++) begin
      @(negedge clk);
      load_valid = 0;
      cmd_output = 4'(n);
      read_valid = done_valid;
      read_output = done_output;
      @(posedge clk);
      if (n >= 16 && !cmd_ready) $fatal(1, "CORE_COMPLETION_READ_THROUGHPUT");
    end
    @(negedge clk);
    cmd_valid = 0;
    read_valid = 0;
    drain();
    // Flush an occupied pipeline. The model retains only writes whose public
    // completion occurred before reset, independent of implementation latency.
    for (n = 0; n < 8; n++) begin
      @(negedge clk);
      cmd_valid = 1;
      cmd_output = 4'(n);
    end
    @(negedge clk);
    rst_n = 0;
    cmd_valid = 0;
    repeat (2) @(negedge clk);
    rst_n = 1;
    for (slot = 0; slot < 16; slot++) begin
      @(negedge clk);
      read_valid = 1;
      read_output = 4'(slot);
    end
    @(negedge clk);
    read_valid = 0;
    if (issued < 100 || reads < 100) $fatal(1, "CORE_SCOREBOARD_COVERAGE");
    $display("PASS: masked writes, arbitrary concurrent reads, old-data collisions, forwarding,");
    $display("PASS: completion-read throughput and reset retention issued=%0d reads=%0d", issued,
             reads);
    $finish;
  end
  initial begin
    #100000;
    $fatal(1, "CORE_WATCHDOG");
  end
endmodule
