`timescale 1ns/1ps
// One 64-feature compact attention row over the existing signed-eight-bit fabric.
// Bind the tensor owner in ordinary mode with one token, eight feature words,
// and a 64-byte activation stride. Compact keys are stored as leading text,
// every image root in original order, and trailing text (including decode keys).
// The value peer returns one vector per requested compact rank, in order.
// Results retain the 65535 scale. Reset must also reset both peers.
// Every frame consumes 576 map entries before publishing a sticky frame error.
module tri_oracle_attention_row426 (
    input logic clk, rst_n,
    input logic frame_valid,
    output logic frame_ready, frame_error,
    input logic [9:0] frame_image_start,
    input logic map_valid,
    output logic map_ready,
    input logic [9:0] map_origin,

    input logic row_valid,
    output logic row_ready,
    input logic [31:0] row_tag,
    input logic [10:0] row_position, row_key_count,
    input logic row_streaming,
    input logic signed [6:0] row_score_shift,
    input logic [63:0] row_query_addr, row_key_base,
    output logic result_valid, result_error,
    input logic result_ready,
    output logic [31:0] result_tag,
    output logic [2047:0] result_values,

    output logic tensor_cfg_valid,
    input logic tensor_cfg_ready,
    output logic [31:0] tensor_cfg_tag,
    output logic [7:0] tensor_cfg_count,
    output logic [16:0] tensor_cfg_dense_rows,
    output logic [2559:0] tensor_cfg_channels, tensor_cfg_keep,
    output logic [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base,
    input logic tensor_out_valid, tensor_out_last,
    output logic tensor_out_ready,
    input logic [31:0] tensor_out_tag,
    input logic [3:0] tensor_out_token,
    input logic [7:0] tensor_out_count,
    input logic [2559:0] tensor_out_channels,
    input logic [5119:0] tensor_out_data,
    input logic tensor_done_valid, tensor_done_error,
    output logic tensor_done_ready,
    input logic [31:0] tensor_done_tag,

    output logic value_req_valid,
    input logic value_req_ready,
    output logic [9:0] value_req_rank,
    input logic value_rsp_valid, value_rsp_error,
    output logic value_rsp_ready,
    input logic [511:0] value_rsp_data
);
    localparam logic [10:0] IMAGE_TOKENS = 11'd576;
    localparam logic [10:0] WINDOW = 11'd32;
    localparam logic [10:0] SPARSE_KEYS = 11'd64;
    typedef enum logic [4:0] {
        Idle, LoadFrame, CheckFrame, QuerySizes, ReceiveSizes, PrepareRow, BuildTile,
        SubmitTile, ReceiveTile, StoreTile, ConfigureSoftmax, SendScores,
        ReceiveProbability, RequestValue, ReceiveValue, DiscardProbabilities, Result, Failed
    } state_t;
    state_t state;

    logic loaded, streaming;
    logic [9:0] map_index, image_start;
    logic [10:0] root_count, position, visible, selected, cursor, tile_start, suffix_visible;
    logic [7:0] lane;
    logic signed [6:0] score_shift;
    logic [31:0] tag;
    logic [9:0] image_sizes[576];
    logic [9:0] size_index;
    logic [15:0] scores[1024];
    logic [5119:0] packet;
    logic have_packet, bad_packet, current_packet_bad, bad_row;
    logic [15:0] probability;
    logic last_value;
    logic [2047:0] accumulator;

    logic sizes_frame_ready, sizes_map_ready, sizes_query_ready, sizes_valid, sizes_last, sizes_error;
    logic [9:0] size_count, prefix_position;
    logic [10:0] prefix, image_end, remaining;
    logic [9:0] send_rank;
    logic [9:0] selected_size;
    logic norm_cfg_ready, norm_in_ready, norm_out_valid, norm_out_last;
    logic [15:0] norm_probability;

    // Power-of-two score scaling, nearest even when right shifting, signed saturation.
    function automatic logic [15:0] scale_score(input logic signed [31:0] dot, input logic signed [6:0] shift);
        logic [31:0] magnitude;
        logic [63:0] rounded, halfway;
        logic [4:0] amount;
        magnitude = dot[31] ? (~$unsigned(dot) + 32'd1) : $unsigned(dot);
        amount = shift[6] ? 5'(-shift) : shift[4:0];
        if (shift[6]) begin
            halfway = 64'd1 << (amount-1'b1);
            rounded = (64'(magnitude) + halfway - 64'd1 + ((64'(magnitude) >> amount) & 64'd1)) >> amount;
        end else begin
            rounded = 64'(magnitude) << amount;
        end
        if (dot[31]) return rounded >= 64'd32768 ? 16'h8000 : (~16'(rounded) + 16'd1);
        return rounded >= 64'd32767 ? 16'h7fff : 16'(rounded);
    endfunction

    function automatic logic [9:0] compact_rank(input logic [10:0] selected_index);
        if (streaming && visible > SPARSE_KEYS && selected_index >= WINDOW)
            return 10'(visible - SPARSE_KEYS + selected_index);
        return 10'(selected_index);
    endfunction

    assign frame_ready = state == Idle && sizes_frame_ready;
    assign frame_error = sizes_error && state != LoadFrame && state != CheckFrame;
    assign map_ready = state == LoadFrame && (sizes_map_ready || sizes_error);
    assign row_ready = state == Idle && !frame_valid;
    assign image_end = 11'(image_start) + IMAGE_TOKENS;
    assign prefix = position - 11'(image_start);
    assign prefix_position = prefix >= IMAGE_TOKENS ? 10'(IMAGE_TOKENS-1'b1) : 10'(prefix);
    assign suffix_visible = position < image_end ? 11'd0 : position - image_end + 1'b1;
    assign bad_row = !loaded || row_key_count == 0 || row_key_count > 1024 ||
                     row_key_count < 11'(image_start) + root_count ||
                     row_position >= row_key_count + IMAGE_TOKENS - root_count ||
                     row_score_shift < -7'sd31 || row_score_shift > 7'sd31;

    tri_oracle_causal_token_size sizes (
        .clk, .rst_n, .frame_valid(frame_valid && state == Idle), .frame_ready(sizes_frame_ready),
        .map_valid(map_valid && state == LoadFrame && !sizes_error), .map_ready(sizes_map_ready), .map_origin,
        .map_last(map_index == 10'(IMAGE_TOKENS-1'b1)),
        .query_valid(state == QuerySizes), .query_ready(sizes_query_ready), .query_position(prefix_position),
        .out_valid(sizes_valid), .out_ready(state == ReceiveSizes), .out_origin(), .out_count(size_count),
        .out_last(sizes_last), .error(sizes_error)
    );

    assign result_valid = state == Result || state == Failed;
    assign result_error = state == Failed;
    assign result_tag = tag;
    assign result_values = result_error ? '0 : accumulator;

    assign tensor_cfg_valid = state == SubmitTile;
    assign tensor_out_ready = state == ReceiveTile;
    assign tensor_done_ready = state == ReceiveTile;
    assign tensor_cfg_tag = tag;
    // All chosen rows are visible. The single query owns the low 160 keep bits.
    assign tensor_cfg_keep = {2400'd0, {160{1'b1}}};
    assign remaining = selected - tile_start;
    assign current_packet_bad = tensor_out_valid &&
        (have_packet || tensor_out_tag != tag || tensor_out_token != 0 || !tensor_out_last ||
         tensor_out_count != tensor_cfg_count || tensor_out_channels != tensor_cfg_channels);

    assign send_rank = compact_rank(cursor);
    assign selected_size = (11'(send_rank) >= 11'(image_start) &&
                            11'(send_rank) < 11'(image_start) + root_count)
        ? image_sizes[10'(send_rank-image_start)] : 10'd1;

    tri_oracle_proportional_softmax normalize (
        .clk, .rst_n, .cfg_valid(state == ConfigureSoftmax), .cfg_ready(norm_cfg_ready),
        .cfg_length(selected), .cfg_error(),
        .in_valid(state == SendScores), .in_ready(norm_in_ready),
        .in_score(scores[cursor[9:0]]), .in_size(selected_size),
        .out_valid(norm_out_valid), .out_ready(state == ReceiveProbability || state == DiscardProbabilities),
        .out_probability(norm_probability), .out_last(norm_out_last)
    );

    assign value_req_valid = state == RequestValue;
    assign value_req_rank = compact_rank(cursor);
    assign value_rsp_ready = state == ReceiveValue;

    always_ff @(posedge clk) begin
        if (state == ReceiveSizes && sizes_valid)
            image_sizes[size_index] <= size_count;
        if (state == StoreTile)
            scores[10'(tile_start + 11'(lane))] <= scale_score($signed(packet[int'(lane)*32 +: 32]), score_shift);
        if (state == ReceiveTile && tensor_out_valid && !have_packet)
            packet <= tensor_out_data;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            loaded <= 0;
            streaming <= 0;
            map_index <= 0;
            image_start <= 0;
            root_count <= 0;
            position <= 0;
            visible <= 0;
            selected <= 0;
            cursor <= 0;
            tile_start <= 0;
            lane <= 0;
            score_shift <= 0;
            size_index <= 0;
            tag <= 0;
            tensor_cfg_count <= 0;
            tensor_cfg_dense_rows <= 0;
            tensor_cfg_channels <= 0;
            tensor_cfg_activation_base <= 0;
            tensor_cfg_weight_base <= 0;
            have_packet <= 0;
            bad_packet <= 0;
            probability <= 0;
            last_value <= 0;
            accumulator <= 0;
        end else case (state)
            Idle: begin
                if (frame_valid && frame_ready) begin
                    image_start <= frame_image_start;
                    map_index <= 0;
                    root_count <= 0;
                    loaded <= 0;
                    state <= LoadFrame;
                end else if (row_valid && row_ready) begin
                    tag <= row_tag;
                    position <= row_position;
                    streaming <= row_streaming;
                    score_shift <= row_score_shift;
                    tensor_cfg_activation_base <= row_query_addr;
                    tensor_cfg_weight_base <= row_key_base;
                    tensor_cfg_dense_rows <= 17'(row_key_count);
                    accumulator <= 0;
                    size_index <= 0;
                    if (bad_row) state <= Failed;
                    else if (row_position < 11'(image_start)) begin
                        visible <= row_position + 1'b1;
                        state <= PrepareRow;
                    end else state <= QuerySizes;
                end
            end
            LoadFrame: if (map_valid && map_ready) begin
                if (!sizes_error && map_origin == map_index) root_count <= root_count + 1'b1;
                map_index <= map_index + 1'b1;
                if (map_index == 10'(IMAGE_TOKENS-1'b1)) state <= CheckFrame;
            end
            CheckFrame: begin
                loaded <= !sizes_error;
                state <= Idle;
            end
            QuerySizes: if (sizes_query_ready) state <= ReceiveSizes;
            ReceiveSizes: if (sizes_valid) begin
                size_index <= size_index + 1'b1;
                if (sizes_last) begin
                    visible <= 11'(image_start) + 11'(size_index) + 1'b1 + suffix_visible;
                    state <= PrepareRow;
                end
            end
            PrepareRow: begin
                selected <= streaming && visible > SPARSE_KEYS ? SPARSE_KEYS : visible;
                tile_start <= 0;
                lane <= 0;
                tensor_cfg_channels <= 0;
                state <= BuildTile;
            end
            BuildTile: begin
                tensor_cfg_channels[int'(lane)*16 +: 16] <= 16'(compact_rank(tile_start + 11'(lane)));
                lane <= lane + 1'b1;
                if (lane == 8'd159 || 11'(lane)+11'd1 == remaining) begin
                    tensor_cfg_count <= lane + 1'b1;
                    lane <= 0;
                    state <= SubmitTile;
                end
            end
            SubmitTile: if (tensor_cfg_ready) begin
                have_packet <= 0;
                bad_packet <= 0;
                state <= ReceiveTile;
            end
            ReceiveTile: begin
                if (tensor_out_valid) begin
                    have_packet <= 1;
                    bad_packet <= bad_packet || current_packet_bad;
                end
                if (tensor_done_valid) begin
                    if (tensor_done_error || tensor_done_tag != tag || bad_packet ||
                        current_packet_bad || !(have_packet || tensor_out_valid)) state <= Failed;
                    else state <= StoreTile;
                end
            end
            StoreTile: begin
                lane <= lane + 1'b1;
                if (lane + 1'b1 == tensor_cfg_count) begin
                    lane <= 0;
                    if (11'(tensor_cfg_count) == remaining) state <= ConfigureSoftmax;
                    else begin
                        tile_start <= tile_start + 11'(tensor_cfg_count);
                        tensor_cfg_channels <= 0;
                        state <= BuildTile;
                    end
                end
            end
            ConfigureSoftmax: if (norm_cfg_ready) begin
                cursor <= 0;
                state <= SendScores;
            end
            SendScores: if (norm_in_ready) begin
                cursor <= cursor + 1'b1;
                if (cursor + 1'b1 == selected) begin
                    cursor <= 0;
                    state <= ReceiveProbability;
                end
            end
            ReceiveProbability: if (norm_out_valid) begin
                probability <= norm_probability;
                last_value <= norm_out_last;
                state <= RequestValue;
            end
            RequestValue: if (value_req_ready) state <= ReceiveValue;
            ReceiveValue: if (value_rsp_valid) begin
                if (value_rsp_error) begin
                    if (last_value) state <= Failed;
                    else state <= DiscardProbabilities;
                end else begin
                    for (int feature = 0; feature < 64; feature++)
                        accumulator[feature*32 +: 32] <= $signed(accumulator[feature*32 +: 32]) +
                            $signed({1'b0, probability}) * $signed(value_rsp_data[feature*8 +: 8]);
                    cursor <= cursor + 1'b1;
                    if (last_value) state <= Result;
                    else state <= ReceiveProbability;
                end
            end
            DiscardProbabilities: if (norm_out_valid && norm_out_last) state <= Failed;
            Result, Failed: if (result_ready) state <= Idle;
            default: state <= Idle;
        endcase
    end
endmodule
