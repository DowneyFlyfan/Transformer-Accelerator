`timescale 1ns/1ps
// One physical compute fabric for both paired gate/up and down projection.
// Paired mode maps each cluster's low16 rows to gate and high16 to up, sharing
// one logical channel and mask. Ordinary mode keeps all32 independent rows.
// Both modes stream32-word feature tiles and retain native partial sums.
// Logical keep masks have a fixed160-column stride in both modes. Requests
// retain ownership through accepted LAST; reset must also reset the peer.
module tri_oracle_external_row_tensor (
  input logic clk,rst_n,cfg_valid,cfg_paired,
  input logic cfg_hold_primary,cfg_append_correction,cfg_clear_context,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [4:0] cfg_tokens,
  input logic [9:0] cfg_feature_words,
  input logic [16:0] cfg_dense_rows,
  input logic [7:0] cfg_count,
  input logic [2559:0] cfg_channels,cfg_keep,
  input logic [63:0] cfg_activation_base,cfg_weight_base,cfg_up_weight_base,
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
  input logic [63:0] rsp_data,
  input tri_oracle_wac_softmax_types::request_t softmax_request,
  output logic backend_rst_n,
  output logic load_valid,
  input logic load_error,
  output logic [4:0] load_core,
  output logic [1:0] load_kind,
  output logic [9:0] load_addr,
  output logic [2047:0] load_data,
  output logic [31:0] load_row_enable,
  output logic backend_cmd_valid,
  input logic backend_cmd_ready,
  output logic [4:0] backend_clusters,backend_cmd_weight,backend_cmd_mask,
  output logic [9:0] backend_cmd_activation,
  output logic [3:0] backend_cmd_output,
  output logic backend_cmd_accumulate,
  output logic [1:0] backend_cmd_reduce,
  output logic [2:0] backend_core_select,
  output logic [4:0] backend_activation_reloaded,
  input logic [4:0] backend_out_valid,
  output logic [4:0] backend_out_ready,
  input logic [19:0] backend_out_output,
  input logic [5119:0] backend_out_data
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
  logic [63:0] activation_base,weight_base,up_weight_base,address_base,activation_buffer;
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
  logic activation_mode,flush_second,burst_owned,paired;
  logic invalid_config,selected_row_kept,valid_response;
  logic [64:0] activation_end,weight_end,up_end,feature_bytes;
  int logical_row;
  logic owner_rst_n;
  // The existing descriptor registers are the retained ownership key. No
  // second channel/mask tensor is stored for the correction command.
  logic hold_primary,append_correction,held_context_valid;
  logic [64:0] expected_correction_base,next_plane_base;
  logic append_matches;






  logic sequence_ready,sequence_out_valid,sequence_done_valid,sequence_done_error;
  logic [31:0] sequence_done_tag;







  logic local_scores, single_core_scores;
  logic [1:0] score_core, weight_part;
  logic [2:0] score_cluster, first_cluster, last_cluster;
  logic [4:0] first_core, last_core;
  logic [5119:0] sequence_data;

  assign first_cluster = local_scores ? score_cluster : 3'd0;
  assign last_cluster = local_scores ? score_cluster : 3'd4;
  assign first_core = {first_cluster, single_core_scores ? score_core : 2'b00};
  assign last_core = {last_cluster, single_core_scores ? score_core : 2'b11};
  assign weight_part = single_core_scores ? 2'd0 : weight_core[1:0];
  assign backend_clusters = local_scores ? 5'b1 << score_cluster : 5'b11111;
  assign out_data = local_scores ? {4096'b0, sequence_data[1024*int'(score_cluster)+:1024]} : sequence_data;


  tri_oracle_batched_projection356 sequencer (
    .clk(clk),.rst_n(owner_rst_n),.in_valid(state==EXECUTE),.in_ready(sequence_ready),
    .in_tag(tag),.in_tokens(tokens),.in_weight_base(5'b0),.in_mask_base(5'b0),
    .in_strips(tile_words),.in_clusters(backend_clusters),.in_activation_base(10'b0),
    .in_activation_stride(11'd32),.in_accumulate(tile_start!=0 || append_correction),
    .in_publish(!hold_primary && 9'(tile_start)+9'(tile_words)==9'(part_words)),
    .out_valid(sequence_out_valid),.out_ready(out_ready && state==WAIT_EXECUTE),
    .out_tag(out_tag),.out_token(out_token),.out_last(out_last),.out_data(sequence_data),
    .done_valid(sequence_done_valid),.done_ready(state==WAIT_EXECUTE),
    .done_error(sequence_done_error),.done_tag(sequence_done_tag),.backend_rst_n(backend_rst_n),
    .backend_cmd_valid(backend_cmd_valid),.backend_cmd_ready(backend_cmd_ready),
    .backend_cmd_weight(backend_cmd_weight),.backend_cmd_mask(backend_cmd_mask),
    .backend_cmd_activation(backend_cmd_activation),.backend_cmd_output(backend_cmd_output),
    .backend_cmd_accumulate(backend_cmd_accumulate),.backend_out_valid(backend_out_valid),
    .backend_out_ready(backend_out_ready),.backend_out_output(backend_out_output),
    .backend_out_data(backend_out_data));
  // Connections formerly bound directly to the sole internal fabric.
  assign backend_core_select={single_core_scores,score_core};
  assign backend_cmd_reduce=2'b0;
  assign backend_activation_reloaded=state==EXECUTE && sequence_ready ? backend_clusters : '0;


  always_comb begin
    next_plane_base={1'b0,cfg_activation_base}+65'(cfg_tokens)*65'(cfg_activation_stride);
    append_matches=held_context_valid && !cfg_paired && !cfg_hold_primary &&
      !softmax_request.score_tile && !softmax_request.score_core &&
      cfg_tag==tag && cfg_tokens==tokens && cfg_feature_words==feature_words &&
      cfg_dense_rows==dense_rows && cfg_count==count && cfg_channels==channels && cfg_keep==keep &&
      cfg_weight_base==weight_base && cfg_up_weight_base==up_weight_base &&
      cfg_activation_stride==activation_stride && !expected_correction_base[64] &&
      {1'b0,cfg_activation_base}==expected_correction_base;
    feature_bytes=65'(cfg_feature_words)<<3;
    activation_end={1'b0,cfg_activation_base}+(65'(cfg_tokens)-65'd1)*65'(cfg_activation_stride)+feature_bytes-65'd1;
    weight_end={1'b0,cfg_weight_base}+65'(cfg_dense_rows)*feature_bytes-65'd1;
    up_end={1'b0,cfg_up_weight_base}+65'(cfg_dense_rows)*feature_bytes-65'd1;
    invalid_config=cfg_tokens==0 || cfg_tokens>16 || cfg_feature_words<4 ||
      cfg_feature_words>1020 || cfg_feature_words[1:0]!=0 ||
      cfg_dense_rows==0 || cfg_dense_rows>65536 || cfg_count==0 || cfg_count>160 || (cfg_paired && cfg_count>80) ||
      cfg_activation_base[2:0]!=0 || cfg_weight_base[2:0]!=0 ||
      cfg_activation_stride[2:0]!=0 || 65'(cfg_activation_stride)<feature_bytes ||
      activation_end[64] || weight_end[64] || (cfg_paired && (cfg_up_weight_base[2:0]!=0 || up_end[64]));
    invalid_config=invalid_config || (softmax_request.score_tile &&
      (cfg_paired || cfg_count>32 || cfg_tokens!=1 || softmax_request.owner>=20));
    invalid_config=invalid_config || (softmax_request.score_core &&
      (!softmax_request.score_tile || cfg_feature_words>32));
    invalid_config=invalid_config ||
      (cfg_append_correction && !append_matches) ||
      (held_context_valid && !cfg_append_correction) ||
      (cfg_hold_primary && (cfg_paired || cfg_append_correction || softmax_request.score_tile ||
        softmax_request.score_core || next_plane_base[64]));
    tile_words=9'(part_words)-9'(tile_start)>32 ? 6'd32 : 6'(part_words-tile_start);
    logical_row=paired ? int'(weight_core/4)*16+int'(weight_row[3:0]) : (local_scores ? 0 : int'(weight_core/4)*32)+int'(weight_row);
    selected_row_kept=0;
    for(int token=0;token<16;token++)
      if(token<int'(tokens) && logical_row<int'(count) && keep[token*160+logical_row])selected_row_kept=1;
    selected_part_active=|active_words[int'(weight_part)*32+:32];
    active_run=0;contiguous=1;
    for(int word=0;word<16;word++)begin
      if(contiguous && int'(chunk_word)+word<int'(tile_words) && active_words[int'(weight_part)*32+int'(chunk_word)+word])
        active_run=active_run+5'd1;
      else contiguous=0;
    end
    address_high_sum={1'b0,address_base[63:32]}+{1'b0,offset[63:32]}+33'(address_low_sum[32]);
    cfg_ready=rst_n && state==IDLE && !cfg_clear_context;
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
      for(int row=0;row<32;row++)begin
        int logical_mask_row;
        logical_mask_row=paired ? int'(mask_core/4)*16+(row%16) : (local_scores ? 0 : int'(mask_core/4)*32)+row;
        if(logical_mask_row<int'(count) && keep[int'(mask_token)*160+logical_mask_row])
          load_data[row*8+:8]=8'hff;
      end
    end else if(state==ACT_BROADCAST)begin
      load_valid=1;load_core=single_core_scores ? first_core : {broadcast_cluster, activation_part};load_kind=1;
      load_addr=10'(activation_token)*10'd32+10'(activation_word)+10'(beat_index);
      load_data[63:0]=activation_buffer;
    end else if(state==CLEAR_WEIGHTS)begin
      load_valid=!active_words[int'(weight_part)*32+int'(clear_word)];
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
      hold_primary<=0;append_correction<=0;held_context_valid<=0;expected_correction_base<=0;
      local_scores<=0;score_cluster<=0;single_core_scores<=0;score_core<=0;
      state<=IDLE;tag<=0;tokens<=0;feature_words<=0;part_words<=0;dense_rows<=0;count<=0;
      channels<=0;keep<=0;activation_base<=0;weight_base<=0;up_weight_base<=0;activation_stride<=0;paired<=0;
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
        IDLE:if(cfg_valid && cfg_ready)begin
          hold_primary<=cfg_hold_primary;append_correction<=cfg_append_correction;
          held_context_valid<=0;expected_correction_base<=next_plane_base;
          local_scores<=softmax_request.score_tile;score_cluster<=softmax_request.owner[4:2];
          single_core_scores<=softmax_request.score_core;score_core<=softmax_request.owner[1:0];
          tag<=cfg_tag;tokens<=cfg_tokens;feature_words<=cfg_feature_words;part_words<=8'(softmax_request.score_core ? cfg_feature_words : cfg_feature_words>>2);
          dense_rows<=cfg_dense_rows;count<=cfg_count;channels<=cfg_channels;keep<=cfg_keep;
          activation_base<=cfg_activation_base;weight_base<=cfg_weight_base;up_weight_base<=cfg_up_weight_base;
          activation_stride<=cfg_activation_stride;paired<=cfg_paired;
          validate_column<=0;
          mask_core<=softmax_request.score_tile ? {softmax_request.owner[4:2],
              softmax_request.score_core ? softmax_request.owner[1:0] : 2'b00} : 5'd0;mask_token<=0;activation_token<=0;activation_part<=0;
          activation_word<=0;weight_core<=0;weight_row<=0;tile_start<=0;chunk_word<=0;
          done_error<=invalid_config;flush_second<=0;active_words<=0;clear_word<=0;
          state<=state_t'(invalid_config ? FLUSH : VALIDATE);
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
            if(mask_core==last_core)state<=ACT_PREPARE;
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
            if(weight_core==last_core)state<=EXECUTE;
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
            offset<=(65'(selected_channel)*65'(feature_words)+65'(weight_part)*65'(part_words)
                     +65'(tile_start)+65'(chunk_word))<<3;
            address_base<=paired && weight_row[4] ? up_weight_base : weight_base;
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
        REQUEST:if(req_ready)begin beat_index<=0;state<=state_t'(done_error ? DRAIN : RESPONSE);end
        RESPONSE:if(rsp_valid)begin
          if(!valid_response)begin
            done_error<=1;flush_second<=0;state<=state_t'(rsp_last ? FLUSH : DRAIN);
          end else if(activation_mode)begin
            active_words[int'(activation_part)*32+int'(activation_word)+int'(beat_index)]<=
              active_words[int'(activation_part)*32+int'(activation_word)+int'(beat_index)] || (|rsp_data);
            activation_buffer<=rsp_data;broadcast_cluster<=first_cluster;state<=ACT_BROADCAST;
          end else if(rsp_last)state<=NEXT_BURST;
          else beat_index<=beat_index+5'd1;
        end
        ACT_BROADCAST:begin
          if(broadcast_cluster==last_cluster)begin
            if(beat_index+5'd1==req_length)state<=NEXT_BURST;
            else begin beat_index<=beat_index+5'd1;state<=RESPONSE;end
          end else broadcast_cluster<=broadcast_cluster+3'd1;
        end
        NEXT_BURST:begin
          if(activation_mode)begin
            if(9'(activation_word)+9'(req_length)==9'(tile_words))begin
              activation_word<=0;
              if(single_core_scores || activation_part==3)begin
                activation_part<=0;
                if(5'(activation_token)+5'd1==tokens)begin
                  activation_mode<=0;weight_core<=first_core;clear_word<=0;state<=CLEAR_WEIGHTS;
                end else begin activation_token<=activation_token+4'd1;state<=ADDRESS_OFFSET;end
              end else begin activation_part<=activation_part+2'd1;state<=ADDRESS_OFFSET;end
            end else begin activation_word<=activation_word+8'(req_length);state<=ADDRESS_OFFSET;end
          end else begin chunk_word<=chunk_word+6'(req_length);state<=WEIGHT_CHUNK;end
        end
        CLEAR_WEIGHTS:begin
          if(clear_word+6'd1==tile_words)begin
            clear_word<=0;
            if(weight_core==last_core)begin weight_core<=first_core;weight_row<=0;chunk_word<=0;state<=WEIGHT_SELECT;end
            else weight_core<=weight_core+5'd1;
          end else clear_word<=clear_word+6'd1;
        end
        WEIGHT_CHUNK:begin
          if(chunk_word>=tile_words)begin
            chunk_word<=0;state<=WEIGHT_SELECT;
            if(weight_row==31)begin
              weight_row<=0;
              if(weight_core==last_core)state<=EXECUTE;
              else weight_core<=weight_core+5'd1;
            end else weight_row<=weight_row+5'd1;
          end else if(!active_words[int'(weight_part)*32+int'(chunk_word)])chunk_word<=chunk_word+6'd1;
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
        DONE:if(done_ready)begin
          state<=IDLE;
          held_context_valid<=hold_primary && !done_error;
        end
        default:begin done_error<=1;flush_second<=0;state<=FLUSH;end
      endcase
      if(cfg_clear_context || state==FLUSH)held_context_valid<=0;
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
