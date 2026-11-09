`timescale 1ns/1ps
// Executes one activation vector against up to 32 packed output rows. Local
// protocol/tiling choices: 16 eight-feature strips per transfer tile, alternating
// weight halves, output slot/mask zero, and exclusive ownership of a core.
// A partial feature range supports splitting a dot product across cores.
// The normalized prediction stream is upstream; this unit moves INT8 operands.
module tri_oracle_tile_executor (
    input wire clk,rst_n,in_valid,in_last,in_fallback,out_ready,
    input wire [31:0] in_tag,
    input wire [511:0] in_channels,
    input wire [5:0] in_count,
    input wire [63:0] in_activation_base,in_weight_base,
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
    localparam [3:0] IDLE=0,MASK=1,A_START=2,A_WAIT=3,W_START=4,W_WAIT=5,
        ISSUE=6,DRAIN_CORE=7,READ_OUT=8,WAIT_READ=9,RESULT=10;
    reg [3:0] state;
    reg [31:0] tag;
    reg [511:0] channels;
    reg [5:0] count;
    reg last,fallback,bank,fault,result_error;
    reg [63:0] activation_base,weight_base;
    reg [9:0] features,range_start,range_end,tile_start;
    reg [3:0] issue_index;
    reg [4:0] completed;
    reg [1023:0] result_data;
    reg [255:0] lane_mask;
    wire [9:0] remaining=range_end-tile_start;
    wire [4:0] tile_length=(remaining>10'd16)?5'd16:remaining[4:0];
    wire [9:0] next_start=tile_start+10'(tile_length);
    wire invalid_shape=in_count>6'd32 || in_features==0 || in_features>10'd512 ||
        in_span==0 || (11'(in_start)+11'(in_span)>11'(in_features)) ||
        in_activation_base[2:0]!=0 || in_weight_base[2:0]!=0;
    wire dma_in_ready,dma_done,dma_error,dma_load_valid;
    wire [4:0] dma_load_address;
    wire [31:0] dma_load_rows;
    wire [2047:0] dma_load_data;
    wire activation_transfer=state==A_WAIT;
    wire weight_transfer=state==W_WAIT;
    integer row;
    tri_oracle_sparse_weight_dma transfer (
        .clk(clk),.rst_n(rst_n),
        .in_valid((state==A_START || state==W_START) && !fault && !core_load_error),
        .in_ready(dma_in_ready),.in_bank(bank),
        .in_channels(state==A_START?512'd0:channels),
        .in_count(state==A_START?6'd1:count),
        .in_base(state==A_START?activation_base:weight_base),
        .in_features(features),.in_start(tile_start[8:0]),.in_length(tile_length),
        .done_ready(activation_transfer || weight_transfer),.done_valid(dma_done),.done_error(dma_error),
        .req_valid(req_valid),.req_ready(req_ready),.req_address(req_address),.req_length(req_length),
        .rsp_valid(rsp_valid),.rsp_last(rsp_last),.rsp_error(rsp_error),.rsp_ready(rsp_ready),.rsp_data(rsp_data),
        .load_valid(dma_load_valid),.load_ready(core_load_ready),.load_address(dma_load_address),
        .load_row_enable(dma_load_rows),.load_data(dma_load_data)
    );
    always @* begin
        lane_mask=0;
        for(row=0;row<32;row=row+1)
            if(row<int'(count)) lane_mask[row*8+:8]=8'hff;
    end
    assign in_ready=state==IDLE;
    assign out_valid=state==RESULT;
    assign out_last=last;
    assign out_fallback=fallback;
    assign out_error=result_error;
    assign out_tag=tag;
    assign out_count=result_error?6'd0:count;
    assign out_channels=channels;
    assign out_data=result_data;
    assign core_load_valid=(state==MASK) || ((activation_transfer || weight_transfer) && dma_load_valid);
    assign core_load_kind=(state==MASK)?2'd2:(activation_transfer?2'd1:2'd0);
    assign core_load_address=(state==MASK)?10'd0:
        (activation_transfer?tile_start+10'(dma_load_address[3:0]):{5'd0,dma_load_address});
    assign core_load_data=(state==MASK)?{{1792{1'b0}},lane_mask}:dma_load_data;
    assign core_load_rows=(state==MASK)?32'd0:dma_load_rows;
    assign core_cmd_valid=state==ISSUE;
    assign core_cmd_weight={bank,issue_index};
    assign core_cmd_activation=tile_start+10'(issue_index);
    assign core_cmd_mask=0;
    assign core_cmd_output=0;
    assign core_cmd_accumulate=(tile_start!=range_start) || issue_index!=0;
    assign core_read_valid=state==READ_OUT;
    assign core_read_output=0;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;tag<=0;channels<=0;count<=0;last<=0;fallback<=0;bank<=0;
            fault<=0;result_error<=0;activation_base<=0;weight_base<=0;features<=0;
            range_start<=0;range_end<=0;tile_start<=0;issue_index<=0;completed<=0;result_data<=0;
        end else begin
            if(state!=IDLE && state!=RESULT) begin
                if(core_load_error || (core_done_valid &&
                    (core_done_output!=0 || !(state==ISSUE || state==DRAIN_CORE)))) fault<=1;
            end
            if(core_done_valid && (state==ISSUE || state==DRAIN_CORE)) completed<=completed+1'b1;
            case(state)
                IDLE: if(in_valid) begin
                    tag<=in_tag;channels<=in_channels;count<=in_count;last<=in_last;fallback<=in_fallback;
                    activation_base<=in_activation_base;weight_base<=in_weight_base;features<=in_features;
                    range_start<=10'(in_start);range_end<=10'(in_start)+in_span;tile_start<=10'(in_start);
                    bank<=0;fault<=0;result_error<=0;result_data<=0;issue_index<=0;completed<=0;
                    if(in_count==0) state<=RESULT;
                    else if(invalid_shape) begin result_error<=1;state<=RESULT;end
                    else state<=MASK;
                end
                MASK: if(core_load_ready) state<=A_START;
                A_START,W_START: begin
                    if(fault || core_load_error) begin result_error<=1;state<=RESULT;end
                    else if(dma_in_ready) state<=(state==A_START)?A_WAIT:W_WAIT;
                end
                A_WAIT,W_WAIT: if(dma_done) begin
                    if(dma_error || fault || core_load_error) begin result_error<=1;state<=RESULT;end
                    else if(state==A_WAIT) state<=W_START;
                    else begin issue_index<=0;completed<=0;state<=ISSUE;end
                end
                ISSUE: if(core_cmd_ready) begin
                    if(({1'b0,issue_index}+5'd1)==tile_length) state<=DRAIN_CORE;
                    else issue_index<=issue_index+1'b1;
                end
                DRAIN_CORE: if(core_done_valid && (completed+5'd1)==tile_length) begin
                    if(fault || core_load_error || core_done_output!=0) begin result_error<=1;state<=RESULT;end
                    else if(next_start==range_end) state<=READ_OUT;
                    else begin tile_start<=next_start;bank<=!bank;state<=A_START;end
                end
                READ_OUT: state<=WAIT_READ;
                WAIT_READ: if(core_result_valid) begin
                    if(fault || core_load_error) result_error<=1;
                    else result_data<=core_result_data;
                    state<=RESULT;
                end
                RESULT: if(out_ready) state<=IDLE;
                default: begin result_error<=1;result_data<=0;state<=RESULT;end
            endcase
        end
    end
endmodule
