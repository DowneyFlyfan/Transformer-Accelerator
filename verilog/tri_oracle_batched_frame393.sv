`timescale 1ns/1ps
// Complete batched feedforward scheduling on one twenty-core fabric.
// Prepared mask packets cover consecutive groups of up to80 original channels.
// Quantized gated codes are written to a caller-owned external intermediate
// allocation. Every write response is accepted before that region is read.
// Output groups have up to160 original rows; terminal error invalidates every
// earlier output packet of this frame. Reset also resets both memory peers.
// A raw tensor command uses the existing ordinary (non-paired) mode.
// The requester holds valid and its descriptor until accepted, and keeps
// ownership of the packet and terminal channels through the terminal transfer.
interface tri_oracle_attention_tensor437;
  logic cfg_valid, cfg_ready;
  logic [31:0] cfg_tag, cfg_activation_stride;
  logic [4:0] cfg_tokens;
  logic [9:0] cfg_feature_words;
  logic [16:0] cfg_dense_rows;
  logic [7:0] cfg_count;
  logic [2559:0] cfg_channels, cfg_keep;
  logic [63:0] cfg_activation_base, cfg_weight_base;
  logic out_valid, out_ready, out_last;
  logic [31:0] out_tag;
  logic [3:0] out_token;
  logic [7:0] out_count;
  logic [2559:0] out_channels;
  logic [5119:0] out_data;
  logic done_valid, done_ready, done_error;
  logic [31:0] done_tag;

  modport server (
    input cfg_valid, cfg_tag, cfg_activation_stride, cfg_tokens, cfg_feature_words,
          cfg_dense_rows, cfg_count, cfg_channels, cfg_keep, cfg_activation_base,
          cfg_weight_base, out_ready, done_ready,
    output cfg_ready, out_valid, out_last, out_tag, out_token, out_count, out_channels,
           out_data, done_valid, done_error, done_tag
  );
endinterface

module tri_oracle_batched_frame393 (
  input logic clk,rst_n,cfg_valid,
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
  output logic req_valid,
  input logic req_ready,
  output logic [63:0] req_address,
  output logic [4:0] req_length,
  input logic rsp_valid,
  output logic rsp_ready,
  input logic rsp_last,rsp_error,
  input logic [63:0] rsp_data,
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
  output logic wr_rsp_ready
);
  tri_oracle_attention_tensor437 unused_attention();
  assign {unused_attention.cfg_valid, unused_attention.cfg_tag, unused_attention.cfg_activation_stride,
          unused_attention.cfg_tokens, unused_attention.cfg_feature_words, unused_attention.cfg_dense_rows,
          unused_attention.cfg_count, unused_attention.cfg_channels, unused_attention.cfg_keep,
          unused_attention.cfg_activation_base, unused_attention.cfg_weight_base,
          unused_attention.out_ready, unused_attention.done_ready} = '0;
  tri_oracle_batched_frame437 implementation (.attention(unused_attention), .attention_enable(1'b0), .merge_sign_data('0), .merge_sign_control('0), .merge_sign_counts(), .*);
endmodule

module tri_oracle_batched_frame437 #(
  parameter bit AGGREGATOR_SIGN_BANK=0
) (
  input logic clk,rst_n,cfg_valid,
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
  output logic req_valid,
  input logic req_ready,
  output logic [63:0] req_address,
  output logic [4:0] req_length,
  input logic rsp_valid,
  output logic rsp_ready,
  input logic rsp_last,rsp_error,
  input logic [63:0] rsp_data,
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
  input logic attention_enable,
  tri_oracle_attention_tensor437.server attention,
  input logic [2047:0] merge_sign_data,
  input logic [12:0] merge_sign_control,
  output logic [119:0] merge_sign_counts
);
  typedef enum logic [3:0] {IDLE,MASK_WAIT,GATE_LAUNCH,GATE_WAIT,WRITE_LOW,WRITE_HIGH,
    WRITE_REQUEST,WRITE_DATA,WRITE_RESPONSE,DOWN_LAUNCH,DOWN_WAIT,ERROR_DRAIN,DONE} state_t;
  state_t state;
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
  logic [2559:0] gate_channels,down_channels,compute_keep;
  logic compute_ready,compute_out_valid,compute_out_ready,compute_last;
  logic compute_done_valid,compute_done_ready,compute_done_error;
  logic [31:0] compute_tag,compute_done_tag;
  logic [3:0] compute_token;
  logic [7:0] compute_count;
  logic [2559:0] compute_channels;
  logic [5119:0] compute_data;
  logic [639:0] compute_down;
  logic attention_owned, attention_window, attention_selected;

  // Frame scheduling owns every command outside Idle. An admitted attention
  // command holds its packet and terminal channels even if its request changes.
  assign attention_window = attention_enable && state == IDLE && !attention_owned;
  assign attention_selected = attention_owned || (attention_window && attention.cfg_valid);
  assign attention.cfg_ready = attention_window && compute_ready;
  assign attention.out_valid = attention_owned && compute_out_valid;
  assign attention.out_tag = compute_tag;
  assign attention.out_token = compute_token;
  assign attention.out_last = compute_last;
  assign attention.out_count = compute_count;
  assign attention.out_channels = compute_channels;
  assign attention.out_data = compute_data;
  assign attention.done_valid = attention_owned && compute_done_valid;
  assign attention.done_error = compute_done_error;
  assign attention.done_tag = compute_done_tag;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) attention_owned <= 0;
    else if (attention.cfg_valid && attention.cfg_ready) attention_owned <= 1;
    else if (attention.done_valid && attention.done_ready) attention_owned <= 0;
  end

  function automatic logic overlaps(input logic [64:0] first_base,first_end,second_base,second_end);
    return first_base<=second_end && second_base<=first_end;
  endfunction
  always_comb begin
    activation_end={1'b0,cfg_activation_base}+(65'(cfg_tokens)-65'd1)*65'(cfg_activation_stride)+65'(cfg_input_features)-65'd1;
    gate_end={1'b0,cfg_gate_base}+65'(cfg_intermediate_features)*65'(cfg_input_features)-65'd1;
    up_end={1'b0,cfg_up_base}+65'(cfg_intermediate_features)*65'(cfg_input_features)-65'd1;
    down_end={1'b0,cfg_down_base}+65'(cfg_output_features)*65'(cfg_intermediate_features)-65'd1;
    intermediate_end={1'b0,cfg_intermediate_base}+65'(cfg_tokens)*65'(cfg_intermediate_features)-65'd1;
    invalid_config=cfg_tokens==0 || cfg_tokens>16 || cfg_input_features<32 || cfg_input_features>8160 ||
      cfg_intermediate_features<32 || cfg_intermediate_features>8160 || cfg_input_features[4:0]!=0 ||
      cfg_intermediate_features[4:0]!=0 || cfg_output_features==0 || cfg_output_features>65536 ||
      cfg_activation_base[2:0]!=0 || cfg_gate_base[2:0]!=0 || cfg_up_base[2:0]!=0 || cfg_down_base[2:0]!=0 ||
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
    down_fault=compute_tag!=tag || compute_count!=down_count || compute_channels!=down_channels ||
      compute_token!=4'(completed_tokens) || completed_tokens>=tokens || compute_last!=(completed_tokens+5'd1==tokens);
    write_high_sum={1'b0,intermediate_base[63:32]}+33'(write_low_sum[32]);
    cfg_ready=state==IDLE && !attention_selected && compute_ready;mask_ready=state==MASK_WAIT;
    compute_out_ready=state==GATE_WAIT || state==ERROR_DRAIN || (state==DOWN_WAIT && (down_fault || out_ready));
    compute_done_ready=state==GATE_WAIT || state==DOWN_WAIT || state==ERROR_DRAIN;
    out_valid=state==DOWN_WAIT && compute_out_valid && !down_fault;
    out_tag=tag;out_token=compute_token;out_start=16'(output_start);out_count=down_count;
    out_last=down_final && compute_last;out_data=compute_data;
    done_valid=state==DONE;done_tag=tag;
    wr_req_valid=state==WRITE_REQUEST;wr_data_valid=state==WRITE_DATA;wr_rsp_ready=state==WRITE_RESPONSE;
    wr_data=write_beat<10 ? write_packet[int'(write_beat)*64+:64] : 64'b0;
    wr_data_last=write_beat+5'd1==wr_length;wr_strobe=8'hff;
  end

  tri_oracle_batched_shared392 #(.AGGREGATOR_SIGN_BANK(AGGREGATOR_SIGN_BANK)) compute (
    .merge_sign_data,.merge_sign_control,.merge_sign_counts,
    .clk(clk),.rst_n(rst_n),
    .cfg_valid(attention_selected ? attention_window && attention.cfg_valid : state==GATE_LAUNCH || state==DOWN_LAUNCH),
    .cfg_ready(compute_ready),.cfg_paired(!attention_selected && launch_paired),
    .cfg_tag(attention_selected ? attention.cfg_tag : tag),
    .cfg_tokens(attention_selected ? attention.cfg_tokens : tokens),
    .cfg_feature_words(attention_selected ? attention.cfg_feature_words : 10'((launch_paired ? input_features : intermediate_features)>>3)),
    .cfg_dense_rows(attention_selected ? attention.cfg_dense_rows : (launch_paired ? 17'(intermediate_features) : output_features)),
    .cfg_count(attention_selected ? attention.cfg_count : (launch_paired ? 8'(gate_count) : down_count)),
    .cfg_channels(attention_selected ? attention.cfg_channels : (launch_paired ? gate_channels : down_channels)),
    .cfg_keep(attention_selected ? attention.cfg_keep : compute_keep),
    .cfg_activation_base(attention_selected ? attention.cfg_activation_base : (launch_paired ? activation_base : intermediate_base)),
    .cfg_weight_base(attention_selected ? attention.cfg_weight_base : (launch_paired ? gate_base : down_base)),
    .cfg_up_weight_base(up_base),
    .cfg_activation_stride(attention_selected ? attention.cfg_activation_stride : (launch_paired ? activation_stride : 32'(intermediate_features))),
    .cfg_gate_shifts(gate_shifts),.cfg_up_shifts(up_shifts),.cfg_down_shifts(down_shifts),
    .out_valid(compute_out_valid),.out_ready(attention_owned ? attention.out_ready : compute_out_ready),.out_tag(compute_tag),.out_token(compute_token),
    .out_last(compute_last),.out_count(compute_count),.out_channels(compute_channels),.out_data(compute_data),.out_down_input(compute_down),
    .done_valid(compute_done_valid),.done_ready(attention_owned ? attention.done_ready : compute_done_ready),
    .done_error(compute_done_error),.done_tag(compute_done_tag),
    .req_valid(req_valid),.req_ready(req_ready),.req_address(req_address),.req_length(req_length),
    .rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_last(rsp_last),.rsp_error(rsp_error),.rsp_data(rsp_data));

  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      state<=IDLE;tag<=0;tokens<=0;completed_tokens<=0;input_features<=0;intermediate_features<=0;output_features<=0;
      intermediate_start<=0;output_start<=0;activation_base<=0;gate_base<=0;up_base<=0;down_base<=0;intermediate_base<=0;
      activation_stride<=0;gate_shifts<=0;up_shifts<=0;down_shifts<=0;saved_mask<=0;write_packet<=0;write_offset<=0;
      write_low_sum<=0;write_beat<=0;wr_address<=0;wr_length<=0;done_error<=0;
    end else case(state)
      IDLE:if(cfg_valid && cfg_ready)begin
        tag<=cfg_tag;tokens<=cfg_tokens;input_features<=cfg_input_features;intermediate_features<=cfg_intermediate_features;
        output_features<=cfg_output_features;activation_base<=cfg_activation_base;gate_base<=cfg_gate_base;
        up_base<=cfg_up_base;down_base<=cfg_down_base;intermediate_base<=cfg_intermediate_base;activation_stride<=cfg_activation_stride;
        gate_shifts<=cfg_gate_shifts;up_shifts<=cfg_up_shifts;down_shifts<=cfg_down_shifts;
        intermediate_start<=0;output_start<=0;completed_tokens<=0;done_error<=invalid_config;
        state<=invalid_config ? DONE : MASK_WAIT;
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
        end else if(compute_out_valid)begin
          if(gate_fault)begin done_error<=1;state<=ERROR_DRAIN;end
          else begin
            write_packet<=compute_down;write_offset<=17'(compute_token)*17'(intermediate_features)+17'(intermediate_start);
            wr_length<=5'(gate_count>>3);write_beat<=0;state<=WRITE_LOW;
          end
        end
      end
      WRITE_LOW:begin write_low_sum<={1'b0,intermediate_base[31:0]}+33'(write_offset);state<=WRITE_HIGH;end
      WRITE_HIGH:begin
        if(write_high_sum[32])begin done_error<=1;state<=ERROR_DRAIN;end
        else begin wr_address<={write_high_sum[31:0],write_low_sum[31:0]};state<=WRITE_REQUEST;end
      end
      WRITE_REQUEST:if(wr_req_ready)state<=WRITE_DATA;
      WRITE_DATA:if(wr_data_ready)begin
        if(wr_data_last)state<=WRITE_RESPONSE;else write_beat<=write_beat+5'd1;
      end
      WRITE_RESPONSE:if(wr_rsp_valid)begin
        if(wr_rsp_error)begin done_error<=1;state<=ERROR_DRAIN;end
        else begin completed_tokens<=completed_tokens+5'd1;state<=GATE_WAIT;end
      end
      DOWN_LAUNCH:if(compute_ready)state<=DOWN_WAIT;
      DOWN_WAIT:begin
        if(compute_done_valid)begin
          if(compute_done_error || compute_done_tag!=tag || completed_tokens!=tokens)begin done_error<=1;state<=DONE;end
          else if(down_final)state<=DONE;
          else begin output_start<=output_start+17'(down_count);completed_tokens<=0;state<=DOWN_LAUNCH;end
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
endmodule
