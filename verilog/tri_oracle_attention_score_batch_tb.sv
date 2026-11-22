`timescale 1ns/1ps
// Literal trained scores catch wrong operand ownership, address phases and
// reduction. A serial-policy counterexample must fail after matching the data.
module tri_oracle_attention_score_batch_tb;
    logic clk=0,rst_n=0;
    logic cfg_valid=0,cfg_ready,cancel=0;
    logic [4:0] cfg_clusters=5'b10001;
    logic [24:0] cfg_heads=0;
    logic [159:0] cfg_rows=0;
    logic [15:0] cfg_query=1,cfg_epoch=16'h9ab3;
    logic [31:0] cfg_tag=32'h5317b92d;
    logic tensor_valid=0,tensor_ready,tensor_query=0;
    logic [2:0] tensor_cluster=0;
    logic [4:0] tensor_head=0,tensor_key=0;
    logic [511:0] tensor_data=0;
    logic [15:0] tensor_query_rank=1,tensor_epoch=16'h9ab3;
    logic [31:0] tensor_tag=32'h5317b92d;
    logic [4:0] result_valid,result_ready=0;
    logic [5119:0] result_data;
    logic [24:0] result_heads;
    logic [159:0] result_rows;
    logic [15:0] result_query,result_epoch;
    logic [31:0] result_tag;
    logic done_valid,done_ready=0,done_error,busy;
    logic load_valid,load_error,cmd_valid,cmd_ready;
    logic [4:0] load_core,cmd_clusters,cmd_weight,cmd_mask;
    logic [1:0] load_kind;
    logic [9:0] load_addr,cmd_activation;
    logic [2047:0] load_data;
    logic [31:0] load_rows;
    logic [3:0] cmd_output;
    logic cmd_accumulate;
    logic [4:0] activation_reloaded,fabric_out_valid,fabric_out_ready;
    logic [19:0] fabric_out_output;
    logic [19:0] routed_out_output;
    logic inject_output_tag=0;
    logic [5119:0] fabric_out_data;
    logic [511:0] trained_vectors[0:5];
    logic [4:0] first_issued=0,issued_before_first_result=0,finished=0;
    logic [4:0] held=0;
    logic [5119:0] held_data;
    int cycle=0,verified=0,case_id=0;
    bit first_result_seen=0,check_results=1;
    string fixture;
    always #5 clk=~clk;
    always_comb routed_out_output=fabric_out_output ^ (inject_output_tag?20'h10000:20'b0);

`ifndef SCORE_BATCH_BASELINE
    tri_oracle_attention_score_batch dut (
        .clk,.rst_n,.cfg_valid,.cfg_ready,.cfg_clusters,.cfg_heads,.cfg_rows,
        .cfg_query,.cfg_epoch,.cfg_tag,.cancel,.tensor_valid,.tensor_ready,
        .tensor_cluster,.tensor_head,.tensor_query,.tensor_key,.tensor_data,
        .tensor_query_rank,.tensor_epoch,.tensor_tag,
        .result_valid,.result_ready,.result_data,.result_heads,.result_rows,
        .result_query,.result_epoch,.result_tag,.done_valid,.done_ready,.done_error,.busy,
        .fabric_load_valid(load_valid),.fabric_load_core(load_core),.fabric_load_kind(load_kind),
        .fabric_load_addr(load_addr),.fabric_load_data(load_data),.fabric_load_rows(load_rows),
        .fabric_load_error(load_error),.fabric_activation_reloaded(activation_reloaded),
        .fabric_cmd_valid(cmd_valid),.fabric_cmd_ready(cmd_ready),.fabric_cmd_clusters(cmd_clusters),
        .fabric_cmd_weight(cmd_weight),.fabric_cmd_mask(cmd_mask),.fabric_cmd_activation(cmd_activation),
        .fabric_cmd_output(cmd_output),.fabric_cmd_accumulate(cmd_accumulate),
        .fabric_out_valid,.fabric_out_ready,.fabric_out_output(routed_out_output),.fabric_out_data
    );
