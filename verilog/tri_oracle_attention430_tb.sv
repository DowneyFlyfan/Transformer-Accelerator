`timescale 1ns/1ps
module tri_oracle_attention430_tb #(parameter int SHARD=0, INTEGRATE=0, HOLD_DISABLED_RESTORE=0);
    localparam int SLOTS=409, WORDS=256, PROMPT=408;
    localparam logic [63:0] ACTIVATION_BASE=64'h10000, WEIGHT_BASE=64'h10000000, CACHE_BASE=64'h2000000;
    logic clk=0,rst_n=0;
    always #5 clk=~clk;

    logic projection_valid=0, projection_done_ready=0, angle_valid=0, angle_last;
    logic [31:0] projection_tag;
    logic [4:0] projection_tokens;
    logic [5:0] projection_first_head, projection_heads=1;
    logic [9:0] projection_slot;
    logic [63:0] projection_activation_base;
    wire [63:0] projection_weight_base=WEIGHT_BASE, projection_cache_base=CACHE_BASE;
    logic [239:0] projection_shifts;
    logic [95:0] projection_shift_biases;
    logic [511:0] angle_cos,angle_sin;
    wire projection_ready,projection_done_valid,projection_done_error,angle_ready;
    wire [31:0] projection_done_tag;
    wire cache_write_valid,cache_write_rsp_ready;
    wire [63:0] cache_write_address;
    wire [511:0] cache_write_data;

    logic frame_valid=0,frame_done_ready=0,sign_valid=0;
    wire frame_new_image=1;
    wire [4:0] frame_layer=0;
    wire [11:0] frame_minimum_matches=1536;
    logic [9:0] frame_image_start;
    logic [2047:0] sign_data;
    wire frame_ready,sign_ready,map_valid,map_last,frame_done_valid,frame_done_error;
    wire [9:0] map_index,map_origin;
    wire map_ready=1;
    wire restore_valid=HOLD_DISABLED_RESTORE!=0,restore_done_ready=0;
    wire [4:0] restore_layer=0;
    wire restore_ready,restore_done_valid,restore_done_error;

    logic head_valid=0,head_done_ready=0;
    wire [4:0] head_id=0;
    wire [31:0] head_tag=32'h43011111;
    logic [31:0] head_alpha;
    wire [10:0] head_tokens=11'(PROMPT);
    wire [7:0] head_ratio_num=8,head_ratio_den=1;
    wire [63:0] head_query_base=CACHE_BASE+96*64, head_key_base=CACHE_BASE+32*65536;
    wire head_ready,head_done_valid,head_done_error,head_done_streaming;
    wire [31:0] head_done_tag;
    wire [4:0] head_done_id;
    wire [17:0] head_done_inner,head_done_recent;

    logic row_valid=0,result_ready=0;
    wire [4:0] row_head=0;
    logic [10:0] row_position,row_key_count;
    logic [31:0] row_tag;
    logic signed [6:0] row_score_shift;
    logic [63:0] row_query_addr;
    wire [63:0] row_key_base=head_key_base;
    wire row_ready,result_valid,result_error;
    wire [31:0] result_tag;
    wire [2047:0] result_values;
    wire value_req_valid,value_rsp_ready;
    wire [9:0] value_req_rank;
    wire value_rsp_error=0;

    wire tensor_cfg_valid,tensor_cfg_ready,tensor_out_valid,tensor_out_ready,tensor_out_last;
    wire tensor_done_valid,tensor_done_ready,tensor_done_error;
    wire [9:0] tensor_cfg_feature_words;
    wire [31:0] tensor_cfg_activation_stride,tensor_cfg_tag,tensor_out_tag,tensor_done_tag;
    wire [4:0] tensor_cfg_tokens;
    wire [7:0] tensor_cfg_count,tensor_out_count;
    wire [16:0] tensor_cfg_dense_rows;
    wire [2559:0] tensor_cfg_channels,tensor_cfg_keep,tensor_out_channels;
    wire [63:0] tensor_cfg_activation_base,tensor_cfg_weight_base;
    wire [3:0] tensor_out_token;
    wire [5119:0] tensor_out_data;
    wire req_valid,rsp_ready;
    wire [63:0] req_address;
    wire [4:0] req_length;

    logic [63:0] activations[SLOTS*WORDS],weights[3*64*WORDS];
    logic [511:0] cosines[SLOTS],sines[SLOTS],expected[3*SLOTS],cache[3*SLOTS],pending_write;
    logic [5:0] biases[SLOTS];
    logic [239:0] shifts[1];
    logic [2047:0] signs[576];
    logic [9:0] golden[576];
    logic [2047:0] expected_result;
    bit committed[3*SLOTS];
    logic reading=0,write_pending=0,value_pending=0,held_write=0;
    logic [63:0] read_address, held_address;
    logic [511:0] held_data;
    int cycles=0,words_left,pending_index,value_rank,projection_writes,failed_writes=0;
    int maps=0,writes=0,rows=0,values=0,attention_reads=0,stalled_writes=0;
    int current_group,start_slot,token_count,expect_inner,expect_recent,expect_streaming;
    int expected_value_requests,row_values=0;
    bit write_fault=0,in_projection=0;
    string fixture,dump;

    function automatic int bank(input int head);
        case (head)
            0: return 0;
            32: return 1;
            36: return 2;
            default: return -1;
        endcase
    endfunction
    function automatic int cache_index(input logic [63:0] address);
        int group_id,slot;
        group_id=bank(int'((address-CACHE_BASE)>>16));
        slot=int'((address-CACHE_BASE)&64'hffff)>>6;
        if (group_id<0 || slot>=SLOTS) return -1;
        return group_id*SLOTS+slot;
    endfunction
    function automatic logic [63:0] word_at(input logic [63:0] address);
        int index;
        if (address>=WEIGHT_BASE) begin
            index=int'((address-WEIGHT_BASE)>>3);
            return weights[bank(index/(64*WORDS))*64*WORDS+index%(64*WORDS)];
        end
        if (address>=CACHE_BASE) return cache[cache_index(address)][int'(address[5:3])*64+:64];
        return activations[int'((address-ACTIVATION_BASE)>>3)];
    endfunction

    wire req_ready=!reading && cycles%5!=0;
    wire rsp_valid=reading,rsp_last=words_left==1;
    wire [63:0] rsp_data=word_at(read_address);
    wire cache_write_ready=!write_pending && cycles%5==0;
    wire cache_write_rsp_valid=write_pending;
    wire cache_write_rsp_error=write_fault && projection_writes==2;
    wire value_req_ready=!value_pending;
    wire value_rsp_valid=value_pending;
    wire [511:0] value_rsp_data=cache[2*SLOTS+value_rank];

    tri_oracle_attention_pipeline430 dut (.*);
    tri_oracle_batched_tensor390 tensor (
        .clk,.rst_n,.cfg_valid(tensor_cfg_valid),.cfg_ready(tensor_cfg_ready),.cfg_paired(1'b0),
        .cfg_tag(tensor_cfg_tag),.cfg_tokens(tensor_cfg_tokens),.cfg_feature_words(tensor_cfg_feature_words),
        .cfg_dense_rows(tensor_cfg_dense_rows),.cfg_count(tensor_cfg_count),.cfg_channels(tensor_cfg_channels),
        .cfg_keep(tensor_cfg_keep),.cfg_activation_base(tensor_cfg_activation_base),.cfg_weight_base(tensor_cfg_weight_base),
        .cfg_up_weight_base(64'd0),.cfg_activation_stride(tensor_cfg_activation_stride),
        .out_valid(tensor_out_valid),.out_ready(tensor_out_ready),.out_tag(tensor_out_tag),.out_token(tensor_out_token),
        .out_last(tensor_out_last),.out_count(tensor_out_count),.out_channels(tensor_out_channels),.out_data(tensor_out_data),
        .done_valid(tensor_done_valid),.done_ready(tensor_done_ready),.done_error(tensor_done_error),.done_tag(tensor_done_tag),
        .req_valid,.req_ready,.req_address,.req_length,.rsp_valid,.rsp_ready,.rsp_last,.rsp_error(1'b0),.rsp_data
    );

    always @(posedge clk) if (rst_n) begin
        cycles<=cycles+1;
        if (in_projection && (row_ready || head_ready || restore_ready || frame_ready))
            $fatal(1,"COMPOSE430_OWNER");
        if (req_valid && req_ready) begin
            if (req_length==0 || req_address[2:0]!=0) $fatal(1,"COMPOSE430_BAD_REQUEST");
            for (int beat=0;beat<int'(req_length);beat++) begin
                logic [63:0] address;
                int index;
                address=req_address+64'(beat*8);
                if (in_projection) begin
                    if (address>=WEIGHT_BASE) begin
                        index=int'((address-WEIGHT_BASE)>>3);
                        if (bank(index/(64*WORDS))!=current_group) $fatal(1,"COMPOSE430_WEIGHT_RANGE");
                    end else if (address<projection_activation_base ||
                                 address>=projection_activation_base+64'(token_count*2048))
                        $fatal(1,"COMPOSE430_ACTIVATION_RANGE");
                end else begin
                    index=cache_index(address);
                    if (address<CACHE_BASE || address>=WEIGHT_BASE || index<0 || !committed[index] ||
                        index>=2*SLOTS) $fatal(1,"COMPOSE430_UNCOMMITTED_READ address=%h",address);
                    attention_reads++;
                end
            end
            reading<=1;
            words_left<=int'(req_length);
            read_address<=req_address;
        end else if (rsp_valid && rsp_ready) begin
            reading<=!rsp_last;
            words_left<=words_left-1;
            read_address<=read_address+64'd8;
        end

        if (held_write && (!cache_write_valid || cache_write_address!==held_address || cache_write_data!==held_data))
            $fatal(1,"COMPOSE430_STALLED_WRITE_CHANGED");
        held_write<=cache_write_valid && !cache_write_ready;
        if (cache_write_valid && !cache_write_ready) begin
            held_address<=cache_write_address;
            held_data<=cache_write_data;
            stalled_writes++;
        end
        if (cache_write_valid && cache_write_ready) begin
            int index;
            index=cache_index(cache_write_address);
            if (!in_projection || index!=current_group*SLOTS+start_slot+projection_writes ||
                cache_write_address[5:0]!=0 || committed[index] || cache_write_data!==expected[index])
                $fatal(1,"COMPOSE430_WRITE group=%0d slot=%0d",current_group,start_slot+projection_writes);
            pending_write<=cache_write_data;
            pending_index<=index;
            write_pending<=1;
            projection_writes++;
        end else if (cache_write_rsp_valid && cache_write_rsp_ready) begin
            if (!cache_write_rsp_error) cache[pending_index]<=pending_write;
            write_pending<=0;
        end
        if (value_req_valid && value_req_ready) begin
            if (in_projection || !committed[2*SLOTS+int'(value_req_rank)])
                $fatal(1,"COMPOSE430_VALUE_READ rank=%0d",value_req_rank);
            value_rank<=int'(value_req_rank);
            value_pending<=1;
            values++;
            row_values++;
        end else if (value_rsp_valid && value_rsp_ready) value_pending<=0;
        if (map_valid && map_ready) begin
            if (map_index!==10'(maps) || map_origin!==golden[maps] || map_last!==(maps==575))
                $fatal(1,"COMPOSE430_MAP index=%0d",maps);
            maps++;
        end
    end

    task automatic project(input int group_id,first,count,input bit fault);
        @(negedge clk);
        current_group=group_id; start_slot=first; token_count=count;
        write_fault=fault; projection_writes=0;
        projection_first_head=group_id==0 ? 6'd0 : group_id==1 ? 6'd32 : 6'd36;
        projection_tag=32'h43000000+32'(group_id*1024+first);
        projection_tokens=5'(count); projection_slot=10'(first);
        projection_activation_base=ACTIVATION_BASE+64'(first*2048);
        projection_shift_biases=0;
        for (int i=0;i<count;i++) projection_shift_biases[i*6+:6]=biases[first+i];
        projection_valid=1;
        @(posedge clk);
        if (!projection_ready) $fatal(1,"COMPOSE430_PROJECTION_NOT_READY");
        @(negedge clk);
        projection_valid=0; in_projection=1;
        if (group_id!=2) begin
            for (int i=0;i<count;i++) begin
                angle_valid=1; angle_last=i==count-1;
                angle_cos=cosines[first+i]; angle_sin=sines[first+i];
                do @(posedge clk); while (!angle_ready);
                @(negedge clk);
            end
            angle_valid=0;
        end
        while (!projection_done_valid) @(negedge clk);
        repeat (2) begin
            if (!projection_done_valid || projection_done_tag!==projection_tag || projection_done_error!==fault ||
                projection_writes!=(fault ? 2 : count) || reading || write_pending)
                $fatal(1,"COMPOSE430_PROJECT_RESULT group=%0d slot=%0d error=%b writes=%0d",
                       group_id,first,projection_done_error,projection_writes);
            @(negedge clk);
        end
        if (fault) failed_writes+=projection_writes;
        else begin
            for (int i=0;i<count;i++) committed[group_id*SLOTS+first+i]=1;
            writes+=count;
        end
        projection_done_ready=1;
        @(negedge clk);
        projection_done_ready=0; in_projection=0; write_fault=0;
    endtask

    task automatic build_frame;
        @(negedge clk);
        frame_valid=1;
        @(posedge clk);
        if (!frame_ready) $fatal(1,"COMPOSE430_FRAME_NOT_READY");
        @(negedge clk);
        frame_valid=0;
        for (int i=0;i<576;i++) begin
            sign_valid=1; sign_data=signs[i];
            do @(posedge clk); while (!sign_ready);
            @(negedge clk);
        end
        sign_valid=0;
        while (!frame_done_valid) @(negedge clk);
        if (frame_done_error || maps!=576) $fatal(1,"COMPOSE430_FRAME_RESULT");
        frame_done_ready=1;
        @(negedge clk);
        frame_done_ready=0;
    endtask

    task automatic predict;
        @(negedge clk);
        head_valid=1;
        @(posedge clk);
        if (!head_ready) $fatal(1,"COMPOSE430_HEAD_NOT_READY");
        @(negedge clk);
        head_valid=0;
        while (!head_done_valid) @(negedge clk);
        if (head_done_error || head_done_id!==0 || head_done_tag!==head_tag ||
            head_done_inner!==18'(expect_inner) || head_done_recent!==18'(expect_recent) ||
            head_done_streaming!==(expect_streaming!=0) || reading)
            $fatal(1,"COMPOSE430_HEAD_RESULT inner=%0d recent=%0d streaming=%b",
                   head_done_inner,head_done_recent,head_done_streaming);
        head_done_ready=1;
        @(negedge clk);
        head_done_ready=0;
    endtask

    task automatic attend_row(input int rank,position);
        @(negedge clk);
        row_values=0; row_tag=32'h43010000+32'(rank);
        row_position=11'(position); row_key_count=rank==PROMPT ? 11'(SLOTS) : 11'(PROMPT);
        row_query_addr=CACHE_BASE+64'(rank*64); row_valid=1;
        @(posedge clk);
        if (!row_ready) $fatal(1,"COMPOSE430_ROW_NOT_READY");
        @(negedge clk);
        row_valid=0;
        while (!result_valid) @(negedge clk);
        repeat (2) begin
            if (!result_valid || result_error || result_tag!==row_tag || result_values!==expected_result ||
                row_values!=expected_value_requests || reading || value_pending)
                $fatal(1,"COMPOSE430_ROW_RESULT rank=%0d",rank);
            @(negedge clk);
        end
        result_ready=1;
        @(negedge clk);
        result_ready=0;
        rows++;
    endtask

    initial begin
        int file, rank, position, image_start, shift;
        if (!$value$plusargs("FIXTURE=%s",fixture) || !$value$plusargs("DUMP=%s",dump))
            $fatal(1,"COMPOSE430_FIXTURE");
        $readmemh({fixture,"/activation.hex"},activations);
        $readmemh({fixture,"/weights.hex"},weights);
        $readmemh({fixture,"/cos.hex"},cosines);
        $readmemh({fixture,"/sin.hex"},sines);
        $readmemh({fixture,"/shifts.hex"},shifts);
        $readmemh({fixture,"/biases.hex"},biases);
        $readmemh({fixture,"/expected.hex"},expected);
        projection_shifts=shifts[0];
        repeat (3) @(negedge clk);
        rst_n=1;
        if (INTEGRATE==0) begin
            for (int group_id=0;group_id<3;group_id++) project(group_id,SHARD*16,16,0);
            file=$fopen(dump,"w");
            if (!file) $fatal(1,"COMPOSE430_DUMP_OPEN");
            for (int group_id=0;group_id<3;group_id++)
                for (int i=0;i<16;i++) $fdisplay(file,"%h",cache[group_id*SLOTS+SHARD*16+i]);
            $fclose(file);
            $display("COMPOSE430_SHARD_PASS shard=%0d writes=%0d stalls=%0d",SHARD,writes,stalled_writes);
        end else begin
            for (int group_id=0;group_id<3;group_id++) begin
                $readmemh($sformatf("%s/seed_%0d.hex",fixture,group_id),cache,group_id*SLOTS,group_id*SLOTS+399);
                for (int i=0;i<400;i++) begin
                    if (cache[group_id*SLOTS+i]!==expected[group_id*SLOTS+i]) $fatal(1,"COMPOSE430_SEED");
                    committed[group_id*SLOTS+i]=1;
                end
            end
            $readmemh({fixture,"/map.hex"},golden);
            $readmemh({fixture,"/signs.hex"},signs);
            file=$fopen({fixture,"/rows.txt"},"r");
            if (!file || $fscanf(file,"%d %d %d %d %d %d",image_start,head_alpha,shift,expect_inner,
                                 expect_recent,expect_streaming)!=6) $fatal(1,"COMPOSE430_REFERENCE");
            frame_image_start=10'(image_start); row_score_shift=7'(shift);
            build_frame();
            project(2,400,8,1);
            for (int group_id=0;group_id<3;group_id++) project(group_id,400,8,0);
            predict();
            for (int i=0;i<4;i++) begin
                if ($fscanf(file,"%d %d %d %h",rank,position,expected_value_requests,expected_result)!=4)
                    $fatal(1,"COMPOSE430_ROW_REFERENCE");
                if (rank==PROMPT)
                    for (int group_id=0;group_id<3;group_id++) project(group_id,PROMPT,1,0);
                attend_row(rank,position);
            end
            $fclose(file);
            $display("COMPOSE430_PASS maps=%0d writes=%0d failed_writes=%0d rows=%0d values=%0d attention_reads=%0d stalls=%0d",
                     maps,writes,failed_writes,rows,values,attention_reads,stalled_writes);
        end
        $finish;
    end

    initial begin
        #100000000;
        $fatal(1,"COMPOSE430_TIMEOUT shard=%0d",SHARD);
    end
endmodule
