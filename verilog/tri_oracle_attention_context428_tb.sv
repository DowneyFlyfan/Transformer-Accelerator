`timescale 1ns/1ps
module tri_oracle_attention_context428_tb;
    logic clk=0, rst_n=0, save_start=0, save_cancel=0, restore_start=0;
    logic save_valid=0, restore_ready=0;
    logic [4:0] layer;
    logic [9:0] save_origin;
    wire idle, save_ready, restore_valid, restore_last;
    wire [9:0] restore_origin;
    int saved=0, restored=0, write_words=0, read_words=0, stalls=0, macros=0;

    always #5 clk=~clk;
    tri_oracle_attention_context428 dut (.*);

    function automatic logic [9:0] expected(input int id, token);
        return 10'(id*137 + token*71 + (token/32)*13);
    endfunction

    task automatic save(input int id, count);
        @(negedge clk);
        layer=5'(id); save_start=1;
        @(posedge clk);
        if (!idle) $fatal(1,"CTX428_SAVE_BUSY");
        @(negedge clk);
        save_start=0;
        for (int index=0;index<count;index++) begin
            save_valid=1; save_origin=expected(id,index);
            do @(posedge clk); while (!save_ready);
            @(negedge clk);
            saved++;
        end
        save_valid=0;
        if (count!=576) begin
            save_cancel=1;
            @(negedge clk);
            save_cancel=0;
        end
        while (!idle) @(negedge clk);
    endtask

    task automatic restore(input int id);
        @(negedge clk);
        layer=5'(id); restore_start=1;
        @(posedge clk);
        if (!idle) $fatal(1,"CTX428_RESTORE_BUSY");
        @(negedge clk);
        restore_start=0;
        for (int index=0;index<576;index++) begin
            restore_ready=0;
            while (!restore_valid) @(negedge clk);
            if (index%29==0) repeat (3) begin
                @(posedge clk);
                if (!restore_valid || restore_origin!==expected(id,index) || restore_last!==(index==575))
                    $fatal(1,"CTX428_STALL layer=%0d index=%0d",id,index);
                stalls++;
                @(negedge clk);
            end
            restore_ready=1;
            @(posedge clk);
            if (!restore_valid || restore_origin!==expected(id,index) || restore_last!==(index==575))
                $fatal(1,"CTX428_ORIGIN layer=%0d index=%0d got=%0d want=%0d",
                       id,index,restore_origin,expected(id,index));
            @(negedge clk);
            restored++;
        end
        restore_ready=0;
        if (!idle || restore_valid) $fatal(1,"CTX428_RESTORE_TERMINAL");
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n=1;
        save(11,35);
        for (int id=0;id<22;id++) save(id,576);
        for (int index=0;index<22;index++) restore((index*7)%22);
        if (macros!=4 || write_words!=1985 || read_words!=1980 || saved!=12707 || restored!=12672)
            $fatal(1,"CTX428_INVENTORY saved=%0d restored=%0d writes=%0d reads=%0d",
                   saved,restored,write_words,read_words);
        $display("CTX428_PASS saved=%0d restored=%0d writes=%0d reads=%0d stalls=%0d",
                 saved,restored,write_words,read_words,stalls);
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1,"CTX428_TIMEOUT");
    end
endmodule

module tri_oracle_context428_memory_observer(input logic clk, ceb, web);
    initial $root.tri_oracle_attention_context428_tb.macros++;
    always @(posedge clk) if (!ceb) begin
        if (web) $root.tri_oracle_attention_context428_tb.read_words++;
        else $root.tri_oracle_attention_context428_tb.write_words++;
    end
endmodule

bind TS5N28HPCPSVTA512X64M4F tri_oracle_context428_memory_observer context428_observer (
    .clk(CLK), .ceb(CEB), .web(WEB)
);
