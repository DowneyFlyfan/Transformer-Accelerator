`timescale 1ns/1ps
// Scaled Token Merging Unit from Tri-Oracle, 2026 IEEE International
// Solid-State Circuits Conference, Fig. 31.6.3.
// Published behavior: sign-bit XNOR/popcount similarity, left/up comparison,
// a Survived Sign Bank (SSB), Semantic Address Translator (SAT), Token Merge
// Table (TMT), and iterative On-the-fly Token Size Unit (OTSU).
// The paper does not specify the threshold or tie priority; both are explicit
// here (threshold parameter, upper neighbor first). This is not chip RTL.
module tri_oracle_token_merger #(
    parameter integer IMG_W = 4,
    parameter integer IMG_H = 3,
    parameter integer SIGN_W = 4,
    parameter integer MATCH_THRESHOLD = 3,
    parameter integer TOTAL = IMG_W * IMG_H,
    parameter integer INDEX_W = $clog2(TOTAL + 1),
    parameter integer SLOT_W = (IMG_W > 1) ? $clog2(IMG_W) : 1,
    parameter integer SIZE_W = $clog2(TOTAL + 1),
    parameter integer HIT_W = $clog2(SIGN_W + 1)
) (
    input  wire                    clk,
    input  wire                    rst_n,
    input  wire                    in_valid,
    output wire                    in_ready,
    input  wire [SIGN_W-1:0]       in_sign,
    output reg                     out_valid,
    input  wire                    out_ready,
    output reg [INDEX_W-1:0]       out_index,
    output reg [INDEX_W-1:0]       out_origin,
    output reg [1:0]               out_merge, // 0=new, 1=left, 2=up
    output wire                    size_valid,
    input  wire                    size_ready,
    output wire [INDEX_W-1:0]      size_origin,
    output wire [SIZE_W-1:0]       size_count,
    output wire                    done
);
    localparam [2:0] RUN=0, ROW_COPY=1, COUNT_CLEAR=2,
                     COUNT_SCAN=3, SIZE_EMIT=4, FINISHED=5;
    localparam [HIT_W-1:0] THRESHOLD_W = MATCH_THRESHOLD[HIT_W-1:0];
    localparam [INDEX_W-1:0] TOTAL_W = TOTAL[INDEX_W-1:0];
    localparam [INDEX_W-1:0] LAST_TOKEN = TOTAL_W - 1'b1;
    localparam [SLOT_W-1:0] LAST_COL = IMG_W[SLOT_W-1:0] - 1'b1;
    reg [2:0] state;
    reg [INDEX_W-1:0] token_idx;
    reg [SLOT_W-1:0] col;
    reg prev_valid;

    // The SSB has IMG_W physical entries. SAT maps each semantic location
    // in the previous and current rows to an SSB address. Consumed previous-
    // row entries can be reused without moving surviving sign vectors.
    reg [SIGN_W-1:0] ssb_sign [0:IMG_W-1];
    reg [INDEX_W-1:0] ssb_origin [0:IMG_W-1];
    reg [SLOT_W-1:0] sat_prev [0:IMG_W-1];
    reg [SLOT_W-1:0] sat_curr [0:IMG_W-1];
    reg curr_valid [0:IMG_W-1];

    reg [INDEX_W-1:0] tmt_origin [0:TOTAL-1];
    reg [SIZE_W-1:0] token_size [0:TOTAL-1];
    reg [INDEX_W-1:0] scan_idx;
    reg [INDEX_W-1:0] emit_idx;

    reg [HIT_W-1:0] up_hits;
    reg [HIT_W-1:0] left_hits;
    reg up_match;
    reg left_match;
    reg alloc_found;
    reg [SLOT_W-1:0] alloc_slot;
    reg [SLOT_W-1:0] chosen_slot;
    reg [1:0] chosen_merge;
    reg [INDEX_W-1:0] chosen_origin;
    reg slot_used;
    integer b;
    integer s;
    integer j;
    integer k;

    always @* begin
        up_hits = {HIT_W{1'b0}};
        left_hits = {HIT_W{1'b0}};
        if (prev_valid) begin
            for (b = 0; b < SIGN_W; b = b + 1)
                up_hits = up_hits + {{(HIT_W-1){1'b0}},
                                     (in_sign[b] == ssb_sign[sat_prev[col]][b])};
        end
        if (col != 0) begin
            for (b = 0; b < SIGN_W; b = b + 1)
                left_hits = left_hits + {{(HIT_W-1){1'b0}},
                     (in_sign[b] == ssb_sign[sat_curr[col-1'b1]][b])};
        end
        up_match = prev_valid && (up_hits >= THRESHOLD_W);
        left_match = (col != 0) && curr_valid[col-1'b1] &&
                     (left_hits >= THRESHOLD_W);

        alloc_found = 1'b0;
        alloc_slot = {SLOT_W{1'b0}};
        for (s = 0; s < IMG_W; s = s + 1) begin
            slot_used = 1'b0;
            for (j = 0; j < IMG_W; j = j + 1) begin
                if ((j < col) && curr_valid[j] && sat_curr[j] == s[SLOT_W-1:0])
                    slot_used = 1'b1;
                if (prev_valid && (j > col) && sat_prev[j] == s[SLOT_W-1:0])
                    slot_used = 1'b1;
            end
            if (!slot_used && !alloc_found) begin
                alloc_found = 1'b1;
                alloc_slot = s[SLOT_W-1:0];
            end
        end

        chosen_merge = 2'd0;
        chosen_slot = alloc_slot;
        chosen_origin = token_idx;
        if (up_match) begin
            chosen_merge = 2'd2;
            chosen_slot = sat_prev[col];
            chosen_origin = ssb_origin[sat_prev[col]];
        end else if (left_match) begin
            chosen_merge = 2'd1;
            chosen_slot = sat_curr[col-1'b1];
            chosen_origin = ssb_origin[sat_curr[col-1'b1]];
        end
    end

    assign in_ready = (state == RUN) && (!out_valid || out_ready) &&
                      (chosen_merge != 0 || alloc_found);
    assign size_valid = (state == SIZE_EMIT) && (emit_idx < TOTAL_W) &&
                        (tmt_origin[emit_idx] == emit_idx);
    assign size_origin = emit_idx;
    assign size_count = (emit_idx < TOTAL_W) ? token_size[emit_idx] : {SIZE_W{1'b0}};
    assign done = state == FINISHED;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= RUN;
            token_idx <= {INDEX_W{1'b0}};
            col <= {SLOT_W{1'b0}};
            prev_valid <= 1'b0;
            scan_idx <= {INDEX_W{1'b0}};
            emit_idx <= {INDEX_W{1'b0}};
            out_valid <= 1'b0;
            out_index <= {INDEX_W{1'b0}};
            out_origin <= {INDEX_W{1'b0}};
            out_merge <= 2'd0;
            for (k = 0; k < IMG_W; k = k + 1) begin
                ssb_sign[k] <= {SIGN_W{1'b0}};
                ssb_origin[k] <= {INDEX_W{1'b0}};
                sat_prev[k] <= {SLOT_W{1'b0}};
                sat_curr[k] <= {SLOT_W{1'b0}};
                curr_valid[k] <= 1'b0;
            end
            for (k = 0; k < TOTAL; k = k + 1) begin
                tmt_origin[k] <= {INDEX_W{1'b0}};
                token_size[k] <= {SIZE_W{1'b0}};
            end
        end else begin
            if (out_valid && out_ready)
                out_valid <= 1'b0;
            case (state)
                RUN: if (in_valid && in_ready) begin
                    if (chosen_merge == 0) begin
                        ssb_sign[chosen_slot] <= in_sign;
                        ssb_origin[chosen_slot] <= token_idx;
                    end
                    sat_curr[col] <= chosen_slot;
                    curr_valid[col] <= 1'b1;
                    tmt_origin[token_idx] <= chosen_origin;
                    out_valid <= 1'b1;
                    out_index <= token_idx;
                    out_origin <= chosen_origin;
                    out_merge <= chosen_merge;
                    token_idx <= token_idx + 1'b1;
                    if (col == LAST_COL) begin
                        col <= {SLOT_W{1'b0}};
                        state <= (token_idx == LAST_TOKEN) ? COUNT_CLEAR : ROW_COPY;
                    end else begin
                        col <= col + 1'b1;
                    end
                end
                ROW_COPY: begin
                    for (k = 0; k < IMG_W; k = k + 1) begin
                        sat_prev[k] <= sat_curr[k];
                        curr_valid[k] <= 1'b0;
                    end
                    prev_valid <= 1'b1;
                    state <= RUN;
                end
                COUNT_CLEAR: begin
                    for (k = 0; k < TOTAL; k = k + 1)
                        token_size[k] <= {SIZE_W{1'b0}};
                    scan_idx <= {INDEX_W{1'b0}};
                    state <= COUNT_SCAN;
                end
                COUNT_SCAN: begin
                    token_size[tmt_origin[scan_idx]] <=
                        token_size[tmt_origin[scan_idx]] + 1'b1;
                    if (scan_idx == LAST_TOKEN) begin
                        emit_idx <= {INDEX_W{1'b0}};
                        state <= SIZE_EMIT;
                    end else begin
                        scan_idx <= scan_idx + 1'b1;
                    end
                end
                SIZE_EMIT: begin
                    if (emit_idx == TOTAL_W)
                        state <= FINISHED;
                    else if (!size_valid || size_ready)
                        emit_idx <= emit_idx + 1'b1;
                end
                default: state <= FINISHED;
            endcase
        end
    end
endmodule
