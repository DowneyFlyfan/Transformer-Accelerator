`timescale 1ps/1ps
module tri_oracle_weight_double_clock_tb;
  localparam time ReadSetup = 80ps;
  time half_period = 431ps;
  logic clk = 0;
  logic ceb = 1, web = 1;
  logic [4:0] address = '0;
  logic [127:0] data = '0, bit_mask = '1, q;
  logic [127:0] expected [32];
  logic [127:0] prior_read;
  bit occupied = 0;
  time last_operation;
  int distinct_pairs = 0, same_pairs = 0, reads = 0, held_reads = 0;

  initial begin
    int half_period_ps;
    if ($value$plusargs("HALF_PERIOD_PS=%d", half_period_ps))
      half_period = half_period_ps * 1ps;
    if (half_period <= ReadSetup) $fatal(1, "WEIGHT_DOUBLE_CLOCK_PERIOD_ARGUMENT");
    forever #(half_period) clk = !clk;
  end

  TS5N28HPCPSVTA32X128M2FW memory (
    .CLK(clk), .CEB(ceb), .WEB(web), .A(address), .D(data), .BWEB(bit_mask), .Q(q)
  );

  task automatic initial_write(input int word);
    @(negedge clk);
    ceb = 0;
    web = 0;
    address = 5'(word);
    data = 128'h3c791e32_060bf5af_67e4371e_960ba71c ^ (128'(word) * 128'h0001f45d);
    bit_mask = '0;
    @(posedge clk);
    expected[word] = data;
  endtask

  task automatic check_continuity;
    // Every subcycle of the read/write burst has an active clock edge.
    if (occupied && $time - last_operation != 2 * half_period)
      $fatal(1, "WEIGHT_DOUBLE_CLOCK_IDLE_IN_PAIR");
    last_operation = $time;
    occupied = 1;
  endtask

  task automatic sample_after_prior_write;
    if (occupied) begin
      if (q !== prior_read) $fatal(1, "WEIGHT_DOUBLE_CLOCK_WRITE_CHANGED_READ_DATA");
      held_reads++;
    end
  endtask

  task automatic pair_access(input int read_address, input int write_address,
                             input logic [127:0] inhibit);
    @(negedge clk);
    web = 1;
    address = 5'(read_address);
    #(half_period - ReadSetup);
    sample_after_prior_write();
    @(posedge clk);
    check_continuity();
    @(negedge clk);
    web = 0;
    address = 5'(write_address);
    data = ~expected[write_address];
    bit_mask = inhibit;
    #(half_period - ReadSetup);
    prior_read = expected[read_address];
    if (q !== prior_read)
      $fatal(1, "WEIGHT_DOUBLE_CLOCK_READ_MISMATCH read=%0d write=%0d",
             read_address, write_address);
    reads++;
    @(posedge clk);
    check_continuity();
    expected[write_address] = (expected[write_address] & inhibit) | (data & ~inhibit);
    if (read_address == write_address) same_pairs++;
    else distinct_pairs++;
  endtask

  initial begin
    repeat (3) @(negedge clk);
    for (int word = 0; word < 32; word++) initial_write(word);
    for (int offset = 1; offset < 32; offset++)
      for (int word = 0; word < 32; word++)
        pair_access(word, (word + offset) % 32, ~(128'h0000ff << ((word + offset) % 16)*8));
    for (int word = 0; word < 32; word++)
      pair_access(word, word, ~(128'h000055 << (word % 16)*8));

    @(negedge clk);
    web = 1;
    address = 0;
    #(half_period - ReadSetup);
    sample_after_prior_write();
    for (int word = 0; word < 32; word++) begin
      @(negedge clk);
      if (q !== expected[word]) $fatal(1, "WEIGHT_DOUBLE_CLOCK_WRITEBACK word=%0d", word);
      reads++;
      address = 5'(word + 1);
    end
    if (distinct_pairs != 992 || same_pairs != 32 || reads != 1056 || held_reads != 1024)
      $fatal(1, "WEIGHT_DOUBLE_CLOCK_COUNTS");
    $display("WEIGHT_DOUBLE_CLOCK_PASS period_ps=%0d reads=%0d held=%0d",
             int'(2 * half_period / 1ps), reads, held_reads);
    $display("WEIGHT_DOUBLE_CLOCK_PAIRS distinct=%0d same=%0d", distinct_pairs, same_pairs);
    $finish;
  end

  initial begin
    #10us;
    $fatal(1, "WEIGHT_DOUBLE_CLOCK_TIMEOUT");
  end
endmodule
