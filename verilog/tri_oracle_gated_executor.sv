`timescale 1ns/1ps
// Complete gate/up dot products on one core, followed by SiLU(gate)*up.
// The external activation/weight format is the tile executor's signed INT8.
// Shift raw32-bit dot sums independently into signed16-bit Q8 code values,
// with ties away from zero and saturation; output Q8 is sign-extended to32 bits.
// Full dot products are required: partial feature ranges are rejected because
// nonlinear activation must follow the sum of all feature partitions.
// The down projection, model calibration and system-bus adapter are separate.
module tri_oracle_gated_executor (
    input wire clk,rst_n,in_valid,in_last,in_fallback,out_ready,
    input wire [31:0] in_tag,
    input wire [511:0] in_channels,
    input wire [5:0] in_count,
    input wire [63:0] in_activation_base,in_weight_base,in_up_weight_base,
    input wire [5:0] in_gate_shift,in_up_shift,
    input wire [9:0] in_features,in_span,
    input wire [8:0] in_start,
    output wire in_ready,out_valid,out_last,out_fallback,out_error,
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
    input wire [63:0] rsp_data,
    output wire core_load_valid,
    input wire core_load_ready,core_load_error,
    output wire [1:0] core_load_kind,
    output wire [9:0] core_load_address,
    output wire [2047:0] core_load_data,
    output wire [31:0] core_load_rows,
    output wire core_cmd_valid,
    input wire core_cmd_ready,
    output wire [4:0] core_cmd_weight,core_cmd_mask,
    output wire [9:0] core_cmd_activation,
    output wire [3:0] core_cmd_output,
    output wire core_cmd_accumulate,
    input wire core_done_valid,
    input wire [3:0] core_done_output,
    output wire core_read_valid,
    output wire [3:0] core_read_output,
    input wire core_result_valid,
    input wire [1023:0] core_result_data
);
    localparam [3:0] IDLE=0,GATE_START=1,GATE_WAIT=2,UP_START=3,UP_WAIT=4,
        ACTIVATE=5,DRAIN=6,RESULT=7;
    reg [3:0] state;
    reg [31:0] tag;
    reg [511:0] channels;
    reg [5:0] count,gate_shift,up_shift,issue_index,completed;
    reg last,fallback,result_error;
    reg [63:0] activation_base,gate_base,up_base;
    reg [9:0] features,span;
    reg [8:0] start;
    reg [1023:0] gate_values,up_values,result_data;
    wire engine_ready,engine_valid,engine_error;
    wire [1023:0] engine_data;
    wire unused_engine_last,unused_engine_fallback;
    wire [31:0] unused_engine_tag;
    wire [5:0] unused_engine_count;
    wire [511:0] unused_engine_channels;
    wire activation_ready,activation_valid;
    wire signed [15:0] activation_data;
    wire [15:0] unused_activation_tag;
    assign in_ready=state==IDLE;
    assign out_valid=state==RESULT;
    assign out_last=last;
    assign out_fallback=fallback;
    assign out_error=result_error;
    assign out_tag=tag;
    assign out_count=result_error?6'd0:count;
    assign out_channels=channels;
    assign out_data=result_data;
    function automatic signed [15:0] requantize(input signed [31:0] value,input [5:0] shift);
        reg signed [33:0] extended,rounded;
        begin
            extended={{2{value[31]}},value};
            if(shift>6'd32) rounded=0;
            else if(shift==0) rounded=extended;
            else if(extended<0) rounded=-((-extended+(34'sd1<<(shift-6'd1)))>>>shift);
            else rounded=(extended+(34'sd1<<(shift-6'd1)))>>>shift;
            if(rounded>34'sd32767) requantize=16'sh7fff;
            else if(rounded < -34'sd32768) requantize=16'sh8000;
            else requantize=rounded[15:0];
        end
    endfunction
    tri_oracle_silu_gate activation_unit (
        .clk(clk),.rst_n(rst_n),.in_valid(state==ACTIVATE),.in_ready(activation_ready),
        .in_gate(requantize($signed(gate_values[issue_index[4:0]*32+:32]),gate_shift)),
        .in_up(requantize($signed(up_values[issue_index[4:0]*32+:32]),up_shift)),
        .in_tag({10'd0,issue_index}),.out_valid(activation_valid),
        .out_ready(state==ACTIVATE || state==DRAIN),.out_data(activation_data),.out_tag(unused_activation_tag)
    );
    tri_oracle_tile_executor engine (
        .clk(clk),.rst_n(rst_n),.in_valid(state==GATE_START || state==UP_START),.in_ready(engine_ready),
        .in_last(last),.in_fallback(fallback),.in_tag(tag),.in_channels(channels),.in_count(count),
        .in_activation_base(activation_base),.in_weight_base(state==GATE_START?gate_base:up_base),
        .in_features(features),.in_start(start),.in_span(span),
        .out_valid(engine_valid),.out_ready(state==GATE_WAIT || state==UP_WAIT),.out_error(engine_error),
        .out_last(unused_engine_last),.out_fallback(unused_engine_fallback),.out_tag(unused_engine_tag),
        .out_count(unused_engine_count),.out_channels(unused_engine_channels),.out_data(engine_data),
        .req_valid(req_valid),.req_ready(req_ready),.req_address(req_address),.req_length(req_length),
        .rsp_valid(rsp_valid),.rsp_last(rsp_last),.rsp_error(rsp_error),.rsp_ready(rsp_ready),.rsp_data(rsp_data),
        .core_load_valid(core_load_valid),
        .core_load_ready(core_load_ready),
        .core_load_error(core_load_error),
        .core_load_kind(core_load_kind),
        .core_load_address(core_load_address),
        .core_load_data(core_load_data),
        .core_load_rows(core_load_rows),
        .core_cmd_valid(core_cmd_valid),
        .core_cmd_ready(core_cmd_ready),
        .core_cmd_weight(core_cmd_weight),
        .core_cmd_mask(core_cmd_mask),
        .core_cmd_activation(core_cmd_activation),
        .core_cmd_output(core_cmd_output),
        .core_cmd_accumulate(core_cmd_accumulate),
        .core_done_valid(core_done_valid),
        .core_done_output(core_done_output),
        .core_read_valid(core_read_valid),
        .core_read_output(core_read_output),
        .core_result_valid(core_result_valid),
        .core_result_data(core_result_data)
    );
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;tag<=0;channels<=0;count<=0;last<=0;fallback<=0;result_error<=0;
            activation_base<=0;gate_base<=0;up_base<=0;features<=0;span<=0;start<=0;
            gate_shift<=0;up_shift<=0;issue_index<=0;completed<=0;
            gate_values<=0;up_values<=0;result_data<=0;
        end else begin
            case(state)
                IDLE: if(in_valid) begin
                    tag<=in_tag;channels<=in_channels;count<=in_count;last<=in_last;fallback<=in_fallback;
                    activation_base<=in_activation_base;gate_base<=in_weight_base;up_base<=in_up_weight_base;
                    features<=in_features;span<=in_span;start<=in_start;
                    gate_shift<=in_gate_shift;up_shift<=in_up_shift;issue_index<=0;completed<=0;
                    result_error<=0;result_data<=0;
                    if(in_count==0) state<=RESULT;
                    else if(in_start!=0 || in_span!=in_features || in_up_weight_base[2:0]!=0) begin
                        result_error<=1;state<=RESULT;
                    end else state<=GATE_START;
                end
                GATE_START: if(engine_ready) state<=GATE_WAIT;
                GATE_WAIT: if(engine_valid) begin
                    if(engine_error) begin result_error<=1;state<=RESULT;end
                    else begin gate_values<=engine_data;state<=UP_START;end
                end
                UP_START: if(engine_ready) state<=UP_WAIT;
                UP_WAIT: if(engine_valid) begin
                    if(engine_error) begin result_error<=1;state<=RESULT;end
                    else begin up_values<=engine_data;state<=ACTIVATE;end
                end
                ACTIVATE: if(activation_ready) begin
                    issue_index<=issue_index+6'd1;
                    if(issue_index+6'd1==count) state<=DRAIN;
                end
                DRAIN: begin end
                RESULT: if(out_ready) state<=IDLE;
                default: begin result_error<=1;result_data<=0;state<=RESULT;end
            endcase
            if((state==ACTIVATE || state==DRAIN) && activation_valid) begin
                result_data[unused_activation_tag[4:0]*32+:32]<={{16{activation_data[15]}},activation_data};
                completed<=completed+6'd1;
                if(completed+6'd1==count) state<=RESULT;
            end
        end
    end
endmodule
