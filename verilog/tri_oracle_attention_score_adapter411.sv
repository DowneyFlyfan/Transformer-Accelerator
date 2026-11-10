`timescale 1ns/1ps
// Map one query and three selected 32-key tiles onto the existing shared
// tensor owner. Each operand has 64 signed eight-bit elements. Valid keys
// form a causal prefix of each tile. Key and query addresses refer to the
// same row-major memory used by the tensor owner. A failed row emits one
// tagged terminal error and no scores. On that error the row producer must
// withdraw queued rows of that head before releasing the error beat.
module tri_oracle_attention_score_adapter411 (
    input logic clk, rst_n,
    input logic row_valid, row_last,
    output logic row_ready,
    input logic [31:0] row_tag,
    input logic [63:0] row_query_addr, row_key_base,
    input logic [16:0] row_key_rows,
    input logic [15:0] row_query_index,
    input logic [47:0] row_tile_start,
    input logic [17:0] row_tile_valid_keys,
    output logic score_valid, score_last, score_error,
    input logic score_ready,
    output logic [31:0] score_tag,
    output logic [1:0] score_region,
    output logic [7:0] score_lanes,
    output logic [255:0] score_data,

    output logic tensor_cfg_valid,
    input logic tensor_cfg_ready,
    output logic [31:0] tensor_cfg_tag,
    output logic [16:0] tensor_cfg_dense_rows,
    output logic [2559:0] tensor_cfg_channels, tensor_cfg_keep,
    output logic [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base,
    input logic tensor_out_valid, tensor_out_last,
    output logic tensor_out_ready,
    input logic [31:0] tensor_out_tag,
    input logic [3:0] tensor_out_token,
    input logic [7:0] tensor_out_count,
    input logic [3071:0] tensor_out_data,
    input logic tensor_done_valid, tensor_done_error,
    output logic tensor_done_ready,
    input logic [31:0] tensor_done_tag
);
    typedef enum logic [2:0] {Idle, Prepare, Submit, Compute, Emit} state_t;
    state_t state;
    logic [47:0] tile_start;
    logic [17:0] tile_valid_keys;
    logic [6:0] key_index;
    logic [3:0] score_beat;
    logic last_row, invalid_row, selected_key_valid, packet_seen, malformed_packet;
    logic [3071:0] saved_scores;

    always_comb begin
        invalid_row = row_key_rows > 65536 || 17'(row_query_index) >= row_key_rows ||
                      row_tile_valid_keys[5:0] == 0;
        for (int region = 0; region < 3; region++) begin
            if (row_tile_valid_keys[region*6 +: 6] > 32 ||
                (row_tile_valid_keys[region*6 +: 6] != 0 &&
                 (17'(row_tile_start[region*16 +: 16]) + 17'(row_tile_valid_keys[region*6 +: 6])) >
                 (17'(row_query_index) + 17'd1)))
                invalid_row = 1;
        end
    end

    assign row_ready = state == Idle;
    assign tensor_cfg_valid = state == Submit;
    assign tensor_out_ready = state == Compute;
    assign tensor_done_ready = state == Compute;
    assign selected_key_valid = 6'(key_index[4:0]) < tile_valid_keys[int'(key_index[6:5])*6 +: 6];
    assign malformed_packet = tensor_out_tag != tensor_cfg_tag || tensor_out_token != 0 ||
                              !tensor_out_last || tensor_out_count != 96;
    assign score_valid = state == Emit;
    assign score_tag = tensor_cfg_tag;
    assign score_region = score_error ? 2'd2 : score_beat[3:2];
    assign score_last = score_error || (last_row && score_beat == 11);
    assign score_data = score_error ? '0 : saved_scores[int'(score_beat)*256 +: 256];
    for (genvar lane = 0; lane < 8; lane++) begin : lanes
        assign score_lanes[lane] = !score_error && (6'({score_beat[1:0], 3'b000}) + 6'(lane)) <
                                    tile_valid_keys[int'(score_region)*6 +: 6];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            tensor_cfg_tag <= 0; tensor_cfg_dense_rows <= 0;
            tensor_cfg_activation_base <= 0; tensor_cfg_weight_base <= 0;
            tensor_cfg_channels <= 0; tensor_cfg_keep <= 0;
            tile_start <= 0; tile_valid_keys <= 0; last_row <= 0;
            score_error <= 0; key_index <= 0; score_beat <= 0;
            packet_seen <= 0;
        end else case (state)
            Idle: if (row_valid) begin
                tensor_cfg_tag <= row_tag;
                tensor_cfg_dense_rows <= row_key_rows;
                tensor_cfg_activation_base <= row_query_addr;
                tensor_cfg_weight_base <= row_key_base;
                tile_start <= row_tile_start;
                tile_valid_keys <= row_tile_valid_keys;
                last_row <= row_last;
                key_index <= 0;
                score_beat <= 0;
                packet_seen <= 0;
                score_error <= invalid_row;
                if (invalid_row) state <= Emit;
                else state <= Prepare;
            end
            Prepare: begin
                // Disabled lanes use a legal placeholder key. The keep bit
                // suppresses its operand read and product in the tensor owner.
                tensor_cfg_channels[int'(key_index)*16 +: 16] <= selected_key_valid ?
                    tile_start[int'(key_index[6:5])*16 +: 16] + 16'(key_index[4:0]) : 16'd0;
                tensor_cfg_keep[int'(key_index)] <= selected_key_valid;
                if (key_index == 95) state <= Submit;
                else key_index <= key_index + 7'd1;
            end
            Submit: if (tensor_cfg_ready) state <= Compute;
            Compute: begin
                if (tensor_out_valid) begin
                    if (!packet_seen) saved_scores <= tensor_out_data;
                    packet_seen <= 1;
                    if (packet_seen || malformed_packet) score_error <= 1;
                end
                if (tensor_done_valid) begin
                    if (tensor_done_error || tensor_done_tag != tensor_cfg_tag || (!packet_seen && !tensor_out_valid))
                        score_error <= 1;
                    state <= Emit;
                end
            end
            Emit: if (score_ready) begin
                if (score_error || score_beat == 11) state <= Idle;
                else score_beat <= score_beat + 4'd1;
            end
            default: state <= Idle;
        endcase
    end
endmodule
