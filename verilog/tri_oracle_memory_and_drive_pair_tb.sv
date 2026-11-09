`timescale 1ns / 1ps
// Native two-state, zero-delay proof for the additional AND drive pair.
module tri_oracle_memory_and_drive_pair_tb ();
  localparam int unsigned PATTERN_COUNT = 4;
  localparam time STEP = 1ns;
  logic [1:0] inputs;
  logic original_value, replacement_value;
  logic expected_value;

`ifdef TRI_MEMORY_AND_BOTH_WRONG
  CKND2D1BWP12T40P140 original_cell (
      .A1(inputs[0]),
      .A2(inputs[1]),
      .ZN(original_value)
  );
`else
  AN2D1BWP12T40P140 original_cell (
      .A1(inputs[0]),
      .A2(inputs[1]),
      .Z (original_value)
  );
`endif
`ifdef TRI_MEMORY_AND_WRONG_NEW
  CKND2D2BWP12T40P140 replacement_cell (
      .A1(inputs[0]),
      .A2(inputs[1]),
      .ZN(replacement_value)
  );
`elsif TRI_MEMORY_AND_BOTH_WRONG
  CKND2D2BWP12T40P140 replacement_cell (
      .A1(inputs[0]),
      .A2(inputs[1]),
      .ZN(replacement_value)
  );
`else
  AN2D2BWP12T40P140 replacement_cell (
      .A1(inputs[0]),
      .A2(inputs[1]),
      .Z (replacement_value)
  );
`endif

  initial begin
    for (int unsigned pattern = 0; pattern < PATTERN_COUNT; pattern++) begin
      inputs = 2'(pattern);
      expected_value = ((pattern & 1) != 0) && ((pattern & 2) != 0);
      #STEP;
      if (original_value !== expected_value || replacement_value !== expected_value) begin
        $fatal(1, "AND_DRIVE_PAIR_MISMATCH pattern=%0d old=%b new=%b expected=%b", pattern,
               original_value, replacement_value, expected_value);
      end
    end
    $display("MEMORY_AND_DRIVE_PAIR_PASS patterns=4 native_outputs=8");
    $finish;
  end

  initial begin
    #100ns;
    $fatal(1, "AND_DRIVE_PAIR_TIMEOUT");
  end
endmodule
