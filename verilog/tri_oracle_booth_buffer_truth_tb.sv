`timescale 1ns/1ps

module tri_oracle_booth_buffer_truth_tb;
  localparam int DriverCount = 8;
  logic left, right;
  wire [DriverCount-1:0] direct, buffered, twice_buffered;

  AN2D4BWP12T40P140 driver0 (.A1(left), .A2(right), .Z(direct[0]));
  BUFFD4BWP12T40P140 driver1 (.I(left), .Z(direct[1]));
  CKAN2D8BWP12T40P140 driver2 (.A1(left), .A2(right), .Z(direct[2]));
  CKND12BWP12T40P140 driver3 (.I(left), .ZN(direct[3]));
  CKND16BWP12T40P140 driver4 (.I(left), .ZN(direct[4]));
  INVD6BWP12T40P140 driver5 (.I(left), .ZN(direct[5]));
  INVD8BWP12T40P140 driver6 (.I(left), .ZN(direct[6]));
  OR2D4BWP12T40P140 driver7 (.A1(left), .A2(right), .Z(direct[7]));

  for (genvar index = 0; index < DriverCount; index++) begin : check_driver
    BUFFD8BWP12T40P140 first_buffer (.I(direct[index]), .Z(buffered[index]));
    BUFFD8BWP12T40P140 second_buffer (.I(buffered[index]), .Z(twice_buffered[index]));
  end

  function automatic logic input_value(input int index);
    case (index)
      0: return 1'b0;
      1: return 1'b1;
      2: return 1'bx;
      3: return 1'bz;
      default: $fatal(1, "Invalid four-state index");
    endcase
  endfunction

  initial begin
    for (int row = 0; row < 16; row++) begin
      left = input_value(row / 4);
      right = input_value(row % 4);
      #1;
      for (int driver = 0; driver < DriverCount; driver++) begin
        if (direct[driver] === 1'bz || direct[driver] !== buffered[driver] ||
            direct[driver] !== twice_buffered[driver])
          $fatal(1, "Buffer mismatch row=%0d driver=%0d direct=%b after=%b cascade=%b",
                 row, driver, direct[driver], buffered[driver], twice_buffered[driver]);
      end
    end
    $display("BOOTH_BUFFER_TRUTH_PASS %0d %0d 2", DriverCount, DriverCount * 16);
    $finish;
  end
endmodule
