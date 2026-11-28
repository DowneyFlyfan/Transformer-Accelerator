`timescale 1ns/1ps
`default_nettype none

// Test-only connection of a real committed projection cache to the real broker.
// The token-size owner is an external table read from the retained frame.
// This module does not instantiate a compute fabric or supply Q, K or V bytes.
module tri_oracle_trained_cache_broker_peer (
    input logic clk, rst_n, cancel, row_done,
    input logic start, retire_valid,
    output logic initialized, committed, retire_ready,
    input logic [31:0] binding_tag, binding_generation,
    input logic [4:0] binding_layer,
    input logic [15:0] binding_epoch,

    input logic tensor_req_valid,
    output logic tensor_req_ready,
    input logic [1:0] tensor_req_kind,
    input logic [4:0] tensor_req_head,
    input logic [9:0] tensor_req_key,
    input logic [15:0] tensor_req_query, tensor_req_epoch,
    input logic [31:0] tensor_req_tag,
    output logic tensor_rsp_valid,
    input logic tensor_rsp_ready,
    output logic tensor_rsp_error,
    output logic [1:0] tensor_rsp_kind,
    output logic [4:0] tensor_rsp_head,
    output logic [9:0] tensor_rsp_key, tensor_rsp_size,
    output logic [15:0] tensor_rsp_query, tensor_rsp_epoch,
    output logic [31:0] tensor_rsp_tag,
    output logic signed [8:0] tensor_rsp_value_exponent,
    output logic [511:0] tensor_rsp_data
);
    logic read_valid, read_ready, read_result_valid, read_result_ready, read_result_error;
    logic [31:0] read_tag, read_generation, read_result_tag, read_result_generation;
    logic [4:0] read_layer, read_result_layer;
    logic [15:0] read_epoch, read_result_epoch;
    logic [5:0] read_head, read_result_head;
    logic [9:0] read_slot, read_result_slot;
    logic signed [8:0] read_result_unit;
    logic [511:0] read_result_data;
    logic fixture_fault, fixture_reset_required, fixture_busy;
    wire binding_valid = committed;
    string sizes_path;
    logic [9:0] sizes[281];
    logic busy, size_req_valid, size_req_ready, size_rsp_valid, size_rsp_ready, size_rsp_error;
    logic [31:0] size_req_tag, size_req_generation, size_rsp_tag, size_rsp_generation;
    logic [4:0] size_req_layer, size_rsp_layer;
    logic [15:0] size_req_epoch, size_rsp_epoch;
    logic [9:0] size_req_slot, size_rsp_slot, size_rsp_size;
    logic outstanding;
    logic [1:0] expected_kind;
    logic [5:0] expected_head;
    logic [9:0] expected_slot;
    integer cycles, cache_requests, cache_results, size_requests, size_results;
    integer broker_requests, broker_replies, key_requests, value_requests, query_requests;
    integer size_delay;
    logic reported;

    tri_oracle_qkv_cache_path_fixture_v1 cache_owner (
        .clk,.rst_n,.start,.cancel,.start_tag(binding_tag),.start_generation(binding_generation),
        .start_epoch(binding_epoch),.scenario(4'd0),.initialized,.committed,.busy(fixture_busy),
        .fault(fixture_fault),.reset_required(fixture_reset_required),.retire_valid,.retire_ready,
        .read_valid,.read_ready,.read_tag,.read_generation,.read_layer,.read_epoch,.read_head,.read_slot,
        .read_result_valid,.read_result_ready,.read_result_error,.read_result_tag,.read_result_generation,
        .read_result_layer,.read_result_epoch,.read_result_head,.read_result_slot,.read_result_unit,.read_result_data
    );
    tri_oracle_broker_qkv_reader reader (.*);

    initial begin
        if (!$value$plusargs("SIZES=%s",sizes_path)) $fatal(1,"+SIZES=<281-row retained Size file> required");
        $readmemh(sizes_path,sizes);
        foreach (sizes[i])
            if ($isunknown(sizes[i]) || sizes[i] == 0) $fatal(1,"invalid retained Size at slot %0d",i);
    end

    assign size_req_ready = rst_n && size_delay == 0 && !size_rsp_valid && cycles%5 != 1;
    always @(posedge clk) begin
        if (!rst_n) begin
            size_delay <= 0;
            size_rsp_valid <= 0;
            size_rsp_error <= 0;
            cycles <= 0;
            outstanding <= 0;
            cache_requests <= 0; cache_results <= 0; size_requests <= 0; size_results <= 0;
            broker_requests <= 0; broker_replies <= 0;
            key_requests <= 0; value_requests <= 0; query_requests <= 0;
            reported <= 0;
        end else begin
            cycles <= cycles+1;
            if (fixture_fault || fixture_reset_required) $fatal(1,"trained cache owner reported failure");
            if (tensor_req_valid && tensor_req_ready) begin
                if (!binding_valid || outstanding || tensor_req_tag !== binding_tag ||
                    tensor_req_epoch !== binding_epoch || tensor_req_query !== 16'd1)
                    $fatal(1,"overlapping or unbound trained broker request");
                broker_requests <= broker_requests+1;
                outstanding <= 1;
                expected_kind <= tensor_req_kind;
                case (tensor_req_kind)
                    0: begin
                        expected_head <= {1'b0,tensor_req_head};
                        expected_slot <= tensor_req_query[9:0];
                        query_requests <= query_requests+1;
                    end
                    1,2: begin
                        if (tensor_req_key > 1) $fatal(1,"trained key/value outside two committed slots");
                        expected_head <= 6'((tensor_req_kind == 1 ? 32 : 36) + int'(tensor_req_head)/8);
                        expected_slot <= tensor_req_key;
                        if (tensor_req_kind == 1) key_requests <= key_requests+1;
                        else value_requests <= value_requests+1;
                    end
                    default: $fatal(1,"invalid trained tensor kind");
                endcase
            end
            if (read_valid && read_ready) begin
                if (!outstanding || {read_tag,read_generation,read_layer,read_epoch,read_head,read_slot} !==
                    {binding_tag,binding_generation,binding_layer,binding_epoch,expected_head,expected_slot})
                    $fatal(1,"broker issued incorrect physical cache read");
                cache_requests <= cache_requests+1;
            end
            if (read_result_valid && read_result_ready) begin
                if (read_result_error !== 1'b0) $fatal(1,"committed cache rejected trained read");
                cache_results <= cache_results+1;
            end
            if (size_req_valid && size_req_ready) begin
                if (!outstanding || expected_kind !== 2'd1 ||
                    {size_req_tag,size_req_generation,size_req_layer,size_req_epoch,size_req_slot} !==
                    {binding_tag,binding_generation,binding_layer,binding_epoch,expected_slot})
                    $fatal(1,"unexpected token Size lookup");
                size_rsp_tag <= size_req_tag;
                size_rsp_generation <= size_req_generation;
                size_rsp_layer <= size_req_layer;
                size_rsp_epoch <= size_req_epoch;
                size_rsp_slot <= size_req_slot;
                size_rsp_size <= sizes[size_req_slot];
                size_delay <= 2+cycles%3;
                size_requests <= size_requests+1;
            end
            if (size_delay > 0) begin
                size_delay <= size_delay-1;
                if (size_delay == 1) size_rsp_valid <= 1;
            end
            if (size_rsp_valid && size_rsp_ready) begin
                size_rsp_valid <= 0;
                size_results <= size_results+1;
            end
            if (tensor_rsp_valid && tensor_rsp_ready) begin
                if (!outstanding || tensor_rsp_error !== 1'b0 || tensor_rsp_kind !== expected_kind ||
                    (expected_kind == 1 && tensor_rsp_size !== sizes[expected_slot]))
                    $fatal(1,"invalid trained cache response to broker");
                outstanding <= 0;
                broker_replies <= broker_replies+1;
            end
            if (row_done && !reported) begin
                if (busy || outstanding || query_requests != 32 || key_requests != 64 || value_requests != 64 ||
                    broker_replies != 160 || broker_requests != 160 || cache_requests != 160 || cache_results != 160 ||
                    size_requests != 64 || size_results != 64)
                    $fatal(1,"incomplete committed QKV traffic q=%0d k=%0d v=%0d cache=%0d/%0d sizes=%0d/%0d",
                           query_requests,key_requests,value_requests,cache_requests,cache_results,size_requests,size_results);
                $display("COMMITTED_BROKER_READS_PASS Q=%0d K=%0d V=%0d cache_reads=%0d size_reads=%0d",
                         query_requests,key_requests,value_requests,cache_results,size_results);
                reported <= 1;
            end
        end
    end
endmodule
module tri_oracle_joined_qkv_broker_tb;
    tri_oracle_broker_context_spool_tb #(.COMMITTED_INPUT(1)) joined();
endmodule
`default_nettype wire
