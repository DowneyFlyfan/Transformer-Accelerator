`timescale 1ns/1ps
// Compare a reduced guard to the original row-wise, 65-bit calculation.
module tri_oracle_row_address_guard_tb;
  parameter int ROWS = 160;
  localparam int COUNT_BITS = $clog2(ROWS + 1);
  logic [COUNT_BITS-1:0] count;
  logic [ROWS*16-1:0] channels;
  logic [9:0] features;
  logic [63:0] base;
  logic overflow;
  int checks = 0;
  int seed = 32'h2975cb16;
  logic [63:0] span;
  tri_oracle_row_address_guard #(.ROWS(ROWS)) dut (
      .in_count(count), .in_channels(channels), .in_features(features),
      .in_weight_base(base), .out_overflow(overflow));

  task automatic check;
    logic expected, independent;
    logic [64:0] input_bytes, row_end;
    logic [63:0] row_bytes;
    begin
      expected = 0;
      independent = 0;
      input_bytes = 65'(features) << 3;
      for (int row = 0; row < ROWS; row++) begin
        row_end = {1'b0, base} + (65'(channels[row*16+:16]) + 1) * input_bytes - 1;
        if (row < int'(count)) begin
          if (row_end > 65'h0ffffffffffffffff) expected = 1;
          // Independently use the distance from the end of the address space.
          row_bytes = (64'(channels[row*16+:16]) + 1) * (64'(features) * 8);
          if (row_bytes == 0) begin
            if (base == 0) independent = 1;
          end else if ((row_bytes - 1) > (~base)) independent = 1;
        end
      end
      #1;
      if (overflow !== expected || expected !== independent)
        $fatal(1, "ROW_GUARD_MISMATCH rows=%0d count=%0d features=%0d base=%h got=%b expected=%b independent=%b check=%0d",
               ROWS, count, features, base, overflow, expected, independent, checks);
      checks++;
    end
  endtask

  initial begin
    // Every representable count, including out-of-range packet counts; the
    // inactive high identifiers deliberately exceed every active identifier.
    for (int n = 0; n < (1 << COUNT_BITS); n++) begin
      count = COUNT_BITS'(n);
      for (int row = 0; row < ROWS; row++)
        channels[row*16+:16] = row < n ? 16'(row + 3) : 16'hffff;
      for (int f = 0; f < 5; f++) begin
        case (f)
          0: features = 0;
          1: features = 1;
          2: features = 512;
          3: features = 513;
          4: features = 1023;
        endcase
        base = 0; check();
        base = 1; check();
        base = 64'hffffffffffffffff; check();
        if (n > 0) begin
          span = (64'(n < ROWS ? n + 2 : ROWS + 2) + 1) * (64'(features) * 8);
          if (span > 1) begin
            base = 64'hffffffffffffffff - (span - 1); check();
            base = base + 1; check();
            base = base - 2; check();
          end
        end
      end
    end
    // All ten-bit feature values and extreme IDs in first, middle, last rows.
    count = COUNT_BITS'(ROWS);
    for (int f = 0; f < 1024; f++) begin
      features = 10'(f);
      for (int position = 0; position < 3; position++) begin
        channels = '0;
        case (position)
          0: channels[0+:16] = 16'hffff;
          1: channels[(ROWS/2)*16+:16] = 16'hffff;
          2: channels[(ROWS-1)*16+:16] = 16'hffff;
        endcase
        span = 64'd65536 * (64'(features) * 8);
        base = 64'hffffffffffffffff - span; check();
        base = base + 1; check();
        base = base + 1; check();
      end
    end
    // Random full-width IDs with near-overflow and arbitrary bases.
    for (int sample = 0; sample < 10000; sample++) begin
      count = COUNT_BITS'($random(seed));
      features = 10'($random(seed));
      for (int row = 0; row < ROWS; row++) channels[row*16+:16] = 16'($random(seed));
      if (sample % 2) base = 64'hffffffffffffffff - (64'($unsigned($random(seed))) & 64'h3fffffff);
      else base = {$random(seed), $random(seed)};
      check();
    end
    $display("ROW_GUARD_PASS rows=%0d checks=%0d", ROWS, checks);
    $finish;
  end
endmodule