`endif

    tri_oracle_compute_fabric #(
        .AGGREGATOR_SIGN_BANK(1),.AGGREGATOR_MERGE_TABLE(1),
        .LOCAL_TOKEN_SIZES(1),.LOCAL_TOKEN_MERGE(1),
        .CORE_STRIP_PREDICTOR(1),.CORE_HEAD_PREDICTOR(1)
    ) fabric (
        .clk,.rst_n,.load_valid,.load_core,.load_kind,.load_addr,.load_data,
        .load_row_enable(load_rows),.load_error,.cmd_valid,.cmd_ready,.cmd_clusters,
        .cmd_weight,.cmd_mask,.cmd_activation,.cmd_output,.cmd_accumulate,.cmd_reduce(2'd0),
        .out_valid(fabric_out_valid),.out_ready(fabric_out_ready),
        .out_output(fabric_out_output),.out_data(fabric_out_data),
        .merge_sign_data('0),.merge_sign_control('0),.merge_sign_counts(),
        .merge_table_request('0),.merge_table_word(),.activation_reloaded,
        .core_score_select(3'd0),.softmax_request('0),.softmax_response(),
        .token_sizes_request('0),.token_sizes_response(),.merge_request('0),.merge_response(),
        .strip_rst_n(rst_n),.strip_request('0),.strip_response(),.head_request('0),.head_response()
    );

    function automatic int q_value(input int cluster,feature);
        return ((cluster*11+feature*3)%19)-9;
    endfunction
    function automatic int k_value(input int cluster,key,feature);
        return ((cluster*7+key*5+feature*2)%17)-8;
    endfunction
    function automatic int expected(input int cluster,key);
        int total=0;
        if(case_id==0)begin
            if(key>1)return 0;
            if(cluster==4)return key==0?396:-237;
            if(cluster==0)return key==0?740:-1180;
            $fatal(1,"SCORE_BATCH_FOREIGN_CLUSTER");
        end
        if(!cfg_rows[cluster*32+key])return 0;
        for(int feature=0;feature<64;feature++)
            total+=q_value(cluster,feature)*k_value(cluster,key,feature);
        return total;
    endfunction

    always @(posedge clk) begin
        cycle<=cycle+1;
        if(rst_n)begin
            if(cmd_valid && cmd_ready)begin
                $display("SCORE_BATCH_ISSUE cycle=%0d clusters=%02h accumulate=%0d",cycle,cmd_clusters,cmd_accumulate);
                if(!cmd_accumulate)first_issued|=cmd_clusters;
            end
            if(!first_result_seen && |fabric_out_valid)begin
                issued_before_first_result=first_issued;
                first_result_seen=1;
            end
            for(int cluster=0;cluster<5;cluster++)begin
                if(held[cluster] && !cancel && !inject_output_tag && (!result_valid[cluster] ||
                    result_data[cluster*1024+:1024]!==held_data[cluster*1024+:1024]))
                    $fatal(1,"SCORE_BATCH_HELD_DATA_CHANGED cluster=%0d",cluster);
                held[cluster]=result_valid[cluster] && !result_ready[cluster];
                if(held[cluster])held_data[cluster*1024+:1024]=result_data[cluster*1024+:1024];
                if(result_valid[cluster] && result_ready[cluster] && check_results)begin
                    if(finished[cluster])$fatal(1,"SCORE_BATCH_DUPLICATE_RESULT");
                    if(result_heads[cluster*5+:5] !== (case_id==0 ? (cluster==4?5'd19:5'd20):5'(cluster)) ||
                        result_query!==16'd1 || result_epoch!==16'h9ab3 || result_tag!==32'h5317b92d)
                        $fatal(1,"SCORE_BATCH_RESULT_METADATA");
                    for(int key=0;key<32;key++)begin
                        if($signed(result_data[cluster*1024+key*32+:32])!==expected(cluster,key))
                            $fatal(1,"SCORE_BATCH_VALUE cluster=%0d key=%0d got=%0d expected=%0d",cluster,key,
                                $signed(result_data[cluster*1024+key*32+:32]),expected(cluster,key));
                        verified++;
                    end
                    finished[cluster]=1;
                    $display("SCORE_BATCH_RESULT cluster=%0d cycle=%0d values=%0256h",cluster,cycle,result_data[cluster*1024+:1024]);
                end
            end
        end
    end

`ifdef SCORE_BATCH_BASELINE
    initial begin
        load_valid=0;cmd_valid=0;load_core=0;cmd_clusters=0;cmd_weight=0;cmd_mask=0;
        load_kind=0;load_addr=0;cmd_activation=0;load_data=0;load_rows=0;
        cmd_output=0;cmd_accumulate=0;activation_reloaded=0;
    end
    // Counterexample: same actual arrays, operands and arithmetic; whole-row
    // cluster service is serial. It must fail the independent overlap contract.
    logic [4:0] baseline_final=0;
    always_comb begin
        result_valid=fabric_out_valid & baseline_final;
        result_data=fabric_out_data;result_heads=cfg_heads;result_rows=cfg_rows;
        result_query=cfg_query;result_epoch=cfg_epoch;result_tag=cfg_tag;
        fabric_out_ready=(fabric_out_valid & ~baseline_final) | (result_ready & baseline_final);
    end
    task automatic baseline_load(input int cluster,kind,core,address,key,input logic[63:0] word);
        @(negedge clk);load_valid=1;load_core=5'(cluster*4+core);load_kind=2'(kind);load_addr=10'(address);
        load_rows=kind==0?32'b1<<key:'1;load_data=0;
        if(kind==0)load_data={32{word}};
        else if(kind==1)load_data[63:0]=word;
        else for(int row=0;row<32;row++)load_data[row*8+:8]=row<2?8'hff:0;
        @(posedge clk);#1;if(load_error)$fatal(1,"SCORE_BATCH_BASELINE_LOAD");
        @(negedge clk);load_valid=0;
    endtask
    task automatic baseline_execute;
        int cluster,index;
        for(int which=0;which<2;which++)begin
            cluster=which==0?0:4;index=which==0?3:0;
            for(int word=0;word<8;word++)begin
                baseline_load(cluster,1,word/2,word%2,0,trained_vectors[index][word*64+:64]);
                for(int key=0;key<2;key++)
                    baseline_load(cluster,0,word/2,word%2,key,trained_vectors[index+1+key][word*64+:64]);
                baseline_load(cluster,2,word/2,word%2,0,0);
            end
            activation_reloaded=5'b1<<cluster;@(negedge clk);activation_reloaded=0;
            for(int phase=0;phase<2;phase++)begin
                cmd_clusters=5'b1<<cluster;cmd_valid=1;cmd_weight=5'(phase);cmd_mask=5'(phase);
                cmd_activation=10'(phase);cmd_accumulate=1'(phase);
                baseline_final=phase==1?5'b1<<cluster:0;
                do @(posedge clk);while(!cmd_ready);
                @(negedge clk);cmd_valid=0;
                while(!fabric_out_valid[cluster])@(negedge clk);
                if(phase==1 && cluster==4)begin
                    repeat(15)@(negedge clk);result_ready[4]=1;
                end
                @(posedge clk);@(negedge clk);
            end
        end
    endtask
