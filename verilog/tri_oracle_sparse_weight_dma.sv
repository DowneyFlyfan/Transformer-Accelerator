`timescale 1ns/1ps
// Local sparse weight direct memory access (DMA) interface. Each selected original
// channel receives one contiguous 64-bit read burst. A beat holds eight signed 8-bit
// weights and writes its packed processing-element row directly into one
// 16-word half of the core's bank using per-row write enables.
// Request length is the actual beat count, from 1 to 16. One read burst
// is outstanding. An adapter to the system memory bus is still required.
// Errors suppress the bad write and drain the accepted burst through last;
// the caller must wait for successful completion before computing this tile.
module tri_oracle_sparse_weight_dma (
    input wire clk,rst_n,in_valid,in_bank,done_ready,
    input wire [511:0] in_channels,
    input wire [5:0] in_count,
    input wire [63:0] in_base,
    input wire [9:0] in_features,
    input wire [8:0] in_start,
    input wire [4:0] in_length,
    output wire in_ready,done_valid,
    output reg done_error,
    output wire req_valid,
    input wire req_ready,
    output reg [63:0] req_address,
    output wire [4:0] req_length,
    input wire rsp_valid,rsp_last,rsp_error,
    output wire rsp_ready,
    input wire [63:0] rsp_data,
    output wire load_valid,
    input wire load_ready,
    output wire [4:0] load_address,
    output wire [31:0] load_row_enable,
    output wire [2047:0] load_data
);
    localparam [2:0] IDLE=0,ADDRESS=1,REQUEST=2,READ=3,DRAIN=4,FINISHED=5;
    reg [2:0] state;
    reg [511:0] channels;
    reg [5:0] row_count;
    reg [4:0] row_index,beat_index,length;
    reg bank;
    reg [63:0] base;
    reg [9:0] features;
    reg [8:0] start;
    wire [15:0] original_channel=channels[row_index*16+:16];
    wire [64:0] strip_offset=65'(original_channel)*65'(features)+65'(start);
    wire [64:0] calculated_address={1'b0,base}+(strip_offset<<3);
    wire burst_overflow=(calculated_address+(65'(length)<<3)-65'd1)>65'h0ffffffffffffffff;
    wire expected_last=(beat_index+5'd1)==length;
    wire bad_beat=rsp_error || rsp_last!=expected_last;
    wire invalid_shape=in_count>6'd32 || in_features==0 || in_features>10'd512 ||
        in_length==0 || in_length>5'd16 ||
        (11'(in_start)+11'(in_length)>11'(in_features)) || in_base[2:0]!=0;
    assign in_ready=state==IDLE;
    assign done_valid=state==FINISHED;
    assign req_valid=state==REQUEST;
    assign req_length=length;
    assign rsp_ready=(state==DRAIN) ||
        ((state==READ) && (load_ready || (rsp_valid && bad_beat)));
    assign load_valid=state==READ && rsp_valid && !bad_beat;
    assign load_address={bank,beat_index[3:0]};
    assign load_row_enable=32'd1<<row_index;
    // All banks see the data; only the selected row has its write enabled.
    assign load_data={32{rsp_data}};
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;channels<=0;row_count<=0;row_index<=0;beat_index<=0;
            length<=0;bank<=0;base<=0;features<=0;start<=0;req_address<=0;done_error<=0;
        end else begin
            case(state)
                IDLE: if(in_valid) begin
                    channels<=in_channels;row_count<=in_count;row_index<=0;beat_index<=0;
                    base<=in_base;features<=in_features;start<=in_start;length<=in_length;
                    bank<=in_bank;done_error<=0;
                    if(in_count==0) state<=FINISHED;
                    else if(invalid_shape) begin done_error<=1;state<=FINISHED;end
                    else state<=ADDRESS;
                end
                ADDRESS: begin
                    beat_index<=0;
                    if(calculated_address[64] || burst_overflow) begin
                        done_error<=1;state<=FINISHED;
                    end else begin req_address<=calculated_address[63:0];state<=REQUEST;end
                end
                REQUEST: if(req_ready) state<=READ;
                READ: if(rsp_valid && rsp_ready) begin
                    if(bad_beat) begin
                        done_error<=1;
                        state<=rsp_last?FINISHED:DRAIN;
                    end else if(expected_last) begin
                        if(({1'b0,row_index}+6'd1)==row_count) state<=FINISHED;
                        else begin row_index<=row_index+1'b1;state<=ADDRESS;end
                    end else beat_index<=beat_index+1'b1;
                end
                DRAIN: if(rsp_valid && rsp_last) state<=FINISHED;
                FINISHED: if(done_ready) state<=IDLE;
                default: begin done_error<=1;state<=FINISHED;end
            endcase
        end
    end
endmodule
