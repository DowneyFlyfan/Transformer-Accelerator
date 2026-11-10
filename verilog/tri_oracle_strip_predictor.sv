`timescale 1ns/1ps
// Streaming sign-magnitude estimator for full activation vectors, based on
// Tri-Oracle Fig.31.6.5. Counts accumulate over all strips before the gate/up
// near-zero decisions are intersected. One strip is accepted per ready cycle.
// Local choices: 8 features/strip, 32 outputs, at most 4096 features, a framed
// ready/valid interface, and signed 16-bit activations with 8 fractional bits.
// Normalization
// and sign-only external-memory fetch remain upstream responsibilities.
// Fig31.6.5 uses a one-sided gate estimate (SiLU suppression), an up
// near-zero interval and mask intersection. Numeric thresholds, inclusive
// comparisons and this symmetric up window are local; exact values are undisclosed.
module tri_oracle_strip_predictor #(
    parameter integer ACT_W=16,
    parameter integer LANES=8,
    parameter integer OUTPUTS=32,
    parameter integer MAX_STRIPS=512,
    parameter integer THREE_SIGMA=768,
    parameter integer MARGIN_LIMIT=0, // Up-branch symmetric window, local choice.
    parameter integer GATE_THRESHOLD=0, // One-sided gate margin, local choice.
    parameter integer COUNT_W=$clog2(LANES*MAX_STRIPS+1),
    parameter integer STRIP_COUNT_W=$clog2(MAX_STRIPS+1)
) (
    input wire clk,rst_n,in_valid,in_last,out_ready,
    input wire [ACT_W*LANES-1:0] norm_activations,
    input wire [LANES*OUTPUTS-1:0] gate_weight_signs,up_weight_signs,
    output wire in_ready,
    output reg out_valid,out_error,
    output reg [OUTPUTS-1:0] gate_nearzero_mask,up_nearzero_mask,skip_mask,
    output reg [COUNT_W-1:0] outlier_count
);
    localparam [STRIP_COUNT_W-1:0] MAX_STRIPS_W=STRIP_COUNT_W'(MAX_STRIPS);
    localparam integer COMPARE_W=(ACT_W+1>32)?ACT_W+1:32;
    localparam signed [COMPARE_W-1:0] THREE_SIGMA_W=COMPARE_W'(THREE_SIGMA);
    localparam signed [COUNT_W+1:0] LIMIT_W=(COUNT_W+2)'(MARGIN_LIMIT);
    localparam signed [COUNT_W+1:0] GATE_THRESHOLD_W=(COUNT_W+2)'(GATE_THRESHOLD);
    reg [STRIP_COUNT_W-1:0] strip_count;
    reg frame_error;
    reg [COUNT_W-1:0] outlier_acc,outlier_total;
    reg [COUNT_W-1:0] gate_acc[0:OUTPUTS-1],up_acc[0:OUTPUTS-1];
    reg [COUNT_W-1:0] gate_total[0:OUTPUTS-1],up_total[0:OUTPUTS-1];
    reg [LANES-1:0] outliers;
    reg [OUTPUTS-1:0] gate_zero,up_zero;
    reg signed [ACT_W-1:0] activation;
    reg signed [ACT_W:0] magnitude;
    reg signed [COUNT_W+1:0] gate_margin,up_margin;
    wire can_add=strip_count<MAX_STRIPS_W;
    integer lane,channel,k;
    assign in_ready=!out_valid || out_ready;
    always @* begin
        outliers=0;
        outlier_total=outlier_acc;
        for(lane=0;lane<LANES;lane=lane+1) begin
            activation=$signed(norm_activations[lane*ACT_W+:ACT_W]);
            magnitude=activation<0 ? -$signed({activation[ACT_W-1],activation}) :
                                    $signed({activation[ACT_W-1],activation});
            outliers[lane]=COMPARE_W'(magnitude)>THREE_SIGMA_W;
            if(can_add && outliers[lane]) outlier_total=outlier_total+1'b1;
        end
        gate_zero=0;up_zero=0;
        for(channel=0;channel<OUTPUTS;channel=channel+1) begin
            gate_total[channel]=gate_acc[channel];
            up_total[channel]=up_acc[channel];
            for(lane=0;lane<LANES;lane=lane+1) begin
                if(can_add && outliers[lane]) begin
                    if(norm_activations[(lane+1)*ACT_W-1]==gate_weight_signs[channel*LANES+lane])
                        gate_total[channel]=gate_total[channel]+1'b1;
                    if(norm_activations[(lane+1)*ACT_W-1]==up_weight_signs[channel*LANES+lane])
                        up_total[channel]=up_total[channel]+1'b1;
                end
            end
            gate_margin=($signed({2'b00,gate_total[channel]})<<<1)-$signed({2'b00,outlier_total});
            up_margin=($signed({2'b00,up_total[channel]})<<<1)-$signed({2'b00,outlier_total});
            if(can_add && !frame_error && outlier_total!=0) begin
                gate_zero[channel]=gate_margin<=GATE_THRESHOLD_W;
                up_zero[channel]=up_margin>=-LIMIT_W && up_margin<=LIMIT_W;
            end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            strip_count<=0;frame_error<=0;outlier_acc<=0;
            out_valid<=0;out_error<=0;outlier_count<=0;
            gate_nearzero_mask<=0;up_nearzero_mask<=0;skip_mask<=0;
            for(k=0;k<OUTPUTS;k=k+1) begin gate_acc[k]<=0;up_acc[k]<=0;end
        end else if(in_ready) begin
            out_valid<=in_valid && in_last;
            if(in_valid) begin
                if(in_last) begin
                    out_error<=frame_error || !can_add;
                    outlier_count<=outlier_total;
                    gate_nearzero_mask<=gate_zero;up_nearzero_mask<=up_zero;
                    skip_mask<=gate_zero & up_zero;
                    strip_count<=0;frame_error<=0;outlier_acc<=0;
                    for(k=0;k<OUTPUTS;k=k+1) begin gate_acc[k]<=0;up_acc[k]<=0;end
                end else begin
                    // Saturate on overlong frames, report the error at their
                    // end, and never skip work based on truncated estimates.
                    frame_error<=frame_error || !can_add;
                    if(can_add) strip_count<=strip_count+1'b1;
                    outlier_acc<=outlier_total;
                    for(k=0;k<OUTPUTS;k=k+1) begin
                        gate_acc[k]<=gate_total[k];up_acc[k]<=up_total[k];
                    end
                end
            end
        end
    end
endmodule

/* verilator lint_off DECLFILENAME */
// Each core estimates eight channels from the already-classified outlier bits.
module tri_oracle_core_strip448 (
    input logic clk, rst_n,
    input logic [146:0] request,
    output logic [39:0] response
);
    localparam int COUNT_W=12;
    logic [8:0] strips;
    logic frame_error, out_valid, out_error;
    logic [COUNT_W-1:0] outliers, completed_outliers;
    logic [7:0] gate_mask, up_mask;
    wire [7:0] active = request[135:128];
    wire [7:0] negative = request[143:136];
    wire can_add = strips<9'd256;
    wire in_ready = !out_valid || request[144];
    wire accept = in_ready && request[146];
    wire final_strip = request[145];
    wire [7:0] gate_zero, up_zero;

    function automatic logic [3:0] count8(input logic [7:0] value);
        logic [1:0] pair0, pair1, pair2, pair3;
        logic [2:0] low, high;
        pair0 = 2'(value[0]) + 2'(value[1]);
        pair1 = 2'(value[2]) + 2'(value[3]);
        pair2 = 2'(value[4]) + 2'(value[5]);
        pair3 = 2'(value[6]) + 2'(value[7]);
        low = 3'(pair0) + 3'(pair1);
        high = 3'(pair2) + 3'(pair3);
        return 4'(low) + 4'(high);
    endfunction

    wire [COUNT_W-1:0] next_outliers =
        can_add ? outliers + COUNT_W'(count8(active)) : outliers;
    wire usable = can_add && !frame_error && next_outliers!=0;
    for (genvar channel=0; channel<8; channel++) begin : estimates
        logic [COUNT_W-1:0] gate_matches, up_matches;
        wire [3:0] gate_hits = count8(active & ~(negative ^ request[64+8*channel+:8]));
        wire [3:0] up_hits = count8(active & ~(negative ^ request[8*channel+:8]));
        wire [COUNT_W-1:0] gate_total = gate_matches + COUNT_W'(gate_hits);
        wire [COUNT_W-1:0] up_total = up_matches + COUNT_W'(up_hits);
        // A nonpositive gate estimate and a zero up estimate both use the
        // difference between matching and mismatching outlier signs.
        assign gate_zero[channel] = usable && {gate_total,1'b0}<={1'b0,next_outliers};
        assign up_zero[channel] = usable && {up_total,1'b0}=={1'b0,next_outliers};
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                gate_matches <= '0;
                up_matches <= '0;
            end else if (accept) begin
                if (final_strip) begin
                    gate_matches <= '0;
                    up_matches <= '0;
                end else if (can_add) begin
                    gate_matches <= gate_total;
                    up_matches <= up_total;
                end
            end
        end
    end

    assign response = {in_ready,out_valid,out_error,gate_mask,up_mask,
                       (gate_mask & up_mask),1'b0,completed_outliers};
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            strips <= '0;
            outliers <= '0;
            frame_error <= 0;
            out_valid <= 0;
            out_error <= 0;
            completed_outliers <= '0;
            gate_mask <= '0;
            up_mask <= '0;
        end else if (in_ready) begin
            out_valid <= accept && final_strip;
            if (accept && final_strip) begin
                out_error <= frame_error || !can_add;
                completed_outliers <= next_outliers;
                gate_mask <= gate_zero;
                up_mask <= up_zero;
                strips <= '0;
                outliers <= '0;
                frame_error <= 0;
            end else if (accept) begin
                if (can_add) strips <= strips + 9'd1;
                outliers <= next_outliers;
                frame_error <= frame_error || !can_add;
            end
        end
    end
endmodule

// The four predictors accept and retire a group together. Each receives a
// disjoint range of output channels and the same eight activation signs.
module tri_oracle_cluster_strip448 (
    input logic [530:0] request,
    output logic [111:0] response,
    output logic [587:0] core_requests,
    input logic [159:0] core_responses
);
    wire [3:0] ready, valid, errors;
    wire [31:0] gate_mask, up_mask, skip_mask;
    wire [12:0] counts[4];
    wire take_strip = request[530] && (&ready);
    wire retire_group = request[528] && (&valid);
    wire counts_disagree = counts[0]!=counts[1] || counts[0]!=counts[2] || counts[0]!=counts[3];
    for (genvar core=0; core<4; core++) begin : channels
        assign core_requests[147*core+:147] = {
            take_strip, request[529], retire_group, request[527:512],
            request[256+64*core+:64], request[64*core+:64]
        };
        assign {ready[core], valid[core], errors[core], gate_mask[8*core+:8],
                up_mask[8*core+:8], skip_mask[8*core+:8], counts[core]} = core_responses[40*core+:40];
    end
    assign response = {(&ready), (&valid), ((|errors) || counts_disagree),
                       gate_mask, up_mask, skip_mask, counts[0]};
endmodule
/* verilator lint_on DECLFILENAME */
