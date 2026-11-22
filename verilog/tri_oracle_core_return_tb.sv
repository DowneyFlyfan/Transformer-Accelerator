`timescale 1ns/1ps
module tri_oracle_core_return_tb;
    logic clk=0,rst_n=0,load_valid=0,cmd_valid=0,cmd_accumulate=0;
    logic [1:0] load_core=0,load_kind=0,cmd_reduce=0;
    logic [9:0] load_addr=0,cmd_activation=0;
    logic [2047:0] load_data=0;
    logic [31:0] load_row_enable='1;
    logic [4:0] cmd_weight=0,cmd_mask=0;
    logic [3:0] cmd_output=0,out_output;
    logic [2:0] core_score_select=0;
    logic activation_reloaded=0;
    logic load_error,cmd_ready,out_valid,out_ready;
    logic [1023:0] out_data;
    int ready_mode=0,cycle=0,accepted=0,retired=0,verified=0,maximum_pending=0;
    int first_issue=-1,last_initial_issue=-1,first_done=-1,blocked_before=0;
    int expected[256][32],tags[256],model[4][16][32];
    bit held=0;
    logic [1023:0] held_data;
    logic [3:0] held_tag;
    logic protocol_finished;
    tri_oracle_cluster_return_owner_protocol_tb protocol_test(.finished(protocol_finished));
    always #5 clk=~clk;
    always_comb out_ready=ready_mode==1 || (ready_mode==2 && cycle%7<3);

    tri_oracle_compute_cluster dut (
        .clk,.rst_n,.load_valid,.load_core,.load_kind,.load_addr,.load_data,.load_row_enable,.load_error,
        .cmd_valid,.cmd_ready,.cmd_weight,.cmd_mask,.cmd_activation,.cmd_output,.cmd_accumulate,.cmd_reduce,
        .out_valid,.out_ready,.out_output,.out_data,.activation_reloaded,.core_score_select,
        .merge_sign_data('0),.merge_sign_control('0),.merge_sign_counts(),.merge_table_request('0),.merge_table_word(),
        .token_size_bank_command('0),.token_size_bank_result(),.softmax_request('0),.softmax_response(),
        .merge_range_command('0),.merge_range_result(),.global_merge_word('0),.global_sign_counts('0),
        .strip_rst_n(rst_n),.strip_request('0),.strip_response(),.head_request('0),.head_response()
    );

    function automatic int weight(input int core,row,lane,phase);
        return (core*17+row*3+lane*5+phase*7)%23-11;
    endfunction
    function automatic int activation(input int core,lane,phase);
        return core*2+lane-5+phase*3;
    endfunction
    function automatic bit enabled(input int core,row,lane,phase);
        return (core+row+lane+phase)%4!=0;
    endfunction
    function automatic int dot(input int core,row,phase);
        int sum=0;
        for (int lane=0;lane<8;lane++)
            if (enabled(core,row,lane,phase))sum+=activation(core,lane,phase)*weight(core,row,lane,phase);
        return sum;
    endfunction
    function automatic int reduced(input int a,b,c,d,mode);
        longint signed sum;
        int maximum;
        sum=longint'(a)+longint'(b)+longint'(c)+longint'(d);
        maximum=a;
        if(b>maximum)maximum=b;
        if(c>maximum)maximum=c;
        if(d>maximum)maximum=d;
        case(mode)
            0:return 32'(sum);
            1:return maximum;
            2:return 32'(sum>>>2);
            default:$fatal(1,"CORE_RETURN_ORACLE_INVALID_MODE");
        endcase
    endfunction

    always @(posedge clk) begin : scoreboard
        int phase;
        cycle<=cycle+1;
        if(!rst_n)begin accepted=retired;held=0;end
        else begin
            if(first_done<0 && (|dut.implementation.done))first_done=cycle;
            if(held && (!out_valid || out_output!==held_tag || out_data!==held_data))
                $fatal(1,"CORE_RETURN_HELD_RESULT_CHANGED");
            held=out_valid && !out_ready;
            if(held)begin held_tag=out_output;held_data=out_data;end
            if(cmd_valid && cmd_ready)begin
                if(first_issue<0)first_issue=cycle;
                if(accepted<4)last_initial_issue=cycle;
                phase=cmd_weight==31 ? 1:0;
                tags[accepted]=int'(cmd_output);
                for(int row=0;row<32;row++)begin
                    for(int core=0;core<4;core++) if(!core_score_select[2] || core_score_select[1:0]==2'(core))begin
                        if(cmd_accumulate)model[core][cmd_output][row]+=dot(core,row,phase);
                        else model[core][cmd_output][row]=dot(core,row,phase);
                    end
                    expected[accepted][row]=core_score_select[2] ? model[core_score_select[1:0]][cmd_output][row]:
                        reduced(model[0][cmd_output][row],model[1][cmd_output][row],model[2][cmd_output][row],model[3][cmd_output][row],int'(cmd_reduce));
                end
                $display("CORE_RETURN_ISSUE tick=%0t slot=%0d owner=%0d reduce=%0d accumulate=%0d",$time,cmd_output,core_score_select,cmd_reduce,cmd_accumulate);
                accepted++;
                if(accepted-retired>maximum_pending)maximum_pending=accepted-retired;
            end
            if(out_valid && out_ready)begin
                if(retired>=accepted || out_output!==4'(tags[retired]))$fatal(1,"CORE_RETURN_TAG_ORDER");
                for(int row=0;row<32;row++)
                    if($signed(out_data[row*32+:32])!==expected[retired][row])
                        $fatal(1,"CORE_RETURN_ARITHMETIC result=%0d row=%0d got=%0d expected=%0d",retired,row,$signed(out_data[row*32+:32]),expected[retired][row]);
                $display("CORE_RETURN_OUTPUT tick=%0t slot=%0d values=%0256h",$time,out_output,out_data);
                retired++;verified++;
            end
        end
    end

    task automatic load(input int core,kind,address,input logic [2047:0] data);
        @(negedge clk);load_valid=1;load_core=2'(core);load_kind=2'(kind);load_addr=10'(address);load_data=data;
        @(posedge clk);#2;
        if(load_error || cmd_ready)$fatal(1,"CORE_RETURN_LOAD");
        @(negedge clk);load_valid=0;
    endtask
    task automatic operands;
        logic [2047:0] data;
        for(int core=0;core<4;core++)for(int phase=0;phase<2;phase++)begin
            data=0;
            for(int row=0;row<32;row++)for(int lane=0;lane<8;lane++)data[(row*8+lane)*8+:8]=8'(weight(core,row,lane,phase));
            load(core,0,phase==0?0:31,data);
            data=0;
            for(int row=0;row<32;row++)for(int lane=0;lane<8;lane++)data[row*8+lane]=enabled(core,row,lane,phase);
            load(core,2,phase==0?0:31,data);
            data=0;
            for(int lane=0;lane<8;lane++)data[lane*8+:8]=8'(activation(core,lane,phase));
            load(core,1,phase==0?0:1023,data);
        end
        core_score_select=0;activation_reloaded=1;
        @(negedge clk);activation_reloaded=0;
    endtask
    task automatic issue(input int slot,owner,mode,phase,input bit accumulate);
        @(negedge clk);cmd_valid=1;cmd_output=4'(slot);core_score_select=3'(owner);cmd_reduce=2'(mode);
        cmd_weight=phase==0?0:31;cmd_mask=phase==0?0:31;cmd_activation=phase==0?0:1023;cmd_accumulate=accumulate;
        do @(posedge clk);while(!cmd_ready);
    endtask
    task automatic withdraw;
        @(negedge clk);cmd_valid=0;core_score_select=3'b111;cmd_reduce=2'b11;
    endtask
    task automatic drain(input int target);
        int timeout=0;
        ready_mode=2;
        while(retired<target)begin @(negedge clk);timeout++;if(timeout>1000)$fatal(1,"CORE_RETURN_DRAIN_TIMEOUT");end
        ready_mode=0;
    endtask

    initial begin
        repeat(2)@(negedge clk);rst_n=1;
        operands();
        for(int core=0;core<4;core++)issue(core,4+core,core%3,0,0);
        withdraw();
        repeat(40)@(negedge clk);
        if(!out_valid)$fatal(1,"CORE_RETURN_WRONG_OWNER_STALL");
        if(last_initial_issue-first_issue!=3 || first_done<=last_initial_issue)
            $fatal(1,"CORE_RETURN_NOT_CONCURRENT");
        $display("CORE_RETURN_OVERLAP_PASS issue_span=%0d first_done_gap=%0d",last_initial_issue-first_issue,first_done-last_initial_issue);
        drain(4);

        for(int n=0;n<16;n++)issue((n*5)%16,n%3==0?0:4+(n%4),n%3,n%2,0);
        withdraw();
        repeat(30)begin @(negedge clk);core_score_select=3'(cycle%8);end
        blocked_before=accepted;
        cmd_output=0;core_score_select=4;cmd_reduce=0;cmd_weight=0;cmd_mask=0;cmd_activation=0;cmd_accumulate=0;cmd_valid=1;
        #1;if(cmd_ready)$fatal(1,"CORE_RETURN_FULL_QUEUE_ACCEPTED");
        @(posedge clk);#1;
        if(accepted!=blocked_before || accepted-retired!=16)$fatal(1,"CORE_RETURN_FULL_QUEUE_ISSUED");
        @(negedge clk);cmd_valid=0;
        drain(20);
        if(maximum_pending!=16)$fatal(1,"CORE_RETURN_FULL_QUEUE_NOT_EXERCISED");
        $display("CORE_RETURN_QUEUE_PASS capacity=16");

        for(int n=0;n<16;n++)issue(n,0,n%3,0,0);
        withdraw();drain(36);
        for(int n=0;n<16;n++)issue((n*7)%16,n%2==0?0:4+(n%4),n%3,1,1);
        withdraw();drain(52);
        $display("CORE_RETURN_ACCUMULATE_PASS results=16");

        for(int n=0;n<4;n++)issue(n,4+n,0,0,0);
        withdraw();repeat(20)@(negedge clk);
        if(!out_valid)$fatal(1,"CORE_RETURN_RESET_CASE_NOT_HELD");
        rst_n=0;repeat(2)@(negedge clk);
        if(out_valid)$fatal(1,"CORE_RETURN_RESET_NOT_FLUSHED");
        rst_n=1;operands();
        for(int n=0;n<4;n++)issue(n,4+n,n%3,1,0);
        withdraw();drain(56);
        if(verified!=56)$fatal(1,"CORE_RETURN_RESULT_COUNT");
        if(!protocol_finished)$fatal(1,"CORE_RETURN_PROTOCOL_NOT_FINISHED");
        $display("CORE_RETURN_RESET_PASS discarded=4 recovered=4");
        $display("CORE_RETURN_PASS verified_results=56 values=1792 pending_capacity=16 arrays=4");
        $finish;
    end
    initial begin #200000;$fatal(1,"CORE_RETURN_WATCHDOG");end
endmodule

module tri_oracle_core_return_array_witness;
    initial $display("CORE_RETURN_ARRAY %m");
endmodule
bind tri_oracle_pe_array tri_oracle_core_return_array_witness return_array_witness();
module tri_oracle_core_return_memory_witness;
    initial $display("CORE_RETURN_MEMORY %m");
endmodule
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_core_return_memory_witness return_memory_witness();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_core_return_memory_witness return_memory_witness();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_core_return_memory_witness return_memory_witness();
