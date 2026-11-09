`timescale 1ns/1ps
// Prediction-guided execution. Default GATED=0 runs one weight matrix.
// GATED=1 runs gate/up projections followed by fixed-point SiLU and product.
// Down projection, normalized activations and weight-sign fetch are upstream
// or downstream responsibilities; this is not a complete feed-forward layer.
// Configuration is held through terminal-result acceptance. Prediction frames
// must contain cfg_features strips; malformed frames retain all rows.
// Transport faults invalidate the tensor and drain later descriptors without
// further transfers. Reset assumes the external memory protocol resets too.
module tri_oracle_predicted_core #(parameter integer GATED=0) (
    input wire clk,rst_n,cfg_valid,
    output wire cfg_ready,
    input wire [31:0] cfg_tag,
    input wire [63:0] cfg_activation_base,cfg_weight_base,cfg_up_weight_base,
    input wire [5:0] cfg_gate_shift,cfg_up_shift,
    input wire [9:0] cfg_features,cfg_span,
    input wire [8:0] cfg_start,
    input wire in_valid,in_last,in_group_last,
    input wire [10:0] in_group,
    input wire [127:0] norm_activations,
    input wire [255:0] gate_weight_signs,up_weight_signs,
    output wire in_ready,out_valid,out_last,out_fallback,out_error,
    input wire out_ready,
    output wire [31:0] out_tag,
    output wire [5:0] out_count,
    output wire [511:0] out_channels,
    output wire [1023:0] out_data,
    output wire req_valid,
    input wire req_ready,
    output wire [63:0] req_address,
    output wire [4:0] req_length,
    input wire rsp_valid,rsp_last,rsp_error,
    output wire rsp_ready,
    input wire [63:0] rsp_data
);
    localparam [1:0] IDLE=0,ACTIVE=1,BAD_CONFIG=2;
    reg [1:0] state;
    reg [31:0] tag;
    reg [63:0] activation_base,weight_base,unused_up_base;
    reg [5:0] unused_gate_shift,unused_up_shift;
    reg [9:0] features,span;
    reg [8:0] start;
    reg first_strip,saved_group_last,input_closed,tensor_fault;
    reg [9:0] strip_count;
    wire [10:0] next_strips=first_strip?11'd1:({1'b0,strip_count}+11'd1);
    wire frame_fault=next_strips>11'(features) || (in_last && next_strips!=11'(features));
    wire invalid_config=cfg_features==0 || cfg_features>10'd512 || cfg_span==0 ||
        (11'(cfg_start)+11'(cfg_span)>11'(cfg_features)) ||
        cfg_activation_base[2:0]!=0 || cfg_weight_base[2:0]!=0 ||
        (GATED!=0 && (cfg_up_weight_base[2:0]!=0 || cfg_start!=0 || cfg_span!=cfg_features));
    wire predictor_ready,packet_valid,packet_ready,packet_last,packet_fallback;
    wire [5:0] packet_count;
    wire [511:0] packet_channels;
    wire [255:0] unused_packet_lanes;
    wire executor_ready,executor_valid,executor_last,executor_fallback,executor_error;
    wire [31:0] unused_executor_tag;
    wire [5:0] executor_count;
    wire [511:0] executor_channels;
    wire [1023:0] executor_data;
    wire core_load_valid,core_load_error,core_cmd_valid,core_cmd_ready,core_cmd_accumulate;
    wire core_read_valid,core_done_valid,core_result_valid;
    wire [1:0] core_load_kind;
    wire [9:0] core_load_address,core_cmd_activation;
    wire [2047:0] core_load_data;
    wire [31:0] core_load_rows;
    wire [4:0] core_cmd_weight,core_cmd_mask;
    wire [3:0] core_cmd_output,core_read_output,core_done_output;
    wire [1023:0] core_result_data;
    assign cfg_ready=state==IDLE;
    assign in_ready=state==ACTIVE && !input_closed && predictor_ready;
    assign packet_ready=state==ACTIVE && executor_ready;
    assign out_valid=state==BAD_CONFIG || (state==ACTIVE && executor_valid);
    assign out_last=state==BAD_CONFIG || executor_last;
    assign out_fallback=state==BAD_CONFIG?1'b0:executor_fallback;
    assign out_error=state==BAD_CONFIG || (state==ACTIVE && (executor_error || tensor_fault));
    assign out_tag=tag;
    assign out_count=out_error?6'd0:executor_count;
    assign out_channels=state==BAD_CONFIG?512'd0:executor_channels;
    assign out_data=out_error?1024'd0:executor_data;
    tri_oracle_predicted_dispatch prediction (
        .clk(clk),.rst_n(rst_n),.in_valid(in_valid && state==ACTIVE && !input_closed),
        .in_last(in_last),.in_group_last(in_group_last),.in_frame_error(frame_fault),
        .in_group(in_group),.norm_activations(norm_activations),
        .gate_weight_signs(gate_weight_signs),.up_weight_signs(up_weight_signs),
        .in_ready(predictor_ready),.out_ready(packet_ready),.out_valid(packet_valid),
        .out_last(packet_last),.out_error(packet_fallback),.out_count(packet_count),
        .out_channels(packet_channels),.out_lane_enable(unused_packet_lanes)
    );
    generate
        if(GATED==0) begin: linear_path
    tri_oracle_tile_executor executor (
        .clk(clk),.rst_n(rst_n),.in_valid(state==ACTIVE && packet_valid),.in_ready(executor_ready),
        .in_last(packet_last),.in_fallback(packet_fallback),.in_tag(tag),
        .in_channels(packet_channels),.in_count(tensor_fault?6'd0:packet_count),
        .in_activation_base(activation_base),.in_weight_base(weight_base),
        .in_features(features),.in_start(start),.in_span(span),
        .out_valid(executor_valid),.out_ready(state==ACTIVE && out_ready),
        .out_last(executor_last),.out_fallback(executor_fallback),.out_error(executor_error),
        .out_tag(unused_executor_tag),.out_count(executor_count),
        .out_channels(executor_channels),.out_data(executor_data),
        .req_valid(req_valid),.req_ready(req_ready),.req_address(req_address),.req_length(req_length),
        .rsp_valid(rsp_valid),.rsp_last(rsp_last),.rsp_error(rsp_error),.rsp_ready(rsp_ready),.rsp_data(rsp_data),
        .core_load_valid(core_load_valid),.core_load_ready(1'b1),.core_load_error(core_load_error),
        .core_load_kind(core_load_kind),.core_load_address(core_load_address),
        .core_load_data(core_load_data),.core_load_rows(core_load_rows),
        .core_cmd_valid(core_cmd_valid),.core_cmd_ready(core_cmd_ready),
        .core_cmd_weight(core_cmd_weight),.core_cmd_mask(core_cmd_mask),
        .core_cmd_activation(core_cmd_activation),.core_cmd_output(core_cmd_output),
        .core_cmd_accumulate(core_cmd_accumulate),.core_done_valid(core_done_valid),
        .core_done_output(core_done_output),.core_read_valid(core_read_valid),
        .core_read_output(core_read_output),.core_result_valid(core_result_valid),.core_result_data(core_result_data)
    );
        end else begin: gated_path
    tri_oracle_gated_executor executor (
        .clk(clk),.rst_n(rst_n),.in_valid(state==ACTIVE && packet_valid),.in_ready(executor_ready),
        .in_last(packet_last),.in_fallback(packet_fallback),.in_tag(tag),
        .in_channels(packet_channels),.in_count(tensor_fault?6'd0:packet_count),
        .in_activation_base(activation_base),.in_weight_base(weight_base),
        .in_up_weight_base(unused_up_base),.in_gate_shift(unused_gate_shift),.in_up_shift(unused_up_shift),
        .in_features(features),.in_start(start),.in_span(span),
        .out_valid(executor_valid),.out_ready(state==ACTIVE && out_ready),
        .out_last(executor_last),.out_fallback(executor_fallback),.out_error(executor_error),
        .out_tag(unused_executor_tag),.out_count(executor_count),
        .out_channels(executor_channels),.out_data(executor_data),
        .req_valid(req_valid),.req_ready(req_ready),.req_address(req_address),.req_length(req_length),
        .rsp_valid(rsp_valid),.rsp_last(rsp_last),.rsp_error(rsp_error),.rsp_ready(rsp_ready),.rsp_data(rsp_data),
        .core_load_valid(core_load_valid),.core_load_ready(1'b1),.core_load_error(core_load_error),
        .core_load_kind(core_load_kind),.core_load_address(core_load_address),
        .core_load_data(core_load_data),.core_load_rows(core_load_rows),
        .core_cmd_valid(core_cmd_valid),.core_cmd_ready(core_cmd_ready),
        .core_cmd_weight(core_cmd_weight),.core_cmd_mask(core_cmd_mask),
        .core_cmd_activation(core_cmd_activation),.core_cmd_output(core_cmd_output),
        .core_cmd_accumulate(core_cmd_accumulate),.core_done_valid(core_done_valid),
        .core_done_output(core_done_output),.core_read_valid(core_read_valid),
        .core_read_output(core_read_output),.core_result_valid(core_result_valid),.core_result_data(core_result_data)
    );
        end
    endgenerate
    tri_oracle_memory_compute core (
        .clk(clk),.rst_n(rst_n),.load_valid(core_load_valid),.load_kind(core_load_kind),
        .load_addr(core_load_address),.load_data(core_load_data),.load_row_enable(core_load_rows),
        .load_error(core_load_error),.cmd_valid(core_cmd_valid),.cmd_ready(core_cmd_ready),
        .cmd_weight(core_cmd_weight),.cmd_activation(core_cmd_activation),.cmd_mask(core_cmd_mask),
        .cmd_output(core_cmd_output),.cmd_accumulate(core_cmd_accumulate),
        .done_valid(core_done_valid),.done_output(core_done_output),
        .read_valid(core_read_valid),.read_output(core_read_output),
        .result_valid(core_result_valid),.result_data(core_result_data)
    );
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;tag<=0;activation_base<=0;weight_base<=0;unused_up_base<=0;
            unused_gate_shift<=0;unused_up_shift<=0;features<=0;span<=0;start<=0;
            first_strip<=1;saved_group_last<=0;input_closed<=0;tensor_fault<=0;strip_count<=0;
        end else begin
            case(state)
                IDLE: if(cfg_valid) begin
                    tag<=cfg_tag;activation_base<=cfg_activation_base;weight_base<=cfg_weight_base;
                    unused_up_base<=cfg_up_weight_base;unused_gate_shift<=cfg_gate_shift;unused_up_shift<=cfg_up_shift;
                    features<=cfg_features;span<=cfg_span;start<=cfg_start;
                    first_strip<=1;saved_group_last<=0;input_closed<=0;tensor_fault<=0;strip_count<=0;
                    state<=invalid_config?BAD_CONFIG:ACTIVE;
                end
                ACTIVE: begin
                    if(in_valid && in_ready) begin
                        if(first_strip) saved_group_last<=in_group_last;
                        if(in_last && (first_strip?in_group_last:saved_group_last)) input_closed<=1;
                        first_strip<=in_last;
                        strip_count<=in_last ? 10'd0 : (next_strips>11'd512 ? 10'd512 : next_strips[9:0]);
                    end
                    // The failing packet is already zeroed by the executor.
                    // Preserve its failure through the tensor's final packet;
                    // subsequent descriptors drain without operand transfers.
                    if(executor_valid && executor_error) tensor_fault<=1;
                    if(out_valid && out_ready && out_last) state<=IDLE;
                end
                BAD_CONFIG: if(out_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
