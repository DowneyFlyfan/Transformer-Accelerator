`timescale 1ns/1ps
// One FLOAT-derived POST row -> real reader/sign fetch -> real twenty-core
// strip predictors. No full-model, attention, matmul, accuracy or PPA claim.
// Expected files are read ONLY by the scoreboard, never the memory provider.
package native_fabric_probe_counts;
  integer counts[0:8] = '{default:0};
endpackage
module native_fabric_probe_marker #(parameter integer ROLE=0) ();
  initial native_fabric_probe_counts::counts[ROLE] = native_fabric_probe_counts::counts[ROLE]+1;
endmodule

package actual_core_transfer_counts;
  integer next_uid = 0;
  integer accepts[0:19] = '{default:0};
  integer results[0:19] = '{default:0};
  string paths[0:19];
endpackage
// This witness reads real core ports only. Its private counters never drive
// a DUT input, internal register, reset, force or fabricated predictor result.
module actual_core_transfer_marker (
  input logic clk, rst_n,
  input logic [146:0] request,
  input logic [39:0] response
);
  integer uid;
  initial begin
    uid = actual_core_transfer_counts::next_uid;
    actual_core_transfer_counts::next_uid = actual_core_transfer_counts::next_uid + 1;
    if (uid >= 20) $fatal(1,"ACTUAL_CORE_TOO_MANY_WITNESSES uid=%0d",uid);
    actual_core_transfer_counts::paths[uid] = $sformatf("%m");
  end
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      actual_core_transfer_counts::accepts[uid] <= 0;
      actual_core_transfer_counts::results[uid] <= 0;
    end else begin
      if (request[146] && response[39])
        actual_core_transfer_counts::accepts[uid] <= actual_core_transfer_counts::accepts[uid]+1;
      if (response[38] && request[144]) begin
        if (response[37] !== 1'b0) $fatal(1,"ACTUAL_CORE_ERROR path=%m");
        actual_core_transfer_counts::results[uid] <= actual_core_transfer_counts::results[uid]+1;
      end
    end
  end
endmodule

module tri_oracle_post_feature_prediction_actual_tb_v1;
  localparam logic [63:0] FEATURE_BASE=64'h40000000;
  localparam logic [63:0] GATE_BASE=64'h50000000, UP_BASE=64'h60000000;
  localparam logic [63:0] SIGN_BYTES=64'd1441792;
  // First sixteen displayed bytes of the complete qualified bundle SHA-256:
  // 61a3dfcd3e2764badb04d69a363c734dbdd8f4063d2ba06ca0121a8ce80e9f69.
  // This numeric128-bit sidecar identifies a caller-bound bundle; it is not
  // a hardware cryptographic provenance verifier.
  localparam logic [127:0] BUNDLE_ID=128'h61a3dfcd3e2764badb04d69a363c734d;
  logic clk=0, rst_n=0, abort_valid=0;
  logic next_context_owned=1, strip_fabric_owned=1;
  logic cfg_valid=0, cfg_ready, cfg_archive_committed=1, cfg_scalar_weight_units=1;
  logic [1:0] cfg_normalization_role=1;
  logic [31:0] cfg_tag;
  logic [4:0] cfg_layer;
  logic [15:0] cfg_epoch;
  logic [9:0] cfg_original_root, cfg_input_rank, cfg_kept_rank;
  logic signed [8:0] cfg_exponent;
  logic [127:0] cfg_bundle_id;
  logic [63:0] cfg_feature_base, cfg_feature_bytes, cfg_gate_sign_base, cfg_gate_sign_bytes;
  logic [63:0] cfg_up_sign_base, cfg_up_sign_bytes;
  logic req_valid, req_ready, rsp_valid, rsp_ready, rsp_last, rsp_error;
  logic [63:0] req_address, rsp_data;
  logic [4:0] req_length;
  logic [533:0] strip_request;
  logic [111:0] strip_response;
  logic mask_valid, mask_ready, mask_last;
  logic [31:0] mask_tag;
  logic [15:0] mask_start;
  logic [6:0] mask_count;
  logic [1279:0] mask_bits;
  logic done_valid, done_ready=0, done_error;
  logic [31:0] done_tag;
  logic [4:0] done_layer;
  logic [15:0] done_epoch;
  logic [9:0] done_original_root, done_input_rank, done_kept_rank;
  logic signed [8:0] done_exponent;
  logic [127:0] done_bundle_id;
  logic [7:0] completed_groups;
  logic [15:0] accepted_strips;
  logic [6:0] accepted_masks;
  logic epoch_fault, active, port_idle, strip_quiet, idle;
  logic peer_owned, peer_valid, peer_last;
  logic [63:0] peer_address, peer_data;
  logic [4:0] peer_length;
  integer peer_kind, peer_pair, peer_beat, peer_delay;
  integer cycles, cfg_accepts, requests, responses;
  integer feature_requests, sign_requests, pred_transfers, pred_strip, group_results;
  integer masks, actual_skipped_channels, first_mask_wait;
  integer request_stalls, strip_stalls, result_stalls, mask_stalls, response_stalls;
  integer expected_active_pairs, expected_outliers;
  logic last_strip_accepted;
  logic [4:0] clusters_seen;
  logic [3:0] gate_requested, up_requested, gate_acked, up_acked;
  logic [63:0] descriptor_words[0:0];
  logic [63:0] selected_row_base;
  logic [31:0] saved_tag;
  logic [4:0] saved_layer;
  logic [15:0] saved_epoch;
  logic [9:0] saved_root, saved_rank;
  logic signed [8:0] saved_exponent;
  byte unsigned feature_bytes[0:767];
  byte unsigned gate_sign_bytes[0:1441791], up_sign_bytes[0:1441791];
  // CHECK ONLY. These arrays have no connection to provider or DUT ports.
  logic [111:0] expected_groups[0:175];
  logic [1279:0] expected_keep[0:70];
  string fixture_root;
  integer sidecar_layer, sidecar_epoch, fd, bytes_read, extra, limit;
  logic request_held, strip_held, result_held, mask_held, done_held, response_held;
  logic [68:0] held_request;
  logic [532:0] held_strip;
  logic [112:0] held_result;
  logic [65:0] held_response;
  typedef struct packed {
    logic last;
    logic [31:0] tag;
    logic [15:0] start;
    logic [6:0] count;
    logic [1279:0] bits;
  } mask_packet_t;
  typedef struct packed {
    logic error;
    logic [31:0] tag;
    logic [4:0] layer;
    logic [15:0] epoch;
    logic [9:0] root, input_rank, kept_rank;
    logic signed [8:0] exponent;
    logic [127:0] bundle;
  } done_packet_t;
  mask_packet_t held_mask;
  done_packet_t held_done;

  tri_oracle_post_feature_prediction_v1 controller (
    .clk,.rst_n,.abort_valid,.next_context_owned,.strip_fabric_owned,
    .cfg_valid,.cfg_ready,.cfg_archive_committed,.cfg_scalar_weight_units,.cfg_normalization_role,
    .cfg_tag,.cfg_layer,.cfg_epoch,.cfg_original_root,.cfg_input_rank,.cfg_kept_rank,
    .cfg_exponent,.cfg_bundle_id,.cfg_feature_base,.cfg_feature_bytes,
    .cfg_gate_sign_base,.cfg_gate_sign_bytes,.cfg_up_sign_base,.cfg_up_sign_bytes,
    .req_valid,.req_ready,.req_address,.req_length,.rsp_valid,.rsp_ready,.rsp_last,.rsp_error,.rsp_data,
    .strip_request,.strip_response,.mask_valid,.mask_ready,.mask_last,.mask_tag,.mask_start,.mask_count,.mask_bits,
    .done_valid,.done_ready,.done_error,.done_tag,.done_layer,.done_epoch,
    .done_original_root,.done_input_rank,.done_kept_rank,.done_exponent,.done_bundle_id,
    .completed_groups,.accepted_strips,.accepted_masks,.epoch_fault,.active,.port_idle,.strip_quiet,.idle
  );

  // EXACT legal full native fabric: six flags1, one instance. All unrelated
  // typed clients are explicitly idle. No inferred duplicate fabric or TMU.
  wire fabric_load_error, fabric_cmd_ready;
  wire [4:0] fabric_out_valid;
  wire [19:0] fabric_out_output;
  wire [5119:0] fabric_out_data;
  wire [119:0] fabric_sign_counts;
  wire [79:0] fabric_merge_word;
  wire [72:0] fabric_head_response;
  tri_oracle_wac_softmax_types::request_t softmax_request;
  tri_oracle_wac_softmax_types::response_t softmax_response;
  tri_oracle_token_size_types::request_t token_request;
  tri_oracle_token_size_types::response_t token_response;
  tri_oracle_merge_range_types::request_t merge_request;
  tri_oracle_merge_range_types::response_t merge_response;
  assign softmax_request='0;
  assign token_request='0;
  assign merge_request='0;
  tri_oracle_compute_fabric #(
    .AGGREGATOR_SIGN_BANK(1),.AGGREGATOR_MERGE_TABLE(1),
    .LOCAL_TOKEN_SIZES(1),.LOCAL_TOKEN_MERGE(1),
    .CORE_STRIP_PREDICTOR(1),.CORE_HEAD_PREDICTOR(1)
  ) fabric (
    .clk,.rst_n,.load_valid(1'b0),.load_core(5'b0),.load_kind(2'b0),
    .load_addr(10'b0),.load_data(2048'b0),.load_row_enable(32'b0),.load_error(fabric_load_error),
    .cmd_valid(1'b0),.cmd_ready(fabric_cmd_ready),.cmd_clusters(5'b0),.cmd_weight(5'b0),
    .cmd_mask(5'b0),.cmd_activation(10'b0),.cmd_output(4'b0),
    .cmd_accumulate(1'b0),.cmd_reduce(2'b0),.out_valid(fabric_out_valid),.out_ready(5'b0),
    .out_output(fabric_out_output),.out_data(fabric_out_data),
    .merge_sign_data(2048'b0),.merge_sign_control(13'b0),.merge_sign_counts(fabric_sign_counts),
    .merge_table_request(22'b0),.merge_table_word(fabric_merge_word),
    .softmax_request,.softmax_response,.activation_reloaded(5'b0),.core_score_select(3'b0),
    .token_sizes_request(token_request),.token_sizes_response(token_response),
    .merge_request,.merge_response,.strip_rst_n(rst_n),.strip_request,.strip_response,
    .head_request(400'b0),.head_response(fabric_head_response)
  );

  assign req_ready = rst_n && !peer_owned && !peer_valid && cycles%5 != 1;
  assign rsp_valid = peer_valid;
  assign rsp_last = peer_last;
  assign rsp_error = 1'b0;
  assign rsp_data = peer_data;
  // Long first KEEP stall allows a genuine held core result if the controller
  // starts its next group. Report actual stalls without requiring that extra
  // scheduling overlap. Never gate/reset the real fabric to invent a stall.
  assign mask_ready = rst_n && cycles%7 != 2 && (masks != 0 || first_mask_wait >= 4096);
  always #5 clk=~clk;

  function automatic integer address_kind(input logic [63:0] address, input logic [4:0] length);
    logic [64:0] last_address;
    last_address = {1'b0,address} + 65'(length)*65'd8 - 65'd1;
    if (length == 0 || last_address[64]) return 0;
    if ({1'b0,address} >= {1'b0,selected_row_base} &&
        last_address <= {1'b0,selected_row_base}+65'd767) return 1;
    if ({1'b0,address} >= {1'b0,GATE_BASE} &&
        last_address < {1'b0,GATE_BASE}+{1'b0,SIGN_BYTES}) return 2;
    if ({1'b0,address} >= {1'b0,UP_BASE} &&
        last_address < {1'b0,UP_BASE}+{1'b0,SIGN_BYTES}) return 3;
    return 0;
  endfunction
  function automatic logic [63:0] memory_word(input integer kind, input logic [63:0] address);
    logic [63:0] value;
    integer offset;
    value='0;
    case (kind)
      1: begin
        offset=int'(address-selected_row_base);
        if (offset < 0 || offset+7 >= 768) $fatal(1,"ACTUAL_PROVIDER_FEATURE_BOUNDS");
        for(integer lane=0;lane<8;lane++)value[lane*8+:8]=feature_bytes[offset+lane];
      end
      2,3: begin
        offset=int'(address-(kind==2 ? GATE_BASE : UP_BASE));
        if (offset < 0 || offset+7 >= 1441792) $fatal(1,"ACTUAL_PROVIDER_SIGN_BOUNDS");
        for(integer lane=0;lane<8;lane++)
          value[lane*8+:8]=kind==2 ? gate_sign_bytes[offset+lane] : up_sign_bytes[offset+lane];
      end
      default:$fatal(1,"ACTUAL_PROVIDER_UNKNOWN_ADDRESS");
    endcase
    return value;
  endfunction
  function automatic logic sign_bit(input logic up, input integer group_index, strip_index, channel, lane);
    integer address;
    address=(group_index*2048+8*strip_index+lane)*4+channel/8;
    return up ? up_sign_bytes[address][channel%8] : gate_sign_bytes[address][channel%8];
  endfunction
  function automatic mask_packet_t mask_packet();
    return {mask_last,mask_tag,mask_start,mask_count,mask_bits};
  endfunction
  function automatic done_packet_t done_packet();
    return {done_error,done_tag,done_layer,done_epoch,done_original_root,
      done_input_rank,done_kept_rank,done_exponent,done_bundle_id};
  endfunction

  // Registered external endpoint: only a request from a PREVIOUS edge can
  // produce a response. One accepted burst remains owned through actual LAST.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      peer_owned<=0;peer_valid<=0;peer_last<=0;peer_address<=0;peer_data<=0;
      peer_length<=0;peer_kind<=0;peer_pair<=0;peer_beat<=0;peer_delay<=0;
    end else begin
      if(req_valid && req_ready)begin
        if(peer_owned || peer_valid)$fatal(1,"ACTUAL_MULTIPLE_OWNED_READS");
        peer_owned<=1;peer_address<=req_address;peer_length<=req_length;
        peer_kind<=address_kind(req_address,req_length);
        peer_pair<=int'((req_address-(req_address>=UP_BASE ? UP_BASE : GATE_BASE))%32)/8;
        peer_beat<=0;peer_delay<=0;
      end
      if(peer_owned && !peer_valid)begin
        if(peer_delay >= cycles%3+1)begin
          peer_valid<=1;peer_last<=peer_beat+1==int'(peer_length);
          peer_data<=memory_word(peer_kind,peer_address+64'(peer_beat)*8);
        end else peer_delay<=peer_delay+1;
      end
      if(peer_valid && rsp_ready)begin
        peer_valid<=0;peer_delay<=0;
        if(peer_last)peer_owned<=0;
        else peer_beat<=peer_beat+1;
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin : scoreboard
    integer kind,offset,request_group,request_strip,pair_index;
    logic [7:0] actual_active,actual_negative;
    if(!rst_n)begin
      cycles<=0;cfg_accepts<=0;requests<=0;responses<=0;feature_requests<=0;sign_requests<=0;
      pred_transfers<=0;pred_strip<=0;group_results<=0;masks<=0;actual_skipped_channels<=0;
      first_mask_wait<=0;last_strip_accepted<=0;clusters_seen<=0;
      gate_requested<=0;up_requested<=0;gate_acked<=0;up_acked<=0;
      request_held<=0;strip_held<=0;result_held<=0;mask_held<=0;done_held<=0;response_held<=0;
      request_stalls<=0;strip_stalls<=0;result_stalls<=0;mask_stalls<=0;response_stalls<=0;
      held_request<=0;held_strip<=0;held_result<=0;held_mask<='0;held_done<='0;held_response<=0;
    end else begin
      cycles<=cycles+1;
      if(cycles>=2000000)$fatal(1,"ACTUAL_PREDICTION_WATCHDOG");
      if(epoch_fault !== 1'b0 || fabric_load_error !== 1'b0 || fabric_out_valid !== 5'b0)
        $fatal(1,"ACTUAL_UNEXPECTED_FAULT_OR_COMPUTE");
      if(cfg_valid && cfg_ready)cfg_accepts<=cfg_accepts+1;
      if(request_held && (!req_valid || {req_address,req_length} !== held_request))$fatal(1,"ACTUAL_RETRACTED_READ");
      if(strip_held && (!strip_request[530] || {strip_request[533:529],strip_request[527:0]} !== held_strip))$fatal(1,"ACTUAL_RETRACTED_STRIP");
      if(result_held && (!strip_response[110] || {strip_request[533:531],strip_response[109:0]} !== held_result))$fatal(1,"ACTUAL_CHANGED_CORE_RESULT");
      if(mask_held && (!mask_valid || mask_packet() !== held_mask))$fatal(1,"ACTUAL_RETRACTED_KEEP");
      if(done_held && (!done_valid || done_packet() !== held_done))$fatal(1,"ACTUAL_CHANGED_DONE");
      if(response_held && (!rsp_valid || {rsp_last,rsp_error,rsp_data} !== held_response))$fatal(1,"ACTUAL_PROVIDER_CHANGED_RESPONSE");
      if(req_valid && req_ready)begin
        kind=address_kind(req_address,req_length);
        if(kind==0)$fatal(1,"ACTUAL_OUT_OF_EXTENT_READ address=%h length=%0d",req_address,req_length);
        requests<=requests+1;
        if(kind==1)begin
          if(req_length!=8 || req_address !== selected_row_base+64'(feature_requests%12)*64 ||
             feature_requests/12!=group_results || completed_groups!=8'(group_results))
            $fatal(1,"ACTUAL_WRONG_FEATURE_REPLAY group=%0d",group_results);
          feature_requests<=feature_requests+1;
        end else begin
          offset=int'(req_address-(kind==3 ? UP_BASE : GATE_BASE));
          request_group=offset/8192;request_strip=(offset%8192)/32;pair_index=(offset%32)/8;
          if(req_length!=1 || req_address[2:0]!=0 || request_group!=group_results || request_strip!=pred_strip ||
             feature_bytes[3*pred_strip][pair_index*2+:2]==0)
            $fatal(1,"ACTUAL_WRONG_SIGN_ADDRESS group=%0d strip=%0d",group_results,pred_strip);
          if(kind==2)begin
            if(gate_requested[pair_index] || up_requested[pair_index])$fatal(1,"ACTUAL_DUPLICATE_GATE_READ");
            gate_requested[pair_index]<=1;
          end else begin
            if(!gate_acked[pair_index] || up_requested[pair_index])$fatal(1,"ACTUAL_UP_READ_BEFORE_GATE_ACK");
            up_requested[pair_index]<=1;
          end
          sign_requests<=sign_requests+1;
        end
      end
      if(rsp_valid && rsp_ready)begin
        if(!peer_owned)$fatal(1,"ACTUAL_RESPONSE_WITHOUT_PREEDGE_OWNER");
        responses<=responses+1;
        if(peer_kind==2 && peer_last)begin
          if(gate_acked[peer_pair])$fatal(1,"ACTUAL_DUPLICATE_GATE_ACK");
          gate_acked[peer_pair]<=1;
        end
        if(peer_kind==3 && peer_last)begin
          if(up_acked[peer_pair])$fatal(1,"ACTUAL_DUPLICATE_UP_ACK");
          up_acked[peer_pair]<=1;
        end
      end
      if(strip_request[530] && strip_response[111])begin
        actual_active=feature_bytes[3*pred_strip];actual_negative=feature_bytes[3*pred_strip+2];
        if(group_results>=176 || last_strip_accepted || strip_request[533:531]!==3'(group_results%5) ||
           strip_request[529] !== (pred_strip==255) || strip_request[519:512]!==actual_active ||
           strip_request[527:520]!==actual_negative)
          $fatal(1,"ACTUAL_WRONG_STRIP_FLAGS group=%0d strip=%0d",group_results,pred_strip);
        for(integer pair=0;pair<4;pair++)begin
          if(gate_acked[pair] !== (actual_active[pair*2+:2]!=0) || up_acked[pair] !== (actual_active[pair*2+:2]!=0))
            $fatal(1,"ACTUAL_STRIP_BEFORE_REAL_SIGN_ACK group=%0d strip=%0d pair=%0d",group_results,pred_strip,pair);
        end
        for(integer channel=0;channel<32;channel++)
          for(integer lane=0;lane<8;lane++)begin
            if(strip_request[256+8*channel+lane] !== (actual_active[lane] && sign_bit(0,group_results,pred_strip,channel,lane)) ||
               strip_request[8*channel+lane] !== (actual_active[lane] && sign_bit(1,group_results,pred_strip,channel,lane)))
              $fatal(1,"ACTUAL_WRONG_CORE_SIGN_LAYOUT group=%0d strip=%0d channel=%0d lane=%0d",group_results,pred_strip,channel,lane);
          end
        pred_transfers<=pred_transfers+1;clusters_seen[group_results%5]<=1;
        gate_requested<=0;up_requested<=0;gate_acked<=0;up_acked<=0;
        if(pred_strip==255)last_strip_accepted<=1;
        else pred_strip<=pred_strip+1;
      end
      if(strip_response[110])begin
        if(!last_strip_accepted || group_results>=176 || strip_request[533:531]!==3'(group_results%5))
          $fatal(1,"ACTUAL_RAW_RESULT_WITHOUT_PRIOR_LAST group=%0d",group_results);
        if(strip_response[109] !== 1'b0 || strip_response[108:0] !== expected_groups[group_results][108:0])
          $fatal(1,"ACTUAL_REAL_CORE_PREDICTION_MISMATCH group=%0d got=%h expected=%h",group_results,strip_response,expected_groups[group_results]);
        if(strip_request[528])begin
          if(peer_owned || peer_valid)$fatal(1,"ACTUAL_GROUP_RESULT_BEFORE_READ_DRAIN");
          $display("ACTUAL_GROUP_RESULT group=%0d cluster=%0d payload=%028h",group_results,group_results%5,{3'b0,strip_response[108:0]});
          actual_skipped_channels<=actual_skipped_channels+$countones(strip_response[44:13]);
          group_results<=group_results+1;pred_strip<=0;last_strip_accepted<=0;
        end
      end
      if(mask_valid && masks==0 && first_mask_wait<4096)first_mask_wait<=first_mask_wait+1;
      if(mask_valid && mask_ready)begin
        if(masks>=71 || mask_tag!==saved_tag || mask_start!==16'(masks*80) ||
           mask_count!==(masks==70 ? 7'd32 : 7'd80) || mask_last!==(masks==70) ||
           mask_bits!==expected_keep[masks] || mask_bits[1279:80]!==1200'b0)
          $fatal(1,"ACTUAL_KEEP_PACKET_MISMATCH packet=%0d",masks);
        $display("ACTUAL_KEEP_PACKET packet=%0d start=%0d count=%0d last=%b bits=%0320h",masks,mask_start,mask_count,mask_last,mask_bits);
        masks<=masks+1;
      end
      if(done_valid)begin
        if(done_error!==1'b0 || done_tag!==saved_tag || done_layer!==saved_layer || done_epoch!==saved_epoch ||
           done_original_root!==saved_root || done_input_rank!==saved_rank || done_kept_rank!==saved_rank ||
           done_exponent!==saved_exponent || done_bundle_id!==BUNDLE_ID)
          $fatal(1,"ACTUAL_WRONG_DONE_CONTEXT");
        if(!done_held && (cfg_accepts!=1 || group_results!=176 || pred_transfers!=45056 || masks!=71 ||
           completed_groups!=176 || accepted_strips!=45056 || accepted_masks!=71 || actual_skipped_channels!=866 ||
           feature_requests!=2112 || sign_requests!=176*2*expected_active_pairs ||
           responses!=2112*8+176*2*expected_active_pairs || peer_owned || peer_valid || req_valid || rsp_valid ||
           strip_request[530] || strip_response[110] || mask_valid || !strip_quiet || !active || clusters_seen!==5'b11111))
          $fatal(1,"ACTUAL_FALSE_EARLY_SUCCESS");
      end
      request_held<=req_valid && !req_ready;strip_held<=strip_request[530] && !strip_response[111];
      result_held<=strip_response[110] && !strip_request[528];mask_held<=mask_valid && !mask_ready;
      done_held<=done_valid && !done_ready;response_held<=rsp_valid && !rsp_ready;
      held_request<={req_address,req_length};held_strip<={strip_request[533:529],strip_request[527:0]};
      held_result<={strip_request[533:531],strip_response[109:0]};held_mask<=mask_packet();held_done<=done_packet();
      held_response<={rsp_last,rsp_error,rsp_data};
      if(req_valid && !req_ready)request_stalls<=request_stalls+1;
      if(strip_request[530] && !strip_response[111])strip_stalls<=strip_stalls+1;
      if(strip_response[110] && !strip_request[528])result_stalls<=result_stalls+1;
      if(mask_valid && !mask_ready)mask_stalls<=mask_stalls+1;
      if(rsp_valid && !rsp_ready)response_stalls<=response_stalls+1;
    end
  end

  task automatic file_end(input integer descriptor, wanted, received, input string label);
    if(descriptor==0 || received!=wanted)$fatal(1,"ACTUAL_BINARY_FILE_SIZE name=%s wanted=%0d got=%0d",label,wanted,received);
    extra=$fgetc(descriptor);
    if(extra!=-1)$fatal(1,"ACTUAL_BINARY_FILE_TRAILING_DATA name=%s",label);
    $fclose(descriptor);
  endtask
  task automatic check_census_and_cores();
    integer accepts,results,n35,n36;
    accepts=0;results=0;n35=0;n36=0;
    if(native_fabric_probe_counts::counts[0]!=360 || native_fabric_probe_counts::counts[1]!=40 ||
       native_fabric_probe_counts::counts[2]!=200 || native_fabric_probe_counts::counts[3]!=16 ||
       native_fabric_probe_counts::counts[4]!=4 || native_fabric_probe_counts::counts[5]!=1 ||
       native_fabric_probe_counts::counts[6]!=20 || native_fabric_probe_counts::counts[7]!=20 ||
       native_fabric_probe_counts::counts[8]!=20)$fatal(1,"ACTUAL_NATIVE_CENSUS_FAILED");
    if(actual_core_transfer_counts::next_uid!=20)$fatal(1,"ACTUAL_CORE_WITNESS_COUNT");
    for(integer uid=0;uid<20;uid++)begin
      if(actual_core_transfer_counts::results[uid]==35)n35++;
      else if(actual_core_transfer_counts::results[uid]==36)n36++;
      else $fatal(1,"ACTUAL_CORE_RESULT_COUNT uid=%0d count=%0d",uid,actual_core_transfer_counts::results[uid]);
      if(actual_core_transfer_counts::accepts[uid]!=256*actual_core_transfer_counts::results[uid])
        $fatal(1,"ACTUAL_CORE_STRIP_COUNT uid=%0d",uid);
      accepts+=actual_core_transfer_counts::accepts[uid];results+=actual_core_transfer_counts::results[uid];
      $display("ACTUAL_PHYSICAL_CORE uid=%0d path=%s accepts=%0d results=%0d",uid,actual_core_transfer_counts::paths[uid],
        actual_core_transfer_counts::accepts[uid],actual_core_transfer_counts::results[uid]);
    end
    if(n35!=16 || n36!=4 || accepts!=180224 || results!=704)$fatal(1,"ACTUAL_CORE_PARTICIPATION_TOTALS");
    for(integer cluster=0;cluster<5;cluster++)begin
      if(fabric.cluster_strip_responses[cluster][111]!==1'b1 || fabric.cluster_strip_responses[cluster][110]!==1'b0)
        $fatal(1,"ACTUAL_NATIVE_CLUSTER_NOT_QUIET cluster=%0d",cluster);
    end
    $display("ACTUAL_NATIVE_CENSUS RAMs=621 PEarrays=20 StripPredictors=20 HeadPredictors=20 active_strip_cores=20 core_accepts=180224 core_results=704");
  endtask

  initial begin
    if(!$value$plusargs("ACTUAL_FIXTURE_ROOT=%s",fixture_root))$fatal(1,"ACTUAL_FIXTURE_ROOT_REQUIRED");
    // Root freezes these caller metadata arguments against actual_context.json,
    // which holds the real layer0/epoch1 demand sidecar. They are DUT inputs.
    if(!$value$plusargs("ACTUAL_LAYER=%d",sidecar_layer) || !$value$plusargs("ACTUAL_EPOCH=%d",sidecar_epoch))
      $fatal(1,"ACTUAL_HELD_DEMAND_SIDECAR_REQUIRED");
    if(sidecar_layer!=0 || sidecar_epoch!=1)$fatal(1,"ACTUAL_HELD_DEMAND_SIDECAR_MISMATCH");
    fd=$fopen({fixture_root,"/actual_feature_archive.bin"},"rb");
    if(fd==0)$fatal(1,"ACTUAL_FEATURE_FILE_MISSING");
    bytes_read=$fread(feature_bytes,fd);file_end(fd,768,bytes_read,"feature");
    fd=$fopen({fixture_root,"/gate_signs_group_major.bin"},"rb");
    if(fd==0)$fatal(1,"ACTUAL_GATE_SIGN_FILE_MISSING");
    bytes_read=$fread(gate_sign_bytes,fd);file_end(fd,1441792,bytes_read,"gate-sign");
    fd=$fopen({fixture_root,"/up_signs_group_major.bin"},"rb");
    if(fd==0)$fatal(1,"ACTUAL_UP_SIGN_FILE_MISSING");
    bytes_read=$fread(up_sign_bytes,fd);file_end(fd,1441792,bytes_read,"up-sign");
    $readmemh({fixture_root,"/actual_descriptor.hex"},descriptor_words);
    $readmemh({fixture_root,"/expected_groups.hex"},expected_groups);
    $readmemh({fixture_root,"/expected_keep_packets.hex"},expected_keep);
    if($isunknown(descriptor_words[0]) || descriptor_words[0][63:61]!==3'b010 ||
       descriptor_words[0][51:42]!==10'd13 || descriptor_words[0][41:32]!==10'd22 ||
       descriptor_words[0][31:0]!==32'h504f000d || $signed(descriptor_words[0][60:52])!==-9'sd7)
      $fatal(1,"ACTUAL_DESCRIPTOR_CONTEXT_MISMATCH");
    cfg_tag=descriptor_words[0][31:0];cfg_original_root=descriptor_words[0][41:32];
    cfg_kept_rank=descriptor_words[0][51:42];cfg_input_rank=descriptor_words[0][51:42];
    cfg_exponent=$signed(descriptor_words[0][60:52]);cfg_layer=5'(sidecar_layer);cfg_epoch=16'(sidecar_epoch);
    cfg_bundle_id=BUNDLE_ID;cfg_feature_base=FEATURE_BASE;cfg_feature_bytes=442368;
    cfg_gate_sign_base=GATE_BASE;cfg_gate_sign_bytes=SIGN_BYTES;cfg_up_sign_base=UP_BASE;cfg_up_sign_bytes=SIGN_BYTES;
    selected_row_base=FEATURE_BASE+64'(cfg_kept_rank)*768;
    saved_tag=cfg_tag;saved_layer=cfg_layer;saved_epoch=cfg_epoch;saved_root=cfg_original_root;
    saved_rank=cfg_kept_rank;saved_exponent=cfg_exponent;
    expected_active_pairs=0;expected_outliers=0;
    for(integer strip=0;strip<256;strip++)begin
      if((feature_bytes[3*strip+2] & ~feature_bytes[3*strip])!=0)$fatal(1,"ACTUAL_OUTLIER_SIGN_NOT_SUBSET");
      expected_outliers+=$countones(feature_bytes[3*strip]);
      for(integer pair=0;pair<4;pair++)if(feature_bytes[3*strip][pair*2+:2]!=0)expected_active_pairs++;
    end
    if(expected_outliers!=12)$fatal(1,"ACTUAL_OUTLIER_COUNT_MISMATCH");
    for(integer group_index=0;group_index<176;group_index++)
      if($isunknown(expected_groups[group_index]) || expected_groups[group_index][111:109]!==3'b0 ||
         expected_groups[group_index][12:0]!==13'd12)$fatal(1,"ACTUAL_CHECK_ONLY_GROUP_FILE_MALFORMED");
    for(integer packet=0;packet<71;packet++)
      if($isunknown(expected_keep[packet]))$fatal(1,"ACTUAL_CHECK_ONLY_KEEP_FILE_MALFORMED");
    $display("ACTUAL_FIXTURE_OPENED rank=%0d root=%0d tag=%08h layer=%0d epoch=%0d eA=%0d descriptor_word=269 active_pairs=%0d outliers=%0d FLOAT_input_origin=1 integer_attention_producer=0",
      saved_rank,saved_root,saved_tag,saved_layer,saved_epoch,saved_exponent,expected_active_pairs,expected_outliers);
    repeat(3)@(posedge clk);@(negedge clk);rst_n=1;repeat(3)@(negedge clk);
    cfg_valid=1;limit=0;
    forever begin
      @(posedge clk);if(cfg_ready===1'b1)break;
      limit++;if(limit>50)$fatal(1,"ACTUAL_NO_CFG_ACCEPTANCE");
    end
    @(negedge clk);cfg_valid=0;
    // All subsequent operations must use captured context and base addresses.
    cfg_tag=0;cfg_bundle_id=0;cfg_feature_base=0;cfg_gate_sign_base=0;cfg_up_sign_base=0;
    limit=0;
    while(!done_valid && limit<2000000)begin @(negedge clk);limit++;end
    if(!done_valid)$fatal(1,"ACTUAL_NO_DONE");
    repeat(4)@(negedge clk);
    check_census_and_cores();
    if(request_stalls==0 || mask_stalls<4096)$fatal(1,"ACTUAL_BACKPRESSURE_TARGETS_NOT_EXERCISED");
    done_ready=1;@(posedge clk);@(negedge clk);done_ready=0;repeat(4)@(negedge clk);
    if(!idle || active || epoch_fault || !port_idle || !strip_quiet || req_valid || rsp_valid || strip_request[530] || mask_valid || done_valid)
      $fatal(1,"ACTUAL_CONTEXT_NOT_RETIRED");
    $display("ACTUAL_PREDICTION_PASS groups=176 strips=45056 masks=71 skipped=866 RAMs=621 physical_strip_cores=20 feature_reads=%0d sign_reads=%0d response_beats=%0d cycles=%0d request_stalls=%0d strip_stalls=%0d result_stalls=%0d mask_stalls=%0d response_stalls=%0d actual_feature_archive=1 real_predictor=1 matmul_verified=0 all22_layers_verified=0 accuracy_verified=0 paper_matching=0 physical_advancement_allowed=0",
      feature_requests,sign_requests,responses,cycles,request_stalls,strip_stalls,result_stalls,mask_stalls,response_stalls);
    $finish;
  end
endmodule

bind TS5N28HPCPSVTA32X128M2FW native_fabric_probe_marker #(.ROLE(0)) probe_role_0();
bind TS5N28HPCPSVTA512X64M4F native_fabric_probe_marker #(.ROLE(1)) probe_role_1();
bind TS6N28HPCPSVTA16X128M2F native_fabric_probe_marker #(.ROLE(2)) probe_role_2();
bind TS5N28HPCPSVTA24X128M2FW native_fabric_probe_marker #(.ROLE(3)) probe_role_3();
bind TS5N28HPCPSVTA16X80M2FW native_fabric_probe_marker #(.ROLE(4)) probe_role_4();
bind TS5N28HPCPSVTA8X80M2FW native_fabric_probe_marker #(.ROLE(5)) probe_role_5();
bind tri_oracle_pe_array native_fabric_probe_marker #(.ROLE(6)) probe_role_6();
bind tri_oracle_core_strip448 native_fabric_probe_marker #(.ROLE(7)) probe_role_7();
bind tri_oracle_core_head450 native_fabric_probe_marker #(.ROLE(8)) probe_role_8();
bind tri_oracle_core_strip448 actual_core_transfer_marker observed_transfers (.clk,.rst_n,.request,.response);
