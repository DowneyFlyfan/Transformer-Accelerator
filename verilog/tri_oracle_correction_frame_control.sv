`timescale 1ns/1ps
// Feed-forward frame scheduling around the existing shared tensor boundary.
// Optional clipping correction reuses its raw accumulator slots and writes two
// external intermediate planes. Only the combined Down result is published.
// All numeric formats and the extra correction pass are local reconstruction
// choices. This controller alone does not qualify the complete trained chip.
module tri_oracle_correction_frame_control #(parameter bit PACKED_FEEDFORWARD_WEIGHTS=1) (

  input logic clk,rst_n,cfg_valid,cfg_correction_enable,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [4:0] cfg_tokens,
  input logic [15:0] cfg_input_features,cfg_intermediate_features,
  input logic [16:0] cfg_output_features,
  input logic [63:0] cfg_activation_base,cfg_gate_base,cfg_up_base,cfg_down_base,cfg_intermediate_base,
  input logic [31:0] cfg_activation_stride,
  input logic [95:0] cfg_gate_shifts,cfg_up_shifts,cfg_down_shifts,
  input logic mask_valid,mask_last,
  output logic mask_ready,
  input logic [31:0] mask_tag,
  input logic [15:0] mask_start,
  input logic [6:0] mask_count,
  input logic [1279:0] mask_bits,
  output logic out_valid,
  input logic out_ready,
  output logic [31:0] out_tag,
  output logic [3:0] out_token,
  output logic [15:0] out_start,
  output logic [7:0] out_count,
  output logic out_last,
  output logic [5119:0] out_data,
  output logic done_valid,
  input logic done_ready,
  output logic done_error,
  output logic [31:0] done_tag,
  output logic wr_req_valid,
  input logic wr_req_ready,
  output logic [63:0] wr_address,
  output logic [4:0] wr_length,
  output logic wr_data_valid,
  input logic wr_data_ready,
  output logic [63:0] wr_data,
  output logic [7:0] wr_strobe,
  output logic wr_data_last,
  input logic wr_rsp_valid,wr_rsp_error,
  output logic wr_rsp_ready,
  input logic attention_enable,attention_cfg_valid,
  output logic attention_cfg_ready,
  input logic [31:0] attention_cfg_tag,attention_cfg_activation_stride,
  input logic [4:0] attention_cfg_tokens,
  input logic [9:0] attention_cfg_feature_words,
  input logic [16:0] attention_cfg_dense_rows,
  input logic [7:0] attention_cfg_count,
  input logic [2559:0] attention_cfg_channels,attention_cfg_keep,
  input logic [63:0] attention_cfg_activation_base,attention_cfg_weight_base,
  input logic attention_out_ready,attention_done_ready,
  output logic attention_out_valid,attention_out_last,
  output logic [31:0] attention_out_tag,
  output logic [3:0] attention_out_token,
  output logic [7:0] attention_out_count,
  output logic [2559:0] attention_out_channels,
  output logic [5119:0] attention_out_data,
  output logic attention_done_valid,attention_done_error,
  output logic [31:0] attention_done_tag,
  output logic compute_cfg_valid,compute_cfg_paired,compute_cfg_packed_weights,
  input logic compute_ready,
  output logic [31:0] compute_cfg_tag,compute_cfg_activation_stride,
  output logic [4:0] compute_cfg_tokens,
  output logic [9:0] compute_cfg_feature_words,
  output logic [16:0] compute_cfg_dense_rows,
  output logic [7:0] compute_cfg_count,
  output logic [2559:0] compute_cfg_channels,compute_cfg_keep,
  output logic [63:0] compute_cfg_activation_base,compute_cfg_weight_base,compute_cfg_up_weight_base,
  output logic [95:0] compute_cfg_gate_shifts,compute_cfg_up_shifts,compute_cfg_down_shifts,
  output logic compute_hold_primary,compute_append_correction,compute_clear_context,
  input logic compute_out_valid,compute_last,
  output logic compute_out_ready,
  input logic [31:0] compute_tag,
  input logic [3:0] compute_token,
  input logic [7:0] compute_count,
  input logic [2559:0] compute_channels,
  input logic [5119:0] compute_data,
  input logic [639:0] compute_down,
  input logic compute_done_valid,compute_done_error,
  output logic compute_done_ready,
  input logic [31:0] compute_done_tag
);
  typedef enum logic [3:0] {IDLE,MASK_WAIT,GATE_LAUNCH,GATE_WAIT,WRITE_LOW,WRITE_HIGH,
    WRITE_REQUEST,WRITE_DATA,WRITE_RESPONSE,DOWN_LAUNCH,DOWN_WAIT,ERROR_DRAIN,DONE} state_t;
  state_t state;
  logic correction_enable,correction_pass,operation_hold,operation_append;
  logic pair_ready,writer_rst_n,writer_flush;
  logic [16:0] plane_bytes;
  logic [63:0] correction_base;
  logic [1279:0] gated_packet;
  logic raw_wr_req_valid,raw_wr_req_ready,raw_wr_data_valid,raw_wr_data_ready;
  logic raw_wr_data_last,raw_wr_rsp_valid,raw_wr_rsp_error,raw_wr_rsp_ready;
  logic [63:0] raw_wr_address,raw_wr_data;
  logic [4:0] raw_wr_length;
  logic [7:0] raw_wr_strobe;
  logic [31:0] tag,activation_stride;
  logic [4:0] tokens,completed_tokens;
  logic [15:0] input_features,intermediate_features,intermediate_start;
  logic [16:0] output_features,output_start;
  logic [63:0] activation_base,gate_base,up_base,down_base,intermediate_base;
  logic [95:0] gate_shifts,up_shifts,down_shifts;
  logic [1279:0] saved_mask;
  logic [639:0] write_packet;
  logic [16:0] write_offset;
  logic [32:0] write_low_sum,write_high_sum;
  logic [4:0] write_beat;
  logic [6:0] gate_count;
  logic [7:0] down_count;
  logic [15:0] remaining_intermediate;
  logic [16:0] remaining_outputs;
  logic gate_final,down_final,launch_paired,invalid_config,invalid_mask,gate_fault,down_fault;
  logic [64:0] activation_end,gate_end,up_end,down_end,intermediate_end;
  logic [4:0] range_last_token;
  logic [36:0] range_activation_span;
  logic [31:0] range_pair_span;
  logic [32:0] range_down_span;
  logic [20:0] range_plane_span;
  logic [2559:0] gate_channels,down_channels,compute_keep;
  logic attention_owned, attention_window, attention_selected;

  // Frame scheduling owns every command outside Idle. An admitted attention
  // command holds its packet and terminal channels even if its request changes.
  assign attention_window = attention_enable && state == IDLE && !attention_owned;
  assign attention_selected = attention_owned || (attention_window && attention_cfg_valid);
  assign attention_cfg_ready = attention_window && compute_ready;
  assign attention_out_valid = attention_owned && compute_out_valid;
  assign attention_out_tag = compute_tag;
  assign attention_out_token = compute_token;
  assign attention_out_last = compute_last;
  assign attention_out_count = compute_count;
  assign attention_out_channels = compute_channels;
  assign attention_out_data = compute_data;
  assign attention_done_valid = attention_owned && compute_done_valid;
  assign attention_done_error = compute_done_error;
  assign attention_done_tag = compute_done_tag;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) attention_owned <= 0;
    else if (attention_cfg_valid && attention_cfg_ready) attention_owned <= 1;
    else if (attention_done_valid && attention_done_ready) attention_owned <= 0;
  end

  function automatic logic overlaps(input logic [64:0] first_base,first_end,second_base,second_end);
    return first_base<=second_end && second_base<=first_end;
  endfunction
  always_comb begin
    // Keep interface-width products before the65-bit address/carry sum.
    // A separate5-bit subtraction avoids widening its underflow expression.
    // Zero tokens still unconditionally reject below; every nonzero endpoint
    // equals the original65-bit expression for all interface port values.
    range_last_token=cfg_tokens-5'd1;
    range_activation_span=37'(range_last_token)*37'(cfg_activation_stride);
    range_pair_span=32'(cfg_intermediate_features)*32'(cfg_input_features);
    range_down_span=33'(cfg_output_features)*33'(cfg_intermediate_features);
    range_plane_span=21'(cfg_tokens)*21'(cfg_intermediate_features);
    activation_end={1'b0,cfg_activation_base}+65'(range_activation_span)+65'(cfg_input_features)-65'd1;
    gate_end={1'b0,cfg_gate_base}+65'(range_pair_span)-65'd1;
    up_end={1'b0,cfg_up_base}+65'(range_pair_span)-65'd1;
    down_end={1'b0,cfg_down_base}+65'(range_down_span)-65'd1;
    intermediate_end={1'b0,cfg_intermediate_base}+(cfg_correction_enable ? (65'(range_plane_span)<<1) : 65'(range_plane_span))-65'd1;
    invalid_config=cfg_tokens==0 || cfg_tokens>16 || cfg_input_features<32 || cfg_input_features>8160 ||
      cfg_intermediate_features<32 || cfg_intermediate_features>8160 || cfg_input_features[4:0]!=0 ||
      cfg_intermediate_features[4:0]!=0 || cfg_output_features==0 || cfg_output_features>65536 ||
      cfg_activation_base[2:0]!=0 || cfg_gate_base[2:0]!=0 || cfg_up_base[2:0]!=0 || cfg_down_base[2:0]!=0 ||
      (PACKED_FEEDFORWARD_WEIGHTS && (cfg_output_features[2:0]!=0 || cfg_down_base[5:0]!=0 ||
                              cfg_gate_base[5:0]!=0 || cfg_up_base[5:0]!=0)) ||
      cfg_intermediate_base[2:0]!=0 || cfg_activation_stride[2:0]!=0 || cfg_activation_stride<32'(cfg_input_features) ||
      activation_end[64] || gate_end[64] || up_end[64] || down_end[64] || intermediate_end[64] ||
      overlaps({1'b0,cfg_intermediate_base},intermediate_end,{1'b0,cfg_activation_base},activation_end) ||
      overlaps({1'b0,cfg_intermediate_base},intermediate_end,{1'b0,cfg_gate_base},gate_end) ||
      overlaps({1'b0,cfg_intermediate_base},intermediate_end,{1'b0,cfg_up_base},up_end) ||
      overlaps({1'b0,cfg_intermediate_base},intermediate_end,{1'b0,cfg_down_base},down_end);
  end
  always_comb begin
    remaining_intermediate=intermediate_features-intermediate_start;
    remaining_outputs=output_features-output_start;
    gate_final=remaining_intermediate<=80;down_final=remaining_outputs<=160;
    gate_count=gate_final ? 7'(remaining_intermediate) : 7'd80;
    down_count=down_final ? 8'(remaining_outputs) : 8'd160;
    launch_paired=state==GATE_LAUNCH;
    gate_channels=0;down_channels=0;compute_keep=0;
    for(int row=0;row<80;row++)if(row<int'(gate_count))gate_channels[row*16+:16]=intermediate_start+16'(row);
    for(int row=0;row<160;row++)if(row<int'(down_count))down_channels[row*16+:16]=16'(output_start+17'(row));
    for(int token=0;token<16;token++)begin
      if(launch_paired)begin
        for(int row=0;row<80;row++)if(row<int'(gate_count))compute_keep[token*160+row]=saved_mask[token*80+row];
      end else begin
        for(int row=0;row<160;row++)if(row<int'(down_count))compute_keep[token*160+row]=1;
      end
    end
    invalid_mask=mask_tag!=tag || mask_start!=intermediate_start || mask_count!=gate_count || mask_last!=gate_final;
    gate_fault=compute_tag!=tag || compute_count!=8'(gate_count) || compute_channels!=gate_channels ||
      compute_token!=4'(completed_tokens) || completed_tokens>=tokens || compute_last!=(completed_tokens+5'd1==tokens);
    down_fault=(correction_enable && !correction_pass) || compute_tag!=tag || compute_count!=down_count || compute_channels!=down_channels ||
      compute_token!=4'(completed_tokens) || completed_tokens>=tokens || compute_last!=(completed_tokens+5'd1==tokens);
    write_high_sum={1'b0,intermediate_base[63:32]}+33'(write_low_sum[32]);
    cfg_ready=state==IDLE && !attention_selected && compute_ready;mask_ready=state==MASK_WAIT;
    compute_out_ready=attention_owned ? attention_out_ready : ((state==GATE_WAIT && (gate_fault || pair_ready)) || state==ERROR_DRAIN || (state==DOWN_WAIT && (down_fault || out_ready)));
    compute_done_ready=attention_owned ? attention_done_ready : (state==GATE_WAIT || state==DOWN_WAIT || state==ERROR_DRAIN);
    out_valid=state==DOWN_WAIT && !(correction_enable && !correction_pass) && compute_out_valid && !down_fault;
    out_tag=tag;out_token=compute_token;out_start=16'(output_start);out_count=down_count;
    out_last=down_final && compute_last;out_data=compute_data;
    done_valid=state==DONE;done_tag=tag;
    raw_wr_req_valid=state==WRITE_REQUEST;raw_wr_data_valid=state==WRITE_DATA;raw_wr_rsp_ready=state==WRITE_RESPONSE;
    raw_wr_data=write_beat<10 ? write_packet[int'(write_beat)*64+:64] : 64'b0;
    raw_wr_data_last=write_beat+5'd1==raw_wr_length;raw_wr_strobe=8'hff;
  end



  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      correction_enable<=0;correction_pass<=0;plane_bytes<=0;
      state<=IDLE;tag<=0;tokens<=0;completed_tokens<=0;input_features<=0;intermediate_features<=0;output_features<=0;
      intermediate_start<=0;output_start<=0;activation_base<=0;gate_base<=0;up_base<=0;down_base<=0;intermediate_base<=0;
      activation_stride<=0;gate_shifts<=0;up_shifts<=0;down_shifts<=0;saved_mask<=0;write_packet<=0;write_offset<=0;
      write_low_sum<=0;write_beat<=0;raw_wr_address<=0;raw_wr_length<=0;done_error<=0;
    end else case(state)
      IDLE:if(cfg_valid && cfg_ready)begin
        correction_enable<=cfg_correction_enable;correction_pass<=0;
        plane_bytes<=17'(cfg_tokens)*17'(cfg_intermediate_features);
        tag<=cfg_tag;tokens<=cfg_tokens;input_features<=cfg_input_features;intermediate_features<=cfg_intermediate_features;
        output_features<=cfg_output_features;activation_base<=cfg_activation_base;gate_base<=cfg_gate_base;
        up_base<=cfg_up_base;down_base<=cfg_down_base;intermediate_base<=cfg_intermediate_base;activation_stride<=cfg_activation_stride;
        gate_shifts<=cfg_gate_shifts;up_shifts<=cfg_up_shifts;down_shifts<=cfg_down_shifts;
        intermediate_start<=0;output_start<=0;completed_tokens<=0;done_error<=invalid_config;
        state<=state_t'(invalid_config ? DONE : MASK_WAIT);
      end
      MASK_WAIT:if(mask_valid)begin
        if(invalid_mask)begin done_error<=1;state<=DONE;end
        else begin saved_mask<=mask_bits;completed_tokens<=0;state<=GATE_LAUNCH;end
      end
      GATE_LAUNCH:if(compute_ready)state<=GATE_WAIT;
      GATE_WAIT:begin
        if(compute_done_valid)begin
          if(compute_done_error || compute_done_tag!=tag || completed_tokens!=tokens)begin done_error<=1;state<=DONE;end
          else if(gate_final)begin completed_tokens<=0;output_start<=0;state<=DOWN_LAUNCH;end
          else begin intermediate_start<=intermediate_start+16'(gate_count);state<=MASK_WAIT;end
        end else if(compute_out_valid && compute_out_ready)begin
          if(gate_fault)begin done_error<=1;state<=ERROR_DRAIN;end
          else begin
            write_packet<=compute_down;write_offset<=17'(compute_token)*17'(intermediate_features)+17'(intermediate_start);
            raw_wr_length<=5'(gate_count>>3);write_beat<=0;state<=WRITE_LOW;
          end
        end
      end
      WRITE_LOW:begin write_low_sum<={1'b0,intermediate_base[31:0]}+33'(write_offset);state<=WRITE_HIGH;end
      WRITE_HIGH:begin
        if(write_high_sum[32])begin done_error<=1;state<=ERROR_DRAIN;end
        else begin raw_wr_address<={write_high_sum[31:0],write_low_sum[31:0]};state<=WRITE_REQUEST;end
      end
      WRITE_REQUEST:if(raw_wr_req_ready)state<=WRITE_DATA;
      WRITE_DATA:if(raw_wr_data_ready)begin
        if(raw_wr_data_last)state<=WRITE_RESPONSE;else write_beat<=write_beat+5'd1;
      end
      WRITE_RESPONSE:if(raw_wr_rsp_valid)begin
        if(raw_wr_rsp_error)begin done_error<=1;state<=ERROR_DRAIN;end
        else begin completed_tokens<=completed_tokens+5'd1;state<=GATE_WAIT;end
      end
      DOWN_LAUNCH:if(compute_ready)state<=DOWN_WAIT;
      DOWN_WAIT:begin
        if(compute_done_valid)begin
          if(compute_done_error || compute_done_tag!=tag ||
             completed_tokens!=(correction_enable && !correction_pass ? 5'd0 : tokens))begin done_error<=1;state<=DONE;end
          else if(correction_enable && !correction_pass)begin
            correction_pass<=1;completed_tokens<=0;state<=DOWN_LAUNCH;
          end else if(down_final)state<=DONE;
          else begin
            output_start<=output_start+17'(down_count);completed_tokens<=0;correction_pass<=0;state<=DOWN_LAUNCH;
          end
        end else if(compute_out_valid)begin
          if(down_fault)begin done_error<=1;state<=ERROR_DRAIN;end
          else if(out_ready)completed_tokens<=completed_tokens+5'd1;
        end
      end
      ERROR_DRAIN:if(compute_done_valid)state<=DONE;
      DONE:if(done_ready)state<=IDLE;
      default:begin done_error<=1;state<=ERROR_DRAIN;end
    endcase
  end

  always_comb begin
    compute_cfg_valid=attention_selected ? attention_window && attention_cfg_valid : state==GATE_LAUNCH || state==DOWN_LAUNCH;
    compute_cfg_paired=!attention_selected && launch_paired;
    compute_cfg_packed_weights=PACKED_FEEDFORWARD_WEIGHTS && !attention_selected && (state==GATE_LAUNCH || state==DOWN_LAUNCH);
    compute_cfg_tag=attention_selected ? attention_cfg_tag : tag;
    compute_cfg_tokens=attention_selected ? attention_cfg_tokens : tokens;
    compute_cfg_feature_words=attention_selected ? attention_cfg_feature_words : 10'((launch_paired ? input_features : intermediate_features)>>3);
    compute_cfg_dense_rows=attention_selected ? attention_cfg_dense_rows : (launch_paired ? 17'(intermediate_features) : output_features);
    compute_cfg_count=attention_selected ? attention_cfg_count : (launch_paired ? 8'(gate_count) : down_count);
    compute_cfg_channels=attention_selected ? attention_cfg_channels : (launch_paired ? gate_channels : down_channels);
    compute_cfg_keep=attention_selected ? attention_cfg_keep : compute_keep;
    compute_cfg_activation_base=attention_selected ? attention_cfg_activation_base : (launch_paired ? activation_base : (correction_pass ? correction_base : intermediate_base));
    compute_cfg_weight_base=attention_selected ? attention_cfg_weight_base : (launch_paired ? gate_base : down_base);
    compute_cfg_up_weight_base=up_base;
    compute_cfg_activation_stride=attention_selected ? attention_cfg_activation_stride : (launch_paired ? activation_stride : 32'(intermediate_features));
    compute_cfg_gate_shifts=gate_shifts;
    compute_cfg_up_shifts=up_shifts;
    compute_cfg_down_shifts=down_shifts;
    compute_hold_primary=state==DOWN_LAUNCH ? correction_enable && !correction_pass : operation_hold;
    compute_append_correction=state==DOWN_LAUNCH ? correction_enable && correction_pass : operation_append;
  end

  // Command flags stay live across every feature tile and an error drain.
  // The tensor owner clears them only when the command's terminal transfers.
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin operation_hold<=0;operation_append<=0;end
    else if(compute_cfg_valid && compute_ready)begin
      operation_hold<=compute_hold_primary;operation_append<=compute_append_correction;
    end else if(compute_done_valid && compute_done_ready)begin operation_hold<=0;operation_append<=0;end
  end
  // Registered flush controls cannot pulse when binary state bits transition.
  // Assertion follows the terminal/drain state, when no write remains owned.
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin writer_flush<=1;compute_clear_context<=0;end
    else begin
      writer_flush<=state==ERROR_DRAIN || state==DONE;
      compute_clear_context<=state==DONE && done_error;
    end
  end
  always_comb begin
    correction_base=intermediate_base+64'(plane_bytes);
    writer_rst_n=rst_n && !writer_flush;
    gated_packet=0;
    for(int row=0;row<80;row++)gated_packet[row*16+:16]=compute_data[row*32+:16];
  end
  // ERROR_DRAIN/DONE occur only outside the owned-write states. Clearing a
  // pending packet here cannot abandon an offered/accepted memory transaction.
  tri_oracle_clipping_write_pair intermediate_writer (
    .clk,.rst_n(writer_rst_n),.enable(correction_enable),
    .packet_valid(state==GATE_WAIT && compute_out_valid && !gate_fault && !compute_done_valid),
    .packet_ready(pair_ready),.packet_count(gate_count),
    .packet_shift(down_shifts[int'(compute_token)*6+:6]),.packet_plane_bytes(plane_bytes),.packet_gated(gated_packet),
    .in_req_valid(raw_wr_req_valid),.in_req_ready(raw_wr_req_ready),.in_address(raw_wr_address),.in_length(raw_wr_length),
    .in_data_valid(raw_wr_data_valid),.in_data_ready(raw_wr_data_ready),.in_data(raw_wr_data),
    .in_strobe(raw_wr_strobe),.in_data_last(raw_wr_data_last),
    .in_rsp_valid(raw_wr_rsp_valid),.in_rsp_ready(raw_wr_rsp_ready),.in_rsp_error(raw_wr_rsp_error),
    .mem_req_valid(wr_req_valid),.mem_req_ready(wr_req_ready),.mem_address(wr_address),.mem_length(wr_length),
    .mem_data_valid(wr_data_valid),.mem_data_ready(wr_data_ready),.mem_data(wr_data),
    .mem_strobe(wr_strobe),.mem_data_last(wr_data_last),
    .mem_rsp_valid(wr_rsp_valid),.mem_rsp_ready(wr_rsp_ready),.mem_rsp_error(wr_rsp_error)
  );
endmodule
