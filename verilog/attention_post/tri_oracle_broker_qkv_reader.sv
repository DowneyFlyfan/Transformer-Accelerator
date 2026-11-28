`timescale 1ns/1ps
`default_nettype none

// Adapt one broker tensor request to the committed, head-major Q/K/V cache.
// The caller keeps a frame binding for the broker job; each request snapshots
// it. Slots are absolute, zero-based frame ranks in both the cache and Size
// table. Query requests carry a sentinel key of zero and use the query rank.
// A key fetch also obtains the retained token Size from its independent owner.
module tri_oracle_broker_qkv_reader (
    input  logic clk, rst_n, cancel,
    output logic busy,

    input  logic binding_valid,
    input  logic [31:0] binding_tag, binding_generation,
    input  logic [4:0] binding_layer,
    input  logic [15:0] binding_epoch,

    input  logic tensor_req_valid,
    output logic tensor_req_ready,
    input  logic [1:0] tensor_req_kind,
    input  logic [4:0] tensor_req_head,
    input  logic [9:0] tensor_req_key,
    input  logic [15:0] tensor_req_query, tensor_req_epoch,
    input  logic [31:0] tensor_req_tag,
    output logic tensor_rsp_valid,
    input  logic tensor_rsp_ready,
    output logic tensor_rsp_error,
    output logic [1:0] tensor_rsp_kind,
    output logic [4:0] tensor_rsp_head,
    output logic [9:0] tensor_rsp_key, tensor_rsp_size,
    output logic [15:0] tensor_rsp_query, tensor_rsp_epoch,
    output logic [31:0] tensor_rsp_tag,
    output logic signed [8:0] tensor_rsp_value_exponent,
    output logic [511:0] tensor_rsp_data,

    output logic read_valid,
    input  logic read_ready,
    output logic [31:0] read_tag, read_generation,
    output logic [4:0] read_layer,
    output logic [15:0] read_epoch,
    output logic [5:0] read_head,
    output logic [9:0] read_slot,
    input  logic read_result_valid,
    output logic read_result_ready,
    input  logic read_result_error,
    input  logic [31:0] read_result_tag, read_result_generation,
    input  logic [4:0] read_result_layer,
    input  logic [15:0] read_result_epoch,
    input  logic [5:0] read_result_head,
    input  logic [9:0] read_result_slot,
    input  logic signed [8:0] read_result_unit,
    input  logic [511:0] read_result_data,

    output logic size_req_valid,
    input  logic size_req_ready,
    output logic [31:0] size_req_tag, size_req_generation,
    output logic [4:0] size_req_layer,
    output logic [15:0] size_req_epoch,
    output logic [9:0] size_req_slot,
    input  logic size_rsp_valid,
    output logic size_rsp_ready,
    input  logic size_rsp_error,
    input  logic [31:0] size_rsp_tag, size_rsp_generation,
    input  logic [4:0] size_rsp_layer,
    input  logic [15:0] size_rsp_epoch,
    input  logic [9:0] size_rsp_slot, size_rsp_size
);
    localparam logic [1:0] Query = 2'd0, Key = 2'd1, Value = 2'd2;
    typedef enum logic [2:0] {Idle, CacheIssue, CacheWait, SizeIssue, SizeWait, Reply} state_t;
    state_t state;
    logic cancelled, bad_request, bad_cache_response, bad_size_response;
    logic unknown_request, unknown_cache_data, unknown_size;

    always_comb begin
        unknown_request = 1'b0;
        unknown_cache_data = 1'b0;
        unknown_size = 1'b0;
        // synthesis translate_off
        unknown_request = $isunknown({binding_tag,binding_generation,binding_layer,binding_epoch,
                                      tensor_req_kind,tensor_req_head,tensor_req_key,
                                      tensor_req_query,tensor_req_epoch,tensor_req_tag});
        unknown_cache_data = $isunknown({read_result_unit,read_result_data});
        unknown_size = $isunknown(size_rsp_size);
        // synthesis translate_on
    end

    assign bad_request = binding_valid !== 1'b1 || unknown_request ||
                         tensor_req_tag !== binding_tag || tensor_req_epoch !== binding_epoch ||
                         tensor_req_kind == 2'd3 ||
                         (tensor_req_kind == Query && (tensor_req_key != 0 || tensor_req_query > 1023));
    assign bad_cache_response = read_result_error !== 1'b0 || unknown_cache_data ||
                                {read_result_tag,read_result_generation,read_result_layer,read_result_epoch,
                                 read_result_head,read_result_slot} !==
                                {read_tag,read_generation,read_layer,read_epoch,read_head,read_slot};
    assign bad_size_response = size_rsp_error !== 1'b0 || unknown_size || size_rsp_size == 0 ||
                               {size_rsp_tag,size_rsp_generation,size_rsp_layer,size_rsp_epoch,size_rsp_slot} !==
                               {size_req_tag,size_req_generation,size_req_layer,size_req_epoch,size_req_slot};

    assign busy = state != Idle;
    assign tensor_req_ready = rst_n && state == Idle && cancel === 1'b0;
    assign tensor_rsp_valid = rst_n && state == Reply;
    assign read_valid = rst_n && state == CacheIssue;
    assign read_result_ready = rst_n && state == CacheWait;
    assign size_req_valid = rst_n && state == SizeIssue;
    assign size_rsp_ready = rst_n && state == SizeWait;

    assign read_tag = tensor_rsp_tag;
    assign read_epoch = tensor_rsp_epoch;
    assign size_req_tag = read_tag;
    assign size_req_generation = read_generation;
    assign size_req_layer = read_layer;
    assign size_req_epoch = read_epoch;
    assign size_req_slot = read_slot;

    // Cancellation before Reply poisons the owned transaction. A request
    // already offered to either peer holds valid and its identity until accepted,
    // then consumes the response. Both peers must remain live while draining.
    // Once Reply is visible the entire response is stable until broker acceptance.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            cancelled <= 0;
            tensor_rsp_error <= 0;
            tensor_rsp_kind <= 0;
            tensor_rsp_head <= 0;
            tensor_rsp_key <= 0;
            tensor_rsp_query <= 0;
            tensor_rsp_epoch <= 0;
            tensor_rsp_tag <= 0;
            tensor_rsp_size <= 0;
            tensor_rsp_value_exponent <= 0;
            tensor_rsp_data <= 0;
            read_generation <= 0;
            read_layer <= 0;
            read_head <= 0;
            read_slot <= 0;
        end else begin
            if (state != Idle && state != Reply && cancel !== 1'b0) cancelled <= 1;
            case (state)
                Idle: if (tensor_req_valid && tensor_req_ready) begin
                    cancelled <= 0;
                    tensor_rsp_kind <= tensor_req_kind;
                    tensor_rsp_head <= tensor_req_head;
                    tensor_rsp_key <= tensor_req_key;
                    tensor_rsp_query <= tensor_req_query;
                    tensor_rsp_epoch <= tensor_req_epoch;
                    tensor_rsp_tag <= tensor_req_tag;
                    tensor_rsp_error <= bad_request;
                    tensor_rsp_data <= 0;
                    tensor_rsp_size <= 0;
                    tensor_rsp_value_exponent <= 0;
                    read_generation <= binding_generation;
                    read_layer <= binding_layer;
                    read_slot <= tensor_req_kind == Query ? tensor_req_query[9:0] : tensor_req_key;
                    case (tensor_req_kind)
                        Query: read_head <= {1'b0,tensor_req_head};
                        Key:   read_head <= 6'd32 + 6'(tensor_req_head[4:3]);
                        Value: read_head <= 6'd36 + 6'(tensor_req_head[4:3]);
                        default: read_head <= 0;
                    endcase
                    state <= bad_request ? Reply : CacheIssue;
                end
                CacheIssue: if (read_ready) state <= CacheWait;
                CacheWait: if (read_result_valid) begin
                    if (cancelled || cancel !== 1'b0 || bad_cache_response) begin
                        tensor_rsp_error <= 1;
                        state <= Reply;
                    end else begin
                        tensor_rsp_data <= read_result_data;
                        tensor_rsp_value_exponent <= read_result_unit;
                        state <= tensor_rsp_kind == Key ? SizeIssue : Reply;
                    end
                end
                SizeIssue: if (size_req_ready) state <= SizeWait;
                SizeWait: if (size_rsp_valid) begin
                    if (cancelled || cancel !== 1'b0 || bad_size_response) begin
                        tensor_rsp_error <= 1;
                        tensor_rsp_data <= 0;
                        tensor_rsp_value_exponent <= 0;
                    end else tensor_rsp_size <= size_rsp_size;
                    state <= Reply;
                end
                Reply: if (tensor_rsp_ready) state <= Idle;
                default: state <= Idle;
            endcase
        end
    end
endmodule
`default_nettype wire
