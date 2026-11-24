`timescale 1ns/1ps
module tri_oracle_head_memory_census_stop;
    initial begin
        #4;
        $display("HEAD_CENSUS_ELABORATION_PASS clocks=0");
        $finish;
    end
endmodule
