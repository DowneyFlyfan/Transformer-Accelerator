`timescale 1ns/1ps
module lease_tb;
    logic clk=0, rst_n=0;
    always #5 clk=~clk;
    logic compute_accepted=0, compute_done=0, activation_reloaded=0;
    logic native_request=0, native_start=0, native_end=0, native_write=0;
    logic probability_request=0, probability_release=0;
    logic [1:0] native_ce_n=2'b10, native_we_n=2'b11;
    logic [1:0] probability_ce_n=2'b11, probability_we_n=2'b11;
    logic [8:0] native_address=9'd270, probability_address=9'd303;
    logic [127:0] native_data=128'h320, probability_data=128'h572, bank_read;
    logic [1:0] bank_ce_n, bank_we_n;
    logic [8:0] bank_address;
    logic [127:0] bank_data, probability_read;
    logic probability_grant, owner_request, owner_start, owner_end, owner_write;
    logic owner_available, owns_bank, load_ready, compute_enabled, activation_reload_required;

    tri_oracle_wac_imem_owner owner (
        .clk,.rst_n,.compute_accepted,.compute_done,.activation_reloaded,
        .softmax_request(owner_request),.softmax_start(owner_start),.softmax_end(owner_end),
        .softmax_wrote_input(owner_write),.softmax_configure(owner_available),
        .softmax_owns_input(owns_bank),.load_ready,.compute_enabled,.activation_reload_required
    );
    tri_oracle_input_bank_lease dut (.*);
    for (genvar bank=0; bank<2; bank++) begin : inputs
        TS5N28HPCPSVTA512X64M4F mem (
            .CLK(clk), .CEB(bank_ce_n[bank]), .WEB(bank_we_n[bank]),
            .A(bank_address), .D(bank_data[64*bank+:64]), .Q(bank_read[64*bank+:64])
        );
    end

    task automatic require_activation_reload;
        #1;
        if (compute_enabled !== 0 || activation_reload_required !== 1 || owns_bank !== 0)
            $fatal(1,"LEASE_ACTIVATION_NOT_INVALIDATED");
        activation_reloaded=1;
        @(negedge clk);
        activation_reloaded=0;
        #1;
        if (compute_enabled !== 1) $fatal(1,"LEASE_RELOAD_NOT_ACCEPTED");
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n=1;
        require_activation_reload();
        @(negedge clk);
        compute_accepted=1;
        @(negedge clk);
        compute_accepted=0;
        probability_request=1;
        #1;
        if (probability_grant !== 0 || bank_address !== native_address)
            $fatal(1,"LEASE_INTERRUPTED_COMPUTE");
        @(negedge clk);
        compute_done=1;
        native_request=1;
        @(negedge clk);
        compute_done=0;
        native_start=1;
        #1;
        if (probability_grant !== 0) $fatal(1,"LEASE_IGNORED_NATIVE_PRIORITY");
        @(negedge clk);
        native_start=0;
        native_request=0;
        native_end=1;
        @(negedge clk);
        native_end=0;
        #1;
        if (probability_grant !== 1) $fatal(1,"LEASE_MISSING_GRANT");
        @(negedge clk);
        probability_request=0;
        probability_ce_n=0;
        probability_we_n=0;
        #1;
        if (bank_address !== probability_address || bank_data !== probability_data || owner_write !== 1)
            $fatal(1,"LEASE_WRITE_ROUTING");
        @(negedge clk);
        probability_we_n=2'b11;
        @(negedge clk);
        #1;
        if (probability_read !== probability_data) $fatal(1,"LEASE_READBACK");
        probability_ce_n=2'b11;
        probability_release=1;
        @(negedge clk);
        probability_release=0;
        if (probability_read !== 0 || bank_address !== native_address) $fatal(1,"LEASE_MISSING_RELEASE");
        require_activation_reload();
        @(negedge clk);
        probability_request=1;
        @(negedge clk);
        probability_request=0;
        probability_ce_n=0;
        repeat (2) @(negedge clk);
        probability_ce_n=2'b11;
        probability_release=1;
        @(negedge clk);
        probability_release=0;
        #1;
        if (activation_reload_required !== 0 || compute_enabled !== 1)
            $fatal(1,"LEASE_READ_ONLY_INVALIDATED_ACTIVATION");
        $display("GROUPED_INPUT_BANK_LEASE_PASS");
        $finish;
    end
endmodule
