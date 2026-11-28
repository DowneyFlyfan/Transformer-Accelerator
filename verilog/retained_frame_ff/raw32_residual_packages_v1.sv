`timescale 1ns/1ps
// Complete source candidate. Native simulation and independent review are pending.
// One saved packet, two line registers, exact 148-bit datapath; no row array.
package raw32_residual_math_v1;
  typedef struct packed {logic bad; logic signed [31:0] code;} recode_t;
  function automatic logic signed [147:0] exact_sum(
      input logic signed [31:0] raw_code, down_code,
      input integer raw_unit, down_unit);
    logic signed [147:0] raw_extended, down_extended;
    integer common_unit;
    common_unit = raw_unit < down_unit ? raw_unit : down_unit;
    raw_extended = {{116{raw_code[31]}},raw_code};
    down_extended = {{116{down_code[31]}},down_code};
    return (raw_extended <<< (raw_unit-common_unit)) +
           (down_extended <<< (down_unit-common_unit));
  endfunction
  function automatic logic [147:0] magnitude(input logic signed [147:0] value);
    return value[147] ? (~$unsigned(value)+148'd1) : $unsigned(value);
  endfunction
  function automatic logic unit_fits(input logic [147:0] peak,
                                     input integer common_unit, unit);
    integer delta;
    logic [147:0] upper, low_mask;
    delta = unit-common_unit;
    if(delta < 0) return peak <= (148'd2147483647 >> (-delta));
    if(delta >= 148) return 1'b1;
    upper = peak >> delta;
    low_mask = (148'd1 << delta)-148'd1;
    // Equality requires zero sticky tail: all-ones upper bits plus a tiny
    // nonzero tail must select the next unit rather than clip on rounding.
    return upper < 148'd2147483647 ||
      (upper == 148'd2147483647 && (peak & low_mask) == 0);
  endfunction
  function automatic logic signed [8:0] choose_unit(
      input logic [147:0] peak,input integer common_unit);
    logic found;
    logic signed [8:0] answer;
    answer=9'sd128;found=0;
    if(peak == 0) return 9'sd0;
    for(integer unit=-32;unit<=97;unit++)
      if(!found && unit_fits(peak,common_unit,unit))begin
        answer=9'(unit);found=1;
      end
    return answer;
  endfunction
  function automatic recode_t recode_once(input logic signed [147:0] value,
                                          input integer common_unit, unit);
    recode_t answer;
    logic [147:0] absolute_value, rounded;
    logic left_overflow;
    integer delta;
    absolute_value=magnitude(value);delta=unit-common_unit;rounded=0;left_overflow=0;
    if(delta > 0)begin
      if(delta < 148)rounded=absolute_value >> delta;
      if(delta <= 148 && absolute_value[delta-1])rounded=rounded+148'd1;
    end else if(delta == 0)rounded=absolute_value;
    else if(-delta < 148)begin
      left_overflow=absolute_value > (148'd2147483647 >> (-delta));
      rounded=absolute_value << (-delta);
    end
    answer.bad=(unit < -32 || unit > 97 || rounded > 148'd2147483647 ||
                left_overflow || (delta <= -148 && absolute_value != 0));
    answer.code=value[147] ? -$signed(rounded[31:0]) : $signed(rounded[31:0]);
    return answer;
  endfunction
  function automatic logic [63:0] physical_epsilon(input logic signed [7:0] unit);
    case(unit)
      -32:return 64'd12089258196146291747;
      -31:return 64'd3022314549036572937;
      -30:return 64'd755578637259143234;
      -29:return 64'd188894659314785809;
      -28:return 64'd47223664828696452;
      -27:return 64'd11805916207174113;
      -26:return 64'd2951479051793528;
      -25:return 64'd737869762948382;
      -24:return 64'd184467440737096;
      -23:return 64'd46116860184274;
      -22:return 64'd11529215046068;
      -21:return 64'd2882303761517;
      -20:return 64'd720575940379;
      -19:return 64'd180143985095;
      -18:return 64'd45035996274;
      -17:return 64'd11258999068;
      -16:return 64'd2814749767;
      -15:return 64'd703687442;
      -14:return 64'd175921860;
      -13:return 64'd43980465;
      -12:return 64'd10995116;
      -11:return 64'd2748779;
      -10:return 64'd687195;
      -9:return 64'd171799;
      -8:return 64'd42950;
      -7:return 64'd10737;
      -6:return 64'd2684;
      -5:return 64'd671;
      -4:return 64'd168;
      -3:return 64'd42;
      -2:return 64'd10;
      -1:return 64'd3;
      0:return 64'd1;
      default:return 64'd0;
    endcase
  endfunction
endpackage

package raw32_residual_commit_types_v1;
  typedef struct packed {
    logic [31:0] source_tag;
    logic [4:0] source_layer;
    logic [15:0] source_epoch;
    logic [9:0] original_root,source_rank,kept_rank,image_start,input_count,kept_count;
    logic [127:0] bundle;
    logic [1:0] phase,normalization_role;
    logic signed [7:0] raw_unit;
    logic [63:0] epsilon;
    logic signed [11:0] down_unit;
    logic [63:0] raw_base,raw_bytes,metadata_base,metadata_bytes,down_table_base;
    logic [63:0] down_scratch_base,down_scratch_bytes;
    logic [63:0] target_raw_base,target_raw_bytes,target_metadata_base,target_metadata_bytes;
    logic [63:0] target_gamma_base,target_gamma_bytes;
    logic signed [7:0] target_gamma_exponent;
    logic [4:0] target_layer;
    logic [15:0] target_epoch;
    logic [31:0] target_tag_base;
    logic [9:0] target_count;
    logic [1:0] target_role;
    logic [9:0] target_rank;
    logic [63:0] gamma_table_base,gamma_table_bytes;
    logic [5:0] target_gamma_index;
    logic [4:0] protected_count;
    logic [15:0][63:0] protected_base,protected_bytes;
    logic signed [8:0] activation_unit,gate_weight_unit,up_weight_unit,down_weight_unit;
    logic signed [8:0] gain_cap,down_offset,gain;
    logic [5:0] gate_shift,up_shift,down_shift;
  } job_t;
endpackage

package raw32_residual_bindings_v1;
  // These source constants are generated from the independently accepted,
  // checkpoint-bound small metadata. No trained numerical payload is embedded.
  function automatic integer bound_weight_unit(input integer layer,role);
    case(layer*3+role)
      0:return -8;
      1:return -9;
      2:return -7;
      3:return -8;
      4:return -8;
      5:return -7;
      6:return -6;
      7:return -8;
      8:return -7;
      9:return -8;
      10:return -8;
      11:return -7;
      12:return -8;
      13:return -8;
      14:return -7;
      15:return -7;
      16:return -8;
      17:return -7;
      18:return -8;
      19:return -8;
      20:return -7;
      21:return -8;
      22:return -8;
      23:return -6;
      24:return -7;
      25:return -8;
      26:return -7;
      27:return -7;
      28:return -8;
      29:return -8;
      30:return -8;
      31:return -8;
      32:return -7;
      33:return -7;
      34:return -9;
      35:return -7;
      36:return -7;
      37:return -8;
      38:return -7;
      39:return -7;
      40:return -8;
      41:return -7;
      42:return -7;
      43:return -8;
      44:return -7;
      45:return -8;
      46:return -8;
      47:return -7;
      48:return -7;
      49:return -8;
      50:return -7;
      51:return -8;
      52:return -8;
      53:return -7;
      54:return -8;
      55:return -8;
      56:return -7;
      57:return -8;
      58:return -8;
      59:return -7;
      60:return -7;
      61:return -9;
      62:return -7;
      63:return -7;
      64:return -7;
      65:return -7;
      default:return 999;
    endcase
  endfunction
  function automatic integer bound_gamma_unit(input integer index);
    case(index)
      0:return -23;
      1:return -23;
      2:return -23;
      3:return -24;
      4:return -23;
      5:return -25;
      6:return -23;
      7:return -25;
      8:return -23;
      9:return -25;
      10:return -23;
      11:return -25;
      12:return -23;
      13:return -25;
      14:return -23;
      15:return -24;
      16:return -22;
      17:return -24;
      18:return -23;
      19:return -24;
      20:return -23;
      21:return -24;
      22:return -23;
      23:return -24;
      24:return -23;
      25:return -24;
      26:return -23;
      27:return -24;
      28:return -23;
      29:return -24;
      30:return -23;
      31:return -24;
      32:return -23;
      33:return -23;
      34:return -22;
      35:return -24;
      36:return -22;
      37:return -23;
      38:return -22;
      39:return -23;
      40:return -22;
      41:return -23;
      42:return -22;
      43:return -23;
      44:return -21;
      default:return 999;
    endcase
  endfunction
  function automatic logic supported_down(input integer unit);
    case(unit)
      -19,-17,-16,-15,-14,-13,-12,-11,-8,-6:return 1;
      default:return 0;
    endcase
  endfunction
  function automatic integer bound_gain_cap(input integer layer,activation_unit);
    case(layer)
      0:begin
        if(activation_unit==-7)return 4;
        if(activation_unit==-6)return 2;
        return 2;end
      1:begin
        if(activation_unit==-8)return 4;
        if(activation_unit==-7)return 2;
        return 2;end
      2:begin
        if(activation_unit==-7)return 2;
        if(activation_unit==-5)return -8;
        return 2;end
      3:begin
        if(activation_unit==-7)return 7;
        if(activation_unit==-5)return 2;
        return 7;end
      4:begin
        if(activation_unit==-7)return 7;
        if(activation_unit==-5)return 4;
        return 2;end
      5:begin
        if(activation_unit==-7)return 7;
        if(activation_unit==-4)return 4;
        return 7;end
      6:begin
        if(activation_unit==-7)return 7;
        if(activation_unit==-4)return 2;
        return 7;end
      7:begin
        if(activation_unit==-7)return 6;
        if(activation_unit==-6)return 6;
        if(activation_unit==-4)return -1;
        return 6;end
      8:begin
        if(activation_unit==-7)return 6;
        if(activation_unit==-6)return 6;
        if(activation_unit==-4)return 2;
        return 0;end
      9:begin
        if(activation_unit==-7)return 4;
        if(activation_unit==-6)return 6;
        if(activation_unit==-4)return 4;
        return 6;end
      10:begin
        if(activation_unit==-7)return 6;
        if(activation_unit==-6)return 0;
        if(activation_unit==-4)return 2;
        return 0;end
      11:begin
        if(activation_unit==-6)return 6;
        if(activation_unit==-4)return 2;
        return 0;end
      12:begin
        if(activation_unit==-6)return 6;
        if(activation_unit==-4)return 2;
        return -1;end
      13:begin
        if(activation_unit==-6)return -1;
        if(activation_unit==-4)return 0;
        return 4;end
      14:begin
        if(activation_unit==-6)return 4;
        if(activation_unit==-5)return 6;
        if(activation_unit==-4)return 2;
        return 4;end
      15:begin
        if(activation_unit==-6)return 6;
        if(activation_unit==-5)return 6;
        if(activation_unit==-4)return 2;
        return 6;end
      16:begin
        if(activation_unit==-6)return 6;
        if(activation_unit==-5)return 6;
        if(activation_unit==-4)return 2;
        return 6;end
      17:begin
        if(activation_unit==-6)return 6;
        if(activation_unit==-5)return 6;
        if(activation_unit==-4)return 2;
        return 6;end
      18:begin
        if(activation_unit==-6)return 6;
        if(activation_unit==-5)return 6;
        if(activation_unit==-4)return 4;
        return 6;end
      19:begin
        if(activation_unit==-6)return 4;
        if(activation_unit==-5)return 6;
        if(activation_unit==-4)return -1;
        return 4;end
      20:begin
        if(activation_unit==-5)return 4;
        if(activation_unit==-3)return -1;
        return 4;end
      21:begin
        if(activation_unit==-5)return 4;
        if(activation_unit==-3)return -6;
        return 4;end
      default:return 999;
    endcase
  endfunction
  function automatic integer bound_down_offset(input integer layer,activation_unit);
    case(layer)
      0:begin
        if(activation_unit==-7)return -6;
        if(activation_unit==-6)return -6;
        return -6;end
      1:begin
        if(activation_unit==-8)return -6;
        if(activation_unit==-7)return -6;
        return -6;end
      2:begin
        if(activation_unit==-7)return -6;
        if(activation_unit==-5)return 9;
        return -6;end
      3:begin
        if(activation_unit==-7)return -1;
        if(activation_unit==-5)return -6;
        return -1;end
      4:begin
        if(activation_unit==-7)return -1;
        if(activation_unit==-5)return -6;
        return -6;end
      5:begin
        if(activation_unit==-7)return -1;
        if(activation_unit==-4)return -6;
        return -1;end
      6:begin
        if(activation_unit==-7)return -1;
        if(activation_unit==-4)return -6;
        return -1;end
      7:begin
        if(activation_unit==-7)return -1;
        if(activation_unit==-6)return 0;
        if(activation_unit==-4)return 3;
        return 0;end
      8:begin
        if(activation_unit==-7)return 0;
        if(activation_unit==-6)return 0;
        if(activation_unit==-4)return -6;
        return -6;end
      9:begin
        if(activation_unit==-7)return 1;
        if(activation_unit==-6)return 0;
        if(activation_unit==-4)return -1;
        return 0;end
      10:begin
        if(activation_unit==-7)return 0;
        if(activation_unit==-6)return -6;
        if(activation_unit==-4)return -6;
        return -6;end
      11:begin
        if(activation_unit==-6)return 1;
        if(activation_unit==-4)return -6;
        return -6;end
      12:begin
        if(activation_unit==-6)return 1;
        if(activation_unit==-4)return -6;
        return -6;end
      13:begin
        if(activation_unit==-6)return -6;
        if(activation_unit==-4)return -6;
        return 1;end
      14:begin
        if(activation_unit==-6)return 1;
        if(activation_unit==-5)return 1;
        if(activation_unit==-4)return -6;
        return 1;end
      15:begin
        if(activation_unit==-6)return 1;
        if(activation_unit==-5)return 1;
        if(activation_unit==-4)return -6;
        return 1;end
      16:begin
        if(activation_unit==-6)return 2;
        if(activation_unit==-5)return 2;
        if(activation_unit==-4)return -6;
        return 2;end
      17:begin
        if(activation_unit==-6)return 2;
        if(activation_unit==-5)return 2;
        if(activation_unit==-4)return -6;
        return 2;end
      18:begin
        if(activation_unit==-6)return 2;
        if(activation_unit==-5)return 2;
        if(activation_unit==-4)return -1;
        return 2;end
      19:begin
        if(activation_unit==-6)return 1;
        if(activation_unit==-5)return 2;
        if(activation_unit==-4)return -6;
        return 2;end
      20:begin
        if(activation_unit==-5)return 3;
        if(activation_unit==-3)return 2;
        return 2;end
      21:begin
        if(activation_unit==-5)return 3;
        if(activation_unit==-3)return 7;
        return 3;end
      default:return 999;
    endcase
  endfunction
  typedef struct packed {
    logic valid;
    logic signed [11:0] gate_shift,up_shift,down_shift,gain,down_unit;
  } scalar_policy_t;
  function automatic scalar_policy_t derive_scalar_policy(input integer activation_unit,
      gate_weight_unit,up_weight_unit,down_weight_unit,gain_cap,down_offset);
    scalar_policy_t answer;
    integer gate,original_up,gain,up,down;
    gate=-(activation_unit+gate_weight_unit+8);
    original_up=-(activation_unit+up_weight_unit+8);
    gain=original_up<gain_cap ? original_up:gain_cap;
    up=original_up-gain;
    down=gain+down_offset;if(down<0)down=0;
    answer.gate_shift=12'(gate);answer.up_shift=12'(up);
    answer.down_shift=12'(down);answer.gain=12'(gain);
    answer.down_unit=12'(down_weight_unit+down-8-gain);
    answer.valid=activation_unit>=-256 && activation_unit<=255 &&
      gate>=0 && gate<=63 && up>=0 && up<=63 && down<=63;
    return answer;
  endfunction
endpackage
