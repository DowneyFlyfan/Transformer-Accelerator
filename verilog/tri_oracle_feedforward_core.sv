`timescale 1ns/1ps
// Prediction-guided gate/up/down projection over a configured output range.
// One shared core: slot0 is gate/up workspace; slots1..15 cache down sums.
// Up to480 output rows are kept locally; larger/model-wide scheduling is external.
// Every input group must be framed; normalization/sign fetch remain upstream.
// No outputs are released until all final down contributions succeed.
// Fixed-point formats, memory layout, framing and scheduling are local choices.
module tri_oracle_feedforward_core (
    input wire clk,rst_n,cfg_valid,
    output wire cfg_ready,
    input wire [31:0] cfg_tag,
    input wire [63:0] cfg_activation_base,cfg_weight_base,cfg_up_weight_base,
    input wire [5:0] cfg_gate_shift,cfg_up_shift,
    input wire [9:0] cfg_features,
    input wire [63:0] cfg_down_weight_base,
    input wire [16:0] cfg_dense_features,
    input wire [15:0] cfg_output_start,
    input wire [8:0] cfg_output_count,
    input wire [5:0] cfg_down_shift,
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
    localparam [2:0] IDLE=0,ACTIVE=1,BAD_CONFIG=2,DOWN_START=3,DOWN_WAIT=4,
        EMIT_READ=5,EMIT_WAIT=6,FINAL=7;
    reg [2:0] state;
    reg [31:0] tag;
    reg [63:0] activation_base,gate_base,up_base,down_base;
    reg [9:0] features;
    reg [16:0] dense_features;
    reg [15:0] output_start;
    reg [8:0] output_count;
    reg [5:0] gate_shift,up_shift,down_shift;
    reg first_strip,saved_group_last,input_closed,tensor_fault,tensor_fallback,have_partial;
    reg [9:0] strip_count;
    reg [3:0] tile_index;
    reg [5:0] saved_count;
    reg [511:0] saved_channels;
    reg [1023:0] saved_data,result_data;
    reg saved_last,packet_invalid;
    reg [511:0] result_channels;
    wire [10:0] next_strips=first_strip?11'd1:({1'b0,strip_count}+11'd1);
    wire frame_fault=next_strips>11'(features) || (in_last && next_strips!=11'(features));
    wire invalid_config=cfg_features==0 || cfg_features>10'd512 ||
        cfg_dense_features<17'd32 || cfg_dense_features>17'd65536 || cfg_dense_features[4:0]!=0 ||
        cfg_output_count==0 || cfg_output_count>9'd480 ||
        (17'(cfg_output_start)+17'(cfg_output_count)>17'd65536) ||
        cfg_activation_base[2:0]!=0 || cfg_weight_base[2:0]!=0 ||
        cfg_up_weight_base[2:0]!=0 || cfg_down_weight_base[2:0]!=0;
    wire [8:0] tile_offset={tile_index,5'd0};
    wire [8:0] remaining=output_count-tile_offset;
    wire [5:0] tile_count=remaining>9'd32 ? 6'd32 : remaining[5:0];
    wire [15:0] tile_start=output_start+16'(tile_offset);
    wire [3:0] tile_slot=tile_index+4'd1;
    wire last_tile=tile_offset+9'(tile_count)==output_count;
    wire gate_owns=state==ACTIVE;
    wire down_owns=state==DOWN_START || state==DOWN_WAIT;
    wire predictor_ready,packet_ready,packet_valid,packet_last,packet_fallback;
    wire [5:0] packet_count;
    wire [511:0] packet_channels;
    wire [255:0] unused_packet_lanes;
    wire core_load_error,core_cmd_ready,core_done_valid,core_result_valid;
    wire [3:0] core_done_output;
    wire [1023:0] core_result_data;
    wire g_in_ready;
    wire g_out_valid;
    wire g_out_last;
    wire g_out_fallback;
    wire g_out_error;
    wire [31:0] unused_g_out_tag;
    wire [5:0] g_out_count;
    wire [511:0] g_out_channels;
    wire [1023:0] g_out_data;
    wire g_req_valid;
    wire [63:0] g_req_address;
    wire [4:0] g_req_length;
    wire g_rsp_ready;
    wire g_core_load_valid;
    wire [1:0] g_core_load_kind;
    wire [9:0] g_core_load_address;
    wire [2047:0] g_core_load_data;
    wire [31:0] g_core_load_rows;
    wire g_core_cmd_valid;
    wire [4:0] g_core_cmd_weight;
    wire [4:0] g_core_cmd_mask;
    wire [9:0] g_core_cmd_activation;
    wire [3:0] g_core_cmd_output;
    wire g_core_cmd_accumulate;
    wire g_core_read_valid;
    wire [3:0] g_core_read_output;
    wire d_in_ready;
    wire d_out_valid;
    wire unused_d_out_last;
    wire d_out_error;
    wire [31:0] unused_d_out_tag;
    wire [5:0] unused_d_out_count;
    wire [15:0] unused_d_out_start;
    wire [3:0] unused_d_out_slot;
    wire [1023:0] unused_d_out_data;
    wire d_req_valid;
    wire [63:0] d_req_address;
    wire [4:0] d_req_length;
    wire d_rsp_ready;
    wire d_core_load_valid;
    wire [1:0] d_core_load_kind;
    wire [9:0] d_core_load_address;
    wire [2047:0] d_core_load_data;
    wire [31:0] d_core_load_rows;
    wire d_core_cmd_valid;
    wire [4:0] d_core_cmd_weight;
    wire [4:0] d_core_cmd_mask;
    wire [9:0] d_core_cmd_activation;
    wire [3:0] d_core_cmd_output;
    wire d_core_cmd_accumulate;
    wire d_core_read_valid;
    wire [3:0] d_core_read_output;
    assign cfg_ready=state==IDLE;
    assign in_ready=state==ACTIVE && !input_closed && predictor_ready;
    assign packet_ready=state==ACTIVE && g_in_ready;
    assign out_valid=state==BAD_CONFIG || state==FINAL;
    assign out_last=state==BAD_CONFIG || tensor_fault || last_tile;
    assign out_error=state==BAD_CONFIG || tensor_fault;
    assign out_fallback=tensor_fallback;
    assign out_tag=tag;
    assign out_count=out_error ? 6'd0 : tile_count;
    assign out_channels=out_error ? 512'd0 : result_channels;
    assign out_data=out_error ? 1024'd0 : result_data;
    assign req_valid=down_owns?d_req_valid:(gate_owns?g_req_valid:1'b0);
    assign req_address=down_owns?d_req_address:g_req_address;
    assign req_length=down_owns?d_req_length:g_req_length;
    assign rsp_ready=down_owns?d_rsp_ready:(gate_owns?g_rsp_ready:1'b0);
    integer i;
    always @* begin
        packet_invalid=0;result_channels=0;
        for(i=0;i<32;i=i+1) begin
            if(i<int'(packet_count) && {1'b0,packet_channels[i*16+:16]}>=dense_features) packet_invalid=1;
            if(i<int'(tile_count)) result_channels[i*16+:16]=tile_start+16'(i);
        end
    end
    tri_oracle_predicted_dispatch prediction (
        .clk(clk),.rst_n(rst_n),.in_valid(in_valid && state==ACTIVE && !input_closed),
        .in_last(in_last),.in_group_last(in_group_last),.in_frame_error(frame_fault),.in_group(in_group),
        .norm_activations(norm_activations),.gate_weight_signs(gate_weight_signs),.up_weight_signs(up_weight_signs),
        .in_ready(predictor_ready),.out_ready(packet_ready),.out_valid(packet_valid),.out_last(packet_last),
        .out_error(packet_fallback),.out_count(packet_count),.out_channels(packet_channels),.out_lane_enable(unused_packet_lanes)
    );
    tri_oracle_gated_executor g_engine (
        .clk(clk),
        .rst_n(rst_n),
        .in_valid(state==ACTIVE && packet_valid),
        .in_last(packet_last),
        .in_fallback(packet_fallback),
        .out_ready(state==ACTIVE),
        .in_tag(tag),
        .in_channels(packet_channels),
        .in_count((tensor_fault || packet_invalid)?6'd0:packet_count),
        .in_activation_base(activation_base),
        .in_weight_base(gate_base),
        .in_up_weight_base(up_base),
        .in_gate_shift(gate_shift),
        .in_up_shift(up_shift),
        .in_features(features),
        .in_span(features),
        .in_start(9'd0),
        .in_ready(g_in_ready),
        .out_valid(g_out_valid),
        .out_last(g_out_last),
        .out_fallback(g_out_fallback),
        .out_error(g_out_error),
        .out_tag(unused_g_out_tag),
        .out_count(g_out_count),
        .out_channels(g_out_channels),
        .out_data(g_out_data),
        .req_valid(g_req_valid),
        .req_ready(req_ready && gate_owns),
        .req_address(g_req_address),
        .req_length(g_req_length),
        .rsp_valid(rsp_valid && gate_owns),
        .rsp_last(rsp_last),
        .rsp_error(rsp_error),
        .rsp_ready(g_rsp_ready),
        .rsp_data(rsp_data),
        .core_load_valid(g_core_load_valid),
        .core_load_ready(gate_owns),
        .core_load_error(core_load_error && gate_owns),
        .core_load_kind(g_core_load_kind),
        .core_load_address(g_core_load_address),
        .core_load_data(g_core_load_data),
        .core_load_rows(g_core_load_rows),
        .core_cmd_valid(g_core_cmd_valid),
        .core_cmd_ready(core_cmd_ready && gate_owns),
        .core_cmd_weight(g_core_cmd_weight),
        .core_cmd_mask(g_core_cmd_mask),
        .core_cmd_activation(g_core_cmd_activation),
        .core_cmd_output(g_core_cmd_output),
        .core_cmd_accumulate(g_core_cmd_accumulate),
        .core_done_valid(core_done_valid && gate_owns),
        .core_done_output(core_done_output),
        .core_read_valid(g_core_read_valid),
        .core_read_output(g_core_read_output),
        .core_result_valid(core_result_valid && gate_owns),
        .core_result_data(core_result_data)
    );
    tri_oracle_down_executor d_engine (
        .clk(clk),
        .rst_n(rst_n),
        .in_valid(state==DOWN_START),
        .in_last(saved_last),
        .in_accumulate(have_partial),
        .out_ready(state==DOWN_WAIT),
        .in_tag(tag),
        .in_count(saved_count),
        .in_output_count(tile_count),
        .in_shift(down_shift),
        .in_channels(saved_channels),
        .in_data(saved_data),
        .in_weight_base(down_base),
        .in_dense_features(dense_features),
        .in_output_start(tile_start),
        .in_slot(tile_slot),
        .in_ready(d_in_ready),
        .out_valid(d_out_valid),
        .out_last(unused_d_out_last),
        .out_error(d_out_error),
        .out_tag(unused_d_out_tag),
        .out_count(unused_d_out_count),
        .out_start(unused_d_out_start),
        .out_slot(unused_d_out_slot),
        .out_data(unused_d_out_data),
        .req_valid(d_req_valid),
        .req_ready(req_ready && down_owns),
        .req_address(d_req_address),
        .req_length(d_req_length),
        .rsp_valid(rsp_valid && down_owns),
        .rsp_last(rsp_last),
        .rsp_error(rsp_error),
        .rsp_ready(d_rsp_ready),
        .rsp_data(rsp_data),
        .core_load_valid(d_core_load_valid),
        .core_load_ready(down_owns),
        .core_load_error(core_load_error && down_owns),
        .core_load_kind(d_core_load_kind),
        .core_load_address(d_core_load_address),
        .core_load_data(d_core_load_data),
        .core_load_rows(d_core_load_rows),
        .core_cmd_valid(d_core_cmd_valid),
        .core_cmd_ready(core_cmd_ready && down_owns),
        .core_cmd_weight(d_core_cmd_weight),
        .core_cmd_mask(d_core_cmd_mask),
        .core_cmd_activation(d_core_cmd_activation),
        .core_cmd_output(d_core_cmd_output),
        .core_cmd_accumulate(d_core_cmd_accumulate),
        .core_done_valid(core_done_valid && down_owns),
        .core_done_output(core_done_output),
        .core_read_valid(d_core_read_valid),
        .core_read_output(d_core_read_output),
        .core_result_valid(core_result_valid && down_owns),
        .core_result_data(core_result_data)
    );
    wire core_load_valid=down_owns?d_core_load_valid:(gate_owns?g_core_load_valid:1'b0);
    wire [1:0] core_load_kind=down_owns?d_core_load_kind:g_core_load_kind;
    wire [9:0] core_load_address=down_owns?d_core_load_address:g_core_load_address;
    wire [2047:0] core_load_data=down_owns?d_core_load_data:g_core_load_data;
    wire [31:0] core_load_rows=down_owns?d_core_load_rows:g_core_load_rows;
    wire core_cmd_valid=down_owns?d_core_cmd_valid:(gate_owns?g_core_cmd_valid:1'b0);
    wire [4:0] core_cmd_weight=down_owns?d_core_cmd_weight:g_core_cmd_weight;
    wire [4:0] core_cmd_mask=down_owns?d_core_cmd_mask:g_core_cmd_mask;
    wire [9:0] core_cmd_activation=down_owns?d_core_cmd_activation:g_core_cmd_activation;
    wire [3:0] core_cmd_output=down_owns?d_core_cmd_output:g_core_cmd_output;
    wire core_cmd_accumulate=down_owns?d_core_cmd_accumulate:g_core_cmd_accumulate;
    wire core_read_valid=state==EMIT_READ || (down_owns?d_core_read_valid:(gate_owns?g_core_read_valid:1'b0));
    wire [3:0] core_read_output=state==EMIT_READ?tile_slot:(down_owns?d_core_read_output:g_core_read_output);
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
            state<=IDLE;tag<=0;activation_base<=0;gate_base<=0;up_base<=0;down_base<=0;features<=0;
            dense_features<=0;output_start<=0;output_count<=0;gate_shift<=0;up_shift<=0;down_shift<=0;
            first_strip<=1;saved_group_last<=0;input_closed<=0;tensor_fault<=0;tensor_fallback<=0;
            have_partial<=0;strip_count<=0;tile_index<=0;saved_count<=0;saved_channels<=0;
            saved_data<=0;result_data<=0;saved_last<=0;
        end else begin
            case(state)
                IDLE: if(cfg_valid) begin
                    tag<=cfg_tag;activation_base<=cfg_activation_base;gate_base<=cfg_weight_base;
                    up_base<=cfg_up_weight_base;down_base<=cfg_down_weight_base;features<=cfg_features;
                    dense_features<=cfg_dense_features;output_start<=cfg_output_start;output_count<=cfg_output_count;
                    gate_shift<=cfg_gate_shift;up_shift<=cfg_up_shift;down_shift<=cfg_down_shift;
                    first_strip<=1;saved_group_last<=0;input_closed<=0;tensor_fault<=0;tensor_fallback<=0;
                    have_partial<=0;strip_count<=0;tile_index<=0;result_data<=0;
                    state<=invalid_config?BAD_CONFIG:ACTIVE;
                end
                ACTIVE: begin
                    if(in_valid && in_ready) begin
                        if(first_strip) saved_group_last<=in_group_last;
                        if(in_last && (first_strip?in_group_last:saved_group_last)) input_closed<=1;
                        first_strip<=in_last;
                        strip_count<=in_last ? 10'd0 : (next_strips>11'd512 ? 10'd512 : next_strips[9:0]);
                    end
                    if(packet_valid && packet_ready && packet_invalid) tensor_fault<=1;
                    if(g_out_valid) begin
                        tensor_fallback<=tensor_fallback || g_out_fallback;
                        if(tensor_fault || g_out_error) begin
                            tensor_fault<=1;result_data<=0;
                            if(g_out_last) state<=FINAL;
                        end else begin
                            saved_count<=g_out_count;saved_channels<=g_out_channels;saved_data<=g_out_data;
                            saved_last<=g_out_last;tile_index<=0;state<=DOWN_START;
                        end
                    end
                end
                DOWN_START: if(d_in_ready) state<=DOWN_WAIT;
                DOWN_WAIT: if(d_out_valid) begin
                    if(d_out_error) begin
                        tensor_fault<=1;result_data<=0;
                        state<=saved_last?FINAL:ACTIVE;
                    end else if(last_tile) begin
                        tile_index<=0;
                        if(saved_last) state<=EMIT_READ;
                        else begin have_partial<=1;state<=ACTIVE;end
                    end else begin tile_index<=tile_index+4'd1;state<=DOWN_START;end
                end
                EMIT_READ: state<=EMIT_WAIT;
                EMIT_WAIT: if(core_result_valid) begin result_data<=core_result_data;state<=FINAL;end
                FINAL: if(out_ready) begin
                    if(out_last) state<=IDLE;
                    else begin tile_index<=tile_index+4'd1;state<=EMIT_READ;end
                end
                BAD_CONFIG: if(out_ready) state<=IDLE;
                default: begin tensor_fault<=1;result_data<=0;state<=FINAL;end
            endcase
        end
    end
endmodule
