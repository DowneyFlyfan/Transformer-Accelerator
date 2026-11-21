`timescale 1ns/1ps

// Real mapped metadata owner and six compiled memory models;
// prediction peers and the context controller remain behavioral.
module tri_oracle_context_metadata_drain_tb;
    localparam int TOKENS = 16, STRIPS = 256, GROUPS = 176;
    localparam int EXPECTED_READS = 9152;
    localparam logic [63:0] GATE_BASE = 64'h0000000bffffff00;
    localparam logic [31:0] TAG = 32'h404c0001;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic cfg_valid = 0, cfg_ready;
    logic meta_valid = 0, meta_last = 0, meta_ready;
    logic [3:0] meta_token = 0;
    logic [9:0] meta_index = 0;
    logic [7:0] meta_outliers = 0, meta_negative = 0;
    logic commit_valid = 0, commit_ready;
    logic out_valid, out_ready, out_last;
    logic [31:0] out_tag, done_tag;
    logic [7:0] out_group;
    logic [3:0] out_token;
    logic [31:0] gate_nearzero_mask, up_nearzero_mask, skip_mask;
    logic [12:0] outlier_count;
    logic done_valid, done_error;
    logic [1:0] req_valid, req_ready;
    logic [63:0] req_address;
    logic [5:0] req_length;
    logic [1:0] rsp_valid, rsp_ready;
    logic [1:0][511:0] rsp_data;
    logic [533:0] strip_request;
    logic [111:0] strip_response;
    logic [111:0] cluster_response [0:4];

    logic [15:0] norm_words [0:TOKENS*STRIPS*8-1];
    logic [15:0] counts [0:TOKENS-1];
    logic [95:0] expected_masks [0:TOKENS*GROUPS-1];
    logic [511:0] lines [GROUPS*STRIPS];
    logic [65:0] expected_addresses [0:EXPECTED_READS-1];
    int metadata_commit_events=0;
    int cycle = 0, reads = 0, logical_reads = 0, checks = 0, skipped = 0;
    logic [1:0] pending = 0;
    int primary = 0, auxiliary = 0;


    wire [5:0] metadata_ce_n,metadata_we_n;
    wire [53:0] metadata_address;
    wire [767:0] metadata_write_data,metadata_write_mask,metadata_read_data;
    wire context_metadata_idle;
    logic allow_context=0,c_cfg_valid=0,c_cfg_ready,c_row_valid=0,c_row_ready;
    logic [10:0] c_query=0;
    logic [4:0] c_head=0;
    logic [2047:0] c_data=0;
    logic signed [7:0] c_value_unit=0;
    logic c_metadata_block,c_invalid,c_rebuilt,c_lease,c_valid;
    logic signed [8:0] c_unit;
    logic [31:0] c_tag;
    logic [10:0] c_result_query;
    logic c_read_valid=0,c_read_ready,c_response_valid,c_response_ready=0,c_response_error;
    logic [9:0] c_word=0;
    logic [63:0] c_response;
    logic c_finish=0,c_finish_ready,c_done,c_done_ready=0,c_error;
    logic [2055:0] c_rows[64];logic [63:0] c_codes[512];logic [8:0] c_units[2];
    logic owner_done_ready=0,metadata_old_work_drained=0;
    always @(posedge clk)if(rst_n && c_lease && !metadata_old_work_drained)$fatal(1,"CONTEXT_METADATA_LEASED_BEFORE_DRAIN");
    always @(posedge clk)if(rst_n && c_rebuilt)begin
      if(!commit_valid || !commit_ready || c_lease)$fatal(1,"CONTEXT_METADATA_FALSE_COMMIT");
      metadata_commit_events++;
    end
    tri_oracle_context_handoff context_controller (
      .clk,.rst_n,.cfg_valid(c_cfg_valid),.cfg_ready(c_cfg_ready),.cfg_tag(32'hcc170000+32'(c_query)),
      .cfg_query(c_query),.cfg_zero_exponent(9'sd0),
      .row_valid(c_row_valid),.row_ready(c_row_ready),.row_error(1'b0),.row_query(c_query),
      .row_head(c_head),.row_data(c_data),.row_value_exponent(c_value_unit),
      .metadata_idle(allow_context && context_metadata_idle),.metadata_block(c_metadata_block),
      .metadata_needs_rebuild(c_invalid),.metadata_rebuilt(c_rebuilt),.lease_active(c_lease),
      .metadata_ce_n,.metadata_we_n,.metadata_address,.metadata_write_data,.metadata_write_mask,.metadata_read_data,
      .context_valid(c_valid),.context_tag(c_tag),.context_query(c_result_query),.context_exponent(c_unit),
      .read_req_valid(c_read_valid),.read_req_ready(c_read_ready),.read_req_word(c_word),
      .read_rsp_valid(c_response_valid),.read_rsp_ready(c_response_ready),.read_rsp_error(c_response_error),.read_rsp_data(c_response),
      .finish_valid(c_finish),.finish_ready(c_finish_ready),.done_valid(c_done),.done_ready(c_done_ready),.done_error(c_error)
    );
    task automatic controller_roundtrip;
      string a,b,c;
      if(!$value$plusargs("RAW_ROWS=%s",a)||!$value$plusargs("CONVERTED_WORDS=%s",b)||!$value$plusargs("RAW_UNITS=%s",c))
        $fatal(1,"CONTEXT_MAPPED_FIXTURES");
      $readmemh(a,c_rows);$readmemh(b,c_codes);$readmemh(c,c_units);
      allow_context=1;
      for(int frame=0;frame<2;frame++)begin
        if(frame!=0)begin
          @(negedge clk);c_query=11'(frame);c_cfg_valid=1;
          @(posedge clk);if(!c_cfg_ready)$fatal(1,"CONTEXT_MAPPED_CONFIG");
          @(negedge clk);c_cfg_valid=0;
        end
        for(int wait_cycles=0;wait_cycles<100;wait_cycles++)begin @(negedge clk);if(c_lease)break;end
        if(!c_lease)$fatal(1,"CONTEXT_METADATA_DRAIN_NEVER_LEASED");
        cfg_valid=1;
        repeat(3)begin
          @(posedge clk);
          if(cfg_ready || !context_metadata_idle)$fatal(1,"CONTEXT_NEW_METADATA_WORK_NOT_BLOCKED");
          @(negedge clk);
        end
        cfg_valid=0;
        for(int i=0;i<32;i++)begin
          c_head=5'(17*i+31);{c_value_unit,c_data}=c_rows[frame*32+int'(c_head)];c_row_valid=1;
          do @(posedge clk);while(!c_row_ready);
          @(negedge clk);c_row_valid=0;
        end
        wait(c_valid);@(negedge clk);
        if(c_unit!==c_units[frame] || c_result_query!==11'(frame) || c_tag!==32'hcc170000+32'(frame))
          $fatal(1,"CONTEXT_MAPPED_UNITS");
        for(int word=0;word<256;word++)begin
          c_word=10'(word);c_read_valid=1;
          @(posedge clk);if(!c_read_ready)$fatal(1,"CONTEXT_MAPPED_READ");
          @(negedge clk);c_read_valid=0;c_finish=1;
          repeat(2)begin
            @(posedge clk);
            if(!c_response_valid || c_response_error || c_response!==c_codes[frame*256+word] || c_finish_ready || !c_lease)
              $fatal(1,"CONTEXT_MAPPED_RESPONSE frame=%0d word=%0d",frame,word);
            @(negedge clk);
          end
          c_finish=0;c_response_ready=1;@(negedge clk);c_response_ready=0;
        end
        c_finish=1;@(posedge clk);if(!c_finish_ready)$fatal(1,"CONTEXT_MAPPED_FINISH");
        @(negedge clk);c_finish=0;wait(c_done);@(negedge clk);
        if(c_error || c_lease || c_valid || !c_invalid)$fatal(1,"CONTEXT_MAPPED_RELEASE");
        c_done_ready=1;@(negedge clk);c_done_ready=0;
      end
      allow_context=0;
      if(c_metadata_block || !c_invalid)$fatal(1,"CONTEXT_MAPPED_REBUILD_BOUNDARY");
      $display("CONTEXT_MAPPED_FRAMES_PASS frames=2 code_words=512 common_units=-8,-9");
    endtask

    tri_oracle_packed_outlier_replay_CORE_STRIP_PREDICTOR1 dut (
        .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_tag(TAG), .cfg_tokens(5'(TOKENS)),
        .cfg_strips(10'(STRIPS)), .cfg_groups(8'(GROUPS)), .cfg_sign_base(GATE_BASE), .meta_valid, .meta_last, .meta_ready, .meta_tag(TAG),
        .meta_token, .meta_index, .meta_outliers, .meta_negative, .commit_valid, .abort_fill(1'b0),
        .commit_ready, .out_valid, .out_ready, .out_last, .out_tag, .out_group, .out_token,
        .gate_nearzero_mask, .up_nearzero_mask, .skip_mask, .outlier_count, .done_valid,
        .done_ready(owner_done_ready), .done_error, .done_tag, .req_valid, .req_ready, .req_address, .req_length,
        .rsp_valid, .rsp_ready, .rsp_last(2'b11), .rsp_error(2'b00),
        .\rsp_data[0] (rsp_data[0]), .\rsp_data[1] (rsp_data[1]), .strip_request, .strip_response,
        .key_owner(1'b0), .storage_select(1'b0), .storage_write(1'b0),
        .storage_address(5'b0), .storage_data(512'b0), .storage_read(),
        .metadata_ce_n,.metadata_we_n,.metadata_address,.metadata_write_data,.metadata_write_mask,.metadata_read_data,
        .context_metadata_block(c_metadata_block),.context_metadata_idle,.context_metadata_commit(c_rebuilt)
    );
    // Count acknowledged cache reads from the original mapped state register.
    logic [2:0] previous_fetch_state;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) previous_fetch_state <= 3'd0;
        else previous_fetch_state <= dut.sign_memory_state;
    end
    wire observed_cache_accept = previous_fetch_state == 3'd1 && dut.sign_memory_state == 3'd2;
    assign strip_response = cluster_response[strip_request[533:531]];
    for (genvar cluster = 0; cluster < 5; cluster++) begin : prediction_clusters
        wire [587:0] requests;
        wire [159:0] responses;
        tri_oracle_cluster_strip448 distributor (
            .request(strip_request[533:531] == 3'(cluster) ? strip_request[530:0] : '0),
            .response(cluster_response[cluster]), .core_requests(requests), .core_responses(responses)
        );
        for (genvar core = 0; core < 4; core++) begin : prediction_cores
            tri_oracle_core_strip448 core_predictor (
                .clk, .rst_n, .request(requests[147*core+:147]), .response(responses[40*core+:40])
            );
        end
    end

    assign req_ready = {2{pending == 0 && cycle % 7 != 0}};
    assign rsp_valid = pending;
    assign out_ready = cycle % 13 != 0;
    always @(posedge clk) begin : monitor
        int index;
        cycle <= cycle + 1;
        if (rst_n) begin
            if (|(req_valid & req_ready)) begin
                logic [1:0] granted;
                granted = req_valid & req_ready;
                if (reads >= EXPECTED_READS || req_length != 1 || req_address !== expected_addresses[reads][63:0] ||
                    granted !== expected_addresses[reads][65:64])
                    $fatal(1, "PACKED_SIGN_PREDICTOR_ADDRESS index=%0d address=%h lane=%b", reads, req_address, granted);
                index = int'((req_address - GATE_BASE) >> 6);
                if (granted[0]) begin
                    rsp_data[0] <= lines[index];
                    primary++;
                end else begin
                    rsp_data[1] <= lines[index];
                    auxiliary++;
                end
                pending <= granted;
                reads++;
            end else if (|(rsp_valid & rsp_ready)) pending <= 0;
            if (observed_cache_accept) logical_reads++;
            if (out_valid && out_ready) begin
                if (checks >= TOKENS*GROUPS || out_group != 8'(checks / TOKENS) || out_token != 4'(checks % TOKENS) ||
                    out_last != (checks == TOKENS*GROUPS-1) || out_tag !== TAG ||
                    outlier_count !== counts[out_token][12:0] ||
                    {gate_nearzero_mask, up_nearzero_mask, skip_mask} !== expected_masks[int'(out_token)*GROUPS+int'(out_group)])
                    $fatal(1, "TRAINED_SIGN_CACHE_MASK check=%0d group=%0d token=%0d", checks, out_group, out_token);
                skipped += $countones(skip_mask);
                checks++;
            end
        end
    end

    initial begin : stimulus
        string fixture, norm, addresses, packed_file;
        logic signed [15:0] value;
        if (!$value$plusargs("FIXTURE=%s", fixture) || !$value$plusargs("NORM=%s", norm) ||
            !$value$plusargs("ADDRESSES=%s", addresses) || !$value$plusargs("PACKED=%s", packed_file)) $fatal(1, "TRAINED_SIGN_CACHE_FIXTURES");
        $readmemh(norm, norm_words);
        $readmemh(addresses, expected_addresses);
        $readmemh({fixture, "/branch_masks.hex"}, expected_masks);
        $readmemh({fixture, "/outlier_counts.hex"}, counts);
        $readmemh(packed_file, lines);
        repeat (2) @(negedge clk);
        rst_n = 1;
        cfg_valid = 1;
        do @(posedge clk); while (!cfg_ready);
        @(negedge clk);
        cfg_valid = 0;
        commit_valid=1;
        repeat(3)begin
          @(posedge clk);
          if(commit_ready || c_rebuilt || !c_invalid)$fatal(1,"CONTEXT_METADATA_PREMATURE_ACK");
          @(negedge clk);
        end
        commit_valid=0;
        for (int token = 0; token < TOKENS; token++) begin
            for (int strip = 0; strip < STRIPS; strip++) begin
                if(token==0 && strip==16)begin
                  meta_valid=0;allow_context=1;c_query=0;c_cfg_valid=1;
                  @(posedge clk);if(!c_cfg_ready)$fatal(1,"CONTEXT_METADATA_DRAIN_CONFIG");
                  @(negedge clk);c_cfg_valid=0;
                  repeat(2)begin
                    @(posedge clk);
                    if(c_lease || !c_metadata_block || context_metadata_idle || !c_invalid)
                      $fatal(1,"CONTEXT_METADATA_DRAIN_NOT_WAITING");
                    @(negedge clk);
                  end
                end
                meta_valid = 1;
                meta_last = strip == STRIPS - 1;
                meta_token = 4'(token);
                meta_index = 10'(strip);
                for (int lane = 0; lane < 8; lane++) begin
                    value = $signed(norm_words[(token*STRIPS + strip)*8 + lane]);
                    meta_outliers[lane] = value > 16'sd768 || value < -16'sd768;
                    meta_negative[lane] = value < 0;
                end
                do @(posedge clk); while (!meta_ready);
                @(negedge clk);
            end
        end
        meta_valid = 0;
        commit_valid = 1;
        do @(posedge clk); while (!commit_ready);
        @(negedge clk);
        commit_valid = 0;
        if(!c_invalid || metadata_commit_events!=1)$fatal(1,"CONTEXT_METADATA_COMMIT_NOT_ACKNOWLEDGED");
        wait (done_valid);
        @(negedge clk);
        if (done_error !== 0 || done_tag !== TAG || pending || reads != EXPECTED_READS || logical_reads != 27808 || primary != 2569 ||
            auxiliary != 6583 ||
            checks != GROUPS * TOKENS || skipped != 5231) $fatal(1, "TRAINED_SIGN_CACHE_INVENTORY");
        $display("PACKED_SIGN_PREDICTOR_PASS groups=%0d bits_per_mask=32 skipped=%0d logical=%0d external=%0d cycles=%0d",
                 checks, skipped, logical_reads, reads, cycle);
        if(c_lease || !c_invalid || !c_metadata_block)$fatal(1,"CONTEXT_METADATA_DRAIN_COMPLETION");
        metadata_old_work_drained=1;owner_done_ready=1;@(negedge clk);owner_done_ready=0;
        controller_roundtrip();
        if(!c_invalid || c_metadata_block || metadata_commit_events!=1)$fatal(1,"CONTEXT_METADATA_DRAIN_FINAL");
        $display("CONTEXT_EXISTING_METADATA_DRAIN_PASS masks=2816 skipped=5231 logical=27808 external=9152 commits=1 frames=2 code_words=512");
        $finish;
    end

    initial begin
        #30000000;
        $fatal(1, "TRAINED_SIGN_CACHE_TIMEOUT");
    end
endmodule
