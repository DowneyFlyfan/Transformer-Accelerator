`timescale 1ns/1ps

// The sign planes are immutable within a command. Invalidate on every
// accepted frame descriptor, including commands that reuse the same address.
module tri_oracle_sign_word_cache (
    input logic clk, rst_n, frame_start,
    input logic client_req_valid,
    output logic client_req_ready,
    input logic [63:0] client_req_address,
    input logic [4:0] client_req_length,
    output logic client_rsp_valid,
    input logic client_rsp_ready,
    output logic client_rsp_last, client_rsp_error,
    output logic [63:0] client_rsp_data,
    output logic mem_req_valid,
    input logic mem_req_ready,
    output logic [63:0] mem_req_address,
    output logic [4:0] mem_req_length,
    input logic mem_rsp_valid,
    output logic mem_rsp_ready,
    input logic mem_rsp_last, mem_rsp_error,
    input logic [63:0] mem_rsp_data
);
    typedef enum logic [1:0] {Idle, CachedResponse, MemoryResponse} state_t;
    state_t state;
    logic [63:0] valid_words;
    logic [63:3] tags [0:63];
    logic [63:0] words [0:63];
    logic [63:0] hit_data;
    logic [63:3] miss_tag;
    logic [5:0] request_slot, miss_slot;
    logic cacheable_request, fill_pending, hit;

    function automatic logic [5:0] word_slot(input logic [63:3] address);
        logic [5:0] folded;
        folded = '0;
        for (int bit_index = 3; bit_index < 64; bit_index++)
            folded[(bit_index - 3) % 6] ^= address[bit_index];
        return folded;
    endfunction

    assign request_slot = word_slot(client_req_address[63:3]);
    assign cacheable_request = client_req_length == 5'd1 && client_req_address[2:0] == 3'b000;
    assign hit = cacheable_request && !frame_start && valid_words[request_slot] &&
        tags[request_slot] == client_req_address[63:3];

    assign client_req_ready = state == Idle && (hit || mem_req_ready);
    assign mem_req_valid = state == Idle && client_req_valid && !hit;
    assign mem_req_address = client_req_address;
    assign mem_req_length = client_req_length;
    assign client_rsp_valid = state == CachedResponse || (state == MemoryResponse && mem_rsp_valid);
    assign client_rsp_last = state == CachedResponse || mem_rsp_last;
    assign client_rsp_error = state == MemoryResponse && mem_rsp_error;
    assign client_rsp_data = state == CachedResponse ? hit_data : mem_rsp_data;
    assign mem_rsp_ready = state == MemoryResponse && client_rsp_ready;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            valid_words <= '0;
            fill_pending <= 0;
        end else begin
            if (frame_start) begin
                valid_words <= '0;
                fill_pending <= 0;
            end
            case (state)
                Idle: if (client_req_valid && client_req_ready) begin
                    if (hit) begin
                        hit_data <= words[request_slot];
                        state <= CachedResponse;
                    end else begin
                        miss_tag <= client_req_address[63:3];
                        miss_slot <= request_slot;
                        fill_pending <= cacheable_request && !frame_start;
                        state <= MemoryResponse;
                    end
                end
                CachedResponse: if (client_rsp_ready) state <= Idle;
                MemoryResponse: if (mem_rsp_valid && mem_rsp_ready) begin
                    // Cache only a successful single-beat response. Forward
                    // all beats of a malformed response for the caller to drain.
                    if (fill_pending && mem_rsp_last && !mem_rsp_error && !frame_start) begin
                        valid_words[miss_slot] <= 1;
                        tags[miss_slot] <= miss_tag;
                        words[miss_slot] <= mem_rsp_data;
                    end
                    fill_pending <= 0;
                    if (mem_rsp_last) state <= Idle;
                end
                default: state <= Idle;
            endcase
        end
    end
endmodule
