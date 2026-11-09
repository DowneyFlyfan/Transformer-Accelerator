`timescale 1ns/1ps
// Prediction and channel dispatch integration. Group identity and tensor-last
// are sampled with the first accepted strip; in_last ends that group's vector.
// The external weight-transfer engine consumes out_channels and out_count,
// packs fetched rows accordingly and uses out_lane_enable for the PE array.
module tri_oracle_predicted_dispatch (
    input wire clk,rst_n,in_valid,in_last,in_group_last,in_frame_error,out_ready,
    input wire [10:0] in_group,
    input wire [127:0] norm_activations,
    input wire [255:0] gate_weight_signs,up_weight_signs,
    output wire in_ready,out_valid,out_last,out_error,
    output wire [5:0] out_count,
    output wire [511:0] out_channels,
    output wire [255:0] out_lane_enable
);
    reg first_strip;
    reg [10:0] saved_group;
    reg saved_last,saved_error;
    wire prediction_valid,prediction_ready,prediction_error;
    wire [31:0] prediction_skip;
    wire [31:0] unused_gate_mask,unused_up_mask;
    wire [12:0] unused_outlier_count;
    tri_oracle_strip_predictor predictor (
        .clk(clk),.rst_n(rst_n),.in_valid(in_valid),.in_last(in_last),.in_ready(in_ready),
        .norm_activations(norm_activations),.gate_weight_signs(gate_weight_signs),
        .up_weight_signs(up_weight_signs),.out_valid(prediction_valid),.out_ready(prediction_ready),
        .out_error(prediction_error),.skip_mask(prediction_skip),
        .gate_nearzero_mask(unused_gate_mask),.up_nearzero_mask(unused_up_mask),
        .outlier_count(unused_outlier_count)
    );
    tri_oracle_channel_compactor dispatch (
        .clk(clk),.rst_n(rst_n),.in_valid(prediction_valid),.in_ready(prediction_ready),
        .in_group(saved_group),.in_last(saved_last),.in_skip(prediction_skip),
        .in_error(prediction_error || saved_error),.out_ready(out_ready),.out_valid(out_valid),
        .out_last(out_last),.out_error(out_error),.out_count(out_count),
        .out_channels(out_channels),.out_lane_enable(out_lane_enable)
    );
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin first_strip<=1;saved_group<=0;saved_last<=0;saved_error<=0;end
        else if(in_valid && in_ready) begin
            if(first_strip) begin saved_group<=in_group;saved_last<=in_group_last;end
            saved_error<=first_strip?in_frame_error:(saved_error || in_frame_error);
            first_strip<=in_last;
        end
    end
endmodule
