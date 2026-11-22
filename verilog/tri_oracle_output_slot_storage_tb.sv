`timescale 1ns/1ps
module tri_oracle_output_slot_tb;
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
    function automatic logic[1023:0] lease_pattern(input int core,slot);
        logic[1023:0] word_data;
        for(int lane=0;lane<32;lane++)word_data[lane*32+:32]=32'(core*100000+slot*1000+lane*3-18000);
        return word_data;
    endfunction
    function automatic logic[1023:0] packed_scores(input int word_index);
        logic[1023:0] word_data;
        int key,value;
        for(int lane=0;lane<64;lane++)begin
            key=word_index*64+lane;
            value=key%7==0 ? -32768 : key%11==0 ? 32767 : key*17-8192;
            word_data[lane*16+:16]=16'(value);
        end
        return word_data;
    endfunction
    task automatic all_output_slots;
        logic[1023:0] expected,held;
        int old_verified,old_arrays;
        old_verified=verified;old_arrays=array_issues;
        for(int lane=0;lane<32;lane++)expected[lane*32+:32]=32'(dot(0,lane));
        issue(0,13);receive(13,expected);
        for(int core=0;core<4;core++)for(int slot=0;slot<16;slot++)
            load(core,3,slot,{1024'h123456789abcdef,lease_pattern(core,slot)});
        for(int core=0;core<4;core++)for(int slot=0;slot<16;slot++)begin
            issue(core,slot,1);receive(slot,lease_pattern(core,slot));
            refuse_command(core,slot);
        end
        for(int slot=0;slot<16;slot++)refuse_group_read(slot);
        if(array_issues!=old_arrays+1)$fatal(1,"SLOT_READ_EXECUTED_ARRAY");
        issue(0,1,1);receive(1,lease_pattern(0,1));
        load(0,3,1,{1024'b0,~lease_pattern(0,1)});
        issue(0,1,1);receive(1,~lease_pattern(0,1));
        $display("SLOT_ALL_SIXTEEN_OWNERSHIP_PASS words=64");
        $display("SLOT_PACK_BEGIN words=16 scores=1024");
        for(int word_index=0;word_index<16;word_index++)begin
            load(word_index%4,3,1+word_index/4,{1024'hf00d,packed_scores(word_index)});
            $display("SLOT_PACK_WORD index=%0d core=%0d slot=%0d data=%0256h",word_index,word_index%4,1+word_index/4,packed_scores(word_index));
        end
        for(int word_index=0;word_index<16;word_index++)begin
            issue(word_index%4,1+word_index/4,1);receive(1+word_index/4,packed_scores(word_index));
        end
        $display("SLOT_PACK_END words=16 scores=1024");
        issue(0,1,1);while(!out_valid)@(negedge clk);held=out_data;
        load(0,3,2,'1,1);
        repeat(9)begin @(negedge clk);core_score_select=3'(int'(core_score_select)+1);
            if(!out_valid || out_output!==1 || out_data!==held)$fatal(1,"SLOT_HELD_RESPONSE_CHANGED");end
        receive(1,packed_scores(0));issue(0,2,1);receive(2,packed_scores(4));
        normalize_begin();load(0,3,1,{1024'b0,packed_scores(0)});
        issue(0,1,1);receive(1,packed_scores(0));normalize_end();operands();
        for(int core=0;core<4;core++)for(int slot=0;slot<16;slot++)begin
            load(core,3,32+slot,0);refuse_command(core,slot,1);
            if(slot<15)begin
                expected=slot+1>=1 && slot+1<=4 ? packed_scores(slot*4+core) : lease_pattern(core,slot+1);
                issue(core,slot+1,1);receive(slot+1,expected);
            end
        end
        for(int lane=0;lane<32;lane++)expected[lane*32+:32]=32'(dot(3,lane));
        issue(3,1);receive(1,expected);
        for(int lane=0;lane<32;lane++)expected[lane*32+:32]=32'(dot(2,lane));
        issue(2,4);receive(4,expected);
        load(2,3,4,{1024'b0,packed_scores(3)});
        rst_n=0;repeat(2)@(negedge clk);rst_n=1;refuse_command(2,4,1);operands();
        issue(2,4);receive(4,expected);
        if(verified-old_verified!=4768 || array_issues-old_arrays!=4)$fatal(1,"SLOT_DIRECTED_COVERAGE_COUNT");
        $display("SLOT_GENERIC_RELEASE_RESET_AND_NORMALIZER_PASS values=4768 array_issues=4");
    endtask
    initial begin : test
        logic[1023:0] expected,held;
        if(!$value$plusargs("FIXTURE=%s",fixture))$fatal(1,"CONTEXT_FIXTURE_MISSING");
        $readmemh(fixture,contexts);
        repeat(2)@(negedge clk);rst_n=1;operands();all_output_slots();
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
        for(int address=0;address<4;address++)load(1,3,address==0?18:address==1?31:address==2?48:1023,'1,1);
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
        $display("SLOT_STORAGE_PASS verified_values=%0d array_issues=%0d",verified,array_issues);
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

// This isolated cluster top instantiates the three core/aggregate memory
// masters instrumented above. The remaining three support-memory masters
// belong to the full chip; they are not present or counted in this test.
module tri_oracle_slot_write_probe(input logic clk,rst_n,write,input logic[9:0] address,input logic[3:0] slot,input logic[1023:0] data);
    initial $display("SLOT_CORE_INSTANCE %m");
    always @(posedge clk)if(rst_n && write)$display("SLOT_PHYSICAL_WRITE scope=%m address=%0d slot=%0d data=%0256h",address,slot,data);
endmodule
bind tri_oracle_sram_memory_compute tri_oracle_slot_write_probe slot_write_witness(.clk(clk),.rst_n(rst_n),.write(context_write),.address(load_addr),.slot(output_write_address),.data(output_write_data));
