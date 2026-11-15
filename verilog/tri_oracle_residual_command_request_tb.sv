`timescale 1ns/1ps
module tri_oracle_residual_command_request_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic command_valid = 0, command_ready;
    logic [2:0] command_opcode = 0;
    logic [31:0] command_tag = 32'h98765432;
    logic payload_valid = 0, payload_ready, payload_last = 0;
    logic [63:0] payload_data = 0;
    logic response_valid, response_ready = 0, response_error;
    logic [2:0] response_opcode;
    logic [31:0] response_tag, layer_command_tag;
    logic [7:0] layer_command_valid, layer_done_valid = 0, layer_done_ready, layer_done_error = 0;
    logic [1663:0] layer_command_payload;
    logic [255:0] layer_done_tag = 0;

    logic override_request = 0, request, granted, ff_ready, grouped_ready = 0;
    logic [3:0] probability_grant = '1;
    logic projection_ready = 1, writer_active = 0;
    int ff_starts = 0;
    logic ff_compute_cfg_valid, ff_writer_cfg_valid, ff_error, ff_out_ready, ff_abort;
    wire writer_ready = granted && !writer_active;
    wire [7:0] layer_command_ready = {grouped_ready, 6'b0, ff_ready};

    tri_oracle_chip_dispatch dispatch (.*);

    `ifdef CHECK_EXTERNAL_ONLY
    assign request = override_request;
    `else
    tri_oracle_residual_command_request request_control (
        .clk, .rst_n, .override_request,
        .command_valid(layer_command_valid[0]), .command_ready(ff_ready),
        .done_valid(layer_done_valid[0]), .done_ready(layer_done_ready[0]),
        .residual_request(request)
    );
    `endif

    tri_oracle_residual_bank_command lease_control (
        .clk, .rst_n, .residual_request(request), .probability_grant,
        .grouped_valid(1'b0), .grouped_core_ready(1'b1), .grouped_ready(), .grouped_core_valid(),
        .grouped_done_valid(1'b0), .grouped_done_ready(1'b0),
        .projection_cfg_valid(1'b0), .projection_cfg_ready(projection_ready),
        .residual_read_valid(1'b0), .residual_read_ready(1'b0), .residual_response_valid(1'b0),
        .writeback_cfg_valid(ff_writer_cfg_valid), .writeback_cfg_ready(writer_ready),
        .writeback_active(writer_active), .residual_granted(granted)
    );

    tri_oracle_linked_writeback_control writer (
        .clk, .rst_n, .command_valid(layer_command_valid[0]), .compute_ready(1'b1), .writer_ready,
        .compute_done(layer_done_valid[0]), .compute_error(1'b0), .packet_error(1'b0), .writer_raw_ready(1'b0),
        .command_ready(ff_ready), .compute_cfg_valid(ff_compute_cfg_valid),
        .writer_cfg_valid(ff_writer_cfg_valid), .done_error(ff_error), .out_ready(ff_out_ready),
        .writer_abort(ff_abort)
    );

    always @(posedge clk) begin
        if (rst_n && layer_command_valid[0] && ff_ready) begin
            if (!granted || !ff_compute_cfg_valid || !ff_writer_cfg_valid)
                $fatal(1, "FEEDFORWARD_LAUNCHED_WITHOUT_RESIDUAL_BANKS");
            ff_starts++;
        end
    end

    task automatic send(input logic [2:0] opcode, input int words);
        command_opcode = opcode;
        command_valid = 1;
        @(negedge clk);
        command_valid = 0;
        for (int word = 0; word < words; word++) begin
            if (request || granted || !payload_ready) $fatal(1, "LEASE_BEFORE_DESCRIPTOR_VALIDATION");
            payload_valid = 1;
            payload_data = 64'(word);
            payload_last = word == words - 1;
            @(negedge clk);
        end
        payload_valid = 0;
        payload_last = 0;
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1;
        send(3'd0, 1);
        if (!response_valid || !response_error || request || granted || ff_starts != 0)
            $fatal(1, "MALFORMED_FEEDFORWARD_CHANGED_OWNER");
        response_ready = 1;
        @(negedge clk);
        response_ready = 0;

        send(3'd7, 26);
        repeat (2) begin
            @(negedge clk);
            if (layer_command_valid !== 8'h80 || request || granted)
                $fatal(1, "GROUPED_COMMAND_REQUESTED_RESIDUAL_BANKS");
        end
        grouped_ready = 1;
        @(negedge clk);
        grouped_ready = 0;
        layer_done_tag[255:224] = command_tag;
        layer_done_valid[7] = 1;
        response_ready = 1;
        @(negedge clk);
        layer_done_valid[7] = 0;
        response_ready = 0;

        probability_grant = 4'b0111;
        send(3'd0, 15);
        repeat (3) begin
            @(negedge clk);
            if (!request || granted || ff_ready || layer_command_valid !== 8'h01)
                $fatal(1, "VALIDATED_FEEDFORWARD_DID_NOT_REQUEST_BANKS");
        end
        probability_grant = '1;
        repeat (3) @(negedge clk);
        if (ff_starts != 1 || !request || !granted || layer_command_valid != 0)
            $fatal(1, "FEEDFORWARD_LEASE_DID_NOT_SURVIVE_COMMAND_ACCEPTANCE");
        writer_active = 1;
        layer_done_valid[0] = 1;
        layer_done_tag[31:0] = command_tag;
        repeat (4) begin
            @(negedge clk);
            if (!request || !granted || !response_valid || response_error || response_tag != command_tag)
                $fatal(1, "FEEDFORWARD_LEASE_RELEASED_BEFORE_RESPONSE");
        end
        response_ready = 1;
        @(negedge clk);
        layer_done_valid[0] = 0;
        response_ready = 0;
        if (request || !granted) $fatal(1, "WRITER_DRAIN_NOT_PROTECTED");
        writer_active = 0;
        projection_ready = 0;
        repeat (2) @(negedge clk);
        if (request || !granted) $fatal(1, "PROJECTION_DRAIN_NOT_PROTECTED");
        projection_ready = 1;
        repeat (2) @(negedge clk);
        if (request || granted) $fatal(1, "FEEDFORWARD_LEASE_STUCK");

        override_request = 1;
        repeat (2) @(negedge clk);
        if (!granted || ff_starts != 1) $fatal(1, "EXPLICIT_LEASE_OVERRIDE_FAILED");
        override_request = 0;
        repeat (2) @(negedge clk);
        if (request || granted) $fatal(1, "OVERRIDE_LEASE_STUCK");
        $display("RESIDUAL_COMMAND_REQUEST_PASS feedforward=1 grouped=1 malformed=1 override=1");
        $finish;
    end

    initial begin
        #3000;
        $fatal(1, "RESIDUAL_COMMAND_REQUEST_TIMEOUT");
    end
endmodule
