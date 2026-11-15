`timescale 1ns/1ps

module control_tb;
    logic clk=0, rst_n=0;
    logic command_valid=0, compute_ready=0, writer_ready=0;
    logic compute_done=0, compute_error=0, packet_error=0, writer_raw_ready=0;
    wire command_ready, compute_cfg_valid, writer_cfg_valid;
    wire done_error, out_ready, writer_abort;

    always #5 clk = ~clk;

    tri_oracle_linked_writeback_control dut (.*);

    task automatic check_outputs(input bit sticky, input int serial);
        if (command_ready !== (compute_ready && writer_ready) ||
            compute_cfg_valid !== (command_valid && writer_ready) ||
            writer_cfg_valid !== (command_valid && compute_ready) ||
            done_error !== (compute_error || sticky || packet_error) ||
            out_ready !== (writer_raw_ready || sticky) ||
            writer_abort !== (compute_done && compute_error))
            $fatal(1,"WRITEBACK_CONTROL_MISMATCH serial=%0d sticky=%0b",serial,sticky);
    endtask

    initial begin
        for (int sticky=0;sticky<2;sticky++) begin
            for (int sample=0;sample<128;sample++) begin
                @(negedge clk); rst_n=0; command_valid=0; packet_error=0;
                compute_ready=0; writer_ready=0;
                @(negedge clk); rst_n=1; packet_error=1'(sticky);
                @(negedge clk);
                {command_valid,compute_ready,writer_ready,compute_done,compute_error,
                 packet_error,writer_raw_ready} = 7'(sample);
                #1; check_outputs(1'(sticky),2*sample);
                @(posedge clk); #1;
                check_outputs(command_valid && compute_ready && writer_ready ? 0 : sticky != 0 || packet_error,
                              2*sample+1);
            end
        end
        @(negedge clk);
        {command_valid,compute_ready,writer_ready,compute_done,compute_error,
         packet_error,writer_raw_ready} = 7'b0000010;
        @(posedge clk); #1;
        packet_error=0;
        #1; check_outputs(1'b1,512);
        #1; rst_n=0;
        #1; check_outputs(1'b0,513);
        $display("WRITEBACK_CONTROL_PASS transitions=256 observations=514 async_reset=1");
        $finish;
    end
    initial begin #100000; $fatal(1,"WRITEBACK_CONTROL_TIMEOUT"); end
endmodule
