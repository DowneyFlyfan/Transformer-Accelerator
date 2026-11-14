`timescale 1ns/1ps

// The grouped batch exclusively owns the native token-size coordinator.
// Between streams, an idle coordinator with ready low has no usable frame.
module tri_oracle_grouped_size_arbiter (
    input  logic clk, rst_n,
    input  logic [4:0] query_valid,
    output logic [4:0] query_ready,
    input  logic [4:0][9:0] query_position,
    output logic [4:0] size_valid,
    input  logic [4:0] size_ready,
    output logic [4:0] size_last, error,
    output logic [9:0] size_count,
    output logic native_query_valid,
    input  logic native_query_ready,
    output logic [9:0] native_query_position,
    input  logic native_size_valid,
    output logic native_size_ready,
    input  logic native_size_last, native_error,
    input  logic [9:0] native_size_count
);
    logic busy, found;
    logic [2:0] owner, next_client, candidate;

    always_comb begin : arbitrate
        int index;
        found = 0;
        candidate = '0;
        for (int offset = 0; offset < 5; offset++) begin
            index = int'(next_client) + offset;
            if (index >= 5) index -= 5;
            if (!found && query_valid[index]) begin
                candidate = 3'(index);
                found = 1;
            end
        end
    end

    assign size_count = native_size_count;

    always_comb begin
        query_ready = '0;
        size_valid = '0;
        size_last = '0;
        error = '0;
        native_query_valid = 0;
        native_query_position = '0;
        native_size_ready = 0;
        if (busy) begin
            error[owner] = native_error;
            size_valid[owner] = native_size_valid && !native_error;
            size_last[owner] = native_size_last && size_valid[owner];
            native_size_ready = size_ready[owner] && !native_error;
        end else if (found) begin
            if (native_query_ready && !native_error) begin
                query_ready[candidate] = 1;
                native_query_valid = 1;
                native_query_position = query_position[candidate];
            end else error[candidate] = 1;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            owner <= '0;
            next_client <= '0;
            busy <= 0;
        end else if (busy) begin
            if (native_error || (native_size_valid && native_size_ready && native_size_last)) busy <= 0;
        end else if (found) begin
            next_client <= candidate == 3'd4 ? 3'd0 : candidate + 1'b1;
            if (native_query_valid) begin
                owner <= candidate;
                busy <= 1;
            end
        end
    end
endmodule
