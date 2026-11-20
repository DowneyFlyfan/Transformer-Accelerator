`timescale 1ns/1ps
module tri_oracle_buffer_branch_truth_tb;
  logic value;
  wire [3:0] direct, buffered, twice_buffered;
  CKND12BWP12T40P140 driver0 (.I(value), .ZN(direct[0]));
  CKND16BWP12T40P140 driver1 (.I(value), .ZN(direct[1]));
  INVD15BWP12T40P140 driver2 (.I(value), .ZN(direct[2]));
  INVD18BWP12T40P140 driver3 (.I(value), .ZN(direct[3]));
  for (genvar index=0;index<4;index++) begin : checks
    BUFFD12BWP12T40P140 first (.I(direct[index]), .Z(buffered[index]));
    BUFFD12BWP12T40P140 second (.I(buffered[index]), .Z(twice_buffered[index]));
  end
  initial begin
    for (int row=0;row<4;row++) begin
      case (row)
        0: value=1'b0;
        1: value=1'b1;
        2: value=1'bx;
        3: value=1'bz;
      endcase
      #1;
      for (int driver=0;driver<4;driver++)
        if (direct[driver]===1'bz || direct[driver]!==buffered[driver] || direct[driver]!==twice_buffered[driver])
          $fatal(1,"Buffer mismatch row=%0d driver=%0d direct=%b after=%b cascade=%b",row,driver,direct[driver],buffered[driver],twice_buffered[driver]);
    end
    $display("TRI_ORACLE_BUFFER_BRANCH_TRUTH_PASS 4 16 2");
    $finish;
  end
endmodule
