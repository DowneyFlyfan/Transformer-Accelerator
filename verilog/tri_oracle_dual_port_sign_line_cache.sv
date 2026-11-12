`timescale 1ns/1ps

// Sign lines stay immutable during a frame. Both memory ports share one
// cache and one outstanding request, selected by the measured steering hash.
module tri_oracle_dual_port_sign_line_cache #(
    parameter int ENTRIES = 128
) (
    input logic clk, rst_n, frame_start,
    input logic client_req_valid,
    output logic client_req_ready,
    input logic [63:0] client_req_address,
    input logic [5:0] client_req_length,
    output logic client_rsp_valid,
    input logic client_rsp_ready,
    output logic client_rsp_last, client_rsp_error,
    output logic [511:0] client_rsp_data,
    output logic [1:0] mem_req_valid,
    input logic [1:0] mem_req_ready,
    output logic [63:0] mem_req_address,
    output logic [5:0] mem_req_length,
    input logic [1:0] mem_rsp_valid,
    output logic [1:0] mem_rsp_ready,
    input logic [1:0] mem_rsp_last, mem_rsp_error,
    input logic [1:0][511:0] mem_rsp_data
);
    localparam int INDEX_BITS = $clog2(ENTRIES);
    localparam int BANK_BITS = INDEX_BITS - 5;
    localparam int BANKS = ENTRIES / 32;
    localparam logic [4:0] PRIMARY_BUCKETS = ENTRIES == 256 ? 5'd8 : 5'd9;

    typedef enum logic [2:0] {Idle, Request, MemoryResponse, CachedResponse, InvalidResponse} state_t;
    state_t state;
    logic [ENTRIES-1:0] valid_lines;
    // At a given folded index, the high tag bits uniquely determine the low
    // address bits. Store only the high bits to avoid duplicate tag storage.
    logic [63:6+INDEX_BITS] tags[ENTRIES];
    logic [INDEX_BITS-1:0] request_slot, miss_slot, access_slot;
    logic [BANK_BITS-1:0] read_bank;
    logic [4:0] request_bucket;
    logic miss_port, fill_pending;
    logic accept_client, accept_response, request_legal, hit, read_line, write_line;
    logic [511:0] bank_output[BANKS];

    always_comb begin
        request_slot = '0;
        request_bucket = '0;
        for (int bit_index = 6; bit_index < 64; bit_index++) begin
            request_slot[(bit_index - 6) % INDEX_BITS] ^= client_req_address[bit_index];
            request_bucket[(bit_index - 6) % 5] ^= client_req_address[bit_index];
        end
    end

    assign request_legal = client_req_length == 6'd1 && client_req_address[5:0] == 0;
    assign hit = valid_lines[request_slot] && tags[request_slot] == client_req_address[63:6+INDEX_BITS];
    assign client_req_ready = state == Idle && !frame_start;
    assign accept_client = client_req_valid && client_req_ready;
    assign mem_req_valid = state == Request ? (2'b01 << miss_port) : 2'b00;
    assign mem_req_length = 6'd1;
    assign mem_rsp_ready = state == MemoryResponse && client_rsp_ready ? (2'b01 << miss_port) : 2'b00;
    assign accept_response = state == MemoryResponse && client_rsp_ready && mem_rsp_valid[miss_port];
    assign read_line = accept_client && request_legal && hit;
    assign write_line = accept_response && fill_pending && mem_rsp_last[miss_port] &&
                        !mem_rsp_error[miss_port] && !frame_start;
    assign access_slot = write_line ? miss_slot : request_slot;

    always_comb begin
        client_rsp_valid = 0;
        client_rsp_last = 0;
        client_rsp_error = 0;
        client_rsp_data = '0;
        case (state)
            MemoryResponse: begin
                client_rsp_valid = mem_rsp_valid[miss_port];
                client_rsp_last = mem_rsp_last[miss_port];
                client_rsp_error = mem_rsp_error[miss_port];
                client_rsp_data = mem_rsp_data[miss_port];
            end
            CachedResponse: begin
                client_rsp_valid = 1;
                client_rsp_last = 1;
                client_rsp_data = bank_output[read_bank];
            end
            InvalidResponse: begin
                client_rsp_valid = 1;
                client_rsp_last = 1;
                client_rsp_error = 1;
            end
            default: ;
        endcase
    end

    for (genvar bank = 0; bank < BANKS; bank++) begin : storage_banks
        logic selected;
        assign selected = (read_line || write_line) && access_slot[INDEX_BITS-1:5] == BANK_BITS'(bank);
        for (genvar word = 0; word < 4; word++) begin : slices
            TS5N28HPCPSVTA32X128M2FW data_memory (
                .CLK(clk), .CEB(!selected), .WEB(!write_line), .A(access_slot[4:0]),
                .D(mem_rsp_data[miss_port][128*word+:128]), .BWEB(128'b0),
                .Q(bank_output[bank][128*word+:128])
            );
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            valid_lines <= '0;
            fill_pending <= 0;
            miss_port <= 0;
            miss_slot <= '0;
            read_bank <= '0;
            mem_req_address <= '0;
        end else begin
            if (frame_start) begin
                valid_lines <= '0;
                fill_pending <= 0;
            end
            case (state)
                Idle: if (accept_client) begin
                    if (!request_legal) state <= InvalidResponse;
                    else if (hit) begin
                        read_bank <= request_slot[INDEX_BITS-1:5];
                        state <= CachedResponse;
                    end else begin
                        mem_req_address <= client_req_address;
                        miss_slot <= request_slot;
                        miss_port <= request_bucket >= PRIMARY_BUCKETS;
                        fill_pending <= 1;
                        state <= Request;
                    end
                end
                Request: if (mem_req_ready[miss_port]) state <= MemoryResponse;
                MemoryResponse: if (accept_response) begin
                    if (write_line) begin
                        valid_lines[miss_slot] <= 1;
                        tags[miss_slot] <= mem_req_address[63:6+INDEX_BITS];
                    end
                    fill_pending <= 0;
                    if (mem_rsp_last[miss_port]) state <= Idle;
                end
                CachedResponse, InvalidResponse: if (client_rsp_ready) state <= Idle;
                default: state <= Idle;
            endcase
        end
    end
endmodule
