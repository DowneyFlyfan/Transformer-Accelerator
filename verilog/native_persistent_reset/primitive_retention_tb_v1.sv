`timescale 1ns/1ps
// Primitive reset-domain proof only. No C, metadata lease, trained FF or owner
// fault response is supplied or qualified. One genuine native fabric is used.
module primitive_reset_cell_witness #(parameter int ROLE=0) ();
  initial $display("PERSISTENT_RESET_CELL role=%0d path=%m",ROLE);
endmodule

module primitive_reset_array_witness (
  input logic clk,rst_n,in_valid,in_ready,out_valid,out_ready
);
  initial $display("PERSISTENT_RESET_ARRAY path=%m");
  always @(posedge clk) begin
    if(rst_n===1'b1 && ((in_valid && in_ready)===1'b1 ||
                         (out_valid && out_ready)===1'b1))
      $fatal(1,"PERSISTENT_RESET_UNEXPECTED_COMPUTE_WORK path=%m");
  end
endmodule

module primitive_reset_cluster_witness (
  input logic clk,rst_n,persistent_rst_n,
  input logic [4:0] count,
  input logic [15:0] reserved,complete,
  input logic out_valid
);
  initial $display("PERSISTENT_RESET_CLUSTER path=%m");
  always @(posedge clk) begin
    #1ps;
    if(rst_n===1'b0)begin
      if(count!==5'd0 || reserved!==16'd0 || complete!==16'd0 || out_valid!==1'b0)
        $fatal(1,"PERSISTENT_RESET_COMPUTE_QUEUE_NOT_RESET path=%m");
      $display("PERSISTENT_RESET_CLUSTER_LOW time=%0t persistent_reset=%b path=%m",$time,persistent_rst_n);
    end
  end
endmodule

module tri_oracle_persistent_reset_retention_tb_v1;
  localparam int TOKENS=576;
  localparam time WATCHDOG=10_485_760ns;
  logic clk;
  logic epoch_rst_n,compute_request_rst_n;
  wire compute_rst_n;
  logic cfg_valid_driver,cfg_new_image_driver,sign_valid_driver,done_ready_driver;
  logic size_frame_driver,query_valid_driver,size_ready_driver,map_connect_driver;
  logic [9:0] query_position_driver;
  logic [2047:0] sign_data_driver;
  tri_oracle_merge_range_types::request_t merge_request;
  tri_oracle_merge_range_types::response_t merge_response;
  tri_oracle_token_size_types::request_t size_request;
  tri_oracle_token_size_types::response_t size_response;
  tri_oracle_wac_softmax_types::request_t softmax_request;
  tri_oracle_wac_softmax_types::response_t softmax_response;
  logic [9:0] size_origin;
  logic load_error,cmd_ready;
  logic [4:0] out_valid;
  logic [19:0] out_output;
  logic [5119:0] out_data;
  logic [119:0] sign_counts;
  logic [79:0] merge_word;
  logic [111:0] strip_response;
  logic [72:0] head_response;

  // Sole writers: the monitor below owns observed_* and bank_seen. These
  // variables have no declaration initializers and no driver/task assignments.
  integer observed_map_count,observed_sign_count,observed_cfg_count,cross_bank_aliases;
  integer observed_map[0:TOKENS-1],observed_multiplicity[0:TOKENS-1];
  bit observed_root[0:TOKENS-1];
  logic [4:0] bank_seen;

  // Check-only state owned by the single scenario process and its tasks.
  integer baseline_map[0:TOKENS-1],baseline_multiplicity[0:TOKENS-1];
  bit baseline_root[0:TOKENS-1],query_seen[0:TOKENS-1];
  integer baseline_roots,completed_frames,completed_queries,compute_pulses;

  // This is the actual public reset stimulus. Epoch reset genuinely reaches
  // compute as well; a local compute pulse never becomes an epoch pulse.
  assign compute_rst_n=epoch_rst_n && compute_request_rst_n;
  assign softmax_request='0;
  always_comb begin
    merge_request='0;
    merge_request.cfg_valid=cfg_valid_driver;
    merge_request.cfg_new_image=cfg_new_image_driver;
    merge_request.threshold=12'd1536;
    merge_request.sign_valid=sign_valid_driver;
    merge_request.map_ready=map_connect_driver && size_response.map_ready;
    merge_request.done_ready=done_ready_driver;
    size_request='0;
    size_request.frame_valid=size_frame_driver;
    // Actual merge outputs alone initialize actual token-size bank state.
    size_request.map_valid=map_connect_driver && merge_response.map_valid;
    size_request.map_origin=merge_response.map_origin;
    size_request.map_last=merge_response.map_last;
    size_request.query_valid=query_valid_driver;
    size_request.query_position=query_position_driver;
    size_request.out_ready=size_ready_driver;
  end

  tri_oracle_compute_fabric #(
    .AGGREGATOR_SIGN_BANK(1),.AGGREGATOR_MERGE_TABLE(1),
    .LOCAL_TOKEN_SIZES(1),.LOCAL_TOKEN_MERGE(1),
    .CORE_STRIP_PREDICTOR(1),.CORE_HEAD_PREDICTOR(1)
  ) fabric (
    .clk,.rst_n(compute_rst_n),.persistent_rst_n(epoch_rst_n),
    .load_valid(1'b0),.load_core(5'd0),.load_kind(2'd0),.load_addr(10'd0),
    .load_data(2048'd0),.load_row_enable(32'd0),.load_error,
    .cmd_valid(1'b0),.cmd_ready,.cmd_clusters(5'd0),.cmd_weight(5'd0),.cmd_mask(5'd0),
    .cmd_activation(10'd0),.cmd_output(4'd0),.cmd_accumulate(1'b0),.cmd_reduce(2'd0),
    .out_valid,.out_ready(5'd0),.out_output,.out_data,
    .merge_sign_data(sign_data_driver),.merge_sign_control(13'd0),.merge_sign_counts(sign_counts),
    .merge_table_request(22'd0),.merge_table_word(merge_word),
    .softmax_request,.softmax_response,.activation_reloaded(5'd0),.core_score_select(3'd0),
    .token_sizes_request(size_request),.token_sizes_response(size_response),
    .token_sizes_out_origin(size_origin),.merge_request,.merge_response,
    .strip_rst_n(epoch_rst_n),.strip_request(534'd0),.strip_response,
    .head_request(400'd0),.head_response
  );

  task automatic check(input logic condition,input string message);
    if(condition!==1'b1)$fatal(1,"PERSISTENT_RESET_%s",message);
  endtask

  function automatic logic [2047:0] signs_for(input int index);
    // Six contiguous raster regions deliberately cross the five128-token
    // bank boundaries. Different patterns agree in at most1024 of2048bits.
    if(index<100)return 2048'd0;
    if(index<220)return {2048{1'b1}};
    if(index<340)return {64{32'haaaaaaaa}};
    if(index<460)return {64{32'hcccccccc}};
    if(index<540)return {64{32'hf0f0f0f0}};
    return {64{32'hff00ff00}};
  endfunction

  // Public accepted-map observations, not a map/owner/normalization provider.
  // The only always_ff in this testbench owns all these references/counters.
  always_ff @(posedge clk or negedge epoch_rst_n) begin
    if(!epoch_rst_n)begin
      observed_map_count<=0;observed_sign_count<=0;observed_cfg_count<=0;bank_seen<=0;cross_bank_aliases<=0;
      for(integer i=0;i<TOKENS;i++)begin
        observed_map[i]<=0;observed_multiplicity[i]<=0;observed_root[i]<=0;
      end
    end else if(merge_request.cfg_valid && merge_response.cfg_ready)begin
      observed_map_count<=0;observed_sign_count<=0;observed_cfg_count<=observed_cfg_count+1;bank_seen<=0;cross_bank_aliases<=0;
      for(integer i=0;i<TOKENS;i++)begin
        observed_map[i]<=0;observed_multiplicity[i]<=0;observed_root[i]<=0;
      end
    end else begin
      if(merge_request.sign_valid && merge_response.sign_ready)
        observed_sign_count<=observed_sign_count+1;
      if(merge_response.map_valid && merge_request.map_ready)begin
        check(!$isunknown({merge_response.map_index,merge_response.map_origin,merge_response.map_last}),"UNKNOWN_MAP");
        check(observed_map_count<TOKENS && merge_response.map_index==observed_map_count &&
          merge_response.map_origin<=merge_response.map_index,"MAP_CANONICAL_ORDER");
        if(merge_response.map_origin<merge_response.map_index)
          check(observed_root[merge_response.map_origin] &&
            observed_map[merge_response.map_origin]==merge_response.map_origin,"MAP_ROOT_NOT_REAL");
        else observed_root[merge_response.map_origin]<=1;
        check(merge_response.map_last==(observed_map_count==TOKENS-1),"MAP_LAST");
        observed_map[observed_map_count]<=int'(merge_response.map_origin);
        observed_multiplicity[merge_response.map_origin]<=observed_multiplicity[merge_response.map_origin]+1;
        bank_seen[int'(merge_response.map_origin)/128]<=1;
        if(int'(merge_response.map_origin)/128!=int'(merge_response.map_index)/128)
          cross_bank_aliases<=cross_bank_aliases+1;
        observed_map_count<=observed_map_count+1;
        $display("PERSISTENT_RESET_MAP time=%0t cfg=%0d index=%0d origin=%0d last=%b",
          $time,observed_cfg_count,merge_response.map_index,merge_response.map_origin,merge_response.map_last);
      end
    end
  end

  task automatic quiet_compute;
    #1ps;
    check(epoch_rst_n===1'b1 && compute_request_rst_n===1'b1 && compute_rst_n===1'b1,"REAL_RESET_SELECTION");
    check(out_valid===5'd0,"UNEXPECTED_COMPUTE_OUTPUT");
    check(!cfg_valid_driver && !sign_valid_driver && !query_valid_driver &&
      !size_frame_driver && !merge_response.map_valid && !merge_response.done_valid &&
      size_response.frame_ready && size_response.query_ready && !size_response.out_valid && !size_response.error,
      "PERSISTENT_NOT_QUIET");
  endtask

  task automatic build_frame(input bit new_image,input bit compare_previous);
    @(negedge clk);size_frame_driver=1;map_connect_driver=1;
    do @(posedge clk);while(size_response.frame_ready!==1'b1);
    @(negedge clk);size_frame_driver=0;cfg_new_image_driver=new_image;cfg_valid_driver=1;
    do @(posedge clk);while(merge_response.cfg_ready!==1'b1);
    @(negedge clk);cfg_valid_driver=0;
    for(integer token=0;token<TOKENS;token++)if(new_image || baseline_root[token])begin
      // Cumulative merge advances old aliases internally and accepts a sign
      // only for a surviving prior root; this matches its public sign_ready.
      sign_data_driver=signs_for(token);sign_valid_driver=1;
      do @(posedge clk);while(merge_response.sign_ready!==1'b1);
      @(negedge clk);sign_valid_driver=0;
    end
    while(merge_response.done_valid!==1'b1)@(negedge clk);
    check(merge_response.done_error===1'b0,"MERGE_FRAME_ERROR");
    check(observed_map_count==TOKENS && observed_sign_count==(new_image ? TOKENS : baseline_roots) &&
      bank_seen===5'b11111 && cross_bank_aliases>0,
      "COMPLETE_CROSS_BANK_FRAME");
    if(compare_previous)begin
      for(integer token=0;token<TOKENS;token++)begin
        check(observed_map[token]==baseline_map[token],"CUMULATIVE_OR_REFILL_MAP_CHANGED");
        check(observed_multiplicity[token]==baseline_multiplicity[token] &&
          observed_root[token]==baseline_root[token],"CUMULATIVE_OR_REFILL_ROOT_COUNTS_CHANGED");
      end
    end
    @(negedge clk);done_ready_driver=1;
    do @(posedge clk);while(merge_response.done_valid!==1'b1);
    @(negedge clk);done_ready_driver=0;map_connect_driver=0;
    #1ps;completed_frames++;
    quiet_compute();
    $display("PERSISTENT_RESET_FRAME_COMPLETE frame=%0d new_image=%b maps=%0d signs=%0d banks=%b cross_bank_aliases=%0d",
      completed_frames,new_image,observed_map_count,observed_sign_count,bank_seen,cross_bank_aliases);
  endtask

  task automatic save_baseline;
    baseline_roots=0;
    for(integer token=0;token<TOKENS;token++)begin
      baseline_map[token]=observed_map[token];baseline_multiplicity[token]=observed_multiplicity[token];
      baseline_root[token]=observed_root[token];
      if(observed_root[token])baseline_roots++;
    end
    check(baseline_roots>=5,"BASELINE_DID_NOT_REACH_ALL_BANKS");
  endtask

  task automatic pulse_compute_quiet;
    quiet_compute();
    @(negedge clk);compute_request_rst_n=0;
    repeat(3)begin
      @(posedge clk);#1ps;
      check(epoch_rst_n===1'b1 && compute_rst_n===1'b0 && size_response.query_ready===1'b1 &&
        size_response.error===1'b0,"QUIET_COMPUTE_RESET_LOST_PERSISTENT_READY");
      check(observed_map_count==TOKENS && bank_seen===5'b11111,"COMPUTE_RESET_CHANGED_REFERENCE_EPOCH");
      @(negedge clk);
    end
    compute_request_rst_n=1;compute_pulses++;
    repeat(2)@(negedge clk);
    quiet_compute();
    $display("PERSISTENT_RESET_COMPUTE_PULSE pulse=%0d phase=quiet persistent_reset=1 actual_compute_reset_low=1",compute_pulses);
  endtask

  task automatic query_and_check(input bit reset_while_held);
    integer values,total,last_count;
    logic [25:0] held;
    values=0;total=0;last_count=0;
    for(integer root=0;root<TOKENS;root++)query_seen[root]=0;
    @(negedge clk);query_position_driver=10'd575;query_valid_driver=1;size_ready_driver=0;
    do @(posedge clk);while(size_response.query_ready!==1'b1);
    @(negedge clk);query_valid_driver=0;
    while(size_response.out_valid!==1'b1)@(negedge clk);
    held={size_response,size_origin};
    repeat(2)begin
      @(posedge clk);#1ps;
      check(size_response.out_valid===1'b1 && {size_response,size_origin}===held,"HELD_SIZE_TUPLE_CHANGED");
      @(negedge clk);
    end
    if(reset_while_held)begin
      compute_request_rst_n=0;
      repeat(3)begin
        @(posedge clk);#1ps;
        check(epoch_rst_n===1'b1 && compute_rst_n===1'b0 && size_response.out_valid===1'b1 &&
          {size_response,size_origin}===held,"HELD_SIZE_TUPLE_LOST_DURING_COMPUTE_RESET");
        @(negedge clk);
      end
      compute_request_rst_n=1;compute_pulses++;
      repeat(2)begin
        @(posedge clk);#1ps;
        check(size_response.out_valid===1'b1 && {size_response,size_origin}===held,"HELD_SIZE_TUPLE_LOST_AFTER_COMPUTE_RESET");
        @(negedge clk);
      end
      $display("PERSISTENT_RESET_COMPUTE_PULSE pulse=%0d phase=held persistent_reset=1 actual_compute_reset_low=1",compute_pulses);
    end
    size_ready_driver=1;
    do begin
      @(posedge clk);
      if(size_response.out_valid===1'b1)begin
        check(!$isunknown({size_response,size_origin}) && !size_response.error && size_origin<TOKENS &&
          size_response.out_count!=0,"SIZE_OUTPUT_UNKNOWN_OR_INVALID");
        check(baseline_root[size_origin] && !query_seen[size_origin] &&
          int'(size_response.out_count)==baseline_multiplicity[size_origin],"SIZE_ROOT_OR_MULTIPLICITY_CHANGED");
        query_seen[size_origin]=1;values++;total+=int'(size_response.out_count);
        if(size_response.out_last)last_count++;
        $display("PERSISTENT_RESET_SIZE query=%0d origin=%0d count=%0d last=%b",
          completed_queries,size_origin,size_response.out_count,size_response.out_last);
      end
    end while(!(size_response.out_valid===1'b1 && size_response.out_last===1'b1));
    @(negedge clk);size_ready_driver=0;#1ps;
    check(values==baseline_roots && total==TOKENS && last_count==1,"INCOMPLETE_SIZE_WALK");
    for(integer root=0;root<TOKENS;root++)check(query_seen[root]==baseline_root[root],"SIZE_ROOT_SET_CHANGED");
    completed_queries++;
    quiet_compute();
    $display("PERSISTENT_RESET_QUERY_COMPLETE query=%0d values=%0d total=%0d last_count=%0d held_compute_pulse=%b",
      completed_queries,values,total,last_count,reset_while_held);
  endtask

  task automatic epoch_invalidate_and_deny_old_context;
    quiet_compute();
    @(negedge clk);epoch_rst_n=0;
    repeat(3)@(negedge clk);
    check(compute_rst_n===1'b0,"GLOBAL_RESET_DID_NOT_REACH_COMPUTE");
    epoch_rst_n=1;
    repeat(3)@(negedge clk);
    check(size_response.frame_ready===1'b1 && size_response.query_ready===1'b0 &&
      size_response.out_valid===1'b0,"GLOBAL_RESET_REUSED_OLD_SIZE_SEMANTICS");
    query_valid_driver=1;query_position_driver=10'd575;
    repeat(8)begin
      @(posedge clk);#1ps;
      check(size_response.query_ready===1'b0 && size_response.out_valid===1'b0,"OLD_QUERY_PUBLISHED_AFTER_EPOCH_RESET");
      @(negedge clk);
    end
    query_valid_driver=0;cfg_new_image_driver=0;cfg_valid_driver=1;
    do @(posedge clk);while(merge_response.cfg_ready!==1'b1);
    @(negedge clk);cfg_valid_driver=0;
    while(merge_response.done_valid!==1'b1)@(negedge clk);
    check(merge_response.done_error===1'b1 && observed_map_count==0 && observed_sign_count==0,
      "GLOBAL_RESET_REUSED_OLD_MERGE_HAS_MAP");
    done_ready_driver=1;
    do @(posedge clk);while(merge_response.done_valid!==1'b1);
    @(negedge clk);done_ready_driver=0;
    $display("PERSISTENT_RESET_EPOCH_INVALIDATED old_query_denied=1 cumulative_without_refill_error=1 SRAM_contents_erasure_claimed=0");
  endtask

  initial begin : clock_source
    clk=0;
    forever #5 clk=~clk;
  end
  initial begin : global_watchdog
    #WATCHDOG;$fatal(1,"PERSISTENT_RESET_SIMULATION_WATCHDOG");
  end
  initial begin : scenario
    epoch_rst_n=0;compute_request_rst_n=0;
    cfg_valid_driver=0;cfg_new_image_driver=1;sign_valid_driver=0;done_ready_driver=0;
    size_frame_driver=0;query_valid_driver=0;size_ready_driver=0;map_connect_driver=0;
    query_position_driver=0;sign_data_driver=0;
    baseline_roots=0;completed_frames=0;completed_queries=0;compute_pulses=0;
    for(integer i=0;i<TOKENS;i++)begin
      baseline_map[i]=0;baseline_multiplicity[i]=0;baseline_root[i]=0;query_seen[i]=0;
    end
    repeat(4)@(negedge clk);epoch_rst_n=1;compute_request_rst_n=1;
    repeat(2)@(negedge clk);
    build_frame(1,0);save_baseline();query_and_check(0);
    pulse_compute_quiet();query_and_check(0);query_and_check(1);
    build_frame(0,1);query_and_check(0);
    epoch_invalidate_and_deny_old_context();
    build_frame(1,1);query_and_check(0);
    check(completed_frames==3 && completed_queries==5 && compute_pulses==2,"PRIMITIVE_SEQUENCE_INCOMPLETE");
    $display("PERSISTENT_RESET_PRIMITIVE_RETENTION_PASS frames=%0d queries=%0d compute_pulses=%0d tokens=576 roots=%0d cross_bank=5 native_macros_expected=621 arrays_expected=20 census_requires_independent_review=1 owner_fault_qualified=0 real_row_frame_FLUSH_qualified=0 paper_matching=0",
      completed_frames,completed_queries,compute_pulses,baseline_roots);
    $finish;
  end
endmodule

bind TS5N28HPCPSVTA32X128M2FW primitive_reset_cell_witness #(.ROLE(0)) reset_cell();
bind TS5N28HPCPSVTA512X64M4F primitive_reset_cell_witness #(.ROLE(1)) reset_cell();
bind TS6N28HPCPSVTA16X128M2F primitive_reset_cell_witness #(.ROLE(2)) reset_cell();
bind TS5N28HPCPSVTA24X128M2FW primitive_reset_cell_witness #(.ROLE(3)) reset_cell();
bind TS5N28HPCPSVTA16X80M2FW primitive_reset_cell_witness #(.ROLE(4)) reset_cell();
bind TS5N28HPCPSVTA8X80M2FW primitive_reset_cell_witness #(.ROLE(5)) reset_cell();
bind tri_oracle_pe_array primitive_reset_array_witness reset_array(.clk,.rst_n,.in_valid,.in_ready,.out_valid,.out_ready);
bind tri_oracle_sram_compute_cluster primitive_reset_cluster_witness reset_cluster(.clk,.rst_n,.persistent_rst_n,.count,.reserved,.complete,.out_valid);
