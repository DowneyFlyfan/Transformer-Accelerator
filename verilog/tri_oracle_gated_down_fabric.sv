`timescale 1ns/1ps
// One owner for paired nonlinear projection and sparse down work on the same
// twenty cores. Successful handoff retains every down slot; fatal packets
// capture their result before resetting both children and all retained slots.
module tri_oracle_gated_down_fabric (
    input logic clk,rst_n,in_valid,in_is_down,in_last,in_fallback,in_accumulate,out_ready,
    input logic [31:0] in_tag,
    input logic [2559:0] in_channels,
    input logic [1023:0] in_data,
    input logic [7:0] in_count,in_output_count,
    input logic [63:0] in_activation_base,in_weight_base,in_up_weight_base,
    input logic [9:0] in_features,
    input logic [16:0] in_dense_features,
    input logic [15:0] in_output_start,
    input logic [5:0] in_shift,in_gate_shift,in_up_shift,
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
  typedef enum logic [2:0] {IDLE,GATED,DOWN,FLUSH,RESULT} state_t;
  state_t state;
  logic controller_reset_n,flush_second_cycle;
  logic owner_idle;
  logic gated_ready,gated_valid,gated_last,gated_fallback,gated_error;
  logic [31:0] gated_tag;
  logic [7:0] gated_count;
  logic [2559:0] gated_channels;
  logic [5119:0] gated_data;
  logic projection_in_valid,projection_in_ready,projection_in_last,projection_in_fallback;
  logic [31:0] projection_in_tag;
  logic [2559:0] projection_in_channels;
  logic [7:0] projection_in_count;
  logic [63:0] projection_in_activation_base,projection_in_weight_base;
  logic [9:0] projection_in_features;
  logic projection_out_valid,projection_out_ready,projection_out_last,projection_out_fallback,projection_out_error;
  logic [31:0] projection_out_tag;
  logic [2559:0] projection_out_channels;
  logic [7:0] projection_out_count;
  logic [5119:0] projection_out_data;
  logic backend_in_valid,backend_ready,backend_valid,backend_out_ready,backend_is_down;
  logic backend_last,backend_fallback,backend_error;
  logic [31:0] backend_tag;
  logic [7:0] backend_count;
  logic [2559:0] backend_channels;
  logic [5119:0] backend_data;
  logic [15:0] backend_start;
  logic [3:0] backend_slot;

  always_comb begin
    // The gated executor holds an accepted command until its projection can
    // start. Keep idle readiness while only a valid gate command can bypass it.
    owner_idle=state==IDLE && controller_reset_n && gated_ready;
    in_ready=owner_idle && (backend_ready || (in_valid && !in_is_down));
    out_valid=state==RESULT;
  end

  always_comb begin
    backend_in_valid=state==GATED?projection_in_valid:(state==IDLE && in_valid && in_ready && in_is_down);
    backend_out_ready=state==GATED?projection_out_ready:state==DOWN;
    projection_in_ready=state==GATED && backend_ready;
    projection_out_valid=state==GATED && backend_valid;
    projection_out_last=backend_last;projection_out_fallback=backend_fallback;
    projection_out_error=backend_error || backend_is_down;
    projection_out_tag=backend_tag;projection_out_count=backend_count;
    projection_out_channels=backend_channels;projection_out_data=backend_data;
  end

  tri_oracle_fabric_gated_executor gated (
      .clk(clk),.rst_n(controller_reset_n),.in_valid(in_valid && owner_idle && !in_is_down),
      .in_ready(gated_ready),.in_last(in_last),.in_fallback(in_fallback),.in_tag(in_tag),
      .in_channels(in_channels),.in_count(in_count),.in_activation_base(in_activation_base),
      .in_weight_base(in_weight_base),.in_up_weight_base(in_up_weight_base),.in_features(in_features),
      .in_gate_shift(in_gate_shift),.in_up_shift(in_up_shift),.out_valid(gated_valid),.out_ready(state==GATED),
      .out_last(gated_last),.out_fallback(gated_fallback),.out_error(gated_error),.out_tag(gated_tag),
      .out_count(gated_count),.out_channels(gated_channels),.out_data(gated_data),
      .projection_in_valid(projection_in_valid),.projection_in_ready(projection_in_ready),
      .projection_in_last(projection_in_last),.projection_in_fallback(projection_in_fallback),
      .projection_in_tag(projection_in_tag),.projection_in_channels(projection_in_channels),
      .projection_in_count(projection_in_count),.projection_in_activation_base(projection_in_activation_base),
      .projection_in_weight_base(projection_in_weight_base),.projection_in_features(projection_in_features),
      .projection_out_valid(projection_out_valid),.projection_out_ready(projection_out_ready),
      .projection_out_last(projection_out_last),.projection_out_fallback(projection_out_fallback),
      .projection_out_error(projection_out_error),.projection_out_tag(projection_out_tag),
      .projection_out_channels(projection_out_channels),.projection_out_count(projection_out_count),
      .projection_out_data(projection_out_data)
  );

  tri_oracle_shared_fabric backend (
      .clk(clk),.rst_n(controller_reset_n),.in_valid(backend_in_valid),.in_ready(backend_ready),
      .in_is_down(state!=GATED),.in_last(state==GATED?projection_in_last:in_last),
      .in_fallback(state==GATED?projection_in_fallback:in_fallback),.in_accumulate(in_accumulate),
      .in_tag(state==GATED?projection_in_tag:in_tag),.in_channels(state==GATED?projection_in_channels:in_channels),
      .in_data(in_data),.in_count(state==GATED?projection_in_count:in_count),.in_output_count(in_output_count),
      .in_activation_base(state==GATED?projection_in_activation_base:in_activation_base),
      .in_weight_base(state==GATED?projection_in_weight_base:in_weight_base),
      .in_features(state==GATED?projection_in_features:in_features),.in_dense_features(in_dense_features),
      .in_output_start(in_output_start),.in_shift(in_shift),.in_slot(in_slot),
      .out_valid(backend_valid),.out_ready(backend_out_ready),.out_is_down(backend_is_down),
      .out_last(backend_last),.out_fallback(backend_fallback),.out_error(backend_error),
      .out_tag(backend_tag),.out_count(backend_count),.out_channels(backend_channels),.out_data(backend_data),
      .out_start(backend_start),.out_slot(backend_slot),.req_valid(req_valid),.req_ready(req_ready),
      .req_address(req_address),.req_length(req_length),.rsp_valid(rsp_valid),.rsp_last(rsp_last),
      .rsp_error(rsp_error),.rsp_ready(rsp_ready),.rsp_data(rsp_data)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      state<=IDLE;controller_reset_n<=0;flush_second_cycle<=0;
      out_is_down<=0;out_last<=0;out_fallback<=0;out_error<=0;out_tag<=0;out_count<=0;
      out_channels<=0;out_data<=0;out_start<=0;out_slot<=0;
    end else begin
      controller_reset_n<=1;
      case(state)
        IDLE: if(in_valid && in_ready) begin
          out_is_down<=in_is_down;state<=in_is_down?DOWN:GATED;
        end
        GATED: if(gated_valid) begin
          out_last<=gated_last;out_fallback<=gated_fallback;out_error<=gated_error;out_tag<=gated_tag;
          out_count<=gated_count;out_channels<=gated_channels;out_data<=gated_data;out_start<=0;out_slot<=0;
          if(gated_error) begin controller_reset_n<=0;flush_second_cycle<=0;state<=FLUSH;end
          else state<=RESULT;
        end
        DOWN: if(backend_valid) begin
          out_last<=backend_last || !backend_is_down;out_fallback<=0;
          out_error<=backend_error || !backend_is_down;out_tag<=backend_tag;
          out_count<=backend_is_down?backend_count:8'b0;out_channels<=0;
          out_data<=backend_is_down?backend_data:5120'b0;out_start<=backend_start;out_slot<=backend_slot;
          if(backend_error || !backend_is_down) begin controller_reset_n<=0;flush_second_cycle<=0;state<=FLUSH;end
          else state<=RESULT;
        end
        FLUSH: begin
          if(flush_second_cycle) state<=RESULT;
          else begin controller_reset_n<=0;flush_second_cycle<=1;end
        end
        RESULT: if(out_ready) state<=IDLE;
        default: begin
          controller_reset_n<=0;flush_second_cycle<=0;out_error<=1;out_last<=1;out_fallback<=0;
          out_count<=0;out_channels<=0;out_data<=0;state<=FLUSH;
        end
      endcase
    end
  end
endmodule
