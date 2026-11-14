`timescale 1ns/1ps

// Cache the current and adjacent query's causal sizes from the native
// aggregator tables. The selected-index conversion matches the sparse row.
module tri_oracle_grouped_token_sizes (
    input logic clk, rst_n,
    input logic prepare_valid,
    output logic prepare_ready,
    input logic [10:0] first_position,
    input logic [9:0] image_start,
    input logic [9:0] first_visible, second_visible,
    input logic [3:0] active_rows, streaming_rows,
    output logic done, error,
    input logic done_ready,
    output logic native_query_valid,
    input logic native_query_ready,
    output logic [9:0] native_query_position,
    input logic native_size_valid,
    output logic native_size_ready,
    input logic [9:0] native_size_count,
    input logic native_size_last, native_error,
    input logic [3:0][8:0] size_index,
    output logic [3:0][9:0] selected_size
);
    typedef enum logic [2:0] {Idle, StartQuery, Query, Collect, Done} state_t;
    state_t state;
    logic later, failed;
    logic [1:0] queries;
    logic [10:0] base_position;
    logic [9:0] prefix_start, root_index;
    logic [1:0][9:0] visible, image_roots;
    logic [3:0] streaming;
    logic [9:0] counts [2][512];
    logic [10:0] position, image_end, image_position, text_tail;
    logic [10:0] last_root_rank, implied_visible;

    assign prepare_ready = state == Idle;
    assign native_query_valid = state == Query;
    assign native_size_ready = state == Collect;
    assign done = state == Done;
    assign error = done && failed;
    assign position = base_position + 11'(later);
    assign image_end = 11'(prefix_start) + 11'd576;
    assign image_position = position - 11'(prefix_start);
    assign text_tail = position >= image_end ? position - image_end + 1'b1 : 11'd0;
    assign native_query_position = image_position >= 576 ? 10'd575 : image_position[9:0];
    assign last_root_rank = 11'(prefix_start) + 11'(root_index);
    assign implied_visible = last_root_rank + 1'b1 + text_tail;

    for (genvar lane=0; lane<4; lane++) begin : lookup
        localparam int QUERY = lane / 2;
        logic [9:0] rank;
        assign rank = (streaming[lane] && visible[QUERY]>64 && size_index[lane]>=32)
                    ? visible[QUERY] - 10'd64 + 10'(size_index[lane])
                    : 10'(size_index[lane]);
        assign selected_size[lane] =
            rank >= prefix_start && rank < prefix_start + image_roots[QUERY]
            ? counts[QUERY][9'(rank-prefix_start)] : 10'd1;
    end

    always_ff @(posedge clk) begin
        if (state == Collect && native_size_valid && last_root_rank < 512)
            counts[later][root_index[8:0]] <= native_size_count;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            later <= 0;
            failed <= 0;
            queries <= '0;
            base_position <= 0;
            prefix_start <= 0;
            root_index <= 0;
            visible <= '0;
            image_roots <= '0;
            streaming <= 0;
        end else case (state)
            Idle: if (prepare_valid) begin
                queries <= {|active_rows[3:2], |active_rows[1:0]};
                later <= active_rows[1:0] == 0;
                base_position <= first_position;
                prefix_start <= image_start;
                visible <= {second_visible, first_visible};
                image_roots <= '0;
                streaming <= streaming_rows;
                failed <= active_rows == 0 || (first_position == 11'h7ff && (|active_rows[3:2]));
                state <= active_rows == 0 || (first_position == 11'h7ff && (|active_rows[3:2])) ? Done : StartQuery;
            end
            StartQuery: begin
                root_index <= 0;
                if (position < 11'(prefix_start)) begin
                    if (position + 1'b1 != 11'(visible[later])) begin
                        failed <= 1;
                        state <= Done;
                    end else if (later || !queries[1]) state <= Done;
                    else later <= 1;
                end else state <= Query;
            end
            Query: if (native_error) begin
                failed <= 1;
                state <= Done;
            end else if (native_query_ready) state <= Collect;
            Collect: if (native_error) begin
                failed <= 1;
                state <= Done;
            end else if (native_size_valid) begin
                if (last_root_rank >= 512 || native_size_count == 0) failed <= 1;
                if (native_size_last) begin
                    image_roots[later] <= root_index + 1'b1;
                    if (implied_visible != 11'(visible[later])) failed <= 1;
                    if (later || !queries[1] || failed ||
                        last_root_rank >= 512 || native_size_count == 0 ||
                        implied_visible != 11'(visible[later])) state <= Done;
                    else begin
                        later <= 1;
                        state <= StartQuery;
                    end
                end else if (root_index < 10'd512) root_index <= root_index + 1'b1;
            end
            Done: if (done_ready) state <= Idle;
            default: state <= Idle;
        endcase
    end
endmodule
