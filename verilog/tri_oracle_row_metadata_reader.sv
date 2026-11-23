`timescale 1ns/1ps
// One current 80-channel packet: 480 payload bits, no layer-sized table.
// The external record is 64 bytes: 60 payload bytes and four zero bytes.
// A failed outstanding burst is drained before a zero-payload error reply.
module tri_oracle_row_metadata_reader (
  input logic clk,rst_n,cfg_valid,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [63:0] cfg_base,
  input logic [15:0] cfg_total,cfg_start,
  output logic out_valid,
  input logic out_ready,
  output logic out_error,
  output logic [31:0] out_tag,
  output logic [15:0] out_start,
  output logic [6:0] out_count,
  output logic [479:0] out_units,
  output logic req_valid,
  input logic req_ready,
  output logic [63:0] req_address,
  output logic [4:0] req_length,
  input logic rsp_valid,
  output logic rsp_ready,
  input logic rsp_last,rsp_error,
  input logic [63:0] rsp_data
);
  typedef enum logic [2:0] {Idle,Offer,Receive,Drain,Reply} state_t;
  state_t state;
  logic [31:0] tag;
  logic [15:0] start;
  logic [6:0] count;
  logic [2:0] word_index;
  logic [479:0] payload;
  logic error_seen,invalid_config,padding_bad;
  logic [64:0] table_end,record_address;
  logic [16:0] remaining;

  always_comb begin
    // Check the entire metadata table's inclusive range before issuing any
    // record. 65-bit intermediates retain carries at the address endpoint.
    table_end={1'b0,cfg_base}+((65'(cfg_total)+65'd79)/65'd80)*65'd64-65'd1;
    record_address={1'b0,cfg_base}+(65'(cfg_start)/65'd80)*65'd64;
    remaining={1'b0,cfg_total}-{1'b0,cfg_start};
    invalid_config=cfg_total<32 || cfg_total>8160 || cfg_total[4:0]!=0 ||
      cfg_start>=cfg_total || cfg_start%16'd80!=0 || cfg_base[5:0]!=0 ||
      table_end[64] || record_address[64];
    padding_bad=0;
    for(int bit_index=0;bit_index<64;bit_index++)
      if(int'(word_index)*64+bit_index>=int'(count)*6 && rsp_data[bit_index])padding_bad=1;
    cfg_ready=rst_n && state==Idle;
    req_valid=state==Offer;req_length=5'd8;
    rsp_ready=state==Receive || state==Drain;
    out_valid=state==Reply;out_error=error_seen;
    out_tag=tag;out_start=start;out_count=count;
    out_units=out_valid && !error_seen ? payload : 480'b0;
  end

  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      state<=Idle;tag<=0;start<=0;count<=0;word_index<=0;
      payload<=0;error_seen<=0;req_address<=0;
    end else begin
      case(state)
        Idle:if(cfg_valid && cfg_ready)begin
          tag<=cfg_tag;start<=cfg_start;word_index<=0;payload<=0;error_seen<=invalid_config;
          count<=invalid_config ? 7'd0 : (remaining>80 ? 7'd80 : 7'(remaining));
          req_address<=record_address[63:0];state<=state_t'(invalid_config ? Reply : Offer);
        end
        Offer:if(req_ready)state<=Receive;
        Receive:if(rsp_valid)begin
          if(rsp_error || padding_bad || rsp_last!=(word_index==7))begin
            error_seen<=1;state<=state_t'(rsp_last ? Reply : Drain);
          end else begin
            if(word_index==7)begin payload[479:448]<=rsp_data[31:0];state<=Reply;end
            else begin payload[int'(word_index)*64+:64]<=rsp_data;word_index<=word_index+3'd1;end
          end
        end
        Drain:if(rsp_valid && rsp_last)state<=Reply;
        Reply:if(out_ready)state<=Idle;
        default:begin error_seen<=1;state<=Reply;end
      endcase
    end
  end
endmodule
