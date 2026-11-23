`timescale 1ns/1ps
// One held row request, one two-row packet cache, full residual precision.
// The owner holds frame fields stable until busy is false and invalidates only
// between leases. The existing external read mux validates/drains eight beats.
module tri_oracle_residual_external_reader (
  input logic clk,rst_n,frame_available,invalidate,
  input logic [31:0] frame_tag,
  input logic [63:0] frame_base,
  input logic [9:0] frame_rows,
  input logic req_valid,
  output logic req_ready,
  input logic [31:0] req_tag,
  input logic [8:0] req_row,
  output logic rsp_valid,rsp_error,busy,
  input logic rsp_ready,
  output logic [31:0] rsp_tag,
  output logic [8:0] rsp_row,
  output logic [231:0] rsp_bypass,
  output logic [127:0] rsp_normalization,
  output logic packet_req_valid,
  input logic packet_req_ready,
  output logic [63:0] packet_req_address,
  input logic packet_rsp_valid,packet_rsp_error,
  output logic packet_rsp_ready,
  input logic [511:0] packet_rsp_data
);
  typedef enum logic[1:0] {Idle,Offer,AwaitPacket,Respond} state_t;
  state_t state;
  logic cache_valid,response_error;
  logic [31:0] held_tag,cache_tag;
  logic [8:0] held_row;
  logic [63:0] held_address,cache_address,request_address;
  logic [511:0] cache_packet;
  logic [255:0] response_word;
  logic [127:0] decoded_normalization;
  logic malformed;

  tri_oracle_residual_replay_row codec (
    .write_bypass(232'd0),.write_normalization(128'd0),.write_padding(),
    .read_bypass(response_word[231:0]),.read_padding(response_word[255:232]),
    .read_normalization(decoded_normalization)
  );
  always_comb begin
    request_address=frame_base+{50'd0,req_row[8:1],6'd0};
    malformed=packet_rsp_error!==1'b0;
    for(int row=0;row<2;row++)begin
      if(packet_rsp_data[row*256+248+:8]!==8'd0)malformed=1;
      for(int lane=0;lane<8;lane++)begin
        case(packet_rsp_data[row*256+232+lane*2+:2])
          2'b00,2'b01,2'b11:;
          default:malformed=1;
        endcase
      end
    end
    req_ready=rst_n && state==Idle && frame_available && !invalidate;
    rsp_valid=rst_n && state==Respond;
    rsp_error=response_error;
    rsp_tag=held_tag;rsp_row=held_row;
    rsp_bypass=rsp_valid && !response_error ? response_word[231:0]:232'd0;
    rsp_normalization=rsp_valid && !response_error ? decoded_normalization:128'd0;
    busy=state!=Idle;
    packet_req_valid=rst_n && state==Offer;
    packet_req_address=packet_req_valid ? held_address:64'd0;
    packet_rsp_ready=rst_n && state==AwaitPacket;
  end
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      state<=Idle;cache_valid<=0;response_error<=0;
      held_tag<=0;held_row<=0;held_address<=0;cache_tag<=0;cache_address<=0;
    end else begin
      if(invalidate)cache_valid<=0;
      case(state)
        Idle:if(req_valid && req_ready)begin
          held_tag<=req_tag;held_row<=req_row;held_address<=request_address;
          response_error<=0;
          if(req_tag!==frame_tag || {1'b0,req_row}>=frame_rows)begin
            response_error<=1;state<=Respond;
          end else if(cache_valid && cache_tag==frame_tag && cache_address==request_address)begin
            response_word<=cache_packet[req_row[0]*256+:256];state<=Respond;
          end else state<=Offer;
        end
        Offer:if(packet_req_valid && packet_req_ready)state<=AwaitPacket;
        AwaitPacket:if(packet_rsp_valid && packet_rsp_ready)begin
          response_error<=malformed;
          if(malformed)cache_valid<=0;
          else begin
            cache_packet<=packet_rsp_data;cache_address<=held_address;cache_tag<=held_tag;
            cache_valid<=!invalidate;response_word<=packet_rsp_data[held_row[0]*256+:256];
          end
          state<=Respond;
        end
        Respond:if(rsp_valid && rsp_ready)state<=Idle;
        default:state<=Idle;
      endcase
    end
  end
endmodule
