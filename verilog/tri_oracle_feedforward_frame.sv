`timescale 1ns/1ps
// Production selected-packet -> complete feedforward-frame scheduling.
// One bounded160-value packet is retained while existing SRAM slots hold
// partial sums for at most15 output rounds. No hidden-tensor cache is added.
// A terminal error invalidates every earlier output prefix with the same tag.
module tri_oracle_feedforward_frame (
    input logic clk,rst_n,cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [63:0] cfg_activation_base,cfg_weight_base,cfg_up_weight_base,cfg_down_weight_base,
    input logic [9:0] cfg_features,
    input logic [16:0] cfg_dense_features,
    input logic [15:0] cfg_output_count,
    input logic [5:0] cfg_gate_shift,cfg_up_shift,cfg_down_shift,
    input logic in_valid,in_last,in_fallback,
    output logic in_ready,
    input logic [7:0] in_count,
    input logic [2559:0] in_channels,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,out_error,out_fallback,
    output logic [31:0] out_tag,
    output logic [15:0] out_start,
    output logic [7:0] out_count,
    output logic [5119:0] out_data,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,rsp_last,rsp_error,
    output logic rsp_ready,
    input logic [63:0] rsp_data
);
  localparam logic [64:0] LastAddress=65'h0ffffffffffffffff;
  typedef enum logic [3:0] {IDLE,RESET_ENGINE,WAIT_ENGINE,PACKET,GATE_LAUNCH,GATE_WAIT,
                          DOWN_LAUNCH,DOWN_WAIT,ERROR_RESET,ERROR_RESULT} state_t;
  state_t state;
  logic engine_reset_n,reset_second_cycle,have_previous_packet;
  logic [31:0] tag;
  logic [63:0] activation_base,weight_base,up_weight_base,down_weight_base;
  logic [9:0] features;
  logic [16:0] dense_features,total_selected;
  logic [15:0] output_count;
  logic [5:0] gate_shift,up_shift,down_shift;
  logic [2559:0] packet_channels;
  logic [5119:0] packet_values;
  logic [7:0] packet_count;
  logic packet_last,packet_fallback,frame_fallback;
  logic [2:0] subgroup,last_subgroup;
  logic [3:0] output_round;
  logic [15:0] current_start,remaining_outputs;
  logic [7:0] current_output_count;
  logic [5:0] subgroup_count;
  logic last_round,final_contribution,down_mode;
  logic invalid_config,invalid_packet,gated_fault,down_fault;
  logic [64:0] input_bytes,activation_end,gate_end,up_end,down_end;
  logic [17:0] incoming_total;
  logic engine_ready,engine_valid,engine_out_ready,engine_is_down,engine_last,engine_error,engine_fallback;
  logic [31:0] engine_tag;
  logic [15:0] engine_start;
  logic [3:0] engine_slot;
  logic [7:0] engine_count;
  logic [2559:0] engine_channels;
  logic [5119:0] engine_data;

  always_comb begin
    input_bytes=65'(cfg_features)<<3;
    activation_end={1'b0,cfg_activation_base}+input_bytes-1;
    gate_end={1'b0,cfg_weight_base}+65'(cfg_dense_features)*input_bytes-1;
    up_end={1'b0,cfg_up_weight_base}+65'(cfg_dense_features)*input_bytes-1;
    down_end={1'b0,cfg_down_weight_base}+65'(cfg_dense_features)*65'(cfg_output_count)-1;
    invalid_config=cfg_features==0 || cfg_features>10'd512 || cfg_dense_features<17'd8 ||
        cfg_dense_features>17'd65536 || cfg_dense_features[2:0]!=0 ||
        cfg_output_count==0 || cfg_output_count>16'd2400 ||
        cfg_activation_base[2:0]!=0 || cfg_weight_base[2:0]!=0 ||
        cfg_up_weight_base[2:0]!=0 || cfg_down_weight_base[2:0]!=0 ||
        activation_end>LastAddress || gate_end>LastAddress || up_end>LastAddress || down_end>LastAddress;
    incoming_total={1'b0,total_selected}+18'(in_count);
    invalid_packet=in_count>8'd160 || incoming_total>{1'b0,dense_features};
    for(int row=0;row<160;row++)
      if(row<int'(in_count) && 17'(in_channels[row*16+:16])>=dense_features) invalid_packet=1;
  end

  // All iteration geometry derives only from captured configuration/packet data.
  always_comb begin
    current_start=16'(output_round)*16'd160;
    remaining_outputs=output_count-current_start;
    current_output_count=remaining_outputs>16'd160 ? 8'd160 : 8'(remaining_outputs);
    last_round=remaining_outputs<=16'd160;
    last_subgroup=packet_count==0?3'b0:3'((packet_count-8'd1)>>5);
    subgroup_count=0;
    if(int'(packet_count)>int'(subgroup)*32)
      subgroup_count=6'(int'(packet_count)-int'(subgroup)*32>32?32:int'(packet_count)-int'(subgroup)*32);
    final_contribution=packet_last && subgroup==last_subgroup;
    down_mode=state==DOWN_LAUNCH || state==DOWN_WAIT;
  end

  always_comb begin
    gated_fault=engine_error || engine_is_down || engine_tag!=tag || engine_count!=packet_count ||
        engine_channels!=packet_channels || engine_last!=packet_last || engine_fallback!=packet_fallback ||
        engine_start!=0 || engine_slot!=0;
    down_fault=engine_error || !engine_is_down || engine_tag!=tag || engine_count!=current_output_count ||
        engine_channels!=0 || engine_last!=final_contribution || engine_fallback ||
        engine_start!=current_start || engine_slot!=output_round+4'd1;
  end

  always_comb begin
    cfg_ready=state==IDLE && engine_reset_n && engine_ready;
    in_ready=state==PACKET && engine_reset_n && engine_ready;
    out_valid=state==ERROR_RESULT || (state==DOWN_WAIT && final_contribution && engine_valid && !down_fault);
    out_error=state==ERROR_RESULT;
    out_last=state==ERROR_RESULT || last_round;
    out_tag=tag;
    out_start=state==ERROR_RESULT?16'b0:engine_start;
    out_count=state==ERROR_RESULT?8'b0:engine_count;
    out_fallback=state!=ERROR_RESULT && frame_fallback;
    // The error reset clears the child's packet registers before ERROR_RESULT.
    // Direct registered data avoids a5120-bit combinational validity mask.
    out_data=engine_data;
    engine_out_ready=state==GATE_WAIT || (state==DOWN_WAIT &&
        (down_fault || !final_contribution || out_ready));
  end

  tri_oracle_gated_down_fabric engine (
      .clk(clk),.rst_n(engine_reset_n),.in_valid(state==GATE_LAUNCH || state==DOWN_LAUNCH),
      .in_ready(engine_ready),.in_is_down(down_mode),.in_last(down_mode?final_contribution:packet_last),
      .in_fallback(packet_fallback),.in_accumulate(have_previous_packet || subgroup!=0),.in_tag(tag),
      .in_channels(down_mode?{2048'b0,packet_channels[int'(subgroup)*512+:512]}:packet_channels),
      .in_data(down_mode?packet_values[int'(subgroup)*1024+:1024]:1024'b0),
      .in_count(down_mode?8'(subgroup_count):packet_count),.in_output_count(current_output_count),
      .in_activation_base(activation_base),.in_weight_base(down_mode?down_weight_base:weight_base),
      .in_up_weight_base(up_weight_base),.in_features(features),.in_dense_features(dense_features),
      .in_output_start(current_start),.in_shift(down_shift),.in_gate_shift(gate_shift),.in_up_shift(up_shift),
      .in_slot(output_round+4'd1),.out_valid(engine_valid),.out_ready(engine_out_ready),
      .out_is_down(engine_is_down),.out_last(engine_last),.out_fallback(engine_fallback),.out_error(engine_error),
      .out_tag(engine_tag),.out_count(engine_count),.out_channels(engine_channels),.out_data(engine_data),
      .out_start(engine_start),.out_slot(engine_slot),.req_valid(req_valid),.req_ready(req_ready),
      .req_address(req_address),.req_length(req_length),.rsp_valid(rsp_valid),.rsp_last(rsp_last),
      .rsp_error(rsp_error),.rsp_ready(rsp_ready),.rsp_data(rsp_data)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      state<=IDLE;engine_reset_n<=0;reset_second_cycle<=0;have_previous_packet<=0;
      tag<=0;activation_base<=0;weight_base<=0;up_weight_base<=0;down_weight_base<=0;
      features<=0;dense_features<=0;output_count<=0;gate_shift<=0;up_shift<=0;down_shift<=0;
      packet_channels<=0;packet_values<=0;packet_count<=0;packet_last<=0;packet_fallback<=0;frame_fallback<=0;
      subgroup<=0;output_round<=0;total_selected<=0;
    end else begin
      engine_reset_n<=1;
      case(state)
        IDLE: if(cfg_valid && cfg_ready) begin
          tag<=cfg_tag;activation_base<=cfg_activation_base;weight_base<=cfg_weight_base;
          up_weight_base<=cfg_up_weight_base;down_weight_base<=cfg_down_weight_base;
          features<=cfg_features;dense_features<=cfg_dense_features;output_count<=cfg_output_count;
          gate_shift<=cfg_gate_shift;up_shift<=cfg_up_shift;down_shift<=cfg_down_shift;
          have_previous_packet<=0;total_selected<=0;frame_fallback<=0;packet_count<=0;
          packet_channels<=0;packet_values<=0;subgroup<=0;output_round<=0;
          engine_reset_n<=0;reset_second_cycle<=0;state<=invalid_config?ERROR_RESET:RESET_ENGINE;
        end
        RESET_ENGINE: begin
          if(reset_second_cycle) state<=WAIT_ENGINE;
          else begin engine_reset_n<=0;reset_second_cycle<=1;end
        end
        WAIT_ENGINE: if(engine_ready) state<=PACKET;
        PACKET: if(in_valid && in_ready) begin
          if(invalid_packet) begin engine_reset_n<=0;reset_second_cycle<=0;state<=ERROR_RESET;end
          else begin
            packet_channels<=in_channels;packet_count<=in_count;packet_last<=in_last;packet_fallback<=in_fallback;
            frame_fallback<=frame_fallback || in_fallback;total_selected<=incoming_total[16:0];
            subgroup<=0;output_round<=0;state<=GATE_LAUNCH;
          end
        end
        GATE_LAUNCH: if(engine_ready) state<=GATE_WAIT;
        GATE_WAIT: if(engine_valid) begin
          if(gated_fault) begin engine_reset_n<=0;reset_second_cycle<=0;state<=ERROR_RESET;end
          else begin packet_values<=engine_data;subgroup<=0;output_round<=0;state<=DOWN_LAUNCH;end
        end
        DOWN_LAUNCH: if(engine_ready) state<=DOWN_WAIT;
        DOWN_WAIT: if(engine_valid) begin
          if(down_fault) begin engine_reset_n<=0;reset_second_cycle<=0;state<=ERROR_RESET;end
          else if(engine_out_ready) begin
            if(last_round) begin
              output_round<=0;
              if(subgroup==last_subgroup) begin
                if(packet_last) state<=IDLE;
                else begin have_previous_packet<=1;state<=PACKET;end
              end else begin subgroup<=subgroup+3'd1;state<=DOWN_LAUNCH;end
            end else begin output_round<=output_round+4'd1;state<=DOWN_LAUNCH;end
          end
        end
        ERROR_RESET: begin
          if(reset_second_cycle) state<=ERROR_RESULT;
          else begin engine_reset_n<=0;reset_second_cycle<=1;end
        end
        ERROR_RESULT: if(out_ready) state<=IDLE;
        default: begin engine_reset_n<=0;reset_second_cycle<=0;state<=ERROR_RESET;end
      endcase
    end
  end
endmodule
