`timescale 1ns/1ps

// Store the 32 head rows of each of two tokens in projection read order.
// Writes are provisional until all 64 distinct rows have been received.
// A duplicate row invalidates the frame until reset or release.
module tri_oracle_projection_activation_store (
    input logic clk, rst_n, in_valid,
    input logic [2047:0] in_data,
    input logic [4:0] in_shift,
    input logic [5:0] in_row,
    output logic in_ready,
    output logic frame_ready, fill_error,
    input logic release_valid,
    output logic release_ready,
    input logic req_valid,
    input logic [8:0] req_word,
    input logic [4:0] req_length,
    output logic req_ready, rsp_valid,
    input logic rsp_ready,
    output logic rsp_last, rsp_error,
    output logic [63:0] rsp_data
);
    logic [63:0] present, row_mask;
    logic [5:0] rows_received;
    logic word_valid, word_ready, word_last, duplicate;
    logic [5:0] word_row;
    logic [2:0] word_column;
    logic [63:0] write_data, read_data;
    logic [8:0] memory_address, read_word;
    logic [4:0] beats_remaining;
    logic memory_write, memory_read, advance_read, request_bad;
    logic [9:0] request_end;

    tri_oracle_attention_projection_stream convert (
        .clk, .rst_n, .in_valid, .in_ready, .in_data, .in_shift, .in_row,
        .out_valid(word_valid), .out_ready(word_ready), .out_last(word_last),
        .out_row(word_row), .out_word(word_column), .out_data(write_data)
    );

    assign release_ready = rst_n && (frame_ready || fill_error) && !rsp_valid;
    assign word_ready = !frame_ready && !fill_error && !release_valid;
    assign duplicate = present[word_row];
    assign row_mask = 64'b1 << word_row;
    assign memory_write = word_valid && word_ready && !duplicate;
    assign req_ready = rst_n && frame_ready && !release_valid && !rsp_valid;
    assign request_end = {1'b0, req_word} + 10'(req_length);
    assign request_bad = req_length == 0 || req_length > 16 || request_end > 512;
    assign advance_read = rsp_valid && rsp_ready && !rsp_last;
    assign memory_read = (req_valid && req_ready && !request_bad) || advance_read;
    assign memory_address = memory_write ? {word_row, word_column} :
                            advance_read ? read_word + 9'd1 : req_word;
    assign rsp_data = rsp_valid && !rsp_error ? read_data : '0;

    TS5N28HPCPSVTA512X64M4F activation_bank (
        .CLK(clk), .CEB(!(memory_write || memory_read)), .WEB(!memory_write),
        .A(memory_address), .D(write_data), .Q(read_data)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            present <= '0;
            rows_received <= '0;
            frame_ready <= 0;
            fill_error <= 0;
            rsp_valid <= 0;
            rsp_last <= 0;
            rsp_error <= 0;
            read_word <= '0;
            beats_remaining <= '0;
        end else begin
            if (release_valid && release_ready) begin
                present <= '0;
                rows_received <= '0;
                frame_ready <= 0;
                fill_error <= 0;
            end else if (word_valid && word_ready && word_last) begin
                if (duplicate)
                    fill_error <= 1;
                else begin
                    present <= present | row_mask;
                    rows_received <= rows_received + 6'd1;
                    frame_ready <= rows_received == 6'd63;
                end
            end

            if (req_valid && req_ready) begin
                rsp_valid <= 1;
                rsp_last <= request_bad || req_length == 1;
                rsp_error <= request_bad;
                read_word <= req_word;
                beats_remaining <= req_length;
            end else if (rsp_valid && rsp_ready) begin
                if (rsp_last) rsp_valid <= 0;
                else begin
                    read_word <= read_word + 9'd1;
                    beats_remaining <= beats_remaining - 5'd1;
                    rsp_last <= beats_remaining == 2;
                end
            end
        end
    end
endmodule
