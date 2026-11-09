`timescale 1ns/1ps
module tri_oracle_sram_gpu_capacity_tb;
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
  logic [2047:0] weights[32];
  logic [63:0] inputs[1024];
  logic [255:0] masks[32];
  logic [1023:0] expected[16];
  integer done_count = 0;
  string fixture;
  tri_oracle_sram_memory_compute dut (.*);

  always @(posedge clk) if (rst_n && done_valid) begin
    if (done_count >= 1024 || done_output !== 4'(done_count < 992 ? done_count % 16 : 3))
      $fatal(1, "GPU_CORE_COMPLETION_ORDER");
    done_count++;
  end
  task automatic load(input integer kind, address, input logic [2047:0] data);
    @(negedge clk);
    load_valid = 1;
    load_kind = 2'(kind);
    load_addr = 10'(address);
    load_data = data;
    @(posedge clk);
    #2;
    if (cmd_ready || load_error) $fatal(1, "GPU_CORE_LEGAL_LOAD");
    @(negedge clk);
    load_valid = 0;
  endtask
  initial begin
    if (!$value$plusargs("FIXTURE_DIR=%s", fixture))
      fixture = ".cache/model_reference/sram_capacity_gpu";
    $readmemh({fixture, "/weights.hex"}, weights);
    $readmemh({fixture, "/inputs.hex"}, inputs);
    $readmemh({fixture, "/masks.hex"}, masks);
    $readmemh({fixture, "/expected.hex"}, expected);
    if ($test$plusargs("CORRUPT_REFERENCE")) expected[0][0] = !expected[0][0];
    repeat (2) @(negedge clk);
    rst_n = 1;
    for (integer word = 0; word < 32; word++) begin
      load(0, word, weights[word]);
      load(2, word, {1792'b0, masks[word]});
    end
    for (integer word = 0; word < 1024; word++)
      load(1, word, {1984'b0, inputs[word]});
    for (integer command = 0; command < 1024; command++) begin
      @(negedge clk);
      cmd_valid = 1;
      cmd_weight = 5'(command*5+3);
      cmd_mask = 5'(command*13+7);
      cmd_activation = 10'(command);
      cmd_output = 4'(command < 992 ? command % 16 : 3);
      cmd_accumulate = command >= 16;
      @(posedge clk);
      if (!cmd_ready) $fatal(1, "GPU_CORE_ISSUE_THROUGHPUT");
    end
    @(negedge clk);
    cmd_valid = 0;
    repeat (16) @(negedge clk);
    if (done_count != 1024) $fatal(1, "GPU_CORE_COMPLETION_COUNT");
    for (integer slot = 0; slot < 16; slot++) begin
      @(negedge clk);
      read_valid = 1;
      read_output = 4'(slot);
      @(posedge clk);
      #2;
      if (!result_valid || result_data !== expected[slot])
        $fatal(1, "GPU_CORE_REFERENCE_MISMATCH slot=%0d", slot);
    end
    @(negedge clk);
    read_valid = 0;
    $display("GPU_CORE_CAPACITY_PASS commands=1024 sums=512 input_addresses=1024");
    $finish;
  end
  initial begin
    #1000000;
    $fatal(1, "GPU_CORE_WATCHDOG");
  end
endmodule
