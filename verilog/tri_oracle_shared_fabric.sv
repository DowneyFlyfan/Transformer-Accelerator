`timescale 1ns/1ps
// Five original four-core clusters share projection slot0 and down slots1..15.
// Down input codes/IDs broadcast; output row groups are disjoint. The producer
// supplies each output round and asserts final only on its last contribution.
// Fatal packets drain advertised/accepted external memory work before reset.
module tri_oracle_shared_fabric (
    input logic clk,rst_n,in_valid,in_is_down,in_last,in_fallback,in_accumulate,out_ready,
    input logic [31:0] in_tag,
    input logic [2559:0] in_channels,
    input logic [1023:0] in_data,
    input logic [7:0] in_count,in_output_count,
    input logic [63:0] in_activation_base,in_weight_base,
    input logic [9:0] in_features,
    input logic [16:0] in_dense_features,
    input logic [15:0] in_output_start,
    input logic [5:0] in_shift,
    input logic [3:0] in_slot,
    output logic in_ready,out_valid,out_is_down,out_last,out_fallback,out_error,
    output logic [31:0] out_tag,
    output logic [7:0] out_count,
    output logic [2559:0] out_channels,
    output logic [5119:0] out_data,
    output logic [15:0] out_start,
    output logic [3:0] out_slot,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,rsp_last,rsp_error,
    output logic rsp_ready,
    input logic [63:0] rsp_data
);
  localparam int Clusters=5;
  localparam int Rows=160;
  localparam logic [64:0] LastAddress=65'h0ffffffffffffffff;
  typedef enum logic [2:0] {IDLE,START,COLLECT,ABORT_DRAIN,RESET_CHILDREN,RESULT} state_t;
  state_t state;
  logic child_rst_n,reset_second_cycle,is_down,last,fallback,accumulate,result_error;
  logic [31:0] tag;
  logic [7:0] count,output_count;
  logic [2559:0] channels;
  logic [1023:0] codes;
  logic [5119:0] sums;
  logic [63:0] activation_base,weight_base;
  logic [9:0] features;
  logic [16:0] dense_features;
  logic [15:0] output_start;
  logic [5:0] shift;
  logic [3:0] slot;
  // A child sees only its local32-row shape. Retain the global range so
  // skipping a formerly active cluster cannot silently lose contributions.
  logic [15:0] context_valid;
  logic [31:0] context_tag[16];
  logic [15:0] context_start[16];
  logic [7:0] context_count[16];
  logic [4:0] active,started,received;
  logic [4:0] child_in_valid,child_in_ready,child_out_valid,child_out_ready;
  logic [4:0] child_out_error,child_out_is_down,child_last,child_fallback;
  logic [5:0] child_count[Clusters],child_output_count[Clusters],child_result_count[Clusters];
  logic [15:0] child_start[Clusters],child_result_start[Clusters];
  logic [3:0] child_result_slot[Clusters];
  logic [511:0] child_input_channels[Clusters],child_channels[Clusters];
  logic [31:0] child_tag[Clusters];
  logic [1023:0] child_data[Clusters];
  logic [4:0] child_req_valid,child_req_ready,child_rsp_valid,child_rsp_ready;
  logic [63:0] child_req_address[Clusters];
  logic [4:0] child_req_length[Clusters];
  logic [4:0] cluster_rst_n,cluster_load_valid,cluster_load_error;
  logic [1:0] cluster_load_core[Clusters],cluster_load_kind[Clusters];
  logic [9:0] cluster_load_address[Clusters],cluster_cmd_activation[Clusters];
  logic [2047:0] cluster_load_data[Clusters];
  logic [31:0] cluster_load_rows[Clusters];
  logic [4:0] cluster_cmd_valid,cluster_cmd_ready,cluster_cmd_accumulate;
  logic [4:0] cluster_cmd_weight[Clusters],cluster_cmd_mask[Clusters];
  logic [3:0] cluster_cmd_output[Clusters],cluster_out_output[Clusters];
  logic [4:0] cluster_out_valid,cluster_out_ready;
  logic [1023:0] cluster_out_data[Clusters];
  logic invalid_shape,fault_now,offer,busy,candidate_valid;
  logic [64:0] input_bytes,activation_end,weight_end;
  logic [2:0] offer_owner,response_owner,round_robin,candidate;
  logic [63:0] offered_address;
  logic [4:0] offered_length;

  // This shape block consumes only captured data and has no ready/fault input.
  always_comb begin
    active=0;
    for(int c=0;c<Clusters;c++) begin
      child_count[c]=0;child_output_count[c]=0;
      child_start[c]=16'(int'(output_start)+c*32);
      child_input_channels[c]=is_down?channels[511:0]:channels[c*512+:512];
      if(is_down) begin
        child_count[c]=6'(count);
        if(int'(output_count)>c*32) begin
          active[c]=1;
          child_output_count[c]=6'(int'(output_count)-c*32>32?32:int'(output_count)-c*32);
        end
      end else if(int'(count)>c*32) begin
        active[c]=1;
        child_count[c]=6'(int'(count)-c*32>32?32:int'(count)-c*32);
      end
    end
  end

  always_comb begin
    input_bytes=65'(in_features)<<3;
    activation_end={1'b0,in_activation_base}+input_bytes-1;
    weight_end=0;
    if(in_is_down) begin
      invalid_shape=in_count>32 || in_output_count==0 || in_output_count>Rows || in_slot==0 ||
          in_dense_features<8 || in_dense_features>65536 || in_dense_features[2:0]!=0 ||
          (17'(in_output_start)+17'(in_output_count)>17'd65536) || in_weight_base[2:0]!=0 ||
          (in_accumulate && (!context_valid[in_slot] || context_tag[in_slot]!=in_tag ||
             context_start[in_slot]!=in_output_start || context_count[in_slot]!=in_output_count));
      for(int row=0;row<32;row++)
        if(row<int'(in_count) && 17'(in_channels[row*16+:16])>=in_dense_features) invalid_shape=1;
    end else begin
      invalid_shape=in_count>Rows || (in_count!=0 &&
          (in_features==0 || in_features>512 || in_activation_base[2:0]!=0 ||
           in_weight_base[2:0]!=0 || activation_end>LastAddress));
      for(int row=0;row<Rows;row++) begin
        weight_end={1'b0,in_weight_base}+(65'(in_channels[row*16+:16])+1)*input_bytes-1;
        if(row<int'(in_count) && weight_end>LastAddress) invalid_shape=1;
      end
    end
  end

  always_comb begin
    fault_now=0;
    for(int c=0;c<Clusters;c++) begin
      if((state==START || state==COLLECT) && started[c] && !received[c] && child_out_valid[c]) begin
        if(child_out_error[c] || child_out_is_down[c]!=is_down || child_tag[c]!=tag ||
           child_result_count[c]!=(is_down?child_output_count[c]:child_count[c]) ||
           child_last[c]!=last || child_fallback[c]!=(is_down?1'b0:fallback) ||
           child_channels[c]!=(is_down?512'b0:child_input_channels[c]) ||
           child_result_start[c]!=(is_down?child_start[c]:16'b0) ||
           child_result_slot[c]!=(is_down?slot:4'b0)) fault_now=1;
      end
    end
  end

  always_comb begin
    in_ready=state==IDLE && child_rst_n && (&child_in_ready);
    out_valid=state==RESULT;out_is_down=is_down;out_tag=tag;
    out_last=result_error || last;out_fallback=!result_error && !is_down && fallback;
    out_error=result_error;out_count=result_error?8'b0:(is_down?output_count:count);
    out_channels=result_error || is_down?2560'b0:channels;
    out_data=result_error?5120'b0:sums;
    out_start=is_down?output_start:16'b0;out_slot=is_down?slot:4'b0;
    child_in_valid=0;child_out_ready=0;
    for(int c=0;c<Clusters;c++) begin
      child_in_valid[c]=state==START && active[c] && !started[c] && !fault_now;
      child_out_ready[c]=state==COLLECT && active[c] && !received[c] && !fault_now;
    end
  end

  always_comb begin : arbitrate_memory
    int index;
    candidate=0;candidate_valid=0;index=0;
    for(int offset=0;offset<Clusters;offset++) begin
      index=int'(round_robin)+offset;
      if(index>=Clusters) index-=Clusters;
      if(!candidate_valid && child_req_valid[index]) begin
        candidate=3'(index);candidate_valid=1;
      end
    end
    req_valid=offer;req_address=offered_address;req_length=offered_length;
    child_req_ready=0;child_rsp_valid=0;rsp_ready=0;
    if(offer) child_req_ready[offer_owner]=req_ready;
    if(busy) begin
      child_rsp_valid[response_owner]=rsp_valid;
      rsp_ready=child_rsp_ready[response_owner];
    end
  end

  for(genvar c=0;c<Clusters;c++) begin : clusters
    tri_oracle_shared_cluster_executor control (
        .clk(clk),.rst_n(child_rst_n),.in_valid(child_in_valid[c]),.in_ready(child_in_ready[c]),
        .in_is_down(is_down),.in_last(last),.in_fallback(fallback),.in_accumulate(accumulate),
        .in_tag(tag),.in_count(child_count[c]),.in_output_count(child_output_count[c]),.in_shift(shift),
        .in_channels(child_input_channels[c]),.in_data(codes),.in_activation_base(activation_base),
        .in_weight_base(weight_base),.in_features(features),.in_dense_features(dense_features),
        .in_output_start(child_start[c]),.in_slot(slot),.out_ready(child_out_ready[c]),
        .out_valid(child_out_valid[c]),.out_is_down(child_out_is_down[c]),.out_last(child_last[c]),
        .out_fallback(child_fallback[c]),.out_error(child_out_error[c]),.out_tag(child_tag[c]),
        .out_count(child_result_count[c]),.out_channels(child_channels[c]),.out_start(child_result_start[c]),
        .out_slot(child_result_slot[c]),.out_data(child_data[c]),.req_valid(child_req_valid[c]),
        .req_ready(child_req_ready[c]),.req_address(child_req_address[c]),.req_length(child_req_length[c]),
        .rsp_valid(child_rsp_valid[c]),.rsp_last(rsp_last),.rsp_error(rsp_error),
        .rsp_ready(child_rsp_ready[c]),.rsp_data(rsp_data),.cluster_rst_n(cluster_rst_n[c]),
        .cluster_load_valid(cluster_load_valid[c]),.cluster_load_core(cluster_load_core[c]),
        .cluster_load_kind(cluster_load_kind[c]),.cluster_load_address(cluster_load_address[c]),
        .cluster_load_data(cluster_load_data[c]),.cluster_load_rows(cluster_load_rows[c]),
        .cluster_load_error(cluster_load_error[c]),.cluster_cmd_valid(cluster_cmd_valid[c]),
        .cluster_cmd_ready(cluster_cmd_ready[c]),.cluster_cmd_weight(cluster_cmd_weight[c]),
        .cluster_cmd_mask(cluster_cmd_mask[c]),.cluster_cmd_activation(cluster_cmd_activation[c]),
        .cluster_cmd_output(cluster_cmd_output[c]),.cluster_cmd_accumulate(cluster_cmd_accumulate[c]),
        .cluster_out_valid(cluster_out_valid[c]),.cluster_out_ready(cluster_out_ready[c]),
        .cluster_out_output(cluster_out_output[c]),.cluster_out_data(cluster_out_data[c])
    );
    tri_oracle_sram_compute_cluster cluster (
        .clk(clk),.rst_n(cluster_rst_n[c]),.load_valid(cluster_load_valid[c]),.load_core(cluster_load_core[c]),
        .load_kind(cluster_load_kind[c]),.load_addr(cluster_load_address[c]),.load_data(cluster_load_data[c]),
        .load_row_enable(cluster_load_rows[c]),.load_error(cluster_load_error[c]),
        .cmd_valid(cluster_cmd_valid[c]),.cmd_ready(cluster_cmd_ready[c]),.cmd_weight(cluster_cmd_weight[c]),
        .cmd_mask(cluster_cmd_mask[c]),.cmd_activation(cluster_cmd_activation[c]),.cmd_output(cluster_cmd_output[c]),
        .cmd_accumulate(cluster_cmd_accumulate[c]),.cmd_reduce(2'b0),.out_valid(cluster_out_valid[c]),
        .out_ready(cluster_out_ready[c]),.out_output(cluster_out_output[c]),.out_data(cluster_out_data[c])
    );
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      offer<=0;busy<=0;offer_owner<=0;response_owner<=0;round_robin<=0;
      offered_address<=0;offered_length<=0;
    end else begin
      if(state==IDLE) round_robin<=0;
      if(offer && req_ready) begin
        offer<=0;busy<=1;response_owner<=offer_owner;
        round_robin<=offer_owner==3'(Clusters-1)?3'b0:offer_owner+1'b1;
      end
      if(busy && rsp_valid && rsp_ready && rsp_last) busy<=0;
      if(!offer && !busy && (state==START || state==COLLECT) && !fault_now && candidate_valid) begin
        offer<=1;offer_owner<=candidate;offered_address<=child_req_address[candidate];
        offered_length<=child_req_length[candidate];
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      state<=IDLE;child_rst_n<=0;reset_second_cycle<=0;is_down<=0;last<=0;fallback<=0;
      accumulate<=0;result_error<=0;tag<=0;count<=0;output_count<=0;channels<=0;codes<=0;sums<=0;
      activation_base<=0;weight_base<=0;features<=0;dense_features<=0;output_start<=0;shift<=0;slot<=0;
      started<=0;received<=0;
      context_valid<=0;
      for(int index=0;index<16;index++) begin
        context_tag[index]<=0;context_start[index]<=0;context_count[index]<=0;
      end
    end else begin
      child_rst_n<=1;
      if((state==START || state==COLLECT) && fault_now) begin
        result_error<=1;sums<=0;context_valid<=0;state<=ABORT_DRAIN;
      end else case(state)
        IDLE: if(in_valid && in_ready) begin
          is_down<=in_is_down;last<=in_last;fallback<=in_fallback;accumulate<=in_accumulate;
          tag<=in_tag;count<=in_count;output_count<=in_output_count;channels<=in_channels;codes<=in_data;
          activation_base<=in_activation_base;weight_base<=in_weight_base;features<=in_features;
          dense_features<=in_dense_features;output_start<=in_output_start;shift<=in_shift;slot<=in_slot;
          sums<=0;started<=0;received<=0;result_error<=invalid_shape;
          if(invalid_shape) context_valid<=0;
          else if(in_is_down && !in_accumulate) context_valid[in_slot]<=0;
          state<=invalid_shape?ABORT_DRAIN:(!in_is_down && in_count==0?RESULT:START);
        end
        START: begin
          started<=started | (child_in_valid & child_in_ready) | ~active;
          received<=received | ~active;
          if(&(started | (child_in_valid & child_in_ready) | ~active)) state<=COLLECT;
        end
        COLLECT: begin
          received<=received | (child_out_valid & child_out_ready);
          for(int c=0;c<Clusters;c++)
            if(child_out_valid[c] && child_out_ready[c]) sums[c*1024+:1024]<=child_data[c];
          if(&(received | (child_out_valid & child_out_ready))) begin
            state<=RESULT;
            if(is_down) begin
              context_valid[slot]<=!last;
              context_tag[slot]<=tag;context_start[slot]<=output_start;context_count[slot]<=output_count;
            end
          end
        end
        ABORT_DRAIN: if(!offer && !busy) begin
          child_rst_n<=0;reset_second_cycle<=0;state<=RESET_CHILDREN;
        end
        RESET_CHILDREN: begin
          if(reset_second_cycle) state<=RESULT;
          else begin child_rst_n<=0;reset_second_cycle<=1;end
        end
        RESULT: if(out_ready) state<=IDLE;
        default: begin result_error<=1;sums<=0;context_valid<=0;state<=ABORT_DRAIN;end
      endcase
    end
  end
endmodule
