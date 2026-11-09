`timescale 1ns/1ps
// Pipelined sparse direct-memory-access address generation; same transaction protocol.
// Seven address stages replace the original combined selector/multiply/add/check path.
module tri_oracle_sparse_weight_dma_pipelined (
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

    localparam logic [3:0] IDLE=0,SELECT_ROW=1,PARTIAL_PRODUCTS=2,COMBINE_PRODUCT=3,
        ADD_START=4,ADDRESS_LOW=5,ADDRESS_HIGH_AND_END=6,CHECK_ADDRESS=7,
        REQUEST=8,READ=9,DRAIN=10,FINISHED=11;
    logic [3:0] state;
    logic [511:0] channels;
    logic [5:0] row_count;
    logic [4:0] row_index,beat_index,length;
    logic bank;
    logic [63:0] base;
    logic [9:0] features;
    logic [8:0] start;
    logic [15:0] selected_channel;
    logic [17:0] low_product,high_product;
    logic [25:0] channel_product;
    logic [26:0] strip_offset;
    logic [31:0] address_low;
    logic low_carry;
    logic [32:0] address_high,end_low;
    wire [32:0] next_low={1'b0,base[31:0]}+({6'b0,strip_offset}<<3);
    wire expected_last=(beat_index+5'd1)==length;
    wire bad_beat=rsp_error || rsp_last!=expected_last;
    wire invalid_shape=in_count>6'd32 || in_features==0 || in_features>10'd512 ||
        in_length==0 || in_length>5'd16 ||
        (11'(in_start)+11'(in_length)>11'(in_features)) || in_base[2:0]!=0;
    assign in_ready=state==IDLE;
    assign done_valid=state==FINISHED;
    assign req_valid=state==REQUEST;
    assign req_length=length;
    assign rsp_ready=state==DRAIN || (state==READ && (load_ready || (rsp_valid && bad_beat)));
    assign load_valid=state==READ && rsp_valid && !bad_beat;
    assign load_address={bank,beat_index[3:0]};
    assign load_row_enable=32'd1<<row_index;
    assign load_data={32{rsp_data}};
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;channels<=0;row_count<=0;row_index<=0;beat_index<=0;
            length<=0;bank<=0;base<=0;features<=0;start<=0;req_address<=0;done_error<=0;
            selected_channel<=0;low_product<=0;high_product<=0;channel_product<=0;strip_offset<=0;
            address_low<=0;low_carry<=0;address_high<=0;end_low<=0;
        end else begin
            case(state)
                IDLE: if(in_valid) begin
                    channels<=in_channels;row_count<=in_count;row_index<=0;beat_index<=0;
                    base<=in_base;features<=in_features;start<=in_start;length<=in_length;
                    bank<=in_bank;done_error<=0;
                    if(in_count==0) state<=FINISHED;
                    else if(invalid_shape) begin done_error<=1;state<=FINISHED;end
                    else state<=SELECT_ROW;
                end
                SELECT_ROW: begin selected_channel<=channels[row_index*16+:16];state<=PARTIAL_PRODUCTS;end
                PARTIAL_PRODUCTS: begin
                    low_product<=18'(selected_channel[7:0])*18'(features);
                    high_product<=18'(selected_channel[15:8])*18'(features);
                    state<=COMBINE_PRODUCT;
                end
                COMBINE_PRODUCT: begin channel_product<={high_product,8'b0}+{8'b0,low_product};state<=ADD_START;end
                ADD_START: begin strip_offset<={1'b0,channel_product}+27'(start);state<=ADDRESS_LOW;end
                ADDRESS_LOW: begin address_low<=next_low[31:0];low_carry<=next_low[32];state<=ADDRESS_HIGH_AND_END;end
                ADDRESS_HIGH_AND_END: begin
                    address_high<={1'b0,base[63:32]}+{32'b0,low_carry};
                    end_low<={1'b0,address_low}+(33'(length)<<3)-33'd1;
                    state<=CHECK_ADDRESS;
                end
                CHECK_ADDRESS: begin
                    beat_index<=0;
                    if(address_high[32] || (end_low[32] && (&address_high[31:0]))) begin
                        done_error<=1;state<=FINISHED;
                    end else begin req_address<={address_high[31:0],address_low};state<=REQUEST;end
                end
                REQUEST: if(req_ready) state<=READ;
                READ: if(rsp_valid && rsp_ready) begin
                    if(bad_beat) begin done_error<=1;state<=rsp_last ? FINISHED : DRAIN;end
                    else if(expected_last) begin
                        if(({1'b0,row_index}+6'd1)==row_count) state<=FINISHED;
                        else begin row_index<=row_index+1'b1;state<=SELECT_ROW;end
                    end else beat_index<=beat_index+1'b1;
                end
                DRAIN: if(rsp_valid && rsp_last) state<=FINISHED;
                FINISHED: if(done_ready) state<=IDLE;
                default: begin done_error<=1;state<=FINISHED;end
            endcase
        end
    end
endmodule
