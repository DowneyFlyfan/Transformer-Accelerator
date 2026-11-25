`timescale 1ns/1ps
module tri_oracle_trained_head_prediction_tb;
    localparam int HEADS=32, ROWS=185, SEQUENCE=281, WIDTH=64, FIRST_QUERY=96;
    logic [31:0] TAG=32'h48500000;
    int frame_serial=0;
    localparam logic [63:0] QUERY_BASE=64'h10000, KEY_BASE=64'h200000;
    logic clk=0, rst_n=0;
    always #5 clk=~clk;
    logic cfg_valid=0, out_ready=0;
    wire cfg_ready, out_valid, out_error, out_streaming;
    logic [31:0] cfg_tag, cfg_alpha;
    logic [12:0] cfg_tokens;
    logic [7:0] cfg_ratio_num, cfg_ratio_den;
    logic [63:0] cfg_query_base, cfg_key_base;
    wire [31:0] out_tag;
    wire [17:0] out_inner, out_outer;

    wire tensor_cfg_valid, tensor_cfg_ready, tensor_out_valid, tensor_out_last, tensor_out_ready;
    wire tensor_done_valid, tensor_done_error, tensor_done_ready;
    wire [31:0] tensor_cfg_tag, tensor_out_tag, tensor_done_tag;
    wire [4:0] tensor_cfg_tokens;
    wire [16:0] tensor_cfg_dense_rows;
    wire [2559:0] tensor_cfg_channels, tensor_cfg_keep;
    wire [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base;
    wire [3:0] tensor_out_token;
    wire [7:0] tensor_out_count;
    wire [5119:0] tensor_results;
    wire [3071:0] tensor_out_data=tensor_results[3071:0];
    wire req_valid, req_ready, rsp_valid, rsp_ready, rsp_last, rsp_error;
    wire [63:0] req_address, rsp_data;
    wire [4:0] req_length;

    logic [7:0] queries[HEADS*ROWS*WIDTH], keys[4*SEQUENCE*WIDTH];
    logic [7:0] counts[HEADS*ROWS*2], types[HEADS];
    logic [31:0] alphas[HEADS];
    logic [63:0] read_address;
    logic reading=0, inject_request=0, fault_seen=0;
    bit fault_armed=0, invalid_case=0;
    int cycles=0, words_left, read_beat, accepted_batches, accepted_tensor, read_requests;
    int configured_tokens, next_position, prefill_batches=0, head_case;
    int active_first, active_count, raw_packets, score_beats, valid_scores;
    int trained_packets=0, trained_beats=0, trained_values=0;
    bit trained_phase=0, short_mode=0, corrupt_query=0;
    bit unknown_raw=0, unknown_result=0;
    string current_role="control";
    logic [31:0] score_gold[HEADS*ROWS*96];
    logic [7:0] score_masks[HEADS*ROWS*12];
    string fixture;

    wire [399:0] head_request;
    wire [72:0] head_response;
    logic [4:0] cfg_head_id;
    tri_oracle_attention_head_predictor415 #(.CORE_HEAD_PREDICTOR(1)) dut (.*);
    logic backend_rst_n,load_valid,load_error,backend_cmd_valid,backend_cmd_ready;
    wire [4:0] load_core,backend_clusters,backend_cmd_weight,backend_cmd_mask;
    wire [1:0] load_kind,backend_cmd_reduce;
    wire [9:0] load_addr,backend_cmd_activation;
    wire [2047:0] load_data;
    wire [31:0] load_row_enable;
    wire [3:0] backend_cmd_output;
    wire backend_cmd_accumulate;
    wire [2:0] backend_core_select;
    logic [4:0] backend_activation_reloaded,backend_out_valid,backend_out_ready;
    logic [19:0] backend_out_output;
    logic [5119:0] backend_out_data;
    `include "verilog/live_native_all_query_attention_frame/connection.svh"
    tri_oracle_external_tensor390 tensor (
        .clk,.rst_n,.cfg_valid(tensor_cfg_valid),.cfg_ready(tensor_cfg_ready),
        .cfg_paired(1'b0),.cfg_tag(tensor_cfg_tag),.cfg_tokens(tensor_cfg_tokens),
        .cfg_feature_words(10'd8),.cfg_dense_rows(tensor_cfg_dense_rows),.cfg_count(8'd96),
        .cfg_channels(tensor_cfg_channels),.cfg_keep(tensor_cfg_keep),
        .cfg_activation_base(tensor_cfg_activation_base),.cfg_weight_base(tensor_cfg_weight_base),
        .cfg_up_weight_base(64'd0),.cfg_activation_stride(32'd64),
        .out_valid(tensor_out_valid),.out_ready(tensor_out_ready),.out_tag(tensor_out_tag),
        .out_token(tensor_out_token),.out_last(tensor_out_last),.out_count(tensor_out_count),
        .out_channels(),.out_data(tensor_results),.done_valid(tensor_done_valid),
        .done_ready(tensor_done_ready),.done_error(tensor_done_error),.done_tag(tensor_done_tag),
        .req_valid,.req_ready,.req_address,.req_length,.rsp_valid,.rsp_ready,.rsp_last,.rsp_error,.rsp_data,
        .softmax_request('0),.backend_rst_n,.load_valid,.load_error,.load_core,.load_kind,.load_addr,
        .load_data,.load_row_enable,.backend_cmd_valid,.backend_cmd_ready,.backend_clusters,
        .backend_cmd_weight,.backend_cmd_mask,.backend_cmd_activation,.backend_cmd_output,
        .backend_cmd_accumulate,.backend_cmd_reduce,.backend_core_select,.backend_activation_reloaded,
        .backend_out_valid,.backend_out_ready,.backend_out_output,.backend_out_data
    );
    tri_oracle_compute_fabric #(.AGGREGATOR_SIGN_BANK(1),.AGGREGATOR_MERGE_TABLE(1),
        .LOCAL_TOKEN_SIZES(1),.LOCAL_TOKEN_MERGE(1),.CORE_STRIP_PREDICTOR(1),.CORE_HEAD_PREDICTOR(1)) fabric (
        .clk,.rst_n(physical_bus.rst_n),.load_valid(physical_bus.load_valid),.load_core(physical_bus.load_core),.load_kind(physical_bus.load_kind),.load_addr(physical_bus.load_addr),.load_data(physical_bus.load_data),.load_row_enable(physical_bus.load_rows),.load_error(physical_return.load_error),
        .cmd_valid(physical_bus.cmd_valid),.cmd_ready(physical_return.cmd_ready),.cmd_clusters(physical_bus.cmd_clusters),
        .cmd_weight(physical_bus.cmd_weight),.cmd_mask(physical_bus.cmd_mask),.cmd_activation(physical_bus.cmd_activation),
        .cmd_output(physical_bus.cmd_output),.cmd_accumulate(physical_bus.cmd_accumulate),.cmd_reduce(physical_bus.cmd_reduce),
        .core_score_select(physical_bus.core_select),.activation_reloaded(physical_bus.activation_reloaded),
        .out_valid(physical_return.out_valid),.out_ready(physical_bus.out_ready),.out_output(physical_return.out_output),.out_data(physical_return.out_data),
        .softmax_request(context_phase ? attention_softmax:'0),.softmax_response(physical_softmax_response),.merge_sign_data('0),.merge_sign_control('0),.merge_sign_counts(),
        .merge_table_request('0),.merge_table_word(),.token_sizes_request('0),.token_sizes_response(),
        .merge_request('0),.merge_response(),
        // Classifier lifetime spans tensor backend resets.
        .strip_rst_n(rst_n),.strip_request('0),.strip_response(),.head_request(context_phase ? 400'd0:head_request),.head_response
    );
    assign req_ready=!reading && cycles%7!=0;
    assign rsp_valid=reading;
    assign rsp_last=words_left==1;
    assign rsp_error=inject_request && read_beat==0;
    for (genvar byte_index=0; byte_index<8; byte_index++) begin : read_memory
        assign rsp_data[byte_index*8 +: 8]=read_address>=KEY_BASE ?
            keys[int'(read_address-KEY_BASE)+byte_index] : queries[int'(read_address-QUERY_BASE)+byte_index];
    end

    // Payload is meaningful only while its valid is known asserted. Poisoned
    // unaccepted configuration fields and masked data are deliberate don't-cares.
    always @(posedge clk) if (rst_n === 1'b1) begin
        if ($isunknown({cfg_valid,cfg_ready,out_valid,out_ready,
                        tensor_cfg_valid,tensor_cfg_ready,tensor_out_valid,tensor_out_ready,
                        tensor_done_valid,tensor_done_ready,req_valid,req_ready,rsp_valid,rsp_ready,
                        dut.batch_valid,dut.batch_ready,dut.score_valid,dut.score_ready}))
            $fatal(1,"HEAD_NATIVE_CONTROL_UNKNOWN");
        if (cfg_valid === 1'b1 && $isunknown({cfg_head_id,cfg_tokens,cfg_tag,cfg_alpha,
                                             cfg_ratio_num,cfg_ratio_den,cfg_query_base,cfg_key_base}))
            $fatal(1,"HEAD_NATIVE_CONFIGURATION_UNKNOWN");
        if (dut.batch_valid === 1'b1 && $isunknown({dut.batch_queries,dut.batch_query_first,
                    dut.batch_key_rows,dut.batch_tile_start,dut.batch_tag,dut.batch_query_addr,
                    dut.batch_key_base,dut.batch_last}))
            $fatal(1,"HEAD_NATIVE_BATCH_DESCRIPTOR_UNKNOWN");
        if (tensor_cfg_valid === 1'b1 && $isunknown({tensor_cfg_tag,tensor_cfg_tokens,
                    tensor_cfg_dense_rows,tensor_cfg_channels,tensor_cfg_keep,
                    tensor_cfg_activation_base,tensor_cfg_weight_base}))
            $fatal(1,"HEAD_NATIVE_TENSOR_CONFIGURATION_UNKNOWN");
        if (tensor_done_valid === 1'b1 && $isunknown({tensor_done_error,tensor_done_tag}))
            $fatal(1,"HEAD_NATIVE_TENSOR_DONE_UNKNOWN");
        if (rsp_valid === 1'b1) begin
            if ($isunknown({rsp_last,rsp_error})) $fatal(1,"HEAD_NATIVE_RESPONSE_DESCRIPTOR_UNKNOWN");
            if (rsp_error === 1'b0 && $isunknown(rsp_data)) $fatal(1,"HEAD_NATIVE_RESPONSE_DATA_UNKNOWN");
        end
        if (out_valid === 1'b1 && $isunknown({out_tag,out_error,out_streaming,out_inner,out_outer}))
            $fatal(1,"HEAD_NATIVE_RESULT_PAYLOAD_UNKNOWN");
    end

    always @(posedge clk) if (rst_n === 1'b1) begin
        cycles<=cycles+1;
        if (dut.batch_valid === 1'b1 && dut.batch_ready === 1'b1) begin
            int expected_count, recent;
            expected_count=configured_tokens-next_position;
            if (expected_count>16) expected_count=16;
            recent=next_position/32*32;
            if (invalid_case || expected_count<1 || dut.batch_queries!==5'(expected_count) ||
                dut.batch_query_first!==16'(next_position) || dut.batch_key_rows!==17'(configured_tokens) ||
                dut.batch_tile_start!=={16'(recent),16'(recent-64),16'd0} || dut.batch_tag!==TAG ||
                dut.batch_query_addr!==QUERY_BASE+64'((head_case*ROWS+next_position-FIRST_QUERY)*WIDTH) ||
                dut.batch_key_base!==KEY_BASE+64'((head_case/8)*SEQUENCE*WIDTH) ||
                dut.batch_last!==(next_position+expected_count==configured_tokens))
                $fatal(1,"BATCH415_BAD_SCHEDULE position=%0d count=%0d",next_position,expected_count);
            active_first=next_position;active_count=expected_count;
            accepted_batches++;
            next_position+=expected_count;
        end
        if (tensor_cfg_valid === 1'b1 && tensor_cfg_ready === 1'b1) accepted_tensor++;
        if (req_valid === 1'b1) begin
            if ($isunknown({req_address,req_length})) $fatal(1,"HEAD_NATIVE_REQUEST_DESCRIPTOR_UNKNOWN");
        end
        if (req_valid === 1'b1 && req_ready === 1'b1) begin
            logic second_query_batch;
            if (invalid_case || fault_seen || req_length==0 || req_length>2)
                $fatal(1,"BATCH415_UNEXPECTED_REQUEST addr=%h",req_address);
            second_query_batch=req_address>=QUERY_BASE+16*WIDTH && req_address<QUERY_BASE+32*WIDTH;
            if (fault_armed && second_query_batch) begin
                int inner_prefix, recent_prefix;
                inner_prefix=0; recent_prefix=0;
                for (int row=0; row<16; row++) begin
                    inner_prefix+=int'(counts[row*2]); recent_prefix+=int'(counts[row*2+1]);
                end
                if (accepted_batches!=2 || score_beats!=192)
                    $fatal(1,"BATCH415_ERROR_WITHOUT_CHECKED_PREFIX");
            end
            inject_request<=fault_armed && second_query_batch;
            fault_seen<=fault_armed && second_query_batch;
            reading<=1;
            read_address<=req_address;
            words_left<=int'(req_length);
            read_beat<=0;
            read_requests++;
        end else if (rsp_valid === 1'b1 && rsp_ready === 1'b1) begin
            reading<=!rsp_last;
            read_address<=read_address+64'd8;
            words_left<=words_left-1;
            read_beat<=read_beat+1;
        end
        if (out_valid === 1'b1 && reading === 1'b1) $fatal(1,"BATCH415_RESULT_BEFORE_READ_DRAIN");
    end

    task automatic configure(input int head, tokens, input logic [7:0] numerator, denominator,
                             input logic [63:0] query_base, key_base, input bit invalid, inject);
        @(negedge clk);
        head_case=head; configured_tokens=tokens; next_position=FIRST_QUERY;
        accepted_batches=0; accepted_tensor=0; read_requests=0;raw_packets=0;score_beats=0;valid_scores=0;
        TAG=trained_phase ? PredictionTag+32'(head):32'h48500000+32'(frame_serial);frame_serial++;
        fault_armed=inject; fault_seen=0; invalid_case=invalid;
        cfg_head_id=5'(head);
        cfg_valid=1; cfg_tokens=13'(tokens); cfg_tag=TAG; cfg_alpha=alphas[head];
        cfg_ratio_num=numerator; cfg_ratio_den=denominator;
        cfg_query_base=query_base; cfg_key_base=key_base;
        $display("HEAD_FRAME_BEGIN role=%s head=%0d tokens=%0d tag=%08h numerator=%0d denominator=%0d",current_role,head,tokens,TAG,numerator,denominator);
        @(posedge clk);
        if (cfg_ready !== 1'b1) $fatal(1,"BATCH415_BUSY");
        @(negedge clk);
        cfg_valid=0; cfg_head_id='x; cfg_tokens='x; cfg_tag='x; cfg_alpha='x;
        cfg_ratio_num='x; cfg_ratio_den='x; cfg_query_base='x; cfg_key_base='x;
    endtask

    task automatic finish_head(input int inner, recent, expected_batches, input bit streaming, error);
        while (out_valid !== 1'b1) begin
            if ($isunknown(out_valid)) $fatal(1,"HEAD_NATIVE_RESULT_VALID_UNKNOWN");
            @(negedge clk);
        end
        repeat (5) begin
            if (out_valid !== 1'b1 || cfg_ready !== 1'b0 || out_tag!==TAG || out_error!==error || out_streaming!==streaming ||
                out_inner!==18'(inner) || out_outer!==18'(recent) || accepted_batches!=expected_batches ||
                accepted_tensor!=expected_batches || (invalid_case && read_requests!=0) || (fault_armed && !fault_seen))
                $fatal(1,"BATCH415_RESULT batches=%0d inner=%0d recent=%0d streaming=%b error=%b",
                       accepted_batches,out_inner,out_outer,out_streaming,out_error);
            @(negedge clk);
        end
        out_ready=1;
        @(negedge clk);
        out_ready=0;
        if (cfg_ready !== 1'b1) $fatal(1,"BATCH415_OWNER_NOT_RELEASED");
        $display("HEAD_FRAME_END role=%s head=%0d tag=%08h inner=%0d recent=%0d streaming=%0d error=%0d batches=%0d raw_packets=%0d beats=%0d values=%0d",current_role,head_case,TAG,inner,recent,streaming,error,accepted_batches,raw_packets,score_beats,valid_scores);
    endtask


    always @(posedge clk) if(rst_n === 1'b1) begin
        // Establish known descriptors before casts, bounds or indexed references.
        if(tensor_out_valid === 1'b1 && $isunknown({tensor_out_token,tensor_out_last,
                                                  tensor_out_tag,tensor_out_count}))
            $fatal(1,"HEAD_NATIVE_RAW_DESCRIPTOR_UNKNOWN");
        if(tensor_out_valid === 1'b1 && tensor_out_ready === 1'b1)begin
            int query,index,mask_index;
            if($isunknown({active_first,active_count,head_case,configured_tokens}) ||
               active_count<1 || head_case<0 || head_case>=HEADS ||
               int'(tensor_out_token)>=active_count)$fatal(1,"HEAD_NATIVE_RAW_INDEX");
            query=active_first+int'(tensor_out_token);
            if(tensor_out_tag!==TAG || tensor_out_count!==96 || query<FIRST_QUERY || query>=configured_tokens ||
               tensor_out_last!==(int'(tensor_out_token)==active_count-1))$fatal(1,"HEAD_NATIVE_RAW_DESCRIPTOR");
            $display("HEAD_TENSOR_PACKET tick=%0d role=%s head=%0d query=%0d tag=%08h data=%0768h",$time,current_role,head_case,query,TAG,tensor_out_data);
            raw_packets++;
            if(trained_phase)trained_packets++;
            for(int lane=0;lane<96;lane++)begin
                index=(head_case*ROWS+query-FIRST_QUERY)*96+lane;
                mask_index=(head_case*ROWS+query-FIRST_QUERY)*12+lane/8;
                if(score_masks[mask_index][lane%8] && tensor_out_data[lane*32+:32]!==score_gold[index])begin
                    if(corrupt_query)$display("HEAD_CORRUPTION_DOT_DIFFERENCE head=%0d query=%0d slot=%0d expected=%0d actual=%0d",head_case,query,lane,$signed(score_gold[index]),$signed(tensor_out_data[lane*32+:32]));
                    $fatal(1,"HEAD_NATIVE_RAW_DOT_VALUE head=%0d query=%0d slot=%0d",head_case,query,lane);
                end
            end
        end
        if(dut.score_valid === 1'b1)begin
            if($isunknown({dut.score_error,dut.score_tag,dut.score_region,dut.score_lanes,dut.score_last}))
                $fatal(1,"HEAD_NATIVE_SCORE_DESCRIPTOR_UNKNOWN");
            if(dut.score_error === 1'b0 && $isunknown({dut.tile.first_query,dut.tile.token_index,
                                                      dut.tile.score_beat,head_case,configured_tokens}))
                $fatal(1,"HEAD_NATIVE_SCORE_INDEX_UNKNOWN");
        end
        if(dut.score_valid === 1'b1 && dut.score_ready === 1'b1)begin
            if(dut.score_error === 1'b1)begin
                if(!fault_armed)$fatal(1,"HEAD_UNEXPECTED_SCORE_ERROR");
            end else begin
                int query,region,beat,index,mask_index;
                query=int'(dut.tile.first_query)+int'(dut.tile.token_index);
                region=int'(dut.score_region);beat=int'(dut.tile.score_beat[1:0]);
                if(head_case<0 || head_case>=HEADS || region<0 || region>=3 ||
                   int'(dut.tile.score_beat)>=12 || query<FIRST_QUERY || query>=configured_tokens ||
                   query>=SEQUENCE)$fatal(1,"HEAD_CLASSIFIER_INDEX");
                mask_index=(head_case*ROWS+query-FIRST_QUERY)*12+region*4+beat;
                if(dut.score_tag!==TAG || region>=3 || query<FIRST_QUERY || query>=configured_tokens ||
                   dut.score_lanes!==score_masks[mask_index])$fatal(1,"HEAD_CLASSIFIER_DESCRIPTOR");
                $display("HEAD_CLASSIFIER_BEAT role=%s head=%0d query=%0d tag=%08h region=%0d beat=%0d mask=%02h data=%064h",current_role,head_case,query,TAG,region,beat,dut.score_lanes,dut.score_data);
                score_beats++;
                if(trained_phase)trained_beats++;
                for(int lane=0;lane<8;lane++)if(dut.score_lanes[lane])begin
                    index=(head_case*ROWS+query-FIRST_QUERY)*96+region*32+beat*8+lane;
                    if(dut.score_data[lane*32+:32]!==score_gold[index])$fatal(1,"HEAD_CLASSIFIER_SCORE_VALUE");
                    valid_scores++;if(trained_phase)trained_values++;
                end
            end
        end
    end
    initial begin
        #3;
        if($root.tri_oracle_complete_memory_inventory.total_count!=621 ||
           $root.tri_oracle_complete_memory_inventory.total_bits!=64'd3249792)$fatal(1,"HEAD_MEMORY_LAYOUT");
        $display("COMPLETE_MEMORY_CENSUS_PASS clocks=0");
    end

    initial begin
        int inner, recent;
        if (!$value$plusargs("FIXTURE=%s",fixture)) $fatal(1,"BATCH415_FIXTURE_REQUIRED");
        load_native_cache_for_prediction();
        $readmemh({fixture,"/alpha.hex"},alphas);
        $readmemh({fixture,"/counts.hex"},counts);
        $readmemh({fixture,"/streaming.hex"},types);
        $readmemh({fixture,"/scores.hex"},score_gold);
        $readmemh({fixture,"/masks.hex"},score_masks);
        short_mode=$test$plusargs("SHORT_HEADS");
        corrupt_query=$test$plusargs("CORRUPT_QUERY");
        unknown_raw=$test$plusargs("HEAD_X_RAW_DESCRIPTOR");
        unknown_result=$test$plusargs("HEAD_X_RESULT_HANDSHAKE");
        if(int'(corrupt_query)+int'(unknown_raw)+int'(unknown_result)>1)
            $fatal(1,"HEAD_CONTROL_MODES_EXCLUSIVE");
        repeat (3) @(negedge clk);
        rst_n=1;
        if(unknown_raw)begin
            current_role="unknown_raw";
            configure(0,97,8,1,QUERY_BASE,KEY_BASE,0,0);
            while(tensor_out_valid !== 1'b1)begin
                if($isunknown(tensor_out_valid))$fatal(1,"HEAD_UNKNOWN_RAW_ARM_FAILED");
                @(negedge clk);
            end
            if(tensor_out_ready !== 1'b1)$fatal(1,"HEAD_UNKNOWN_RAW_NOT_READY");
            $display("HEAD_UNKNOWN_INJECTED role=raw token=x last=x");
            force tensor_out_token=4'bxxxx;
            force tensor_out_last=1'bx;
            @(posedge clk); #1;
            $fatal(1,"HEAD_UNKNOWN_RAW_NOT_REJECTED");
        end
        if(unknown_result)begin
            current_role="unknown_result";
            configure(0,97,8,1,QUERY_BASE,KEY_BASE,0,0);
            while(out_valid !== 1'b1)begin
                if($isunknown(out_valid))$fatal(1,"HEAD_UNKNOWN_RESULT_ARM_FAILED");
                @(negedge clk);
            end
            $display("HEAD_UNKNOWN_INJECTED role=result valid=x ready=x");
            force out_valid=1'bx;
            force cfg_ready=1'bx;
            #1;
            if(out_valid !== 1'bx || cfg_ready !== 1'bx)
                $fatal(1,"HEAD_UNKNOWN_RESULT_FORCE_NOT_ARMED");
            inner=int'(counts[0]);recent=int'(counts[1]);
            finish_head(inner,recent,1,recent>8*inner,0);
            $fatal(1,"HEAD_UNKNOWN_RESULT_NOT_REJECTED");
        end
        if(corrupt_query)begin
            int feature;
            logic[7:0] before_value;
            feature=-1;
            for(int lane=0;lane<64;lane++)if(feature<0 && keys[lane]!=0)feature=lane;
            if(feature<0)$fatal(1,"HEAD_CORRUPTION_FEATURE_MISSING");
            before_value=queries[feature];queries[feature]=before_value^8'd1;
            $display("HEAD_INPUT_CORRUPTED head=0 query=96 feature=%0d before=%02h after=%02h key=%0d",feature,before_value,queries[feature],$signed(keys[feature]));
            current_role="corrupt";
            configure(0,97,8,1,QUERY_BASE,KEY_BASE,0,0);
            while(out_valid !== 1'b1)begin
                if($isunknown(out_valid))$fatal(1,"HEAD_NATIVE_RESULT_VALID_UNKNOWN");
                @(negedge clk);
            end
            $fatal(1,"HEAD_CORRUPTION_NOT_OBSERVED");
        end
        configure(0,96,1,1,QUERY_BASE,KEY_BASE,1,0);
        finish_head(0,0,0,0,1);
        configure(0,4193,1,1,QUERY_BASE,KEY_BASE,1,0);
        finish_head(0,0,0,0,1);
        configure(0,SEQUENCE,1,0,QUERY_BASE,KEY_BASE,1,0);
        finish_head(0,0,0,0,1);
        configure(0,SEQUENCE,1,1,QUERY_BASE+1,KEY_BASE,1,0);
        finish_head(0,0,0,0,1);
        configure(0,97,1,1,64'hffffffffffffffc8,KEY_BASE,1,0);
        finish_head(0,0,0,0,1);
        configure(0,97,1,1,QUERY_BASE,64'hfffffffffffffff8,1,0);
        finish_head(0,0,0,0,1);
        inner=0;recent=0;
        for(int row=0;row<ROWS;row++)begin
            inner+=int'(counts[(6*ROWS+row)*2]);recent+=int'(counts[(6*ROWS+row)*2+1]);
        end
        if(inner<=0 || recent<=0 || recent>8*inner)$fatal(1,"HEAD_RATIO_CONTROL_CHANGED");
        current_role="ratio";
        configure(6,SEQUENCE,0,1,QUERY_BASE+64'(6*ROWS*WIDTH),KEY_BASE+64'((6/8)*SEQUENCE*WIDTH),0,0);
        finish_head(inner,recent,12,1,0);
        current_role="late_abort";
        configure(0,SEQUENCE,1,1,QUERY_BASE,KEY_BASE,0,1);
        finish_head(0,0,2,0,1);

        begin_prediction_mask();
        trained_phase=1;current_role="trained";
        for (int head=0; head<HEADS; head++) begin
            int rows;
            rows=short_mode?1:ROWS;inner=0;recent=0;
            for(int row=0;row<rows;row++)begin
                inner+=int'(counts[(head*ROWS+row)*2]);recent+=int'(counts[(head*ROWS+row)*2+1]);
            end
            if(!short_mode && types[head][0] !== (recent>8*inner))$fatal(1,"HEAD_EXPECTED_LABEL_CHANGED");
            configure(head,FIRST_QUERY+rows,8,1,QUERY_BASE+64'(head*ROWS*WIDTH),
                      KEY_BASE+64'((head/8)*SEQUENCE*WIDTH),0,0);
            finish_head(inner,recent,(rows+15)/16,recent>8*inner,0);
        end
        trained_phase=0;
        if(short_mode)begin
            if(trained_packets!=32 || trained_beats!=384 || trained_values!=2080)$fatal(1,"HEAD_SHORT_COVERAGE");
            $display("HEAD_NATIVE_SHORT_PASS heads=32 rows=1 packets=32 beats=384 values=2080");
        end else begin
            if(trained_packets!=5920 || trained_beats!=71040 || trained_values!=473760)$fatal(1,"HEAD_FULL_COVERAGE");
            $display("HEAD_NATIVE_FULL_PASS heads=32 rows=185 packets=5920 beats=71040 values=473760");
        end
        run_predicted_attention();
        $finish;
    end
    initial begin #(64'd4000000000); $fatal(1,"BATCH415_WATCHDOG"); end
endmodule
