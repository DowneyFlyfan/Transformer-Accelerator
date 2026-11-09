`timescale 1ns/1ps
// Prediction/framing/batching control extracted from predicted_gated_fabric.
// This block owns no compute fabric and issues no memory transactions.
module tri_oracle_prediction_packet_stream (
    input logic clk,rst_n,cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [9:0] cfg_features,
    input logic [16:0] cfg_dense_rows,
    input logic in_valid,in_last,in_group_last,
    input logic [10:0] in_group,
    input logic [127:0] norm_activations,
    input logic [255:0] gate_weight_signs,up_weight_signs,
    output logic in_ready,out_valid,
    input logic out_ready,
    output logic out_last,out_fallback,out_error,
    output logic [31:0] out_tag,
    output logic [7:0] out_count,
    output logic [2559:0] out_channels
);
  typedef enum logic [2:0] {IDLE,CONFIGURE_RESET,COLLECT,DRAIN,LAUNCH,ABORT_RESET,ERROR} state_t;
  state_t state;
  logic child_rst_n,reset_second_cycle,first_strip,input_closed,saved_group_last;
  logic [31:0] tag;
  logic [9:0] features,strip_count;
  logic [16:0] dense_rows;
  logic [11:0] expected_group,groups;
  logic [10:0] saved_group,incoming_count;
  logic input_allow,input_fault,invalid_config,packet_fits,packet_fault;
  logic pred_in_ready,pred_valid,pred_ready,pred_last,pred_fallback;
  logic [5:0] pred_count;
  logic [511:0] pred_channels;
  logic [255:0] unused_lane_enable;
  logic [7:0] batch_count;
  logic [2559:0] batch_channels;
  logic batch_final,batch_fallback;

  always_comb begin
    invalid_config=cfg_features==0 || cfg_features>10'd512 || cfg_dense_rows<17'd32 ||
        cfg_dense_rows>17'd65536 || cfg_dense_rows[4:0]!=0;
    cfg_ready=state==IDLE;
    input_allow=(state==COLLECT && !input_closed) || state==DRAIN;
    incoming_count=first_strip?11'd1:{1'b0,strip_count}+11'd1;
    input_fault=in_last!=(incoming_count=={1'b0,features}) ||
        (first_strip?({1'b0,in_group}!=expected_group ||
          in_group_last!=(expected_group+12'd1==groups)):
          (in_group!=saved_group || in_group_last!=saved_group_last));
    in_ready=input_allow && pred_in_ready;
    packet_fits=9'(batch_count)+9'(pred_count)<=9'd160;
    packet_fault=pred_count>6'd32 || (pred_last?pred_count>=6'd32:pred_count!=6'd32);
    for(int row=0;row<32;row++)
      if(row<int'(pred_count) && {1'b0,pred_channels[row*16+:16]}>=dense_rows) packet_fault=1;
    pred_ready=state==DRAIN || (state==COLLECT && packet_fits);
    out_valid=state==LAUNCH || state==ERROR;
    out_last=state==ERROR || batch_final;
    out_error=state==ERROR;
    out_fallback=state==LAUNCH && batch_fallback;
    out_tag=tag;
    out_count=state==ERROR?8'd0:batch_count;
    out_channels=state==ERROR?2560'b0:batch_channels;
  end

  tri_oracle_predicted_dispatch prediction (
      .clk(clk),.rst_n(child_rst_n),.in_valid(input_allow && in_valid),.in_last(in_last),
      .in_group_last(in_group_last),.in_frame_error(input_fault),.in_group(in_group),
      .norm_activations(norm_activations),.gate_weight_signs(gate_weight_signs),.up_weight_signs(up_weight_signs),
      .in_ready(pred_in_ready),.out_ready(pred_ready),.out_valid(pred_valid),.out_last(pred_last),
      .out_error(pred_fallback),.out_count(pred_count),.out_channels(pred_channels),.out_lane_enable(unused_lane_enable)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      state<=IDLE;child_rst_n<=0;reset_second_cycle<=0;tag<=0;features<=0;strip_count<=0;dense_rows<=0;
      expected_group<=0;groups<=0;saved_group<=0;saved_group_last<=0;first_strip<=1;input_closed<=0;
      batch_count<=0;batch_channels<=0;batch_final<=0;batch_fallback<=0;
    end else begin
      child_rst_n<=1;
      case(state)
        IDLE: if(cfg_valid) begin
          tag<=cfg_tag;features<=cfg_features;dense_rows<=cfg_dense_rows;groups<=cfg_dense_rows[16:5];
          expected_group<=0;saved_group<=0;saved_group_last<=0;first_strip<=1;strip_count<=0;input_closed<=0;
          batch_count<=0;batch_channels<=0;batch_final<=0;batch_fallback<=0;
          child_rst_n<=0;reset_second_cycle<=0;state<=invalid_config?ABORT_RESET:CONFIGURE_RESET;
        end
        CONFIGURE_RESET: begin
          if(reset_second_cycle) state<=COLLECT;
          else begin child_rst_n<=0;reset_second_cycle<=1;end
        end
        COLLECT: begin
          if(in_valid && in_ready) begin
            if(first_strip) begin saved_group<=in_group;saved_group_last<=in_group_last;end
            first_strip<=in_last;
            strip_count<=in_last ? 10'd0 : (incoming_count>11'd512 ? 10'd512 : incoming_count[9:0]);
            if(in_last) begin
              expected_group<=expected_group+12'd1;
              if(first_strip?in_group_last:saved_group_last) input_closed<=1;
            end
          end
          if(in_valid && in_ready && input_fault) begin
            if(in_last) begin child_rst_n<=0;reset_second_cycle<=0;state<=ABORT_RESET;end
            else state<=DRAIN;
          end else if(pred_valid) begin
            if(packet_fault) begin child_rst_n<=0;reset_second_cycle<=0;state<=ABORT_RESET;end
            else if(!packet_fits) state<=LAUNCH;
            else if(pred_ready) begin
              if(pred_count!=0) batch_channels[int'(batch_count[7:5])*512+:512]<=pred_channels;
              batch_count<=batch_count+8'(pred_count);batch_final<=pred_last;
              batch_fallback<=batch_fallback || pred_fallback;
              if(pred_last) state<=LAUNCH;
            end
          end
        end
        DRAIN: if(in_valid && in_ready && in_last) begin child_rst_n<=0;reset_second_cycle<=0;state<=ABORT_RESET;end
        LAUNCH: if(out_ready) begin
          if(batch_final) state<=IDLE;
          else begin batch_count<=0;batch_channels<=0;batch_final<=0;batch_fallback<=0;state<=COLLECT;end
        end
        ABORT_RESET: begin
          if(reset_second_cycle) state<=ERROR;
          else begin child_rst_n<=0;reset_second_cycle<=1;end
        end
        ERROR: if(out_ready) state<=IDLE;
        default: begin child_rst_n<=0;reset_second_cycle<=0;state<=ABORT_RESET;end
      endcase
    end
  end
endmodule
