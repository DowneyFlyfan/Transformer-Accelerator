`timescale 1ns/1ps
// Local dispatch protocol for predicted output channels. Group g denotes
// channels 32*g through 32*g+31. Surviving channels retain their order and
// are packed across group boundaries into 32-row weight-fetch/compute batches.
// Two 32-entry banks bound storage and avoid a 32-read-port circular memory.
// Full batches have out_last=0. A final partial batch (possibly empty) marks
// tensor completion; an empty batch requests no weights and no compute.
// Prediction errors force every channel in that group to be retained.
module tri_oracle_channel_compactor (
    input wire clk,rst_n,in_valid,in_last,in_error,out_ready,
    input wire [10:0] in_group,
    input wire [31:0] in_skip,
    output wire in_ready,out_valid,out_last,
    output reg out_error,
    output wire [5:0] out_count,
    output reg [511:0] out_channels,
    output reg [255:0] out_lane_enable
);
    reg [511:0] bank0,bank1;
    reg [31:0] errors0,errors1;
    reg [5:0] tail;
    reg head_bank;
    reg [6:0] count;
    reg busy,end_pending,fallback_seen;
    reg [31:0] pending;
    reg [10:0] group_id;
    reg packet_last,packet_error;
    reg [4:0] first_channel;
    reg [511:0] head_channels;
    reg [31:0] head_errors;
    wire push=busy && (|pending) && count<7'd64;
    wire pop=out_valid && out_ready;
    wire finish=busy && (!(|pending) ||
                (push && ((pending & (pending-32'd1))==0)));
    integer bit_index,row;
    assign in_ready=!busy && !end_pending && count<=7'd32;
    assign out_valid=count>=7'd32 || end_pending;
    assign out_count=(count>=7'd32)?6'd32:count[5:0];
    // Never change a full batch's last flag when a later group finishes.
    assign out_last=end_pending && count<7'd32;
    always @* begin
        first_channel=0;
        for(bit_index=31;bit_index>=0;bit_index=bit_index-1)
            if(pending[bit_index]) first_channel=5'(bit_index);
        head_channels=head_bank?bank1:bank0;
        head_errors=head_bank?errors1:errors0;
        out_channels=0;out_lane_enable=0;
        // For nonempty batches this flag applies to their own descriptors.
        // An empty terminal batch reports whether any group needed fallback.
        out_error=(out_count==0) && fallback_seen;
        for(row=0;row<32;row=row+1) begin
            if(row<int'(out_count)) begin
                out_channels[row*16+:16]=head_channels[row*16+:16];
                out_lane_enable[row*8+:8]=8'hff;
                out_error=out_error || head_errors[row];
            end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            tail<=0;head_bank<=0;count<=0;busy<=0;end_pending<=0;
            pending<=0;group_id<=0;packet_last<=0;packet_error<=0;fallback_seen<=0;
        end else if(pop && out_last) begin
            tail<=0;head_bank<=0;count<=0;busy<=0;end_pending<=0;
            pending<=0;fallback_seen<=0;
        end else begin
            case({push,pop})
                2'b10:count<=count+7'd1;
                2'b01:count<=count-7'd32;
                2'b11:count<=count-7'd31;
                default:count<=count;
            endcase
            if(pop) head_bank<=!head_bank;
            if(in_valid && in_ready) begin
                busy<=1;pending<=in_error?32'hffffffff:~in_skip;
                group_id<=in_group;packet_last<=in_last;packet_error<=in_error;
                fallback_seen<=fallback_seen || in_error;
            end
            if(push) begin
                if(tail[5]) begin
                    bank1[tail[4:0]*16+:16]<={group_id,first_channel};
                    errors1[tail[4:0]]<=packet_error;
                end else begin
                    bank0[tail[4:0]*16+:16]<={group_id,first_channel};
                    errors0[tail[4:0]]<=packet_error;
                end
                tail<=tail+1'b1;
                pending<=pending & ~(32'd1<<first_channel);
            end
            if(finish) begin
                busy<=0;
                if(packet_last) end_pending<=1;
            end
        end
    end
endmodule
