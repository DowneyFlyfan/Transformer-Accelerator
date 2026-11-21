`timescale 1ns/1ps

// Local reconstruction of the frozen reference's saturation correction.
// One gated packet stays valid/stable until packet_ready. The caller then
// writes its ordinary signed-eight-bit plane. Completion is withheld until
// that write and a second, signed-eight-bit correction-plane write finish.
// A terminal error invalidates the entire owning frame, including prior writes.
// Enable changes only between frames; reset must also reset the memory peer.
// The downstream Down scheduler must sum both raw projections before rounding.
module tri_oracle_clipping_write_pair (
  input logic clk,rst_n,enable,
  input logic packet_valid,
  output logic packet_ready,
  input logic [6:0] packet_count,
  input logic [5:0] packet_shift,
  input logic [16:0] packet_plane_bytes,
  input logic [1279:0] packet_gated,
  input logic in_req_valid,
  output logic in_req_ready,
  input logic [63:0] in_address,
  input logic [4:0] in_length,
  input logic in_data_valid,
  output logic in_data_ready,
  input logic [63:0] in_data,
  input logic [7:0] in_strobe,
  input logic in_data_last,
  output logic in_rsp_valid,
  input logic in_rsp_ready,
  output logic in_rsp_error,
  output logic mem_req_valid,
  input logic mem_req_ready,
  output logic [63:0] mem_address,
  output logic [4:0] mem_length,
  output logic mem_data_valid,
  input logic mem_data_ready,
  output logic [63:0] mem_data,
  output logic [7:0] mem_strobe,
  output logic mem_data_last,
  input logic mem_rsp_valid,mem_rsp_error,
  output logic mem_rsp_ready
);
  typedef enum logic [3:0] {
    WaitPacket,Capture,PacketReady,WaitRequest,PrimaryData,PrimaryResponse,
    CorrectionRequest,CorrectionData,CorrectionResponse,ReturnResponse
  } state_t;
  state_t state;
  logic bypass,bad_packet,bad_write,response_error;
  logic [6:0] count,index;
  logic [5:0] shift;
  logic [16:0] plane_bytes;
  logic [4:0] length,beat;
  logic [639:0] correction;
  logic [63:0] correction_address;
  logic [64:0] next_address,next_end;

  function automatic logic signed [7:0] clipped_remainder(
    input logic signed [15:0] value,input logic [5:0] down_shift
  );
    logic signed [17:0] extended,wide,coarse,delta;
    extended={{2{value[15]}},value};
    if(down_shift>16)wide=0;
    else if(down_shift==0)wide=extended;
    else if(extended<0)wide=-((-extended+(18'sd1<<(down_shift-6'd1)))>>>down_shift);
    else wide=(extended+(18'sd1<<(down_shift-6'd1)))>>>down_shift;
    coarse=wide>127 ? 18'sd127 : wide< -128 ? -18'sd128 : wide;
    delta=wide-coarse;
    if(delta>127)return 8'sh7f;
    if(delta< -128)return 8'sh80;
    return delta[7:0];
  endfunction

  always_comb begin
    bypass=state==WaitPacket && !enable;
    packet_ready=bypass || state==PacketReady;
    next_address={1'b0,in_address}+65'(plane_bytes);
    next_end=next_address+(65'(in_length)<<3)-65'd1;
    in_req_ready=bypass ? mem_req_ready : state==WaitRequest && (in_length==0 || mem_req_ready);
    mem_req_valid=bypass ? in_req_valid : state==WaitRequest ? in_req_valid && in_length!=0 : state==CorrectionRequest;
    mem_address=state==CorrectionRequest ? correction_address : in_address;
    mem_length=state==CorrectionRequest ? length : in_length;
    in_data_ready=(bypass || state==PrimaryData) && mem_data_ready;
    mem_data_valid=bypass || state==PrimaryData ? in_data_valid : state==CorrectionData;
    mem_data=state==CorrectionData ? correction[int'(beat)*64+:64] : in_data;
    mem_strobe=state==CorrectionData ? 8'hff : in_strobe;
    mem_data_last=state==CorrectionData ? beat+5'd1==length : in_data_last;
    in_rsp_valid=bypass ? mem_rsp_valid : state==ReturnResponse;
    in_rsp_error=bypass ? mem_rsp_error : response_error;
    mem_rsp_ready=bypass ? in_rsp_ready : state==PrimaryResponse || state==CorrectionResponse;
  end

  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      state<=WaitPacket;bad_packet<=0;bad_write<=0;response_error<=0;
      count<=0;index<=0;shift<=0;plane_bytes<=0;length<=0;beat<=0;
      correction<=0;correction_address<=0;
    end else case(state)
      WaitPacket:if(enable && packet_valid)begin
        count<=packet_count;shift<=packet_shift;plane_bytes<=packet_plane_bytes;
        index<=0;correction<=0;response_error<=0;
        bad_packet<=packet_count==0 || packet_count>80 || packet_count[2:0]!=0 ||
                    packet_plane_bytes<17'(packet_count) || packet_plane_bytes[2:0]!=0;
        state<=packet_count==0 || packet_count>80 ? PacketReady : Capture;
      end
      Capture:begin
        correction[int'(index)*8+:8]<=clipped_remainder($signed(packet_gated[int'(index)*16+:16]),shift);
        if(index+7'd1==count)state<=PacketReady;
        else index<=index+7'd1;
      end
      PacketReady:if(packet_valid)state<=WaitRequest;
      WaitRequest:if(in_req_valid && in_req_ready)begin
        if(in_length==0)begin response_error<=1;state<=ReturnResponse;end
        else begin
          length<=in_length;beat<=0;correction_address<=next_address[63:0];
          bad_write<=bad_packet || in_length!=5'(count>>3) ||
                     in_address[2:0]!=0 || next_address[64] || next_end[64];
          state<=PrimaryData;
        end
      end
      PrimaryData:if(in_data_valid && mem_data_ready)begin
        if(in_data_last!=(beat+5'd1==length) || in_strobe!=8'hff)bad_write<=1;
        if(in_data_last)state<=PrimaryResponse;
        else beat<=beat+5'd1;
      end
      PrimaryResponse:if(mem_rsp_valid)begin
        if(mem_rsp_error || bad_write)begin response_error<=1;state<=ReturnResponse;end
        else begin beat<=0;state<=CorrectionRequest;end
      end
      CorrectionRequest:if(mem_req_ready)state<=CorrectionData;
      CorrectionData:if(mem_data_ready)begin
        if(beat+5'd1==length)state<=CorrectionResponse;
        else beat<=beat+5'd1;
      end
      CorrectionResponse:if(mem_rsp_valid)begin response_error<=mem_rsp_error;state<=ReturnResponse;end
      ReturnResponse:if(in_rsp_ready)state<=WaitPacket;
      default:begin response_error<=1;state<=ReturnResponse;end
    endcase
  end
endmodule