`else
    task automatic configure;
        @(negedge clk);cfg_valid=1;
        do @(posedge clk);while(!cfg_ready);
        @(negedge clk);cfg_valid=0;
    endtask
    task automatic send_vector(input int cluster,head,key,input bit is_query,input logic[511:0] vector);
        @(negedge clk);tensor_valid=1;tensor_cluster=3'(cluster);tensor_head=5'(head);
        tensor_key=5'(key);tensor_query=is_query;tensor_data=vector;
        do @(posedge clk);while(!tensor_ready);
        @(negedge clk);tensor_valid=0;tensor_data='x;tensor_head='x;
    endtask
    task automatic wait_done(input bit error_expected);
        while(!done_valid)@(negedge clk);
        if(done_error!==error_expected)$fatal(1,"SCORE_BATCH_DONE_STATUS");
        repeat(3)begin
            @(negedge clk);
            if(!done_valid || !busy || cfg_ready)$fatal(1,"SCORE_BATCH_COMPLETION_HOLD");
        end
        done_ready=1;@(negedge clk);done_ready=0;
        #1;if(busy || !cfg_ready)$fatal(1,"SCORE_BATCH_NOT_RELEASED");
    endtask
    task automatic trained_operands;
        // Deliberately interleave owners and provide key before query.
        send_vector(4,19,1,0,trained_vectors[2]);
        send_vector(0,20,0,1,trained_vectors[3]);
        send_vector(4,19,0,1,trained_vectors[0]);
        send_vector(0,20,0,0,trained_vectors[4]);
        send_vector(4,19,0,0,trained_vectors[1]);
        send_vector(0,20,1,0,trained_vectors[5]);
    endtask
`endif

    initial begin : test
        logic[511:0] vector;
        if(!$value$plusargs("FIXTURE=%s",fixture))$fatal(1,"SCORE_BATCH_FIXTURE_MISSING");
        $readmemh(fixture,trained_vectors);
        cfg_heads[4*5+:5]=19;cfg_heads[0+:5]=20;
        cfg_rows[4*32+:32]=3;cfg_rows[0+:32]=3;
        repeat(2)@(negedge clk);rst_n=1;result_ready=1;
