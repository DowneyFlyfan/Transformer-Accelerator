`timescale 1ns/1ps
// Prospective Task2 test, written before its production module. Synthetic
// normalized beats exercise compaction; this is not RMS/model-accuracy proof.
module tri_oracle_normalized_image_compactor_tb;
  import tri_oracle_merge_range_types::*;
  logic clk=0,rst_n=0;
  int cycles=0,frame_number=0;
  always #5 clk=~clk;
  // Drive clock-dependent backpressure only at the negative edge. The DUT
  // therefore sees a stable ready value throughout each positive-edge event.
  always @(negedge clk)begin
    cycles++;
    if(cycles>8000000)$fatal(1,"COMPACTOR_WATCHDOG");
  end
  typedef enum logic [1:0] {Nobody,Compactor,Projection} owner_t;
  owner_t owner=Nobody;
  logic checking=0,expect_error=0,abort_valid=0,row_source_error=0;
  logic cfg_valid=0,cfg_ready,cfg_new_image=1;
  logic [11:0] cfg_minimum_matches=2048;
  logic [31:0] cfg_tag_base=32'h1000_0000;
  logic [4:0] cfg_layer=0;
  logic [15:0] cfg_epoch=1;
  logic [63:0] cfg_immutable_input_base=64'h1000_0000;
  logic [63:0] cfg_immutable_input_bytes=64'h20_0000;
  logic [63:0] cfg_compact_output_base=64'h2000_0000;
  logic frame_protect,epoch_invalid;
  logic row_request_valid,row_request_ready,producer_idle=1;
  logic [9:0] row_request_original_root,row_request_input_rank;
  logic [31:0] row_request_tag;
  logic [4:0] row_request_layer;
  logic [15:0] row_request_epoch;
  logic in_valid=0,in_ready,in_last=0,in_error=0;
  logic [31:0] in_tag=0;
  logic [9:0] in_index=0;
  logic [3:0] in_count=8;
  logic [63:0] in_activation=0;
  logic signed [8:0] in_exponent=0;
  logic [7:0] in_negative=0;
  logic memory_acquire_valid,memory_acquire_ready,memory_context_owned;
  logic frame_port_granted,memory_req_valid,memory_req_ready,memory_req_write;
  logic [9:0] memory_req_word;
  logic [63:0] memory_req_data,memory_rsp_data;
  logic memory_rsp_valid,memory_rsp_ready,memory_rsp_error;
  request_t merge_request;
  response_t merge_response;
  logic [2047:0] merge_sign_data;
  tri_oracle_token_size_types::request_t size_request_observed;
  tri_oracle_token_size_types::response_t size_response_observed;
  logic vector_req_valid,vector_req_ready,vector_rsp_valid,vector_rsp_ready,vector_rsp_error;
  logic [63:0] vector_req_address;
  logic [511:0] vector_req_data;
  logic image_done_valid,image_done_ready=0,image_error,abort_drained;
  logic [31:0] handoff_tag_base;
  logic [4:0] handoff_layer;
  logic [15:0] handoff_epoch;
  logic [9:0] handoff_input_count,handoff_kept_count;

  // The owner enum really selects the one physical store's ports.
  logic ff_idle=1;
  logic [1:0] ff_ce_n=3,ff_we_n=3;
  logic [17:0] ff_address=0;
  logic [127:0] ff_write_data=0,ff_read_data;
  logic store_acquire_valid,store_acquire_ready,store_release_valid,store_release_ready;
  logic store_req_valid,store_req_ready,store_req_write,store_rsp_valid,store_rsp_ready,store_rsp_error;
  logic [9:0] store_req_word;
  logic [63:0] store_req_data,store_rsp_data;
  logic projection_req_valid=0,projection_rsp_ready=0,projection_release=0;
  logic [9:0] projection_word=0;
  logic raw_cfg_valid,raw_cfg_ready,raw_sign_ready,raw_map_valid,raw_map_ready;
  logic [9:0] raw_map_index,raw_map_origin;
  logic raw_map_last,raw_done_valid,raw_done_error;
  logic query_valid=0,size_out_ready=0;
  logic [9:0] query_position=575,size_out_origin;
  logic bridge_abort;

  // Real external-write mux followed by a backpressured test transport.
  logic mem_req_valid,mem_req_ready,mem_data_valid,mem_data_ready,mem_data_last;
  logic [63:0] mem_req_address,mem_data;
  logic [4:0] mem_req_length;
  logic [7:0] mem_strobe;
  logic mem_rsp_valid=0,mem_rsp_ready,mem_rsp_error=0;
  logic hold_request=0,hold_response=0,inject_external_error=0;
  logic transport_busy=0,response_due=0;
  int transport_beat=0,response_delay=0;
  logic [63:0] accepted_external_address=0;
  logic [511:0] observed_external_line=0;
  int vendor_cell_count=0;
  logic [22:0] vendor_cells_seen=0;

  // These are observation/scoreboard registers, never a source of keep decisions.
  int requested_rows=0,signed_rows=0,retired_maps=0,kept_maps=0;
  int stage_writes=0,compact_reads=0,descriptor_writes=0,descriptor_acks=0;
  int vector_lines=0,vector_acks=0,serialized_beats=0,done_acks=0;
  int total_lines=0,total_beats=0,total_rows=0,total_maps=0;
  int current_root=0,current_rank=0,survivor_root=0,survivor_input_rank=0;
  int survivor_read_word=0,survivor_lines=0;
  logic [31:0] current_tag=0,survivor_tag=0;
  logic signed [8:0] current_exponent=0,survivor_exponent=0;
  logic row_pending=0,decision_pending=0,survivor_pending=0;
  logic memory_pending=0,pending_write=0;
  logic [9:0] pending_word=0;
  logic [63:0] pending_data=0;
  int parent_handoffs=0,physical_releases=0,clobber_attempts=0,passes=0;
  int logical_grants=0,logical_releases=0,rejected_configurations=0,no_lease_aborts=0;
  int positive_rows=0,positive_maps=0,positive_lines=0,positive_beats=0;
  logic no_physical_lease_case=0,parent_acquired=0,observed_protect=0;
  int configuration_test_kind=0;
  logic handoff_abort_seen=0;

  // These assertions independently observe the production outputs/real Stage;
  // TB ownership alone cannot stand in for the missing frame protection.
  always @(posedge clk)if(rst_n)begin
    if(frame_protect!==observed_protect)begin
      $display("COMPACTOR_PROTECT frame=%0d cycle=%0d level=%0b owner=%0d physical_owned=%0b",frame_number,cycles,frame_protect,owner,memory_context_owned);
      observed_protect=frame_protect;
    end
    if(cfg_valid && cfg_ready)
      $display("COMPACTOR_CONFIG_ACCEPT frame=%0d cycle=%0d kind=%0d input_base=%016h input_bytes=%016h output_base=%016h tag_base=%08h threshold=%0d new_image=%0b layer=%0d epoch=%0d",frame_number,cycles,configuration_test_kind,cfg_immutable_input_base,cfg_immutable_input_bytes,cfg_compact_output_base,cfg_tag_base,cfg_minimum_matches,cfg_new_image,cfg_layer,cfg_epoch);
    if(abort_valid)begin
      $display("COMPACTOR_ABORT_SAMPLE frame=%0d cycle=%0d component_packet=%05h raw_map_valid=%0b size_request=%07h size_response=%04h relay_state=%0d active_bank=%0d",frame_number,cycles,merge_request,raw_map_valid,size_request_observed,size_response_observed,merge_fabric.relay.state,merge_fabric.relay.active_bank);
      if(frame_number==3 && !handoff_abort_seen)begin
        // This samples the real relay before its positive-edge state update.
        check(merge_fabric.relay.state===2'd2 && merge_fabric.relay.active_bank===3'd1,
          "FIRST_ABORT_EDGE_MISSED_REAL_RELAY_HANDOFF");
        handoff_abort_seen=1;
        $display("COMPACTOR_HANDOFF_ABORT_EDGE frame=%0d cycle=%0d relay_state=%0d active_bank=%0d",frame_number,cycles,merge_fabric.relay.state,merge_fabric.relay.active_bank);
      end
    end
    if(cfg_valid || (owner==Compactor && (checking || no_physical_lease_case || memory_context_owned)))
      check(frame_protect,"FRAME_PROTECTION_NOT_ASSERTED_BEFORE_HANDOFF");
    if(bridge_abort && (checking || no_physical_lease_case))begin
      check(!merge_request.cfg_valid && !merge_request.sign_valid &&
        !merge_request.done_ready && merge_request.map_ready,
        "DUT_ABORT_PACKET_HIDDEN_BY_PARENT_SAFETY_OVERRIDE");
      check(merge_response.map_valid===raw_map_valid && merge_response.cfg_ready===raw_cfg_ready &&
        merge_response.sign_ready===raw_sign_ready && merge_response.done_valid===raw_done_valid,
        "ABORT_OBSERVER_MASKED_RAW_NATIVE_STATUS");
    end
  end

  tri_oracle_normalized_image_compactor dut (.*);
  tri_oracle_shared_metadata_store memory (
    .clk,.rst_n,.ff_idle,.acquire_valid(store_acquire_valid),.acquire_ready(store_acquire_ready),
    .release_valid(store_release_valid),.release_ready(store_release_ready),.context_owned(memory_context_owned),
    .ff_ce_n,.ff_we_n,.ff_address,.ff_write_data,.ff_read_data,
    .req_valid(store_req_valid),.req_ready(store_req_ready),.req_write(store_req_write),
    .req_word(store_req_word),.req_data(store_req_data),.rsp_valid(store_rsp_valid),
    .rsp_ready(store_rsp_ready),.rsp_error(store_rsp_error),.rsp_data(store_rsp_data)
  );
  tri_oracle_local_merge_fabric merge_fabric (
    .clk,.rst_n,.cfg_valid(raw_cfg_valid),.cfg_new_image(merge_request.cfg_new_image),
    .cfg_ready(raw_cfg_ready),.cfg_minimum_matches(merge_request.threshold),
    .sign_valid(merge_request.sign_valid && !bridge_abort),.sign_ready(raw_sign_ready),.sign_data(merge_sign_data),
    .map_valid(raw_map_valid),.map_ready(raw_map_ready),.map_index(raw_map_index),
    .map_origin(raw_map_origin),.map_last(raw_map_last),.done_valid(raw_done_valid),
    .done_error(raw_done_error),.done_ready(merge_request.done_ready && !bridge_abort),
    .size_frame_valid(size_request_observed.frame_valid),.size_frame_ready(size_response_observed.frame_ready),
    .size_map_valid(size_request_observed.map_valid),.size_map_ready(size_response_observed.map_ready),
    .query_valid(size_request_observed.query_valid),.query_ready(size_response_observed.query_ready),
    .query_position(size_request_observed.query_position),.out_valid(size_response_observed.out_valid),
    .out_ready(size_request_observed.out_ready),.out_origin(size_out_origin),
    .out_count(size_response_observed.out_count),.out_last(size_response_observed.out_last),
    .size_error(size_response_observed.error)
  );
  tri_oracle_external_write_mux write_mux (
    .clk,.rst_n,.scalar_req_valid(1'b0),.scalar_req_ready(),.scalar_req_address(64'b0),
    .scalar_req_length(5'b0),.scalar_data_valid(1'b0),.scalar_data_ready(),.scalar_data_last(1'b0),
    .scalar_data(64'b0),.scalar_strobe(8'b0),.scalar_rsp_valid(),.scalar_rsp_ready(1'b0),.scalar_rsp_error(),
    .vector_req_valid,.vector_req_ready,.vector_req_address,.vector_req_data,
    .vector_rsp_valid,.vector_rsp_ready,.vector_rsp_error,
    .mem_req_valid,.mem_req_ready,.mem_req_address,.mem_req_length,.mem_data_valid,.mem_data_ready,
    .mem_data_last,.mem_data,.mem_strobe,.mem_rsp_valid,.mem_rsp_ready,.mem_rsp_error
  );

  always_comb begin
    frame_port_granted=owner==Compactor;
    store_acquire_valid=owner==Compactor && memory_acquire_valid;
    memory_acquire_ready=owner==Compactor && store_acquire_ready;
    store_release_valid=owner==Projection && projection_release;
    store_req_valid=owner==Compactor ? memory_req_valid : owner==Projection && projection_req_valid;
    store_req_write=owner==Compactor && memory_req_write;
    store_req_word=owner==Compactor ? memory_req_word : projection_word;
    store_req_data=owner==Compactor ? memory_req_data : 64'b0;
    memory_req_ready=owner==Compactor && store_req_ready;
    store_rsp_ready=owner==Compactor ? memory_rsp_ready : owner==Projection && projection_rsp_ready;
    memory_rsp_valid=owner==Compactor && store_rsp_valid;
    memory_rsp_error=store_rsp_error;
    memory_rsp_data=store_rsp_data;
    row_request_ready=producer_idle;
    bridge_abort=abort_valid || epoch_invalid || image_error;
    raw_cfg_valid=!bridge_abort && merge_request.cfg_valid && size_response_observed.frame_ready;
    raw_map_ready=bridge_abort ? 1'b1 : merge_request.map_ready && size_response_observed.map_ready;
    merge_response='0;
    merge_response.cfg_ready=bridge_abort ? raw_cfg_ready : raw_cfg_ready && size_response_observed.frame_ready;
    merge_response.sign_ready=raw_sign_ready;
    merge_response.map_valid=bridge_abort ? raw_map_valid : raw_map_valid && size_response_observed.map_ready;
    merge_response.map_index=raw_map_index;merge_response.map_origin=raw_map_origin;
    merge_response.map_last=raw_map_last;merge_response.done_valid=raw_done_valid;merge_response.done_error=raw_done_error;
    size_request_observed='0;
    size_request_observed.frame_valid=!bridge_abort && merge_request.cfg_valid && raw_cfg_ready;
    size_request_observed.map_valid=!bridge_abort && raw_map_valid && merge_request.map_ready;
    size_request_observed.map_origin=raw_map_origin;size_request_observed.map_last=raw_map_last;
    size_request_observed.query_valid=query_valid;
    size_request_observed.query_position=query_position;size_request_observed.out_ready=size_out_ready;
    mem_req_ready=!hold_request && !transport_busy && !response_due && !mem_rsp_valid && cycles%7!=0;
    mem_data_ready=transport_busy && cycles%5!=0;
  end

  function automatic logic [63:0] activation(input int layer,input int original_root,input int word_index);
    return 64'h8102_0304_a5b6_c7d8 ^ (64'(layer)<<56) ^
           (64'(original_root)*64'h0101_0001_0001_0001) ^ (64'(word_index)*64'h0000_0101_0100_0001);
  endfunction
  function automatic logic [2047:0] signs(input int original_root);
    logic [2047:0] result;
    result='0;result[original_root]=1'b1;return result;
  endfunction
  function automatic logic signed [8:0] exponent(input int original_root);
    return 9'((original_root%512)-256);
  endfunction
  function automatic logic [63:0] descriptor(input int original_root,input int input_rank,input int compact_rank);
    logic [63:0] result;
    result='0;result[31:0]=cfg_tag_base+32'(input_rank);
    result[41:32]=10'(original_root);result[51:42]=10'(compact_rank);
    result[60:52]=exponent(original_root);result[62]=1;return result;
  endfunction
  task automatic check(input logic condition,input string reason);
    if(condition!==1'b1)$fatal(1,"COMPACTOR_%s frame=%0d cycle=%0d",reason,frame_number,cycles);
  endtask
  task automatic pass(input string reason);
    passes++;$display("COMPACTOR_CASE_PASS name=%s",reason);
  endtask

  // Producer reads ONLY hardware row requests. The oracle checks a request;
  // it cannot supply a keep bit, select the next root or manufacture a map.
  initial forever begin : normalized_producer
    int root_snapshot,rank_snapshot;
    logic [31:0] tag_snapshot;
    logic [2047:0] sign_snapshot;
    @(posedge clk);
    if(rst_n && row_request_valid && row_request_ready)begin
      root_snapshot=int'(row_request_original_root);rank_snapshot=int'(row_request_input_rank);
      tag_snapshot=row_request_tag;sign_snapshot=signs(root_snapshot);
      @(negedge clk);producer_idle=0;
      repeat(2)@(negedge clk);
      for(int word_index=0;word_index<256;word_index++)begin
        in_valid=1;in_tag=tag_snapshot;in_index=10'(word_index);in_count=8;
        in_last=word_index==255;in_error=0;in_exponent=exponent(root_snapshot);
        in_activation=activation(int'(cfg_layer),root_snapshot,word_index);
        in_negative=sign_snapshot[word_index*8+:8];
        do @(posedge clk);while(!in_ready);
        @(negedge clk);in_valid=0;
        if(word_index%17==0)repeat(2)@(negedge clk);
      end
      producer_idle=1;
    end
  end

  // One real downstream transaction at a time. Record actual serialized words,
  // not the offered golden vector, then log the reconstructed 512-bit payload.
  always @(posedge clk)begin
    if(!rst_n)begin
      transport_busy<=0;response_due<=0;mem_rsp_valid<=0;mem_rsp_error<=0;
      transport_beat=0;response_delay=0;
    end else begin
      if(mem_req_valid && mem_req_ready)begin
        check(!transport_busy && !response_due && !mem_rsp_valid,"OVERLAPPED_EXTERNAL_REQUEST");
        check(mem_req_length===5'd8,"EXTERNAL_LENGTH");
        check(mem_req_address===cfg_compact_output_base+64'(descriptor_acks)*2048+64'(survivor_lines)*64,"EXTERNAL_ADDRESS");
        accepted_external_address=mem_req_address;observed_external_line='0;
        transport_busy<=1;transport_beat=0;
      end
      if(mem_data_valid && mem_data_ready)begin
        check(transport_busy && mem_strobe===8'hff && mem_data_last===(transport_beat==7),"EXTERNAL_BEAT_PROTOCOL");
        check(mem_data===activation(int'(cfg_layer),survivor_root,survivor_lines*8+transport_beat),"EXTERNAL_BEAT_PAYLOAD");
        observed_external_line[transport_beat*64+:64]=mem_data;
        transport_beat++;serialized_beats++;total_beats++;
        if(mem_data_last)begin
          $display("COMPACTOR_LINE frame=%0d root=%0d compact_rank=%0d line=%0d address=%016h data=%0128h",frame_number,survivor_root,descriptor_acks,survivor_lines,accepted_external_address,observed_external_line);
          transport_busy<=0;response_due<=1;response_delay=3;vector_lines++;total_lines++;
        end
      end
      if(response_due && !hold_response)begin
        if(response_delay!=0)response_delay--;
        else begin mem_rsp_valid<=1;mem_rsp_error<=inject_external_error;response_due<=0;end
      end
      if(mem_rsp_valid && mem_rsp_ready)begin
        check(expect_error || !mem_rsp_error,"UNEXPECTED_EXTERNAL_ERROR");
        mem_rsp_valid<=0;mem_rsp_error<=0;vector_acks++;survivor_lines++;
        $display("COMPACTOR_VECTOR_ACK frame=%0d cycle=%0d rank=%0d line=%0d address=%016h error=%0b acknowledged_lines=%0d",frame_number,cycles,descriptor_acks,survivor_lines-1,accepted_external_address,mem_rsp_error,vector_acks);
      end
      if(store_acquire_valid && store_acquire_ready)begin
        check(!parent_acquired && owner==Compactor,"PHYSICAL_ACQUIRE_HISTORY");parent_acquired=1;
        $display("COMPACTOR_OWNERSHIP event=acquire frame=%0d cycle=%0d owner=%0d context_owned_pre=%0b protect=%0b",frame_number,cycles,owner,memory_context_owned,frame_protect);
      end
      if(image_done_valid && image_done_ready)begin
        $display("COMPACTOR_OWNERSHIP event=handoff frame=%0d cycle=%0d owner=%0d context_owned=%0b acquired_history=%0b error=%0b input_count=%0d kept_count=%0d protect=%0b",frame_number,cycles,owner,memory_context_owned,parent_acquired,image_error,handoff_input_count,handoff_kept_count,frame_protect);
        check(owner==Compactor && !memory_pending && !store_rsp_valid &&
              !transport_busy && !response_due && !mem_rsp_valid && !vector_req_valid && producer_idle,"HANDOFF_NOT_DRAINED");
        if(no_physical_lease_case)begin
          check(!memory_context_owned && image_error && epoch_invalid,"INVENTED_PHYSICAL_LEASE_ON_REJECTION");owner<=Nobody;
        end else begin
          check(memory_context_owned,"HANDOFF_DROPPED_PHYSICAL_LEASE");owner<=Projection;parent_handoffs++;
        end
      end
      if(store_release_valid && store_release_ready)begin
        check(owner==Projection && !store_rsp_valid && !memory_pending,"PARENT_RELEASE_NOT_DRAINED");
        check(parent_acquired,"PHYSICAL_RELEASE_WITHOUT_ACQUIRE");parent_acquired=0;physical_releases++;
        $display("COMPACTOR_OWNERSHIP event=release frame=%0d cycle=%0d owner=%0d context_owned_pre=%0b",frame_number,cycles,owner,memory_context_owned);
      end
    end
  end

  always @(posedge clk)if(rst_n && checking)begin : scoreboard
    if(dut.stage_start_valid && dut.stage_start_ready)begin
      check(dut.stage_acquire_valid && dut.stage_acquire_ready && memory_context_owned && frame_port_granted,
        "STAGE_START_WITHOUT_REAL_LOGICAL_ACQUIRE");logical_grants++;
      $display("COMPACTOR_ROW_LEASE event=acquire frame=%0d cycle=%0d count=%0d physical_owned=%0b frame_granted=%0b",frame_number,cycles,logical_grants,memory_context_owned,frame_port_granted);
    end
    if(dut.stage_memory_release_valid && dut.virtual_release_ready)begin
      logical_releases++;
      $display("COMPACTOR_ROW_LEASE event=release frame=%0d cycle=%0d count=%0d physical_owned=%0b frame_granted=%0b",frame_number,cycles,logical_releases,memory_context_owned,frame_port_granted);
    end
    if(row_request_valid && row_request_ready)begin
      check(memory_context_owned && frame_port_granted && !row_pending && !decision_pending && !survivor_pending,"BAD_ROW_DEMAND_OWNERSHIP");
      check(raw_sign_ready && !raw_map_valid && dut.stage_lease_held && dut.row_grant &&
        logical_grants==requested_rows+1 && logical_releases==requested_rows,
        "ROW_REQUEST_BEFORE_REAL_DEMAND_AND_LOGICAL_STAGE_GRANT");
      check(row_request_input_rank===10'(requested_rows) && row_request_tag===cfg_tag_base+32'(requested_rows) &&
            row_request_layer===cfg_layer && row_request_epoch===cfg_epoch,"ROW_IDENTITY");
      check(row_request_original_root===(frame_number==2 ? 10'd0 : 10'(requested_rows)),"REQUEST_NOT_ACTUAL_PRIOR_ROOT");
      current_root=int'(row_request_original_root);current_rank=int'(row_request_input_rank);
      current_tag=row_request_tag;current_exponent=exponent(current_root);
      row_pending=1;requested_rows++;total_rows++;
      $display("COMPACTOR_ROW_REQUEST frame=%0d cycle=%0d original_root=%0d input_rank=%0d tag=%08h layer=%0d epoch=%0d exponent=%0d physical_owned=%0b frame_granted=%0b stage_lease=%0b raw_sign_ready=%0b raw_map_valid=%0b",frame_number,cycles,current_root,current_rank,current_tag,row_request_layer,row_request_epoch,$signed(current_exponent),memory_context_owned,frame_port_granted,dut.stage_lease_held,raw_sign_ready,raw_map_valid);
    end
    // Deliberately process old map BEFORE a possible same-edge new sign.
    if(raw_map_valid && raw_map_ready)begin
      check(raw_map_index===10'(retired_maps) && raw_map_last===(retired_maps==575),"MAP_ORDER_OR_LAST");
      check(raw_map_origin===(frame_number==0 ? 10'(retired_maps) : 10'd0),"INDEPENDENT_MAP_ORACLE");
      if(!bridge_abort)begin
        check((merge_response.map_valid && merge_request.map_ready) &&
              (size_request_observed.map_valid && size_response_observed.map_ready),"THREE_WAY_MAP_FIRE");
        if(decision_pending)begin
          check(raw_map_index===10'(current_root),"NEW_DECISION_INDEX");
          decision_pending=0;row_pending=0;
          if(raw_map_origin==raw_map_index)begin
            check(!survivor_pending,"OVERLAPPED_SURVIVOR");
            survivor_pending=1;survivor_root=current_root;survivor_input_rank=current_rank;
            survivor_tag=current_tag;survivor_exponent=current_exponent;
            survivor_read_word=0;survivor_lines=0;kept_maps++;
          end
        end
      end
      $display("COMPACTOR_MAP frame=%0d cycle=%0d index=%0d origin=%0d last=%0b component_fire=%0b size_fire=%0b abort=%0b",frame_number,cycles,raw_map_index,raw_map_origin,raw_map_last,merge_response.map_valid && merge_request.map_ready,size_request_observed.map_valid && size_response_observed.map_ready,bridge_abort);
      retired_maps++;total_maps++;
    end
    if(merge_request.sign_valid && raw_sign_ready && !bridge_abort)begin
      check(row_pending && !decision_pending && !survivor_pending && merge_sign_data===signs(current_root),"REAL_SIGN_VALUE_OR_ASSOCIATION");
      decision_pending=1;signed_rows++;
      $display("COMPACTOR_SIGN frame=%0d cycle=%0d root=%0d input_rank=%0d tag=%08h exponent=%0d negative=%0512h",frame_number,cycles,current_root,current_rank,dut.stage_row_tag,$signed(dut.stage_row_exponent),merge_sign_data);
    end
    if(raw_cfg_valid && raw_cfg_ready)
      check(size_request_observed.frame_valid && size_response_observed.frame_ready && merge_request.cfg_valid && merge_response.cfg_ready,"THREE_WAY_CONFIG_FIRE");
    if(raw_done_valid && merge_request.done_ready && !bridge_abort)begin
      check(retired_maps==576 && !raw_done_error && done_acks==0,"DONE_ACK_BEFORE_ALL_MAPS");done_acks++;
      $display("COMPACTOR_DONE_ACK frame=%0d cycle=%0d error=%0b maps=%0d",frame_number,cycles,raw_done_error,retired_maps);
    end
    if(store_req_valid && store_req_ready && owner==Compactor)begin
      check(!memory_pending,"RAM_REQUEST_OVERLAP");memory_pending=1;
      pending_write=store_req_write;pending_word=store_req_word;pending_data=store_req_data;
      if(store_req_write && store_req_word<256)begin
        check(store_req_data===activation(int'(cfg_layer),current_root,int'(store_req_word)),"STAGE_WRITE_PAYLOAD");stage_writes++;
      end else if(!store_req_write)begin
        check(survivor_pending && store_req_word===10'(survivor_read_word),"COMPACT_READ_ORDER");survivor_read_word++;compact_reads++;
      end else begin
        check(survivor_pending && survivor_read_word==256 && survivor_lines==32 &&
              store_req_word===10'(256+descriptor_acks) &&
              store_req_data===descriptor(survivor_root,survivor_input_rank,descriptor_acks),"DESCRIPTOR_BEFORE_ACK_OR_BAD_DATA");descriptor_writes++;
        $display("COMPACTOR_DESCRIPTOR_REQUEST frame=%0d cycle=%0d word=%0d data=%016h rank=%0d",frame_number,cycles,store_req_word,store_req_data,store_req_data[51:42]);
      end
    end
    if(store_rsp_valid && store_rsp_ready && owner==Compactor)begin
      check(memory_pending && !store_rsp_error,"RAM_RESPONSE_IDENTITY_OR_ERROR");
      if(!pending_write)check(store_rsp_data===activation(int'(cfg_layer),survivor_root,int'(pending_word)),"ACTUAL_STAGED_READ_DATA");
      else if(pending_word>=256)begin
        $display("COMPACTOR_DESCRIPTOR_ACK frame=%0d cycle=%0d word=%0d data=%016h rank=%0d error=%0b",frame_number,cycles,pending_word,pending_data,pending_data[51:42],store_rsp_error);
        descriptor_acks++;survivor_pending=0;
      end
      memory_pending=0;
    end
    if(image_done_valid && !image_error)check(done_acks==1 && retired_maps==576 && !decision_pending &&
      !row_pending && !survivor_pending && producer_idle,"EARLY_SUCCESS");
  end

  task automatic clear_counts;
    requested_rows=0;signed_rows=0;retired_maps=0;kept_maps=0;stage_writes=0;compact_reads=0;
    descriptor_writes=0;descriptor_acks=0;vector_lines=0;vector_acks=0;serialized_beats=0;done_acks=0;
    row_pending=0;decision_pending=0;survivor_pending=0;memory_pending=0;
    survivor_read_word=0;survivor_lines=0;logical_grants=0;logical_releases=0;
  endtask
  task automatic start_frame(input int number,input bit new_image,input int threshold);
    @(negedge clk);check(owner==Nobody && !memory_context_owned && producer_idle,"START_PARENT_NOT_IDLE");
    clear_counts();frame_number=number;cfg_layer=5'(number);cfg_epoch=16'(number+1);
    cfg_tag_base=32'h1000_0000+32'(number)*32'h1_0000;cfg_new_image=new_image;
    cfg_minimum_matches=12'(threshold);owner=Compactor;checking=1;cfg_valid=1;
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;
  endtask
  task automatic projection_read(input int word_index,input logic [63:0] wanted);
    @(negedge clk);projection_word=10'(word_index);projection_req_valid=1;
    do @(posedge clk);while(!store_req_ready);
    @(negedge clk);projection_req_valid=0;projection_rsp_ready=1;
    do @(posedge clk);while(!store_rsp_valid);
    check(!store_rsp_error && store_rsp_data===wanted && memory_context_owned && owner==Projection,"PROJECTION_DESCRIPTOR_READBACK");
    $display("COMPACTOR_PROJECTION_READ frame=%0d cycle=%0d word=%0d data=%016h error=%0b",frame_number,cycles,word_index,store_rsp_data,store_rsp_error);
    @(negedge clk);projection_rsp_ready=0;
  endtask
  task automatic parent_release;
    @(negedge clk);check(owner==Projection && memory_context_owned,"RELEASE_WITHOUT_ACTUAL_PARENT_GRANT");projection_release=1;
    do @(posedge clk);while(!store_release_ready);
    @(negedge clk);projection_release=0;check(!memory_context_owned,"PHYSICAL_RELEASE_FAILED");owner=Nobody;checking=0;
  endtask
  task automatic finish_success(input int wanted_inputs,input int wanted_kept);
    while(!image_done_valid)@(negedge clk);
    check(!image_error && !epoch_invalid && done_acks==1 && retired_maps==576 && requested_rows==wanted_inputs &&
      signed_rows==wanted_inputs && descriptor_acks==wanted_kept && kept_maps==wanted_kept &&
      stage_writes==wanted_inputs*256 && compact_reads==wanted_kept*256 &&
      vector_lines==wanted_kept*32 && vector_acks==wanted_kept*32 && serialized_beats==wanted_kept*256 &&
      logical_grants==wanted_inputs && logical_releases==wanted_inputs,"COMPLETE_IMAGE_COUNTS");
    check(handoff_input_count===10'(wanted_inputs) && handoff_kept_count===10'(wanted_kept) &&
      handoff_tag_base===cfg_tag_base && handoff_layer===cfg_layer && handoff_epoch===cfg_epoch,"HANDOFF_IDENTITIES");
    repeat(3)begin
      @(negedge clk);
      check(image_done_valid && memory_context_owned && !cfg_ready &&
        handoff_input_count===10'(wanted_inputs) && handoff_kept_count===10'(wanted_kept) &&
        handoff_tag_base===cfg_tag_base && handoff_layer===cfg_layer && handoff_epoch===cfg_epoch,
        "HANDOFF_STALL_CHANGED_PACKET_OR_OWNERSHIP");
    end
    image_done_ready=1;do @(posedge clk);while(!image_done_valid);
    @(negedge clk);image_done_ready=0;check(owner==Projection && memory_context_owned,"HANDOFF_RELEASED_PHYSICAL_LEASE");
    for(int rank=0;rank<wanted_kept;rank++)projection_read(256+rank,descriptor(frame_number==0?rank:0,frame_number==0?rank:0,rank));
    parent_release();pass(frame_number==0?"all576_unique_roots":frame_number==1?"subsequent_merge_to_one":"prior_aliases_only_one_demand");
  endtask
  task automatic attempted_ff_clobber;
    while(descriptor_acks<1)@(negedge clk);
    @(negedge clk);check(memory_context_owned && owner==Compactor,"FF_ATTEMPT_WITHOUT_PHYSICAL_FRAME_LEASE");
    ff_idle=0;ff_ce_n=2'b10;ff_we_n=2'b10;ff_address[8:0]=9'd256;ff_write_data[63:0]=64'hdead_beef_0bad_f00d;
    repeat(9)begin @(posedge clk);check(memory_context_owned && owner==Compactor,"ROW_TURNOVER_DROPPED_PHYSICAL_LEASE");end
    @(negedge clk);ff_ce_n=3;ff_we_n=3;ff_idle=1;clobber_attempts++;
    $display("COMPACTOR_MASKED_FF_ATTEMPT word=256 data=deadbeef0badf00d physical_owned=1");
  endtask
  task automatic delayed_last_vector_ack;
    while(vector_lines<576*32)@(negedge clk);
    hold_response=1;
    repeat(9)begin
      @(negedge clk);
      check(response_due && !mem_rsp_valid && vector_acks==576*32-1 &&
        !image_done_valid && memory_context_owned,"FINAL_EXTERNAL_ACK_BYPASSED");
    end
    hold_response=0;pass("last_real_external_response_blocks_descriptor_and_image_commit");
  endtask
  task automatic query_sizes(input int wanted_outputs,input int wanted_each);
    int outputs,total;
    outputs=0;total=0;
    @(negedge clk);query_valid=1;query_position=575;size_out_ready=0;
    do @(posedge clk);while(!size_response_observed.query_ready);
    @(negedge clk);query_valid=0;
    // A real prior Walk is not cancelled by dropping query_valid. Admission
    // must wait for actual Idle/Load, not trust a synthetic size_idle flag.
    owner=Compactor;cfg_valid=1;
    repeat(3)begin @(negedge clk);check(!cfg_ready && !raw_cfg_valid && !merge_request.sign_valid,"ADMISSION_DURING_REAL_SIZE_WALK");end
    cfg_valid=0;
    while(!size_response_observed.out_valid)@(negedge clk);
    repeat(3)begin @(negedge clk);check(!size_response_observed.frame_ready && !size_response_observed.map_ready && size_response_observed.out_valid,"REAL_SIZE_EMIT_STALL");end
    size_out_ready=1;
    do begin
      @(posedge clk);
      if(size_response_observed.out_valid)begin
        check(!size_response_observed.error && size_response_observed.out_count===10'(wanted_each) &&
          size_out_origin===(wanted_outputs==576 ? 10'(outputs) : 10'd0),"ACTUAL_SIZE_QUERY_VALUE");
        outputs++;total+=int'(size_response_observed.out_count);
      end
    end while(!(size_response_observed.out_valid && size_response_observed.out_last));
    @(negedge clk);size_out_ready=0;owner=Nobody;
    check(outputs==wanted_outputs && total==576,"ACTUAL_SIZE_QUERY_COUNTS");
    repeat(3)@(negedge clk);
    check(size_response_observed.frame_ready && !size_response_observed.out_valid,"SIZE_QUERY_NOT_DRAINED");
    pass("real_size_walk_emit_drain_before_reconfigure");
  endtask
  task automatic check_quiet_cut;
    logic [1:0] merger_branch,size_branch,first_merger_branch,first_size_branch;
    int edge_count;
    edge_count=0;first_merger_branch=0;first_size_branch=0;
    repeat(2)begin
      @(posedge clk);
      merger_branch=raw_sign_ready ? 2'd1 : raw_done_valid ? 2'd2 : raw_cfg_ready ? 2'd3 : 2'd0;
      size_branch=size_response_observed.frame_ready ? 2'd1 : size_response_observed.map_ready ? 2'd2 : 2'd0;
      if(edge_count==0)begin first_merger_branch=merger_branch;first_size_branch=size_branch;end
      else check(merger_branch===first_merger_branch && size_branch===first_size_branch,
        "QUIET_OR_BRANCH_CHANGED_BETWEEN_REQUIRED_EDGES");
      edge_count++;
      $display("COMPACTOR_QUIET_SAMPLE frame=%0d cycle=%0d edge=%0d merger_branch=%0d size_branch=%0d raw_packet=%07h component_packet=%05h size_request=%07h size_response=%04h sign_enables=%03b table_active=%0b",frame_number,cycles,edge_count,merger_branch,size_branch,{raw_cfg_ready,raw_sign_ready,raw_map_valid,raw_map_index,raw_map_origin,raw_map_last,raw_done_valid,raw_done_error},merge_request,size_request_observed,size_response_observed,merge_fabric.sign_control[2:0],merge_fabric.table_request[21]);
      check(!raw_map_valid && (raw_sign_ready || raw_done_valid || raw_cfg_ready) &&
        (size_response_observed.frame_ready || size_response_observed.map_ready) &&
        !size_response_observed.out_valid && !size_request_observed.frame_valid &&
        !size_request_observed.map_valid && !size_request_observed.query_valid &&
        merge_fabric.sign_control[2:0]===3'b000 && !merge_fabric.table_request[21],"SOURCE_PROVED_REAL_QUIET_CUT");
      for(int bank=0;bank<5;bank++)check(!merge_fabric.size_command[bank].walking &&
        !merge_fabric.size_command[bank].table_request[18],"SIBLING_TABLE_REQUEST_NOT_QUIET");
    end
  endtask
  task automatic finish_aborted;
    while(!image_done_valid)@(negedge clk);
    check(image_error && epoch_invalid && abort_drained && memory_context_owned &&
          !transport_busy && !response_due && !mem_rsp_valid && !vector_req_valid && producer_idle,"ABORT_NOT_ACTUALLY_DRAINED");
    if(frame_number==4 || frame_number==5 || frame_number==6)
      check(handoff_kept_count===10'd0,"ABORT_PUBLISHED_INCOMPLETE_OR_QUARANTINED_RANK");
    check_quiet_cut();
    @(negedge clk);image_done_ready=1;do @(posedge clk);while(!image_done_valid);
    @(negedge clk);image_done_ready=0;parent_release();
    check(!memory_pending && !store_rsp_valid && !transport_busy && !response_due && !mem_rsp_valid && producer_idle,"RESET_WITH_LIVE_TRANSACTION");
    @(negedge clk);rst_n=0;repeat(3)@(negedge clk);rst_n=1;
    repeat(3)@(negedge clk);expect_error=0;inject_external_error=0;hold_request=0;hold_response=0;
  endtask
  task automatic pulse_abort;
    @(negedge clk);expect_error=1;abort_valid=1;
    repeat(2)@(negedge clk);abort_valid=0;
  endtask

  task automatic finish_no_lease_fault;
    while(!image_done_valid)@(negedge clk);
    check(image_error && epoch_invalid && abort_drained && !memory_context_owned &&
      !memory_pending && !store_rsp_valid && !vector_req_valid && !transport_busy &&
      !response_due && !mem_rsp_valid && producer_idle,"NO_LEASE_FAULT_NOT_DRAINED");
    check_quiet_cut();
    @(negedge clk);image_done_ready=1;do @(posedge clk);while(!image_done_valid);
    @(negedge clk);image_done_ready=0;check(owner==Nobody && !memory_context_owned && !store_release_valid,
      "NO_LEASE_FAULT_REQUESTED_PHYSICAL_RELEASE");
    rst_n=0;repeat(3)@(negedge clk);rst_n=1;repeat(3)@(negedge clk);
    no_physical_lease_case=0;expect_error=0;ff_idle=1;
  endtask
  task automatic reject_configuration(input int kind);
    @(negedge clk);check(owner==Nobody && !memory_context_owned,"CONFIG_REJECT_START_NOT_IDLE");
    cfg_immutable_input_base=64'h1000_0000;cfg_immutable_input_bytes=64'h20_0000;
    cfg_compact_output_base=64'h2000_0000;cfg_tag_base=32'h4000_0000;
    cfg_minimum_matches=2048;cfg_new_image=1;
    case(kind)
      1:cfg_immutable_input_base=64'h1000_0001;
      2:cfg_immutable_input_bytes=65;
      3:cfg_compact_output_base=64'h2000_0001;
      4:cfg_immutable_input_bytes=0;
      5:begin cfg_immutable_input_base=64'hffff_ffff_ffff_ffc0;cfg_immutable_input_bytes=128;end
      6:cfg_compact_output_base=64'hffff_ffff_ffff_f000;
      7:cfg_compact_output_base=64'h1000_0040;
      8:cfg_tag_base=32'hffff_ffff;
      9:cfg_minimum_matches=2049;
      default:$fatal(1,"COMPACTOR_UNKNOWN_BAD_CONFIGURATION_CASE");
    endcase
    owner=Compactor;no_physical_lease_case=1;expect_error=1;configuration_test_kind=kind;cfg_valid=1;
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;
    while(!image_done_valid)begin
      @(negedge clk);
      check(!memory_acquire_valid && !memory_context_owned && !memory_req_valid &&
        !row_request_valid && !raw_cfg_valid && !merge_request.sign_valid,
        "INVALID_CONFIGURATION_ADVANCED_TO_HARDWARE");
    end
    finish_no_lease_fault();rejected_configurations++;
    $display("COMPACTOR_CONFIG_REJECT kind=%0d real_acquires=0 real_releases=0",kind);
  endtask
  task automatic abort_before_acquire;
    @(negedge clk);cfg_immutable_input_base=64'h1000_0000;cfg_immutable_input_bytes=64'h20_0000;
    cfg_compact_output_base=64'h2000_0000;cfg_tag_base=32'h5000_0000;cfg_minimum_matches=2048;
    ff_idle=0;owner=Compactor;no_physical_lease_case=1;expect_error=1;configuration_test_kind=-1;cfg_valid=1;
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;
    repeat(3)begin @(negedge clk);check(!memory_context_owned && !store_release_valid,"ABORT_CASE_ALREADY_ACQUIRED");end
    abort_valid=1;repeat(2)@(negedge clk);abort_valid=0;
    finish_no_lease_fault();no_lease_aborts++;pass("abort_before_real_acquire_has_no_physical_release");
  endtask

  initial begin
    $display("COMPACTOR_BEGIN normalized_interface=synthetic actual_rms=0 hardware_keep_source=real_TMU");
    repeat(4)@(negedge clk);rst_n=1;repeat(4)@(negedge clk);
    check(vendor_cell_count==23 && vendor_cells_seen===23'h7fffff,"REAL_VENDOR_CENSUS");
    start_frame(0,1,2048);
    fork attempted_ff_clobber();delayed_last_vector_ack();finish_success(576,576);join
    query_sizes(576,1);
    start_frame(1,0,0);finish_success(576,1);query_sizes(1,576);
    start_frame(2,0,0);finish_success(1,1);query_sizes(1,576);
    positive_rows=total_rows;positive_maps=total_maps;positive_lines=total_lines;positive_beats=total_beats;
    check(positive_rows==1153 && positive_maps==1728 && positive_lines==18496 && positive_beats==147968,
      "POSITIVE_ONLY_TOTALS");
    $display("COMPACTOR_POSITIVE_TOTALS frames=3 input_rows=%0d maps=%0d lines=%0d beats=%0d",positive_rows,positive_maps,positive_lines,positive_beats);

    // Old aliases cross every range without supplied keep/roster information.
    start_frame(3,0,0);
    while(merge_fabric.relay.state!==2'd2)@(negedge clk);
    // Assert now: another negative edge would follow the Handoff->Run edge.
    check(merge_fabric.relay.active_bank===3'd1,"HANDOFF_ABORT_TRIGGER_WRONG_BANK");
    $display("COMPACTOR_HANDOFF_ABORT_TRIGGER frame=%0d cycle=%0d relay_state=%0d active_bank=%0d",frame_number,cycles,merge_fabric.relay.state,merge_fabric.relay.active_bank);
    expect_error=1;abort_valid=1; // CURRENT observed Handoff negative edge
    repeat(2)@(negedge clk);abort_valid=0;
    check(handoff_abort_seen,"HANDOFF_ABORT_EDGE_NOT_OBSERVED");
    finish_aborted();pass("abort_real_range_handoff_and_prior_alias_lookup");

    hold_request=1;start_frame(4,1,2048);
    while(!vector_req_valid)@(negedge clk);
    begin
      logic [63:0] held_address;logic [511:0] held_data;
      held_address=vector_req_address;held_data=vector_req_data;
      repeat(3)@(negedge clk);expect_error=1;abort_valid=1;
      repeat(3)begin
        @(negedge clk);check(vector_req_valid && vector_req_address===held_address && vector_req_data===held_data,"ABORT_WITHDRAWN_OFFER_LOCKED_BY_MUX");
        $display("COMPACTOR_ABORT_HELD_OFFER frame=%0d cycle=%0d valid=%0b ready=%0b address=%016h data=%0128h",frame_number,cycles,vector_req_valid,vector_req_ready,vector_req_address,vector_req_data);
      end
      abort_valid=0;hold_request=0;
    end
    finish_aborted();pass("abort_preserves_offered_external_line_until_real_ack");

    inject_external_error=1;expect_error=1;start_frame(5,1,2048);
    finish_aborted();pass("genuine_external_error_quarantines_epoch");

    start_frame(6,1,2048);
    while(!(store_rsp_valid && memory_pending && pending_write && pending_word==256))@(negedge clk);
    // Assert on THIS negative edge, before the still-pending response's next
    // positive-edge handshake. Waiting another negative edge would miss it.
    check(descriptor_acks==0,"DESCRIPTOR_ABORT_TRIGGER_TOO_LATE");
    expect_error=1;abort_valid=1;repeat(2)@(negedge clk);abort_valid=0;
    finish_aborted();pass("abort_on_descriptor_response_never_publishes_image");
    for(int kind=1;kind<=9;kind++)reject_configuration(kind);
    abort_before_acquire();
    check(clobber_attempts==1 && parent_handoffs==7 && physical_releases==7 &&
      rejected_configurations==9 && no_lease_aborts==1,"FINAL_PARENT_ACCOUNTING");
    $display("COMPACTOR_ALL_TRAFFIC_TOTALS input_rows=%0d maps=%0d lines=%0d beats=%0d includes_aborted_frames=1",total_rows,total_maps,total_lines,total_beats);
    $display("COMPACTOR_TASK2_GREEN_PASS cases=%0d positive_input_rows=%0d positive_maps=%0d positive_lines=%0d positive_beats=%0d rejected_configurations=9 real_vendor_cells=23 synthetic_normalized=1",passes,positive_rows,positive_maps,positive_lines,positive_beats);
    $finish;
  end
endmodule
