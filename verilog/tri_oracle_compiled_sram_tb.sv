`timescale 1ns / 1ps
// Functional checks use the unmodified compiler model's documented UNIT_DELAY mode.
module tri_oracle_compiled_sram_tb ();
  localparam int unsigned WORD_COUNT = 512;
  localparam int unsigned DATA_WIDTH = 40;
  logic clk = 0;
  logic ceb = 1, web = 1;
  logic [8:0] address = 0, macro_address;
  logic [DATA_WIDTH-1:0] data = 0, bit_mask = '1, macro_bit_mask;
  logic macro_ceb;
  wire [DATA_WIDTH-1:0] q;
  logic [DATA_WIDTH-1:0] golden[WORD_COUNT];
  logic [DATA_WIDTH-1:0] held_q, new_data;
  int unsigned read_checks = 0;
  int unsigned hold_checks = 0;

  always #5ns clk = ~clk;
  always_comb begin
    macro_address = address;
    macro_bit_mask = bit_mask;
    macro_ceb = ceb;
`ifdef TRI_SRAM_WRONG_ADDRESS
    macro_address[8] = 0;
`endif
`ifdef TRI_SRAM_WRONG_BIT_MASK
    macro_bit_mask = ~bit_mask;
`endif
`ifdef TRI_SRAM_WRONG_ENABLE
    macro_ceb = ~ceb;
`endif
  end

  TS5N28HPCPSVTA512X40M4FW memory (
      .CLK(clk),
      .CEB(macro_ceb),
      .WEB(web),
      .A(macro_address),
      .D(data),
      .BWEB(macro_bit_mask),
      .Q(q)
  );

  function automatic logic [DATA_WIDTH-1:0] pattern(input int unsigned index);
    return 40'h935ea61bc7 ^ (40'(index) * 40'h0102040811);
  endfunction

  task automatic cycle(input bit disabled, input bit reading, input int unsigned index,
                       input logic [DATA_WIDTH-1:0] value, mask);
    @(negedge clk);
    ceb = disabled;
    web = reading;
    address = 9'(index);
    data = value;
    bit_mask = mask;
    @(posedge clk);
    #1ns;
  endtask

  task automatic check_read(input int unsigned index);
    cycle(0, 1, index, 0, '1);
    if (q !== golden[index])
      $fatal(1, "COMPILED_SRAM_MISMATCH address=%0d got=%h expected=%h", index, q, golden[index]);
    read_checks++;
  endtask

  initial begin
    // Fill the entire array before reading; no reset or initialization is assumed.
    for (int unsigned index = 0; index < WORD_COUNT; index++) begin
      golden[index] = pattern(index);
      cycle(0, 0, index, golden[index], '0);
    end
    for (int unsigned index = 0; index < WORD_COUNT; index++) check_read(index);

    // Mask polarity and preserved bits are checked against the software scoreboard.
    for (int unsigned index = 0; index < WORD_COUNT; index++) begin
      new_data = ~pattern(index);
      golden[index] = (golden[index] & 40'haaaaaaaaaa) | (new_data & 40'h5555555555);
      cycle(0, 0, index, new_data, 40'haaaaaaaaaa);
    end
    for (int unsigned index = 0; index < WORD_COUNT; index++) check_read(index);

    // Exercise every individual bit enable, including bit39 at address511.
    for (int unsigned bit_index = 0; bit_index < DATA_WIDTH; bit_index++) begin
      new_data = ~golden[WORD_COUNT-1];
      cycle(0, 0, WORD_COUNT - 1, new_data, ~(40'b1 << bit_index));
      golden[WORD_COUNT-1][bit_index] = new_data[bit_index];
      check_read(WORD_COUNT - 1);
    end

    check_read(1);
    held_q = q;
    for (int unsigned index = 0; index < WORD_COUNT; index++) begin
      cycle(1, 0, index, ~golden[index], '0);
      if (q !== held_q) $fatal(1, "COMPILED_SRAM_DISABLED_OUTPUT_CHANGED address=%0d", index);
      hold_checks++;
    end
    for (int unsigned index = 0; index < WORD_COUNT; index++) check_read(index);
    cycle(0, 0, WORD_COUNT - 1, ~golden[WORD_COUNT-1], '1);
    check_read(WORD_COUNT - 1);
    $display("COMPILED_SRAM_PASS read_checks=%0d disabled_hold_checks=%0d", read_checks,
             hold_checks);
    $finish;
  end

  initial begin
    #100us;
    $fatal(1, "COMPILED_SRAM_TIMEOUT");
  end
endmodule
