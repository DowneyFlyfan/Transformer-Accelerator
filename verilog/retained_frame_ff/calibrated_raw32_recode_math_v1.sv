`timescale 1ns/1ps
// Private155-bit recode functions. Original package remains unchanged.
// Alignment/common-unit selection is supplied by the separate lane helper.
package calibrated_raw32_recode_math_v1;
  typedef raw32_residual_math_v1::recode_t recode_t;

  function automatic logic [154:0] magnitude_155(input logic signed [154:0] value);
    return value[154] ? (~$unsigned(value)+155'd1) : $unsigned(value);
  endfunction

  function automatic logic unit_fits_155(input logic [154:0] peak,
                                     input integer common_unit, unit);
    integer delta;
    logic [154:0] upper, low_mask;
    delta = unit-common_unit;
    if(delta < 0) return peak <= (155'd2147483647 >> (-delta));
    if(delta >= 155) return 1'b1;
    upper = peak >> delta;
    low_mask = (155'd1 << delta)-155'd1;
    // Equality requires zero sticky tail: all-ones upper bits plus a tiny
    // nonzero tail must select the next unit rather than clip on rounding.
    return upper < 155'd2147483647 ||
      (upper == 155'd2147483647 && (peak & low_mask) == 0);
  endfunction

  function automatic recode_t recode_once_155(input logic signed [154:0] value,
                                          input integer common_unit, unit);
    recode_t answer;
    logic [154:0] absolute_value, rounded;
    logic left_overflow;
    integer delta;
    absolute_value=magnitude_155(value);delta=unit-common_unit;rounded=0;left_overflow=0;
    if(delta > 0)begin
      if(delta < 155)rounded=absolute_value >> delta;
      if(delta <= 155 && absolute_value[delta-1])rounded=rounded+155'd1;
    end else if(delta == 0)rounded=absolute_value;
    else if(-delta < 155)begin
      left_overflow=absolute_value > (155'd2147483647 >> (-delta));
      rounded=absolute_value << (-delta);
    end
    answer.bad=(unit < -32 || unit > 97 || rounded > 155'd2147483647 ||
                left_overflow || (delta <= -155 && absolute_value != 0));
    answer.code=value[154] ? -$signed(rounded[31:0]) : $signed(rounded[31:0]);
    return answer;
  endfunction
endpackage
