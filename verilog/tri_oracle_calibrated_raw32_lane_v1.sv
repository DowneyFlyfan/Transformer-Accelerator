`timescale 1ns/1ps

// Isolated source candidate: exact alignment, with no rounding or storage.
// The complete three-bit decrement domain needs this signed155-bit path.
module tri_oracle_calibrated_raw32_lane_v1 (
  input logic signed [31:0] raw_value,
  input logic signed [31:0] down_value,
  input logic signed [7:0] raw_unit,
  input logic signed [11:0] base_down_unit,
  input logic [2:0] maximum_decrement,
  input logic [2:0] lane_decrement,
  input logic correction_enable,
  output logic bad,
  output logic signed [8:0] common_unit,
  output logic signed [11:0] lane_unit,
  output logic signed [154:0] exact_sum,
  output logic [154:0] magnitude
);
  integer raw_unit_value, base_unit_value;
  integer maximum_decrement_value, lane_decrement_value;
  integer common_value, lane_value, raw_shift, down_shift, down_bound;
  logic signed [154:0] raw_extended, down_extended, sum_value;

  function automatic logic supported_base(input logic signed [11:0] unit);
    case (unit)
      -12'sd19, -12'sd17, -12'sd16, -12'sd15, -12'sd14,
      -12'sd13, -12'sd12, -12'sd11, -12'sd8, -12'sd6:
        return 1'b1;
      default: return 1'b0;
    endcase
  endfunction

  always_comb begin
    // Every failure, including an unknown unused-looking input, is known bad.
    bad = 1'b1;
    common_unit = '0;
    lane_unit = '0;
    exact_sum = '0;
    magnitude = '0;
    raw_unit_value = 0;
    base_unit_value = 0;
    maximum_decrement_value = 0;
    lane_decrement_value = 0;
    common_value = 0;
    lane_value = 0;
    raw_shift = 0;
    down_shift = 0;
    down_bound = 0;
    raw_extended = '0;
    down_extended = '0;
    sum_value = '0;

    if (!$isunknown({raw_value, down_value, raw_unit, base_down_unit,
                     maximum_decrement, lane_decrement, correction_enable})) begin
      raw_unit_value = $signed(raw_unit);
      base_unit_value = $signed(base_down_unit);
      // Explicit zero extension prevents decrements4..7 becoming negative.
      maximum_decrement_value = {29'd0, maximum_decrement};
      lane_decrement_value = {29'd0, lane_decrement};
      down_bound = correction_enable ? 184549376 : 92274688;

      if (raw_value != 32'sh80000000 &&
          raw_unit_value >= -32 && raw_unit_value <= 97 &&
          supported_base(base_down_unit) &&
          lane_decrement_value <= maximum_decrement_value &&
          $signed(down_value) >= -down_bound &&
          $signed(down_value) <= down_bound) begin
        lane_value = base_unit_value - lane_decrement_value;
        common_value = raw_unit_value < base_unit_value - maximum_decrement_value ?
          raw_unit_value : base_unit_value - maximum_decrement_value;
        raw_shift = raw_unit_value - common_value;
        down_shift = lane_value - common_value;

        // Both operands and the addition remain signed155 bits throughout.
        raw_extended = {{123{raw_value[31]}}, raw_value};
        down_extended = {{123{down_value[31]}}, down_value};
        sum_value = (raw_extended <<< raw_shift) +
                    (down_extended <<< down_shift);
        common_unit = common_value[8:0];
        lane_unit = lane_value[11:0];
        exact_sum = sum_value;
        magnitude = sum_value[154] ?
          (~$unsigned(sum_value) + 155'd1) : $unsigned(sum_value);
        bad = 1'b0;
      end
    end
  end
endmodule
