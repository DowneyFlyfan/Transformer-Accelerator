`timescale 1ns/1ps
// Image-only parent for the qualified row stage. Physical memory ownership
// passes to projection; this module never releases the physical frame lease.
module tri_oracle_normalized_image_compactor (
  input logic clk,rst_n,cfg_valid,cfg_new_image,
  input logic [11:0] cfg_minimum_matches,
  input logic [31:0] cfg_tag_base,
  input logic [4:0] cfg_layer,
  input logic [15:0] cfg_epoch,
  input logic [63:0] cfg_immutable_input_base,cfg_immutable_input_bytes,cfg_compact_output_base,
  input logic abort_valid,row_source_error,
  output logic cfg_ready,frame_protect,epoch_invalid,
  output logic row_request_valid,
  input logic row_request_ready,producer_idle,
  output logic [9:0] row_request_original_root,row_request_input_rank,
  output logic [31:0] row_request_tag,
  output logic [4:0] row_request_layer,
  output logic [15:0] row_request_epoch,
  input logic in_valid,
  output logic in_ready,
  input logic [31:0] in_tag,
  input logic [9:0] in_index,
  input logic [3:0] in_count,
  input logic in_last,in_error,
  input logic [63:0] in_activation,
  input logic signed [8:0] in_exponent,
  input logic [7:0] in_negative,
  output logic memory_acquire_valid,
  input logic memory_acquire_ready,memory_context_owned,frame_port_granted,
  output logic memory_req_valid,memory_req_write,
  input logic memory_req_ready,
  output logic [9:0] memory_req_word,
  output logic [63:0] memory_req_data,
  input logic memory_rsp_valid,memory_rsp_error,
  input logic [63:0] memory_rsp_data,
  output logic memory_rsp_ready,
  output tri_oracle_merge_range_types::request_t merge_request,
  input tri_oracle_merge_range_types::response_t merge_response,
  output logic [2047:0] merge_sign_data,
  input tri_oracle_token_size_types::request_t size_request_observed,
  input tri_oracle_token_size_types::response_t size_response_observed,
  output logic vector_req_valid,
  input logic vector_req_ready,
  output logic [63:0] vector_req_address,
  output logic [511:0] vector_req_data,
  input logic vector_rsp_valid,vector_rsp_error,
  output logic vector_rsp_ready,
  output logic image_done_valid,image_error,abort_drained,
  input logic image_done_ready,
  output logic [31:0] handoff_tag_base,
  output logic [4:0] handoff_layer,
  output logic [15:0] handoff_epoch,
  output logic [9:0] handoff_input_count,handoff_kept_count
);
  typedef enum logic [4:0] {
    Idle,Acquire,Configure,AwaitRoot,StartRow,RequestRow,ReceiveRow,Decision,
    CopyRequest,CopyResponse,OfferLine,LineResponse,DescriptorRequest,
    DescriptorResponse,ReleaseRow,WaitTerminal,Handoff,FaultDrain
  } state_t;
  typedef enum logic [1:0] {NoMemory,StageMemory,CopyMemory,DescriptorMemory} memory_owner_t;
  state_t state;
  memory_owner_t memory_owner;
  logic physical_lease,row_grant,row_authorized,decision_pending,terminal_received;
  logic terminal_error,fault_drain_complete;
  logic [31:0] saved_tag_base;
  logic [4:0] saved_layer;
  logic [15:0] saved_epoch;
  logic saved_new_image;
  logic [11:0] saved_threshold;
  logic [63:0] saved_output_base,descriptor_data;
  logic [9:0] map_cursor,input_count,kept_count,row_root;
  logic [8:0] read_word;
  logic [5:0] line_acknowledgements;
  logic [511:0] line_data;
  logic vector_offered,vector_pending;
  logic [64:0] input_last,output_last;
  logic [32:0] tag_last;
  logic configuration_legal,active,fault_now,fault_active,map_fire,map_bad;
  logic request_fire,response_fire,vector_request_fire,vector_response_fire;
  logic aggregate_idle,virtual_release_ready,virtual_context,source_authorized;
  logic [1:0] merger_cut_kind,size_cut_kind;
  logic [3:0] cut_kind,previous_cut_kind;
  logic cut_sample,cut_same;

  logic stage_start_valid,stage_start_ready,stage_acquire_valid,stage_acquire_ready;
  logic stage_memory_release_valid,stage_memory_req_valid,stage_memory_req_ready;
  logic stage_memory_req_write,stage_memory_rsp_ready,stage_in_ready;
  logic [9:0] stage_memory_req_word;
  logic [63:0] stage_memory_req_data;
  logic stage_row_valid,stage_row_ready,stage_row_consumed,stage_release_valid,stage_release_ready;
  logic stage_epoch_invalid,stage_epoch_clear_ready,stage_lease_held,stage_abort;
  logic [31:0] stage_row_tag;
  logic signed [8:0] stage_row_exponent;
  logic [2047:0] stage_row_negative;
  logic [8:0] stage_accepted_words,stage_acknowledged_words;

  tri_oracle_normalized_row_stage stage (
    .clk,.rst_n,.start_valid(stage_start_valid),.start_ready(stage_start_ready),
    .start_tag(saved_tag_base+32'(input_count)),.abort_valid(stage_abort),.producer_idle,
    .epoch_clear_valid(1'b0),.epoch_clear_ready(stage_epoch_clear_ready),.epoch_invalid(stage_epoch_invalid),
    .in_valid(in_valid && source_authorized),.in_ready(stage_in_ready),.in_tag,.in_index,.in_count,
    .in_last,.in_error,.in_activation,.in_exponent,.in_negative,
    .memory_acquire_valid(stage_acquire_valid),.memory_acquire_ready(stage_acquire_ready),
    .memory_context_owned(virtual_context),.memory_release_valid(stage_memory_release_valid),
    .memory_release_ready(virtual_release_ready),.memory_req_valid(stage_memory_req_valid),
    .memory_req_ready(stage_memory_req_ready),.memory_req_write(stage_memory_req_write),
    .memory_req_word(stage_memory_req_word),.memory_req_data(stage_memory_req_data),
    .memory_rsp_valid(memory_rsp_valid && memory_owner==StageMemory),.memory_rsp_error,
    .memory_rsp_ready(stage_memory_rsp_ready),.row_valid(stage_row_valid),.row_ready(stage_row_ready),
    .row_tag(stage_row_tag),.row_exponent(stage_row_exponent),.row_negative(stage_row_negative),
    .row_consumed(stage_row_consumed),.release_valid(stage_release_valid),.release_ready(stage_release_ready),
    .consumer_idle(aggregate_idle),.lease_held(stage_lease_held),
    .accepted_words(stage_accepted_words),.acknowledged_words(stage_acknowledged_words)
  );

  always_comb begin
    input_last={1'b0,cfg_immutable_input_base}+{1'b0,cfg_immutable_input_bytes}-65'd1;
    output_last={1'b0,cfg_compact_output_base}+65'd1179647;
    tag_last={1'b0,cfg_tag_base}+33'd575;
    configuration_legal=cfg_immutable_input_bytes!=0 && cfg_immutable_input_base[5:0]==0 &&
      cfg_immutable_input_bytes[5:0]==0 && cfg_compact_output_base[5:0]==0 &&
      !input_last[64] && !output_last[64] && !tag_last[32] && cfg_minimum_matches<=2048 &&
      (input_last<{1'b0,cfg_compact_output_base} || output_last<{1'b0,cfg_immutable_input_base});
    active=state!=Idle;
    map_fire=merge_response.map_valid && rst_n && (active || epoch_invalid);
    map_bad=map_fire && !epoch_invalid &&
      (map_cursor>=576 || merge_response.map_index!=map_cursor ||
       merge_response.map_last!=(map_cursor==575) || merge_response.map_origin>merge_response.map_index ||
       (decision_pending && merge_response.map_index!=row_root) ||
       (!decision_pending && merge_response.map_origin==merge_response.map_index));
    fault_now=abort_valid || row_source_error || map_bad ||
      (active && stage_epoch_invalid) ||
      (physical_lease && (!memory_context_owned || !frame_port_granted)) ||
      (active && size_response_observed.error) ||
      (active && memory_rsp_valid && (memory_owner==NoMemory || memory_rsp_error)) ||
      (active && vector_rsp_valid && (!vector_pending || vector_rsp_error)) ||
      (active && merge_response.done_valid && !terminal_received &&
       (merge_response.done_error || map_cursor!=576));
    fault_active=epoch_invalid || fault_now;

    merge_request='0;
    merge_request.cfg_new_image=saved_new_image;merge_request.threshold=saved_threshold;
    merge_request.cfg_valid=rst_n && state==Configure && !fault_active;
    merge_request.map_ready=rst_n && (active || epoch_invalid);
    merge_request.sign_valid=rst_n && state==ReceiveRow && stage_row_valid && !fault_active;
    merge_request.done_ready=rst_n && active && map_cursor==576 && !terminal_received && !fault_active;
    merge_sign_data=stage_row_negative;
    stage_row_ready=merge_request.sign_valid && merge_response.sign_ready;

    merger_cut_kind=merge_response.sign_ready ? 2'd1 : merge_response.done_valid ? 2'd2 :
      merge_response.cfg_ready ? 2'd3 : 2'd0;
    size_cut_kind=size_response_observed.frame_ready ? 2'd1 : size_response_observed.map_ready ? 2'd2 : 2'd0;
    cut_kind={merger_cut_kind,size_cut_kind};
    cut_sample=!merge_response.map_valid && merger_cut_kind!=0 && size_cut_kind!=0 &&
      !size_response_observed.out_valid && !size_request_observed.frame_valid &&
      !size_request_observed.map_valid && !size_request_observed.query_valid &&
      !merge_request.cfg_valid && !merge_request.sign_valid && !merge_request.done_ready;
    cut_same=cut_sample && previous_cut_kind==cut_kind;
    cfg_ready=rst_n && state==Idle && !epoch_invalid && !abort_valid && producer_idle && !in_valid &&
      frame_port_granted && !memory_context_owned && !memory_rsp_valid && cut_same &&
      merge_response.cfg_ready && size_response_observed.frame_ready && !size_response_observed.error;
    frame_protect=rst_n && (cfg_valid || state!=Idle || physical_lease);
    memory_acquire_valid=rst_n && state==Acquire && !fault_active && frame_port_granted;

    virtual_context=row_grant && memory_context_owned && frame_port_granted;
    aggregate_idle=(state==ReleaseRow || state==FaultDrain) && memory_owner==NoMemory &&
      !memory_rsp_valid && !vector_offered && !vector_pending && !vector_rsp_valid &&
      producer_idle && !in_valid;
    virtual_release_ready=aggregate_idle && row_grant && memory_context_owned && frame_port_granted;
    stage_start_valid=rst_n && state==StartRow && !fault_active;
    stage_acquire_ready=physical_lease && memory_context_owned && frame_port_granted && !row_grant &&
      memory_owner==NoMemory && !memory_rsp_valid && !vector_offered && !vector_pending;
    stage_abort=abort_valid || (state!=FaultDrain && state!=Handoff && active && fault_now);
    stage_release_valid=row_grant && aggregate_idle && (state==ReleaseRow || state==FaultDrain);
    source_authorized=row_authorized && (state==ReceiveRow || state==FaultDrain);
    in_ready=source_authorized && stage_in_ready;
    row_request_valid=rst_n && state==RequestRow && !fault_active && stage_lease_held &&
      merge_response.sign_ready && !merge_response.map_valid;
    row_request_original_root=row_root;row_request_input_rank=input_count;
    row_request_tag=saved_tag_base+32'(input_count);row_request_layer=saved_layer;row_request_epoch=saved_epoch;

    memory_req_valid=0;memory_req_write=0;memory_req_word=0;memory_req_data=0;
    stage_memory_req_ready=0;
    if(rst_n && virtual_context && memory_owner==NoMemory && !fault_active)begin
      case(state)
        ReceiveRow: begin
          memory_req_valid=stage_memory_req_valid;memory_req_write=stage_memory_req_write;
          memory_req_word=stage_memory_req_word;memory_req_data=stage_memory_req_data;
          stage_memory_req_ready=memory_req_ready;
        end
        CopyRequest: if(read_word<256)begin memory_req_valid=1;memory_req_word={1'b0,read_word};end
        DescriptorRequest: if(kept_count<576 && read_word==255 && line_acknowledgements==32)begin
          memory_req_valid=1;memory_req_write=1;memory_req_word=10'd256+kept_count;memory_req_data=descriptor_data;
        end
        default:begin end
      endcase
    end
    memory_rsp_ready=rst_n && (memory_owner==StageMemory ? stage_memory_rsp_ready : memory_owner!=NoMemory);
    request_fire=memory_req_valid && memory_req_ready;
    response_fire=memory_rsp_valid && memory_rsp_ready;
    vector_req_valid=rst_n && vector_offered;
    vector_req_address=saved_output_base+64'(kept_count)*2048+64'(read_word[7:3])*64;
    vector_req_data=line_data;
    vector_rsp_ready=rst_n && vector_pending;
    vector_request_fire=vector_req_valid && vector_req_ready;
    vector_response_fire=vector_rsp_valid && vector_rsp_ready;
    image_done_valid=rst_n && state==Handoff && !row_grant && memory_owner==NoMemory &&
      !memory_rsp_valid && !vector_offered && !vector_pending && !vector_rsp_valid && producer_idle && !in_valid &&
      (!physical_lease || (memory_context_owned && frame_port_granted)) &&
      (epoch_invalid ? (fault_drain_complete && cut_same && !abort_valid) : !fault_now);
    image_error=epoch_invalid;abort_drained=epoch_invalid && image_done_valid;
    handoff_tag_base=saved_tag_base;handoff_layer=saved_layer;handoff_epoch=saved_epoch;
    handoff_input_count=input_count;handoff_kept_count=kept_count;
  end

  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      state<=Idle;memory_owner<=NoMemory;physical_lease<=0;row_grant<=0;row_authorized<=0;
      epoch_invalid<=0;decision_pending<=0;terminal_received<=0;terminal_error<=0;fault_drain_complete<=0;
      saved_tag_base<=0;saved_layer<=0;saved_epoch<=0;saved_new_image<=0;saved_threshold<=0;saved_output_base<=0;
      descriptor_data<=0;map_cursor<=0;input_count<=0;kept_count<=0;row_root<=0;
      read_word<=0;line_acknowledgements<=0;line_data<=0;vector_offered<=0;vector_pending<=0;previous_cut_kind<=0;
    end else begin
      previous_cut_kind<=cut_sample ? cut_kind : 4'b0;
      if(request_fire)case(state)
        ReceiveRow:memory_owner<=StageMemory;
        CopyRequest:memory_owner<=CopyMemory;
        DescriptorRequest:memory_owner<=DescriptorMemory;
        default:memory_owner<=NoMemory;
      endcase
      if(response_fire)memory_owner<=NoMemory;
      if(vector_request_fire)begin vector_offered<=0;vector_pending<=1;end
      if(vector_response_fire)vector_pending<=0;
      if(stage_start_valid && stage_start_ready)row_grant<=1;
      if(stage_memory_release_valid && virtual_release_ready)begin row_grant<=0;row_authorized<=0;end
      if(map_fire && map_cursor<576)map_cursor<=map_cursor+1'b1;

      if(!fault_active)begin
        if(merge_response.done_valid && merge_request.done_ready)begin
          terminal_received<=1;terminal_error<=merge_response.done_error;
        end
        case(state)
          Idle:if(cfg_valid && cfg_ready)begin
            saved_tag_base<=cfg_tag_base;saved_layer<=cfg_layer;saved_epoch<=cfg_epoch;
            saved_new_image<=cfg_new_image;saved_threshold<=cfg_minimum_matches;saved_output_base<=cfg_compact_output_base;
            map_cursor<=0;input_count<=0;kept_count<=0;terminal_received<=0;terminal_error<=0;
            fault_drain_complete<=0;decision_pending<=0;
            if(configuration_legal)state<=Acquire;
            else begin epoch_invalid<=1;state<=FaultDrain;previous_cut_kind<=0;end
          end
          Acquire:if(memory_acquire_valid && memory_acquire_ready)begin physical_lease<=1;state<=Configure;end
          Configure:if(merge_request.cfg_valid && merge_response.cfg_ready)state<=AwaitRoot;
          AwaitRoot:begin
            if(map_cursor==576)state<=WaitTerminal;
            else if(merge_response.sign_ready && !merge_response.map_valid && producer_idle && !row_grant)begin
              row_root<=map_cursor;state<=StartRow;
            end
          end
          StartRow:if(stage_start_valid && stage_start_ready)state<=RequestRow;
          RequestRow:if(row_request_valid && row_request_ready)begin row_authorized<=1;state<=ReceiveRow;end
          ReceiveRow:if(merge_request.sign_valid && merge_response.sign_ready)begin
            decision_pending<=1;input_count<=input_count+1'b1;
            descriptor_data<={1'b0,1'b1,1'b0,stage_row_exponent,kept_count,row_root,stage_row_tag};state<=Decision;
          end
          Decision:if(map_fire && decision_pending)begin
            decision_pending<=0;
            if(merge_response.map_origin==merge_response.map_index)begin
              read_word<=0;line_acknowledgements<=0;state<=CopyRequest;
            end else state<=ReleaseRow;
          end
          CopyRequest:if(request_fire)state<=CopyResponse;
          CopyResponse:if(response_fire)begin
            line_data[read_word[2:0]*64+:64]<=memory_rsp_data;
            if(read_word[2:0]==7)begin vector_offered<=1;state<=OfferLine;end
            else begin read_word<=read_word+1'b1;state<=CopyRequest;end
          end
          OfferLine:if(vector_request_fire)state<=LineResponse;
          LineResponse:if(vector_response_fire)begin
            line_acknowledgements<=line_acknowledgements+1'b1;
            if(read_word==255)state<=DescriptorRequest;
            else begin read_word<=read_word+1'b1;state<=CopyRequest;end
          end
          DescriptorRequest:if(request_fire)state<=DescriptorResponse;
          DescriptorResponse:if(response_fire)begin kept_count<=kept_count+1'b1;state<=ReleaseRow;end
          ReleaseRow:if(stage_release_valid && stage_release_ready)state<=AwaitRoot;
          WaitTerminal:if(terminal_received && !terminal_error && !row_grant && !decision_pending &&
            memory_owner==NoMemory && !memory_rsp_valid && !vector_offered && !vector_pending &&
            !vector_rsp_valid && producer_idle && !in_valid)state<=Handoff;
          default:begin end
        endcase
      end

      // Drains stay live after a fault. In particular the Stage keeps its
      // logical context and an already offered vector stays asserted.
      if(state==FaultDrain && !row_grant && memory_owner==NoMemory && !memory_rsp_valid &&
        !vector_offered && !vector_pending && !vector_rsp_valid && producer_idle && !in_valid &&
        !abort_valid && cut_same && (!physical_lease || (memory_context_owned && frame_port_granted)))begin
        fault_drain_complete<=1;state<=Handoff;
      end
      if(state==Handoff && image_done_valid && image_done_ready)begin
        physical_lease<=0;state<=Idle;
      end
      if(fault_now && !epoch_invalid)begin
        epoch_invalid<=1;state<=FaultDrain;decision_pending<=0;previous_cut_kind<=0;
      end
    end
  end
endmodule