`ifdef SCORE_BATCH_BASELINE
        baseline_execute();
`else
        configure();trained_operands();
        // Accepted descriptors must survive arbitrary later input changes.
        cfg_heads='1;cfg_query='1;cfg_epoch=0;cfg_tag=0;
        while(!result_valid[4] || !finished[0])@(negedge clk);
        repeat(17)begin
            @(negedge clk);
            if(!result_valid[4] || finished[4] || !finished[0] || done_valid)
                $fatal(1,"SCORE_BATCH_STALLED_OWNER");
        end
        result_ready[4]=1;
        while(!finished[4])@(negedge clk);
        wait_done(0);
`endif
        if(verified!=64 || finished!=5'b10001)$fatal(1,"SCORE_BATCH_TRAINED_COUNT");
        $display("SCORE_BATCH_TRAINED_DATA_PASS scores=64 trained_nonzero=4");
        if(issued_before_first_result!==5'b10001)$fatal(1,"SCORE_BATCH_SERIAL_POLICY_REJECTED mask=%02h",issued_before_first_result);
        $display("SCORE_BATCH_TRAINED_OVERLAP_PASS clusters=17 stalled_cluster=4 completed_cluster=0");
`ifndef SCORE_BATCH_BASELINE
        case_id=1;verified=0;finished=0;first_issued=0;first_result_seen=0;held=0;
        cfg_clusters=31;cfg_query=1;cfg_epoch=16'h9ab3;cfg_tag=32'h5317b92d;
        for(int cluster=0;cluster<5;cluster++)begin
            cfg_heads[cluster*5+:5]=5'(cluster);cfg_rows[cluster*32+:32]=32'h80010001;
        end
        configure();result_ready=31;
        for(int cluster=4;cluster>=0;cluster--)begin
            for(int feature=0;feature<64;feature++)vector[feature*8+:8]=8'(q_value(cluster,feature));
            send_vector(cluster,cluster,0,1,vector);
            for(int key=31;key>=0;key--)if(cfg_rows[cluster*32+key])begin
                for(int feature=0;feature<64;feature++)vector[feature*8+:8]=8'(k_value(cluster,key,feature));
                send_vector(cluster,cluster,key,0,vector);
            end
        end
        wait_done(0);
        if(verified!=160 || finished!=31 || issued_before_first_result!=31)$fatal(1,"SCORE_BATCH_FIVE_CLUSTER_COUNT");
        $display("SCORE_BATCH_FIVE_CLUSTER_PASS scores=160 active_key_rows=15");

        // A foreign operand must fail before issuing any array command.
        first_issued=0;check_results=0;
        configure();send_vector(0,31,0,1,trained_vectors[0]);wait_done(1);
        if(first_issued!=0)$fatal(1,"SCORE_BATCH_FOREIGN_OPERAND_ISSUED");
        $display("SCORE_BATCH_FOREIGN_OPERAND_PASS");

        cfg_clusters=17;cfg_heads=0;cfg_heads[20+:5]=19;cfg_heads[0+:5]=20;
        cfg_rows=0;cfg_rows[128+:32]=3;cfg_rows[0+:32]=3;first_issued=0;
        configure();trained_operands();
        while(first_issued!=17)@(negedge clk);
        cancel=1;@(negedge clk);cancel=0;
        result_ready=0;
        wait_done(1);
        if(|fabric_out_valid)$fatal(1,"SCORE_BATCH_CANCEL_NOT_DRAINED");
        $display("SCORE_BATCH_CANCEL_DRAIN_PASS");

        // Recovery without resetting the real fabric or its compiled memories.
        case_id=0;verified=0;finished=0;held=0;check_results=1;result_ready=31;
        configure();trained_operands();wait_done(0);
        if(verified!=64 || finished!=17)$fatal(1,"SCORE_BATCH_RECOVERY");
        $display("SCORE_BATCH_RECOVERY_PASS scores=64");

        // Same head/cluster but stale query, placement epoch or transaction
        // tag must never be accepted as data for a fresh frozen descriptor.
        check_results=0;
        for(int field=0;field<3;field++)begin
            tensor_query_rank=1;tensor_epoch=16'h9ab3;tensor_tag=32'h5317b92d;
            case(field)
                0:tensor_epoch^=16'h0001;
                1:tensor_tag^=32'h00000001;
                2:tensor_query_rank=2;
            endcase
            first_issued=0;configure();send_vector(0,20,0,1,trained_vectors[3]);
            repeat(12)@(negedge clk);
            if(!done_valid || !done_error || first_issued!=0)
                $fatal(1,"SCORE_BATCH_STALE_CONTEXT_ACCEPTED field=%0d",field);
            wait_done(1);
        end
        tensor_query_rank=1;tensor_epoch=16'h9ab3;tensor_tag=32'h5317b92d;
        $display("SCORE_BATCH_STALE_CONTEXT_PASS fields=3");

        // Cancellation revokes provisional held beats. The caller may commit
        // previously consumed results only after a successful batch completion.
        case_id=0;verified=0;finished=0;held=0;check_results=1;result_ready=1;
        configure();trained_operands();
        while(!result_valid[4] || !finished[0])@(negedge clk);
        if(verified!=32)$fatal(1,"SCORE_BATCH_FINAL_CANCEL_NOT_PARTIAL");
        repeat(7)@(negedge clk);
        cancel=1;#1;
        if(|result_valid)$fatal(1,"SCORE_BATCH_CANCEL_DID_NOT_REVOKE");
        @(negedge clk);cancel=0;wait_done(1);
        if(|fabric_out_valid || |result_valid || verified!=32 || finished!=1)
            $fatal(1,"SCORE_BATCH_FINAL_CANCEL_NOT_DRAINED");
        $display("SCORE_BATCH_FINAL_CANCEL_PASS consumed_clusters=1 revoked_cluster=4");
        verified=0;finished=0;held=0;result_ready=31;
        configure();trained_operands();wait_done(0);
        if(verified!=64 || finished!=17)$fatal(1,"SCORE_BATCH_FINAL_CANCEL_RECOVERY");
        $display("SCORE_BATCH_FINAL_CANCEL_RECOVERY_PASS scores=64");

        // A detected bad fabric tag has the same provisional-result revocation
        // contract as cancellation, including already consumed peer results.
        verified=0;finished=0;held=0;result_ready=1;
        configure();trained_operands();
        while(!result_valid[4] || !finished[0])@(negedge clk);
        if(verified!=32)$fatal(1,"SCORE_BATCH_TAG_ERROR_NOT_PARTIAL");
        inject_output_tag=1;#1;
        if(|result_valid)$fatal(1,"SCORE_BATCH_TAG_ERROR_DID_NOT_REVOKE");
        @(negedge clk);inject_output_tag=0;wait_done(1);
        if(|fabric_out_valid || |result_valid || verified!=32 || finished!=1)
            $fatal(1,"SCORE_BATCH_TAG_ERROR_NOT_DRAINED");
        $display("SCORE_BATCH_TAG_ERROR_PASS consumed_clusters=1 revoked_cluster=4");
        verified=0;finished=0;held=0;result_ready=31;
        configure();trained_operands();wait_done(0);
        if(verified!=64 || finished!=17)$fatal(1,"SCORE_BATCH_TAG_ERROR_RECOVERY");
        $display("SCORE_BATCH_TAG_ERROR_RECOVERY_PASS scores=64");
