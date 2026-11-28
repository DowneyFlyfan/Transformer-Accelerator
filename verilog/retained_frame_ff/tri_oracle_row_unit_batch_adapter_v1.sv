`timescale 1ns/1ps
// Collect one contiguous batch from ACTUAL retained Size tuples and acknowledged
// NextOwner descriptors. No fabricated owner/root, release or normalizer exists.
module tri_oracle_row_unit_batch_adapter_v1 (
  input logic clk,rst_n,abort_valid,owner_held,
  input logic cfg_valid,
  output logic cfg_ready,
  input tri_oracle_FF_frame_types_v2::frame_t cfg_frame,
  input logic [9:0] cfg_batch_start,
  input logic [4:0] cfg_batch_tokens,
  input logic [31:0] cfg_batch_tag,
  input logic root_valid,root_last,
  input logic [9:0] root_origin,root_count,
  output logic root_ready,
  output logic next_req_valid,next_req_write,
  input logic next_req_ready,
  output logic [9:0] next_req_word,
  output logic [63:0] next_req_data,
  input logic next_rsp_valid,next_rsp_error,
  input logic [63:0] next_rsp_data,
  output logic next_rsp_ready,
  output logic batch_valid,
  input logic batch_ready,
  output tri_oracle_FF_frame_types_v2::batch_t batch_context,
  output logic epoch_fault,idle,port_idle
);
  import tri_oracle_FF_frame_types_v2::*;
  typedef enum logic [2:0] {Idle,WaitRoot,OfferRead,ReceiveRead,OfferBatch,FaultLock} state_t;
  state_t state;
  frame_t saved_frame;
  batch_t saved_batch;
  logic fault_latched,read_owned,read_quarantined,held_context;
  logic [3:0] slot;
  logic [9:0] selected_origin;
  logic cfg_fire,root_fire,request_fire,response_fire,batch_fire;
  logic cfg_bad,root_bad,descriptor_bad,fault_now,unexpected_response,ambiguous_response;
  logic [10:0] batch_end,selected_rank,selected_position;
  logic [32:0] upstream_rank,maximum_tag;
  logic [9:0] previous_root,previous_input;
  row_t decoded_row;

  // Payloads below depend only on saved registers. A late fault cannot retract
  // an exposed descriptor request or completed batch, or rewrite its context.
  always_comb begin
    batch_end={1'b0,cfg_batch_start}+11'(cfg_batch_tokens);
    maximum_tag={1'b0,cfg_frame.common.source_tag}+33'(cfg_frame.upstream_input_count)-33'd1;
    cfg_bad=$isunknown({cfg_frame,cfg_batch_start,cfg_batch_tokens,cfg_batch_tag}) ||
      cfg_frame.common.normalization_role!=1 || cfg_frame.common.phase!=1 ||
      cfg_frame.common.source_layer>=22 || cfg_frame.common.kept_count==0 ||
      cfg_frame.common.kept_count>576 || cfg_frame.common.input_count!=cfg_frame.common.kept_count ||
      cfg_frame.upstream_input_count==0 || cfg_frame.upstream_input_count>576 ||
      cfg_batch_tokens==0 || cfg_batch_tokens>16 || batch_end[10] ||
      batch_end>{1'b0,cfg_frame.common.kept_count} || maximum_tag[32];
    selected_rank={1'b0,saved_batch.start_rank}+11'(slot);
    selected_position={1'b0,saved_frame.common.image_start}+{1'b0,root_origin};
    root_bad=$isunknown({root_origin,root_count,root_last}) || root_origin>=576 ||
      root_count==0 || root_count>576 || selected_position[10] || selected_position==0 ||
      root_last!=(selected_rank+11'd1=={1'b0,saved_frame.common.kept_count}) ||
      (slot!=0 && root_origin<=previous_root);
    // common.source_tag is the held SOURCE TAG BASE for frame_t, not a row tag.
    // Actual row source_tag and unit always come from this descriptor response.
    upstream_rank={1'b0,next_rsp_data[31:0]}-{1'b0,saved_frame.common.source_tag};
    descriptor_bad=$isunknown(next_rsp_data) || next_rsp_data[63:61]!=3'b010 ||
      next_rsp_data[51:42]!=selected_rank[9:0] || next_rsp_data[41:32]!=selected_origin ||
      upstream_rank[32] || upstream_rank>=33'(saved_frame.common.input_count) ||
      upstream_rank>=33'(saved_frame.upstream_input_count) ||
      (slot!=0 && upstream_rank<=33'(previous_input));
    decoded_row='0;
    decoded_row.source_tag=next_rsp_data[31:0];
    decoded_row.original_root=next_rsp_data[41:32];
    decoded_row.activation_unit=$signed(next_rsp_data[60:52]);
    decoded_row.upstream_input_rank=upstream_rank[9:0];
    // This fixed raw layout is indexed by ACTUAL upstream row, not root.
    decoded_row.raw_input_rank=upstream_rank[9:0];
    decoded_row.frame_rank=selected_rank[9:0];
  end

  always_comb begin
    cfg_ready=rst_n===1'b1 && state==Idle && !fault_latched && !held_context &&
      abort_valid===1'b0 && owner_held===1'b1 && next_rsp_valid===1'b0;
    cfg_fire=cfg_valid===1'b1 && cfg_ready===1'b1;
    root_ready=rst_n===1'b1 && state==WaitRoot && !fault_latched &&
      abort_valid===1'b0 && owner_held===1'b1;
    root_fire=root_valid===1'b1 && root_ready===1'b1;
    next_req_valid=rst_n===1'b1 && state==OfferRead;
    next_req_write=1'b0;
    next_req_word=10'd256+selected_rank[9:0];
    next_req_data=64'd0;
    request_fire=next_req_valid===1'b1 && next_req_ready===1'b1;
    ambiguous_response=read_owned && next_rsp_valid!==1'b0 &&
      $isunknown({next_rsp_valid,next_rsp_error,next_rsp_data});
    next_rsp_ready=rst_n===1'b1 && read_owned && !read_quarantined && !ambiguous_response;
    response_fire=next_rsp_valid===1'b1 && next_rsp_ready===1'b1;
    unexpected_response=rst_n===1'b1 && next_rsp_valid!==1'b0 && !read_owned;
    batch_valid=rst_n===1'b1 && state==OfferBatch;
    batch_context=saved_batch;
    batch_fire=batch_valid===1'b1 && batch_ready===1'b1;
    fault_now=unexpected_response || ambiguous_response ||
      (held_context && (abort_valid!==1'b0 || owner_held!==1'b1)) ||
      (state==Idle && cfg_valid!==1'b0 && $isunknown({cfg_valid,abort_valid,owner_held})) ||
      (state==WaitRoot && root_valid!==1'b0 && root_valid!==1'b1) ||
      (state==OfferRead && next_req_ready!==1'b0 && next_req_ready!==1'b1) ||
      (state==OfferBatch && batch_ready!==1'b0 && batch_ready!==1'b1) ||
      (cfg_fire && cfg_bad) || (root_fire && root_bad) ||
      (response_fire && (next_rsp_error!==1'b0 || descriptor_bad));
    epoch_fault=rst_n===1'b1 && (fault_latched || fault_now);
    port_idle=rst_n===1'b1 && state!=OfferRead && !read_owned &&
      !read_quarantined && next_rsp_valid===1'b0;
    idle=rst_n===1'b1 && state==Idle && !held_context && !fault_latched &&
      cfg_valid===1'b0 && abort_valid===1'b0 && port_idle;
  end

  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      state<=Idle;saved_frame<='0;saved_batch<='0;slot<=0;selected_origin<=0;
      previous_root<=0;previous_input<=0;
      fault_latched<=0;held_context<=0;read_owned<=0;read_quarantined<=0;
    end else begin
      if(fault_now)fault_latched<=1;
      // PRE-edge association is authoritative, including response appearance
      // on an exposed request's acceptance edge. No retroactive ownership.
      if(unexpected_response || ambiguous_response ||
         (state==OfferRead && $isunknown(next_req_ready)))read_quarantined<=1;
      case(state)
        Idle:begin
          if(cfg_fire)begin
            saved_frame<=cfg_frame;saved_batch<='0;
            saved_batch.tag<=cfg_batch_tag;saved_batch.start_rank<=cfg_batch_start;
            saved_batch.tokens<=cfg_batch_tokens;slot<=0;
            previous_root<=0;previous_input<=0;held_context<=1;
            if(cfg_bad || fault_now)state<=FaultLock;else state<=WaitRoot;
          end else if(fault_now)state<=FaultLock;
        end
        WaitRoot:begin
          if(root_fire)begin
            selected_origin<=root_origin;
            if(root_bad || fault_now)state<=FaultLock;else state<=OfferRead;
          end else if(fault_latched || fault_now)state<=FaultLock;
        end
        // Offer is irrevocable after exposure, even if poisoned. A known
        // accepted transaction still owns/drains exactly its one response.
        OfferRead:if(request_fire)begin read_owned<=1;state<=ReceiveRead;end
        ReceiveRead:if(response_fire)begin
          read_owned<=0;
          if(fault_latched || fault_now || descriptor_bad || next_rsp_error!==1'b0)
            state<=FaultLock;
          else begin
            saved_batch.rows[slot]<=decoded_row;
            previous_root<=decoded_row.original_root;
            previous_input<=decoded_row.upstream_input_rank;
            if({1'b0,slot}+5'd1==saved_batch.tokens)state<=OfferBatch;
            else begin slot<=slot+4'd1;state<=WaitRoot;end
          end
        end
        OfferBatch:if(batch_fire)begin
          if(fault_latched || fault_now)state<=FaultLock;
          else begin held_context<=0;state<=Idle;end
        end
        FaultLock:begin end
        default:begin fault_latched<=1;state<=FaultLock;end
      endcase
    end
  end
endmodule
