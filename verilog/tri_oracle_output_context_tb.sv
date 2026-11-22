`timescale 1ns/1ps
module tri_oracle_output_context_tb;
    import tri_oracle_wac_softmax_types::*;
    logic clk=0,rst_n=0,load_valid=0,cmd_valid=0,cmd_accumulate=0;
    logic [1:0] load_core=0,load_kind=0,cmd_reduce=0;
    logic [9:0] load_addr=0,cmd_activation=0;
    logic [2047:0] load_data=0;
    logic [31:0] load_row_enable='1;
    logic [4:0] cmd_weight=0,cmd_mask=0;
    logic [3:0] cmd_output=0,out_output;
    logic [2:0] core_score_select=0;
    logic activation_reloaded=0,load_error,cmd_ready,out_valid,out_ready=0;
    logic [1023:0] out_data,contexts[0:7];
    request_t softmax_request='0;
    response_t softmax_response;
    int array_issues=0,array_before=0,verified=0;
    string fixture;
    always #5 clk=~clk;
    tri_oracle_compute_cluster dut (
        .clk,.rst_n,.load_valid,.load_core,.load_kind,.load_addr,.load_data,.load_row_enable,.load_error,
        .cmd_valid,.cmd_ready,.cmd_weight,.cmd_mask,.cmd_activation,.cmd_output,.cmd_accumulate,.cmd_reduce,
        .out_valid,.out_ready,.out_output,.out_data,.activation_reloaded,.core_score_select,
        .merge_sign_data('0),.merge_sign_control('0),.merge_sign_counts(),.merge_table_request('0),.merge_table_word(),
        .token_size_bank_command('0),.token_size_bank_result(),.softmax_request,.softmax_response,
        .merge_range_command('0),.merge_range_result(),.global_merge_word('0),.global_sign_counts('0),
        .strip_rst_n(rst_n),.strip_request('0),.strip_response(),.head_request('0),.head_response()
    );
    always @(posedge clk)if(rst_n)for(int core=0;core<4;core++)
        if(dut.implementation.core_issue[core] && dut.implementation.ready[core])array_issues++;
    function automatic int dot(input int core,row);
        int total=0;
        for(int lane=0;lane<8;lane++)total+=(core+lane-3)*(row-lane+2);
        return total;
    endfunction
    task automatic load(input int core,kind,address,input logic[2047:0] data,input bit expect_error=0);
        @(negedge clk);load_valid=1;load_core=2'(core);load_kind=2'(kind);load_addr=10'(address);load_data=data;
        @(posedge clk);#2;
        if(load_error!==expect_error)$fatal(1,"CONTEXT_WRITE_REJECTED core=%0d kind=%0d addr=%0d got=%0b expected=%0b",core,kind,address,load_error,expect_error);
        @(negedge clk);load_valid=0;
    endtask
    task automatic operands;
        logic[2047:0] data;
        for(int core=0;core<4;core++)begin
            data=0;
            for(int row=0;row<32;row++)for(int lane=0;lane<8;lane++)data[(row*8+lane)*8+:8]=8'(row-lane+2);
            load(core,0,0,data);
            data=0;data[255:0]='1;load(core,2,0,data);
            data=0;for(int lane=0;lane<8;lane++)data[lane*8+:8]=8'(core+lane-3);
            load(core,1,0,data);
        end
        core_score_select=0;
        activation_reloaded=1;@(negedge clk);activation_reloaded=0;
    endtask
    task automatic issue(input int core,slot,input bit context_read=0,accumulate=0);
        @(negedge clk);cmd_valid=1;core_score_select=3'(4+core);cmd_output=4'(slot);
        cmd_reduce=context_read?3:0;cmd_accumulate=accumulate;
        do @(posedge clk);while(!cmd_ready);
        @(negedge clk);cmd_valid=0;core_score_select=3'b111;cmd_reduce=0;
    endtask
    task automatic receive(input int slot,input logic[1023:0] expected);
        while(!out_valid)@(negedge clk);
        if(out_output!==4'(slot) || out_data!==expected)
            $fatal(1,"CONTEXT_DATA_MISMATCH slot=%0d got=%0256h expected=%0256h",slot,out_data,expected);
        $display("CONTEXT_RESULT slot=%0d values=%0256h",slot,out_data);verified+=32;
        out_ready=1;@(negedge clk);out_ready=0;
    endtask
    task automatic issue_group(input int slot,input bit stored_read=0);
        @(negedge clk);cmd_valid=1;core_score_select=0;cmd_output=4'(slot);
        cmd_reduce=stored_read?3:0;cmd_accumulate=0;
        do @(posedge clk);while(!cmd_ready);
        @(negedge clk);cmd_valid=0;core_score_select=7;cmd_reduce=0;
    endtask
    task automatic refuse_group_read(input int slot);
        @(negedge clk);cmd_valid=1;core_score_select=0;cmd_output=4'(slot);cmd_reduce=3;
        repeat(3)begin #1;if(cmd_ready)$fatal(1,"CONTEXT_MIXED_OWNER_SUM_ACCEPTED");@(negedge clk);end
        cmd_valid=0;core_score_select=7;cmd_reduce=0;
    endtask
    task automatic refuse_command(input int core,slot,input bit context_read=0);
        @(negedge clk);cmd_valid=1;core_score_select=3'(4+core);cmd_output=4'(slot);cmd_reduce=context_read?3:0;
        repeat(3)begin #1;if(cmd_ready)$fatal(1,"CONTEXT_UNRESERVED_OR_OWNED_COMMAND_ACCEPTED");@(negedge clk);end
        cmd_valid=0;core_score_select=7;cmd_reduce=0;
    endtask
    task automatic context_write(input int core,half,input logic[1023:0] data);
        load(core,3,14+half,{1024'hdeadbeef,data});
    endtask
    task automatic normalize_begin;
        @(negedge clk);softmax_request='0;softmax_request.owner=0;
        softmax_request.cfg_valid=1;softmax_request.cfg_length=2;
        do @(posedge clk);while(!softmax_response.cfg_ready);
        @(negedge clk);softmax_request.cfg_valid=0;
        for(int key=0;key<2;key++)begin
            softmax_request.in_valid=1;softmax_request.score=0;softmax_request.size=1;
            do @(posedge clk);while(!softmax_response.in_ready);
            @(negedge clk);softmax_request.in_valid=0;
        end
    endtask
    task automatic normalize_end;
        for(int key=0;key<2;key++)begin
            while(!softmax_response.out_valid)@(negedge clk);
            if(softmax_response.probability!==16'd32768 || softmax_response.out_last!==(key==1) || softmax_response.cfg_error)
                $fatal(1,"CONTEXT_NORMALIZER_CORRUPTED");
            softmax_request.out_ready=1;@(negedge clk);softmax_request.out_ready=0;
        end
        softmax_request='0;
    endtask
    initial begin : test
        logic[1023:0] expected,held;
        if(!$value$plusargs("FIXTURE=%s",fixture))$fatal(1,"CONTEXT_FIXTURE_MISSING");
        $readmemh(fixture,contexts);
        repeat(2)@(negedge clk);rst_n=1;operands();
        // Prime the exact slot in the core's recent-write forwarding cache.
        for(int core=0;core<4;core++)begin
            for(int row=0;row<32;row++)expected[row*32+:32]=32'(dot(core,row));
            issue(core,14);receive(14,expected);
        end
        array_before=array_issues;
        for(int core=0;core<4;core++)for(int half=0;half<2;half++)context_write(core,half,contexts[core*2+half]);
        for(int core=0;core<4;core++)for(int half=0;half<2;half++)begin
            issue(core,14+half,1);receive(14+half,contexts[core*2+half]);
            refuse_command(core,14+half);
        end
        if(array_issues!=array_before)$fatal(1,"CONTEXT_READ_USED_ARRAY");
        refuse_group_read(14);refuse_group_read(15);
        $display("CONTEXT_ALL_CORES_PASS words=8 values=256");

        for(int row=0;row<32;row++)expected[row*32+:32]=32'(dot(0,row)+dot(1,row)+dot(2,row)+dot(3,row));
        issue_group(0);receive(0,expected);array_before=array_issues;
        issue_group(0,1);receive(0,expected);
        for(int row=0;row<32;row++)expected[row*32+:32]=32'(dot(2,row));
        issue(2,0,1);receive(0,expected);
        if(array_issues!=array_before)$fatal(1,"CONTEXT_STORED_SCORE_USED_ARRAY");
        $display("CONTEXT_STORED_SCORE_SUM_PASS values=64");

        issue(0,14,1);
        while(!out_valid)@(negedge clk);
        held=out_data;
        load(0,3,14,'1,1);load(0,3,16,0,1);
        repeat(9)begin
            @(negedge clk);
            core_score_select=3'(int'(core_score_select)+1);
            if(!out_valid || out_output!==14 || out_data!==held)$fatal(1,"CONTEXT_HELD_RESPONSE_CHANGED");
        end
        receive(14,contexts[0]);issue(0,14,1);receive(14,contexts[0]);
        $display("CONTEXT_HELD_AND_RELEASE_FENCE_PASS");

        // Existing matrix commands still use unreserved output slots.
        issue(2,0);load(2,3,14,0,1);
        for(int row=0;row<32;row++)expected[row*32+:32]=32'(dot(2,row));
        receive(0,expected);issue(2,14,1);receive(14,contexts[4]);
        for(int address=0;address<4;address++)load(1,3,address==0?0:address==1?13:address==2?18:1023,'1,1);
        refuse_command(1,13,1);
        issue(1,14,1);receive(14,contexts[2]);
        $display("CONTEXT_BUSY_INVALID_ADDRESS_PASS");

        // The existing local normalizer owns input memory during this access;
        // context state lives only in the independent output memory macros.
        normalize_begin();context_write(0,0,contexts[0]);
        issue(0,14,1);receive(14,contexts[0]);normalize_end();
        $display("CONTEXT_NORMALIZER_INDEPENDENCE_PASS");
        operands();
        for(int core=0;core<4;core++)begin
            load(core,3,16,0);load(core,3,17,0);
            refuse_command(core,14,1);refuse_command(core,15,1);
            for(int row=0;row<32;row++)expected[row*32+:32]=contexts[core*2][row*32+:32]+32'(dot(core,row));
            issue(core,14,0,1);receive(14,expected);
        end
        $display("CONTEXT_RELEASE_AND_ACCUMULATE_PASS values=128");

        context_write(0,0,contexts[0]);
        rst_n=0;repeat(2)@(negedge clk);rst_n=1;
        refuse_command(0,14,1);operands();
        for(int row=0;row<32;row++)expected[row*32+:32]=32'(dot(0,row));
        issue(0,14);receive(14,expected);
        context_write(0,0,contexts[0]);issue(0,14,1);receive(14,contexts[0]);
        $display("CONTEXT_RESET_RECOVERY_PASS");
        $display("CONTEXT_STORAGE_PASS verified_values=%0d array_issues=%0d",verified,array_issues);
        $finish;
    end
    initial begin #200000;$fatal(1,"CONTEXT_STORAGE_WATCHDOG");end
endmodule
module tri_oracle_context_storage_array_probe;
    initial $display("CONTEXT_STORAGE_ARRAY %m");
endmodule
bind tri_oracle_pe_array tri_oracle_context_storage_array_probe context_array_witness();
module tri_oracle_context_storage_memory_probe;
    initial $display("CONTEXT_STORAGE_MEMORY %m");
endmodule
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_context_storage_memory_probe context_memory_witness();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_context_storage_memory_probe context_memory_witness();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_context_storage_memory_probe context_memory_witness();