`endif
        $display("SCORE_BATCH_PASS trained_scores=320 synthetic_scores=160");
        $finish;
    end
    initial begin #2000000;$fatal(1,"SCORE_BATCH_WATCHDOG");end
endmodule

module tri_oracle_score_batch_core_probe (
    input logic clk,rst_n,cmd_valid,cmd_ready,cmd_accumulate,done_valid
);
    always @(posedge clk)if(rst_n)begin
        if(cmd_valid && cmd_ready)$display("SCORE_BATCH_PHYSICAL_ISSUE path=%m tick=%0t accumulate=%0d",$time,cmd_accumulate);
        if(done_valid)$display("SCORE_BATCH_PHYSICAL_DONE path=%m tick=%0t",$time);
    end
endmodule
bind tri_oracle_sram_strip_core448 tri_oracle_score_batch_core_probe physical_witness(.*);

module tri_oracle_score_batch_array_probe (
    input logic clk,rst_n,in_valid,in_ready,out_valid,out_ready,
    input logic [2047:0] operand_a,operand_b,
    input logic [255:0] lane_enable,
    input logic [607:0] out_sums
);
    initial $display("SCORE_BATCH_ARRAY path=%m");
    always @(posedge clk)if(rst_n)begin
        if(in_valid && in_ready)$display("SCORE_BATCH_ARRAY_INPUT path=%m tick=%0t a=%0512h b=%0512h mask=%064h",$time,operand_a,operand_b,lane_enable);
        if(out_valid && out_ready)$display("SCORE_BATCH_ARRAY_OUTPUT path=%m tick=%0t sums=%0152h",$time,out_sums);
    end
endmodule
bind tri_oracle_pe_array tri_oracle_score_batch_array_probe array_witness(.*);
module tri_oracle_score_batch_memory_probe;
    initial $display("SCORE_BATCH_MEMORY path=%m");
endmodule
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_score_batch_memory_probe batch_memory_witness();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_score_batch_memory_probe batch_memory_witness();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_score_batch_memory_probe batch_memory_witness();
