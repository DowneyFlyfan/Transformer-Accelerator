    localparam logic [31:0] PredictionTag=32'h48500020;
    localparam logic [15:0] PredictionEpoch=16'h5a19;
    `include "verilog/live_predicted_attention_frame/configuration.svh"
    logic mask_cfg_valid=0,mask_cfg_ready,mask_result_ready;
    logic mask_valid,mask_ready,mask_error;
    logic [31:0] mask_heads,mask_streaming,mask_tag;
    logic [15:0] mask_epoch;
    logic context_phase=0,a_collection_seen=0;
    tri_oracle_head_mask_commit mask_commit (
        .clk,.rst_n,.cancel(1'b0),.cfg_valid(mask_cfg_valid),.cfg_ready(mask_cfg_ready),
        .cfg_heads(32'hffffffff),.cfg_tag(PredictionTag),.cfg_epoch(PredictionEpoch),
        // Consume exactly the predictor's accepted result, after its held
        // output checks. Controls preceding the trained frame are excluded.
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
    logic [511:0] a_rsp_data=0,a_values[1124];
    logic [2047:0] a_gold[32],a_context_data;
    logic [9:0] a_sizes[281];
    logic a_context_valid,a_context_ready;
    logic [4:0] a_context_head;
    logic [15:0] a_context_query,a_context_epoch;
    logic [31:0] a_context_tag,a_seen=0,a_committed_mask=0;
    logic signed [7:0] a_context_exponent;
    int a_delay=0,a_values_read=0,a_keys_read=0,a_contexts=0;
    int a_head_keys[32],a_head_values[32];
    string context_root;
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
        a_req_ready=context_phase && !a_serving && !a_rsp_valid && cycles%5!=0;
        a_context_ready=context_phase && cycles%7!=0;
        mask_ready=context_phase && a_cfg_ready && !mask_error;
    end
    tri_oracle_complete_head_broker attention (
        .clk,.rst_n,.cfg_valid(context_phase && mask_valid && !mask_error),.cfg_ready(a_cfg_ready),
        .cfg_heads(mask_heads),.cfg_streaming(mask_streaming),.cfg_total_keys(11'd281),.cfg_visible_keys(11'd281),
        .cfg_score_shifts(ATTENTION_SHIFTS),.cfg_value_exponents(ATTENTION_EXPONENTS),
        .cfg_query(16'd280),.cfg_epoch(mask_epoch),.cfg_tag(mask_tag),.cancel(1'b0),
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
        .all_contexts_collected(a_collected),.done_valid(a_done),.done_ready(1'b0),
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
    function automatic logic [511:0] attention_operand(input int kind,head,key);
        logic [511:0] value;
        value='0;
        for(int lane=0;lane<64;lane++)begin
            if(kind==0)value[lane*8+:8]=queries[(head*ROWS+ROWS-1)*64+lane];
            else if(kind==1)value[lane*8+:8]=keys[((head/8)*281+key)*64+lane];
        end
        if(kind==2)value=a_values[(head/8)*281+key];
        return value;
    endfunction
    always @(posedge clk)if(rst_n)begin
        if(context_phase && a_collected)begin
            if(!a_collection_seen)$display("PREDICTED_ATTENTION_ARCHIVED tick=%0t",$time);
            a_collection_seen<=1;
        end
        if(trained_phase && out_valid && out_ready && !mask_result_ready)
            $fatal(1,"PREDICTED_MASK_RESULT_DROPPED");
        if(mask_valid && mask_ready)begin
            if(mask_heads!==32'hffffffff || mask_streaming!==32'hfd6c64bf ||
               mask_tag!==PredictionTag || mask_epoch!==PredictionEpoch || mask_error)
                $fatal(1,"PREDICTED_MASK_COMMIT_WRONG");
            a_committed_mask<=mask_streaming;
            $display("PREDICTED_MASK_ACCEPT tick=%0t heads=%08h streaming=%08h tag=%08h epoch=%04h",$time,mask_heads,mask_streaming,mask_tag,mask_epoch);
        end
        if(a_req_valid && a_req_ready)begin
            if($isunknown({a_req_kind,a_req_head,a_req_key,a_req_query,a_req_epoch,a_req_tag}) ||
               a_req_kind>2 || a_req_key>=281 || a_req_query!=280 ||
               a_req_epoch!==PredictionEpoch || a_req_tag!==PredictionTag)
                $fatal(1,"PREDICTED_ATTENTION_REQUEST_DESCRIPTOR");
            if(a_req_kind!=0 && a_committed_mask[a_req_head] && a_req_key>=32 && a_req_key<249)
                $fatal(1,"PREDICTED_ATTENTION_SKIPPED_KEY_REQUESTED");
            a_rsp_kind<=a_req_kind;a_rsp_head<=a_req_head;a_rsp_key<=a_req_key;
            a_rsp_query<=a_req_query;a_rsp_epoch<=a_req_epoch;a_rsp_tag<=a_req_tag;
            a_rsp_size<=a_req_kind==1 ? a_sizes[a_req_key]:10'd1;
            a_rsp_data<=attention_operand(int'(a_req_kind),int'(a_req_head),int'(a_req_key));
            a_serving<=1;a_delay<=2+cycles%3;
            if(a_req_kind==1)begin a_keys_read++;a_head_keys[a_req_head]++;end
            if(a_req_kind==2)begin a_values_read++;a_head_values[a_req_head]++;end
            $display("PREDICTED_ATTENTION_REQUEST kind=%0d head=%0d key=%0d",a_req_kind,a_req_head,a_req_key);
        end
        if(a_serving)begin
            if(a_delay==0)begin a_serving<=0;a_rsp_valid<=1;end
            else a_delay<=a_delay-1;
        end
        if(a_rsp_valid && a_rsp_ready)a_rsp_valid<=0;
        if(a_context_valid)begin
            if($isunknown({a_context_head,a_context_query,a_context_epoch,a_context_tag,a_context_data,a_context_exponent}) ||
               a_context_data!==a_gold[a_context_head] || a_seen[a_context_head] ||
               a_context_query!==16'd280 || a_context_epoch!==PredictionEpoch ||
               a_context_tag!==PredictionTag || a_context_exponent!==-8'sd5)
                $fatal(1,"PREDICTED_ATTENTION_CONTEXT_WRONG head=%0d",a_context_head);
            if(a_context_ready)begin
                a_seen[a_context_head]<=1;a_contexts++;
                $display("PREDICTED_ATTENTION_CONTEXT head=%0d data=%0512h",a_context_head,a_context_data);
            end
        end
        if(a_done && a_error)$fatal(1,"PREDICTED_ATTENTION_FAILED code=%0d",a_error_code);
    end
    task automatic begin_prediction_mask;
        @(negedge clk);
        if(mask_cfg_ready!==1'b1)$fatal(1,"PREDICTED_MASK_NOT_IDLE");
        mask_cfg_valid=1;@(negedge clk);mask_cfg_valid=0;
    endtask
    task automatic run_predicted_attention;
        if(short_mode || mask_valid!==1'b1 || mask_error || reading || tensor_out_valid || tensor_done_valid)
            $fatal(1,"PREDICTED_ATTENTION_INCOMPLETE_PREDICTION");
        $display("PREDICTED_ATTENTION_BEGIN tick=%0t",$time);
        @(negedge clk);context_phase=1;
        while(!a_done)@(negedge clk);
        if(a_error || a_reset || !a_collection_seen || a_seen!==32'hffffffff || a_contexts!=32 ||
           a_keys_read!=4435 || a_values_read!=4435 || a_serving || a_rsp_valid)
            $fatal(1,"PREDICTED_ATTENTION_COVERAGE keys=%0d values=%0d contexts=%0d",a_keys_read,a_values_read,a_contexts);
        for(int head=0;head<32;head++)begin
            if(a_head_keys[head]!=(a_committed_mask[head]?64:281) ||
               a_head_values[head]!=(a_committed_mask[head]?64:281))
                $fatal(1,"PREDICTED_ATTENTION_HEAD_COVERAGE head=%0d",head);
        end
        repeat(3)@(negedge clk);
        $display("PREDICTED_ATTENTION_FULL_PASS heads=32 contexts=2048 keys=4435 values=4435 streaming=%08h",a_committed_mask);
    endtask
    initial begin
        if(!$value$plusargs("CONTEXT_ROOT=%s",context_root))$fatal(1,"PREDICTED_ATTENTION_FIXTURE_REQUIRED");
        $readmemh({context_root,"/value.hex"},a_values);
        $readmemh({context_root,"/expected.hex"},a_gold);
        $readmemh({context_root,"/sizes.hex"},a_sizes);
        for(int head=0;head<32;head++)begin a_head_keys[head]=0;a_head_values[head]=0;end
    end
