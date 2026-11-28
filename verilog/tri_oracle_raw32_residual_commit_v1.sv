`timescale 1ns/1ps
// One-row residual commit; the native test retains its 264-row parent frame.
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

module tri_oracle_raw32_residual_commit_v1 (
  input logic clk,rst_n,abort_valid,owner_held,
  input logic cfg_valid,output logic cfg_ready,
  input raw32_residual_commit_types_v1::job_t cfg_job,
  output raw32_residual_commit_types_v1::job_t held_job,
  output logic launch_allowed,active,epoch_fault,native_input_drained,
  input logic row_context_valid,
  input logic [31:0] row_tag,
  input logic [4:0] row_layer,
  input logic [15:0] row_epoch,
  input logic [9:0] row_root,row_input_rank,row_kept_rank,
  input logic [127:0] row_bundle,
  input logic signed [11:0] row_down_unit,
  input logic [63:0] row_down_table,
  input logic signed [8:0] row_activation_unit,row_gain,
  input logic [5:0] row_gate_shift,row_up_shift,row_down_shift,
  input logic in_valid,output logic in_ready,
  input logic [31:0] in_tag,
  input logic [3:0] in_token,
  input logic [15:0] in_start,
  input logic [7:0] in_count,
  input logic in_last,input logic [5119:0] in_data,
  input logic native_done_fire,native_done_error,
  input logic [31:0] native_done_tag,
  output logic req_valid,input logic req_ready,
  output logic [63:0] req_address,output logic [4:0] req_length,
  input logic rsp_valid,rsp_last,rsp_error,output logic rsp_ready,
  input logic [63:0] rsp_data,input logic physical_unowned_response,
  output logic write_req_valid,input logic write_req_ready,
  output logic [63:0] write_address,output logic [4:0] write_length,
  output logic write_data_valid,input logic write_data_ready,
  output logic [63:0] write_data,output logic [7:0] write_strobe,
  output logic write_last,input logic write_rsp_valid,write_rsp_error,
  output logic write_rsp_ready,
  output logic c_read_selected,c_cfg_valid,c_demand_valid,c_retire_valid,
  input logic c_cfg_ready,c_demand_ready,c_retire_ready,
  input logic c_fault,c_producer_idle,c_port_idle,c_idle,
  input logic [9:0] c_accepted_rows,c_completed_rows,
  input logic c_output_valid,c_read_request_valid,c_read_response_valid,
  input logic c_output_fire,c_output_last,c_output_error,
  input logic [31:0] c_output_tag,
  input logic [9:0] c_output_index,
  input logic [3:0] c_output_count,
  output logic row_done_valid,row_done_error,input logic row_done_ready,
  output logic [31:0] row_done_tag,
  output logic [7:0] table_words,output logic [1:0] metadata_words,
  output logic packet_captured,output logic [5119:0] held_packet,
  output logic signed [7:0] selected_raw_unit,
  output logic [63:0] selected_epsilon,
  output logic [8:0] scratch_ack_count,raw_ack_count,
  output logic metadata_acknowledged
);
  import raw32_residual_commit_types_v1::*;
  import raw32_residual_math_v1::*;
  import raw32_residual_bindings_v1::*;
  typedef enum logic [5:0] {Idle,TableSetup,TableWait,MetaSetup,MetaWait,CheckMeta,
    WaitPacket,ScratchSetup,ScratchWait,OriginalSetup,OriginalWait,PeakLane,
    WaitNative,SelectUnit,ReplayOriginalSetup,ReplayOriginalWait,ReplayDownSetup,
    ReplayDownWait,RecodeLane,RawSetup,RawWait,PublishSetup,PublishWait,
    CConfigure,CDemand,CRun,DoneHold,Completed,FaultDrain,ProtocolQuarantine} state_t;
  state_t state;
  job_t saved;
  logic fault,quarantine,row_seen,native_success,c_phase,c_demand_seen,input_complete,accepted_complete;
  logic read_offer,read_owned,write_offer,write_owned,write_all;
  logic c_config_offer,c_demand_offer;
  logic [63:0] read_address,write_address_saved;
  logic [4:0] read_length,write_length_saved;
  logic [3:0] read_beat,write_beat,table_burst,packet_index,packet_line;
  logic [7:0] line_index;
  logic [3:0] lane;
  logic [8:0] c_strips;
  logic [511:0] residual_buffer,write_buffer;
  logic [127:0] source_metadata,target_metadata,expected_source_metadata;
  logic [147:0] peak,lane_magnitude;
  logic signed [147:0] lane_sum;
  logic signed [7:0] unit_scan;
  recode_t recoded;
  integer common_unit,calc_gate,calc_original_up,calc_gain,calc_up,calc_down,calc_output;
  logic configuration_bad,context_match,packet_bad,lane_bad;
  logic read_request_fire,read_response_fire,read_complete;
  logic write_request_fire,write_data_fire,write_response_fire;
  logic bad_read_association,bad_write_association,malformed_read_last;
  logic ordinary_fault,association_fault,quiet_owned,c_quiet;
  logic ambiguous_control,c_health_unknown,c_visible_unknown,c_output_fault;
  logic [10:0] position_sum;
  logic [32:0] target_tag;
  logic [64:0] raw_end,meta_end,table_end,scratch_end,target_raw_end,target_meta_end,gamma_end,gamma_table_end;
  logic [64:0] protected_end;
  logic signed [31:0] raw_lane,down_lane;
  scalar_policy_t scalar_policy;

  function automatic logic overlap(input logic [63:0] a,b,input logic [64:0] ae,be);
    return {1'b0,a} <= be && {1'b0,b} <= ae;
  endfunction

  always_comb begin
    raw_end={1'b0,cfg_job.raw_base}+{1'b0,cfg_job.raw_bytes}-65'd1;
    meta_end={1'b0,cfg_job.metadata_base}+{1'b0,cfg_job.metadata_bytes}-65'd1;
    table_end={1'b0,cfg_job.down_table_base}+65'd1023;
    scratch_end={1'b0,cfg_job.down_scratch_base}+{1'b0,cfg_job.down_scratch_bytes}-65'd1;
    target_raw_end={1'b0,cfg_job.target_raw_base}+{1'b0,cfg_job.target_raw_bytes}-65'd1;
    target_meta_end={1'b0,cfg_job.target_metadata_base}+{1'b0,cfg_job.target_metadata_bytes}-65'd1;
    gamma_end={1'b0,cfg_job.target_gamma_base}+{1'b0,cfg_job.target_gamma_bytes}-65'd1;
    gamma_table_end={1'b0,cfg_job.gamma_table_base}+{1'b0,cfg_job.gamma_table_bytes}-65'd1;
    scalar_policy=derive_scalar_policy(int'($signed(cfg_job.activation_unit)),int'($signed(cfg_job.gate_weight_unit)),
      int'($signed(cfg_job.up_weight_unit)),int'($signed(cfg_job.down_weight_unit)),
      int'($signed(cfg_job.gain_cap)),int'($signed(cfg_job.down_offset)));
    calc_gate=int'($signed(scalar_policy.gate_shift));calc_gain=int'($signed(scalar_policy.gain));
    calc_up=int'($signed(scalar_policy.up_shift));calc_down=int'($signed(scalar_policy.down_shift));
    calc_output=int'($signed(scalar_policy.down_unit));calc_original_up=0;
    configuration_bad=$isunknown(cfg_job) || (owner_held!==1'b1) || cfg_job.phase!=1 || cfg_job.normalization_role!=1 ||
      cfg_job.source_layer>=22 || cfg_job.input_count==0 || cfg_job.input_count>576 ||
      $isunknown({c_idle,c_producer_idle,c_port_idle,c_output_valid,c_read_request_valid,
        c_read_response_valid,c_accepted_rows,c_completed_rows,c_fault}) || (c_fault!==1'b0) ||
      !c_idle || !c_producer_idle || !c_port_idle || c_output_valid || c_read_request_valid || c_read_response_valid ||
      c_accepted_rows!=0 || c_completed_rows!=0 ||
      cfg_job.kept_count==0 || cfg_job.kept_count>cfg_job.input_count || cfg_job.target_count!=cfg_job.kept_count ||
      cfg_job.source_rank>=cfg_job.input_count || cfg_job.original_root>=576 ||
      (11'(cfg_job.image_start)+11'(cfg_job.original_root))>1023 ||
      (11'(cfg_job.image_start)+11'(cfg_job.original_root))==0 ||
      cfg_job.kept_rank!=0 || cfg_job.target_rank!=cfg_job.kept_rank ||
      cfg_job.source_epoch==16'hffff || {1'b0,cfg_job.target_epoch}!=({1'b0,cfg_job.source_epoch}+17'd1) ||
      cfg_job.raw_unit < -32 || cfg_job.raw_unit > 97 || !supported_down(int'($signed(cfg_job.down_unit))) ||
      cfg_job.epsilon!=physical_epsilon(cfg_job.raw_unit) ||
      int'($signed(cfg_job.gate_weight_unit))!=bound_weight_unit(int'(cfg_job.source_layer),0) ||
      int'($signed(cfg_job.up_weight_unit))!=bound_weight_unit(int'(cfg_job.source_layer),1) ||
      int'($signed(cfg_job.down_weight_unit))!=bound_weight_unit(int'(cfg_job.source_layer),2) ||
      !scalar_policy.valid || calc_gate<0 || calc_gate>63 || calc_up<0 || calc_up>63 || calc_down>63 ||
      int'(cfg_job.gate_shift)!=calc_gate || int'(cfg_job.up_shift)!=calc_up || int'(cfg_job.down_shift)!=calc_down ||
      int'($signed(cfg_job.gain_cap))!=bound_gain_cap(int'(cfg_job.source_layer),int'($signed(cfg_job.activation_unit))) ||
      int'($signed(cfg_job.down_offset))!=bound_down_offset(int'(cfg_job.source_layer),int'($signed(cfg_job.activation_unit))) ||
      int'($signed(cfg_job.gain))!=calc_gain || int'($signed(cfg_job.down_unit))!=calc_output ||
      cfg_job.raw_base[5:0]!=0 || cfg_job.raw_bytes[5:0]!=0 ||
      {1'b0,cfg_job.raw_bytes}<(65'(cfg_job.image_start)+65'(cfg_job.input_count))*65'd8192 ||
      cfg_job.metadata_base[3:0]!=0 || cfg_job.metadata_bytes[3:0]!=0 ||
      {1'b0,cfg_job.metadata_bytes}<65'(cfg_job.input_count)*65'd16 ||
      cfg_job.down_table_base[2:0]!=0 || cfg_job.down_scratch_base[5:0]!=0 || cfg_job.down_scratch_bytes!=8192 ||
      cfg_job.target_raw_base[5:0]!=0 || cfg_job.target_raw_bytes[5:0]!=0 ||
      {1'b0,cfg_job.target_raw_bytes}<(65'(cfg_job.image_start)+65'(cfg_job.target_count))*65'd8192 ||
      cfg_job.target_metadata_base[3:0]!=0 || cfg_job.target_metadata_bytes[3:0]!=0 ||
      {1'b0,cfg_job.target_metadata_bytes}<65'(cfg_job.target_count)*65'd16 ||
      cfg_job.gamma_table_base[2:0]!=0 || cfg_job.gamma_table_bytes!=276480 ||
      cfg_job.target_gamma_base[2:0]!=0 || cfg_job.target_gamma_bytes!=6144 ||
      (cfg_job.source_layer==21 ? (cfg_job.target_layer!=21 || cfg_job.target_role!=2 || cfg_job.target_gamma_index!=44) :
        (cfg_job.target_layer!=cfg_job.source_layer+1 || cfg_job.target_role!=0 || cfg_job.target_gamma_index!=2*(cfg_job.source_layer+1))) ||
      {1'b0,cfg_job.target_gamma_base}!=({1'b0,cfg_job.gamma_table_base}+65'(cfg_job.target_gamma_index)*65'd6144) ||
      int'($signed(cfg_job.target_gamma_exponent))!=bound_gamma_unit(int'(cfg_job.target_gamma_index)) ||
      ({1'b0,cfg_job.target_tag_base}+33'd575)>33'hffffffff ||
      (11'(cfg_job.image_start)+11'd575)>1023 ||
      raw_end[64] || meta_end[64] || table_end[64] || scratch_end[64] ||
      target_raw_end[64] || target_meta_end[64] || gamma_end[64] || gamma_table_end[64] ||
      cfg_job.protected_count==0 || cfg_job.protected_count>16;
    // Every writable extent is disjoint from explicit immutable operands and
    // the caller's complete still-owned weight/code/feature/intermediate set.
    for(integer region=0;region<3;region++)begin
      case(region)
        0:begin
          if(overlap(cfg_job.down_scratch_base,cfg_job.target_raw_base,scratch_end,target_raw_end) ||
             overlap(cfg_job.down_scratch_base,cfg_job.target_metadata_base,scratch_end,target_meta_end))configuration_bad=1;
        end
        1:if(overlap(cfg_job.target_raw_base,cfg_job.target_metadata_base,target_raw_end,target_meta_end))configuration_bad=1;
        default:begin end
      endcase
      for(integer protected_region=0;protected_region<20;protected_region++)begin
        logic [63:0] writable_base,immutable_base;
        logic [64:0] writable_end,immutable_end;
        writable_base=region==0 ? cfg_job.down_scratch_base : region==1 ? cfg_job.target_raw_base : cfg_job.target_metadata_base;
        writable_end=region==0 ? scratch_end : region==1 ? target_raw_end : target_meta_end;
        immutable_base=0;immutable_end=0;
        if(protected_region<16 && protected_region<int'(cfg_job.protected_count))begin
          immutable_base=cfg_job.protected_base[protected_region];
          immutable_end={1'b0,immutable_base}+{1'b0,cfg_job.protected_bytes[protected_region]}-65'd1;
          if(cfg_job.protected_bytes[protected_region]==0 || immutable_end[64])configuration_bad=1;
        end
        if(protected_region==16)begin immutable_base=cfg_job.raw_base;immutable_end=raw_end;end
        if(protected_region==17)begin immutable_base=cfg_job.metadata_base;immutable_end=meta_end;end
        if(protected_region==18)begin immutable_base=cfg_job.down_table_base;immutable_end=table_end;end
        if(protected_region==19)begin immutable_base=cfg_job.gamma_table_base;immutable_end=gamma_table_end;end
        if((protected_region>=16 || protected_region<int'(cfg_job.protected_count)) &&
           overlap(writable_base,immutable_base,writable_end,immutable_end))configuration_bad=1;
      end
    end
    protected_end=0;
    position_sum={1'b0,saved.image_start}+{1'b0,saved.original_root};
    target_tag={1'b0,saved.target_tag_base}+33'(saved.target_rank);
    expected_source_metadata={5'd0,saved.source_epoch,saved.source_layer,position_sum[9:0],
      saved.source_rank,saved.original_root,saved.raw_unit,saved.epsilon};
    target_metadata={5'd0,saved.target_epoch,saved.target_layer,position_sum[9:0],
      saved.target_rank,saved.original_root,selected_raw_unit,selected_epsilon};
    context_match=!$isunknown({row_context_valid,row_tag,row_layer,row_epoch,row_root,row_input_rank,row_kept_rank,
      row_bundle,row_down_unit,row_down_table,row_activation_unit,row_gain,row_gate_shift,row_up_shift,row_down_shift}) &&
      row_context_valid && row_tag==saved.source_tag && row_layer==saved.source_layer && row_epoch==saved.source_epoch &&
      row_root==saved.original_root && row_input_rank==saved.source_rank && row_kept_rank==saved.kept_rank &&
      row_bundle==saved.bundle && row_down_unit==saved.down_unit && row_down_table==saved.down_table_base &&
      row_activation_unit==saved.activation_unit && row_gain==saved.gain && row_gate_shift==saved.gate_shift &&
      row_up_shift==saved.up_shift && row_down_shift==saved.down_shift;
    packet_bad=$isunknown({in_tag,in_token,in_start,in_count,in_last}) || in_tag!=saved.source_tag || in_token!=0 ||
      in_start!=16'(int'(packet_index)*160) || in_count!=(packet_index==12 ? 8'd128:8'd160) ||
      in_last!=(packet_index==12);
    for(integer value=0;value<160;value++)
      if(value<int'(in_count) && $isunknown(in_data[value*32+:32]))packet_bad=1;
    raw_lane=$signed(residual_buffer[int'(lane)*32+:32]);
    down_lane=$signed(write_buffer[int'(lane)*32+:32]);
    lane_sum=exact_sum(raw_lane,down_lane,int'($signed(saved.raw_unit)),int'($signed(saved.down_unit)));
    lane_magnitude=magnitude(lane_sum);
    lane_bad=$isunknown({raw_lane,down_lane}) || raw_lane===32'h80000000 ||
      $signed(down_lane)>32'sd92274688 || $signed(down_lane)<-32'sd92274688;
    recoded=recode_once(lane_sum,common_unit,int'($signed(selected_raw_unit)));
    held_job=saved;
    cfg_ready=rst_n && state==Idle && !fault && (abort_valid===1'b0) && (owner_held===1'b1) &&
      (rsp_valid===1'b0) && (write_rsp_valid===1'b0) && (physical_unowned_response===1'b0);
    active=rst_n && state!=Idle;
    launch_allowed=rst_n && table_words==128 && metadata_words==2 &&
      state>=WaitPacket && !fault && (abort_valid===1'b0) && (owner_held===1'b1);
    in_ready=rst_n && state==WaitPacket && context_match && !fault && (abort_valid===1'b0) && (owner_held===1'b1);
    native_input_drained=rst_n && input_complete && scratch_ack_count==128 && !fault;
    req_valid=rst_n && read_offer;req_address=read_address;req_length=read_length;
    rsp_ready=rst_n && read_owned && !quarantine;
    write_req_valid=rst_n && write_offer;write_address=write_address_saved;write_length=write_length_saved;
    write_data_valid=rst_n && write_owned && !write_all;
    write_data=write_buffer[int'(write_beat)*64+:64];write_strobe=8'hff;
    write_last=(write_beat+1)==write_length_saved;
    write_rsp_ready=rst_n && write_owned && write_all && !quarantine;
    read_request_fire=req_valid && (req_ready===1'b1);read_response_fire=(rsp_valid===1'b1) && rsp_ready;
    read_complete=read_response_fire && rsp_last;
    write_request_fire=write_req_valid && (write_req_ready===1'b1);
    write_data_fire=write_data_valid && (write_data_ready===1'b1);
    write_response_fire=(write_rsp_valid===1'b1) && write_rsp_ready;
    bad_read_association=rst_n && (rsp_valid===1'b1) && !read_owned;
    malformed_read_last=read_response_fire && (rsp_last!==(read_beat+1==read_length));
    bad_write_association=rst_n && (write_rsp_valid===1'b1) && (!write_owned || !write_all);
    c_health_unknown=$isunknown({c_idle,c_producer_idle,c_port_idle,c_accepted_rows,c_completed_rows,c_fault});
    c_visible_unknown=$isunknown({c_output_valid,c_read_request_valid,c_read_response_valid});
    // Known-ready/valid events alone advance owned records. An ambiguous
    // acceptance poisons association permanently, but never retracts an
    // already exposed request/data/Done tuple. Known later acceptances may
    // drain its offer; no unknown response can clear quarantine or complete.
    ambiguous_control=
      (state==Idle && cfg_ready && $isunknown(cfg_valid)) ||
      (state==Idle && (cfg_valid===1'b1) &&
        $isunknown({owner_held,abort_valid,rsp_valid,write_rsp_valid,physical_unowned_response})) ||
      (read_offer && $isunknown(req_ready)) ||
      (rst_n && $isunknown({rsp_valid,write_rsp_valid,native_done_fire,physical_unowned_response})) ||
      (write_offer && $isunknown(write_req_ready)) ||
      (write_data_valid && $isunknown(write_data_ready)) ||
      (active && $isunknown(in_valid)) ||
      (c_config_offer && $isunknown(c_cfg_ready)) ||
      (c_demand_offer && $isunknown(c_demand_ready)) ||
      (c_phase && c_visible_unknown) ||
      (c_phase && $isunknown(c_output_fire)) ||
      (row_done_valid && $isunknown(row_done_ready));
    association_fault=(physical_unowned_response===1'b1) || bad_read_association ||
      bad_write_association || malformed_read_last || ambiguous_control;
    c_output_fault=c_phase && (c_output_fire===1'b1) &&
      ((c_output_valid!==1'b1) || !c_demand_seen || c_strips>=256 || c_output_tag!=target_tag[31:0] ||
       c_output_index!=10'(c_strips) || c_output_count!=8 || c_output_last!=(c_strips==255) ||
       c_output_error || $isunknown({c_output_tag,c_output_index,c_output_count,c_output_last,c_output_error}));
    ordinary_fault=(active && ((abort_valid===1'b1) || (owner_held===1'b0) || $isunknown({abort_valid,owner_held}))) ||
      (row_seen && !context_match && state!=Completed) ||
      (state==WaitPacket && (in_valid===1'b1) && (!context_match || packet_bad)) ||
      (input_complete && (in_valid===1'b1)) ||
      (active && (c_health_unknown || (c_fault===1'b1))) ||
      c_output_fault ||
      (active && !c_phase && (c_visible_unknown || (c_idle!==1'b1) ||
        (c_producer_idle!==1'b1) || (c_port_idle!==1'b1) ||
        (c_output_valid===1'b1) || (c_read_request_valid===1'b1) || (c_read_response_valid===1'b1) ||
        (c_accepted_rows!==10'd0) || (c_completed_rows!==10'd0))) ||
      ((state==PeakLane || state==RecodeLane) && lane_bad) ||
      (state==RecodeLane && recoded.bad) ||
      (read_response_fire && (rsp_error || $isunknown({rsp_data,rsp_error,rsp_last}))) ||
      (write_response_fire && (write_rsp_error || $isunknown(write_rsp_error))) ||
      ((native_done_fire===1'b1) && (native_done_error || native_done_tag!=saved.source_tag || native_success ||
        !accepted_complete || (in_valid!==1'b0) ||
        $isunknown({native_done_error,native_done_tag})));
    c_cfg_valid=rst_n && c_config_offer;c_demand_valid=rst_n && c_demand_offer;
    c_retire_valid=0;c_read_selected=rst_n && c_phase;
    c_quiet=(c_output_valid===1'b0) && (c_read_request_valid===1'b0) && (c_read_response_valid===1'b0) &&
      (c_producer_idle===1'b1) && (c_port_idle===1'b1);
    quiet_owned=!read_offer && !read_owned && !write_offer && !write_owned && (rsp_valid===1'b0) && (write_rsp_valid===1'b0) &&
      !c_config_offer && !c_demand_offer && (!c_phase || c_quiet);
    epoch_fault=fault || (rst_n && (ordinary_fault || association_fault));
  end

  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      state<=Idle;saved<='0;fault<=0;quarantine<=0;row_seen<=0;native_success<=0;c_phase<=0;c_demand_seen<=0;input_complete<=0;accepted_complete<=0;
      read_offer<=0;read_owned<=0;write_offer<=0;write_owned<=0;write_all<=0;c_config_offer<=0;c_demand_offer<=0;
      read_address<=0;write_address_saved<=0;read_length<=0;write_length_saved<=0;read_beat<=0;write_beat<=0;
      table_burst<=0;packet_index<=0;packet_line<=0;line_index<=0;lane<=0;c_strips<=0;
      residual_buffer<=0;write_buffer<=0;source_metadata<=0;peak<=0;common_unit<=0;
      table_words<=0;metadata_words<=0;packet_captured<=0;held_packet<=0;selected_raw_unit<=0;selected_epsilon<=0;
      unit_scan<=-8'sd32;
      scratch_ack_count<=0;raw_ack_count<=0;metadata_acknowledged<=0;row_done_valid<=0;row_done_error<=0;row_done_tag<=0;
    end else begin
      // Transport remains stable independently of fault-state transitions.
      if(read_request_fire)begin read_offer<=0;read_owned<=1;read_beat<=0;end
      if(read_response_fire)begin
        if(state==TableWait)begin table_words<=table_words+1'b1;if(rsp_data!==64'd0)fault<=1;end
        if(state==MetaWait)begin source_metadata[int'(read_beat)*64+:64]<=rsp_data;metadata_words<=metadata_words+1'b1;end
        if(state==OriginalWait || state==ReplayOriginalWait)residual_buffer[int'(read_beat)*64+:64]<=rsp_data;
        if(state==ReplayDownWait)write_buffer[int'(read_beat)*64+:64]<=rsp_data;
        if(rsp_last && !malformed_read_last)read_owned<=0;
        else if(read_beat<15)read_beat<=read_beat+1'b1;
      end
      if(write_request_fire)begin write_offer<=0;write_owned<=1;write_all<=0;write_beat<=0;end
      if(write_data_fire)begin
        if(write_last)write_all<=1;
        else write_beat<=write_beat+1'b1;
      end
      if(write_response_fire)begin write_owned<=0;write_all<=0;end
      // Producer completion follows acceptance of all packets, not this
      // consumer's later scratch writes/original reads/peak calculation.
      // Preserve strict-after-lastaccept ordering: same-edge Done is early.
      if((native_done_fire===1'b1) && !fault && !ordinary_fault && !association_fault &&
        accepted_complete && (native_done_error===1'b0) && native_done_tag==saved.source_tag && !native_success)native_success<=1;
      if(c_cfg_valid && (c_cfg_ready===1'b1))begin c_config_offer<=0;end
      if(c_demand_valid && (c_demand_ready===1'b1))begin c_demand_offer<=0;c_demand_seen<=1;end
      if(c_phase && (c_output_fire===1'b1))begin
        if(c_output_fault)fault<=1;
        else c_strips<=c_strips+1'b1;
      end
      if(row_done_valid && (row_done_ready===1'b1))begin
        row_done_valid<=0;state<=quarantine ? ProtocolQuarantine:Completed;
      end
      if(!fault && !ordinary_fault && !association_fault)begin
        case(state)
          Idle:if((cfg_valid===1'b1) && cfg_ready)begin
            saved<=cfg_job;common_unit<=int'($signed(cfg_job.raw_unit))<int'($signed(cfg_job.down_unit)) ?
              int'($signed(cfg_job.raw_unit)):int'($signed(cfg_job.down_unit));
            if(configuration_bad)begin fault<=1;state<=FaultDrain;end
            else state<=TableSetup;
          end
          TableSetup:begin read_address<=saved.down_table_base+64'(table_burst)*64;read_length<=8;read_offer<=1;state<=TableWait;end
          TableWait:if(read_complete)begin
            if(table_burst==15)state<=MetaSetup;
            else begin table_burst<=table_burst+1'b1;state<=TableSetup;end
          end
          MetaSetup:begin read_address<=saved.metadata_base+64'(saved.source_rank)*16;read_length<=2;read_offer<=1;state<=MetaWait;end
          MetaWait:if(read_complete)state<=CheckMeta;
          CheckMeta:if(source_metadata!==expected_source_metadata || table_words!=128 || metadata_words!=2)begin fault<=1;state<=FaultDrain;end
            else state<=WaitPacket;
          WaitPacket:if((in_valid===1'b1) && in_ready)begin
            held_packet<=in_data;packet_captured<=1;row_seen<=1;packet_line<=0;
            if(packet_index==12)accepted_complete<=1;
            state<=ScratchSetup;
          end
          ScratchSetup:begin write_buffer<=held_packet[int'(packet_line)*512+:512];write_address_saved<=saved.down_scratch_base+64'(line_index)*64;write_length_saved<=8;write_offer<=1;state<=ScratchWait;end
          ScratchWait:if(write_response_fire)begin scratch_ack_count<=scratch_ack_count+1'b1;state<=OriginalSetup;end
          OriginalSetup:begin read_address<=saved.raw_base+(64'(saved.image_start)+64'(saved.source_rank))*8192+64'(line_index)*64;read_length<=8;read_offer<=1;state<=OriginalWait;end
          OriginalWait:if(read_complete)begin lane<=0;state<=PeakLane;end
          PeakLane:begin
            if(lane_magnitude>peak)peak<=lane_magnitude;
            if(lane==15)begin
              if(line_index==127)begin input_complete<=1;state<=WaitNative;end
              else begin
                line_index<=line_index+1'b1;
                if(packet_line==(packet_index==12 ? 7:9))begin packet_index<=packet_index+1'b1;state<=WaitPacket;end
                else begin packet_line<=packet_line+1'b1;state<=ScratchSetup;end
              end
            end else lane<=lane+1'b1;
          end
          WaitNative:if(native_success && input_complete && quiet_owned && scratch_ack_count==128)begin unit_scan<=-8'sd32;state<=SelectUnit;end
          // One shared wide comparison per cycle; do not unroll 130 barrel
          // shifts/comparators into a parallel hardware selection network.
          SelectUnit:begin
            if(peak==0)begin selected_raw_unit<=0;selected_epsilon<=physical_epsilon(8'sd0);line_index<=0;state<=ReplayOriginalSetup;end
            else if(unit_fits(peak,common_unit,int'($signed(unit_scan))))begin
              selected_raw_unit<=unit_scan;selected_epsilon<=physical_epsilon(unit_scan);line_index<=0;state<=ReplayOriginalSetup;
            end else if(unit_scan==8'sd97)begin fault<=1;state<=FaultDrain;end
            else unit_scan<=unit_scan+8'sd1;
          end
          ReplayOriginalSetup:begin read_address<=saved.raw_base+(64'(saved.image_start)+64'(saved.source_rank))*8192+64'(line_index)*64;read_length<=8;read_offer<=1;state<=ReplayOriginalWait;end
          ReplayOriginalWait:if(read_complete)state<=ReplayDownSetup;
          ReplayDownSetup:begin read_address<=saved.down_scratch_base+64'(line_index)*64;read_length<=8;read_offer<=1;state<=ReplayDownWait;end
          ReplayDownWait:if(read_complete)begin lane<=0;state<=RecodeLane;end
          RecodeLane:begin held_packet[int'(lane)*32+:32]<=recoded.code;if(lane==15)state<=RawSetup;else lane<=lane+1'b1;end
          RawSetup:begin write_buffer<=held_packet[511:0];write_address_saved<=saved.target_raw_base+(64'(saved.image_start)+64'(saved.target_rank))*8192+64'(line_index)*64;write_length_saved<=8;write_offer<=1;state<=RawWait;end
          RawWait:if(write_response_fire)begin raw_ack_count<=raw_ack_count+1'b1;if(line_index==127)state<=PublishSetup;else begin line_index<=line_index+1'b1;state<=ReplayOriginalSetup;end end
          PublishSetup:if(scratch_ack_count!=128 || raw_ack_count!=128 || !native_success)begin fault<=1;state<=FaultDrain;end
            else begin write_buffer<={384'd0,target_metadata};write_address_saved<=saved.target_metadata_base+64'(saved.target_rank)*16;write_length_saved<=2;write_offer<=1;state<=PublishWait;end
          PublishWait:if(write_response_fire)begin metadata_acknowledged<=1;c_phase<=1;state<=CConfigure;end
          CConfigure:begin
            if(!c_config_offer && (c_idle===1'b1) && c_quiet && c_accepted_rows==0 && c_completed_rows==0)c_config_offer<=1;
            if(c_cfg_valid && (c_cfg_ready===1'b1))state<=CDemand;
          end
          CDemand:begin if(!c_demand_offer && !c_demand_seen)c_demand_offer<=1;if(c_demand_valid && (c_demand_ready===1'b1))state<=CRun;end
          CRun:if(c_strips==256 && c_accepted_rows==1 && c_completed_rows==1 && c_quiet && quiet_owned)begin
            row_done_valid<=1;row_done_error<=0;row_done_tag<=target_tag[31:0];state<=DoneHold;
          end
          DoneHold:begin end
          Completed:begin end
          default:begin fault<=1;state<=ProtocolQuarantine;quarantine<=1;end
        endcase
      end
      if(ordinary_fault || fault)begin
        fault<=1;
        if(state!=DoneHold && state!=Completed && !quarantine)state<=FaultDrain;
      end
      if(association_fault)begin fault<=1;quarantine<=1;state<=ProtocolQuarantine;end
      if(fault && !quarantine && !association_fault && quiet_owned && !in_valid && !row_done_valid && state!=Completed)begin
        row_done_valid<=1;row_done_error<=1;row_done_tag<=target_tag[31:0];state<=DoneHold;
      end
      // A late fault invalidates the epoch but never rewrites a held Done tuple.
      // Retire and owner release are deliberately absent: actual C frame stays
      // AwaitDemand at accepted/completed 1 of the configured target_count.
    end
  end
endmodule
