`timescale 1ns/1ps
// Stream one feature tile of at most32 words/core for all1..16 tokens.
// The existing input memories use token stride32; all full-feature addresses
// remain original row-major addresses. Native output slots retain partial sums
// across feature tiles. Each activation is read once and broadcast to clusters.
// A128-bit tile summary records whether any token has a nonzero8-byte word.
// All-zero words are cleared locally in weight memory and never fetched.
// One offered request/accepted burst owns its peer through actual LAST, including
// faults. Reset also resets the peer. This is a local control reconstruction;
// no extra memory macros, complete feedforward or paper metrics are implied.
module tri_oracle_batched_stream385 (
  input logic clk,rst_n,cfg_valid,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [4:0] cfg_tokens,
  input logic [9:0] cfg_feature_words,
  input logic [16:0] cfg_dense_rows,
  input logic [7:0] cfg_count,
  input logic [2559:0] cfg_channels,cfg_keep,
  input logic [63:0] cfg_activation_base,cfg_weight_base,
  input logic [31:0] cfg_activation_stride,
  output logic out_valid,
  input logic out_ready,
  output logic [31:0] out_tag,
  output logic [3:0] out_token,
  output logic out_last,
  output logic [7:0] out_count,
  output logic [2559:0] out_channels,
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
  input logic [63:0] rsp_data
);
  typedef enum logic [4:0] {
    IDLE,VALIDATE,LOAD_MASK,ACT_PREPARE,WEIGHT_SELECT,ADDRESS_OFFSET,
    ADDRESS_LOW,ADDRESS_HIGH,REQUEST,RESPONSE,ACT_BROADCAST,NEXT_BURST,
    EXECUTE,WAIT_EXECUTE,DRAIN,FLUSH,DONE,CLEAR_WEIGHTS,WEIGHT_CHUNK
  } state_t;
  state_t state;
  logic [31:0] tag,activation_stride;
  logic [4:0] tokens;
  logic [9:0] feature_words;
  logic [7:0] count,validate_column,part_words,activation_word;
  logic [16:0] dense_rows;
  logic [2559:0] channels,keep;
  logic [63:0] activation_base,weight_base,address_base,activation_buffer;
  logic [64:0] offset;
  logic [32:0] address_low_sum,address_high_sum;
  logic [4:0] mask_core,weight_core;
  logic [3:0] mask_token,activation_token;
  logic [1:0] activation_part;
  logic [2:0] broadcast_cluster;
  logic [4:0] weight_row,beat_index;
  logic [7:0] tile_start;
  logic [5:0] tile_words,chunk_word,clear_word;
  logic [127:0] active_words;
  logic [4:0] active_run;
  logic contiguous,selected_part_active;
  logic [15:0] selected_channel;
  logic activation_mode,flush_second,burst_owned;
  logic invalid_config,selected_row_kept,valid_response;
  logic [64:0] activation_end,weight_end,feature_bytes;
  int logical_row;
  logic owner_rst_n,backend_rst_n,load_valid,load_error;
  logic [4:0] load_core;
  logic [1:0] load_kind;
  logic [9:0] load_addr;
  logic [2047:0] load_data;
  logic [31:0] load_row_enable;
  logic sequence_ready,sequence_out_valid,sequence_done_valid,sequence_done_error;
  logic [31:0] sequence_done_tag;
  logic backend_cmd_valid,backend_cmd_ready,backend_cmd_accumulate;
  logic [4:0] backend_cmd_weight,backend_cmd_mask;
  logic [9:0] backend_cmd_activation;
  logic [3:0] backend_cmd_output;
  logic [4:0] backend_out_valid,backend_out_ready;
  logic [19:0] backend_out_output;
  logic [5119:0] backend_out_data;

  tri_oracle_batched_projection356 sequencer (
    .clk(clk),.rst_n(owner_rst_n),.in_valid(state==EXECUTE),.in_ready(sequence_ready),
    .in_tag(tag),.in_tokens(tokens),.in_weight_base(5'b0),.in_mask_base(5'b0),
    .in_strips(tile_words),.in_activation_base(10'b0),
    .in_activation_stride(11'd32),.in_accumulate(tile_start!=0),
    .in_publish(9'(tile_start)+9'(tile_words)==9'(part_words)),
    .out_valid(sequence_out_valid),.out_ready(out_ready && state==WAIT_EXECUTE),
    .out_tag(out_tag),.out_token(out_token),.out_last(out_last),.out_data(out_data),
    .done_valid(sequence_done_valid),.done_ready(state==WAIT_EXECUTE),
    .done_error(sequence_done_error),.done_tag(sequence_done_tag),.backend_rst_n(backend_rst_n),
    .backend_cmd_valid(backend_cmd_valid),.backend_cmd_ready(backend_cmd_ready),
    .backend_cmd_weight(backend_cmd_weight),.backend_cmd_mask(backend_cmd_mask),
    .backend_cmd_activation(backend_cmd_activation),.backend_cmd_output(backend_cmd_output),
    .backend_cmd_accumulate(backend_cmd_accumulate),.backend_out_valid(backend_out_valid),
    .backend_out_ready(backend_out_ready),.backend_out_output(backend_out_output),
    .backend_out_data(backend_out_data));
  tri_oracle_compute_fabric fabric (
    .clk(clk),.rst_n(backend_rst_n),.load_valid(load_valid),.load_core(load_core),
    .load_kind(load_kind),.load_addr(load_addr),.load_data(load_data),
    .load_row_enable(load_row_enable),.load_error(load_error),
    .cmd_valid(backend_cmd_valid),.cmd_ready(backend_cmd_ready),.cmd_clusters(5'b11111),
    .cmd_weight(backend_cmd_weight),.cmd_mask(backend_cmd_mask),
    .cmd_activation(backend_cmd_activation),.cmd_output(backend_cmd_output),
    .cmd_accumulate(backend_cmd_accumulate),.cmd_reduce(2'b0),
    .out_valid(backend_out_valid),.out_ready(backend_out_ready),
    .out_output(backend_out_output),.out_data(backend_out_data));

  always_comb begin
    feature_bytes=65'(cfg_feature_words)<<3;
    activation_end={1'b0,cfg_activation_base}+(65'(cfg_tokens)-65'd1)*65'(cfg_activation_stride)+feature_bytes-65'd1;
    weight_end={1'b0,cfg_weight_base}+65'(cfg_dense_rows)*feature_bytes-65'd1;
    invalid_config=cfg_tokens==0 || cfg_tokens>16 || cfg_feature_words<4 ||
      cfg_feature_words>1020 || cfg_feature_words[1:0]!=0 ||
      cfg_dense_rows==0 || cfg_dense_rows>65536 || cfg_count==0 || cfg_count>160 ||
      cfg_activation_base[2:0]!=0 || cfg_weight_base[2:0]!=0 ||
      cfg_activation_stride[2:0]!=0 || 65'(cfg_activation_stride)<feature_bytes ||
      activation_end[64] || weight_end[64];
    tile_words=9'(part_words)-9'(tile_start)>32 ? 6'd32 : 6'(part_words-tile_start);
    logical_row=int'(weight_core/4)*32+int'(weight_row);
    selected_row_kept=0;
    for(int token=0;token<16;token++)
      if(token<int'(tokens) && logical_row<int'(count) && keep[token*160+logical_row])selected_row_kept=1;
    selected_part_active=|active_words[int'(weight_core%4)*32+:32];
    active_run=0;contiguous=1;
    for(int word=0;word<16;word++)begin
      if(contiguous && int'(chunk_word)+word<int'(tile_words) && active_words[int'(weight_core%4)*32+int'(chunk_word)+word])
        active_run=active_run+5'd1;
      else contiguous=0;
    end
    address_high_sum={1'b0,address_base[63:32]}+{1'b0,offset[63:32]}+33'(address_low_sum[32]);
    cfg_ready=state==IDLE;
    out_valid=state==WAIT_EXECUTE && sequence_out_valid;
    out_count=count;out_channels=channels;
    done_valid=state==DONE;done_tag=tag;
    req_valid=state==REQUEST;
    rsp_ready=state==RESPONSE || state==DRAIN;
    owner_rst_n=rst_n && state!=FLUSH;
    valid_response=state==RESPONSE && rsp_valid && !rsp_error && rsp_last==(beat_index+5'd1==req_length);
    load_valid=0;load_core=0;load_kind=0;load_addr=0;load_data=0;load_row_enable='1;
    if(state==LOAD_MASK)begin
      load_valid=1;load_core=mask_core;load_kind=2;load_addr=10'(mask_token);
      for(int row=0;row<32;row++)
        if(int'(mask_core/4)*32+row<int'(count) && keep[int'(mask_token)*160+int'(mask_core/4)*32+row])
          load_data[row*8+:8]=8'hff;
    end else if(state==ACT_BROADCAST)begin
      load_valid=1;load_core=5'(broadcast_cluster)*5'd4+5'(activation_part);load_kind=1;
      load_addr=10'(activation_token)*10'd32+10'(activation_word)+10'(beat_index);
      load_data[63:0]=activation_buffer;
    end else if(state==CLEAR_WEIGHTS)begin
      load_valid=!active_words[int'(weight_core%4)*32+int'(clear_word)];
      load_core=weight_core;load_kind=0;load_addr=10'(clear_word);
    end else if(valid_response && !activation_mode)begin
      load_valid=1;load_core=weight_core;load_kind=0;
      load_addr=10'(chunk_word)+10'(beat_index);
      load_row_enable=32'b1<<weight_row;
      load_data[int'(weight_row)*64+:64]=rsp_data;
    end
  end

  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      state<=IDLE;tag<=0;tokens<=0;feature_words<=0;part_words<=0;dense_rows<=0;count<=0;
      channels<=0;keep<=0;activation_base<=0;weight_base<=0;activation_stride<=0;
      validate_column<=0;mask_core<=0;mask_token<=0;activation_token<=0;activation_part<=0;
      activation_word<=0;activation_mode<=0;activation_buffer<=0;broadcast_cluster<=0;
      weight_core<=0;weight_row<=0;tile_start<=0;chunk_word<=0;selected_channel<=0;
      offset<=0;address_base<=0;address_low_sum<=0;req_address<=0;req_length<=0;beat_index<=0;
      done_error<=0;flush_second<=0;burst_owned<=0;active_words<=0;clear_word<=0;
    end else begin
      // Ownership ends only at an actually accepted LAST, including malformed
      // response bursts. Local broadcast cycles do not end a peer transaction.
      if(state==REQUEST && req_ready)burst_owned<=1;
      if(rsp_valid && rsp_ready && rsp_last)burst_owned<=0;
      case(state)
        IDLE:if(cfg_valid)begin
          tag<=cfg_tag;tokens<=cfg_tokens;feature_words<=cfg_feature_words;part_words<=8'(cfg_feature_words>>2);
          dense_rows<=cfg_dense_rows;count<=cfg_count;channels<=cfg_channels;keep<=cfg_keep;
          activation_base<=cfg_activation_base;weight_base<=cfg_weight_base;activation_stride<=cfg_activation_stride;
          validate_column<=0;mask_core<=0;mask_token<=0;activation_token<=0;activation_part<=0;
          activation_word<=0;weight_core<=0;weight_row<=0;tile_start<=0;chunk_word<=0;
          done_error<=invalid_config;flush_second<=0;active_words<=0;clear_word<=0;
          state<=invalid_config ? FLUSH : VALIDATE;
        end
        VALIDATE:begin
          if(17'(channels[int'(validate_column)*16+:16])>=dense_rows)begin
            done_error<=1;flush_second<=0;state<=FLUSH;
          end else if(validate_column+8'd1==count)state<=LOAD_MASK;
          else validate_column<=validate_column+8'd1;
        end
        LOAD_MASK:begin
          if(5'(mask_token)+5'd1==tokens)begin
            mask_token<=0;
            if(mask_core==19)state<=ACT_PREPARE;
            else mask_core<=mask_core+5'd1;
          end else mask_token<=mask_token+4'd1;
        end
        ACT_PREPARE:begin activation_mode<=1;state<=ADDRESS_OFFSET;end
        WEIGHT_SELECT:begin
          activation_mode<=0;
          if(selected_row_kept && selected_part_active)begin
            selected_channel<=channels[logical_row*16+:16];chunk_word<=0;state<=WEIGHT_CHUNK;
          end else if(weight_row==31)begin
            weight_row<=0;
            if(weight_core==19)state<=EXECUTE;
            else weight_core<=weight_core+5'd1;
          end else weight_row<=weight_row+5'd1;
        end
        ADDRESS_OFFSET:begin
          if(activation_mode)begin
            offset<=65'(activation_token)*65'(activation_stride)
              +((65'(activation_part)*65'(part_words)+65'(tile_start)+65'(activation_word))<<3);
            address_base<=activation_base;
            req_length<=7'(tile_words)-7'(activation_word)>16 ? 5'd16 : 5'(tile_words-activation_word);
          end else begin
            offset<=(65'(selected_channel)*65'(feature_words)+65'(weight_core%4)*65'(part_words)
                     +65'(tile_start)+65'(chunk_word))<<3;
            address_base<=weight_base;
            req_length<=active_run;
          end
          state<=ADDRESS_LOW;
        end
        ADDRESS_LOW:begin
          address_low_sum<={1'b0,address_base[31:0]}+{1'b0,offset[31:0]};state<=ADDRESS_HIGH;
        end
        ADDRESS_HIGH:begin
          if(offset[64] || address_high_sum[32])begin done_error<=1;flush_second<=0;state<=FLUSH;end
          else begin req_address<={address_high_sum[31:0],address_low_sum[31:0]};state<=REQUEST;end
        end
        REQUEST:if(req_ready)begin beat_index<=0;state<=done_error ? DRAIN : RESPONSE;end
        RESPONSE:if(rsp_valid)begin
          if(!valid_response)begin
            done_error<=1;flush_second<=0;state<=rsp_last ? FLUSH : DRAIN;
          end else if(activation_mode)begin
            active_words[int'(activation_part)*32+int'(activation_word)+int'(beat_index)]<=
              active_words[int'(activation_part)*32+int'(activation_word)+int'(beat_index)] || (|rsp_data);
            activation_buffer<=rsp_data;broadcast_cluster<=0;state<=ACT_BROADCAST;
          end else if(rsp_last)state<=NEXT_BURST;
          else beat_index<=beat_index+5'd1;
        end
        ACT_BROADCAST:begin
          if(broadcast_cluster==4)begin
            if(beat_index+5'd1==req_length)state<=NEXT_BURST;
            else begin beat_index<=beat_index+5'd1;state<=RESPONSE;end
          end else broadcast_cluster<=broadcast_cluster+3'd1;
        end
        NEXT_BURST:begin
          if(activation_mode)begin
            if(9'(activation_word)+9'(req_length)==9'(tile_words))begin
              activation_word<=0;
              if(activation_part==3)begin
                activation_part<=0;
                if(5'(activation_token)+5'd1==tokens)begin
                  activation_mode<=0;weight_core<=0;clear_word<=0;state<=CLEAR_WEIGHTS;
                end else begin activation_token<=activation_token+4'd1;state<=ADDRESS_OFFSET;end
              end else begin activation_part<=activation_part+2'd1;state<=ADDRESS_OFFSET;end
            end else begin activation_word<=activation_word+8'(req_length);state<=ADDRESS_OFFSET;end
          end else begin chunk_word<=chunk_word+6'(req_length);state<=WEIGHT_CHUNK;end
        end
        CLEAR_WEIGHTS:begin
          if(clear_word+6'd1==tile_words)begin
            clear_word<=0;
            if(weight_core==19)begin weight_core<=0;weight_row<=0;chunk_word<=0;state<=WEIGHT_SELECT;end
            else weight_core<=weight_core+5'd1;
          end else clear_word<=clear_word+6'd1;
        end
        WEIGHT_CHUNK:begin
          if(chunk_word>=tile_words)begin
            chunk_word<=0;state<=WEIGHT_SELECT;
            if(weight_row==31)begin
              weight_row<=0;
              if(weight_core==19)state<=EXECUTE;
              else weight_core<=weight_core+5'd1;
            end else weight_row<=weight_row+5'd1;
          end else if(!active_words[int'(weight_core%4)*32+int'(chunk_word)])chunk_word<=chunk_word+6'd1;
          else state<=ADDRESS_OFFSET;
        end
        EXECUTE:if(sequence_ready)state<=WAIT_EXECUTE;
        WAIT_EXECUTE:if(sequence_done_valid)begin
          if(sequence_done_error || sequence_done_tag!=tag)begin done_error<=1;flush_second<=0;state<=FLUSH;end
          else if(9'(tile_start)+9'(tile_words)==9'(part_words))state<=DONE;
          else begin
            tile_start<=tile_start+8'(tile_words);weight_core<=0;weight_row<=0;chunk_word<=0;
            activation_token<=0;activation_part<=0;activation_word<=0;active_words<=0;state<=ACT_PREPARE;
          end
        end
        DRAIN:if(rsp_valid && rsp_last)begin flush_second<=0;state<=FLUSH;end
        FLUSH:if(flush_second)state<=DONE;else flush_second<=1;
        DONE:if(done_ready)state<=IDLE;
        default:begin done_error<=1;flush_second<=0;state<=FLUSH;end
      endcase
      if(load_error && state!=IDLE && state!=DONE && state!=FLUSH)begin
        done_error<=1;flush_second<=0;
        if(state==REQUEST)begin
          // Once offered, keep request metadata/valid stable until accepted;
          // an error latched during that stall must drain the accepted burst.
          if(req_ready)state<=DRAIN;
        end else if(burst_owned && !(rsp_valid && rsp_ready && rsp_last))state<=DRAIN;
        else state<=FLUSH;
      end
    end
  end
endmodule
