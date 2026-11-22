`timescale 1ns/1ps
// Autonomous head batch over the existing score arrays, output memories,
// independent input-memory normalizers and one shared value accumulator.
// Every result is provisional until successful batch completion. On failure,
// accepted traffic drains before failed completion; reset this controller and
// the fabric together before another batch. The caller owns all fabric ports.
module tri_oracle_complete_head_broker (
 input logic clk,rst_n,
 input logic cfg_valid,output logic cfg_ready,
 input logic [31:0] cfg_heads,cfg_streaming,
 input logic [10:0] cfg_total_keys,cfg_visible_keys,
 input logic [223:0] cfg_score_shifts,
 input logic [255:0] cfg_value_exponents,
 input logic [15:0] cfg_query,cfg_epoch,
 input logic [31:0] cfg_tag,
 input logic cancel,
 output logic tensor_req_valid,input logic tensor_req_ready,
 output logic [1:0] tensor_req_kind,
 output logic [4:0] tensor_req_head,
 output logic [9:0] tensor_req_key,
 output logic [15:0] tensor_req_query,tensor_req_epoch,
 output logic [31:0] tensor_req_tag,
 input logic tensor_rsp_valid,output logic tensor_rsp_ready,
 input logic tensor_rsp_error,
 input logic [1:0] tensor_rsp_kind,
 input logic [4:0] tensor_rsp_head,
 input logic [9:0] tensor_rsp_key,tensor_rsp_size,
 input logic [15:0] tensor_rsp_query,tensor_rsp_epoch,
 input logic [31:0] tensor_rsp_tag,
 input logic signed [7:0] tensor_rsp_value_exponent,
 input logic [511:0] tensor_rsp_data,
 output logic context_valid,input logic context_ready,
 output logic [4:0] context_head,
 output logic [15:0] context_query,context_epoch,
 output logic [31:0] context_tag,
 output logic signed [7:0] context_value_exponent,
 output logic [2047:0] context_data,
 output logic all_contexts_collected,
 output logic done_valid,input logic done_ready,
 output logic done_error,reset_required,busy,
 output logic [7:0] error_code,
 output logic fabric_load_valid,input logic fabric_load_error,
 output logic [4:0] fabric_load_core,
 output logic [1:0] fabric_load_kind,
 output logic [9:0] fabric_load_addr,
 output logic [2047:0] fabric_load_data,
 output logic [31:0] fabric_load_rows,
 output logic [4:0] fabric_activation_reloaded,
 output logic fabric_cmd_valid,input logic fabric_cmd_ready,
 output logic [4:0] fabric_cmd_clusters,fabric_cmd_weight,fabric_cmd_mask,
 output logic [9:0] fabric_cmd_activation,
 output logic [3:0] fabric_cmd_output,
 output logic fabric_cmd_accumulate,
 output logic [1:0] fabric_cmd_reduce,
 output logic [2:0] fabric_core_select,
 input logic [4:0] fabric_out_valid,
 output logic [4:0] fabric_out_ready,
 input logic [19:0] fabric_out_slot,
 input logic [5119:0] fabric_out_data,
 output tri_oracle_wac_softmax_types::request_t softmax_request,
 input tri_oracle_wac_softmax_types::response_t softmax_response
);
 typedef enum logic [5:0] {
  Idle,Allocate,ScoreStart,RequestScore,ReceiveScore,WaitScores,CaptureScore,
  AcceptScore,StoreAcquire,StoreWrite,StoreCheck,FinishScoreBatch,AdvanceScore,
  NormPick,NormConfigure,NormReadIssue,NormReadWait,NormSend,
  NormReleaseAcquire,NormReleaseWrite,NormReleaseCheck,
  PickProbability,RequestValue,ReceiveValue,SubmitValue,WaitValue,
  ArchiveAcquire,ArchiveWrite,ArchiveCheck,ArchiveAcknowledge,SubmitRelease,
  WaitRelease,AdvanceWave,ContextPick,ContextReadIssue,ContextReadWait,
  ContextEmit,ContextReleaseAcquire,ContextReleaseWrite,ContextReleaseCheck,
  Done,AbortDrain,Failed
 } state_t;
 state_t state;
 logic [31:0] requested,pending,archived,streaming;
 logic [10:0] total_keys,visible_keys;
 logic [223:0] shifts;
 logic [255:0] exponents;
 logic [15:0] query,epoch;
 logic [31:0] tag;
 logic core_mode;
 logic [19:0] wave_valid,value_done,norm_fed;
 logic [4:0] wave_heads[20];
 logic [9:0] value_cursor[20];
 logic [5:0] head_scan,allocation_count;
 logic [1:0] score_group;
 logic [4:0] score_tile;
 logic [2:0] request_cluster,retain_cluster;
 logic request_query;
 logic [4:0] request_key,retain_lane;
 logic [4:0] norm_owner,value_owner,emit_head;
 logic [10:0] norm_cursor,wave_max_selected;
 logic norm_word_last,archive_half,context_half;
 logic [4:0] release_core;
 logic [3:0] release_slot;
 logic [2047:0] transport;
 logic [511:0] value_operand;
 logic [15:0] value_probability;
 logic value_last;
 logic [9:0] tile_sizes[5][32];
 logic tensor_pending,read_pending;
 logic [2:0] read_cluster;
 logic [3:0] read_slot;
 logic [1:0] expected_kind;
 logic [4:0] expected_head;
 logic [9:0] expected_key;
 logic response_matches;
 logic [4:0] own_read_core;
 logic [3:0] own_read_slot;
 logic [4:0] archive_core;
 logic [3:0] archive_base;
 logic signed [31:0] scale_dot;
 logic signed [6:0] scale_shift;
 logic [15:0] scaled_score;
 logic [4:0] allocated_owner;
 logic [4:0] active_score_clusters;
 logic [24:0] active_score_heads;
 logic [159:0] active_score_rows;
 logic [2:0] first_score_cluster;
 logic [4:0] retain_owner;

 function automatic logic [10:0] selected_count(input logic [4:0] head);
  return streaming[head] && visible_keys>64 ? 11'd64:visible_keys;
 endfunction
 function automatic logic [9:0] compact_key(input logic [4:0] head,input logic [10:0] index);
  if(streaming[head] && visible_keys>64 && index>=32)return 10'(visible_keys-11'd64+index);
  return 10'(index);
 endfunction
 function automatic logic [4:0] next_owner(input logic [4:0] owner);
  return owner==19?5'd0:owner+5'd1;
 endfunction
 task automatic fail(input logic [7:0] code);
  state<=AbortDrain;if(error_code==0)error_code<=code;
 endtask

 logic sb_cfg_ready,sb_tensor_ready,sb_done_valid,sb_done_error,sb_busy;
 logic sb_cfg_valid,sb_tensor_valid,sb_done_ready;
 logic [4:0] sb_result_valid,sb_result_ready;
 logic [5119:0] sb_result_data;
 logic [24:0] sb_result_heads;
 logic [159:0] sb_result_rows;
 logic [15:0] sb_result_query,sb_result_epoch;
 logic [31:0] sb_result_tag;
 logic sb_load_valid,sb_cmd_valid;
 logic [4:0] sb_load_core,sb_cmd_clusters,sb_cmd_weight,sb_cmd_mask,sb_reloaded;
 logic [1:0] sb_load_kind;
 logic [9:0] sb_load_addr,sb_cmd_activation;
 logic [2047:0] sb_load_data;
 logic [31:0] sb_load_rows;
 logic [3:0] sb_cmd_output;
 logic sb_cmd_accumulate;
 logic [2:0] sb_core_select;
 logic [4:0] sb_out_ready;

 logic u_req_valid,u_req_ready,u_rsp_valid,u_rsp_ready,u_rsp_error;
 logic [1:0] u_operation,u_rsp_operation;
 logic [4:0] u_rsp_owner,u_rsp_head;
 logic [15:0] u_rsp_query,u_rsp_epoch;
 logic [31:0] u_rsp_tag;
 logic [9:0] u_rsp_key;
 logic u_rsp_last,u_load_valid,u_read_valid,u_lock;
 logic [2047:0] u_values;
 logic [19:0] u_resident,u_completed,u_poisoned;
 logic [4:0] u_busy,u_core,u_clusters,u_out_ready;
 logic [9:0] u_address;
 logic [1023:0] u_write_data;
 logic [3:0] u_slot;
 logic [2:0] u_core_select;
 logic u_metadata_matches;

 tri_oracle_attention_score_scale scaler(.dot(scale_dot),.shift(scale_shift),.score(scaled_score));
 tri_oracle_attention_dual_mapping_scores score_engine (
  .clk,.rst_n,.cfg_valid(sb_cfg_valid),.cfg_ready(sb_cfg_ready),
  .cfg_core_mode(core_mode),.cfg_core(score_group),.cfg_tile(score_tile[3:0]),
  .cfg_clusters(active_score_clusters),.cfg_heads(active_score_heads),.cfg_rows(active_score_rows),
  .cfg_query(query),.cfg_epoch(epoch),.cfg_tag(tag),.cancel(cancel || state==AbortDrain),
  .tensor_valid(sb_tensor_valid),.tensor_ready(sb_tensor_ready),.tensor_cluster(request_cluster),
  .tensor_head(expected_head),.tensor_key(request_key),.tensor_query(request_query),
  .tensor_query_rank(query),.tensor_epoch(epoch),.tensor_tag(tag),.tensor_data(tensor_rsp_data),
  .result_valid(sb_result_valid),.result_ready(sb_result_ready),.result_data(sb_result_data),
  .result_heads(sb_result_heads),.result_rows(sb_result_rows),.result_query(sb_result_query),
  .result_epoch(sb_result_epoch),.result_tag(sb_result_tag),.done_valid(sb_done_valid),
  .done_ready(sb_done_ready),.done_error(sb_done_error),.busy(sb_busy),
  .fabric_load_valid(sb_load_valid),.fabric_load_core(sb_load_core),.fabric_load_kind(sb_load_kind),
  .fabric_load_addr(sb_load_addr),.fabric_load_data(sb_load_data),.fabric_load_rows(sb_load_rows),
  .fabric_load_error,.fabric_activation_reloaded(sb_reloaded),.fabric_cmd_valid(sb_cmd_valid),
  .fabric_cmd_ready(fabric_cmd_ready),.fabric_cmd_clusters(sb_cmd_clusters),.fabric_cmd_weight(sb_cmd_weight),
  .fabric_cmd_mask(sb_cmd_mask),.fabric_cmd_activation(sb_cmd_activation),.fabric_cmd_output(sb_cmd_output),
  .fabric_cmd_accumulate(sb_cmd_accumulate),.fabric_core_select(sb_core_select),
  .fabric_out_valid,.fabric_out_ready(sb_out_ready),.fabric_out_output(fabric_out_slot),.fabric_out_data
 );
 tri_oracle_attention_value_accumulator value_engine (
  .clk,.rst_n,.req_valid(u_req_valid),.req_ready(u_req_ready),.req_operation(u_operation),
  .req_owner(value_owner),.req_head(wave_heads[value_owner]),.req_query(query),.req_epoch(epoch),.req_tag(tag),
  .req_key(value_cursor[value_owner]),.req_first(u_operation==0 && value_cursor[value_owner]==0),
  .req_last(value_last),.req_probability(value_probability),.req_value(value_operand),
  .cancel(cancel || state==AbortDrain),.rsp_valid(u_rsp_valid),.rsp_ready(u_rsp_ready),.rsp_error(u_rsp_error),
  .rsp_operation(u_rsp_operation),.rsp_owner(u_rsp_owner),.rsp_head(u_rsp_head),.rsp_query(u_rsp_query),
  .rsp_epoch(u_rsp_epoch),.rsp_tag(u_rsp_tag),.rsp_key(u_rsp_key),.rsp_last(u_rsp_last),.rsp_values(u_values),
  .resident(u_resident),.completed(u_completed),.poisoned(u_poisoned),.busy_clusters(u_busy),
  .fabric_grant(1'b1),.fabric_lock(u_lock),.memory_load_valid(u_load_valid),.memory_core(u_core),
  .memory_address(u_address),.memory_write_data(u_write_data),.memory_load_error(fabric_load_error),
  .memory_read_valid(u_read_valid),.memory_read_ready(fabric_cmd_ready),.memory_clusters(u_clusters),
  .memory_slot(u_slot),.memory_core_select(u_core_select),.memory_out_valid(fabric_out_valid),
  .memory_out_ready(u_out_ready),.memory_out_slot(fabric_out_slot),.memory_out_data(fabric_out_data)
 );

 always_comb begin
  cfg_ready=state==Idle && !cancel;busy=state!=Idle;
  done_valid=state==Done || state==Failed;done_error=state==Failed;reset_required=state==Failed;
  all_contexts_collected=requested!=0 && archived==requested;
  context_valid=state==ContextEmit && !cancel;
  context_head=emit_head;context_query=query;context_epoch=epoch;context_tag=tag;
  context_value_exponent=$signed(exponents[int'(emit_head)*8+:8]);context_data=transport;
  allocated_owner=core_mode ? 5'((int'(allocation_count)%5)*4+int'(allocation_count)/5) : 5'(allocation_count*4);
  wave_max_selected=0;active_score_clusters=0;active_score_heads=0;active_score_rows=0;
  first_score_cluster=0;
  for(int owner=0;owner<20;owner++)if(wave_valid[owner] && selected_count(wave_heads[owner])>wave_max_selected)
   wave_max_selected=selected_count(wave_heads[owner]);
  for(int cluster=4;cluster>=0;cluster--)begin
   if(wave_valid[cluster*4+(core_mode?int'(score_group):0)] &&
      selected_count(wave_heads[cluster*4+(core_mode?int'(score_group):0)])>11'(score_tile)*32)begin
    active_score_clusters[cluster]=1;first_score_cluster=3'(cluster);
    active_score_heads[cluster*5+:5]=wave_heads[cluster*4+(core_mode?int'(score_group):0)];
    for(int lane=0;lane<32;lane++)active_score_rows[cluster*32+lane]=
     11'(score_tile)*32+11'(lane)<selected_count(wave_heads[cluster*4+(core_mode?int'(score_group):0)]);
   end
  end
  retain_owner=5'(retain_cluster)*4+(core_mode?5'(score_group):5'd0);
  expected_kind=(state==RequestValue || state==ReceiveValue)?2'd2:(request_query?2'd0:2'd1);
  expected_head=expected_kind==2?wave_heads[value_owner]:active_score_heads[int'(request_cluster)*5+:5];
  expected_key=expected_kind==2?compact_key(expected_head,11'(value_cursor[value_owner])):
   (request_query?10'd0:compact_key(expected_head,11'(score_tile)*32+11'(request_key)));
  tensor_req_valid=(state==RequestValue || (state==RequestScore && sb_tensor_ready)) && !cancel;
  tensor_req_kind=expected_kind;tensor_req_head=expected_head;tensor_req_key=expected_key;
  tensor_req_query=query;tensor_req_epoch=epoch;tensor_req_tag=tag;
  response_matches=tensor_rsp_kind==expected_kind && tensor_rsp_head==expected_head && tensor_rsp_key==expected_key &&
   tensor_rsp_query==query && tensor_rsp_epoch==epoch && tensor_rsp_tag==tag;
  tensor_rsp_ready=state==AbortDrain ? tensor_pending : state==ReceiveValue ? 1'b1:
   state==ReceiveScore ? (!response_matches || tensor_rsp_error || (!request_query && tensor_rsp_size==0) || sb_tensor_ready):1'b0;
  sb_cfg_valid=state==ScoreStart && active_score_clusters!=0 && !cancel;
  sb_tensor_valid=state==ReceiveScore && tensor_rsp_valid && response_matches && !tensor_rsp_error &&
   (request_query || tensor_rsp_size!=0) && !cancel;
  sb_result_ready=state==AcceptScore?5'b1<<retain_cluster:5'b0;
  sb_done_ready=state==FinishScoreBatch || state==AbortDrain;
  scale_dot=$signed(sb_result_data[int'(retain_cluster)*1024+int'(retain_lane)*32+:32]);
  scale_shift=$signed(shifts[int'(wave_heads[retain_owner])*7+:7]);
  u_operation=state==SubmitRelease || state==WaitRelease?2'd2:2'd0;
  u_req_valid=(state==SubmitValue || state==SubmitRelease) && !cancel;
  u_metadata_matches=u_rsp_owner==value_owner && u_rsp_head==wave_heads[value_owner] && u_rsp_query==query &&
   u_rsp_epoch==epoch && u_rsp_tag==tag && u_rsp_key==value_cursor[value_owner] && u_rsp_last==value_last;
  u_rsp_ready=state==AbortDrain || state==ArchiveAcknowledge ||
   (state==WaitValue && !u_rsp_last && !u_rsp_error && u_metadata_matches) ||
   (state==WaitRelease && !u_rsp_error && u_metadata_matches);

  own_read_core=norm_owner;
  own_read_slot=4'd1+4'(norm_cursor>>5);
  if(!core_mode)begin
   own_read_core={norm_owner[4:2],norm_cursor[6:5]};
   own_read_slot=4'd1+4'(norm_cursor>>7);
  end
  archive_core=wave_heads[value_owner]<20 ? wave_heads[value_owner]:wave_heads[value_owner]-5'd20;
  archive_base=wave_heads[value_owner]<20?4'd12:4'd10;
  if(state==ContextReadIssue || state==ContextReadWait || state==ContextReleaseAcquire ||
     state==ContextReleaseWrite || state==ContextReleaseCheck || state==ContextEmit)begin
   own_read_core=emit_head<20?emit_head:emit_head-5'd20;
   own_read_slot=(emit_head<20?4'd12:4'd10)+4'(context_half);
  end
  fabric_load_valid=sb_load_valid;fabric_load_core=sb_load_core;fabric_load_kind=sb_load_kind;
  fabric_load_addr=sb_load_addr;fabric_load_data=sb_load_data;fabric_load_rows=sb_load_rows;
  fabric_activation_reloaded=sb_reloaded;
  fabric_cmd_valid=sb_cmd_valid;fabric_cmd_clusters=sb_cmd_clusters;fabric_cmd_weight=sb_cmd_weight;
  fabric_cmd_mask=sb_cmd_mask;fabric_cmd_activation=sb_cmd_activation;fabric_cmd_output=sb_cmd_output;
  fabric_cmd_accumulate=sb_cmd_accumulate;fabric_cmd_reduce=0;fabric_core_select=sb_core_select;
  fabric_out_ready=sb_out_ready;
  if(u_busy!=0)begin
   fabric_load_valid=u_load_valid;fabric_load_core=u_core;fabric_load_kind=3;
   fabric_load_addr=u_address;fabric_load_data={1024'b0,u_write_data};fabric_load_rows='1;
   fabric_cmd_valid=u_read_valid;fabric_cmd_clusters=u_clusters;fabric_cmd_weight=0;fabric_cmd_mask=0;
   fabric_cmd_activation=0;fabric_cmd_output=u_slot;fabric_cmd_accumulate=0;fabric_cmd_reduce=3;
   fabric_core_select=u_core_select;fabric_out_ready=u_out_ready;
  end
  if(state==NormReadIssue || state==ContextReadIssue)begin
   fabric_cmd_valid=!cancel;fabric_cmd_clusters=5'b1<<own_read_core[4:2];
   fabric_cmd_weight=0;fabric_cmd_mask=0;fabric_cmd_activation=0;fabric_cmd_output=own_read_slot;
   fabric_cmd_accumulate=0;fabric_cmd_reduce=3;fabric_core_select={1'b1,own_read_core[1:0]};
  end
  if(state==NormReadWait || state==ContextReadWait)fabric_out_ready=5'b1<<read_cluster;
  if(state==StoreWrite || state==NormReleaseWrite || state==ArchiveWrite || state==ContextReleaseWrite)begin
   fabric_load_valid=!cancel;fabric_load_kind=3;fabric_load_rows='1;fabric_load_data=0;
   if(state==StoreWrite)begin
    fabric_load_core=core_mode?retain_owner:{retain_cluster,score_tile[1:0]};
    fabric_load_addr=core_mode?10'd1+10'(score_tile):10'd1+10'(score_tile>>2);
    fabric_load_data[1023:0]=transport[1023:0];
   end else if(state==NormReleaseWrite)begin
    fabric_load_core=release_core;fabric_load_addr=10'd32+10'(release_slot);
   end else if(state==ArchiveWrite)begin
    fabric_load_core=archive_core;fabric_load_addr=10'(archive_base)+10'(archive_half);
    fabric_load_data[1023:0]=u_values[int'(archive_half)*1024+:1024];
   end else begin
    fabric_load_core=own_read_core;fabric_load_addr=10'd32+10'(own_read_slot);
   end
  end
  if(state==AbortDrain)fabric_out_ready='1;
  softmax_request='0;softmax_request.owner=state==PickProbability?value_owner:norm_owner;
  softmax_request.cfg_valid=state==NormConfigure && !cancel;
  softmax_request.cfg_length=selected_count(wave_heads[norm_owner]);
  softmax_request.in_valid=state==NormSend && !cancel;
  softmax_request.score=$signed(transport[int'(norm_cursor[4:0])*32+:16]);
  softmax_request.size=transport[int'(norm_cursor[4:0])*32+16+:10];
  softmax_request.out_ready=state==PickProbability && wave_valid[value_owner] && !value_done[value_owner] && !cancel;
 end

 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin
   state<=Idle;requested<=0;pending<=0;archived<=0;streaming<=0;total_keys<=0;visible_keys<=0;
   shifts<=0;exponents<=0;query<=0;epoch<=0;tag<=0;core_mode<=0;wave_valid<=0;value_done<=0;norm_fed<=0;
   head_scan<=0;allocation_count<=0;score_group<=0;score_tile<=0;request_cluster<=0;retain_cluster<=0;
   request_query<=0;request_key<=0;retain_lane<=0;norm_owner<=0;value_owner<=0;emit_head<=0;norm_cursor<=0;
   norm_word_last<=0;archive_half<=0;context_half<=0;release_core<=0;release_slot<=0;transport<=0;
   value_operand<=0;value_probability<=0;value_last<=0;tensor_pending<=0;read_pending<=0;read_cluster<=0;read_slot<=0;error_code<=0;
   for(int owner=0;owner<20;owner++)begin wave_heads[owner]<=0;value_cursor[owner]<=0;end
   for(int cluster=0;cluster<5;cluster++)for(int lane=0;lane<32;lane++)tile_sizes[cluster][lane]<=0;
  end else begin
   case(state)
    Idle:if(cfg_valid && cfg_ready)begin
     requested<=cfg_heads;pending<=cfg_heads;archived<=0;streaming<=cfg_streaming;
     total_keys<=cfg_total_keys;visible_keys<=cfg_visible_keys;shifts<=cfg_score_shifts;exponents<=cfg_value_exponents;
     query<=cfg_query;epoch<=cfg_epoch;tag<=cfg_tag;core_mode<=cfg_total_keys<=128;
     wave_valid<=0;value_done<=0;norm_fed<=0;head_scan<=0;allocation_count<=0;error_code<=0;
     for(int owner=0;owner<20;owner++)value_cursor[owner]<=0;
     if(cfg_heads==0 || cfg_total_keys==0 || cfg_total_keys>1024 || cfg_visible_keys==0 || cfg_visible_keys>cfg_total_keys || cfg_query>2047)
      fail(8'h02);
     else begin
      state<=Allocate;
      for(int head=0;head<32;head++)if(cfg_heads[head] &&
       ($signed(cfg_score_shifts[head*7+:7]) < -31 || $signed(cfg_score_shifts[head*7+:7]) > 31))fail(8'h03);
     end
    end
    Allocate:begin
     if(pending[head_scan[4:0]])begin
      wave_heads[allocated_owner]<=head_scan[4:0];wave_valid[allocated_owner]<=1;pending[head_scan[4:0]]<=0;
      allocation_count<=allocation_count+6'd1;
     end
     if(head_scan==31 || (pending[head_scan[4:0]] && allocation_count+6'd1==(core_mode?6'd20:6'd5)))begin
      score_group<=0;score_tile<=0;state<=ScoreStart;
     end else head_scan<=head_scan+6'd1;
    end
    ScoreStart:begin
     if(active_score_clusters==0)state<=AdvanceScore;
     else if(sb_cfg_valid && sb_cfg_ready)begin
      request_cluster<=first_score_cluster;request_query<=1;request_key<=0;state<=RequestScore;
     end
    end
    RequestScore:if(tensor_req_valid && tensor_req_ready)begin tensor_pending<=1;state<=ReceiveScore;end
    ReceiveScore:if(tensor_rsp_valid && tensor_rsp_ready)begin
     tensor_pending<=0;
     if(!response_matches || tensor_rsp_error || (!request_query && tensor_rsp_size==0))fail(8'h10);
     else begin
      if(!request_query)tile_sizes[request_cluster][request_key]<=tensor_rsp_size;
      if(request_query)begin request_query<=0;request_key<=0;state<=RequestScore;end
      else if(request_key<31 && active_score_rows[int'(request_cluster)*32+int'(request_key)+1])begin
       request_key<=request_key+5'd1;state<=RequestScore;
      end else begin
       state<=WaitScores;
       for(int cluster=4;cluster>=0;cluster--)if(cluster>int'(request_cluster) && active_score_clusters[cluster])begin
        request_cluster<=3'(cluster);request_query<=1;request_key<=0;state<=RequestScore;
       end
      end
     end
    end
    WaitScores:begin
     if(sb_done_valid && sb_done_error)fail(8'h11);
     else if(|sb_result_valid)begin
      for(int cluster=4;cluster>=0;cluster--)if(sb_result_valid[cluster])retain_cluster<=3'(cluster);
      retain_lane<=0;transport<=0;state<=CaptureScore;
     end else if(sb_done_valid)state<=FinishScoreBatch;
    end
    CaptureScore:begin
     if(!sb_result_valid[retain_cluster] || sb_result_heads!=active_score_heads || sb_result_rows!=active_score_rows ||
        sb_result_query!=query || sb_result_epoch!=epoch || sb_result_tag!=tag)fail(8'h12);
     else begin
      transport[int'(retain_lane)*32+:32]<=active_score_rows[int'(retain_cluster)*32+int'(retain_lane)]?
       {6'b0,tile_sizes[retain_cluster][retain_lane],scaled_score}:32'b0;
      if(retain_lane==31)state<=AcceptScore;else retain_lane<=retain_lane+5'd1;
     end
    end
    AcceptScore:state<=StoreAcquire;
    StoreAcquire:state<=StoreWrite;
    StoreWrite:if(fabric_load_valid)begin
     if(fabric_load_error)fail(8'h13);else state<=StoreCheck;
    end
    StoreCheck:if(fabric_load_error)fail(8'h13);else state<=WaitScores;
    FinishScoreBatch:if(sb_done_valid)begin if(sb_done_error)fail(8'h11);else state<=AdvanceScore;end
    AdvanceScore:begin
     if(core_mode && score_group<3)begin score_group<=score_group+2'd1;state<=ScoreStart;end
     else if(11'(score_tile)*32+32<wave_max_selected)begin score_group<=0;score_tile<=score_tile+5'd1;state<=ScoreStart;end
     else begin norm_owner<=0;norm_cursor<=0;state<=NormPick;end
    end
    NormPick:begin
     if(wave_valid[norm_owner])begin norm_cursor<=0;state<=NormConfigure;end
     else if(norm_owner==19)begin value_owner<=0;state<=PickProbability;end
     else norm_owner<=norm_owner+5'd1;
    end
    NormConfigure:if(softmax_request.cfg_valid && softmax_response.cfg_ready)state<=NormReadIssue;
    NormReadIssue:if(fabric_cmd_valid && fabric_cmd_ready)begin
     read_pending<=1;read_cluster<=own_read_core[4:2];read_slot<=own_read_slot;state<=NormReadWait;
    end
    NormReadWait:if(fabric_out_valid[read_cluster])begin
     read_pending<=0;
     if(fabric_out_slot[int'(read_cluster)*4+:4]!=read_slot)fail(8'h20);
     else begin transport[1023:0]<=fabric_out_data[int'(read_cluster)*1024+:1024];state<=NormSend;end
    end
    NormSend:if(softmax_request.in_valid && softmax_response.in_ready)begin
     norm_cursor<=norm_cursor+11'd1;
     if(norm_cursor[4:0]==31 || norm_cursor+11'd1==selected_count(wave_heads[norm_owner]))begin
      norm_word_last<=norm_cursor+11'd1==selected_count(wave_heads[norm_owner]);
      release_core<=own_read_core;release_slot<=own_read_slot;state<=NormReleaseAcquire;
     end
    end
    NormReleaseAcquire:state<=NormReleaseWrite;
    NormReleaseWrite:if(fabric_load_valid)begin if(fabric_load_error)fail(8'h21);else state<=NormReleaseCheck;end
    NormReleaseCheck:begin
     if(fabric_load_error)fail(8'h21);
     else if(norm_word_last)begin
      norm_fed[norm_owner]<=1;
      if(norm_owner==19)begin value_owner<=0;state<=PickProbability;end
      else begin norm_owner<=norm_owner+5'd1;state<=NormPick;end
     end else state<=NormReadIssue;
    end
    PickProbability:begin
     if((value_done & wave_valid)==wave_valid)state<=AdvanceWave;
     else if(!wave_valid[value_owner] || value_done[value_owner])value_owner<=next_owner(value_owner);
     else if(softmax_response.out_valid && softmax_request.out_ready)begin
      if(softmax_response.cfg_error || softmax_response.out_last!==(11'(value_cursor[value_owner])+11'd1==selected_count(wave_heads[value_owner])))fail(8'h30);
      else begin value_probability<=softmax_response.probability;value_last<=softmax_response.out_last;state<=RequestValue;end
     end else value_owner<=next_owner(value_owner);
    end
    RequestValue:if(tensor_req_valid && tensor_req_ready)begin tensor_pending<=1;state<=ReceiveValue;end
    ReceiveValue:if(tensor_rsp_valid && tensor_rsp_ready)begin
     tensor_pending<=0;
     if(!response_matches || tensor_rsp_error || tensor_rsp_value_exponent!=$signed(exponents[int'(wave_heads[value_owner])*8+:8]))fail(8'h31);
     else begin value_operand<=tensor_rsp_data;state<=SubmitValue;end
    end
    SubmitValue:if(u_req_valid && u_req_ready)state<=WaitValue;
    WaitValue:if(u_rsp_valid)begin
     if(u_rsp_error || !u_metadata_matches || u_rsp_operation!=0)fail(8'h32);
     else if(u_rsp_last)begin archive_half<=0;state<=ArchiveAcquire;end
     else if(u_rsp_ready)begin value_cursor[value_owner]<=value_cursor[value_owner]+10'd1;value_owner<=next_owner(value_owner);state<=PickProbability;end
    end
    ArchiveAcquire:state<=ArchiveWrite;
    ArchiveWrite:if(fabric_load_valid)begin if(fabric_load_error)fail(8'h33);else state<=ArchiveCheck;end
    ArchiveCheck:begin
     if(fabric_load_error)fail(8'h33);
     else if(!archive_half)begin archive_half<=1;state<=ArchiveWrite;end
     else begin archived[wave_heads[value_owner]]<=1;state<=ArchiveAcknowledge;end
    end
    ArchiveAcknowledge:state<=SubmitRelease;
    SubmitRelease:if(u_req_valid && u_req_ready)state<=WaitRelease;
    WaitRelease:if(u_rsp_valid)begin
     if(u_rsp_error || !u_metadata_matches || u_rsp_operation!=2)fail(8'h34);
     else if(u_rsp_ready)begin value_done[value_owner]<=1;value_owner<=next_owner(value_owner);state<=PickProbability;end
    end
    AdvanceWave:begin
     if(pending!=0)begin
      wave_valid<=0;value_done<=0;norm_fed<=0;head_scan<=0;allocation_count<=0;
      for(int owner=0;owner<20;owner++)value_cursor[owner]<=0;
      state<=Allocate;
     end else begin emit_head<=0;state<=ContextPick;end
    end
    ContextPick:begin
     if(requested[emit_head])begin
      if(!archived[emit_head])fail(8'h40);else begin context_half<=0;state<=ContextReadIssue;end
     end else if(emit_head==31)state<=Done;else emit_head<=emit_head+5'd1;
    end
    ContextReadIssue:if(fabric_cmd_valid && fabric_cmd_ready)begin
     read_pending<=1;read_cluster<=own_read_core[4:2];read_slot<=own_read_slot;state<=ContextReadWait;
    end
    ContextReadWait:if(fabric_out_valid[read_cluster])begin
     read_pending<=0;
     if(fabric_out_slot[int'(read_cluster)*4+:4]!=read_slot)fail(8'h41);
     else begin
      transport[int'(context_half)*1024+:1024]<=fabric_out_data[int'(read_cluster)*1024+:1024];
      if(context_half)state<=ContextEmit;else begin context_half<=1;state<=ContextReadIssue;end
     end
    end
    ContextEmit:if(context_valid && context_ready)begin context_half<=0;state<=ContextReleaseAcquire;end
    ContextReleaseAcquire:state<=ContextReleaseWrite;
    ContextReleaseWrite:if(fabric_load_valid)begin if(fabric_load_error)fail(8'h42);else state<=ContextReleaseCheck;end
    ContextReleaseCheck:begin
     if(fabric_load_error)fail(8'h42);
     else if(!context_half)begin context_half<=1;state<=ContextReleaseWrite;end
     else begin
      archived[emit_head]<=0;
      if(emit_head==31)state<=Done;else begin emit_head<=emit_head+5'd1;state<=ContextPick;end
     end
    end
    Done:if(done_ready)state<=Idle;
    AbortDrain:begin
     if(tensor_pending && tensor_rsp_valid)tensor_pending<=0;
     if(read_pending && fabric_out_valid[read_cluster])read_pending<=0;
     if(!sb_busy && u_busy==0 && !tensor_pending && !read_pending && fabric_out_valid==0)state<=Failed;
    end
    Failed:;
    default:fail(8'hff);
   endcase
   if(cancel && state!=Idle && state!=Done && state!=Failed && state!=AbortDrain)fail(8'h01);
   if(sb_busy && u_busy!=0 && state!=AbortDrain)fail(8'he0);
   if(sb_done_valid && sb_done_error && state!=Idle && state!=Done && state!=AbortDrain && state!=Failed)fail(8'h11);
   if(softmax_response.cfg_error && (state==NormConfigure || state==NormReadIssue || state==NormReadWait ||
      state==NormSend || state==NormReleaseAcquire || state==NormReleaseWrite || state==NormReleaseCheck))fail(8'h22);
  end
 end
endmodule
