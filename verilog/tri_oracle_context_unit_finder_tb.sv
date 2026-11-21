`timescale 1ns/1ps
module tri_oracle_context_unit_finder_tb #(parameter int FRAMES=34);
    logic clk=0,rst_n=0; always #5 clk=~clk;
    logic row_valid=0,row_ready,out_valid,out_ready=0,out_error;
    logic [2047:0] row_data;
    logic signed [7:0] row_value_exponent;
    logic [5:0] row_index;
    logic [17:0] zero_exponents={9'(-5),9'(3)},out_exponents;
    logic [2055:0] operands[FRAMES*64];
    logic [17:0] expected[FRAMES];
    string inputs,outputs;
    int checked=0,stalls=0;
    tri_oracle_context_unit_finder dut(.*);
    task automatic offer(input int frame,row);
        {row_value_exponent,row_data}=operands[frame*64+row];
        row_index=6'(row);row_valid=1;
        do @(posedge clk); while(!row_ready);
        @(negedge clk);row_valid=0;
    endtask
    initial begin
        if(!$value$plusargs("OPERANDS=%s",inputs)||!$value$plusargs("EXPECTED=%s",outputs))$fatal(1,"UNIT_FIXTURE_ARGS");
        $readmemh(inputs,operands);$readmemh(outputs,expected);
        repeat(2) @(negedge clk);rst_n=1;
        // Duplicate rows must invalidate the entire reduction.
        offer(0,63);offer(0,63);
        if(!out_valid||!out_error)$fatal(1,"UNIT_DUPLICATE_ACCEPTED");
        out_ready=1;@(negedge clk);out_ready=0;
        row_valid=1;row_index=7;row_value_exponent=0;row_data='0;
        row_data[31:0]=32'h7fffffff;
        repeat(3) @(negedge clk);
        rst_n=0;row_valid=0;repeat(2) @(negedge clk);rst_n=1;
        for(int frame=0;frame<FRAMES;frame++)begin
            zero_exponents={9'(-5),9'(3)};
            for(int i=0;i<64;i++)begin
                offer(frame,(17*i+63)%64);
                if(i==0)zero_exponents='0;
                if(out_valid!==(i==63))$fatal(1,"UNIT_PREMATURE_RESULT frame=%0d i=%0d",frame,i);
            end
            zero_exponents=~zero_exponents;
            repeat(3)begin
                @(posedge clk);
                if(!out_valid||out_error||row_ready||out_exponents!==expected[frame])
                    $fatal(1,"UNIT_RESULT frame=%0d got=%h expected=%h",frame,out_exponents,expected[frame]);
                stalls++;@(negedge clk);
            end
            checked++;
            out_ready=1;@(negedge clk);out_ready=0;
            if(out_valid||row_ready)$fatal(1,"UNIT_STALE_RESULT");
        end
        $display("CONTEXT_UNIT_FINDER_PASS frames=%0d head_rows=%0d actual_queries=0 stalls=%0d",checked,checked*64,stalls);
        $finish;
    end
    initial begin #3000000;$fatal(1,"UNIT_TIMEOUT");end
endmodule
