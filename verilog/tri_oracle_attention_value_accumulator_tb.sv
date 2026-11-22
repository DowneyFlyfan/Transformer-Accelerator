`timescale 1ns/1ps
// Exercise actual shared score arrays, local normalizers and context memories.
// The external stimulus schedules transactions; this is not a head-batch broker.
module tri_oracle_attention_value_accumulator_tb;
    logic clk=0,rst_n=0;
    logic req_valid=0,req_ready,req_first=0,req_last=0,cancel=0;
    logic [1:0] req_operation=0;
    logic [4:0] req_owner=0,req_head=0;
    logic [15:0] req_query=1,req_epoch=16'h9ab3,req_probability=0;
    logic [31:0] req_tag=32'h5317b92d;
    logic [9:0] req_key=0;
    logic [511:0] req_value=0;
    logic rsp_valid,rsp_ready=0,rsp_error,fabric_lock;
    logic [1:0] rsp_operation;
    logic [4:0] rsp_owner,rsp_head;
    logic [15:0] rsp_query,rsp_epoch;
    logic [31:0] rsp_tag;
    logic [9:0] rsp_key;
    logic rsp_last;
    logic [2047:0] rsp_values;
    logic [19:0] resident,completed,poisoned;
    logic [4:0] busy_clusters;
    logic fabric_grant=1,memory_load_valid,memory_read_valid,memory_read_ready;
    logic [4:0] memory_core,memory_clusters,memory_out_ready;
    logic [9:0] memory_address;
    logic [3:0] memory_slot;
    logic [2:0] memory_core_select;
    logic [1023:0] memory_write_data;
    logic memory_load_error;

    logic score_cfg_valid=0,score_cfg_ready,score_tensor_valid=0,score_tensor_ready,score_tensor_query=0;
    logic [2:0] score_tensor_cluster=0;
    logic [4:0] score_tensor_head=0,score_tensor_key=0;
    logic [511:0] score_tensor_data=0;
    logic [24:0] score_heads=0;
    logic [159:0] score_rows=0;
    logic [4:0] score_result_valid,score_result_ready=0;
    logic [5119:0] score_result_data;
    logic score_done_valid,score_done_error,score_done_ready=0;
    logic score_load_valid,score_cmd_valid,score_cmd_ready;
    logic [4:0] score_load_core,score_cmd_clusters,score_cmd_weight,score_cmd_mask,score_reloaded;
    logic [1:0] score_load_kind;
    logic [9:0] score_load_addr,score_cmd_activation;
    logic [2047:0] score_load_data;
    logic [31:0] score_load_rows;
    logic [3:0] score_cmd_output;
    logic score_cmd_accumulate;
    logic [4:0] score_out_ready;

    logic value_mode=0,inject_load_error=0,inject_tag_error=0,block_read_accept=0;
    logic load_valid,load_error,cmd_valid,cmd_ready,cmd_accumulate;
    logic [4:0] load_core,cmd_clusters,cmd_weight,cmd_mask,activation_reloaded,out_valid,out_ready;
    logic [1:0] load_kind,cmd_reduce;
    logic [9:0] load_addr,cmd_activation;
    logic [2047:0] load_data;
    logic [31:0] load_rows;
    logic [3:0] cmd_output;
    logic [2:0] core_score_select;
    logic [19:0] out_output,routed_out_output;
    logic [5119:0] out_data;
    tri_oracle_wac_softmax_types::request_t norm_request='0;
    tri_oracle_wac_softmax_types::response_t norm_response;
    logic signed [31:0] scale_dot=0;
    logic signed [6:0] scale_shift=0;
    logic [15:0] scaled_score;
    logic [511:0] qk[0:5],vectors[0:3];
    logic [2047:0] golden[0:1];
    string qk_file,value_file,gold_file;
    int expected_model[20][64];
    int accepted=0,responses=0,checked_values=0;
    int saved_op,saved_owner,saved_head,saved_key;
    logic saved_first,saved_last;
    logic [15:0] saved_query,saved_epoch,saved_probability;
    logic [31:0] saved_tag;
    logic [511:0] saved_value;
    always #5 clk=~clk;

    tri_oracle_attention_score_scale scale(.dot(scale_dot),.shift(scale_shift),.score(scaled_score));
    tri_oracle_attention_value_accumulator dut (
        .clk,.rst_n,.req_valid,.req_ready,.req_operation,.req_owner,.req_head,.req_query,.req_epoch,.req_tag,
        .req_key,.req_first,.req_last,.req_probability,.req_value,.cancel,
        .rsp_valid,.rsp_ready,.rsp_error,.rsp_operation,.rsp_owner,.rsp_head,.rsp_query,.rsp_epoch,.rsp_tag,
        .rsp_key,.rsp_last,.rsp_values,.resident,.completed,.poisoned,.busy_clusters,
        .fabric_grant,.fabric_lock,.memory_load_valid,.memory_core,.memory_address,.memory_write_data,.memory_load_error,
        .memory_read_valid,.memory_read_ready,.memory_clusters,.memory_slot,.memory_core_select,
        .memory_out_valid(out_valid),.memory_out_ready,.memory_out_slot(routed_out_output),.memory_out_data(out_data)
    );
    tri_oracle_attention_score_batch score (
        .clk,.rst_n,.cfg_valid(score_cfg_valid),.cfg_ready(score_cfg_ready),.cfg_clusters(5'b10001),
        .cfg_heads(score_heads),.cfg_rows(score_rows),.cfg_query(16'd1),.cfg_epoch(16'h9ab3),.cfg_tag(32'h5317b92d),.cancel(1'b0),
        .tensor_valid(score_tensor_valid),.tensor_ready(score_tensor_ready),.tensor_cluster(score_tensor_cluster),
        .tensor_head(score_tensor_head),.tensor_query(score_tensor_query),.tensor_key(score_tensor_key),
        .tensor_query_rank(16'd1),.tensor_epoch(16'h9ab3),.tensor_tag(32'h5317b92d),.tensor_data(score_tensor_data),
        .result_valid(score_result_valid),.result_ready(score_result_ready),.result_data(score_result_data),
        .result_heads(),.result_rows(),.result_query(),.result_epoch(),.result_tag(),
        .done_valid(score_done_valid),.done_ready(score_done_ready),.done_error(score_done_error),.busy(),
        .fabric_load_valid(score_load_valid),.fabric_load_core(score_load_core),.fabric_load_kind(score_load_kind),
        .fabric_load_addr(score_load_addr),.fabric_load_data(score_load_data),.fabric_load_rows(score_load_rows),.fabric_load_error(load_error),
        .fabric_activation_reloaded(score_reloaded),.fabric_cmd_valid(score_cmd_valid),.fabric_cmd_ready(score_cmd_ready),
        .fabric_cmd_clusters(score_cmd_clusters),.fabric_cmd_weight(score_cmd_weight),.fabric_cmd_mask(score_cmd_mask),
        .fabric_cmd_activation(score_cmd_activation),.fabric_cmd_output(score_cmd_output),.fabric_cmd_accumulate(score_cmd_accumulate),
        .fabric_out_valid(out_valid),.fabric_out_ready(score_out_ready),.fabric_out_output(out_output),.fabric_out_data(out_data)
    );
    always_comb begin
        load_valid=value_mode?memory_load_valid:score_load_valid;
        load_core=value_mode?memory_core:score_load_core;
        load_kind=value_mode?2'd3:score_load_kind;
        load_addr=value_mode?memory_address:score_load_addr;
        load_data=value_mode?{1024'b0,memory_write_data}:score_load_data;
        load_rows=value_mode?'1:score_load_rows;
        cmd_valid=value_mode?(memory_read_valid && !block_read_accept):score_cmd_valid;
        cmd_clusters=value_mode?memory_clusters:score_cmd_clusters;
        cmd_weight=value_mode?5'd0:score_cmd_weight;cmd_mask=value_mode?5'd0:score_cmd_mask;
        cmd_activation=value_mode?10'd0:score_cmd_activation;cmd_output=value_mode?memory_slot:score_cmd_output;
        cmd_accumulate=value_mode?1'b0:score_cmd_accumulate;cmd_reduce=value_mode?2'd3:2'd0;
        core_score_select=value_mode?memory_core_select:3'd0;
        activation_reloaded=value_mode?5'd0:score_reloaded;
        score_cmd_ready=!value_mode && cmd_ready;
        memory_read_ready=value_mode && !block_read_accept && cmd_ready;
        memory_load_error=load_error || inject_load_error;
        out_ready=value_mode?memory_out_ready:score_out_ready;
        routed_out_output=out_output ^ (inject_tag_error?20'h11111:20'd0);
    end
    always @(posedge clk)if(rst_n && value_mode)begin
        if(memory_load_valid)$display("VALUE_MEMORY_LOAD n=%0d core=%0d address=%0d data=%0256h",accepted,memory_core,memory_address,memory_write_data);
        if(cmd_valid && cmd_ready)$display("VALUE_MEMORY_READ n=%0d clusters=%02h core_select=%0d slot=%0d",accepted,cmd_clusters,core_score_select,cmd_output);
        for(int cluster=0;cluster<5;cluster++)if(out_valid[cluster] && out_ready[cluster])
            $display("VALUE_MEMORY_RETURN n=%0d cluster=%0d slot=%0d routed_slot=%0d data=%0256h",accepted,cluster,
                out_output[cluster*4+:4],routed_out_output[cluster*4+:4],out_data[cluster*1024+:1024]);
    end
    tri_oracle_compute_fabric #(
        .AGGREGATOR_SIGN_BANK(1),.AGGREGATOR_MERGE_TABLE(1),.LOCAL_TOKEN_SIZES(1),.LOCAL_TOKEN_MERGE(1),
        .CORE_STRIP_PREDICTOR(1),.CORE_HEAD_PREDICTOR(1)
    ) fabric (
        .clk,.rst_n,.load_valid,.load_core,.load_kind,.load_addr,.load_data,.load_row_enable(load_rows),.load_error,
        .cmd_valid,.cmd_ready,.cmd_clusters,.cmd_weight,.cmd_mask,.cmd_activation,.cmd_output,.cmd_accumulate,.cmd_reduce,
        .out_valid,.out_ready,.out_output,.out_data,.merge_sign_data('0),.merge_sign_control('0),.merge_sign_counts(),
        .merge_table_request('0),.merge_table_word(),.softmax_request(norm_request),.softmax_response(norm_response),
        .activation_reloaded,.core_score_select,.token_sizes_request('0),.token_sizes_response(),.merge_request('0),.merge_response(),
        .strip_rst_n(rst_n),.strip_request('0),.strip_response(),.head_request('0),.head_response()
    );
    task automatic score_vector(input int cluster,head,key,input bit is_query,input logic[511:0] data);
        @(negedge clk);score_tensor_valid=1;score_tensor_cluster=3'(cluster);score_tensor_head=5'(head);
        score_tensor_key=5'(key);score_tensor_query=is_query;score_tensor_data=data;
        do @(posedge clk);while(!score_tensor_ready);
        @(negedge clk);score_tensor_valid=0;
    endtask
    task automatic configure_normalizer(input int owner);
        norm_request='0;norm_request.owner=5'(owner);norm_request.cfg_valid=1;norm_request.cfg_length=2;
        do @(posedge clk);while(!norm_response.cfg_ready);
        @(negedge clk);norm_request='0;
    endtask
    task automatic score_to_normalizer(input int owner,cluster,key);
        norm_request='0;norm_request.owner=5'(owner);norm_request.in_valid=1;norm_request.size=1;
        scale_dot=$signed(score_result_data[cluster*1024+key*32+:32]);scale_shift=cluster==0?-1:0;
        #1;norm_request.score=$signed(scaled_score);
        do @(posedge clk);while(!norm_response.in_ready);
        $display("VALUE_SCORE owner=%0d key=%0d raw=%0d scaled=%0d",owner,key,scale_dot,$signed(norm_request.score));
        @(negedge clk);norm_request='0;
    endtask
    task automatic probability(input int owner,key,input logic[15:0] expected,output logic[15:0] actual);
        norm_request='0;norm_request.owner=5'(owner);#1;
        while(!norm_response.out_valid)@(negedge clk);
        actual=norm_response.probability;
        if(actual!==expected || norm_response.out_last!==(key==1) || norm_response.cfg_error)$fatal(1,"VALUE_PROBABILITY");
        norm_request.out_ready=1;@(posedge clk);
        $display("VALUE_PROBABILITY owner=%0d key=%0d probability=%0d",owner,key,actual);
        @(negedge clk);norm_request='0;
    endtask
    task automatic start(input int operation,owner,head,key,input bit first,last,input logic[15:0] p,
        input logic[511:0] value,input logic[31:0] tag=32'h5317b92d,input logic[15:0] epoch=16'h9ab3,query=1);
        @(negedge clk);req_valid=1;req_operation=2'(operation);req_owner=5'(owner);req_head=5'(head);
        req_key=10'(key);req_first=first;req_last=last;req_probability=p;req_value=value;req_tag=tag;req_epoch=epoch;req_query=query;
        do @(posedge clk);while(!req_ready);
        saved_op=operation;saved_owner=owner;saved_head=head;saved_key=key;saved_first=first;saved_last=last;
        saved_probability=p;saved_value=value;saved_tag=tag;saved_epoch=epoch;saved_query=query;accepted++;
        $display("VALUE_REQUEST n=%0d op=%0d owner=%0d head=%0d key=%0d first=%0d last=%0d query=%0d epoch=%04h tag=%08h probability=%0d value=%0128h",
            accepted,operation,owner,head,key,first,last,query,epoch,tag,p,value);
        @(negedge clk);req_valid=0;req_owner=31;req_value='x;req_tag='x;
    endtask
    task automatic finish(input bit expect_error,input int hold_cycles=0);
        logic[2047:0] held;
        longint signed total;
        while(!rsp_valid)@(negedge clk);
        if(rsp_error!==expect_error || rsp_operation!==2'(saved_op) || rsp_owner!==5'(saved_owner) || rsp_head!==5'(saved_head) ||
            rsp_key!==10'(saved_key) || rsp_last!==saved_last || rsp_query!==saved_query || rsp_epoch!==saved_epoch || rsp_tag!==saved_tag)
            $fatal(1,"VALUE_RESPONSE_METADATA n=%0d",accepted);
        held=rsp_values;
        if(expect_error)begin if(rsp_values!==0)$fatal(1,"VALUE_ERROR_PAYLOAD");end
        else if(saved_op!=2)begin
            if(saved_op==0)for(int feature=0;feature<64;feature++)begin
                total=saved_first?0:longint'(expected_model[saved_owner][feature]);
                total+=longint'({1'b0,saved_probability})*longint'($signed(saved_value[feature*8+:8]));
                expected_model[saved_owner][feature]=32'(total);
            end
            for(int feature=0;feature<64;feature++)begin
                if($signed(rsp_values[feature*32+:32])!==expected_model[saved_owner][feature])
                    $fatal(1,"VALUE_ACCUMULATOR_MISMATCH owner=%0d key=%0d feature=%0d got=%0d expected=%0d",saved_owner,saved_key,feature,
                        $signed(rsp_values[feature*32+:32]),expected_model[saved_owner][feature]);
                checked_values++;
            end
        end
        repeat(hold_cycles)begin
            req_valid=1;req_owner=5'(saved_owner+1);req_tag=32'hbadadada;cancel=1;
            @(negedge clk);
            if(!rsp_valid || rsp_values!==held || req_ready || rsp_error!==expect_error ||
                rsp_owner!==5'(saved_owner) || rsp_tag!==saved_tag || memory_load_valid || memory_read_valid)
                $fatal(1,"VALUE_HELD_RESPONSE_CHANGED");
        end
        req_valid=0;cancel=0;
        $display("VALUE_RESPONSE n=%0d op=%0d owner=%0d head=%0d key=%0d error=%0d resident=%05h completed=%05h poisoned=%05h values=%0512h",
            responses+1,saved_op,saved_owner,saved_head,saved_key,rsp_error,resident,completed,poisoned,rsp_values);
        rsp_ready=1;@(negedge clk);rsp_ready=0;responses++;
    endtask
    task automatic release_owner(input int owner,head);
        start(2,owner,head,0,0,0,0,0);finish(0);
    endtask
    initial begin : test
        logic[15:0] p;
        logic[511:0] pattern;
        if(!$value$plusargs("VALUES=%s",value_file) || !$value$plusargs("GOLD=%s",gold_file) || !$value$plusargs("QK=%s",qk_file))
            $fatal(1,"VALUE_FIXTURES_MISSING");
        $readmemh(value_file,vectors);$readmemh(gold_file,golden);$readmemh(qk_file,qk);
        score_heads[0+:5]=20;score_heads[20+:5]=19;score_rows[0+:32]=3;score_rows[128+:32]=3;
        repeat(2)@(negedge clk);rst_n=1;score_cfg_valid=1;
        do @(posedge clk);while(!score_cfg_ready);
        @(negedge clk);score_cfg_valid=0;
        score_vector(4,19,0,1,qk[0]);score_vector(0,20,0,1,qk[3]);
        score_vector(0,20,0,0,qk[4]);score_vector(4,19,1,0,qk[2]);
        score_vector(4,19,0,0,qk[1]);score_vector(0,20,1,0,qk[5]);
        while(!score_result_valid[0] || !score_result_valid[4])@(negedge clk);
        configure_normalizer(0);configure_normalizer(19);
        for(int key=0;key<2;key++)begin score_to_normalizer(0,0,key);score_to_normalizer(19,4,key);end
        score_result_ready=17;@(negedge clk);score_result_ready=0;
        while(!score_done_valid)@(negedge clk);
        if(score_done_error)$fatal(1,"VALUE_SCORE_BATCH_ERROR");
        score_done_ready=1;@(negedge clk);score_done_ready=0;value_mode=1;

        probability(0,0,64029,p);start(0,0,20,0,1,0,p,vectors[2]);finish(0);
        probability(19,0,60434,p);start(0,19,19,0,1,0,p,vectors[0]);finish(0);
        if(!resident[0] || !resident[19] || completed[0] || completed[19])$fatal(1,"VALUE_TWO_CONTEXTS_NOT_RESIDENT");
        $display("VALUE_TWO_CONTEXTS_RESIDENT");
        // Invalid descriptors cannot poison either valid partial context.
        start(0,0,20,2,0,1,1,vectors[3]);finish(1);
        start(0,0,20,1,0,1,1,vectors[3],32'h5317b92c);finish(1);
        start(0,0,20,1,0,1,1,vectors[3],32'h5317b92d,16'h9ab2);finish(1);
        start(0,0,20,1,0,1,1,vectors[3],32'h5317b92d,16'h9ab3,2);finish(1);
        start(0,0,19,1,0,1,1,vectors[3]);finish(1);
        start(0,0,20,0,1,0,1,vectors[3]);finish(1);
        start(1,0,20,0,0,1,0,0);finish(1);
        if(poisoned[0] || poisoned[19])$fatal(1,"VALUE_INVALID_REQUEST_POISONED_PEER");
        probability(0,1,1506,p);start(0,0,20,1,0,1,p,vectors[3]);finish(0);
        start(1,0,20,1,0,1,0,0);finish(0,17);
        if(rsp_values!==golden[1] || !completed[0] || completed[19])$fatal(1,"VALUE_FIRST_CONTEXT_GOLDEN");
        norm_request='0;norm_request.owner=19;#1;
        if(!norm_response.out_valid || norm_response.probability!==5101)$fatal(1,"VALUE_STALLED_NORMALIZER_LOST");
        $display("VALUE_PEER_FINISHED_WHILE_HEAD19_STALLED");
        probability(19,1,5101,p);start(0,19,19,1,0,1,p,vectors[1]);finish(0);
        start(1,19,19,1,0,1,0,0);finish(0);
        if(rsp_values!==golden[0])$fatal(1,"VALUE_SECOND_CONTEXT_GOLDEN");
        $display("VALUE_TRAINED_DATAPATH_PASS values=128");
        start(0,0,20,2,0,1,1,vectors[3]);finish(1);

        // Cancel a pending read; the reserved response must drain without reset.
        start(1,19,19,1,0,1,0,0);
        while(!memory_read_valid || !memory_read_ready)@(negedge clk);
        @(posedge clk);@(negedge clk);cancel=1;
        $display("VALUE_FAULT n=%0d cause=cancel_read",accepted);
        @(negedge clk);cancel=0;finish(1);
        if(!poisoned[19])$fatal(1,"VALUE_CANCEL_NOT_POISONED");
        release_owner(19,19);
        // A corrupt physical read tag cannot publish a successful final context.
        inject_tag_error=1;start(1,0,20,1,0,1,0,0);
        $display("VALUE_FAULT n=%0d cause=bad_read_tag",accepted);finish(1);inject_tag_error=0;
        if(!poisoned[0])$fatal(1,"VALUE_BAD_TAG_NOT_POISONED");
        start(1,0,20,1,0,1,0,0);finish(1);release_owner(0,20);
        $display("VALUE_READ_CANCEL_AND_TAG_ERROR_PASS");

        // Cancel after one half has physically written; require explicit release.
        start(0,1,1,0,1,1,65535,vectors[0]);
        while(!memory_load_valid || memory_address!=14)@(negedge clk);
        @(posedge clk);@(negedge clk);cancel=1;
        $display("VALUE_FAULT n=%0d cause=cancel_half_write",accepted);
        @(negedge clk);cancel=0;finish(1);
        if(!resident[1] || !poisoned[1])$fatal(1,"VALUE_PARTIAL_WRITE_NOT_POISONED");
        start(0,1,1,0,1,1,1,vectors[0]);finish(1);release_owner(1,1);
        start(0,1,1,0,1,1,0,vectors[0]);finish(0);release_owner(1,1);
        inject_load_error=1;start(0,3,3,0,1,1,1,vectors[0]);
        $display("VALUE_FAULT n=%0d cause=load_error",accepted);finish(1);inject_load_error=0;
        if(!poisoned[3])$fatal(1,"VALUE_LOAD_ERROR_NOT_POISONED");
        release_owner(3,3);start(0,3,3,0,1,1,1,vectors[0]);finish(0);release_owner(3,3);
        start(0,31,20,0,1,1,1,vectors[0]);finish(1);
        $display("VALUE_ERROR_RELEASE_RECOVERY_PASS");

        start(0,6,6,0,1,1,1,vectors[0]);finish(0);
        block_read_accept=1;start(1,6,6,0,0,1,0,0);
        while(!memory_read_valid)@(negedge clk);
        if(memory_read_ready || |out_valid)$fatal(1,"VALUE_UNACCEPTED_READ_TEST");
        cancel=1;$display("VALUE_FAULT n=%0d cause=unaccepted_read_cancel",accepted);
        @(negedge clk);cancel=0;finish(1);block_read_accept=0;release_owner(6,6);
        $display("VALUE_UNACCEPTED_READ_CANCEL_PASS");

        // An earlier client's registered error is present while this client
        // waits for the grant, including its first exclusive acquisition edge.
        fabric_grant=0;inject_load_error=1;start(0,4,4,0,1,1,1,vectors[0]);
        repeat(3)@(negedge clk);
        if(rsp_valid || memory_load_valid || poisoned[4])$fatal(1,"VALUE_FOREIGN_ERROR_BEFORE_GRANT");
        fabric_grant=1;#1;
        if(!fabric_lock || memory_load_valid)$fatal(1,"VALUE_WRITE_ACQUISITION_NOT_IDLE");
        @(posedge clk);@(negedge clk);inject_load_error=0;
        while(!rsp_valid)@(negedge clk);
        if(fabric_lock)$fatal(1,"VALUE_WRITE_LOCK_NOT_RELEASED");
        fabric_grant=0;inject_load_error=1;finish(0,3);
        if(poisoned[4])$fatal(1,"VALUE_FOREIGN_ERROR_AFTER_COMMIT");
        fabric_grant=1;inject_load_error=0;start(1,4,4,0,0,1,0,0);finish(0);release_owner(4,4);
        $display("VALUE_FOREIGN_ERROR_HANDOFF_PASS");

        // Once a write has accepted, withdrawing its grant before its error
        // response is a protocol violation even if the global error bit is0.
        start(0,5,5,0,1,1,1,vectors[0]);
        while(!memory_load_valid || memory_address!=14)@(negedge clk);
        @(posedge clk);@(negedge clk);fabric_grant=0;
        @(negedge clk);$display("VALUE_FAULT n=%0d cause=grant_withdraw",accepted);
        fabric_grant=1;finish(1);release_owner(5,5);
        start(0,5,5,0,1,1,1,vectors[0]);finish(0);release_owner(5,5);
        $display("VALUE_WRITE_GRANT_VIOLATION_PASS");

        // Unsigned16 probabilities and signed8 values with signed32 wrap.
        for(int feature=0;feature<64;feature++)pattern[feature*8+:8]=feature%2?8'd127:8'h80;
        for(int key=0;key<263;key++)begin
            start(0,2,2,key,key==0,key==262,65535,pattern);finish(0);
        end
        start(1,2,2,262,0,1,0,0);finish(0);release_owner(2,2);
        $display("VALUE_SIGNED_WRAP_PASS updates=263");
        for(int owner=0;owner<20;owner++)begin
            for(int feature=0;feature<64;feature++)pattern[feature*8+:8]=8'((owner*7+feature*3)%255-127);
            start(0,owner,owner,0,1,1,16'(owner*1234+1),pattern);finish(0);
        end
        if(resident!==20'hfffff || completed!==20'hfffff || poisoned!==0)$fatal(1,"VALUE_TWENTY_CONTEXT_CAPACITY");
        for(int owner=0;owner<20;owner++)begin start(1,owner,owner,0,0,1,0,0);finish(0);release_owner(owner,owner);end
        if(resident!==0)$fatal(1,"VALUE_ALL_CONTEXTS_NOT_RELEASED");
        $display("VALUE_TWENTY_CONTEXTS_PASS contexts=20");
        if(responses!=accepted)$fatal(1,"VALUE_RESPONSE_COUNT");
        $display("VALUE_ACCUMULATOR_PASS trained_context_values=128");
        $display("VALUE_CHECKED_VALUES total=%0d requests=%0d",checked_values,accepted);
        $finish;
    end
    initial begin #2000000;$fatal(1,"VALUE_ACCUMULATOR_WATCHDOG");end
endmodule
