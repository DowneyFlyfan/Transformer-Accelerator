`timescale 1ns/1ps
// Batched paired projection followed by the existing signed16 SiLU gate.
// Only one raw packet is retained while the native result queues hold the rest
// of the batch. Each token has independent captured gate/up/down shifts.
// Prepared masks and all numeric formats are local reconstruction choices.
// Terminal errors invalidate every earlier output carrying the descriptor tag.
module tri_oracle_batched_gated380 (
  input logic clk,rst_n,cfg_valid,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [4:0] cfg_tokens,
  input logic [9:0] cfg_feature_words,
  input logic [16:0] cfg_dense_rows,
  input logic [6:0] cfg_count,
  input logic [1279:0] cfg_channels,cfg_keep,
  input logic [63:0] cfg_activation_base,cfg_weight_base,cfg_up_weight_base,
  input logic [31:0] cfg_activation_stride,
  input logic [95:0] cfg_gate_shifts,cfg_up_shifts,cfg_down_shifts,
  output logic out_valid,
  input logic out_ready,
  output logic [31:0] out_tag,
  output logic [3:0] out_token,
  output logic out_last,
  output logic [6:0] out_count,
  output logic [1279:0] out_channels,out_gated,
  output logic [639:0] out_down_input,
  output logic done_valid,
  input logic done_ready,
  output logic done_error,
  output logic [31:0] done_tag,
  output logic req_valid,
  input logic req_ready,
  output logic [63:0] req_address,
  output logic [4:0] req_length,
  input logic rsp_valid,
  output logic rsp_ready,
  input logic rsp_last,rsp_error,
  input logic [63:0] rsp_data
);
  typedef enum logic [2:0] {IDLE,WAIT_RAW,ACTIVATE,DRAIN_ACTIVATION,RESULT,ERROR_DRAIN,ERROR_FLUSH,DONE} state_t;
  state_t state;
  logic [31:0] tag;
  logic [4:0] tokens,completed_tokens;
  logic [6:0] count,issued,completed;
  logic [1279:0] channels;
  logic [95:0] gate_shifts,up_shifts,down_shifts;
  logic [5119:0] raw_values;
  logic [3:0] token;
  logic last,flush_second;
  logic projection_ready,projection_valid,projection_out_ready,projection_last;
  logic [31:0] projection_tag,projection_done_tag;
  logic [3:0] projection_token;
  logic [6:0] projection_count;
  logic [1279:0] projection_channels;
  logic [5119:0] projection_data;
  logic projection_done_valid,projection_done_error,projection_done_ready;
  logic activation_rst_n,activation_in_valid,activation_in_ready,activation_valid;
  logic signed [15:0] activation_data;
  logic [15:0] activation_tag;
  logic raw_fault,activation_fault;
  int gate_row,up_row;

  function automatic logic signed [15:0] requantize16(input logic signed [31:0] value,input logic [5:0] shift);
    logic signed [33:0] extended,rounded;
    extended={{2{value[31]}},value};
    if(shift>32)rounded=0;
    else if(shift==0)rounded=extended;
    else if(extended<0)rounded=-((-extended+(34'sd1<<(shift-6'd1)))>>>shift);
    else rounded=(extended+(34'sd1<<(shift-6'd1)))>>>shift;
    if(rounded>32767)return 16'sh7fff;
    if(rounded< -32768)return 16'sh8000;
    return rounded[15:0];
  endfunction
  function automatic logic signed [7:0] requantize8(input logic signed [15:0] value,input logic [5:0] shift);
    logic signed [17:0] extended,rounded;
    extended={{2{value[15]}},value};
    if(shift>16)rounded=0;
    else if(shift==0)rounded=extended;
    else if(extended<0)rounded=-((-extended+(18'sd1<<(shift-6'd1)))>>>shift);
    else rounded=(extended+(18'sd1<<(shift-6'd1)))>>>shift;
    if(rounded>127)return 8'sh7f;
    if(rounded< -128)return 8'sh80;
    return rounded[7:0];
  endfunction

  tri_oracle_batched_paired379 projection (
    .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid && state==IDLE),.cfg_ready(projection_ready),
    .cfg_tag(cfg_tag),.cfg_tokens(cfg_tokens),.cfg_feature_words(cfg_feature_words),
    .cfg_dense_rows(cfg_dense_rows),.cfg_count(cfg_count),.cfg_channels(cfg_channels),.cfg_keep(cfg_keep),
    .cfg_activation_base(cfg_activation_base),.cfg_weight_base(cfg_weight_base),.cfg_up_weight_base(cfg_up_weight_base),
    .cfg_activation_stride(cfg_activation_stride),.out_valid(projection_valid),.out_ready(projection_out_ready),
    .out_tag(projection_tag),.out_token(projection_token),.out_last(projection_last),
    .out_count(projection_count),.out_channels(projection_channels),.out_data(projection_data),
    .done_valid(projection_done_valid),.done_ready(projection_done_ready),.done_error(projection_done_error),
    .done_tag(projection_done_tag),.req_valid(req_valid),.req_ready(req_ready),.req_address(req_address),
    .req_length(req_length),.rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_last(rsp_last),
    .rsp_error(rsp_error),.rsp_data(rsp_data));
  tri_oracle_silu_gate activation (
    .clk(clk),.rst_n(activation_rst_n),.in_valid(activation_in_valid),.in_ready(activation_in_ready),
    .in_gate(requantize16($signed(raw_values[gate_row*32+:32]),gate_shifts[int'(token)*6+:6])),
    .in_up(requantize16($signed(raw_values[up_row*32+:32]),up_shifts[int'(token)*6+:6])),
    .in_tag(16'(issued)),.out_valid(activation_valid),
    .out_ready(state==ACTIVATE || state==DRAIN_ACTIVATION),.out_data(activation_data),.out_tag(activation_tag));

  always_comb begin
    cfg_ready=state==IDLE && projection_ready;
    projection_out_ready=state==WAIT_RAW || state==ERROR_DRAIN;
    projection_done_ready=state==WAIT_RAW || state==ERROR_DRAIN;
    raw_fault=projection_tag!=tag || projection_count!=count || projection_channels!=channels ||
      projection_token!=4'(completed_tokens) || projection_last!=(completed_tokens+5'd1==tokens) || completed_tokens>=tokens;
    gate_row=(int'(issued)/16)*32+int'(issued)%16;
    up_row=gate_row+16;
    if(issued>=80)begin gate_row=0;up_row=16;end
    activation_rst_n=rst_n && state!=ERROR_DRAIN && state!=ERROR_FLUSH;
    activation_in_valid=state==ACTIVATE && issued<count;
    activation_fault=activation_valid && (activation_tag!=16'(completed) || completed>=count);
    out_valid=state==RESULT;
    out_tag=tag;out_token=token;out_last=last;out_count=count;out_channels=channels;
    done_valid=state==DONE;done_tag=tag;
  end
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      state<=IDLE;tag<=0;tokens<=0;completed_tokens<=0;count<=0;channels<=0;
      gate_shifts<=0;up_shifts<=0;down_shifts<=0;raw_values<=0;token<=0;last<=0;
      issued<=0;completed<=0;out_gated<=0;out_down_input<=0;done_error<=0;flush_second<=0;
    end else begin
      case(state)
        IDLE:if(cfg_valid && cfg_ready)begin
          tag<=cfg_tag;tokens<=cfg_tokens;count<=cfg_count;channels<=cfg_channels;
          gate_shifts<=cfg_gate_shifts;up_shifts<=cfg_up_shifts;down_shifts<=cfg_down_shifts;
          completed_tokens<=0;done_error<=0;state<=WAIT_RAW;
        end
        WAIT_RAW:begin
          if(projection_done_valid)begin
            done_error<=projection_done_error || projection_done_tag!=tag || completed_tokens!=tokens;
            if(projection_done_error || projection_done_tag!=tag || completed_tokens!=tokens)begin
              flush_second<=0;state<=ERROR_FLUSH;
            end else state<=DONE;
          end else if(projection_valid)begin
            if(raw_fault)begin done_error<=1;state<=ERROR_DRAIN;end
            else begin
              raw_values<=projection_data;token<=projection_token;last<=projection_last;
              issued<=0;completed<=0;out_gated<=0;out_down_input<=0;state<=ACTIVATE;
            end
          end
        end
        ACTIVATE,DRAIN_ACTIVATION:begin
          if(activation_fault)begin done_error<=1;state<=ERROR_DRAIN;end
          else begin
            if(activation_in_valid && activation_in_ready)begin
              issued<=issued+7'd1;if(issued+7'd1==count)state<=DRAIN_ACTIVATION;
            end
            if(activation_valid)begin
              out_gated[int'(completed)*16+:16]<=activation_data;
              out_down_input[int'(completed)*8+:8]<=requantize8(activation_data,down_shifts[int'(token)*6+:6]);
              completed<=completed+7'd1;if(completed+7'd1==count)state<=RESULT;
            end
          end
        end
        RESULT:if(out_ready)begin completed_tokens<=completed_tokens+5'd1;state<=WAIT_RAW;end
        ERROR_DRAIN:if(projection_done_valid)begin flush_second<=0;state<=ERROR_FLUSH;end
        ERROR_FLUSH:if(flush_second)state<=DONE;else flush_second<=1;
        DONE:if(done_ready)state<=IDLE;
        default:begin done_error<=1;state<=ERROR_DRAIN;end
      endcase
    end
  end
endmodule
