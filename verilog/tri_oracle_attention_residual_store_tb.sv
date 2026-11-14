`timescale 1ns/1ps
module tri_oracle_attention_residual_store_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic in_valid = 0, in_ready;
    logic [8:0] in_row;
    logic [279:0] residual_q32;
    logic [63:0] projection_codes;
    logic [4:0] projection_shift;
    logic write_valid, write_ready;
    logic [8:0] write_row;
    logic [231:0] write_data;
    logic norm_valid, norm_ready;
    logic [8:0] norm_row;
    logic [127:0] norm_data;

    logic writing = 1, read_valid = 0, request_ready;
    logic [8:0] read_row;
    logic response_valid, response_ready = 0;
    logic [231:0] response_data;
    logic ce_n, we_n;
    logic [8:0] address;
    logic [255:0] bank_in, bank_out;
    logic [708:0] vectors [576];
    string fixture;
    int cycle, written, normalized, accepted, simultaneous, write_stalls, norm_stalls;

`ifdef UNBUFFERED
    assign in_ready = write_ready && norm_ready;
    assign write_valid = in_valid;
    assign norm_valid = in_valid;
    assign write_row = in_row;
    assign norm_row = in_row;
    tri_oracle_attention_residual_precision add_projection (
        .residual_q32, .projection_codes, .projection_shift,
        .bypass_q26(write_data), .result_q13(norm_data)
    );
`else
    tri_oracle_attention_residual_store dut (.*);
`endif

    wire write_window = writing && cycle%7 >= 3;
    assign write_ready = write_window && request_ready;
    assign norm_ready = writing && cycle%11 >= 5;
    wire [8:0] request_row = writing ? write_row : read_row;
    tri_oracle_residual_bank_adapter memory_port (
        .clk, .rst_n, .lease_granted(1'b1), .req_valid(writing ? write_window && write_valid : read_valid),
        .req_ready(request_ready), .req_write(writing), .req_token(request_row[8]), .req_strip(request_row[7:0]),
        .req_data(write_data), .rsp_valid(response_valid), .rsp_ready(response_ready),
        .rsp_data(response_data), .bank_ce_n(ce_n), .bank_we_n(we_n),
        .bank_addr(address), .bank_d(bank_in), .bank_q(bank_out)
    );
    for (genvar bank = 0; bank < 4; bank++) begin : banks
        TS5N28HPCPSVTA512X64M4F memory (
            .CLK(clk), .CEB(ce_n), .WEB(we_n), .A(address),
            .D(bank_in[64*bank +: 64]), .Q(bank_out[64*bank +: 64])
        );
    end

    function automatic int address_at(input int index);
        return (151*index+7)%512;
    endfunction

    always @(posedge clk) if (rst_n) begin
        if (write_valid) begin
            if (written >= accepted || write_row !== 9'(address_at(written)) ||
                write_data !== vectors[address_at(written)][580:349])
                $fatal(1, "ATTENTION_RESIDUAL_STORE_WRITE index=%0d accepted=%0d", written, accepted);
            if (write_ready) written++;
            else write_stalls++;
        end
        if (norm_valid) begin
            if (normalized >= accepted || norm_row !== 9'(address_at(normalized)) ||
                norm_data !== vectors[address_at(normalized)][708:581])
                $fatal(1, "ATTENTION_RESIDUAL_STORE_NORMALIZE index=%0d accepted=%0d", normalized, accepted);
            if (norm_ready) normalized++;
            else norm_stalls++;
        end
        if (in_valid && in_ready) begin
            accepted++;
            if (write_valid && write_ready && norm_valid && norm_ready) simultaneous++;
        end
    end

    initial begin
        if (!$value$plusargs("VECTORS=%s", fixture)) $fatal(1, "Missing residual operand vectors");
        $readmemh(fixture, vectors);
        repeat (3) @(negedge clk);
        rst_n = 1;
        for (int i = 0; i < 512; i++) begin
            in_valid = 1;
            in_row = 9'(address_at(i));
            {projection_shift, projection_codes, residual_q32} = vectors[in_row][348:0];
            do @(posedge clk); while (in_ready !== 1'b1);
            @(negedge clk);
        end
        in_valid = 0;
        wait (written == 512 && normalized == 512);
        @(negedge clk);
        writing = 0;
        for (int row = 0; row < 512; row++) begin
            read_row = 9'(row);
            read_valid = 1;
            @(posedge clk);
            if (!request_ready || ce_n || !we_n)
                $fatal(1, "ATTENTION_RESIDUAL_STORE_READ_REQUEST row=%0d", row);
            @(negedge clk);
            read_valid = 0;
            if (!response_valid || response_data !== vectors[row][580:349])
                $fatal(1, "ATTENTION_RESIDUAL_STORE_READBACK row=%0d", row);
            response_ready = 1;
            @(negedge clk);
            response_ready = 0;
        end
        if (accepted != 512 || simultaneous == 0 || write_stalls == 0 || norm_stalls == 0)
            $fatal(1, "ATTENTION_RESIDUAL_STORE_CENSUS accepted=%0d simultaneous=%0d stalls=%0d,%0d",
                   accepted, simultaneous, write_stalls, norm_stalls);
        $display("ATTENTION_RESIDUAL_STORE_PASS rows=512 values=4096 macros=4 simultaneous=%0d stalls=%0d,%0d",
                 simultaneous, write_stalls, norm_stalls);
        $finish;
    end
    always @(negedge clk) cycle++;
    initial begin #100000; $fatal(1, "ATTENTION_RESIDUAL_STORE_TIMEOUT"); end
endmodule
