`timescale 1ns/1ps
// Passive asynchronous reset observations, including post-edge reset changes.
// Decimal $time is expressed in this module's nanosecond units and does not
// depend on the global display formatter or its time-one scheduling order.
module tri_oracle_head_reset_probe (
    input logic rst_n, backend_rst_n
);
    bit observe_changes=0;
    initial begin
        #1;
        $display("TRACE_HEAD_RESET_INITIAL tick=%0d global=%0b backend=%0b",$time,rst_n,backend_rst_n);
        observe_changes=1;
    end
    always @(rst_n or backend_rst_n) begin
        if (observe_changes)
            $display("TRACE_HEAD_RESET tick=%0d global=%0b backend=%0b",$time,rst_n,backend_rst_n);
    end
endmodule
bind tri_oracle_trained_head_prediction_tb tri_oracle_head_reset_probe reset_observation(.*);
