module tri_oracle_key_tile_read_buffer (
    input  logic         clk, rst_n,
    input  logic         row_start,
    input  logic [63:0]  key_base,
    input  logic         req_valid,
    output logic         req_ready,
    input  logic [9:0]   key_rank,
    input  logic [2:0]   word_start,
    input  logic [3:0]   word_count,
    output logic         rsp_valid,
    input  logic         rsp_ready,
    output logic         rsp_last, rsp_error,
    output logic [63:0]  rsp_word,
    output logic         wide_req_valid,
    input  logic         wide_req_ready,
    output logic [63:0]  wide_req_address,
    input  logic         wide_rsp_valid,
    output logic         wide_rsp_ready,
    input  logic         wide_rsp_last, wide_rsp_error,
    input  logic [511:0] wide_rsp_data
);
    typedef enum logic [2:0] {Idle, Request, Receive, Drain, Read, Respond} state_t;
    state_t state;
    logic [31:0] valid;
    logic [9:0] tags [32];
    logic [4:0] next_slot, slot;
    logic [31:0] tag_matches;
    logic hit;
    logic [4:0] hit_slot;
    logic [9:0] requested_rank;
    logic [63:0] row_base;
    logic [2:0] word_index;
    logic [3:0] words_left;
    logic failed;
    logic [511:0] line;
    logic read_enable, write_enable;

    for (genvar entry=0; entry<32; entry++) begin : compare_tags
        assign tag_matches[entry] = valid[entry] && tags[entry] == key_rank;
    end
    assign hit = |tag_matches;
    // Each valid rank appears in at most one entry.
    always_comb begin
        hit_slot = '0;
        for (int entry=0; entry<32; entry++)
            hit_slot |= 5'(entry) & {5{tag_matches[entry]}};
    end

    assign req_ready = rst_n && state == Idle && !row_start;
    assign wide_req_valid = state == Request;
    assign wide_req_address = row_base + {48'd0, requested_rank, 6'd0};
    assign wide_rsp_ready = state == Receive || state == Drain;
    assign read_enable = state == Read;
    assign write_enable = state == Receive && wide_rsp_valid && wide_rsp_last && !wide_rsp_error;
    assign rsp_valid = state == Respond;
    assign rsp_last = rsp_valid && words_left == 1;
    assign rsp_error = rsp_valid && failed;
    assign rsp_word = failed ? '0 : line[64*word_index+:64];

    for (genvar part=0; part<4; part++) begin : banks
        TS5N28HPCPSVTA32X128M2FW bank (
            .CLK(clk), .CEB(!(read_enable || write_enable)), .WEB(!write_enable),
            .A(slot), .D(wide_rsp_data[128*part+:128]), .BWEB(128'b0),
            .Q(line[128*part+:128])
        );
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            row_base <= '0;
            valid <= '0;
            next_slot <= '0;
            slot <= '0;
            requested_rank <= '0;
            word_index <= '0;
            words_left <= '0;
            failed <= 1'b0;
        end else begin
            case (state)
                Idle: if (row_start) begin
                    row_base <= key_base;
                    valid <= '0;
                    next_slot <= '0;
                end else if (req_valid) begin
                    requested_rank <= key_rank;
                    word_index <= word_start;
                    words_left <= word_count;
                    slot <= hit ? hit_slot : next_slot;
                    failed <= 1'b0;
                    state <= hit ? Read : Request;
                end
                Request: if (wide_req_ready) state <= Receive;
                Receive: if (wide_rsp_valid) begin
                    failed <= wide_rsp_error || !wide_rsp_last;
                    if (!wide_rsp_last) state <= Drain;
                    else if (wide_rsp_error) state <= Respond;
                    else begin
                        valid[slot] <= 1'b1;
                        next_slot <= next_slot+5'd1;
                        state <= Read;
                    end
                end
                Drain: if (wide_rsp_valid && wide_rsp_last) state <= Respond;
                Read: state <= Respond;
                Respond: if (rsp_ready) begin
                    word_index <= word_index+3'd1;
                    words_left <= words_left-4'd1;
                    if (rsp_last) state <= Idle;
                end
                default: state <= Idle;
            endcase
        end
    end

    always_ff @(posedge clk)
        if (write_enable)
            tags[slot] <= requested_rank;
endmodule
