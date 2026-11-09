`timescale 1ns/1ps
// Sparse down-projection contributions using original intermediate-channel IDs.
// Row-major signed INT8 weights: address=base+output_row*dense_features+input_ID.
// One-word read cache gathers selected bytes into eight-feature compute strips.
// Incoming gated values are signed32 codes; shift/round/saturate into INT8.
// Output slots1..15 retain partial sums across packets; slot0 is reserved for
// gate/up work. Appends require matching tensor tag, output start and row count.
// Empty overwrite initializes zeros; empty append reads/finalizes existing sums.
// A failed packet invalidates its destination context. Reset also invalidates
// contexts; external memory protocol must reset with this controller.
// These layout, quantization and protocol choices are local implementations.
module tri_oracle_down_executor_staged (
    input wire clk,rst_n,in_valid,in_last,in_accumulate,out_ready,
    input wire [31:0] in_tag,
    input wire [5:0] in_count,in_output_count,in_shift,
    input wire [511:0] in_channels,
    input wire [1023:0] in_data,
    input wire [63:0] in_weight_base,
    input wire [16:0] in_dense_features,
    input wire [15:0] in_output_start,
    input wire [3:0] in_slot,
    output wire in_ready,out_valid,out_last,out_error,
    output wire [31:0] out_tag,
    output wire [5:0] out_count,
    output wire [15:0] out_start,
    output wire [3:0] out_slot,
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
    localparam [4:0] IDLE=0,QUANTIZE=1,MASK=2,ACTIVATION=3,LOOKUP=4,
        REQUEST=5,RESPONSE=6,DRAIN_ERROR=7,LOAD_WEIGHT=8,ISSUE=9,
        WAIT_CORE=10,READ_RESULT=11,WAIT_READ=12,FAILED=13,RESULT=14,
        ROW_SELECT=15,ROW_PRODUCTS=16,ROW_COMBINE=17,ROW_LOW=18,ROW_HIGH=19,
        LANE_SELECT=20,ADDRESS_LOW=21,ADDRESS_HIGH=22,
        QUANT_MAGNITUDE=23,QUANT_ROUND=24,QUANT_SHIFT=25,QUANT_STORE=26;
    reg [4:0] state;
    reg [3:0] slot;
    reg [31:0] tag;
    reg [5:0] count,output_count,shift,quant_index,chunk_start,row_index;
    reg [2:0] lane_index;
    reg last,accumulate,result_error,fault,cache_valid;
    reg [511:0] channels;
    reg [1023:0] source_data,result_data;
    reg [255:0] values;
    reg signed [31:0] quant_raw;
    reg quant_negative;
    reg [33:0] quant_magnitude,quant_rounded,quant_shifted;
    reg [63:0] weight_base,weight_buffer,request_address,cache_address,cache_data;
    reg [16:0] dense_features;
    reg [15:0] output_start,slot_valid;
    reg [31:0] slot_tags[0:15];
    reg [15:0] slot_starts[0:15];
    reg [5:0] slot_counts[0:15];
    reg invalid_shape;
    reg [255:0] mask;
    reg [63:0] activation_word;
    wire [5:0] chunk_length=(count-chunk_start>6'd8)?6'd8:(count-chunk_start);
    wire [4:0] selected_index=chunk_start[4:0]+{2'd0,lane_index};
    reg [15:0] selected_id,row_number;
    reg [7:0] selected_value;
    reg [24:0] row_low_product,row_high_product;
    reg [31:0] row_offset,row_base_low,address_low;
    reg row_low_carry,lane_low_carry;
    reg [32:0] row_base_high,address_high;
    wire [32:0] calculated_row_low={1'b0,weight_base[31:0]}+{1'b0,row_offset};
    wire [32:0] calculated_lane_low={1'b0,row_base_low}+33'(selected_id);
    wire [16:0] output_row={1'b0,output_start}+17'(row_index);
    wire [64:0] next_address={address_high,address_low};
    wire [63:0] aligned_address={next_address[63:3],3'b000};
    // Aligned address <=2^64-8 whenever next_address[64]==0; its last byte fits.
    wire cache_hit=cache_valid && cache_address==aligned_address;
    wire bad_completion=core_done_valid && (state!=WAIT_CORE || core_done_output!=slot);
    wire abort_packet=fault || core_load_error || bad_completion;
    integer i,r,lane;
    assign in_ready=state==IDLE;
    assign out_valid=state==RESULT;
    assign out_last=last;
    assign out_error=result_error;
    assign out_tag=tag;
    assign out_count=result_error?6'd0:output_count;
    assign out_start=output_start;
    assign out_slot=slot;
    assign out_data=result_data;
    assign req_valid=state==REQUEST && !abort_packet;
    assign req_address=request_address;
    assign req_length=5'd1;
    assign rsp_ready=state==RESPONSE || state==DRAIN_ERROR;
    assign core_load_valid=!abort_packet && (state==MASK || state==ACTIVATION || state==LOAD_WEIGHT);
    assign core_load_kind=(state==MASK)?2'd2:(state==ACTIVATION?2'd1:2'd0);
    assign core_load_address=0;
    assign core_load_data=(state==MASK)?{{1792{1'b0}},mask}:
        (state==ACTIVATION?{{1984{1'b0}},activation_word}:{32{weight_buffer}});
    assign core_load_rows=(state==LOAD_WEIGHT)?(32'd1<<row_index):32'd0;
    assign core_cmd_valid=state==ISSUE && !abort_packet;
    assign core_cmd_weight=0;
    assign core_cmd_activation=0;
    assign core_cmd_mask=0;
    assign core_cmd_output=slot;
    assign core_cmd_accumulate=accumulate || chunk_start!=0;
    assign core_read_valid=state==READ_RESULT && !abort_packet;
    assign core_read_output=slot;
    always @* begin
        invalid_shape=in_count>6'd32 || in_output_count==0 || in_output_count>6'd32 || in_slot==0 ||
            in_dense_features<17'd8 || in_dense_features>17'd65536 || in_dense_features[2:0]!=0 ||
            (17'(in_output_start)+17'(in_output_count)>17'd65536) || in_weight_base[2:0]!=0 ||
            (in_accumulate && (!slot_valid[in_slot] || slot_tags[in_slot]!=in_tag ||
                slot_starts[in_slot]!=in_output_start || slot_counts[in_slot]!=in_output_count));
        for(i=0;i<32;i=i+1)
            if(i<int'(in_count) && {1'b0,in_channels[i*16+:16]}>=in_dense_features) invalid_shape=1;
        mask=0;activation_word=0;
        for(lane=0;lane<8;lane=lane+1) begin
            if(lane<int'(chunk_length))
                activation_word[lane*8+:8]=values[(int'(chunk_start)+lane)*8+:8];
            for(r=0;r<32;r=r+1)
                if(r<int'(output_count) && lane<int'(chunk_length)) mask[r*8+lane]=1;
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;slot<=0;tag<=0;count<=0;output_count<=0;shift<=0;quant_index<=0;
            chunk_start<=0;row_index<=0;lane_index<=0;last<=0;accumulate<=0;result_error<=0;fault<=0;
            cache_valid<=0;channels<=0;source_data<=0;result_data<=0;values<=0;weight_base<=0;
            weight_buffer<=0;request_address<=0;cache_address<=0;cache_data<=0;dense_features<=0;
            output_start<=0;slot_valid<=0;
            selected_id<=0;selected_value<=0;row_number<=0;row_low_product<=0;row_high_product<=0;
            row_offset<=0;row_base_low<=0;row_low_carry<=0;row_base_high<=0;
            address_low<=0;lane_low_carry<=0;address_high<=0;
            quant_raw<=0;quant_negative<=0;quant_magnitude<=0;quant_rounded<=0;quant_shifted<=0;
        end else begin
            if(state!=IDLE && state!=FAILED && state!=RESULT && (core_load_error || bad_completion)) fault<=1;
            case(state)
                IDLE: if(in_valid) begin
                    slot<=in_slot;tag<=in_tag;count<=in_count;output_count<=in_output_count;shift<=in_shift;
                    quant_index<=0;chunk_start<=0;row_index<=0;lane_index<=0;last<=in_last;
                    accumulate<=in_accumulate;result_error<=0;fault<=0;cache_valid<=0;
                    channels<=in_channels;source_data<=in_data;result_data<=0;values<=0;
                    weight_base<=in_weight_base;dense_features<=in_dense_features;output_start<=in_output_start;
                    if(!in_accumulate) slot_valid[in_slot]<=0;
                    if(invalid_shape) state<=FAILED;
                    else if(in_count==0) state<=in_accumulate?READ_RESULT:MASK;
                    else state<=QUANTIZE;
                end
                QUANTIZE: begin
                    if(abort_packet) state<=FAILED;
                    else begin quant_raw<=$signed(source_data[quant_index[4:0]*32+:32]);state<=QUANT_MAGNITUDE;end
                end
                QUANT_MAGNITUDE: begin
                    if(abort_packet) state<=FAILED;
                    else begin
                        quant_negative<=quant_raw[31];
                        quant_magnitude<=quant_raw[31] ? -$signed({{2{quant_raw[31]}},quant_raw}) : {2'b0,quant_raw};
                        state<=QUANT_ROUND;
                    end
                end
                QUANT_ROUND: begin
                    if(abort_packet) state<=FAILED;
                    else begin
                        // Magnitude <=2^31 and bias <=2^31;34 unsigned bits
                        // preserve the exact sum even for signed32 minimum.
                        quant_rounded<=quant_magnitude+((shift!=0 && shift<=6'd32) ? (34'd1<<(shift-6'd1)) : 34'd0);
                        state<=QUANT_SHIFT;
                    end
                end
                QUANT_SHIFT: begin
                    if(abort_packet) state<=FAILED;
                    else begin quant_shifted<=shift>6'd32 ? 34'd0 : (quant_rounded>>shift);state<=QUANT_STORE;end
                end
                QUANT_STORE: begin
                    if(abort_packet) state<=FAILED;
                    else begin
                        if(quant_negative)
                            values[quant_index[4:0]*8+:8]<=quant_shifted>34'd128 ? 8'h80 : 8'(-$signed({1'b0,quant_shifted[7:0]}));
                        else values[quant_index[4:0]*8+:8]<=quant_shifted>34'd127 ? 8'h7f : quant_shifted[7:0];
                        quant_index<=quant_index+6'd1;
                        state<=quant_index+6'd1==count ? MASK : QUANTIZE;
                    end
                end
                MASK: begin
                    if(abort_packet) state<=FAILED;
                    else if(core_load_ready) state<=ACTIVATION;
                end
                ACTIVATION: begin
                    if(abort_packet) state<=FAILED;
                    else if(core_load_ready) begin
                        row_index<=0;lane_index<=0;weight_buffer<=0;
                        state<=count==0 ? ISSUE : ROW_SELECT;
                    end
                end
                // A valid descriptor guarantees output_row <=65535. Thus
                // row*dense_features <=65535*65536 <2^32, so row_offset32 is exact.
                ROW_SELECT: begin
                    if(abort_packet) state<=FAILED;
                    else begin row_number<=16'(output_row);state<=ROW_PRODUCTS;end
                end
                ROW_PRODUCTS: begin
                    if(abort_packet) state<=FAILED;
                    else begin
                        row_low_product<=25'(row_number[7:0])*25'(dense_features);
                        row_high_product<=25'(row_number[15:8])*25'(dense_features);
                        state<=ROW_COMBINE;
                    end
                end
                ROW_COMBINE: begin
                    if(abort_packet) state<=FAILED;
                    else begin row_offset<=32'({row_high_product,8'b0}+{8'b0,row_low_product});state<=ROW_LOW;end
                end
                ROW_LOW: begin
                    if(abort_packet) state<=FAILED;
                    else begin row_base_low<=calculated_row_low[31:0];row_low_carry<=calculated_row_low[32];state<=ROW_HIGH;end
                end
                ROW_HIGH: begin
                    if(abort_packet) state<=FAILED;
                    else begin row_base_high<={1'b0,weight_base[63:32]}+{32'b0,row_low_carry};state<=LANE_SELECT;end
                end
                LANE_SELECT: begin
                    if(abort_packet || row_base_high[32]) state<=FAILED;
                    else begin
                        selected_id<=channels[selected_index*16+:16];selected_value<=values[selected_index*8+:8];
                        state<=ADDRESS_LOW;
                    end
                end
                ADDRESS_LOW: begin
                    if(abort_packet) state<=FAILED;
                    else begin address_low<=calculated_lane_low[31:0];lane_low_carry<=calculated_lane_low[32];state<=ADDRESS_HIGH;end
                end
                ADDRESS_HIGH: begin
                    if(abort_packet) state<=FAILED;
                    else begin address_high<=row_base_high+{32'b0,lane_low_carry};state<=LOOKUP;end
                end
                LOOKUP: begin
                    if(abort_packet || next_address[64]) state<=FAILED;
                    else if(selected_value==0 || cache_hit) begin
                        weight_buffer[lane_index*8+:8]<=selected_value==0 ? 8'd0 : cache_data[next_address[2:0]*8+:8];
                        if({3'd0,lane_index}+6'd1==chunk_length) state<=LOAD_WEIGHT;
                        else begin lane_index<=lane_index+3'd1;state<=LANE_SELECT;end
                    end else begin request_address<=aligned_address;state<=REQUEST;end
                end
                REQUEST: begin
                    if(abort_packet) state<=FAILED;
                    else if(req_ready) state<=RESPONSE;
                end
                RESPONSE: if(rsp_valid) begin
                    if(!rsp_last) begin fault<=1;state<=DRAIN_ERROR;end
                    else if(rsp_error || abort_packet) state<=FAILED;
                    else begin cache_data<=rsp_data;cache_address<=request_address;cache_valid<=1;state<=LOOKUP;end
                end
                DRAIN_ERROR: if(rsp_valid && rsp_last) state<=FAILED;
                LOAD_WEIGHT: begin
                    if(abort_packet) state<=FAILED;
                    else if(core_load_ready) begin
                        if(row_index+6'd1==output_count) state<=ISSUE;
                        else begin row_index<=row_index+6'd1;lane_index<=0;weight_buffer<=0;state<=ROW_SELECT;end
                    end
                end
                ISSUE: begin
                    if(abort_packet) state<=FAILED;
                    else if(core_cmd_ready) state<=WAIT_CORE;
                end
                WAIT_CORE: if(core_done_valid) begin
                    if(abort_packet) state<=FAILED;
                    else begin
                        slot_valid[slot]<=1;slot_tags[slot]<=tag;slot_starts[slot]<=output_start;slot_counts[slot]<=output_count;
                        if(count==0 || chunk_start+chunk_length==count) state<=READ_RESULT;
                        else begin chunk_start<=chunk_start+chunk_length;state<=MASK;end
                    end
                end
                READ_RESULT: begin
                    if(abort_packet) state<=FAILED;
                    else state<=WAIT_READ;
                end
                WAIT_READ: if(core_result_valid) begin
                    if(abort_packet) state<=FAILED;
                    else begin result_data<=core_result_data;state<=RESULT;end
                end
                FAILED: begin result_error<=1;result_data<=0;slot_valid[slot]<=0;state<=RESULT;end
                RESULT: if(out_ready) begin if(last) slot_valid[slot]<=0;state<=IDLE;end
                default: state<=FAILED;
            endcase
        end
    end
endmodule
