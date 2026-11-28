`timescale 1ns/1ps
`default_nettype none
// One admitted projection job: all40 heads,1..16 contiguous cache slots.
// Vector payload lives ONLY in caller-owned external memory. This module owns
// the real legacy writer and a single512-bit read-response register, no SRAM.
// No original-position or causal-Size truth is invented by this raw cache path.
module tri_oracle_committed_qkv_cache_v1 (
  input logic clk,rst_n,cancel,
  input logic cfg_valid,output logic cfg_ready,
  input logic [31:0] cfg_tag,cfg_generation,
  input logic [4:0] cfg_layer,cfg_tokens,
  input logic [15:0] cfg_epoch,
  input logic [9:0] cfg_slot,
  input logic [63:0] cfg_activation_base,cfg_activation_bytes,
  input logic [63:0] cfg_weight_base,cfg_weight_bytes,cfg_cache_base,cfg_cache_bytes,
  input logic [239:0] cfg_shifts,input logic [95:0] cfg_shift_biases,
  input logic [359:0] cfg_head_units,
  output logic producer_cfg_valid,input logic producer_cfg_ready,
  output logic [31:0] producer_cfg_tag,
  output logic [4:0] producer_cfg_tokens,
  output logic [63:0] producer_cfg_activation_base,producer_cfg_weight_base,
  output logic [239:0] producer_cfg_shifts,output logic [95:0] producer_cfg_shift_biases,
  output logic producer_enabled,
  input logic source_valid,source_last,output logic source_ready,
  input logic [31:0] source_tag,input logic [5:0] source_head,
  input logic [3:0] source_token,input logic [511:0] source_data,
  input logic source_done_valid,source_done_error,output logic source_done_ready,
  input logic [31:0] source_done_tag,
  output logic cache_write_valid,input logic cache_write_ready,
  output logic [63:0] cache_write_address,output logic [511:0] cache_write_data,
  output logic [4:0] cache_write_length,
  input logic cache_write_rsp_valid,cache_write_rsp_error,output logic cache_write_rsp_ready,
  output logic done_valid,done_error,input logic done_ready,
  output logic [31:0] done_tag,done_generation,
  output logic committed_valid,output logic [9:0] committed_first_slot,
  output logic [4:0] committed_tokens,
  input logic retire_valid,output logic retire_ready,
  input logic read_valid,output logic read_ready,
  input logic [31:0] read_tag,read_generation,input logic [4:0] read_layer,
  input logic [15:0] read_epoch,input logic [5:0] read_head,input logic [9:0] read_slot,
  output logic read_result_valid,input logic read_result_ready,
  output logic read_result_error,output logic [31:0] read_result_tag,read_result_generation,
  output logic [4:0] read_result_layer,output logic [15:0] read_result_epoch,
  output logic [5:0] read_result_head,output logic [9:0] read_result_slot,
  output logic signed [8:0] read_result_unit,output logic [511:0] read_result_data,
  output logic memory_read_valid,input logic memory_read_ready,
  output logic [63:0] memory_read_address,output logic [4:0] memory_read_length,
  input logic memory_rsp_valid,memory_rsp_last,memory_rsp_error,
  input logic [63:0] memory_rsp_data,output logic memory_rsp_ready,
  output logic fault,reset_required,busy
);
  localparam logic [63:0] HEAD_STRIDE=64'd65536,WEIGHT_BYTES=64'd5242880;
  typedef enum logic [2:0] {Idle,Launch,Produce,Finish,Visible,Stopped} state_t;
  typedef enum logic [2:0] {ReadIdle,ReadIssue,ReadWait,ReadDrain,ReadReply,ReadQuarantine} read_state_t;
  state_t state;
  read_state_t read_state;
  logic [31:0] tag,generation,last_generation;
  logic [4:0] layer,tokens;
  logic [15:0] epoch;
  logic [9:0] first_slot;
  logic [63:0] activation_base,weight_base,cache_base,cache_bytes;
  logic [239:0] shifts;
  logic [95:0] biases;
  logic [359:0] units;
  logic generation_seen,producer_sent,store_sent,write_pending,fault_q,quarantine_q;
  logic cfg_bad,raw_fault,raw_quarantine,source_unknown;
  logic s_cfg_ready,s_source_ready,s_source_done_ready,s_write_valid,s_write_rsp_ready;
  logic s_done_valid,s_done_error,s_cfg_valid,s_source_valid;
  logic [31:0] s_done_tag;
  logic [63:0] s_write_address;
  logic [511:0] s_write_data;
  logic [9:0] requests,acknowledgments;
  logic [64:0] activation_end,weight_end,cache_end,required_cache_end;
  logic [10:0] slot_end;
  logic [63:0] expected_write_address;
  logic [5:0] expected_head;
  logic [4:0] expected_token;
  logic [3:0] read_beat;
  logic read_failed;
  logic [511:0] read_buffer;
  logic [63:0] read_address;
  logic producer_fire,store_fire,write_fire,write_rsp_fire;

  logic unknown_config;
  logic unknown_write;
  logic unknown_config_tag;
  logic unknown_config_generation;
  logic unknown_read;
  logic unknown_read_tag;
  logic unknown_read_data;

  // These four-state tests have no physical unknown detector.
  always_comb begin
    unknown_config = 1'b0;
    source_unknown = 1'b0;
    unknown_write = 1'b0;
    unknown_config_tag = 1'b0;
    unknown_config_generation = 1'b0;
    unknown_read = 1'b0;
    unknown_read_tag = 1'b0;
    unknown_read_data = 1'b0;
    // synthesis translate_off
    unknown_config = $isunknown({cfg_tag,cfg_generation,cfg_layer,cfg_epoch,cfg_tokens,cfg_slot,
      cfg_activation_base,cfg_activation_bytes,cfg_weight_base,cfg_weight_bytes,cfg_cache_base,cfg_cache_bytes,
      cfg_shifts,cfg_shift_biases,cfg_head_units});
    source_unknown = $isunknown({source_last,source_tag,source_head,source_token,source_data});
    unknown_write = $isunknown({s_write_address,s_write_data});
    unknown_config_tag = $isunknown(cfg_tag);
    unknown_config_generation = $isunknown(cfg_generation);
    unknown_read = $isunknown({read_tag,read_generation,read_layer,read_epoch,read_head,read_slot});
    unknown_read_tag = $isunknown(read_tag);
    unknown_read_data = $isunknown(memory_rsp_data);
    // synthesis translate_on
  end

  function automatic logic disjoint(input logic [63:0] a,ab,b,bb);
    logic [64:0] ae,be;
    ae={1'b0,a}+{1'b0,ab};be={1'b0,b}+{1'b0,bb};
    return !ae[64] && !be[64] && (ae<={1'b0,b} || be<={1'b0,a});
  endfunction

  // Request/address producers read saved registers only. No return-response
  // process drives these fields, and no producer valid is cancelled by fault.
  always_comb begin
    cfg_ready=rst_n===1'b1 && state==Idle && !fault_q && cancel===1'b0 && !raw_fault;
    producer_cfg_valid=state==Launch && !producer_sent;
    producer_cfg_tag=tag;producer_cfg_tokens=tokens;
    producer_cfg_activation_base=activation_base;producer_cfg_weight_base=weight_base;
    producer_cfg_shifts=shifts;producer_cfg_shift_biases=biases;
    producer_enabled=(state==Produce) && !quarantine_q;
    s_cfg_valid=state==Launch && !store_sent;
    s_source_valid=state==Produce && source_valid===1'b1 && !source_unknown && !quarantine_q;
    source_ready=state==Produce && !source_unknown && !quarantine_q && s_source_ready;
    source_done_ready=state==Produce && !quarantine_q && s_source_done_ready;
    cache_write_valid=s_write_valid;cache_write_address=s_write_address;cache_write_data=s_write_data;
    cache_write_length=5'd8;cache_write_rsp_ready=s_write_rsp_ready;
    done_valid=state==Finish;done_tag=tag;done_generation=generation;
    committed_valid=state==Visible && !fault_q && cancel===1'b0;
    committed_first_slot=first_slot;committed_tokens=tokens;
    retire_ready=state==Visible && read_state==ReadIdle && !fault_q && cancel===1'b0;
    read_ready=state==Visible && read_state==ReadIdle && !fault_q && !raw_fault && cancel===1'b0 && retire_valid===1'b0;
    read_result_valid=read_state==ReadReply;read_result_data=read_buffer;
    memory_read_valid=read_state==ReadIssue;memory_read_address=read_address;memory_read_length=5'd8;
    memory_rsp_ready=read_state==ReadWait || read_state==ReadDrain;
    fault=fault_q;reset_required=fault_q;busy=state!=Idle || read_state!=ReadIdle;
  end

  // Handshake producers are separate from admission outputs: the raw-fault
  // process cannot trigger a returning request through a response-reading
  // request-builder block. Physical offers depend on registered owner state.
  always_comb begin
    producer_fire=(state==Launch && !producer_sent) && producer_cfg_ready===1'b1;
    store_fire=(state==Launch && !store_sent) && s_cfg_ready===1'b1;
    write_fire=s_write_valid && cache_write_ready===1'b1;
    write_rsp_fire=s_write_rsp_ready && cache_write_rsp_valid===1'b1;
  end

  always_comb begin
    activation_end={1'b0,cfg_activation_base}+{1'b0,cfg_activation_bytes};
    weight_end={1'b0,cfg_weight_base}+{1'b0,cfg_weight_bytes};
    cache_end={1'b0,cfg_cache_base}+{1'b0,cfg_cache_bytes};
    slot_end={1'b0,cfg_slot}+11'(cfg_tokens);
    required_cache_end={1'b0,cfg_cache_base}+65'd2555904+(65'(cfg_slot)+65'(cfg_tokens))*65'd64;
    cfg_bad=unknown_config || cfg_tokens==0 || cfg_tokens>16 || slot_end>1024 ||
      cfg_activation_base[2:0]!=0 || cfg_weight_base[2:0]!=0 || cfg_cache_base[5:0]!=0 ||
      cfg_activation_bytes<(64'(cfg_tokens)*2048) || cfg_weight_bytes<WEIGHT_BYTES || cfg_cache_bytes==0 ||
      activation_end[64] || weight_end[64] || cache_end[64] || required_cache_end[64] || required_cache_end>cache_end ||
      !disjoint(cfg_activation_base,cfg_activation_bytes,cfg_weight_base,cfg_weight_bytes) ||
      !disjoint(cfg_activation_base,cfg_activation_bytes,cfg_cache_base,cfg_cache_bytes) ||
      !disjoint(cfg_weight_base,cfg_weight_bytes,cfg_cache_base,cfg_cache_bytes) ||
      (generation_seen && cfg_generation<=last_generation);
    expected_head=0;expected_token=0;expected_write_address=cache_base;
    if(tokens!=0)begin
      expected_head=6'((int'(requests)/(2*int'(tokens)))*2+(int'(requests)%2));
      expected_token=5'((int'(requests)%(2*int'(tokens)))/2);
      expected_write_address=cache_base+64'(expected_head)*HEAD_STRIDE+(64'(first_slot)+64'(expected_token))*64;
    end
  end

  always_comb begin
    raw_fault=cancel!==1'b0;raw_quarantine=cancel!==1'b0 && cancel!==1'b1;
    if(state==Idle && cfg_valid!==1'b0 && cfg_valid!==1'b1)begin raw_fault=1;raw_quarantine=1;end
    if(state==Produce && source_valid!==1'b0 && source_valid!==1'b1)begin raw_fault=1;raw_quarantine=1;end
    if(state==Produce && source_valid===1'b1 && source_unknown)begin raw_fault=1;raw_quarantine=1;end
    if(s_write_valid)begin
      if(unknown_write || requests>=10'(40*int'(tokens)) || s_write_address!=expected_write_address)begin raw_fault=1;raw_quarantine=1;end
      if(cache_write_ready!==1'b0 && cache_write_ready!==1'b1)begin raw_fault=1;raw_quarantine=1;end
    end
    if(cache_write_rsp_valid!==1'b0 && cache_write_rsp_valid!==1'b1)begin raw_fault=1;raw_quarantine=1;end
    if(cache_write_rsp_valid===1'b1 && !write_pending && !write_fire)begin raw_fault=1;raw_quarantine=1;end
    if(write_rsp_fire && cache_write_rsp_error!==1'b0)raw_fault=1;
    if(state==Produce && source_done_valid!==1'b0 && source_done_valid!==1'b1)begin raw_fault=1;raw_quarantine=1;end
    if(state==Visible && (read_valid!==1'b0 && read_valid!==1'b1))begin raw_fault=1;raw_quarantine=1;end
    if(state==Visible && (retire_valid!==1'b0 && retire_valid!==1'b1))begin raw_fault=1;raw_quarantine=1;end
    if(memory_rsp_valid!==1'b0 && memory_rsp_valid!==1'b1)begin raw_fault=1;raw_quarantine=1;end
    // This bus admits its first response no earlier than the cycle AFTER the
    // read-header handshake. An unsolicited/zero-latency response is ambiguous.
    if(memory_rsp_valid===1'b1 && read_state!=ReadWait && read_state!=ReadDrain)begin raw_fault=1;raw_quarantine=1;end
    if(read_state==ReadIssue && memory_read_ready!==1'b0 && memory_read_ready!==1'b1)begin raw_fault=1;raw_quarantine=1;end
    if((read_state==ReadWait || read_state==ReadDrain) && memory_rsp_valid===1'b1 &&
      (memory_rsp_last!==1'b0 && memory_rsp_last!==1'b1))begin raw_fault=1;raw_quarantine=1;end
  end

  tri_oracle_qkv_store430 writer (
    .clk,.rst_n,.cfg_valid(s_cfg_valid),.cfg_ready(s_cfg_ready),.cfg_tag(tag),.cfg_tokens(tokens),
    .cfg_first_head(6'd0),.cfg_heads(6'd40),.cfg_slot(first_slot),.cfg_base(cache_base),
    .source_valid(s_source_valid),.source_last,.source_ready(s_source_ready),.source_tag,.source_head,.source_token,.source_data,
    .source_done_valid(state==Produce && source_done_valid===1'b1 && !quarantine_q),
    .source_done_error,.source_done_ready(s_source_done_ready),.source_done_tag,
    .write_valid(s_write_valid),.write_ready(cache_write_ready===1'b1),.write_address(s_write_address),.write_data(s_write_data),
    .write_rsp_valid(cache_write_rsp_valid===1'b1),.write_rsp_error(cache_write_rsp_error),.write_rsp_ready(s_write_rsp_ready),
    .done_valid(s_done_valid),.done_error(s_done_error),.done_ready(state==Produce),.done_tag(s_done_tag)
  );

  always_ff @(posedge clk or negedge rst_n)begin
    if(rst_n===1'b0)begin
      state<=Idle;read_state<=ReadIdle;fault_q<=0;quarantine_q<=0;done_error<=0;
      tag<=0;generation<=0;last_generation<=0;generation_seen<=0;layer<=0;epoch<=0;tokens<=0;first_slot<=0;
      activation_base<=0;weight_base<=0;cache_base<=0;cache_bytes<=0;shifts<=0;biases<=0;units<=0;
      producer_sent<=0;store_sent<=0;write_pending<=0;requests<=0;acknowledgments<=0;
      read_address<=0;read_buffer<=0;read_beat<=0;read_failed<=0;read_result_error<=0;
      read_result_tag<=0;read_result_generation<=0;read_result_layer<=0;read_result_epoch<=0;
      read_result_head<=0;read_result_slot<=0;read_result_unit<=0;
    end else if(rst_n!==1'b1)begin fault_q<=1;quarantine_q<=1;end
    else begin
      if(write_fire)begin write_pending<=1;requests<=requests+1'b1;end
      if(write_rsp_fire)begin write_pending<=0;acknowledgments<=acknowledgments+1'b1;end
      case(state)
        Idle:if(cfg_valid===1'b1 && cfg_ready)begin
          done_error<=0;producer_sent<=0;store_sent<=0;requests<=0;acknowledgments<=0;write_pending<=0;
          if(cfg_bad)begin
            tag<=unknown_config_tag?32'd0:cfg_tag;generation<=unknown_config_generation?32'd0:cfg_generation;
            done_error<=1;fault_q<=1;state<=Finish;
          end else begin
            tag<=cfg_tag;generation<=cfg_generation;layer<=cfg_layer;epoch<=cfg_epoch;tokens<=cfg_tokens;first_slot<=cfg_slot;
            activation_base<=cfg_activation_base;weight_base<=cfg_weight_base;cache_base<=cfg_cache_base;cache_bytes<=cfg_cache_bytes;
            shifts<=cfg_shifts;biases<=cfg_shift_biases;units<=cfg_head_units;last_generation<=cfg_generation;generation_seen<=1;state<=Launch;
          end
        end
        Launch:begin
          if(producer_fire)producer_sent<=1;if(store_fire)store_sent<=1;
          if((producer_sent || producer_fire) && (store_sent || store_fire))state<=Produce;
        end
        Produce:if(s_done_valid===1'b1)begin
          done_error<=s_done_error!==1'b0 || s_done_tag!==tag || requests!=10'(40*int'(tokens)) ||
            acknowledgments!=10'(40*int'(tokens)) || write_pending || fault_q || raw_fault;
          if(s_done_error!==1'b0 || s_done_tag!==tag || requests!=10'(40*int'(tokens)) ||
            acknowledgments!=10'(40*int'(tokens)) || write_pending)fault_q<=1;
          state<=Finish;
        end
        Finish:if(done_ready===1'b1)state<=done_error ? Stopped:Visible;
        Visible:if(retire_valid===1'b1 && retire_ready)state<=Idle;
        default:begin end
      endcase
      case(read_state)
        ReadIdle:if(read_valid===1'b1 && read_ready)begin
          read_buffer<=0;read_beat<=0;read_failed<=0;
          if(unknown_read ||
            read_generation!==generation || read_layer!==layer || read_epoch!==epoch || read_head>=40 ||
            {1'b0,read_slot}<{1'b0,first_slot} || {1'b0,read_slot}>={1'b0,first_slot}+11'(tokens))begin
            read_result_tag<=unknown_read_tag?32'd0:read_tag;read_result_generation<=generation;
            read_result_layer<=layer;read_result_epoch<=epoch;read_result_head<=0;read_result_slot<=0;read_result_unit<=0;
            read_result_error<=1;fault_q<=1;read_state<=ReadReply;
          end else begin
            read_result_tag<=read_tag;read_result_generation<=generation;read_result_layer<=layer;read_result_epoch<=epoch;
            read_result_head<=read_head;read_result_slot<=read_slot;read_result_unit<=$signed(units[int'(read_head)*9+:9]);
            read_result_error<=0;read_address<=cache_base+64'(read_head)*HEAD_STRIDE+64'(read_slot)*64;read_state<=ReadIssue;
          end
        end
        ReadIssue:if(memory_read_ready===1'b1)begin read_failed<=fault_q || raw_fault;read_state<=ReadWait;end
        ReadWait:if(memory_rsp_valid===1'b1)begin
          if(memory_rsp_last!==1'b0 && memory_rsp_last!==1'b1)read_state<=ReadQuarantine;
          else if(memory_rsp_error!==1'b0 || unknown_read_data || memory_rsp_last!==(read_beat==7))begin
            fault_q<=1;read_failed<=1;read_buffer<=0;
            if(memory_rsp_last===1'b1)begin read_result_error<=1;read_state<=ReadReply;end
            else read_state<=ReadDrain;
          end else begin
            read_buffer[int'(read_beat)*64+:64]<=memory_rsp_data;
            if(read_beat==7)begin read_result_error<=read_failed || fault_q || raw_fault;read_state<=ReadReply;end
            else read_beat<=read_beat+1'b1;
          end
        end
        ReadDrain:if(memory_rsp_valid===1'b1)begin
          if(memory_rsp_last!==1'b0 && memory_rsp_last!==1'b1)read_state<=ReadQuarantine;
          else if(memory_rsp_last===1'b1)begin read_result_error<=1;read_state<=ReadReply;end
        end
        ReadReply:if(read_result_ready===1'b1)read_state<=ReadIdle;
        default:begin end
      endcase
      // Independent registered poison is authoritative even when an earlier
      // already-offered successful response/Done tuple must remain stable.
      if(raw_fault)fault_q<=1;
      if(raw_quarantine)begin quarantine_q<=1;fault_q<=1;end
    end
  end
endmodule
`default_nettype wire
