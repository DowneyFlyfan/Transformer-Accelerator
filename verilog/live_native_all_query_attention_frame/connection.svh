    localparam logic [31:0] PredictionTag=32'h48500020;
    localparam logic [15:0] PredictionEpoch=16'h5a19;
    `include "verilog/live_native_all_query_attention_frame/configuration.svh"
    logic mask_cfg_valid=0,mask_cfg_ready,mask_result_ready;
    logic mask_valid,mask_ready,mask_error;
    logic [31:0] mask_heads,mask_streaming,mask_tag;
    logic [15:0] mask_epoch;
    logic context_phase=0,a_collection_seen=0,a_query_active=0;
    logic a_mask_saved=0,a_cfg_valid=0,a_done_ready=0;
    logic [31:0] a_saved_heads=0,a_saved_tag=0,a_committed_mask=0;
    logic [15:0] a_saved_epoch=0,a_query=0;
    logic [31:0] a_query_tag;
    logic [10:0] a_visible;
    logic [511:0] native_cache[40*281];
    logic native_cache_loaded=0,corrupt_early_size=0;
    string native_cache_root,context_root;
    tri_oracle_head_mask_commit mask_commit (
        .clk,.rst_n,.cancel(1'b0),.cfg_valid(mask_cfg_valid),.cfg_ready(mask_cfg_ready),
        .cfg_heads(32'hffffffff),.cfg_tag(PredictionTag),.cfg_epoch(PredictionEpoch),
        .result_valid(trained_phase && out_valid && out_ready),.result_ready(mask_result_ready),
        .result_head(out_tag[4:0]),.result_tag(out_tag),.result_error(out_error),.result_streaming(out_streaming),
        .mask_valid,.mask_ready,.mask_heads,.mask_streaming,.mask_tag,.mask_epoch,.mask_error
    );
    tri_oracle_fabric_owner_types::request_t predictor_bus,attention_bus,physical_bus;
    tri_oracle_fabric_owner_types::response_t physical_return;
    tri_oracle_wac_softmax_types::request_t attention_softmax;
    tri_oracle_wac_softmax_types::response_t attention_softmax_response,physical_softmax_response;
    logic a_cfg_ready,a_busy,a_done,a_error,a_reset,a_collected;
    logic [7:0] a_error_code;
    logic a_req_valid,a_req_ready,a_rsp_valid=0,a_rsp_ready,a_serving=0;
    logic [1:0] a_req_kind,a_rsp_kind=0;
    logic [4:0] a_req_head,a_rsp_head=0;
    logic [9:0] a_req_key,a_rsp_key=0,a_rsp_size=0;
    logic [15:0] a_req_query,a_req_epoch,a_rsp_query=0,a_rsp_epoch=0;
    logic [31:0] a_req_tag,a_rsp_tag=0;
    logic [511:0] a_rsp_data=0;
    logic [2047:0] a_gold[281*32],a_context_data;
    logic [9:0] a_sizes[281*281];
    logic a_context_valid,a_context_ready;
    logic [4:0] a_context_head;
    logic [15:0] a_context_query,a_context_epoch;
    logic [31:0] a_context_tag,a_seen=0;
    logic signed [7:0] a_context_exponent;
    logic a_context_held=0,a_response_held=0,a_request_held=0;
    logic [2124:0] a_held_context;
    logic [602:0] a_held_response;
    logic [80:0] a_held_request;
    int a_delay=0,a_values_read=0,a_keys_read=0,a_queries_read=0,a_contexts=0;
    int a_total_values=0,a_total_keys=0,a_total_queries=0,a_total_contexts=0;
    int a_head_keys[32],a_head_values[32],a_head_queries[32];
    always_comb begin
        predictor_bus='0;
        predictor_bus.rst_n=backend_rst_n;
        predictor_bus.load_valid=load_valid;predictor_bus.load_core=load_core;
        predictor_bus.load_kind=load_kind;predictor_bus.load_addr=load_addr;
        predictor_bus.load_data=load_data;predictor_bus.load_rows=load_row_enable;
        predictor_bus.cmd_valid=backend_cmd_valid;predictor_bus.cmd_clusters=backend_clusters;
        predictor_bus.cmd_weight=backend_cmd_weight;predictor_bus.cmd_mask=backend_cmd_mask;
        predictor_bus.cmd_activation=backend_cmd_activation;predictor_bus.cmd_output=backend_cmd_output;
        predictor_bus.cmd_accumulate=backend_cmd_accumulate;predictor_bus.cmd_reduce=backend_cmd_reduce;
        predictor_bus.core_select=backend_core_select;predictor_bus.activation_reloaded=backend_activation_reloaded;
        predictor_bus.out_ready=backend_out_ready;
        physical_bus=context_phase ? attention_bus:predictor_bus;
        load_error=!context_phase && physical_return.load_error;
        backend_cmd_ready=!context_phase && physical_return.cmd_ready;
        backend_out_valid=context_phase ? '0:physical_return.out_valid;
        backend_out_output=physical_return.out_output;backend_out_data=physical_return.out_data;
        attention_softmax_response=context_phase ? physical_softmax_response:'0;
        a_req_ready=context_phase && a_query_active && !a_serving && !a_rsp_valid && cycles%5!=0;
        a_context_ready=context_phase && a_query_active && cycles%7!=0;
        mask_ready=context_phase && !a_mask_saved && !mask_error;
        a_query_tag=a_saved_tag+32'(a_query);
        a_visible=11'(a_query)+11'd1;
    end
    tri_oracle_complete_head_broker attention (
        .clk,.rst_n,.cfg_valid(a_cfg_valid && a_mask_saved),.cfg_ready(a_cfg_ready),
        .cfg_heads(a_saved_heads),.cfg_streaming(a_committed_mask),.cfg_total_keys(11'd281),.cfg_visible_keys(a_visible),
        .cfg_score_shifts(ATTENTION_SHIFTS),.cfg_value_exponents(ATTENTION_EXPONENTS),
        .cfg_query(a_query),.cfg_epoch(a_saved_epoch),.cfg_tag(a_query_tag),.cancel(1'b0),
        .tensor_req_valid(a_req_valid),.tensor_req_ready(a_req_ready),.tensor_req_kind(a_req_kind),
        .tensor_req_head(a_req_head),.tensor_req_key(a_req_key),.tensor_req_query(a_req_query),
        .tensor_req_epoch(a_req_epoch),.tensor_req_tag(a_req_tag),
        .tensor_rsp_valid(a_rsp_valid),.tensor_rsp_ready(a_rsp_ready),.tensor_rsp_error(1'b0),
        .tensor_rsp_kind(a_rsp_kind),.tensor_rsp_head(a_rsp_head),.tensor_rsp_key(a_rsp_key),.tensor_rsp_size(a_rsp_size),
        .tensor_rsp_query(a_rsp_query),.tensor_rsp_epoch(a_rsp_epoch),.tensor_rsp_tag(a_rsp_tag),
        .tensor_rsp_value_exponent(-8'sd5),.tensor_rsp_data(a_rsp_data),
        .context_valid(a_context_valid),.context_ready(a_context_ready),.context_head(a_context_head),
        .context_query(a_context_query),.context_epoch(a_context_epoch),.context_tag(a_context_tag),
        .context_value_exponent(a_context_exponent),.context_data(a_context_data),
        .all_contexts_collected(a_collected),.done_valid(a_done),.done_ready(a_done_ready),
        .done_error(a_error),.reset_required(a_reset),.busy(a_busy),.error_code(a_error_code),
        .fabric_load_valid(attention_bus.load_valid),.fabric_load_error(physical_return.load_error),
        .fabric_load_core(attention_bus.load_core),.fabric_load_kind(attention_bus.load_kind),
        .fabric_load_addr(attention_bus.load_addr),.fabric_load_data(attention_bus.load_data),
        .fabric_load_rows(attention_bus.load_rows),.fabric_activation_reloaded(attention_bus.activation_reloaded),
        .fabric_cmd_valid(attention_bus.cmd_valid),.fabric_cmd_ready(physical_return.cmd_ready && context_phase),
        .fabric_cmd_clusters(attention_bus.cmd_clusters),.fabric_cmd_weight(attention_bus.cmd_weight),
        .fabric_cmd_mask(attention_bus.cmd_mask),.fabric_cmd_activation(attention_bus.cmd_activation),
        .fabric_cmd_output(attention_bus.cmd_output),.fabric_cmd_accumulate(attention_bus.cmd_accumulate),
        .fabric_cmd_reduce(attention_bus.cmd_reduce),.fabric_core_select(attention_bus.core_select),
        .fabric_out_valid(context_phase ? physical_return.out_valid:5'd0),.fabric_out_ready(attention_bus.out_ready),
        .fabric_out_slot(physical_return.out_output),.fabric_out_data(physical_return.out_data),
        .softmax_request(attention_softmax),.softmax_response(attention_softmax_response)
    );
    always_comb attention_bus.rst_n=rst_n;
    task automatic load_native_cache_for_prediction;
        if(!$value$plusargs("NATIVE_CACHE_ROOT=%s",native_cache_root))$fatal(1,"ALL_NATIVE_CACHE_REQUIRED");
        $readmemh({native_cache_root,"/native_cache.hex"},native_cache);
        for(int slot=0;slot<40*281;slot++)if($isunknown(native_cache[slot]))$fatal(1,"ALL_NATIVE_CACHE_UNKNOWN slot=%0d",slot);
        for(int h=0;h<32;h++)for(int t=96;t<281;t++)for(int i=0;i<64;i++)queries[(h*185+t-96)*64+i]=native_cache[h*281+t][i*8+:8];
        for(int h=0;h<4;h++)for(int t=0;t<281;t++)for(int i=0;i<64;i++)keys[(h*281+t)*64+i]=native_cache[(32+h)*281+t][i*8+:8];
        native_cache_loaded=1;
        $display("ALL_NATIVE_CACHE_RESTORED tick=%0t vectors=11240 bytes=719360",$time);
    endtask
    function automatic logic [511:0] attention_operand(input int kind,head,key);
        int source_head,source_token;
        source_head=kind==0 ? head:32+(kind-1)*4+head/8;
        source_token=kind==0 ? int'(a_query):key;
        if(!native_cache_loaded || source_head<0 || source_head>=40 || source_token<0 || source_token>=281)
            $fatal(1,"ALL_NATIVE_CACHE_READ_BOUNDS");
        return native_cache[source_head*281+source_token];
    endfunction
    always @(posedge clk)if(rst_n)begin
        if(trained_phase && out_valid && out_ready && !mask_result_ready)$fatal(1,"ALL_MASK_RESULT_DROPPED");
        if(mask_valid && mask_ready)begin
            if(a_mask_saved || mask_heads!==32'hffffffff || mask_streaming!==32'hfd6c64bf ||
               mask_tag!==PredictionTag || mask_epoch!==PredictionEpoch || mask_error)$fatal(1,"ALL_MASK_COMMIT_WRONG");
            a_mask_saved<=1;a_saved_heads<=mask_heads;a_committed_mask<=mask_streaming;
            a_saved_tag<=mask_tag;a_saved_epoch<=mask_epoch;
            $display("PREDICTED_MASK_ACCEPT tick=%0t heads=%08h streaming=%08h tag=%08h epoch=%04h",$time,mask_heads,mask_streaming,mask_tag,mask_epoch);
        end
        if(context_phase)begin
            if($isunknown({a_cfg_valid,a_cfg_ready,a_done,a_error,a_reset,a_busy,a_req_valid,a_req_ready,a_rsp_valid,a_rsp_ready,a_context_valid,a_context_ready}))$fatal(1,"ALL_ATTENTION_UNKNOWN_CONTROL");
            if(a_cfg_valid && a_cfg_ready)$display("ALL_QUERY_CONFIG tick=%0t query=%0d visible=%0d epoch=%04h tag=%08h heads=%08h streaming=%08h",$time,a_query,a_visible,a_saved_epoch,a_query_tag,a_saved_heads,a_committed_mask);
            if(a_request_held && (!a_req_valid || {a_req_kind,a_req_head,a_req_key,a_req_query,a_req_epoch,a_req_tag}!==a_held_request))$fatal(1,"ALL_REQUEST_CHANGED_WHILE_STALLED");
            a_request_held<=a_req_valid && !a_req_ready;
            if(a_req_valid && !a_req_ready)a_held_request<={a_req_kind,a_req_head,a_req_key,a_req_query,a_req_epoch,a_req_tag};
            if(a_response_held && (!a_rsp_valid || {a_rsp_kind,a_rsp_head,a_rsp_key,a_rsp_query,a_rsp_epoch,a_rsp_tag,a_rsp_size,a_rsp_data}!==a_held_response))$fatal(1,"ALL_RESPONSE_CHANGED_WHILE_STALLED");
            a_response_held<=a_rsp_valid && !a_rsp_ready;
            if(a_rsp_valid && !a_rsp_ready)a_held_response<={a_rsp_kind,a_rsp_head,a_rsp_key,a_rsp_query,a_rsp_epoch,a_rsp_tag,a_rsp_size,a_rsp_data};
            if(a_context_held && (!a_context_valid || {a_context_head,a_context_query,a_context_epoch,a_context_tag,a_context_exponent,a_context_data}!==a_held_context))$fatal(1,"ALL_CONTEXT_CHANGED_WHILE_STALLED");
            a_context_held<=a_context_valid && !a_context_ready;
            if(a_context_valid && !a_context_ready)a_held_context<={a_context_head,a_context_query,a_context_epoch,a_context_tag,a_context_exponent,a_context_data};
        end
        if(a_query_active && a_collected)begin
            if(!a_collection_seen)$display("ALL_QUERY_ARCHIVED tick=%0t query=%0d",$time,a_query);
            a_collection_seen<=1;
        end
        if(a_req_valid && a_req_ready)begin
            if(!a_query_active || $isunknown({a_req_kind,a_req_head,a_req_key,a_req_query,a_req_epoch,a_req_tag}) ||
               a_req_kind>2 || a_req_key>=a_visible || a_req_query!==a_query ||
               a_req_epoch!==a_saved_epoch || a_req_tag!==a_query_tag)$fatal(1,"ALL_ATTENTION_REQUEST_DESCRIPTOR");
            if(a_req_kind!=0 && a_committed_mask[a_req_head] && a_visible>64 && a_req_key>=32 && a_req_key<a_visible-32)$fatal(1,"ALL_ATTENTION_SKIPPED_KEY_REQUESTED");
            a_rsp_kind<=a_req_kind;a_rsp_head<=a_req_head;a_rsp_key<=a_req_key;
            a_rsp_query<=a_req_query;a_rsp_epoch<=a_req_epoch;a_rsp_tag<=a_req_tag;
            a_rsp_size<=a_req_kind==1 ? a_sizes[int'(a_query)*281+int'(a_req_key)]:10'd1;
            a_rsp_data<=attention_operand(int'(a_req_kind),int'(a_req_head),int'(a_req_key));
            a_serving<=1;a_delay<=2+cycles%3;
            if(a_req_kind==0)begin a_queries_read++;a_head_queries[a_req_head]++;end
            if(a_req_kind==1)begin a_keys_read++;a_head_keys[a_req_head]++;end
            if(a_req_kind==2)begin a_values_read++;a_head_values[a_req_head]++;end
            $display("ALL_TENSOR_REQUEST tick=%0t query=%0d kind=%0d head=%0d key=%0d epoch=%04h tag=%08h",$time,a_req_query,a_req_kind,a_req_head,a_req_key,a_req_epoch,a_req_tag);
        end
        if(a_serving)begin
            if(a_delay==0)begin a_serving<=0;a_rsp_valid<=1;end
            else a_delay<=a_delay-1;
        end
        if(a_rsp_valid && a_rsp_ready)begin
            a_rsp_valid<=0;
            $display("ALL_TENSOR_RESPONSE tick=%0t query=%0d kind=%0d head=%0d key=%0d epoch=%04h tag=%08h size=%0d exponent=-5 data=%0128h",$time,a_rsp_query,a_rsp_kind,a_rsp_head,a_rsp_key,a_rsp_epoch,a_rsp_tag,a_rsp_size,a_rsp_data);
        end
        if(a_context_valid)begin
            if(!a_query_active || !a_collection_seen || $isunknown({a_context_head,a_context_query,a_context_epoch,a_context_tag,a_context_data,a_context_exponent}) ||
               a_context_data!==a_gold[int'(a_query)*32+int'(a_context_head)] || a_seen[a_context_head] ||
               a_context_query!==a_query || a_context_epoch!==a_saved_epoch || a_context_tag!==a_query_tag || a_context_exponent!==-8'sd5)$fatal(1,"ALL_ATTENTION_CONTEXT_WRONG query=%0d head=%0d",a_query,a_context_head);
            if(a_context_ready)begin
                a_seen[a_context_head]<=1;a_contexts++;
                $display("ALL_CONTEXT_VALUE tick=%0t query=%0d head=%0d epoch=%04h tag=%08h exponent=%0d data=%0512h",$time,a_context_query,a_context_head,a_context_epoch,a_context_tag,$signed(a_context_exponent),a_context_data);
            end
        end
        if(a_done && a_error)$fatal(1,"ALL_ATTENTION_FAILED query=%0d code=%0d",a_query,a_error_code);
    end
    task automatic begin_prediction_mask;
        @(negedge clk);
        if(mask_cfg_ready!==1'b1)$fatal(1,"ALL_MASK_NOT_IDLE");
        mask_cfg_valid=1;@(negedge clk);mask_cfg_valid=0;
    endtask
    task automatic run_predicted_attention;
        if(short_mode || mask_valid!==1'b1 || mask_error || reading || tensor_out_valid || tensor_done_valid)$fatal(1,"ALL_ATTENTION_INCOMPLETE_PREDICTION");
        $display("PREDICTED_ATTENTION_BEGIN tick=%0t",$time);
        @(negedge clk);context_phase=1;
        while(!a_mask_saved)@(negedge clk);
        for(int query=0;query<281;query++)begin
            while(a_done || a_busy || !a_cfg_ready)@(negedge clk);
            a_query=16'(query);a_collection_seen=0;a_seen=0;a_contexts=0;
            a_values_read=0;a_keys_read=0;a_queries_read=0;
            for(int head=0;head<32;head++)begin a_head_keys[head]=0;a_head_values[head]=0;a_head_queries[head]=0;end
            if(corrupt_early_size && query==5)begin
                if(a_sizes[5*281+5]==a_sizes[280*281+5])$fatal(1,"ALL_CAUSAL_SIZE_CORRUPTION_NOT_ARMED");
                $display("ALL_CAUSAL_SIZE_CORRUPTED query=5 key=5 before=%0d after=%0d",a_sizes[5*281+5],a_sizes[280*281+5]);
                a_sizes[5*281+5]=a_sizes[280*281+5];
            end
            @(negedge clk);a_cfg_valid=1;
            do @(posedge clk);while(!a_cfg_ready);
            @(negedge clk);a_cfg_valid=0;a_query_active=1;
            while(!a_done)@(negedge clk);
            if(a_error || a_reset || !a_collection_seen || a_seen!==32'hffffffff || a_contexts!=32 || a_serving || a_rsp_valid || a_context_valid || a_req_valid)$fatal(1,"ALL_ATTENTION_QUERY_COVERAGE query=%0d",query);
            for(int head=0;head<32;head++)begin
                int expected;
                expected=a_committed_mask[head] && query>=64 ? 64:query+1;
                if(a_head_keys[head]!=expected || a_head_values[head]!=expected || a_head_queries[head]!=(expected+31)/32)$fatal(1,"ALL_ATTENTION_HEAD_COVERAGE query=%0d head=%0d",query,head);
            end
            $display("ALL_QUERY_DONE tick=%0t query=%0d head_words=%0d keys=%0d values=%0d query_tiles=%0d",$time,query,a_contexts,a_keys_read,a_values_read,a_queries_read);
            a_total_contexts+=a_contexts;a_total_keys+=a_keys_read;a_total_values+=a_values_read;a_total_queries+=a_queries_read;
            a_done_ready=1;@(negedge clk);a_done_ready=0;a_query_active=0;
            if(a_done || a_busy || !a_cfg_ready)$fatal(1,"ALL_ATTENTION_QUERY_NOT_RETIRED query=%0d",query);
            $display("ALL_QUERY_RETIRED tick=%0t query=%0d",$time,query);
        end
        if(a_total_contexts!=8992 || a_total_keys!=771159 || a_total_values!=771159)$fatal(1,"ALL_ATTENTION_TOTAL_COVERAGE");
        repeat(3)@(negedge clk);
        $display("ALL_ATTENTION_FULL_PASS queries=281 heads=32 head_words=8992 context_values=575488 keys=771159 values=771159 query_tiles=%0d streaming=%08h",a_total_queries,a_committed_mask);
    endtask
    initial begin
        if(!$value$plusargs("ALL_CONTEXT_ROOT=%s",context_root))$fatal(1,"ALL_ATTENTION_FIXTURE_REQUIRED");
        $readmemh({context_root,"/expected_context.hex"},a_gold);
        $readmemh({context_root,"/sizes.hex"},a_sizes);
        corrupt_early_size=$test$plusargs("CORRUPT_EARLY_IMAGE_SIZE");
        for(int row=0;row<281*32;row++)if($isunknown(a_gold[row]))$fatal(1,"ALL_CONTEXT_REFERENCE_UNKNOWN");
        for(int slot=0;slot<281*281;slot++)if($isunknown(a_sizes[slot]))$fatal(1,"ALL_CAUSAL_SIZES_UNKNOWN");
        for(int head=0;head<32;head++)begin a_head_keys[head]=0;a_head_values[head]=0;a_head_queries[head]=0;end
    end
