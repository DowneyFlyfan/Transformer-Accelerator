`timescale 1ns/1ps
// SOURCE-ONLY integrated draft; no native authority or qualified parent result.
// Input-only raw/gain/metadata provider; no normalized fixture or supplied keep.
module tri_oracle_normalized_image_compactor_tb;
  import tri_oracle_merge_range_types::*;
  localparam int JOURNAL_BITS=7411, JOURNAL_DIGITS=1853;
  localparam int RAW_BYTES=4759552,GAMMA_BYTES=6144,META_BYTES=9216;
  localparam logic [63:0] RAW_BASE=64'h10000000,GAMMA_BASE=64'h12000000,META_BASE=64'h11000000;
  logic clk = 0;
  logic rst_n = 0;
  logic abort_valid = 0;
  logic cfg_valid = 0;
  logic cfg_ready;
  logic cfg_new_image = 1;
  logic [11:0] cfg_minimum_matches = 12'd1536;
  logic [31:0] cfg_tag_base = 32'h60000000;
  logic [4:0] cfg_layer = 0;
  logic [15:0] cfg_epoch = 1;
  logic [9:0] cfg_image_start = 5;
  logic [9:0] cfg_input_rows = 576;
  logic [63:0] cfg_raw_frame_base = 64'h10000000;
  logic [63:0] cfg_raw_frame_bytes = 64'd4759552;
  logic [63:0] cfg_metadata_base = 64'h11000000;
  logic [63:0] cfg_metadata_bytes = 64'd9216;
  logic [63:0] cfg_gamma_base = 64'h12000000;
  logic [63:0] cfg_gamma_bytes = 64'd6144;
  logic [63:0] cfg_compact_output_base = 64'h20000000;
  logic signed [7:0] cfg_gamma_exponent = -8'sd23;
  logic read_req_valid;
  logic read_req_ready;
  logic [63:0] read_req_address;
  logic [4:0] read_req_length;
  logic read_rsp_valid;
  logic read_rsp_last;
  logic read_rsp_error;
  logic read_rsp_ready;
  logic [63:0] read_rsp_data;
  logic store_acquire_valid;
  logic store_release_valid;
  logic store_req_valid;
  logic store_req_write;
  logic store_rsp_ready;
  logic store_acquire_ready;
  logic store_release_ready;
  logic store_context_owned;
  logic store_req_ready;
  logic store_rsp_valid;
  logic store_rsp_error;
  logic [9:0] store_req_word;
  logic [63:0] store_req_data;
  logic [63:0] store_rsp_data;
  logic next_req_valid = 0;
  logic next_req_write = 0;
  logic next_rsp_ready = 0;
  logic next_release_valid = 0;
  logic next_req_ready;
  logic next_rsp_valid;
  logic next_rsp_error;
  logic next_release_ready;
  logic [9:0] next_req_word = 0;
  logic [63:0] next_req_data = 0;
  logic [63:0] next_rsp_data;
  logic vector_req_valid;
  logic vector_rsp_ready;
  logic vector_req_ready;
  logic vector_rsp_valid;
  logic vector_rsp_error;
  logic [63:0] vector_req_address;
  logic [511:0] vector_req_data;
  logic done_valid;
  logic done_error;
  logic epoch_fault;
  logic frame_protect;
  logic metadata_needs_rebuild;
  logic port_idle;
  logic idle;
  logic done_ready = 0;
  logic metadata_rebuilt = 0;
  logic [31:0] done_tag_base;
  logic [4:0] done_layer;
  logic [15:0] done_epoch;
  logic [9:0] done_input_count;
  logic [9:0] done_kept_count;
  logic [16:0] fabric_merge_request;
  logic [25:0] fabric_merge_response;
  logic [2047:0] fabric_sign_data;
  logic [24:0] fabric_size_request;
  logic [15:0] fabric_size_response;
  logic [9:0] fabric_size_out_origin;
  logic [24:0] next_size_request;
  logic [15:0] next_size_response;
  logic [9:0] next_size_out_origin;
  byte unsigned raw_memory[0:RAW_BYTES-1],gamma_memory[0:GAMMA_BYTES-1],metadata_memory[0:META_BYTES-1];
  string input_root,journal_path,catalogue_sha,input_manifest_sha;
  int journal_fd=0,episode_id=0,input_layout_generation=0;
  longint unsigned tick=0,edge_count=0;
  logic journal_enabled=0,data_loaded=0,input_layout_frozen=0;
  logic ff_idle=1;
  logic [1:0] ff_ce_n=3,ff_we_n=3;
  logic [17:0] ff_address=0;
  logic [127:0] ff_write_data=0,ff_read_data;
  logic [22:0] vendor_cells_seen=0;
  int vendor_cell_count=0;
  tri_oracle_merge_range_types::request_t raw_merge_request;
  tri_oracle_merge_range_types::response_t raw_merge_response;
  tri_oracle_token_size_types::request_t raw_size_request,next_size;
  tri_oracle_token_size_types::response_t raw_size_response,next_size_reply;
  logic mem_req_valid,mem_req_ready,mem_data_valid,mem_data_ready,mem_data_last;
  logic [63:0] mem_req_address,mem_data;
  logic [4:0] mem_req_length;
  logic [7:0] mem_strobe;
  logic mem_rsp_valid=0,mem_rsp_ready,mem_rsp_error=0;
  logic read_busy=0,hold_read_request=0,hold_write_request=0,hold_write_response=0;
  logic [63:0] read_address=0;
  logic [4:0] read_length=0;
  int read_beat=0,read_delay=0;
  logic transport_busy=0,response_due=0;
  int transport_beat=0,response_delay=0;
  logic [511:0] accepted_vector=0;
  logic [63:0] accepted_write_address=0;
  logic store_pending=0,store_pending_write=0;
  logic [9:0] store_pending_word=0;
  logic [63:0] store_pending_data=0;
  logic [63:0] observed_descriptor[0:575];
  bit actual_self_root[0:575];
  int read_requests=0,read_responses=0,normalized_words=0,bcfgs=0,bdones=0;
  int maps=0,signs=0,self_roots=0,descriptor_acks=0,vector_lines=0,vector_acks=0,serialized_beats=0;
  int acquisitions=0,releases=0,child_done_acks=0,parent_done_acks=0;
  int successor_rows=0,positive_frames=0;
  logic previous_read_hold=0,previous_vector_hold=0,previous_done_hold=0;
  logic [68:0] previous_read_packet=0;
  logic [575:0] previous_vector_packet=0;
  logic [73:0] previous_done_packet=0;
  logic [JOURNAL_BITS-1:0] journal_packet;
  tri_oracle_raw32_frame_parent_v1 dut (
    .clk, .rst_n, .abort_valid, .cfg_valid, .cfg_ready, .cfg_new_image, .cfg_minimum_matches, .cfg_tag_base, .cfg_layer, .cfg_epoch, .cfg_image_start, .cfg_input_rows, .cfg_raw_frame_base, .cfg_raw_frame_bytes, .cfg_metadata_base, .cfg_metadata_bytes, .cfg_gamma_base, .cfg_gamma_bytes, .cfg_compact_output_base, .cfg_gamma_exponent, .read_req_valid, .read_req_ready, .read_req_address, .read_req_length, .read_rsp_valid, .read_rsp_last, .read_rsp_error, .read_rsp_ready, .read_rsp_data, .store_acquire_valid, .store_release_valid, .store_req_valid, .store_req_write, .store_rsp_ready, .store_acquire_ready, .store_release_ready, .store_context_owned, .store_req_ready, .store_rsp_valid, .store_rsp_error, .store_req_word, .store_req_data, .store_rsp_data, .next_req_valid, .next_req_write, .next_rsp_ready, .next_release_valid, .next_req_ready, .next_rsp_valid, .next_rsp_error, .next_release_ready, .next_req_word, .next_req_data, .next_rsp_data, .vector_req_valid, .vector_rsp_ready, .vector_req_ready, .vector_rsp_valid, .vector_rsp_error, .vector_req_address, .vector_req_data, .done_valid, .done_error, .epoch_fault, .frame_protect, .metadata_needs_rebuild, .port_idle, .idle, .done_ready, .metadata_rebuilt, .done_tag_base, .done_layer, .done_epoch, .done_input_count, .done_kept_count, .fabric_merge_request, .fabric_merge_response, .fabric_sign_data, .fabric_size_request, .fabric_size_response, .fabric_size_out_origin, .next_size_request, .next_size_response, .next_size_out_origin
  );
  tri_oracle_shared_metadata_store memory (
    .clk,.rst_n,.ff_idle,.acquire_valid(store_acquire_valid),.acquire_ready(store_acquire_ready),
    .release_valid(store_release_valid),.release_ready(store_release_ready),.context_owned(store_context_owned),
    .ff_ce_n,.ff_we_n,.ff_address,.ff_write_data,.ff_read_data,
    .req_valid(store_req_valid),.req_ready(store_req_ready),.req_write(store_req_write),
    .req_word(store_req_word),.req_data(store_req_data),.rsp_valid(store_rsp_valid),
    .rsp_ready(store_rsp_ready),.rsp_error(store_rsp_error),.rsp_data(store_rsp_data)
  );
  // No second bridge here: the production parent drives actual raw endpoints.
  assign raw_merge_request=fabric_merge_request;
  assign fabric_merge_response=raw_merge_response;
  assign raw_size_request=fabric_size_request;
  assign fabric_size_response=raw_size_response;
  assign next_size_request=next_size;
  assign next_size_reply=next_size_response;
  tri_oracle_local_merge_fabric merge_fabric (
    .clk,.rst_n,.cfg_valid(raw_merge_request.cfg_valid),.cfg_new_image(raw_merge_request.cfg_new_image),
    .cfg_ready(raw_merge_response.cfg_ready),.cfg_minimum_matches(raw_merge_request.threshold),
    .sign_valid(raw_merge_request.sign_valid),.sign_ready(raw_merge_response.sign_ready),.sign_data(fabric_sign_data),
    .map_valid(raw_merge_response.map_valid),.map_ready(raw_merge_request.map_ready),
    .map_index(raw_merge_response.map_index),.map_origin(raw_merge_response.map_origin),
    .map_last(raw_merge_response.map_last),.done_valid(raw_merge_response.done_valid),
    .done_error(raw_merge_response.done_error),.done_ready(raw_merge_request.done_ready),
    .size_frame_valid(raw_size_request.frame_valid),.size_frame_ready(raw_size_response.frame_ready),
    .size_map_valid(raw_size_request.map_valid),.size_map_ready(raw_size_response.map_ready),
    .query_valid(raw_size_request.query_valid),.query_ready(raw_size_response.query_ready),
    .query_position(raw_size_request.query_position),.out_valid(raw_size_response.out_valid),
    .out_ready(raw_size_request.out_ready),.out_origin(fabric_size_out_origin),
    .out_count(raw_size_response.out_count),.out_last(raw_size_response.out_last),.size_error(raw_size_response.error)
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
  always #5 clk=~clk;
  always @(negedge clk)begin
    tick++;
    if(tick>=16777216)$fatal(1,"FRAME_PARENT_EDGE_WATCHDOG");
  end
  always_comb begin
    read_req_ready=rst_n && data_loaded && input_layout_frozen && !read_busy && !read_rsp_valid && !hold_read_request && tick%5!=1;
    mem_req_ready=rst_n && !hold_write_request && !transport_busy && !response_due && !mem_rsp_valid && tick%7!=0;
    mem_data_ready=rst_n && transport_busy && tick%5!=0;
  end
  task automatic check(input logic condition,input string reason);
    if(condition!==1'b1)$fatal(1,"FRAME_PARENT_%s episode=%0d edge=%0d",reason,episode_id,edge_count);
  endtask

  task automatic load_inputs;
    int fd,count,tail;
    fd=$fopen({input_root,"/raw_frame_i32_le.bin"},"rb");check(fd!=0,"MISSING_RAW_INPUT");
    count=$fread(raw_memory,fd);tail=$fgetc(fd);$fclose(fd);check(count==RAW_BYTES && tail==-1,"RAW_INPUT_LENGTH");
    fd=$fopen({input_root,"/gamma_i24_le.bin"},"rb");check(fd!=0,"MISSING_GAIN_INPUT");
    count=$fread(gamma_memory,fd);tail=$fgetc(fd);$fclose(fd);check(count==GAMMA_BYTES && tail==-1,"GAIN_INPUT_LENGTH");
    fd=$fopen({input_root,"/row_metadata_le.bin"},"rb");check(fd!=0,"MISSING_METADATA_INPUT");
    count=$fread(metadata_memory,fd);tail=$fgetc(fd);$fclose(fd);check(count==META_BYTES && tail==-1,"METADATA_INPUT_LENGTH");
    data_loaded=1;input_layout_frozen=1;
  endtask
  function automatic logic [63:0] input_word(input logic [63:0] address);
    logic [63:0] result;
    int offset;
    result=0;
    if(address>=RAW_BASE && address+7<RAW_BASE+RAW_BYTES)begin
      offset=int'(address-RAW_BASE);
      for(int b=0;b<8;b++)result[8*b+:8]=raw_memory[offset+b];
    end else if(address>=GAMMA_BASE && address+7<GAMMA_BASE+GAMMA_BYTES)begin
      offset=int'(address-GAMMA_BASE);
      for(int b=0;b<8;b++)result[8*b+:8]=gamma_memory[offset+b];
    end else if(address>=META_BASE && address+7<META_BASE+META_BYTES)begin
      offset=int'(address-META_BASE);
      for(int b=0;b<8;b++)result[8*b+:8]=metadata_memory[offset+b];
    end else $fatal(1,"FRAME_SOURCE_UNMAPPED_READ address=%016h",address);
    return result;
  endfunction
  task automatic check_request(input logic [63:0] address,input logic [4:0] length);
    if(address>=META_BASE && address+15<META_BASE+META_BYTES)
      check(length==2 && (address-META_BASE)%16==0,"METADATA_BURST_GEOMETRY");
    else if(address>=GAMMA_BASE && address+23<GAMMA_BASE+GAMMA_BYTES)
      check(length==3 && (address-GAMMA_BASE)%24==0,"GAMMA_BURST_GEOMETRY");
    else if(address>=RAW_BASE+40960 && address+31<RAW_BASE+RAW_BYTES)
      check(length==4 && (address-RAW_BASE-40960)%32==0,"RAW_BURST_GEOMETRY");
    else $fatal(1,"FRAME_SOURCE_WRONG_READ_ADDRESS address=%016h length=%0d",address,length);
  endtask


  // Delayed, fair, one-outstanding 64-bit response provider. Only declared
  // immutable input regions are readable; every request is observed directly.
  always @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      read_busy<=0;read_address<=0;read_length<=0;read_beat<=0;read_delay<=0;
      read_rsp_valid<=0;read_rsp_last<=0;read_rsp_error<=0;read_rsp_data<=0;
    end else begin
      if(read_req_valid && read_req_ready)begin
        check(!read_busy && !read_rsp_valid,"OVERLAPPED_INPUT_READ");check_request(read_req_address,read_req_length);
        read_busy<=1;read_address<=read_req_address;read_length<=read_req_length;read_beat<=0;read_delay<=int'(tick%3)+1;
        read_requests<=read_requests+1;
      end
      if(read_busy && !read_rsp_valid)begin
        if(read_delay>0)read_delay<=read_delay-1;
        else begin read_rsp_valid<=1;read_rsp_data<=input_word(read_address+64'(read_beat)*8);read_rsp_last<=read_beat==int'(read_length)-1;read_rsp_error<=0;end
      end
      if(read_rsp_valid && read_rsp_ready)begin
        read_rsp_valid<=0;read_responses<=read_responses+1;
        if(read_rsp_last)read_busy<=0;else begin read_beat<=read_beat+1;read_delay<=int'(tick%3);end
      end
    end
  end
  // Actual write mux plus eight low-first accepted beats and genuine ACK.
  // No expected activation/line data is supplied to this transport.
  always @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      transport_busy<=0;response_due<=0;mem_rsp_valid<=0;mem_rsp_error<=0;
      transport_beat<=0;response_delay<=0;accepted_vector<=0;accepted_write_address<=0;
    end else begin
      if(vector_req_valid && vector_req_ready)accepted_vector<=vector_req_data;
      if(mem_req_valid && mem_req_ready)begin
        check(!transport_busy && !response_due && !mem_rsp_valid && mem_req_length==8 && mem_req_address[5:0]==0 &&
          mem_req_address>=cfg_compact_output_base && mem_req_address<=cfg_compact_output_base+1179584,"EXTERNAL_WRITE_GEOMETRY");
        transport_busy<=1;transport_beat<=0;accepted_write_address<=mem_req_address;
      end
      if(mem_data_valid && mem_data_ready)begin
        check(transport_busy && mem_strobe==8'hff && mem_data_last==(transport_beat==7) &&
          mem_data===accepted_vector[transport_beat*64+:64],"REAL_MUX_SERIALIZATION");
        serialized_beats<=serialized_beats+1;
        if(mem_data_last)begin transport_busy<=0;response_due<=1;response_delay<=3;vector_lines<=vector_lines+1;end
        else transport_beat<=transport_beat+1;
      end
      if(response_due && !hold_write_response)begin
        if(response_delay>0)response_delay<=response_delay-1;
        else begin mem_rsp_valid<=1;mem_rsp_error<=0;response_due<=0;end
      end
      if(mem_rsp_valid && mem_rsp_ready)begin mem_rsp_valid<=0;vector_acks<=vector_acks+1;end
    end
  end
  always @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      store_pending<=0;store_pending_write<=0;store_pending_word<=0;store_pending_data<=0;
      previous_read_hold<=0;previous_vector_hold<=0;previous_done_hold<=0;
      previous_read_packet<=0;previous_vector_packet<=0;previous_done_packet<=0;
    end else begin
      if(previous_read_hold)check(read_req_valid && {read_req_address,read_req_length}===previous_read_packet,"WITHDRAWN_INPUT_OFFER");
      if(previous_vector_hold)check(vector_req_valid && {vector_req_address,vector_req_data}===previous_vector_packet,"WITHDRAWN_EXTERNAL_OFFER");
      if(previous_done_hold)check(done_valid && {done_error,done_tag_base,done_layer,done_epoch,done_input_count,done_kept_count}===previous_done_packet,"CHANGED_PUBLIC_COMPLETION");
      previous_read_hold<=read_req_valid && !read_req_ready;previous_read_packet<={read_req_address,read_req_length};
      previous_vector_hold<=vector_req_valid && !vector_req_ready;previous_vector_packet<={vector_req_address,vector_req_data};
      previous_done_hold<=done_valid && !done_ready;previous_done_packet<={done_error,done_tag_base,done_layer,done_epoch,done_input_count,done_kept_count};
      if(store_context_owned)check(frame_protect,"UNPROTECTED_PHYSICAL_CONTEXT");
      if(cfg_valid || dut.frame_active)check(frame_protect,"OFFERED_FRAME_NOT_PROTECTED");
      if(store_acquire_valid && store_acquire_ready)acquisitions<=acquisitions+1;
      if(store_release_valid && store_release_ready)begin check(!store_pending && !store_rsp_valid && !transport_busy && !response_due && !mem_rsp_valid,"RELEASE_BEFORE_REAL_DRAIN");releases<=releases+1;end
      if(dut.source.row.cfg_valid && dut.source.row.cfg_ready)bcfgs<=bcfgs+1;
      if(dut.source.row.done_valid && dut.source.row.done_ready)bdones<=bdones+1;
      if(dut.source.out_valid && dut.source.out_ready)normalized_words<=normalized_words+1;
      if(raw_merge_response.map_valid && raw_merge_request.map_ready)begin
        check(maps<576 && raw_merge_response.map_index==10'(maps) && raw_merge_response.map_last==(maps==575),"ACTUAL_MAP_ORDER");
        actual_self_root[maps]=raw_merge_response.map_origin==raw_merge_response.map_index;
        if(raw_merge_response.map_origin==raw_merge_response.map_index)self_roots<=self_roots+1;
        maps<=maps+1;
      end
      if(raw_merge_request.sign_valid && raw_merge_response.sign_ready)signs<=signs+1;
      if(dut.compactor.image_done_valid && dut.compactor.image_done_ready)child_done_acks<=child_done_acks+1;
      if(done_valid && done_ready)parent_done_acks<=parent_done_acks+1;
      if(store_req_valid && store_req_ready)begin
        check(!store_pending,"STORE_REQUEST_OVERLAP");store_pending<=1;store_pending_write<=store_req_write;store_pending_word<=store_req_word;store_pending_data<=store_req_data;
      end
      if(store_rsp_valid && store_rsp_ready)begin
        check(store_pending && !store_rsp_error,"STORE_RESPONSE_ASSOCIATION");store_pending<=0;
        if(store_pending_write && store_pending_word>=256)begin
          observed_descriptor[store_pending_word-256]=store_pending_data;descriptor_acks<=descriptor_acks+1;
        end
      end
    end
  end
  // One direct full PREUPDATE snapshot per rising edge, no stdout duplicate.
  always @(posedge clk)if(journal_enabled)begin
    if(edge_count>=16777216)$fatal(1,"FRAME_PARENT_JOURNAL_RECORD_LIMIT");

    journal_packet={clk,
      rst_n,
      abort_valid,
      cfg_valid,
      cfg_ready,
      cfg_new_image,
      cfg_minimum_matches,
      cfg_tag_base,
      cfg_layer,
      cfg_epoch,
      cfg_image_start,
      cfg_input_rows,
      cfg_raw_frame_base,
      cfg_raw_frame_bytes,
      cfg_metadata_base,
      cfg_metadata_bytes,
      cfg_gamma_base,
      cfg_gamma_bytes,
      cfg_compact_output_base,
      cfg_gamma_exponent,
      read_req_valid,
      read_req_ready,
      read_req_address,
      read_req_length,
      read_rsp_valid,
      read_rsp_last,
      read_rsp_error,
      read_rsp_ready,
      read_rsp_data,
      store_acquire_valid,
      store_release_valid,
      store_req_valid,
      store_req_write,
      store_rsp_ready,
      store_acquire_ready,
      store_release_ready,
      store_context_owned,
      store_req_ready,
      store_rsp_valid,
      store_rsp_error,
      store_req_word,
      store_req_data,
      store_rsp_data,
      next_req_valid,
      next_req_write,
      next_rsp_ready,
      next_release_valid,
      next_req_ready,
      next_rsp_valid,
      next_rsp_error,
      next_release_ready,
      next_req_word,
      next_req_data,
      next_rsp_data,
      vector_req_valid,
      vector_rsp_ready,
      vector_req_ready,
      vector_rsp_valid,
      vector_rsp_error,
      vector_req_address,
      vector_req_data,
      done_valid,
      done_error,
      epoch_fault,
      frame_protect,
      metadata_needs_rebuild,
      port_idle,
      idle,
      done_ready,
      metadata_rebuilt,
      done_tag_base,
      done_layer,
      done_epoch,
      done_input_count,
      done_kept_count,
      fabric_merge_request,
      fabric_merge_response,
      fabric_sign_data,
      fabric_size_request,
      fabric_size_response,
      fabric_size_out_origin,
      next_size_request,
      next_size_response,
      next_size_out_origin,
      dut.source.cfg_valid,
      dut.source.cfg_ready,
      dut.source.row_request_valid,
      dut.source.row_request_ready,
      dut.source.row_request_original_root,
      dut.source.row_request_input_rank,
      dut.source.row_request_tag,
      dut.source.row_request_layer,
      dut.source.row_request_epoch,
      dut.source.out_valid,
      dut.source.out_last,
      dut.source.out_error,
      dut.source.out_ready,
      dut.source.out_tag,
      dut.source.out_index,
      dut.source.out_count,
      dut.source.out_activation,
      dut.source.out_exponent,
      dut.source.out_outlier_mask,
      dut.source.out_outlier_negative,
      dut.source.out_normalized_negative,
      dut.source.retire_valid,
      dut.source.retire_ready,
      dut.source.row_source_error,
      dut.source.producer_idle,
      dut.source.port_idle,
      dut.source.idle,
      dut.source.accepted_rows,
      dut.source.completed_rows,
      dut.source.row.normalizer.rst_n,
      dut.source.row.normalizer.cfg_ready,
      dut.source.row.normalizer.out_valid,
      dut.source.row.normalizer.base.state,
      dut.source.row.normalizer.out_ready,
      dut.source.row.normalizer.out_error,
      dut.source.row.reader.rst_n,
      dut.source.row.reader.cfg_valid,
      dut.source.row.reader.cfg_ready,
      dut.source.row.reader.cfg_tag,
      dut.source.row.reader.cfg_strips,
      dut.source.row.reader.cfg_raw_base,
      dut.source.row.reader.cfg_gamma_base,
      dut.source.row.reader.abort_valid,
      dut.source.row.reader.stats_valid,
      dut.source.row.reader.stats_ready,
      dut.source.row.reader.stats_last,
      dut.source.row.reader.stats_data,
      dut.source.row.reader.stats_gamma,
      dut.source.row.reader.replay_valid,
      dut.source.row.reader.replay_ready,
      dut.source.row.reader.replay_last,
      dut.source.row.reader.replay_data,
      dut.source.row.reader.replay_gamma,
      dut.source.row.reader.req_valid,
      dut.source.row.reader.req_ready,
      dut.source.row.reader.req_address,
      dut.source.row.reader.req_length,
      dut.source.row.reader.rsp_valid,
      dut.source.row.reader.rsp_ready,
      dut.source.row.reader.rsp_last,
      dut.source.row.reader.rsp_error,
      dut.source.row.reader.rsp_data,
      dut.source.row.reader.port_idle,
      dut.source.row.reader.idle,
      dut.source.row.reader.row_fault,
      dut.source.row.reader.done_valid,
      dut.source.row.reader.done_ready,
      dut.source.row.reader.done_error,
      dut.source.row.reader.done_tag,
      dut.source.row.reader.clear_valid,
      dut.source.row.reader.clear_ready,
      dut.source.state,
      dut.source.frame_active,
      dut.source.frame_fault,
      dut.source.metadata_offered,
      dut.source.metadata_owned,
      dut.source.metadata_beats,
      dut.source.metadata_packet,
      dut.source.row_active,
      dut.source.row_done_acknowledged,
      dut.source.row_root,
      dut.source.row_rank,
      dut.source.row_tag,
      dut.source.row_layer,
      dut.source.row_epoch,
      dut.source.row_raw_address,
      dut.source.metadata_address,
      dut.source.metadata_position,
      dut.source.saved_new_image,
      dut.source.saved_tag_base,
      dut.source.saved_layer,
      dut.source.saved_epoch,
      dut.source.saved_image_start,
      dut.source.saved_input_rows,
      dut.source.saved_raw_base,
      dut.source.saved_metadata_base,
      dut.source.saved_gamma_base,
      dut.source.saved_gamma_exponent,
      dut.source.unknown_response,
      dut.source.metadata_beat_fault,
      dut.source.metadata_validation_fault,
      dut.source.row_completion_fault,
      dut.source.immediate_fault,
      dut.source.row.cfg_valid,
      dut.source.row.cfg_ready,
      dut.source.row.cfg_tag,
      dut.source.row.cfg_strips,
      dut.source.row.cfg_raw_base,
      dut.source.row.cfg_gamma_base,
      dut.source.row.cfg_epsilon_q16,
      dut.source.row.cfg_gamma_exponent,
      dut.source.row.done_valid,
      dut.source.row.done_ready,
      dut.source.row.done_error,
      dut.source.row.done_tag,
      dut.source.row.state,
      dut.source.row.reader_success,
      dut.source.row.terminal_accepted,
      dut.source.row.fault_latched,
      dut.source.row.skid_valid,
      dut.source.row.idle,
      dut.source.row.port_idle,
      dut.source.row.row_fault,
      dut.source.row.abort_valid,
      dut.compactor.stage.start_valid,
      dut.compactor.stage.start_ready,
      dut.compactor.stage.start_tag,
      dut.compactor.stage.abort_valid,
      dut.compactor.stage.epoch_clear_valid,
      dut.compactor.stage.epoch_clear_ready,
      dut.compactor.stage.epoch_invalid,
      dut.compactor.stage.in_valid,
      dut.compactor.stage.in_ready,
      dut.compactor.stage.memory_acquire_valid,
      dut.compactor.stage.memory_acquire_ready,
      dut.compactor.stage.memory_context_owned,
      dut.compactor.stage.memory_release_valid,
      dut.compactor.stage.memory_release_ready,
      dut.compactor.stage.memory_req_valid,
      dut.compactor.stage.memory_req_ready,
      dut.compactor.stage.memory_req_write,
      dut.compactor.stage.memory_req_word,
      dut.compactor.stage.memory_req_data,
      dut.compactor.stage.memory_rsp_valid,
      dut.compactor.stage.memory_rsp_error,
      dut.compactor.stage.memory_rsp_ready,
      dut.compactor.stage.row_valid,
      dut.compactor.stage.row_ready,
      dut.compactor.stage.row_tag,
      dut.compactor.stage.row_exponent,
      dut.compactor.stage.row_consumed,
      dut.compactor.stage.release_valid,
      dut.compactor.stage.release_ready,
      dut.compactor.stage.consumer_idle,
      dut.compactor.stage.lease_held,
      dut.compactor.stage.accepted_words,
      dut.compactor.stage.acknowledged_words,
      dut.compactor.state,
      dut.compactor.memory_owner,
      dut.compactor.physical_lease,
      dut.compactor.row_grant,
      dut.compactor.row_authorized,
      dut.compactor.decision_pending,
      dut.compactor.terminal_received,
      dut.compactor.terminal_error,
      dut.compactor.fault_drain_complete,
      dut.compactor.map_cursor,
      dut.compactor.input_count,
      dut.compactor.kept_count,
      dut.compactor.row_root,
      dut.compactor.read_word,
      dut.compactor.line_acknowledgements,
      dut.compactor.vector_offered,
      dut.compactor.vector_pending,
      dut.compactor.aggregate_idle,
      dut.compactor.virtual_release_ready,
      dut.compactor.virtual_context,
      dut.compactor.source_authorized,
      dut.compactor.cut_kind,
      dut.compactor.previous_cut_kind,
      dut.compactor.cut_sample,
      dut.compactor.cut_same,
      dut.compactor.cfg_valid,
      dut.compactor.cfg_ready,
      dut.compactor.cfg_immutable_input_base,
      dut.compactor.cfg_immutable_input_bytes,
      dut.compactor.image_done_valid,
      dut.compactor.image_done_ready,
      dut.compactor.image_error,
      dut.compactor.abort_drained,
      dut.compactor.handoff_tag_base,
      dut.compactor.handoff_layer,
      dut.compactor.handoff_epoch,
      dut.compactor.handoff_input_count,
      dut.compactor.handoff_kept_count,
      dut.compactor.frame_port_granted,
      dut.compactor.epoch_invalid,
      dut.compactor.frame_protect,
      dut.compactor.merge_request,
      dut.compactor.merge_response,
      dut.compactor.size_request_observed,
      dut.compactor.size_response_observed,
      dut.physical_owner,
      dut.physical_acquired,
      dut.completion_seen,
      dut.store_response_pending,
      dut.frame_active,
      dut.frame_started,
      dut.epoch_fault_latched,
      dut.capture_first,
      dut.completion_join_bad,
      dut.completion_drain_bad,
      mem_req_valid,
      mem_req_ready,
      mem_req_address,
      mem_req_length,
      mem_data_valid,
      mem_data_ready,
      mem_data_last,
      mem_data,
      mem_strobe,
      mem_rsp_valid,
      mem_rsp_ready,
      mem_rsp_error,
      ff_idle,
      ff_ce_n,
      ff_we_n,
      ff_address,
      ff_write_data,
      memory.ce_n,
      memory.we_n,
      memory.address,
      memory.write_data,
      merge_fabric.relay.state,
      merge_fabric.relay.active_bank,
      merge_fabric.sign_control[2:0],
      merge_fabric.table_request[21],
      merge_fabric.size_command[0].walking,
      merge_fabric.size_command[0].table_request[18],
      merge_fabric.size_command[1].walking,
      merge_fabric.size_command[1].table_request[18],
      merge_fabric.size_command[2].walking,
      merge_fabric.size_command[2].table_request[18],
      merge_fabric.size_command[3].walking,
      merge_fabric.size_command[3].table_request[18],
      merge_fabric.size_command[4].walking,
      merge_fabric.size_command[4].table_request[18],
      read_busy,
      read_address,
      read_length,
      3'(read_beat),
      4'(read_delay),
      hold_read_request,
      hold_write_request,
      hold_write_response,
      transport_busy,
      response_due,
      4'(transport_beat),
      input_layout_frozen,
      2'(input_layout_generation)};
    if($isunknown(journal_packet))$fatal(1,"FRAME_PARENT_UNKNOWN_JOURNAL edge=%0d",edge_count);
    $fdisplay(journal_fd,"FPC_C episode=%0d edge=%0d data=%01853h",episode_id,edge_count,journal_packet);edge_count++;
  end

  task automatic clear_counts;
    check(!store_pending && !read_busy && !read_rsp_valid && !transport_busy && !response_due && !mem_rsp_valid,"CLEAR_WITH_PENDING_TRAFFIC");
    read_requests=0;read_responses=0;normalized_words=0;bcfgs=0;bdones=0;
    maps=0;signs=0;self_roots=0;descriptor_acks=0;vector_lines=0;vector_acks=0;serialized_beats=0;
    acquisitions=0;releases=0;child_done_acks=0;parent_done_acks=0;
    for(int n=0;n<576;n++)begin actual_self_root[n]=0;observed_descriptor[n]=0;end
  endtask
  task automatic clean_edges;
    repeat(2)begin @(posedge clk);@(negedge clk);end
  endtask
  task automatic reset_inputs;
    cfg_valid=0;abort_valid=0;done_ready=0;metadata_rebuilt=0;
    next_req_valid=0;next_req_write=0;next_req_word=0;next_req_data=0;
    next_rsp_ready=0;next_release_valid=0;next_size='0;
    hold_read_request=0;hold_write_request=0;hold_write_response=0;
    ff_idle=1;ff_ce_n=3;ff_we_n=3;ff_address=0;ff_write_data=0;
  endtask
  task automatic fresh_config;
    cfg_new_image=1;cfg_minimum_matches=1536;cfg_tag_base=32'h60000000;cfg_layer=0;cfg_epoch=1;
    cfg_image_start=5;cfg_input_rows=576;cfg_raw_frame_base=RAW_BASE;cfg_raw_frame_bytes=RAW_BYTES;
    cfg_metadata_base=META_BASE;cfg_metadata_bytes=META_BYTES;
    cfg_gamma_base=GAMMA_BASE;cfg_gamma_bytes=GAMMA_BYTES;cfg_gamma_exponent=-8'sd23;
    cfg_compact_output_base=64'h20000000;
  endtask
  task automatic begin_episode(input int number,input string kind,input bit reset_peers);
    if(edge_count==0)@(negedge clk);
    check(!journal_enabled,"OVERLAPPED_EPISODES");episode_id=number;
    if(reset_peers)begin
      rst_n=0;reset_inputs();fresh_config();load_inputs();input_layout_generation=0;
    end
    clear_counts();
    $fdisplay(journal_fd,"FPC_CASE_BEGIN episode=%0d kind=%s first_edge=%0d layout=%0d",episode_id,kind,edge_count,input_layout_generation);
    journal_enabled=1;
    if(reset_peers)begin repeat(4)@(negedge clk);rst_n=1;repeat(2)@(negedge clk);end
    check(idle && !store_context_owned && !dut.physical_acquired && metadata_needs_rebuild && !metadata_rebuilt,"INITIAL_OWNER_NOT_QUIET");
  endtask
  task automatic end_episode(input string outcome);
    clean_edges();
    $fdisplay(journal_fd,"FPC_CASE_END episode=%0d outcome=%s next_edge=%0d reads=%0d responses=%0d normalized=%0d bcfg=%0d bdone=%0d maps=%0d signs=%0d self_roots=%0d descriptor_acks=%0d lines=%0d vector_acks=%0d beats=%0d acquisitions=%0d releases=%0d child_done_acks=%0d parent_done_acks=%0d",episode_id,outcome,edge_count,read_requests,read_responses,normalized_words,bcfgs,bdones,maps,signs,self_roots,descriptor_acks,vector_lines,vector_acks,serialized_beats,acquisitions,releases,child_done_acks,parent_done_acks);
    journal_enabled=0;
  endtask
  task automatic accept_frame;
    @(negedge clk);check(idle && port_idle && input_layout_frozen,"FRAME_START_NOT_QUIET");
    cfg_valid=1;
    // cfg_ready depends on the genuine offered frame-port grant. Do not wait
    // for it before offering cfg_valid and thereby create a startup cycle.
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;
  endtask
  task automatic actual_ff_clobber_owned_phase(input logic [1:0] target_owner);
    check((target_owner==2 || target_owner==3) && store_context_owned &&
      dut.physical_owner==target_owner && frame_protect,"FF_PHASE_CALL_WITHOUT_ACTUAL_OWNER");
    // Runs concurrently with the existing slot hold/read handshake. It never
    // edits NextOwner valid/ready and cannot postpone an already offered read.
    @(negedge clk);
    check(store_context_owned && dut.physical_owner==target_owner && frame_protect,"FF_PHASE_TARGET_LEFT_OWNER");
    ff_idle=0;ff_ce_n=2'b10;ff_we_n=2'b10;ff_address=18'(256);ff_write_data={64'b0,~observed_descriptor[0]};
    repeat(2)begin
      @(posedge clk);
      check(store_context_owned && dut.physical_owner==target_owner && frame_protect &&
        dut.physical_acquired,"FF_HELD_OR_NEXT_PROTECTION_GAP");
      if(!(store_req_valid && store_req_ready))check(memory.ce_n==3 && memory.we_n==3,"FF_HELD_OR_NEXT_ACTUAL_WRITE_NOT_MASKED");
      @(negedge clk);
    end
    ff_idle=1;ff_ce_n=3;ff_we_n=3;ff_write_data=0;
  endtask
  task automatic sampled_done_hold(output logic [73:0] packet);
    while(!done_valid)@(negedge clk);
    packet={done_error,done_tag_base,done_layer,done_epoch,done_input_count,done_kept_count};
    // A real speculative NextOwner read remains offered through backpressure.
    next_req_valid=1;next_req_write=0;next_req_word=256;next_req_data=0;next_rsp_ready=0;
    fork
      actual_ff_clobber_owned_phase(2'd2);
      begin
        repeat(4)begin
          @(posedge clk);
          check(done_valid && !done_ready && !done_error && !epoch_fault && store_context_owned && frame_protect &&
            dut.physical_acquired && dut.physical_owner==2'd2 && !next_req_ready && !next_rsp_valid &&
            {done_error,done_tag_base,done_layer,done_epoch,done_input_count,done_kept_count}===packet,"PUBLIC_HELD_COMPLETION_OR_OWNER_CHANGED");
          @(negedge clk);
        end
      end
    join
  endtask
  task automatic check_complete_numeric_traffic;
    check(!done_error && !epoch_fault && maps==576 && signs==int'(cfg_input_rows) &&
      read_requests==1025*int'(cfg_input_rows) && read_responses==3586*int'(cfg_input_rows) &&
      normalized_words==256*int'(cfg_input_rows) && bcfgs==int'(cfg_input_rows) && bdones==int'(cfg_input_rows) &&
      descriptor_acks==self_roots && vector_lines==32*self_roots && vector_acks==32*self_roots &&
      serialized_beats==256*self_roots && child_done_acks==1 && parent_done_acks==0 && acquisitions==1 && releases==0 &&
      done_tag_base==cfg_tag_base && done_layer==cfg_layer && done_epoch==cfg_epoch &&
      done_input_count==cfg_input_rows && done_kept_count==self_roots,"COMPLETE_AUTHENTIC_TRAFFIC_COUNTS");
  endtask
  task automatic complete_projection_read(input int rank,input bit already_offered);
    if(!already_offered)begin @(negedge clk);next_req_word=10'(256+rank);next_req_valid=1;next_req_write=0;end
    do @(posedge clk);while(!next_req_ready);
    check(dut.physical_owner==2'd3 && store_context_owned && frame_protect,"NEXT_REQUEST_WITHOUT_GENUINE_HANDOFF");
    @(negedge clk);next_req_valid=0;next_rsp_ready=1;
    do @(posedge clk);while(!next_rsp_valid);
    check(!next_rsp_error && next_rsp_data===observed_descriptor[rank] && store_context_owned && frame_protect,"ACTUAL_DESCRIPTOR_LOST_OR_CLOBBERED");
    @(negedge clk);next_rsp_ready=0;
  endtask
  task automatic query_actual_sizes;
    int values,total;
    values=0;total=0;
    @(negedge clk);next_size='0;next_size.query_valid=1;next_size.query_position=575;
    do @(posedge clk);while(!next_size_reply.query_ready);
    @(negedge clk);next_size.query_valid=0;
    while(!next_size_reply.out_valid)@(negedge clk);
    repeat(2)begin @(posedge clk);check(next_size_reply.out_valid && !next_size.out_ready,"SIZE_EMIT_TARGET_NOT_SAMPLED");@(negedge clk);end
    next_size.out_ready=1;
    do begin
      @(posedge clk);
      if(next_size_reply.out_valid)begin
        check(!next_size_reply.error && next_size_reply.out_count!=0 && next_size_out_origin<576,"SIZE_QUERY_OUTPUT_INVALID");
        values++;total+=int'(next_size_reply.out_count);
      end
    end while(!(next_size_reply.out_valid && next_size_reply.out_last));
    @(negedge clk);next_size.out_ready=0;
    check(values==self_roots && total==576,"SIZE_QUERY_MULTIPLICITY_COUNTS");clean_edges();
    check(raw_size_response.frame_ready && !raw_size_response.out_valid && !next_size.query_valid,"SIZE_QUERY_NOT_REAL_DRAINED");
  endtask
  task automatic actual_next_release;
    @(negedge clk);check(!store_pending && !store_rsp_valid && !next_req_valid &&
      !transport_busy && !response_due && !mem_rsp_valid && !vector_req_valid &&
      raw_size_response.frame_ready && !raw_size_response.out_valid,"NEXT_RELEASE_NOT_QUIET");
    next_release_valid=1;do @(posedge clk);while(!next_release_ready);
    check(store_release_valid && store_release_ready && store_context_owned && metadata_needs_rebuild,"RELEASE_NOT_ACTUAL_PHYSICAL_HANDSHAKE");
    @(negedge clk);next_release_valid=0;#1;
    check(!store_context_owned && !dut.physical_acquired && dut.physical_owner==0 && metadata_needs_rebuild && !metadata_rebuilt,"RELEASE_INVENTED_PREDICTOR_REBUILD");
    clean_edges();check(idle && port_idle,"POST_RELEASE_NOT_IDLE");
  endtask
  task automatic actual_ff_clobber_attempt;
    while(descriptor_acks<1)@(negedge clk);
    @(negedge clk);check(store_context_owned && dut.physical_owner==1 && frame_protect,"FF_CLOBBER_TARGET_NOT_OWNED");
    ff_idle=0;ff_ce_n=2'b10;ff_we_n=2'b10;ff_address=18'(256);ff_write_data={64'b0,~observed_descriptor[0]};
    repeat(4)begin
      @(posedge clk);check(store_context_owned && frame_protect && dut.physical_acquired,"INTERROW_PHYSICAL_PROTECTION_GAP");
      if(!(store_req_valid && store_req_ready))check(memory.ce_n==3 && memory.we_n==3,"ACTUAL_FF_WRITE_NOT_MASKED");
      @(negedge clk);
    end
    ff_idle=1;ff_ce_n=3;ff_we_n=3;ff_write_data=0;
  endtask
  task automatic finish_success;
    logic [73:0] held;
    sampled_done_hold(held);check_complete_numeric_traffic();
    done_ready=1;do @(posedge clk);while(!done_valid);
    check(!next_req_ready && !epoch_fault && dut.physical_owner==2,"PUBLIC_ACK_EARLY_NEXT_ADMISSION");
    @(negedge clk);done_ready=0;
    fork
      complete_projection_read(0,1);
      actual_ff_clobber_owned_phase(2'd3);
    join
    // Reread after the NextOwner FF attempt, so an old captured RAM Q cannot
    // stand in for physical preservation after the attempted write.
    complete_projection_read(0,0);
    for(int rank=1;rank<self_roots;rank++)complete_projection_read(rank,0);
    query_actual_sizes();actual_next_release();positive_frames++;
  endtask
  task automatic pack_actual_root_successor;
    int rank;
    logic [63:0] second_word;
    check(idle && !store_context_owned && !read_busy && !read_rsp_valid && maps==576 && self_roots==done_kept_count,"SUCCESSOR_BEFORE_ACTUAL_HANDOFF");
    input_layout_frozen=0;data_loaded=0;rank=0;
    // Observed self-roots arrive in increasing original-root order. Dense
    // destination rank<=original root, so forward copies cannot overwrite a
    // later source row. This is an input-layout transform, never a keep input.
    for(int original_root=0;original_root<576;original_root++)if(actual_self_root[original_root])begin
      check(rank<=original_root,"SUCCESSOR_COPY_ORDER");
      for(int byte_index=0;byte_index<8192;byte_index++)raw_memory[(5+rank)*8192+byte_index]=raw_memory[(5+original_root)*8192+byte_index];
      for(int byte_index=0;byte_index<16;byte_index++)metadata_memory[rank*16+byte_index]=metadata_memory[original_root*16+byte_index];
      second_word=input_word(META_BASE+64'(rank)*16+8);
      check(second_word[17:8]==10'(original_root) && second_word[37:28]==10'(5+original_root),"SUCCESSOR_ORIGINAL_IDENTITY");
      second_word[27:18]=10'(rank);second_word[42:38]=0;second_word[58:43]=2;
      for(int byte_index=0;byte_index<8;byte_index++)metadata_memory[rank*16+8+byte_index]=second_word[byte_index*8+:8];
      rank++;
    end
    check(rank==self_roots && rank>0,"SUCCESSOR_ACTUAL_ROOT_CENSUS");successor_rows=rank;
    cfg_new_image=0;cfg_input_rows=10'(rank);cfg_tag_base=32'h60010000;cfg_layer=0;cfg_epoch=2;
    input_layout_generation=1;data_loaded=1;input_layout_frozen=1;
  endtask
  task automatic finish_same_edge_fault;
    logic [73:0] held;
    int later_edges;
    sampled_done_hold(held);check_complete_numeric_traffic();
    // The very first fault and the public ACK share an edge. The already
    // offered NextOwner request must remain blocked and held until reset.
    abort_valid=1;done_ready=1;#1;
    check(done_valid && {done_error,done_tag_base,done_layer,done_epoch,done_input_count,done_kept_count}===held &&
      epoch_fault && !next_req_ready && !store_release_valid,"SAME_EDGE_FAULT_RETRACTED_SLOT_OR_ADMITTED_PROJECTION");
    @(posedge clk);check(done_valid && done_ready && epoch_fault && !next_req_ready,"ACK_FAULT_TARGET_NOT_SAMPLED");
    @(negedge clk);abort_valid=0;done_ready=0;
    later_edges=0;
    while(child_done_acks<2 && later_edges<32)begin
      @(posedge clk);check(!done_valid && !next_req_ready && !store_release_valid &&
        store_context_owned && frame_protect && epoch_fault &&
        {done_error,done_tag_base,done_layer,done_epoch,done_input_count,done_kept_count}===held,"LATE_CHILD_STATUS_REPUBLISHED_SLOT_OR_LOST_OWNER");
      @(negedge clk);later_edges++;
    end
    check(child_done_acks==2 && parent_done_acks==1 && dut.completion_seen && dut.physical_owner==2 && releases==0,"SECOND_CHILD_ERROR_NOT_DRAINED_ONCE");
    clean_edges();check(!cfg_ready && !next_release_ready && !done_valid && epoch_fault,"POSTCOMPLETION_FAULT_NOT_LOCKED");
  endtask
  task automatic pulse_abort;
    abort_valid=1;repeat(2)begin @(posedge clk);check(epoch_fault,"ABORT_NOT_IMMEDIATE");@(negedge clk);end
    abort_valid=0;
  endtask
  task automatic finish_error(input bit acquired);
    while(!done_valid)@(negedge clk);
    check(done_error && epoch_fault && acquisitions==int'(acquired) &&
      store_context_owned==acquired && dut.physical_acquired==acquired && releases==0,"ERROR_COMPLETION_INVENTED_OR_LOST_LEASE");
    repeat(4)begin @(posedge clk);check(done_valid && done_error && epoch_fault && !next_req_ready,"ERROR_SLOT_NOT_HELD");@(negedge clk);end
    done_ready=1;do @(posedge clk);while(!done_valid);
    @(negedge clk);done_ready=0;clean_edges();
    check(epoch_fault && !cfg_ready && !next_req_ready && !store_release_valid &&
      store_context_owned==acquired && !read_busy && !read_rsp_valid && !transport_busy && !response_due && !mem_rsp_valid,"ERROR_ACK_FALSE_DRAIN_OR_RECONFIGURATION");
  endtask
  initial begin : integrated_corpus
    int probe;
    next_size='0;
    if(!$value$plusargs("FRAME_PARENT_INPUT_ROOT=%s",input_root))$fatal(1,"FRAME_PARENT_INPUT_ROOT_REQUIRED");
    if(!$value$plusargs("FRAME_PARENT_JOURNAL=%s",journal_path))$fatal(1,"FRAME_PARENT_JOURNAL_REQUIRED");
    if(!$value$plusargs("FRAME_PARENT_CATALOG_SHA=%s",catalogue_sha) || catalogue_sha.len()!=64)$fatal(1,"FRAME_PARENT_CATALOG_SHA_REQUIRED");
    if(!$value$plusargs("FRAME_PARENT_INPUT_MANIFEST_SHA=%s",input_manifest_sha) ||
      input_manifest_sha!="8d0abf0909d5dcdba34cca9e5acf27df6f4343e809df5c39d4ca010dc11261e2")$fatal(1,"FRAME_PARENT_INPUT_MANIFEST_SHA_REQUIRED");
    probe=$fopen(journal_path,"rb");if(probe!=0)begin $fclose(probe);$fatal(1,"FRAME_PARENT_PRESERVE_OLD_JOURNAL");end
    journal_fd=$fopen(journal_path,"w");check(journal_fd!=0,"JOURNAL_OPEN");
    $fdisplay(journal_fd,"FPC_BEGIN schema=1 bits=%0d digits=%0d catalogue=%s input_manifest=%s",JOURNAL_BITS,JOURNAL_DIGITS,catalogue_sha,input_manifest_sha);
    begin_episode(0,"fresh576",1);check(vendor_cell_count==23 && (&vendor_cells_seen),"GENUINE_VENDOR_CENSUS");
    accept_frame();fork actual_ff_clobber_attempt();finish_success();join
    end_episode("fresh_complete_projected_actual_release");
    pack_actual_root_successor();begin_episode(1,"actual_root_successor_same_edge_completion_fault",0);
    accept_frame();finish_same_edge_fault();end_episode("successor_numeric_complete_same_edge_fault_locked");

    begin_episode(2,"abort_before_physical_acquire",1);ff_idle=0;accept_frame();
    while(!(store_acquire_valid && !store_acquire_ready))@(negedge clk);
    repeat(2)begin @(posedge clk);check(store_acquire_valid && !store_acquire_ready && !store_context_owned,"NO_ACQUIRE_TARGET_NOT_SAMPLED");@(negedge clk);end
    pulse_abort();ff_idle=1;finish_error(0);end_episode("error_without_invented_lease");

    begin_episode(3,"abort_held_metadata_offer",1);hold_read_request=1;accept_frame();
    while(!read_req_valid)@(negedge clk);
    repeat(2)begin @(posedge clk);check(read_req_valid && !read_req_ready && read_req_address==META_BASE && read_req_length==2 && store_context_owned,"HELD_METADATA_TARGET_NOT_SAMPLED");@(negedge clk);end
    pulse_abort();repeat(2)begin @(posedge clk);check(read_req_valid && !read_req_ready,"ABORT_WITHDREW_METADATA");@(negedge clk);end
    hold_read_request=0;finish_error(1);check(read_requests==1 && read_responses==2 && bcfgs==0,"ABORTED_METADATA_NOT_REAL_LAST_DRAINED");
    end_episode("held_metadata_real_last_drained_lease_retained");

    begin_episode(4,"abort_first_held_external_vector",1);hold_write_request=1;accept_frame();
    while(!vector_req_valid)@(negedge clk);
    repeat(2)begin @(posedge clk);check(vector_req_valid && !vector_req_ready && mem_req_valid && !mem_req_ready,"HELD_VECTOR_TARGET_NOT_SAMPLED");@(negedge clk);end
    pulse_abort();repeat(2)begin @(posedge clk);check(vector_req_valid && !vector_req_ready && mem_req_valid,"ABORT_WITHDREW_LOCKED_VECTOR");@(negedge clk);end
    hold_write_request=0;finish_error(1);
    check(vector_lines==1 && vector_acks==1 && serialized_beats==8 && descriptor_acks==0,"ABORTED_VECTOR_NOT_REAL_ACK_DRAINED");

    // Explicit whole-endpoint reset finally releases the fault-locked test
    // context. This is not a claimed physical release or predictor rebuild.
    @(negedge clk);rst_n=0;reset_inputs();
    repeat(4)@(negedge clk);rst_n=1;repeat(2)@(negedge clk);clean_edges();
    check(idle && port_idle && !store_context_owned && metadata_needs_rebuild,"FINAL_COUPLED_RESET_NOT_QUIET");
    end_episode("held_vector_real_ack_drained_then_explicit_coupled_reset");
    $fdisplay(journal_fd,"FPC_END episodes=5 records=%0d completed_projected_frames=%0d successor_rows=%0d final_coupled_reset=1 model_step=0 predictor_rebuild=0",edge_count,positive_frames,successor_rows);
    $fflush(journal_fd);$fclose(journal_fd);
    $display("FRAME_PARENT_DRAFT_BENCH_PASS episodes=5 predictor_rebuild=0 model_step=0 paper_matching=0");$finish;
  end
endmodule
