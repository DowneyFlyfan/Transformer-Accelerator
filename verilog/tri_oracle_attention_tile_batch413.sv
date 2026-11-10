`timescale 1ns/1ps
// Share three disjoint key tiles across up to 16 queries. The tensor owner
// reads each selected key once for each feature word active in the batch.
// Rows are contiguous 64-byte vectors. Masks enforce causality per query.
// A terminal error discards the entire head, including any earlier score rows.
// The caller withdraws pending batches of that head before releasing the error.
module tri_oracle_attention_tile_batch413 (
    input logic clk, rst_n,
    input logic batch_valid, batch_last,
    output logic batch_ready,
    input logic [31:0] batch_tag,
    input logic [63:0] batch_query_addr, batch_key_base,
    input logic [16:0] batch_key_rows,
    input logic [15:0] batch_query_first,
    input logic [4:0] batch_queries,
    input logic [47:0] batch_tile_start,

    output logic score_valid, score_last, score_error,
    input logic score_ready,
    output logic [31:0] score_tag,
    output logic [1:0] score_region,
    output logic [7:0] score_lanes,
    output logic [255:0] score_data,

    output logic tensor_cfg_valid,
    input logic tensor_cfg_ready,
    output logic [31:0] tensor_cfg_tag,
    output logic [4:0] tensor_cfg_tokens,
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
    typedef enum logic [2:0] {Idle, Prepare, Submit, ReadPacket, EmitPacket, WaitDone, Drain, Error} state_t;
    state_t state;
    logic last_batch, bad_config, last_token, bad_packet, extra_packet;
    logic [47:0] tile_start;
    logic [17:0] row_limits;
    logic [15:0] first_query;
    logic [16:0] query_limit, key_position, last_query;
    logic [6:0] key_index;
    logic [3:0] token_index, score_beat;
    logic [3071:0] saved_scores;

    function automatic logic [5:0] tile_limit(input logic [16:0] query_bound, input logic [15:0] start);
        logic [16:0] span;
        span = query_bound - 17'(start);
        if (query_bound <= 17'(start)) return 0;
        if (span >= 32) return 32;
        return 6'(span);
    endfunction

    assign bad_config = batch_key_rows > 65536 || batch_queries == 0 || batch_queries > 16 ||
                        17'(batch_query_first) + 17'(batch_queries) > batch_key_rows ||
                        batch_tile_start[15:0] > batch_query_first ||
                        17'(batch_tile_start[15:0]) + 17'd32 > 17'(batch_tile_start[31:16]) ||
                        17'(batch_tile_start[31:16]) + 17'd32 > 17'(batch_tile_start[47:32]) ||
                        17'(batch_tile_start[47:32]) >= batch_key_rows;
    assign batch_ready = state == Idle;
    assign tensor_cfg_valid = state == Submit;
    assign tensor_out_ready = state == ReadPacket || state == WaitDone || state == Drain;
    assign tensor_done_ready = tensor_out_ready;
    assign key_position = 17'(tile_start[int'(key_index[6:5])*16 +: 16]) + 17'(key_index[4:0]);
    assign last_query = 17'(first_query) + 17'(tensor_cfg_tokens) - 17'd1;
    assign query_limit = 17'(first_query) + 17'(token_index) + 17'd1;
    assign last_token = 5'(token_index) + 5'd1 == tensor_cfg_tokens;
    assign bad_packet = tensor_out_tag != tensor_cfg_tag || tensor_out_token != token_index ||
                        tensor_out_last != last_token || tensor_out_count != 96;
    assign score_valid = state == EmitPacket || state == Error;
    assign score_error = state == Error;
    assign score_tag = tensor_cfg_tag;
    assign score_region = score_error ? 2'd3 : score_beat[3:2];
    assign score_last = score_error || (last_batch && last_token && score_beat == 11);
    assign score_data = score_error ? '0 : saved_scores[int'(score_beat)*256 +: 256];
    for (genvar lane = 0; lane < 8; lane++) begin : lanes
        assign score_lanes[lane] = !score_error && (6'({score_beat[1:0], 3'b000}) + 6'(lane)) <
                                    row_limits[int'(score_beat[3:2])*6 +: 6];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            tensor_cfg_tag <= 0; tensor_cfg_tokens <= 0; tensor_cfg_dense_rows <= 0;
            tensor_cfg_activation_base <= 0; tensor_cfg_weight_base <= 0;
            tensor_cfg_channels <= 0; tensor_cfg_keep <= 0;
            tile_start <= 0; first_query <= 0; row_limits <= 0;
            last_batch <= 0; extra_packet <= 0;
            key_index <= 0; token_index <= 0; score_beat <= 0;
        end else case (state)
            Idle: if (batch_valid) begin
                tensor_cfg_tag <= batch_tag;
                tensor_cfg_tokens <= batch_queries;
                tensor_cfg_dense_rows <= batch_key_rows;
                tensor_cfg_activation_base <= batch_query_addr;
                tensor_cfg_weight_base <= batch_key_base;
                tile_start <= batch_tile_start;
                first_query <= batch_query_first;
                last_batch <= batch_last;
                key_index <= 0; token_index <= 0; score_beat <= 0;
                extra_packet <= 0;
                if (bad_config) state <= Error;
                else state <= Prepare;
            end
            Prepare: begin
                // A key beyond the final query is absent from every row.
                tensor_cfg_channels[int'(key_index)*16 +: 16] <= key_position <= last_query ?
                    key_position[15:0] : 16'd0;
                for (int token = 0; token < 16; token++)
                    tensor_cfg_keep[token*160+int'(key_index)] <= 5'(token) < tensor_cfg_tokens &&
                        key_position <= 17'(first_query) + 17'(token);
                if (key_index == 95) state <= Submit;
                else key_index <= key_index + 7'd1;
            end
            Submit: if (tensor_cfg_ready) state <= ReadPacket;
            ReadPacket: begin
                if (tensor_done_valid) state <= Error;
                else if (tensor_out_valid) begin
                    if (bad_packet) state <= Drain;
                    else begin
                        saved_scores <= tensor_out_data;
                        for (int region = 0; region < 3; region++)
                            row_limits[region*6 +: 6] <= tile_limit(query_limit, tile_start[region*16 +: 16]);
                        if (last_token) state <= WaitDone;
                        else state <= EmitPacket;
                    end
                end
            end
            // Hold the last row until the tensor owner certifies completion.
            WaitDone: begin
                if (tensor_out_valid) extra_packet <= 1;
                if (tensor_done_valid) begin
                    if (tensor_done_error || tensor_done_tag != tensor_cfg_tag || extra_packet || tensor_out_valid)
                        state <= Error;
                    else state <= EmitPacket;
                end
            end
            Drain: if (tensor_done_valid) state <= Error;
            EmitPacket: if (score_ready) begin
                if (score_beat == 11) begin
                    score_beat <= 0;
                    if (last_token) state <= Idle;
                    else begin
                        token_index <= token_index + 4'd1;
                        state <= ReadPacket;
                    end
                end else score_beat <= score_beat + 4'd1;
            end
            Error: if (score_ready) state <= Idle;
            default: state <= Idle;
        endcase
    end
endmodule
