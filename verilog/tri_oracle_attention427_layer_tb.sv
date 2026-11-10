`timescale 1ns/1ps
module tri_oracle_attention427_layer_tb #(parameter int TARGET_LAYER=0, parameter bit PERSIST_LAYER_CONTEXT=0);
    localparam logic [63:0] QUERY_ADDR = 64'h1000, KEY_ADDR = 64'h20000;
    logic clk=0, rst_n=0;
    always #5 clk=~clk;

    logic frame_valid=0, frame_new_image, frame_done_ready=0, sign_valid=0;
    logic [4:0] frame_layer;
    logic [11:0] frame_minimum_matches;
    logic [9:0] frame_image_start;
    logic [2047:0] sign_data;
    wire frame_ready, frame_done_valid, frame_done_error, sign_ready, map_valid, map_last;
    wire [9:0] map_index, map_origin;
    logic restore_valid=0, restore_done_ready=0, checking_restore=0;
    logic [4:0] restore_layer;
    wire restore_ready, restore_done_valid, restore_done_error;

    logic head_valid=0, head_done_ready=0;
    logic [4:0] head_id;
    logic [31:0] head_tag, head_alpha;
    logic [10:0] head_tokens;
    logic [7:0] head_ratio_num=8, head_ratio_den=1;
    wire head_ready, head_done_valid, head_done_error, head_done_streaming;
    wire [31:0] head_done_tag;
    wire [4:0] head_done_id;
    wire [17:0] head_done_inner, head_done_recent;

    logic row_valid=0, result_ready=0;
    logic [4:0] row_head;
    logic [10:0] row_position, row_key_count;
    logic [31:0] row_tag;
    logic signed [6:0] row_score_shift;
    wire row_ready, result_valid, result_error;
    wire [31:0] result_tag;
    wire [2047:0] result_values;

    wire tensor_cfg_valid, tensor_cfg_ready, tensor_out_valid, tensor_out_ready, tensor_out_last;
    wire tensor_done_valid, tensor_done_ready, tensor_done_error;
    wire [31:0] tensor_cfg_tag, tensor_out_tag, tensor_done_tag;
    wire [4:0] tensor_cfg_tokens;
    wire [7:0] tensor_cfg_count, tensor_out_count;
    wire [16:0] tensor_cfg_dense_rows;
    wire [2559:0] tensor_cfg_channels, tensor_cfg_keep, tensor_out_channels;
    wire [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base;
    wire [3:0] tensor_out_token;
    wire [5119:0] tensor_out_data;

    wire value_req_valid, value_rsp_ready;
    logic value_pending=0;
    wire [9:0] value_req_rank;
    logic [9:0] value_rank;
    wire req_valid, rsp_ready;
    logic reading=0;
    wire [63:0] req_address;
    wire [4:0] req_length;
    logic [63:0] read_address;
    int words_left;
    int cycles=0, active_layer, frame_maps, sign_words=0, total_maps=0, frames=0, frame_errors=0;
    int checked_heads=0, streaming_heads=0, head_errors=0, checked_rows=0, row_errors=0, score_words=0;
    int selected_count, accepted_values, accepted_scores, query_count, key_count, row_id;
    int restored_words, restored_maps=0, restore_errors=0;
    bit predicting=0, rejecting=0;
    logic [511:0] queries[1024], keys[1024], values[1024];
    logic [9:0] golden[22*576], ranks[1024];
    logic [2047:0] signs[22*576], expected_result;
    logic [31:0] dots[1024];
    bit selected[1024];
    string fixture;

    wire map_ready = cycles%7!=1 && cycles%7!=2;
    wire req_ready = !reading && cycles%5!=0;
    wire rsp_valid = reading;
    wire rsp_last = words_left==1;
    wire [9:0] read_key = 10'((read_address-KEY_ADDR)>>6);
    wire [9:0] read_query = 10'((read_address-QUERY_ADDR)>>6);
    wire [63:0] rsp_data = read_address>=KEY_ADDR ?
        keys[read_key][int'(read_address[5:3])*64+:64] : queries[read_query][int'(read_address[5:3])*64+:64];
    wire value_req_ready = !value_pending && cycles%5!=1;
    wire value_rsp_valid = value_pending;
    wire [511:0] value_rsp_data = values[value_rank];

    tri_oracle_attention_layer427 #(.PERSIST_LAYER_CONTEXT(PERSIST_LAYER_CONTEXT)) dut (
        .head_query_base(QUERY_ADDR), .head_key_base(KEY_ADDR),
        .row_query_addr(QUERY_ADDR), .row_key_base(KEY_ADDR), .value_rsp_error(1'b0), .*
    );
    tri_oracle_batched_tensor390 tensor (
        .clk, .rst_n, .cfg_valid(tensor_cfg_valid), .cfg_ready(tensor_cfg_ready),
        .cfg_paired(1'b0), .cfg_tag(tensor_cfg_tag), .cfg_tokens(tensor_cfg_tokens), .cfg_feature_words(10'd8),
        .cfg_dense_rows(tensor_cfg_dense_rows), .cfg_count(tensor_cfg_count),
        .cfg_channels(tensor_cfg_channels), .cfg_keep(tensor_cfg_keep),
        .cfg_activation_base(tensor_cfg_activation_base), .cfg_weight_base(tensor_cfg_weight_base),
        .cfg_up_weight_base(64'd0), .cfg_activation_stride(32'd64),
        .out_valid(tensor_out_valid), .out_ready(tensor_out_ready), .out_tag(tensor_out_tag),
        .out_token(tensor_out_token), .out_last(tensor_out_last), .out_count(tensor_out_count),
        .out_channels(tensor_out_channels), .out_data(tensor_out_data), .done_valid(tensor_done_valid),
        .done_ready(tensor_done_ready), .done_error(tensor_done_error), .done_tag(tensor_done_tag),
        .req_valid, .req_ready, .req_address, .req_length, .rsp_valid, .rsp_ready, .rsp_last, .rsp_error(1'b0), .rsp_data
    );

    always @(posedge clk) if (rst_n) begin
        cycles <= cycles+1;
        if (map_valid && map_ready) begin
            if (rejecting || frame_maps>=576 || map_index!==10'(frame_maps) ||
                map_origin!==golden[active_layer*576+frame_maps] || map_last!==(frame_maps==575))
                $fatal(1,"LAYER427_MAP layer=%0d index=%0d",active_layer,frame_maps);
            frame_maps++;
            total_maps++;
        end
        if (sign_valid && sign_ready) sign_words++;
        if (checking_restore) begin
            if (sign_ready || map_valid || tensor_cfg_valid || value_req_valid)
                $fatal(1,"CTX428_RESTORE_SIDE_EFFECT layer=%0d",restore_layer);
            if (dut.row_map_valid && dut.row_map_ready) begin
                if (restored_words>=576 || dut.row_map_origin!==golden[int'(restore_layer)*576+restored_words])
                    $fatal(1,"CTX428_RESTORED_MAP layer=%0d index=%0d",restore_layer,restored_words);
                restored_words++;
            end
        end
        if (req_valid && req_ready) begin
            if (rejecting || req_length==0 || req_address[2:0]!=0) $fatal(1,"LAYER427_UNEXPECTED_READ");
            for (int word=0;word<int'(req_length);word++) begin
                logic [63:0] address;
                address=req_address+64'(word*8);
                if (address<QUERY_ADDR || (address>=QUERY_ADDR+64'(query_count*64) && address<KEY_ADDR) ||
                    address>=KEY_ADDR+64'(key_count*64))
                    $fatal(1,"LAYER427_ADDRESS address=%h",address);
                if (!predicting && address>=KEY_ADDR && !selected[int'((address-KEY_ADDR)>>6)])
                    $fatal(1,"LAYER427_KEY_READ row=%0d address=%h",row_id,address);
            end
            reading <= 1;
            read_address <= req_address;
            words_left <= int'(req_length);
        end else if (rsp_valid && rsp_ready) begin
            reading <= !rsp_last;
            read_address <= read_address+64'd8;
            words_left <= words_left-1;
        end
        if (!predicting && tensor_out_valid && tensor_out_ready) begin
            for (int lane=0;lane<int'(tensor_out_count);lane++) begin
                if (accepted_scores>=selected_count || tensor_out_channels[lane*16+:16]!==16'(ranks[accepted_scores]) ||
                    tensor_out_data[lane*32+:32]!==dots[accepted_scores])
                    $fatal(1,"LAYER427_DOT row=%0d score=%0d",row_id,accepted_scores);
                accepted_scores++;
            end
        end
        if (value_req_valid && value_req_ready) begin
            if (rejecting || predicting || accepted_values>=selected_count || value_req_rank!==ranks[accepted_values])
                $fatal(1,"LAYER427_VALUE_ORDER row=%0d value=%0d",row_id,accepted_values);
            value_rank <= value_req_rank;
            value_pending <= 1;
            accepted_values++;
        end else if (value_rsp_valid && value_rsp_ready) value_pending <= 0;
    end

    task automatic load_frame(input int layer, input bit invalid, reject_continuation);
        int previous_signs, expected_signs;
        @(negedge clk);
        active_layer=layer; frame_maps=0; rejecting=invalid; previous_signs=sign_words; expected_signs=0;
        frame_new_image=layer==0; frame_layer=5'(layer);
        frame_minimum_matches=(invalid && !reject_continuation) ? 12'd4095 : 12'd1536;
        frame_image_start=10'd5; frame_valid=1;
        @(posedge clk);
        if (!frame_ready) $fatal(1,"LAYER427_FRAME_BUSY");
        @(negedge clk);
        frame_valid=0;
        if (!invalid) begin
            for (int position=0;position<576;position++) begin
                if (layer==0 || golden[(layer-1)*576+position]==10'(position)) begin
                    sign_valid=1; sign_data=signs[layer*576+position];
                    do @(posedge clk); while (!sign_ready);
                    @(negedge clk);
                    sign_valid=0;
                    expected_signs++;
                end
            end
        end
        while (!frame_done_valid) begin
            if (invalid && sign_ready)
                $fatal(1,"LAYER427_REJECTED_FRAME_REQUESTED_SIGN layer=%0d",layer);
            @(negedge clk);
        end
        repeat (2) begin
            if (!frame_done_valid || frame_done_error!==invalid || frame_ready || row_ready || head_ready ||
                frame_maps!=(invalid ? 0 : 576) || sign_words-previous_signs!=expected_signs)
                $fatal(1,"LAYER427_FRAME_RESULT layer=%0d error=%b",layer,frame_done_error);
            @(negedge clk);
        end
        frame_done_ready=1;
        @(negedge clk);
        frame_done_ready=0;
        frames+=int'(!invalid); frame_errors+=int'(invalid);
    endtask

    task automatic restore_frame(input int layer, input bit invalid);
        @(negedge clk);
        rejecting=1; checking_restore=1; restored_words=0; active_layer=layer;
        restore_layer=5'(layer); restore_valid=1;
        @(posedge clk);
        if (!restore_ready) $fatal(1,"CTX428_RESTORE_NOT_READY");
        @(negedge clk);
        restore_valid=0;
        while (!restore_done_valid) @(negedge clk);
        repeat (2) begin
            if (!restore_done_valid || restore_done_error!==invalid ||
                restored_words!=(invalid ? 0 : 576) || frame_ready || head_ready || row_ready)
                $fatal(1,"CTX428_RESTORE_RESULT layer=%0d error=%b words=%0d",layer,restore_done_error,restored_words);
            @(negedge clk);
        end
        restore_done_ready=1;
        @(negedge clk);
        restore_done_ready=0; checking_restore=0;
        restored_maps+=int'(!invalid); restore_errors+=int'(invalid);
    endtask

    task automatic predict_head(input int id, alpha, inner, recent, input bit expected_streaming, invalid);
        @(negedge clk);
        predicting=1; rejecting=invalid;
        head_id=5'(id); head_alpha=32'(alpha); head_tokens=11'(key_count); head_tag=32'h42710000+32'(id);
        head_ratio_den=invalid ? 0 : 1;
        head_valid=1;
        @(posedge clk);
        if (!head_ready) $fatal(1,"LAYER427_HEAD_BUSY");
        @(negedge clk);
        head_valid=0;
        while (!head_done_valid) @(negedge clk);
        repeat (2) begin
            if (!head_done_valid || head_done_tag!==head_tag || head_done_id!==head_id ||
                head_done_error!==invalid || head_done_streaming!==(expected_streaming && !invalid) ||
                head_done_inner!==(invalid ? 18'd0 : 18'(inner)) ||
                head_done_recent!==(invalid ? 18'd0 : 18'(recent)) || reading || row_ready)
                $fatal(1,"LAYER427_HEAD layer=%0d head=%0d inner=%0d recent=%0d streaming=%b error=%b",
                       active_layer,id,head_done_inner,head_done_recent,head_done_streaming,head_done_error);
            @(negedge clk);
        end
        head_done_ready=1;
        @(negedge clk);
        head_done_ready=0;
        checked_heads+=int'(!invalid); streaming_heads+=int'(expected_streaming && !invalid); head_errors+=int'(invalid);
    endtask

    task automatic execute_row(input int id, position, shift, input bit invalid);
        @(negedge clk);
        predicting=0; rejecting=invalid; query_count=1;
        accepted_scores=0; accepted_values=0;
        row_head=5'(id); row_position=11'(position); row_key_count=11'(key_count);
        row_score_shift=7'(shift); row_tag=32'h42720000+32'(row_id);
        row_valid=1;
        @(posedge clk);
        if (!row_ready) $fatal(1,"LAYER427_ROW_BUSY");
        @(negedge clk);
        row_valid=0;
        while (!result_valid) @(negedge clk);
        if (accepted_scores!=(invalid ? 0 : selected_count) || accepted_values!=(invalid ? 0 : selected_count) ||
            value_pending || reading)
            $fatal(1,"LAYER427_ROW_INVENTORY row=%0d",row_id);
        repeat (2) begin
            if (!result_valid || result_error!==invalid || result_tag!==row_tag || head_ready || row_ready ||
                result_values!==(invalid ? 2048'd0 : expected_result))
                $fatal(1,"LAYER427_ROW_RESULT row=%0d error=%b",row_id,result_error);
            @(negedge clk);
        end
        result_ready=1;
        @(negedge clk);
        result_ready=0;
        checked_rows+=int'(!invalid); row_errors+=int'(invalid); score_words+=accepted_scores;
    endtask

    task automatic run_heads(input string filename, input bit inject_error);
        int heads_file, id, alpha, inner, recent, stream;
        heads_file=$fopen(filename,"r");
        if (!heads_file) $fatal(1,"LAYER427_FIXTURE_OPEN");
        while ($fscanf(heads_file,"%d %d %d %d %d %d",id,key_count,alpha,inner,recent,stream)==6) begin
            query_count=key_count-96;
            for (int row=0;row<query_count;row++)
                if ($fscanf(heads_file,"%h",queries[row])!=1) $fatal(1,"LAYER427_HEAD_QUERY");
            for (int key=0;key<key_count;key++)
                if ($fscanf(heads_file,"%h",keys[key])!=1) $fatal(1,"LAYER427_HEAD_KEY");
            if (inject_error) predict_head(id,alpha,inner,recent,stream!=0,1);
            predict_head(id,alpha,inner,recent,stream!=0,0);
        end
        if (!$feof(heads_file)) $fatal(1,"LAYER427_HEAD_FILE");
        $fclose(heads_file);
    endtask

    task automatic run_rows(input string filename);
        int rows_file, id, position, shift;
        rows_file=$fopen(filename,"r");
        if (!rows_file) $fatal(1,"LAYER427_FIXTURE_OPEN");
        while ($fscanf(rows_file,"%d %d %d %d %d %d",row_id,id,key_count,position,shift,selected_count)==6) begin
            if ($fscanf(rows_file,"%h %h",queries[0],expected_result)!=2) $fatal(1,"LAYER427_ROW_HEADER");
            for (int key=0;key<key_count;key++) begin
                selected[key]=0;
                if ($fscanf(rows_file,"%h %h",keys[key],values[key])!=2) $fatal(1,"LAYER427_ROW_KEY");
            end
            for (int index=0;index<selected_count;index++) begin
                if ($fscanf(rows_file,"%h %h",ranks[index],dots[index])!=2) $fatal(1,"LAYER427_ROW_DOT");
                selected[ranks[index]]=1;
            end
            execute_row(id,position,shift,0);
        end
        if (!$feof(rows_file)) $fatal(1,"LAYER427_ROW_FILE");
        $fclose(rows_file);
    endtask

    initial begin
        if (!$value$plusargs("FIXTURE=%s",fixture)) $fatal(1,"LAYER427_FIXTURE");
        $readmemh({fixture,"/map.hex"},golden);
        $readmemh({fixture,"/signs.hex"},signs);
        repeat (3) @(negedge clk);
        rst_n=1;
        if (PERSIST_LAYER_CONTEXT) begin
            restore_frame(21,1);
            for (int layer=0;layer<22;layer++) begin
                load_frame(layer,0,0);
                run_heads($sformatf("%s/heads_%0d.txt",fixture,layer),0);
                run_rows($sformatf("%s/prefill_%0d.txt",fixture,layer));
                if (layer==0) load_frame(2,1,1);
                if (layer==10) restore_frame(0,0);
            end
            for (int layer=0;layer<22;layer++) begin
                restore_frame(layer,0);
                run_rows($sformatf("%s/decode_%0d.txt",fixture,layer));
            end
            execute_row(31,0,-1,1);
            predict_head(0,0,0,0,0,1);
            restore_frame(10,0);
            restore_frame(21,0);
            execute_row(0,0,-1,1);
            restore_frame(31,1);
            execute_row(1,0,-1,1);
            restore_frame(0,0);
            load_frame(0,1,0);
            restore_frame(21,1);
            $display("CTX428_ATTENTION_PASS frames=%0d maps=%0d signs=%0d restores=%0d heads=%0d streaming=%0d rows=%0d scores=%0d frame_errors=%0d restore_errors=%0d head_errors=%0d row_errors=%0d",
                     frames,total_maps,sign_words,restored_maps,checked_heads,streaming_heads,checked_rows,score_words,
                     frame_errors,restore_errors,head_errors,row_errors);
        end else begin
            if (TARGET_LAYER==0) load_frame(0,1,0);
            for (int layer=0;layer<=TARGET_LAYER;layer++) load_frame(layer,0,0);
            run_heads({fixture,"/heads.txt"},TARGET_LAYER==0);
            run_rows({fixture,"/rows.txt"});
            if (TARGET_LAYER==0) begin
                load_frame(1,1,0);
                load_frame(1,0,0);
                execute_row(0,0,-1,1);
                load_frame(0,1,0);
                load_frame(1,1,1);
            end
            $display("LAYER427_PASS frames=%0d maps=%0d signs=%0d heads=%0d streaming=%0d rows=%0d scores=%0d frame_errors=%0d head_errors=%0d row_errors=%0d",
                     frames,total_maps,sign_words,checked_heads,streaming_heads,checked_rows,score_words,frame_errors,head_errors,row_errors);
        end
        if (checked_heads==0 || checked_rows==0) $fatal(1,"LAYER427_FIXTURE_END");
        $finish;
    end

    initial begin
        #100000000;
        $fatal(1,"LAYER427_TIMEOUT layer=%0d head=%0d row=%0d",active_layer,head_id,row_id);
    end
endmodule
