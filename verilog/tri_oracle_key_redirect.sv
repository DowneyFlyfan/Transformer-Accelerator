module tri_oracle_key_redirect (
    input logic clk, rst_n,
    input logic row_valid, row_ready, result_valid, result_ready,
    input logic [63:0] row_key_base, row_query_addr,
    input logic [10:0] row_key_count,
    input logic req_valid,
    output logic req_ready,
    input logic [63:0] req_address,
    input logic [4:0] req_length,
    output logic rsp_valid,
    input logic rsp_ready,
    output logic rsp_last, rsp_error,
    output logic [63:0] rsp_word,
    output logic narrow_req_valid,
    input logic narrow_req_ready,
    input logic narrow_rsp_valid,
    output logic narrow_rsp_ready,
    input logic narrow_rsp_last, narrow_rsp_error,
    input logic [63:0] narrow_rsp_word,
    output logic wide_req_valid,
    input logic wide_req_ready,
    output logic [63:0] wide_req_address,
    input logic wide_rsp_valid,
    output logic wide_rsp_ready,
    input logic wide_rsp_last, wide_rsp_error,
    input logic [511:0] wide_rsp_data,
    output logic key_owner, storage_select, storage_write,
    output logic [4:0] storage_address,
    output logic [511:0] storage_data,
    input logic [511:0] storage_read
);
    logic row_start, eligible, use_buffer, outstanding, key_transaction;
    logic [63:0] key_base;
    logic [10:0] key_count;
    logic [64:0] offset, end_address;
    logic [5:0] end_word;
    logic key_ready, key_valid, key_last, key_error;
    logic [63:0] key_word;

    assign row_start = row_valid && row_ready;
    assign end_address = {1'b0,row_key_base} + {48'b0,row_key_count,6'b0};
    assign eligible = row_key_count != 0 && row_key_count <= 11'd1024 && row_key_base[5:0] == 0 &&
                      !end_address[64] &&
                      (row_query_addr < row_key_base || row_query_addr >= end_address[63:0]);
    assign offset = {1'b0,req_address} - {1'b0,key_base};
    assign end_word = {3'b0,req_address[5:3]} + {1'b0,req_length};
    assign use_buffer = key_owner && !offset[64] && offset[63:6] < {47'b0,key_count}
                      && req_address[2:0] == 0 && req_length != 0 && end_word <= 8;
    assign narrow_req_valid = !outstanding && req_valid && !use_buffer;
    assign req_ready = !outstanding && (use_buffer ? key_ready : narrow_req_ready);
    assign rsp_valid = outstanding && (key_transaction ? key_valid : narrow_rsp_valid);
    assign narrow_rsp_ready = outstanding && !key_transaction && rsp_ready;
    assign rsp_last = key_transaction ? key_last : narrow_rsp_last;
    assign rsp_error = key_transaction ? key_error : narrow_rsp_error;
    assign rsp_word = key_transaction ? key_word : narrow_rsp_word;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            key_owner <= 1'b0;
            outstanding <= 1'b0;
            key_transaction <= 1'b0;
            key_base <= '0;
            key_count <= '0;
        end else begin
            if (row_start) begin
                key_owner <= eligible;
                key_base <= row_key_base;
                key_count <= row_key_count;
            end else if (result_valid && result_ready) begin
                key_owner <= 1'b0;
            end
            if (req_valid && req_ready) begin
                outstanding <= 1'b1;
                key_transaction <= use_buffer;
            end else if (rsp_valid && rsp_ready && rsp_last) begin
                outstanding <= 1'b0;
            end
        end
    end

    tri_oracle_key_buffer_external_storage buffer (
        .clk,.rst_n,.row_start,.key_base(row_key_base),
        .req_valid(!outstanding && req_valid && use_buffer),.req_ready(key_ready),
        .key_rank(offset[15:6]),.word_start(req_address[5:3]),.word_count(req_length[3:0]),
        .rsp_valid(key_valid),.rsp_ready(outstanding && key_transaction && rsp_ready),
        .rsp_last(key_last),.rsp_error(key_error),.rsp_word(key_word),
        .wide_req_valid,.wide_req_ready,.wide_req_address,.wide_rsp_valid,.wide_rsp_ready,
        .wide_rsp_last,.wide_rsp_error,.wide_rsp_data,
        .storage_select,.storage_write,.storage_address,.storage_data,.storage_read
    );
endmodule
