`timescale 1ns/1ps
// Connected PRE/POST test-first corpus. No second token merge in POST.
// Input-only raw/gain/metadata provider; no normalized fixture or supplied keep.
`ifndef POST_NEXT_C_DUT
`define POST_NEXT_C_DUT tri_oracle_pre_post_normalizer_frame_next_c_v1
`endif
module tri_oracle_normalized_image_compactor_tb;
  tri_oracle_next_c_types_v1::request_t next_c_request = '0;
  tri_oracle_next_c_types_v1::response_t next_c_response;
  int origin_case = -1;
  logic origin_lease_unknown = 0;
  logic actual_store_context_owned;
  // Negative case3 injects uncertainty only after a real acquired/ACKed lease.
  // The memory itself retains its real state. No healthy owner is supplied.
  import tri_oracle_merge_range_types::*;
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
  assign store_context_owned = origin_lease_unknown ? 1'bx : actual_store_context_owned;
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
  string input_root,post_input_root,journal_path,catalogue_sha,input_manifest_sha;
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

  localparam int POST_RAW_BYTES=5046272, FEATURE_BYTES=1179648;
  localparam logic [63:0] POST_RAW_BASE=64'h30000000,
      POST_META_BASE=64'h31000000,POST_GAMMA_BASE=64'h32000000,
      POST_FEATURE_BASE=64'h40000000;
  byte unsigned post_raw_memory[0:POST_RAW_BYTES-1],
      post_gamma_memory[0:GAMMA_BYTES-1],post_metadata_memory[0:META_BYTES-1];
  // Only actual accepted external write bytes populate these observation arrays.
  byte unsigned observed_code_bytes[0:1179647],observed_feature_bytes[0:FEATURE_BYTES-1];
  logic [9:0] post_root_by_rank[0:575];
  bit post_demand_seen[0:575];
  int post_source_cfgs=0,post_demands=0,post_normalized_words=0;
  int post_vector_acks=0,feature_acks=0,post_descriptor_acks=0;
  int accepted_write_length=0;
  bit accepted_write_vector=0;
  longint unsigned journal_bytes=0,journal_events=0;
  logic [511:0] source_cfg_packet,previous_source_cfg_packet=0;
  logic [144:0] source_out_packet,previous_source_out_packet=0;
  logic [319:0] post_done_packet,previous_post_done_packet=0;
  logic previous_source_cfg_hold=0,previous_source_out_hold=0,previous_post_done_hold=0;
  logic previous_mem_req_hold=0,previous_mem_data_hold=0,previous_read_rsp_hold=0;
  logic previous_feature_req_hold=0,previous_feature_data_hold=0;
  logic [68:0] previous_mem_req_packet=0,previous_feature_req_packet=0;
  logic [72:0] previous_mem_data_packet=0,previous_feature_data_packet=0;
  logic [65:0] previous_read_rsp_packet=0;
  logic post_cfg_valid = 0;
  logic post_cfg_ready;
  logic [31:0] post_cfg_tag_base = 32'h504f0000;
  logic [63:0] post_cfg_raw_frame_base = POST_RAW_BASE;
  logic [63:0] post_cfg_raw_frame_bytes = POST_RAW_BYTES;
  logic [63:0] post_cfg_metadata_base = POST_META_BASE;
  logic [63:0] post_cfg_metadata_bytes = META_BYTES;
  logic [63:0] post_cfg_gamma_base = POST_GAMMA_BASE;
  logic [63:0] post_cfg_gamma_bytes = GAMMA_BYTES;
  logic [63:0] post_cfg_feature_base = POST_FEATURE_BASE;
  logic [63:0] post_cfg_feature_bytes = FEATURE_BYTES;
  logic signed [7:0] post_cfg_gamma_exponent = -8'sd23;
  logic [127:0] post_cfg_bundle_id = 128'h4f53545f4c305f45504f43485f303031;
  logic post_done_valid;
  logic post_done_ready = 0;
  logic post_done_error;
  logic post_epoch_fault;
  logic post_active;
  logic [31:0] post_done_tag_base;
  logic [4:0] post_done_layer;
  logic [15:0] post_done_epoch;
  logic [9:0] post_done_count;
  logic [63:0] post_done_code_base;
  logic [63:0] post_done_feature_base;
  logic [127:0] post_done_bundle_id;
  logic feature_req_valid;
  logic feature_req_ready;
  logic [63:0] feature_req_address;
  logic [4:0] feature_req_length;
  logic feature_data_valid;
  logic feature_data_ready;
  logic feature_data_last;
  logic [63:0] feature_data;
  logic [7:0] feature_strobe;
  logic feature_rsp_valid;
  logic feature_rsp_ready;
  logic feature_rsp_error;
  // These are observations of accepted C outputs, never provider inputs or
  // a normalized software fixture. They check downstream packing/identity.
  byte unsigned expected_post_code[0:1179647],expected_post_feature[0:442367];
  integer post_row_strips[0:575],post_row_code_acks[0:575],post_row_feature_acks[0:575];
  logic signed [8:0] post_row_exponent[0:575];
  bit post_row_has_exponent[0:575],post_descriptor_seen[0:575];
  logic [63:0] actual_post_descriptor[0:575];
  bit pre_size_seen[0:575],post_size_seen[0:575];
  logic [9:0] pre_size_count[0:575];
  integer post_code_requests=0,post_feature_requests=0,post_descriptor_requests=0;
  integer post_retire_fires=0,post_done_acks=0;
  logic pre_completion_captured=0;
  logic [73:0] immutable_pre_completion=0;
  `POST_NEXT_C_DUT dut (
    .next_c_request, .next_c_response,
    .clk, .rst_n, .abort_valid, .cfg_valid, .cfg_ready, .cfg_new_image, .cfg_minimum_matches, .cfg_tag_base, .cfg_layer, .cfg_epoch, .cfg_image_start, .cfg_input_rows, .cfg_raw_frame_base, .cfg_raw_frame_bytes, .cfg_metadata_base, .cfg_metadata_bytes, .cfg_gamma_base, .cfg_gamma_bytes, .cfg_compact_output_base, .cfg_gamma_exponent, .read_req_valid, .read_req_ready, .read_req_address, .read_req_length, .read_rsp_valid, .read_rsp_last, .read_rsp_error, .read_rsp_ready, .read_rsp_data, .store_acquire_valid, .store_release_valid, .store_req_valid, .store_req_write, .store_rsp_ready, .store_acquire_ready, .store_release_ready, .store_context_owned, .store_req_ready, .store_rsp_valid, .store_rsp_error, .store_req_word, .store_req_data, .store_rsp_data, .next_req_valid, .next_req_write, .next_rsp_ready, .next_release_valid, .next_req_ready, .next_rsp_valid, .next_rsp_error, .next_release_ready, .next_req_word, .next_req_data, .next_rsp_data, .vector_req_valid, .vector_rsp_ready, .vector_req_ready, .vector_rsp_valid, .vector_rsp_error, .vector_req_address, .vector_req_data, .done_valid, .done_error, .epoch_fault, .frame_protect, .metadata_needs_rebuild, .port_idle, .idle, .done_ready, .metadata_rebuilt, .done_tag_base, .done_layer, .done_epoch, .done_input_count, .done_kept_count, .fabric_merge_request, .fabric_merge_response, .fabric_sign_data, .fabric_size_request, .fabric_size_response, .fabric_size_out_origin, .next_size_request, .next_size_response, .next_size_out_origin, .post_cfg_valid, .post_cfg_ready, .post_cfg_tag_base, .post_cfg_raw_frame_base, .post_cfg_raw_frame_bytes, .post_cfg_metadata_base, .post_cfg_metadata_bytes, .post_cfg_gamma_base, .post_cfg_gamma_bytes, .post_cfg_feature_base, .post_cfg_feature_bytes, .post_cfg_gamma_exponent, .post_cfg_bundle_id, .post_done_valid, .post_done_ready, .post_done_error, .post_epoch_fault, .post_active, .post_done_tag_base, .post_done_layer, .post_done_epoch, .post_done_count, .post_done_code_base, .post_done_feature_base, .post_done_bundle_id, .feature_req_valid, .feature_req_ready, .feature_req_address, .feature_req_length, .feature_data_valid, .feature_data_ready, .feature_data_last, .feature_data, .feature_strobe, .feature_rsp_valid, .feature_rsp_ready, .feature_rsp_error
  );
  tri_oracle_shared_metadata_store memory (
    .clk,.rst_n,.ff_idle,.acquire_valid(store_acquire_valid),.acquire_ready(store_acquire_ready),
    .release_valid(store_release_valid),.release_ready(store_release_ready),.context_owned(actual_store_context_owned),
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
    .clk,.rst_n,.scalar_req_valid(feature_req_valid),.scalar_req_ready(feature_req_ready),.scalar_req_address(feature_req_address),
    .scalar_req_length(feature_req_length),.scalar_data_valid(feature_data_valid),.scalar_data_ready(feature_data_ready),.scalar_data_last(feature_data_last),
    .scalar_data(feature_data),.scalar_strobe(feature_strobe),.scalar_rsp_valid(feature_rsp_valid),.scalar_rsp_ready(feature_rsp_ready),.scalar_rsp_error(feature_rsp_error),
    .vector_req_valid,.vector_req_ready,.vector_req_address,.vector_req_data,
    .vector_rsp_valid,.vector_rsp_ready,.vector_rsp_error,
    .mem_req_valid,.mem_req_ready,.mem_req_address,.mem_req_length,.mem_data_valid,.mem_data_ready,
    .mem_data_last,.mem_data,.mem_strobe,.mem_rsp_valid,.mem_rsp_ready,.mem_rsp_error
  );
  always #5 clk=~clk;
  always @(negedge clk)begin
    tick++;
    if(tick>=16777216)$fatal(1,"PHASE_CONNECTION_EDGE_WATCHDOG");
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
    fd=$fopen({post_input_root,"/raw_frame_i32_le.bin"},"rb");check(fd!=0,"MISSING_POST_RAW_INPUT");
    count=$fread(post_raw_memory,fd);tail=$fgetc(fd);$fclose(fd);check(count==POST_RAW_BYTES && tail==-1,"POST_RAW_INPUT_LENGTH");
    fd=$fopen({post_input_root,"/gamma_i24_le.bin"},"rb");check(fd!=0,"MISSING_POST_GAIN_INPUT");
    count=$fread(post_gamma_memory,fd);tail=$fgetc(fd);$fclose(fd);check(count==GAMMA_BYTES && tail==-1,"POST_GAIN_INPUT_LENGTH");
    fd=$fopen({post_input_root,"/row_metadata_le.bin"},"rb");check(fd!=0,"MISSING_POST_METADATA_INPUT");
    count=$fread(post_metadata_memory,fd);tail=$fgetc(fd);$fclose(fd);check(count==META_BYTES && tail==-1,"POST_METADATA_INPUT_LENGTH");
    data_loaded=1;input_layout_frozen=1;
  endtask

  // All lines are bounded before writing. This is one compact transfer journal,
  // not an all-cycle dump; every accepted C strip includes all three features.
  task automatic emit(input string line);
    check(journal_fd!=0 && line.len()<=1023,"JOURNAL_LINE_BOUND");
    check(journal_bytes+64'(line.len())+1<=64'd536870912,"JOURNAL_512MIB_CAP");
    check(journal_events<16777216,"JOURNAL_EVENT_CAP");
    $fdisplay(journal_fd,"%s",line);
    journal_bytes+=64'(line.len())+1;journal_events++;
  endtask

  function automatic logic [63:0] input_word(input logic [63:0] address);
    logic [63:0] result;
    logic [127:0] metadata;
    int offset,rank,root,within_row;
    result=0;metadata=0;offset=0;rank=0;root=0;within_row=0;
    if(address>=RAW_BASE && address+7<RAW_BASE+RAW_BYTES)begin
      offset=int'(address-RAW_BASE);
      for(int b=0;b<8;b++)result[8*b+:8]=raw_memory[offset+b];
    end else if(address>=GAMMA_BASE && address+7<GAMMA_BASE+GAMMA_BYTES)begin
      offset=int'(address-GAMMA_BASE);
      for(int b=0;b<8;b++)result[8*b+:8]=gamma_memory[offset+b];
    end else if(address>=META_BASE && address+7<META_BASE+META_BYTES)begin
      offset=int'(address-META_BASE);
      for(int b=0;b<8;b++)result[8*b+:8]=metadata_memory[offset+b];
    end else if(address>=POST_RAW_BASE+40960 && address+7<POST_RAW_BASE+POST_RAW_BYTES)begin
      offset=int'(address-POST_RAW_BASE);rank=offset/8192-5;within_row=offset%8192;
      if(rank<0 || rank>=self_roots || !post_demand_seen[rank])$fatal(1,"POST_RAW_WITHOUT_ACTUAL_DEMAND");
      root=int'(post_root_by_rank[rank]);
      for(int b=0;b<8;b++)result[8*b+:8]=post_raw_memory[(5+root)*8192+within_row+b];
    end else if(address>=POST_GAMMA_BASE && address+7<POST_GAMMA_BASE+GAMMA_BYTES)begin
      offset=int'(address-POST_GAMMA_BASE);
      for(int b=0;b<8;b++)result[8*b+:8]=post_gamma_memory[offset+b];
    end else if(address>=POST_META_BASE && address+7<POST_META_BASE+META_BYTES)begin
      offset=int'(address-POST_META_BASE);rank=offset/16;within_row=offset%16;
      if(rank>=self_roots || !post_demand_seen[rank] || (within_row!=0 && within_row!=8))$fatal(1,"POST_METADATA_WITHOUT_ACTUAL_DEMAND");
      root=int'(post_root_by_rank[rank]);
      for(int b=0;b<16;b++)metadata[8*b+:8]=post_metadata_memory[root*16+b];
      // Preserve actual epsilon/raw unit, changing only declared dense layout
      // identities from the actual root demand/retired descriptor, not gold.
      if(metadata[81:72]!=10'(root) || metadata[101:92]!=10'(5+root) ||
          metadata[106:102]!=0 || metadata[122:107]!=1 || metadata[127:123]!=0)
        $fatal(1,"POST_ORIGINAL_METADATA_IDENTITY");
      metadata[81:72]=10'(root);metadata[91:82]=10'(rank);
      metadata[101:92]=10'(5+root);metadata[106:102]=0;metadata[122:107]=1;
      result=within_row==0 ? metadata[63:0] : metadata[127:64];
    end else $fatal(1,"PHASE_CONNECTION_UNMAPPED_READ address=%016h",address);
    return result;
  endfunction
  task automatic check_request(input logic [63:0] address,input logic [4:0] length);
    if(address>=META_BASE && address+15<META_BASE+META_BYTES)
      check(length==2 && (address-META_BASE)%16==0,"METADATA_BURST_GEOMETRY");
    else if(address>=GAMMA_BASE && address+23<GAMMA_BASE+GAMMA_BYTES)
      check(length==3 && (address-GAMMA_BASE)%24==0,"GAMMA_BURST_GEOMETRY");
    else if(address>=RAW_BASE+40960 && address+31<RAW_BASE+RAW_BYTES)
      check(length==4 && (address-RAW_BASE-40960)%32==0,"RAW_BURST_GEOMETRY");
    else if(address>=POST_META_BASE && address+15<POST_META_BASE+META_BYTES)
      check(episode_id==1 && length==2 && (address-POST_META_BASE)%16==0,"POST_METADATA_BURST_GEOMETRY");
    else if(address>=POST_GAMMA_BASE && address+23<POST_GAMMA_BASE+GAMMA_BYTES)
      check(episode_id==1 && length==3 && (address-POST_GAMMA_BASE)%24==0,"POST_GAMMA_BURST_GEOMETRY");
    else if(address>=POST_RAW_BASE+40960 && address+31<POST_RAW_BASE+POST_RAW_BYTES)
      check(episode_id==1 && length==4 && (address-POST_RAW_BASE-40960)%32==0,"POST_RAW_BURST_GEOMETRY");
    else $fatal(1,"PHASE_CONNECTION_WRONG_READ_ADDRESS address=%016h length=%0d",address,length);
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

  // Real mux transport: request, accepted serialized data, then delayed ACK.
  // Scalar features and vector code lines share the same physical endpoint.
  always @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      transport_busy<=0;response_due<=0;mem_rsp_valid<=0;mem_rsp_error<=0;
      transport_beat<=0;response_delay<=0;accepted_vector<=0;accepted_write_address<=0;
      accepted_write_length<=0;accepted_write_vector<=0;
    end else begin
      if(vector_req_valid && vector_req_ready)accepted_vector<=vector_req_data;
      if(mem_req_valid && mem_req_ready)begin
        check(!transport_busy && !response_due && !mem_rsp_valid && mem_req_length>0,"EXTERNAL_WRITE_OVERLAP");
        check((vector_req_valid && vector_req_ready) ^ (feature_req_valid && feature_req_ready),"MUX_OWNER_NOT_UNIQUE");
        if(vector_req_valid && vector_req_ready)
          check(mem_req_length==8 && mem_req_address[5:0]==0 &&
            mem_req_address>=cfg_compact_output_base && mem_req_address<=cfg_compact_output_base+1179584,"CODE_WRITE_GEOMETRY");
        else check(episode_id==1 && mem_req_address[2:0]==0 &&
          mem_req_address>=POST_FEATURE_BASE &&
          {1'b0,mem_req_address}+65'(mem_req_length)*8<=65'(POST_FEATURE_BASE)+FEATURE_BYTES,"FEATURE_WRITE_GEOMETRY");
        transport_busy<=1;transport_beat<=0;accepted_write_address<=mem_req_address;
        accepted_write_length<=int'(mem_req_length);accepted_write_vector<=vector_req_valid && vector_req_ready;
      end
      if(mem_data_valid && mem_data_ready)begin
        check(transport_busy && mem_data_last==(transport_beat==accepted_write_length-1),"WRITE_LAST_OR_OWNERSHIP");
        if(accepted_write_vector)begin
          check(mem_strobe==8'hff && mem_data===accepted_vector[transport_beat*64+:64],"REAL_MUX_VECTOR_SERIALIZATION");
          for(int b=0;b<8;b++)observed_code_bytes[int'(accepted_write_address-cfg_compact_output_base)+transport_beat*8+b]=mem_data[8*b+:8];
        end else begin
          check(feature_data_valid && feature_data_ready &&
            {mem_data,mem_strobe,mem_data_last}==={feature_data,feature_strobe,feature_data_last},"REAL_MUX_FEATURE_SERIALIZATION");
          for(int b=0;b<8;b++)if(mem_strobe[b])observed_feature_bytes[int'(accepted_write_address-POST_FEATURE_BASE)+transport_beat*8+b]=mem_data[8*b+:8];
        end
        serialized_beats<=serialized_beats+1;
        if(mem_data_last)begin
          transport_busy<=0;response_due<=1;response_delay<=3;
          if(accepted_write_vector)vector_lines<=vector_lines+1;
        end else transport_beat<=transport_beat+1;
      end
      if(response_due && !hold_write_response)begin
        if(response_delay>0)response_delay<=response_delay-1;
        else begin mem_rsp_valid<=1;mem_rsp_error<=0;response_due<=0;end
      end
      if(mem_rsp_valid && mem_rsp_ready)begin
        mem_rsp_valid<=0;
        if(accepted_write_vector)begin
          vector_acks<=vector_acks+1;if(episode_id==1)post_vector_acks<=post_vector_acks+1;
        end else feature_acks<=feature_acks+1;
      end
    end
  end

  assign source_cfg_packet={dut.src_cfg_new_image,dut.src_cfg_tag_base,
    dut.src_cfg_layer,dut.src_cfg_epoch,dut.src_cfg_image_start,dut.src_cfg_input_rows,
    dut.src_cfg_raw_frame_base,dut.src_cfg_raw_frame_bytes,dut.src_cfg_metadata_base,
    dut.src_cfg_metadata_bytes,dut.src_cfg_gamma_base,dut.src_cfg_gamma_bytes,dut.src_cfg_gamma_exponent};
  assign source_out_packet={dut.src_out_error,dut.src_out_tag,dut.src_out_index,
    dut.src_out_count,dut.src_out_last,dut.src_out_activation,dut.src_out_exponent,
    dut.src_out_outlier_mask,dut.src_out_normalized_negative,dut.src_out_outlier_negative};
  assign post_done_packet={post_done_error,post_done_tag_base,post_done_layer,post_done_epoch,
    post_done_count,post_done_code_base,post_done_feature_base,post_done_bundle_id};
  always @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      store_pending<=0;store_pending_write<=0;store_pending_word<=0;store_pending_data<=0;
      previous_read_hold<=0;previous_vector_hold<=0;previous_done_hold<=0;
      previous_source_cfg_hold<=0;previous_source_out_hold<=0;previous_post_done_hold<=0;
      previous_mem_req_hold<=0;previous_mem_data_hold<=0;previous_read_rsp_hold<=0;
      previous_feature_req_hold<=0;previous_feature_data_hold<=0;
    end else begin
      if(previous_read_hold)check(read_req_valid && {read_req_address,read_req_length}===previous_read_packet,"WITHDRAWN_INPUT_OFFER");
      if(previous_vector_hold)check(vector_req_valid && {vector_req_address,vector_req_data}===previous_vector_packet,"WITHDRAWN_CODE_OFFER");
      if(previous_done_hold)check(done_valid && {done_error,done_tag_base,done_layer,done_epoch,done_input_count,done_kept_count}===previous_done_packet,"CHANGED_PRE_DONE");
      if(previous_source_cfg_hold)check(dut.src_cfg_valid && source_cfg_packet===previous_source_cfg_packet,"CHANGED_C_CONFIG");
      if(previous_source_out_hold)check(dut.src_out_valid && source_out_packet===previous_source_out_packet,"CHANGED_C_STRIP");
      if(previous_post_done_hold)check(post_done_valid && post_done_packet===previous_post_done_packet,"CHANGED_POST_DONE");
      if(previous_mem_req_hold)check(mem_req_valid && {mem_req_address,mem_req_length}===previous_mem_req_packet,"CHANGED_MUX_REQUEST");
      if(previous_mem_data_hold)check(mem_data_valid && {mem_data,mem_strobe,mem_data_last}===previous_mem_data_packet,"CHANGED_MUX_DATA");
      if(previous_read_rsp_hold)check(read_rsp_valid && {read_rsp_data,read_rsp_last,read_rsp_error}===previous_read_rsp_packet,"CHANGED_INPUT_RESPONSE");
      if(previous_feature_req_hold)check(feature_req_valid && {feature_req_address,feature_req_length}===previous_feature_req_packet,"CHANGED_FEATURE_REQUEST");
      if(previous_feature_data_hold)check(feature_data_valid && {feature_data,feature_strobe,feature_data_last}===previous_feature_data_packet,"CHANGED_FEATURE_DATA");
      previous_read_hold<=read_req_valid && !read_req_ready;previous_read_packet<={read_req_address,read_req_length};
      previous_vector_hold<=vector_req_valid && !vector_req_ready;previous_vector_packet<={vector_req_address,vector_req_data};
      previous_done_hold<=done_valid && !done_ready;previous_done_packet<={done_error,done_tag_base,done_layer,done_epoch,done_input_count,done_kept_count};
      previous_source_cfg_hold<=dut.src_cfg_valid && !dut.src_cfg_ready;previous_source_cfg_packet<=source_cfg_packet;
      previous_source_out_hold<=dut.src_out_valid && !dut.src_out_ready;previous_source_out_packet<=source_out_packet;
      previous_post_done_hold<=post_done_valid && !post_done_ready;previous_post_done_packet<=post_done_packet;
      previous_mem_req_hold<=mem_req_valid && !mem_req_ready;previous_mem_req_packet<={mem_req_address,mem_req_length};
      previous_mem_data_hold<=mem_data_valid && !mem_data_ready;previous_mem_data_packet<={mem_data,mem_strobe,mem_data_last};
      previous_read_rsp_hold<=read_rsp_valid && !read_rsp_ready;previous_read_rsp_packet<={read_rsp_data,read_rsp_last,read_rsp_error};
      previous_feature_req_hold<=feature_req_valid && !feature_req_ready;previous_feature_req_packet<={feature_req_address,feature_req_length};
      previous_feature_data_hold<=feature_data_valid && !feature_data_ready;previous_feature_data_packet<={feature_data,feature_strobe,feature_data_last};
      if(store_context_owned)check(frame_protect,"UNPROTECTED_PHYSICAL_CONTEXT");
      if(cfg_valid || dut.pre.frame_active)check(frame_protect,"FRAME_NOT_PROTECTED");
      if(store_acquire_valid && store_acquire_ready)acquisitions<=acquisitions+1;
      if(store_release_valid && store_release_ready)begin
        if(origin_case!=2)$fatal(1,"PHASE_CONNECTION_UNEXPECTED_LEASE_RELEASE");
        releases<=releases+1;
      end
      if(dut.source.row.cfg_valid && dut.source.row.cfg_ready)bcfgs<=bcfgs+1;
      if(dut.source.row.done_valid && dut.source.row.done_ready)bdones<=bdones+1;
      if(dut.src_out_valid && dut.src_out_ready)begin
        normalized_words<=normalized_words+1;
        if(episode_id==1)post_normalized_words<=post_normalized_words+1;
      end
      if(episode_id==1)begin
        check(!raw_merge_request.cfg_valid && !raw_merge_request.sign_valid && !raw_merge_response.map_valid &&
          !raw_size_request.frame_valid && !raw_size_request.map_valid,"POST_STARTED_SECOND_MERGE_OR_MAP_RESET");
        if(dut.src_cfg_valid && dut.src_cfg_ready)begin
          check(!dut.src_cfg_new_image && dut.src_cfg_input_rows==10'(self_roots) &&
            dut.src_cfg_tag_base==post_cfg_tag_base && dut.src_cfg_layer==0 && dut.src_cfg_epoch==1 &&
            dut.src_cfg_image_start==5 && dut.src_cfg_raw_frame_base==POST_RAW_BASE &&
            dut.src_cfg_raw_frame_bytes==POST_RAW_BYTES && dut.src_cfg_metadata_base==POST_META_BASE &&
            dut.src_cfg_metadata_bytes==META_BYTES && dut.src_cfg_gamma_base==POST_GAMMA_BASE &&
            dut.src_cfg_gamma_bytes==GAMMA_BYTES && dut.src_cfg_gamma_exponent==-8'sd23,"POST_C_CONFIG_IDENTITY");
          post_source_cfgs<=post_source_cfgs+1;
        end
        if(dut.src_row_request_valid && dut.src_row_request_ready)begin
          check(post_demands<self_roots && dut.src_row_request_input_rank==10'(post_demands) &&
            dut.src_row_request_original_root==observed_descriptor[post_demands][41:32] &&
            dut.src_row_request_tag==post_cfg_tag_base+32'(post_demands) &&
            dut.src_row_request_layer==0 && dut.src_row_request_epoch==1,"POST_DEMAND_NOT_ACTUAL_RETIRED_ROOT");
          post_root_by_rank[post_demands]=dut.src_row_request_original_root;
          post_demand_seen[post_demands]=1;post_demands<=post_demands+1;
        end
      end
      if(raw_merge_response.map_valid && raw_merge_request.map_ready)begin
        check(episode_id==0 && maps<576 && raw_merge_response.map_index==10'(maps) && raw_merge_response.map_last==(maps==575),"ACTUAL_MAP_ORDER");
        actual_self_root[maps]=raw_merge_response.map_origin==raw_merge_response.map_index;
        if(raw_merge_response.map_origin==raw_merge_response.map_index)self_roots<=self_roots+1;
        maps<=maps+1;
      end
      if(raw_merge_request.sign_valid && raw_merge_response.sign_ready)signs<=signs+1;
      if(dut.pre.compactor.image_done_valid && dut.pre.compactor.image_done_ready)child_done_acks<=child_done_acks+1;
      if(done_valid && done_ready)parent_done_acks<=parent_done_acks+1;
      if(store_req_valid && store_req_ready)begin
        check(!store_pending,"STORE_REQUEST_OVERLAP");
        store_pending<=1;store_pending_write<=store_req_write;store_pending_word<=store_req_word;store_pending_data<=store_req_data;
      end
      if(store_rsp_valid && store_rsp_ready)begin
        check(store_pending && !store_rsp_error,"STORE_RESPONSE_ASSOCIATION");store_pending<=0;
        if(store_pending_write && store_pending_word>=256)begin
          check(store_pending_word<832,"DESCRIPTOR_ADDRESS_RANGE");
          if(episode_id==0)begin
            check(store_pending_word==10'(256+descriptor_acks) && store_pending_data[63:61]==3'b010 &&
              store_pending_data[51:42]==10'(descriptor_acks) && store_pending_data[41:32]<576 &&
              store_pending_data[31:0]==cfg_tag_base+32'(store_pending_data[41:32]),"PRE_DESCRIPTOR_IDENTITY");
            observed_descriptor[store_pending_word-256]=store_pending_data;descriptor_acks<=descriptor_acks+1;
          end else post_descriptor_acks<=post_descriptor_acks+1;
        end
      end
    end
  end

  function automatic logic [63:0] expected_post_descriptor(input integer rank);
    return {3'b010,post_row_exponent[rank],10'(rank),post_root_by_rank[rank],
      (post_cfg_tag_base+32'(rank))};
  endfunction

  // Observe every real C strip and compare all downstream bytes against it.
  // This proves transport/packing, not numerical equivalence with FLOAT or an
  // independent integer oracle. No expected array is read by input_word().
  always @(posedge clk)begin : positive_POST_scoreboard
    integer rank,strip,offset,line;
    logic [32:0] tag_delta;
    if(rst_n && episode_id==1)begin
      check(store_context_owned && frame_protect && !epoch_fault && !post_epoch_fault &&
        dut.pre.physical_owner==3 && metadata_needs_rebuild && !metadata_rebuilt &&
        !store_release_valid && !next_release_valid,"POST_PHYSICAL_CONTEXT_NOT_RETAINED");
      check(pre_completion_captured && !done_valid &&
        {done_error,done_tag_base,done_layer,done_epoch,done_input_count,done_kept_count}===immutable_pre_completion,
        "PRE_COMPLETION_CHANGED_DURING_POST");
      if(dut.src_row_request_valid && dut.src_row_request_ready)begin
        rank=int'(dut.src_row_request_input_rank);
        check(rank<self_roots,"POST_DEMAND_OUTSIDE_ACTUAL_KEEP_COUNT");
        if(rank>0)check(post_row_strips[rank-1]==256 && post_row_code_acks[rank-1]==32 &&
          post_row_feature_acks[rank-1]==12 && post_descriptor_seen[rank-1] &&
          dut.src_completed_rows>=10'(rank),"NEXT_POST_DEMAND_BEFORE_REAL_PRIOR_ROW_COMPLETIONS");
      end
      if(dut.src_out_valid && dut.src_out_ready)begin
        tag_delta={1'b0,dut.src_out_tag}-{1'b0,post_cfg_tag_base};
        check(!tag_delta[32] && tag_delta<33'(self_roots) && !$isunknown(source_out_packet),"POST_STRIP_UNKNOWN_TAG_OR_DATA");
        rank=int'(tag_delta);strip=int'(dut.src_out_index);
        check(post_demand_seen[rank] && strip==post_row_strips[rank] && strip<256 &&
          dut.src_out_count==8 && dut.src_out_last==(strip==255) && !dut.src_out_error,"POST_STRIP_IDENTITY_OR_ORDER");
        if(!post_row_has_exponent[rank])begin
          check(strip==0,"POST_EXPONENT_NOT_FROM_FIRST_STRIP");
          post_row_exponent[rank]=dut.src_out_exponent;post_row_has_exponent[rank]=1;
        end else check(dut.src_out_exponent===post_row_exponent[rank],"POST_STRIP_EXPONENT_CHANGED");
        for(integer lane=0;lane<8;lane++)expected_post_code[rank*2048+strip*8+lane]=dut.src_out_activation[lane*8+:8];
        expected_post_feature[rank*768+strip*3]=dut.src_out_outlier_mask;
        expected_post_feature[rank*768+strip*3+1]=dut.src_out_normalized_negative;
        expected_post_feature[rank*768+strip*3+2]=dut.src_out_outlier_negative;
        post_row_strips[rank]++;
      end
      if(vector_req_valid && vector_req_ready)begin
        offset=int'(vector_req_address-cfg_compact_output_base);rank=offset/2048;line=(offset%2048)/64;
        check(post_code_requests<32*self_roots && vector_req_address==cfg_compact_output_base+64'(post_code_requests)*64 &&
          rank<self_roots && post_row_strips[rank]>=8*(line+1),"POST_CODE_LINE_ORDER_OR_EARLY_WRITE");
        for(integer b=0;b<64;b++)check(vector_req_data[b*8+:8]===expected_post_code[offset+b],"POST_VECTOR_DIFFERS_FROM_ACTUAL_C");
        post_code_requests++;
      end
      if(feature_req_valid && feature_req_ready)begin
        offset=int'(feature_req_address-POST_FEATURE_BASE);rank=offset/768;line=(offset%768)/64;
        check(post_feature_requests<12*self_roots && feature_req_address==POST_FEATURE_BASE+64'(post_feature_requests)*64 &&
          feature_req_length==8 && rank<self_roots && post_row_strips[rank]>=((line+1)*64+2)/3,
          "POST_FEATURE_LINE_ORDER_OR_EARLY_WRITE");
        post_feature_requests++;
      end
      if(mem_data_valid && mem_data_ready)begin
        if(accepted_write_vector)begin
          offset=int'(accepted_write_address-cfg_compact_output_base)+transport_beat*8;
          for(integer b=0;b<8;b++)check(mem_data[b*8+:8]===expected_post_code[offset+b],"POST_SERIAL_CODE_DIFFERS_FROM_C");
        end else begin
          offset=int'(accepted_write_address-POST_FEATURE_BASE)+transport_beat*8;
          check(mem_strobe==8'hff,"POST_FEATURE_STROBE_DROPPED_BYTE");
          for(integer b=0;b<8;b++)check(mem_data[b*8+:8]===expected_post_feature[offset+b],"POST_FEATURE_DIFFERS_FROM_ATOMIC_C_TUPLE");
        end
      end
      if(vector_rsp_valid && vector_rsp_ready)begin
        rank=int'((accepted_write_address-cfg_compact_output_base)/2048);
        check(!vector_rsp_error && rank<self_roots && post_row_code_acks[rank]<32,"POST_VECTOR_ACK_IDENTITY");
        post_row_code_acks[rank]++;
      end
      if(feature_rsp_valid && feature_rsp_ready)begin
        rank=int'((accepted_write_address-POST_FEATURE_BASE)/768);
        check(!feature_rsp_error && rank<self_roots && post_row_feature_acks[rank]<12,"POST_FEATURE_ACK_IDENTITY");
        post_row_feature_acks[rank]++;
      end
      if(store_req_valid && store_req_ready && store_req_write)begin
        check(store_req_word>=256 && store_req_word<10'(256+self_roots),"POST_OVERWROTE_NONDESCRIPTOR_METADATA");
        rank=int'(store_req_word)-256;
        check(rank==post_descriptor_requests && post_row_strips[rank]==256 && post_row_code_acks[rank]==32 &&
          post_row_has_exponent[rank] && store_req_data===expected_post_descriptor(rank),"POST_DESCRIPTOR_NOT_FROM_ACTUAL_C_OR_ACKS");
        post_descriptor_requests++;
      end
      if(store_rsp_valid && store_rsp_ready && store_pending_write)begin
        rank=int'(store_pending_word)-256;
        check(!store_rsp_error && rank>=0 && rank<self_roots && !post_descriptor_seen[rank] &&
          store_pending_data===expected_post_descriptor(rank),"POST_DESCRIPTOR_ACK_IDENTITY_OR_DUPLICATE");
        actual_post_descriptor[rank]=store_pending_data;post_descriptor_seen[rank]=1;
      end
      if(dut.src_retire_valid && dut.src_retire_ready)begin
        check(dut.src_accepted_rows==10'(self_roots) && dut.src_completed_rows==10'(self_roots),"POST_C_RETIRED_BEFORE_ALL_ROWS");
        post_retire_fires++;
      end
      if(post_done_valid && post_done_ready)post_done_acks++;
    end
  end

  // One producer controls journal order. Fields are sampled before nonblocking
  // updates at the actual accepted edge; no derived expected values are inputs.
  always @(posedge clk)if(journal_enabled && rst_n)begin
    edge_count++;
    if(cfg_valid && cfg_ready)emit($sformatf("PC_PRE_CFG %08h %08h %03h %03h %04h %02h %03h %016h",tick,cfg_tag_base,cfg_image_start,cfg_input_rows,cfg_epoch,cfg_layer,cfg_minimum_matches,cfg_compact_output_base));
    if(post_cfg_valid && post_cfg_ready)emit($sformatf("PC_POST_CFG %08h %08h %016h %016h %016h %016h %032h",tick,post_cfg_tag_base,post_cfg_raw_frame_base,post_cfg_metadata_base,post_cfg_gamma_base,post_cfg_feature_base,post_cfg_bundle_id));
    if(dut.src_cfg_valid && dut.src_cfg_ready)emit($sformatf("PC_C_CFG %08h %01h %b %08h %03h %03h %02h %04h %016h %016h %016h %02h",tick,episode_id,dut.src_cfg_new_image,dut.src_cfg_tag_base,dut.src_cfg_image_start,dut.src_cfg_input_rows,dut.src_cfg_layer,dut.src_cfg_epoch,dut.src_cfg_raw_frame_base,dut.src_cfg_metadata_base,dut.src_cfg_gamma_base,dut.src_cfg_gamma_exponent));
    if(dut.src_retire_valid && dut.src_retire_ready)emit($sformatf("PC_C_RETIRE %08h %01h %03h %03h",tick,episode_id,dut.src_accepted_rows,dut.src_completed_rows));
    if(dut.src_row_request_valid && dut.src_row_request_ready)emit($sformatf("PC_DEMAND %08h %01h %03h %03h %08h %02h %04h",tick,episode_id,dut.src_row_request_original_root,dut.src_row_request_input_rank,dut.src_row_request_tag,dut.src_row_request_layer,dut.src_row_request_epoch));
    if(read_req_valid && read_req_ready)emit($sformatf("PC_RQ %08h %016h %02h",tick,read_req_address,read_req_length));
    if(read_rsp_valid && read_rsp_ready)emit($sformatf("PC_RP %08h %016h %b %b",tick,read_rsp_data,read_rsp_last,read_rsp_error));
    if(dut.src_out_valid && dut.src_out_ready)emit($sformatf("PC_STRIP %08h %01h %08h %02h %01h %b %016h %03h %02h %02h %02h %b",tick,episode_id,dut.src_out_tag,dut.src_out_index,dut.src_out_count,dut.src_out_last,dut.src_out_activation,dut.src_out_exponent,dut.src_out_outlier_mask,dut.src_out_normalized_negative,dut.src_out_outlier_negative,dut.src_out_error));
    if(store_acquire_valid && store_acquire_ready)emit($sformatf("PC_ACQUIRE %08h",tick));
    if(store_req_valid && store_req_ready)emit($sformatf("PC_STORE_RQ %08h %b %03h %016h",tick,store_req_write,store_req_word,store_req_data));
    if(store_rsp_valid && store_rsp_ready)emit($sformatf("PC_STORE_RP %08h %b %016h",tick,store_rsp_error,store_rsp_data));
    if(raw_merge_request.sign_valid && raw_merge_response.sign_ready)emit($sformatf("PC_MERGE_SIGN %08h %0512h",tick,fabric_sign_data));
    if(raw_merge_response.map_valid && raw_merge_request.map_ready)emit($sformatf("PC_MAP %08h %03h %03h %b",tick,raw_merge_response.map_index,raw_merge_response.map_origin,raw_merge_response.map_last));
    if(vector_req_valid && vector_req_ready)emit($sformatf("PC_VECTOR %08h %01h %016h %0128h",tick,episode_id,vector_req_address,vector_req_data));
    if(vector_rsp_valid && vector_rsp_ready)emit($sformatf("PC_VECTOR_ACK %08h %01h %b",tick,episode_id,vector_rsp_error));
    if(feature_req_valid && feature_req_ready)emit($sformatf("PC_FEATURE_RQ %08h %016h %02h",tick,feature_req_address,feature_req_length));
    if(feature_rsp_valid && feature_rsp_ready)emit($sformatf("PC_FEATURE_ACK %08h %b",tick,feature_rsp_error));
    if(mem_req_valid && mem_req_ready)emit($sformatf("PC_WRITE_RQ %08h %016h %02h",tick,mem_req_address,mem_req_length));
    if(mem_data_valid && mem_data_ready)emit($sformatf("PC_WRITE_DATA %08h %016h %02h %b",tick,mem_data,mem_strobe,mem_data_last));
    if(mem_rsp_valid && mem_rsp_ready)emit($sformatf("PC_WRITE_ACK %08h %b",tick,mem_rsp_error));
    if(next_req_valid && next_req_ready)emit($sformatf("PC_NEXT_RQ %08h %b %03h %016h",tick,next_req_write,next_req_word,next_req_data));
    if(next_rsp_valid && next_rsp_ready)emit($sformatf("PC_NEXT_RP %08h %b %016h",tick,next_rsp_error,next_rsp_data));
    if(next_size.query_valid && next_size_reply.query_ready)emit($sformatf("PC_SIZE_RQ %08h %03h",tick,next_size.query_position));
    if(next_size_reply.out_valid && next_size.out_ready)emit($sformatf("PC_SIZE_OUT %08h %03h %03h %b %b",tick,next_size_out_origin,next_size_reply.out_count,next_size_reply.out_last,next_size_reply.error));
    if(done_valid && done_ready)emit($sformatf("PC_PRE_DONE_ACK %08h %b %08h %02h %04h %03h %03h",tick,done_error,done_tag_base,done_layer,done_epoch,done_input_count,done_kept_count));
    if(post_done_valid && post_done_ready)emit($sformatf("PC_POST_DONE_ACK %08h %b %08h %02h %04h %03h %016h %016h %032h",tick,post_done_error,post_done_tag_base,post_done_layer,post_done_epoch,post_done_count,post_done_code_base,post_done_feature_base,post_done_bundle_id));
  end
  task automatic clean_edges;
    repeat(2)begin @(posedge clk);@(negedge clk);end
  endtask
  task automatic accept_frame;
    @(negedge clk);check(idle && port_idle && input_layout_frozen,"FRAME_START_NOT_QUIET");
    cfg_valid=1;
    // cfg_ready depends on the genuine offered frame-port grant. Do not wait
    // for it before offering cfg_valid and thereby create a startup cycle.
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;
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
    check(dut.pre.physical_owner==2'd3 && store_context_owned && frame_protect,"NEXT_REQUEST_WITHOUT_GENUINE_HANDOFF");
    @(negedge clk);next_req_valid=0;next_rsp_ready=1;
    do @(posedge clk);while(!next_rsp_valid);
    check(!next_rsp_error && next_rsp_data===observed_descriptor[rank] && store_context_owned && frame_protect,"ACTUAL_DESCRIPTOR_LOST_OR_CLOBBERED");
    @(negedge clk);next_rsp_ready=0;
  endtask
  task automatic query_actual_sizes;
    int values,total;
    values=0;total=0;
    if(episode_id==1)for(integer root=0;root<576;root++)post_size_seen[root]=0;
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
        if(episode_id==0)begin
          check(!pre_size_seen[next_size_out_origin],"DUPLICATE_PRE_SIZE_ORIGIN");
          pre_size_seen[next_size_out_origin]=1;pre_size_count[next_size_out_origin]=next_size_reply.out_count;
        end else begin
          check(pre_size_seen[next_size_out_origin] && !post_size_seen[next_size_out_origin] &&
            next_size_reply.out_count===pre_size_count[next_size_out_origin],"POST_CHANGED_RETAINED_TOKEN_SIZE_MAP");
          post_size_seen[next_size_out_origin]=1;
        end
        values++;total+=int'(next_size_reply.out_count);
      end
    end while(!(next_size_reply.out_valid && next_size_reply.out_last));
    @(negedge clk);next_size.out_ready=0;
    check(values==self_roots && total==576,"SIZE_QUERY_MULTIPLICITY_COUNTS");
    if(episode_id==1)for(integer root=0;root<576;root++)check(post_size_seen[root]==pre_size_seen[root],"POST_CHANGED_SIZE_ORIGIN_SET");
    clean_edges();
    check(raw_size_response.frame_ready && !raw_size_response.out_valid && !next_size.query_valid,"SIZE_QUERY_NOT_REAL_DRAINED");
  endtask

  task automatic complete_pre_handoff;
    logic [73:0] packet;
    while(!done_valid)@(negedge clk);
    packet={done_error,done_tag_base,done_layer,done_epoch,done_input_count,done_kept_count};
    repeat(4)begin
      @(posedge clk);
      check(done_valid && !done_ready && !done_error && !epoch_fault &&
        store_context_owned && frame_protect && dut.pre.physical_owner==2 &&
        {done_error,done_tag_base,done_layer,done_epoch,done_input_count,done_kept_count}===packet,"PRE_HELD_SUCCESS");
      @(negedge clk);
    end
    check_complete_numeric_traffic();
    immutable_pre_completion=packet;pre_completion_captured=1;
    done_ready=1;
    do @(posedge clk);while(!done_valid);
    check(!done_error && store_context_owned && frame_protect,"PRE_REAL_DONE_ACK");
    @(negedge clk);done_ready=0;clean_edges();
    check(parent_done_acks==1 && !done_valid && !epoch_fault &&
      dut.pre.physical_owner==3 && store_context_owned && frame_protect &&
      dut.src_idle && dut.src_port_idle && !dut.src_out_valid && !read_req_valid && !read_rsp_valid,"PRE_C_NOT_RETIRED_OR_OWNER_NOT_NEXT");
    // Every descriptor is read back through the genuine NextOwner endpoint.
    for(int rank=0;rank<self_roots;rank++)complete_projection_read(rank,0);
    query_actual_sizes();
    emit($sformatf("PC_PRE_COMPLETE edge=%0d roots=%0d maps=%0d strips=%0d descriptor_acks=%0d vector_acks=%0d reads=%0d responses=%0d vendor_cells=%0d owner_released=0",tick,self_roots,maps,normalized_words,descriptor_acks,vector_acks,read_requests,read_responses,vendor_cell_count));
    $display("PHASE_CONNECTION_PRE_COMPLETE roots=%0d maps=%0d strips=%0d descriptors=%0d owner=NextOwner",self_roots,maps,normalized_words,descriptor_acks);
  endtask


  task automatic check_complete_POST();
    check(post_source_cfgs==1 && post_demands==self_roots && post_normalized_words==256*self_roots &&
      post_code_requests==32*self_roots && post_vector_acks==32*self_roots &&
      post_feature_requests==12*self_roots && feature_acks==12*self_roots &&
      post_descriptor_requests==self_roots && post_descriptor_acks==self_roots && post_retire_fires==1 &&
      read_requests==1025*(576+self_roots) && read_responses==3586*(576+self_roots) &&
      bcfgs==576+self_roots && bdones==576+self_roots &&
      normalized_words==256*(576+self_roots) && vector_lines==64*self_roots && vector_acks==64*self_roots &&
      serialized_beats==608*self_roots && maps==576 && signs==576 &&
      acquisitions==1 && releases==0 && child_done_acks==1 && parent_done_acks==1,
      "INCOMPLETE_POSITIVE_POST_TRAFFIC");
    for(integer rank=0;rank<self_roots;rank++)begin
      check(post_demand_seen[rank] && post_row_has_exponent[rank] && post_row_strips[rank]==256 &&
        post_row_code_acks[rank]==32 && post_row_feature_acks[rank]==12 && post_descriptor_seen[rank] &&
        actual_post_descriptor[rank]===expected_post_descriptor(rank),"INCOMPLETE_POSITIVE_POST_ROW");
      for(integer b=0;b<2048;b++)check(observed_code_bytes[rank*2048+b]===expected_post_code[rank*2048+b],"POST_FINAL_CODE_READBACK_DIFFERS_FROM_C");
      for(integer b=0;b<768;b++)check(observed_feature_bytes[rank*768+b]===expected_post_feature[rank*768+b],"POST_FINAL_FEATURE_READBACK_DIFFERS_FROM_C");
    end
    check(dut.src_idle && dut.src_port_idle && !dut.src_out_valid && !read_busy && !read_rsp_valid &&
      !read_req_valid && !vector_req_valid && !vector_rsp_valid && !feature_req_valid && !feature_data_valid &&
      !feature_rsp_valid && !transport_busy && !response_due && !mem_rsp_valid && !store_pending && !store_rsp_valid,
      "POST_DONE_BEFORE_REAL_SOURCE_CONSUMER_DRAIN");
  endtask
  task automatic complete_positive_POST();
    logic [319:0] held;
    while(!post_done_valid)@(negedge clk);
    check(!post_done_error && !post_epoch_fault && post_done_tag_base==post_cfg_tag_base &&
      post_done_layer==0 && post_done_epoch==1 && post_done_count==10'(self_roots) &&
      post_done_code_base==cfg_compact_output_base && post_done_feature_base==POST_FEATURE_BASE &&
      post_done_bundle_id==post_cfg_bundle_id,"POST_DONE_CONTEXT_IDENTITY");
    check_complete_POST();held=post_done_packet;
    repeat(4)begin
      @(posedge clk);check(post_done_valid && !post_done_ready && post_done_packet===held &&
        store_context_owned && frame_protect && !post_epoch_fault && !epoch_fault,"POST_HELD_DONE_NOT_STABLE");
      @(negedge clk);
    end
    // Case1 offers the same configuration while real POST Done is held.
    if(origin_case==1)begin
      origin_make_configuration();
      origin_expect_denied(12,0);
      next_c_request='0;
    end
    post_done_ready=1;do @(posedge clk);while(!post_done_valid);
    @(negedge clk);post_done_ready=0;clean_edges();
    check(post_done_acks==1 && !post_done_valid && store_context_owned && frame_protect &&
      !epoch_fault && !post_epoch_fault && dut.pre.physical_owner==3,"POST_DONE_ACK_LOST_NEXT_OWNER");
    for(integer rank=0;rank<self_roots;rank++)begin
      @(negedge clk);next_req_valid=1;next_req_write=0;next_req_word=10'(256+rank);next_rsp_ready=0;
      do @(posedge clk);while(!next_req_ready);
      @(negedge clk);next_req_valid=0;next_rsp_ready=1;
      do @(posedge clk);while(!next_rsp_valid);
      check(!next_rsp_error && next_rsp_data===expected_post_descriptor(rank) &&
        next_rsp_data===actual_post_descriptor[rank] && store_context_owned && frame_protect,"POST_ACKNOWLEDGED_DESCRIPTOR_ACTUAL_READBACK");
      @(negedge clk);next_rsp_ready=0;
    end
    query_actual_sizes();check_complete_POST();
    check(!next_release_valid && !store_release_valid && releases==0 && metadata_needs_rebuild &&
      !metadata_rebuilt && !done_valid &&
      {done_error,done_tag_base,done_layer,done_epoch,done_input_count,done_kept_count}===immutable_pre_completion,
      "POST_CHANGED_PRE_STATUS_OR_FABRICATED_RELEASE_REBUILD");
  endtask

  task automatic origin_make_configuration;
    check(post_done_count==10'(self_roots) && self_roots==264,
      "ORIGIN_CONFIG_MUST_RETAIN_REAL_264_FRAME");
    next_c_request='0;
    next_c_request.selected=1;
    next_c_request.cfg_valid=1;
    next_c_request.cfg_new_image=0;
    next_c_request.cfg_tag_base=32'h4e430000;
    next_c_request.cfg_layer=post_done_layer+5'd1;
    next_c_request.cfg_epoch=post_done_epoch+16'd1;
    next_c_request.cfg_image_start=cfg_image_start;
    next_c_request.cfg_input_rows=post_done_count;
    // These are legal protected envelopes for CONFIGURATION-ONLY protocol use.
    // No demand is issued: the archived metadata is NOT asserted to be next-layer
    // residual data. The later FF consumer supplies its held committed envelope.
    next_c_request.cfg_raw_frame_base=post_cfg_raw_frame_base;
    next_c_request.cfg_raw_frame_bytes=post_cfg_raw_frame_bytes;
    next_c_request.cfg_metadata_base=post_cfg_metadata_base;
    next_c_request.cfg_metadata_bytes=post_cfg_metadata_bytes;
    next_c_request.cfg_gamma_base=post_cfg_gamma_base;
    next_c_request.cfg_gamma_bytes=post_cfg_gamma_bytes;
    next_c_request.cfg_gamma_exponent=post_cfg_gamma_exponent;
  endtask

  task automatic origin_expect_denied(input int cycles,input bit fault_required);
    repeat(cycles)begin
      @(posedge clk);
      check(next_c_response.cfg_ready===1'b0 && next_c_response.row_request_ready===1'b0 &&
        next_c_response.out_valid===1'b0 && next_c_response.retire_ready===1'b0 &&
        dut.src_cfg_valid===1'b0 && dut.src_row_request_valid===1'b0 &&
        dut.src_retire_valid===1'b0 && !read_req_valid && !read_rsp_valid,
        "ORIGIN_UNAUTHORIZED_C_ACCESS");
      @(negedge clk);#1ps;
    end
    if(fault_required)check(epoch_fault===1'b1 && post_epoch_fault===1'b1,
      "ORIGIN_UNKNOWN_LEASE_MUST_BE_KNOWN_STICKY_FAULT");
  endtask

  task automatic origin_probe;
    bit accepted;
    logic[544:0]held_request;
    if(origin_case==1)begin
      $display("POST_NEXT_C_EARLY_HANDOFF_DENIAL_PASS case=1 retained_count=%0d post_ack=%0d",self_roots,post_done_acks);
      return;
    end
    check(post_done_acks==1 && !post_done_valid && !cfg_valid &&
      store_context_owned===1'b1 && actual_store_context_owned===1'b1 &&
      dut.pre.physical_owner===2'd3 && !epoch_fault && !post_epoch_fault &&
      dut.src_idle && dut.src_producer_idle && dut.src_port_idle &&
      dut.src_accepted_rows==264 && dut.src_completed_rows==264 &&
      post_retire_fires==1 && releases==0 && !read_req_valid && !read_rsp_valid,
      "ORIGIN_REQUIRES_REAL_POST_HANDOFF_RETIRED_264_COUNTS");
    episode_id=2;
    if(origin_case==2)begin
      // Lose owner through the REAL public release handshake, not a forced bit.
      @(negedge clk);next_release_valid=1;
      accepted=0;
      repeat(64)begin
        @(posedge clk);if(next_release_ready===1'b1)begin accepted=1;break;end
        @(negedge clk);
      end
      check(accepted,"ORIGIN_REAL_RELEASE_TIMEOUT");
      @(negedge clk);next_release_valid=0;clean_edges();
      check(actual_store_context_owned===1'b0 && dut.pre.physical_owner===2'd0 && releases==1,
        "ORIGIN_NEGATIVE_DID_NOT_REALLY_RELEASE");
      origin_make_configuration();origin_expect_denied(12,0);
      $display("POST_NEXT_C_RELEASED_OWNER_DENIAL_PASS case=2 retained_count=%0d real_release=1",self_roots);
      return;
    end
    if(origin_case==3)begin
      @(negedge clk);origin_lease_unknown=1;
      origin_make_configuration();origin_expect_denied(12,1);
      check(actual_store_context_owned===1'b1 && store_context_owned===1'bx && frame_protect===1'b1,
        "ORIGIN_UNKNOWN_LEASE_PROXY_OR_PROTECTION");
      // Resolving uncertainty cannot silently undo the invalidation.
      origin_lease_unknown=0;origin_expect_denied(8,1);
      $display("POST_NEXT_C_UNKNOWN_LEASE_DENIAL_PASS case=3 retained_count=%0d sticky_fault=1",self_roots);
      return;
    end
    check(origin_case==0,"ORIGIN_CASE_UNSUPPORTED");
    @(negedge clk);origin_make_configuration();held_request=next_c_request;
    accepted=0;
    repeat(32)begin
      @(posedge clk);
      check(next_c_request===held_request && store_context_owned===1'b1 &&
        actual_store_context_owned===1'b1 && frame_protect===1'b1 && releases==0 &&
        !epoch_fault && !post_epoch_fault && cfg_ready===1'b0 && !cfg_valid,
        "ORIGIN_VALID_CONFIG_LOST_LEASE_OR_REUSED_PRE_CFG");
      if(next_c_response.cfg_ready===1'b1)begin
        check(dut.src_cfg_valid===1'b1 && dut.src_cfg_ready===1'b1 &&
          source_cfg_packet[465:0]===held_request[541:76],
          "ORIGIN_CONFIG_NOT_THE_SINGLE_REAL_C_HANDSHAKE");
        accepted=1;break;
      end
      check(next_c_response.cfg_ready===1'b0,"ORIGIN_UNKNOWN_CONFIG_READY");
      @(negedge clk);
    end
    if(!accepted)begin
      $display("POST_NEXT_C_ADMISSION_MISSING_WITNESS case=0 post_ack=%0d retained_count=%0d Caccepted=%0d Ccompleted=%0d owner=%0d lease=%b pre_cfg_valid=%b pre_cfg_ready=%b next_cfg_valid=%b next_cfg_ready=%b",post_done_acks,self_roots,dut.src_accepted_rows,dut.src_completed_rows,dut.pre.physical_owner,store_context_owned,cfg_valid,cfg_ready,next_c_request.cfg_valid,next_c_response.cfg_ready);
      $fatal(1,"POST_NEXT_C_VALID_POST_HANDOFF_CONFIGURATION_NOT_ACCEPTED");
    end
    @(negedge clk);next_c_request.cfg_valid=0;#1ps;
    check(dut.src_accepted_rows==0 && dut.src_completed_rows==0 &&
      !dut.src_idle && dut.src_producer_idle && dut.src_port_idle &&
      !read_req_valid && !read_rsp_valid && !next_c_response.out_valid &&
      store_context_owned===1'b1 && frame_protect===1'b1 && releases==0,
      "ORIGIN_CONFIG_MUST_RESET_REAL_COUNTS_WITHOUT_DEMAND_OR_RETIRE");
    $display("POST_NEXT_C_CONFIGURATION_PASS case=0 retained_count=%0d Caccepted=%0d Ccompleted=%0d owner_held=1 demand=0 retire=0",self_roots,dut.src_accepted_rows,dut.src_completed_rows);
  endtask

  initial begin : phase_connection
    int probe,post_wait;
    next_size='0;
    check($bits(next_c_request)==545 && $bits(next_c_response)==175,"ORIGIN_API_WIDTHS");
    if(!$value$plusargs("ORIGIN_CASE=%d",origin_case) || origin_case<0 || origin_case>3)
      $fatal(1,"ORIGIN_CASE_0_TO_3_REQUIRED");
    if(!$value$plusargs("PHASE_PRE_INPUT_ROOT=%s",input_root))$fatal(1,"PHASE_PRE_INPUT_ROOT_REQUIRED");
    if(!$value$plusargs("PHASE_POST_INPUT_ROOT=%s",post_input_root))$fatal(1,"PHASE_POST_INPUT_ROOT_REQUIRED");
    if(!$value$plusargs("PHASE_JOURNAL=%s",journal_path))$fatal(1,"PHASE_JOURNAL_REQUIRED");
    probe=$fopen(journal_path,"rb");if(probe!=0)begin $fclose(probe);$fatal(1,"PHASE_PRESERVE_OLD_JOURNAL");end
    journal_fd=$fopen(journal_path,"w");check(journal_fd!=0,"JOURNAL_OPEN");
    emit("PC_BEGIN schema=1 PRE_manifest=8d0abf0909d5dcdba34cca9e5acf27df6f4343e809df5c39d4ca010dc11261e2 POST_manifest=578f007d565801e59df91a113b76ddbc6512e4a37af9f34f89306b7feaaaa152 input_only=1 integer_attention_producer=0 paper_matching=0");
    for(int n=0;n<576;n++)begin
      actual_self_root[n]=0;observed_descriptor[n]=0;post_root_by_rank[n]=0;post_demand_seen[n]=0;
      post_row_strips[n]=0;post_row_code_acks[n]=0;post_row_feature_acks[n]=0;
      post_row_exponent[n]=0;post_row_has_exponent[n]=0;post_descriptor_seen[n]=0;actual_post_descriptor[n]=0;
      pre_size_seen[n]=0;post_size_seen[n]=0;pre_size_count[n]=0;
    end
    load_inputs();journal_enabled=1;
    repeat(4)@(negedge clk);rst_n=1;repeat(2)@(negedge clk);clean_edges();
    check(vendor_cell_count==23 && (&vendor_cells_seen),"GENUINE_23_VENDOR_CELLS");
    check(idle && port_idle && !store_context_owned,"INITIAL_NOT_QUIET");
    accept_frame();complete_pre_handoff();
    check(self_roots==264,"AUTHENTIC_PRE_FIXTURE_KEEP_CENSUS");
    @(negedge clk);episode_id=1;post_cfg_valid=1;
    do @(posedge clk);while(!post_cfg_ready);
    check(store_context_owned && frame_protect && !epoch_fault && !done_valid &&
      !read_busy && !read_rsp_valid && dut.src_idle && dut.src_port_idle,"POST_ADMISSION_BEFORE_PRE_RETIRE");
    @(negedge clk);post_cfg_valid=0;
    for(post_wait=0;post_wait<500;post_wait++)begin
      @(posedge clk);
      check(store_context_owned && frame_protect && !epoch_fault && !post_epoch_fault && releases==0,"POST_LOST_CONTEXT_OR_FAULT");
      @(negedge clk);
      if(post_source_cfgs!=0)break;
    end
    if(post_source_cfgs!=1)begin
      emit($sformatf("PC_EXPECTED_MISSING_POST_SOURCE_CONFIG edge=%0d cycles=%0d PREroots=%0d POSTcfgs=%0d POSTstrips=%0d owner=NextOwner",tick,post_wait,self_roots,post_source_cfgs,post_normalized_words));
      $fflush(journal_fd);
      $fatal(1,"PHASE_CONNECTION_EXPECTED_POST_SOURCE_CONFIG PREroots=%0d POSTcfgs=%0d POSTstrips=%0d after_cycles=%0d",self_roots,post_source_cfgs,post_normalized_words,post_wait);
    end
    complete_positive_POST();
    origin_probe();
    $fflush(journal_fd);$fclose(journal_fd);journal_fd=0;journal_enabled=0;
    $finish;
  end
endmodule
