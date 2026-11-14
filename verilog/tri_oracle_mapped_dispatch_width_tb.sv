`timescale 1ns/1ps
module dispatch_width_tb;
    bit clk=0, rst_n=0, command_valid=0, payload_valid=0, payload_last=0;
    bit response_ready=0;
    logic [2:0] command_opcode=0, response_opcode;
    logic [31:0] command_tag=0,response_tag,layer_command_tag;
    logic [63:0] payload_data=0;
    logic [7:0] layer_command_valid,layer_done_ready;
    logic [1663:0] layer_command_payload;
    logic command_ready,payload_ready,response_valid,response_error;
    bit [7:0] layer_done_valid=0;
    always #5 clk=~clk;
    tri_oracle_chip_dispatch dut(.clk(clk),.rst_n(rst_n),.command_valid(command_valid),
        .command_ready(command_ready),.command_opcode(command_opcode),.command_tag(command_tag),
        .payload_valid(payload_valid),.payload_ready(payload_ready),.payload_data(payload_data),.payload_last(payload_last),
        .response_valid(response_valid),.response_ready(response_ready),.response_error(response_error),
        .response_opcode(response_opcode),.response_tag(response_tag),.layer_command_valid(layer_command_valid),
        .layer_command_ready(8'hff),.layer_command_tag(layer_command_tag),.layer_command_payload(layer_command_payload),
        .layer_done_valid(layer_done_valid),.layer_done_ready(layer_done_ready),.layer_done_error(8'h00),
        .layer_done_tag({8{command_tag}}));

    task automatic send(input logic [2:0] op,input int words,input logic [1663:0] payload);
        @(negedge clk);
        command_opcode=op;
        command_tag=32'h39300000+32'(op);
        command_valid=1;
        @(posedge clk);
        if(command_ready!==1) $fatal(1,"DISPATCH_NOT_READY");
        @(negedge clk);
        command_valid=0;
        for(int word=0;word<words;word++) begin
            payload_valid=1;
            payload_data=payload[64*word+:64];
            payload_last=word==words-1;
            @(posedge clk);
            if(payload_ready!==1) $fatal(1,"DISPATCH_PAYLOAD_NOT_READY");
            @(negedge clk);
        end
        payload_valid=0;
        payload_last=0;
        @(posedge clk);
        if (layer_command_valid !== (8'd1 << op) || layer_command_tag !== command_tag)
            $fatal(1,"DISPATCH_WRONG_ISSUE");
    endtask

    task automatic finish_command(input logic [2:0] op);
        @(negedge clk);
        layer_done_valid=8'd1<<op;
        response_ready=1;
        @(posedge clk);
        if ({response_valid,response_error,response_opcode,response_tag} !== {1'b1,1'b0,op,command_tag})
            $fatal(1,"DISPATCH_WRONG_RESPONSE");
        @(negedge clk);
        layer_done_valid=0;
        response_ready=0;
    endtask

    initial begin
        logic [959:0] ff, next_ff;
        logic [1663:0] grouped;
        for (int word=0;word<15;word++) ff[64*word+:64]=64'h5aa5111144443333 ^ (64'(word)<<29);
        grouped='1;
        repeat(4) @(negedge clk);
        rst_n=1;
        send(0,15,1664'(ff));
        if (layer_command_payload[959:0]!==ff || layer_command_payload===ff ||
            !$isunknown(layer_command_payload[1663:960]))
            $fatal(1,"DISPATCH_RESET_WIDTH_CAUSE_NOT_REPRODUCED");
        finish_command(0);
        send(7,26,grouped);
        if (layer_command_payload!==grouped) $fatal(1,"DISPATCH_GROUPED_PAYLOAD");
        finish_command(7);
        next_ff=~ff;
        send(0,15,1664'(next_ff));
        if (layer_command_payload[959:0]!==next_ff || layer_command_payload[1663:960]!==grouped[1663:960] ||
            layer_command_payload===1664'(next_ff))
            $fatal(1,"DISPATCH_STALE_UPPER_BITS_CAUSE_NOT_REPRODUCED");
        finish_command(0);
        $display("FEEDFORWARD_DESCRIPTOR_WIDTH_REPRODUCED reset_upper_unknown=1 stale_upper_held=1 verified_bits=960");
        $finish;
    end
endmodule
