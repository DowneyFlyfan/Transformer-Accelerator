`timescale 1ns/1ps
module tri_oracle_leased_writeback_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic acquire_request = 0, release_request = 0;
    logic acquire, release_lease, leased = 0;
    logic [1:0] grant, owned, load_ready, compute_enabled, reload_required;
    logic [1:0] compute_accepted = 0, compute_done = 0, activation_reloaded = 0;
    logic [1:0] native_request = 0;

    logic load_valid = 0;
    logic [8:0] load_row;
    logic req_ready, bank_ce_n, bank_we_n;
    logic [8:0] bank_addr;
    logic [255:0] bank_d, bank_q;
    logic bypass_valid, bypass_ready;
    logic [231:0] bypass_data;
    logic in_valid = 0, in_ready, in_last;
    logic [31:0] in_tag = 32'habcd0010;
    logic [3:0] in_token;
    logic [15:0] in_start;
    logic [7:0] in_count;
    logic [5119:0] in_data;
    logic [4:0] down_shift = 5'd11;
    logic out_valid, out_ready = 0, out_last;
    logic [31:0] out_tag;
    logic [3:0] out_token;
    logic [15:0] out_start;
    logic [3:0] out_count;
    logic [127:0] out_data;

    logic [620:0] trained [512];
    string fixture;
    int reads = 0, strips = 0, packets = 0, stalls = 0;

    // Acquire both owners together. Keep them until the final response
    // retires so neither native path can replace the held bank data.
    assign acquire = acquire_request && (&grant);
    assign release_lease = release_request && !in_valid && !bypass_valid && !load_valid;
    always @(posedge clk) begin
        if (acquire) leased <= 1;
        else if (release_lease) leased <= 0;
    end

    for (genvar core = 0; core < 2; core++) begin : cores
        logic owner_available, owner_request, owner_start, owner_end, owner_write;
        logic [1:0] ce_n, we_n;
        logic [8:0] address;
        logic [127:0] write_data, read_data;

        tri_oracle_wac_imem_owner owner (
            .clk, .rst_n, .compute_accepted(compute_accepted[core]), .compute_done(compute_done[core]),
            .softmax_request(owner_request || acquire_request), .softmax_start(owner_start),
            .softmax_end(owner_end), .softmax_wrote_input(owner_write),
            .activation_reloaded(activation_reloaded[core]), .load_ready(load_ready[core]),
            .compute_enabled(compute_enabled[core]), .softmax_configure(owner_available),
            .softmax_owns_input(owned[core]), .activation_reload_required(reload_required[core])
        );
        tri_oracle_input_bank_lease lease (
            .clk, .rst_n, .owner_available, .native_request(native_request[core]),
            .native_start(1'b0), .native_end(1'b0), .native_write(1'b0),
            .native_ce_n(2'b11), .native_we_n(2'b11), .native_address(9'd0), .native_data(128'd0),
            .bank_read(read_data), .probability_request(acquire), .probability_release(release_lease),
            .probability_ce_n({2{bank_ce_n}}), .probability_we_n({2{bank_we_n}}),
            .probability_address(bank_addr), .probability_data(bank_d[128*core +: 128]),
            .probability_grant(grant[core]), .probability_read(bank_q[128*core +: 128]),
            .owner_request, .owner_start, .owner_end, .owner_write, .bank_ce_n(ce_n),
            .bank_we_n(we_n), .bank_address(address), .bank_data(write_data)
        );
        for (genvar bank = 0; bank < 2; bank++) begin : banks
            TS5N28HPCPSVTA512X64M4F input_bank (
                .CLK(clk), .CEB(ce_n[bank]), .WEB(we_n[bank]), .A(address),
                .D(write_data[64*bank +: 64]), .Q(read_data[64*bank +: 64])
            );
        end
    end

    tri_oracle_residual_bank_adapter residual_memory (
        .clk, .rst_n, .lease_granted(leased), .req_valid(load_valid || in_valid),
        .req_ready, .req_write(load_valid), .req_token(load_valid ? load_row[8] : in_token[0]),
        .req_strip(load_valid ? load_row[7:0] : out_start[10:3]), .req_data(trained[load_row][231:0]),
        .rsp_valid(bypass_valid), .rsp_ready(bypass_ready), .rsp_data(bypass_data),
        .bank_ce_n, .bank_we_n, .bank_addr, .bank_d, .bank_q
    );
    tri_oracle_decoder_writeback_bridge writeback (.*);

    always @(posedge clk) if (rst_n) begin
        if (owned !== {2{leased}} || (leased && (load_ready !== 0 || compute_enabled !== 0)))
            $fatal(1, "LEASED_WRITEBACK_OWNERSHIP owned=%b leased=%b", owned, leased);
        if (!bank_ce_n && bank_we_n) reads++;
        if (out_valid && !out_ready) stalls++;
        if (out_valid && out_ready) strips++;
        if (in_valid && in_ready) packets++;
    end

    task automatic send_tile(input int token, start, count, input bit last);
        int row;
        logic [184:0] expected;
        @(negedge clk);
        in_token = 4'(token);
        in_start = 16'(start);
        in_count = 8'(count);
        in_last = last;
        in_data = '0;
        for (int k = 0; k < count; k++) begin
            row = token * 256 + (start + k) / 8;
            in_data[32*k +: 32] = trained[row][232+32*(k%8) +: 32];
        end
        in_valid = 1;
        for (int offset = 0; offset < count; offset += 8) begin
            row = token * 256 + (start + offset) / 8;
            expected = {in_tag, in_token, 16'(start+offset), 4'd8,
                        1'(last && offset+8==count), trained[row][620:493]};
            out_ready = 0;
            @(posedge clk);
            if (out_valid || !req_ready || bank_ce_n || !bank_we_n)
                $fatal(1, "LEASED_WRITEBACK_READ row=%0d", row);
            @(negedge clk);
            release_request = 1;
            repeat (2) begin
                @(posedge clk);
                if (!out_valid || in_ready || bypass_ready || !bank_ce_n ||
                    {out_tag, out_token, out_start, out_count, out_last, out_data} !== expected)
                    $fatal(1, "LEASED_WRITEBACK_DATA row=%0d actual=%h expected=%h",
                           row, out_data, trained[row][620:493]);
            end
            @(negedge clk);
            release_request = 0;
            out_ready = 1;
            @(posedge clk);
            if (!out_valid || !bypass_ready || in_ready !== (offset+8==count) ||
                {out_tag, out_token, out_start, out_count, out_last, out_data} !== expected)
                $fatal(1, "LEASED_WRITEBACK_HANDSHAKE row=%0d", row);
            @(negedge clk);
        end
        in_valid = 0;
        out_ready = 0;
    endtask

    initial begin
        if (!$value$plusargs("TRAINED=%s", fixture)) $fatal(1, "Missing trained vectors");
        $readmemh(fixture, trained);
        for (int row = 0; row < 512; row++)
            if (trained[row][492:488] !== down_shift) $fatal(1, "Unknown shift for row %0d", row);
        load_row = 0;
        repeat (3) @(negedge clk);
        rst_n = 1;
        activation_reloaded = 2'b11;
        @(negedge clk);
        activation_reloaded = 0;
        if (compute_enabled !== 2'b11) $fatal(1, "Initial activation reload failed");
        compute_accepted = 2'b01;
        @(negedge clk);
        compute_accepted = 0;
        acquire_request = 1;
        repeat (2) begin
            @(posedge clk);
            if (acquire || owned !== 0 || compute_enabled !== 0)
                $fatal(1, "Lease acquired with matrix compute outstanding");
        end
        @(negedge clk);
        native_request = 2'b10;
        compute_done = 2'b01;
        @(negedge clk);
        compute_done = 0;
        @(posedge clk);
        if (acquire || owned !== 0) $fatal(1, "Lease acquired with competing bank request");
        @(negedge clk);
        native_request = 0;
        @(negedge clk);
        if (!leased || owned !== 2'b11) $fatal(1, "Dual bank grant missing");
        acquire_request = 0;

        for (int row = 0; row < 512; row++) begin
            load_valid = 1;
            load_row = 9'(row);
            @(posedge clk);
            if (!req_ready || bank_ce_n || bank_we_n) $fatal(1, "Load not accepted row=%0d", row);
            @(negedge clk);
        end
        load_valid = 0;
        for (int start = 0; start < 2048; start += 160)
            for (int token = 0; token < 2; token++)
                send_tile(token, start, start < 1920 ? 160 : 128, start == 1920 && token == 1);

        release_request = 1;
        @(negedge clk);
        release_request = 0;
        if (leased || owned !== 0 || load_ready !== 2'b11 ||
            reload_required !== 2'b11 || compute_enabled !== 0)
            $fatal(1, "Matrix compute allowed before restoring activations");
        activation_reloaded = 2'b01;
        @(negedge clk);
        if (compute_enabled !== 2'b01) $fatal(1, "Reload affected the wrong owner");
        activation_reloaded = 2'b10;
        @(negedge clk);
        if (compute_enabled !== 2'b11 || reads != 512 || strips != 512 || packets != 26 || stalls != 1024)
            $fatal(1, "LEASED_WRITEBACK_CENSUS reads=%0d strips=%0d packets=%0d stalls=%0d",
                   reads, strips, packets, stalls);
        $display("LEASED_WRITEBACK_PASS reads=%0d strips=%0d values=%0d packets=%0d stalls=%0d",
                 reads, strips, strips*8, packets, stalls);
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "LEASED_WRITEBACK_TIMEOUT");
    end
endmodule
