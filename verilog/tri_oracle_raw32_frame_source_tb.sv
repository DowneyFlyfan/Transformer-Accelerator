`timescale 1ns/1ps
// Source-only coupled row-source corpus. Input bytes never serve as output gold.
// Fault overlays are confined to declared metadata responses or peer-reset cases.
module tri_oracle_frame_source_tb;
  localparam int RAW_BYTES=4759552, GAMMA_BYTES=6144, META_BYTES=9216;
  localparam logic [63:0] RAW_BASE=64'h10000000, GAMMA_BASE=64'h12000000, META_BASE=64'h11000000;
  localparam int JOURNAL_BITS=3167, JOURNAL_DIGITS=792;
  logic clk = 0;
  logic rst_n = 0;
  logic abort_valid = 0;
  logic cfg_valid = 0;
  logic cfg_ready;
  logic cfg_new_image = 1;
  logic [31:0] cfg_tag_base = 32'h60000000;
  logic [4:0] cfg_layer = 0;
  logic [15:0] cfg_epoch = 1;
  logic [9:0] cfg_image_start = 5;
  logic [9:0] cfg_input_rows = 576;
  logic [63:0] cfg_raw_frame_base = 64'h10000000;
  logic [63:0] cfg_raw_frame_bytes = 64'd4759552;
  logic [63:0] cfg_metadata_base = 64'h11000000;
  logic [63:0] cfg_metadata_bytes = 9216;
  logic [63:0] cfg_gamma_base = 64'h12000000;
  logic [63:0] cfg_gamma_bytes = 6144;
  logic signed [7:0] cfg_gamma_exponent = -8'sd23;
  logic row_request_valid = 0;
  logic row_request_ready;
  logic [9:0] row_request_original_root = 0;
  logic [9:0] row_request_input_rank = 0;
  logic [31:0] row_request_tag = 32'h60000000;
  logic [4:0] row_request_layer = 0;
  logic [15:0] row_request_epoch = 1;
  logic out_valid;
  logic out_last;
  logic out_error;
  logic out_ready;
  logic [31:0] out_tag;
  logic [9:0] out_index;
  logic [3:0] out_count;
  logic [63:0] out_activation;
  logic signed [8:0] out_exponent;
  logic [7:0] out_outlier_mask;
  logic [7:0] out_outlier_negative;
  logic [7:0] out_normalized_negative;
  logic read_req_valid;
  logic read_req_ready;
  logic [63:0] read_req_address;
  logic [4:0] read_req_length;
  logic read_rsp_valid;
  logic read_rsp_last;
  logic read_rsp_error;
  logic read_rsp_ready;
  logic [63:0] read_rsp_data;
  logic retire_valid = 0;
  logic retire_ready;
  logic row_source_error;
  logic producer_idle;
  logic port_idle;
  logic idle;
  logic [9:0] accepted_rows;
  logic [9:0] completed_rows;
  byte unsigned raw_memory[0:RAW_BYTES-1];
  byte unsigned gamma_memory[0:GAMMA_BYTES-1];
  byte unsigned metadata_memory[0:META_BYTES-1];
  string input_root,journal_path,catalogue_sha;
  int journal_fd=0;
  logic data_loaded=0,journal_enabled=0;
  longint unsigned tick=0,edge_count=0;
  int episode_id=0;
  logic hold_request=0,hold_output=0,hold_response=0,inject_ghost=0;
  logic [5:0] fault_mode=0;
  logic memory_is_metadata;
  logic ghost_issued;
  int coupled_resets=0;
  logic memory_busy;
  logic [63:0] memory_address;
  logic [4:0] memory_length;
  int memory_beat,memory_delay;
  int requests=0,responses=0,outputs=0,bcfg_count=0,bdone_count=0,statistics_words=0,replay_words=0;
  int bdone_errors=0;
  longint unsigned positive_requests=0,positive_responses=0,positive_outputs=0;
  int positive_rows=0;
  logic previous_request_stall,previous_response_stall,previous_output_stall;
  logic [68:0] previous_request_payload;
  logic [65:0] previous_response_payload;
  logic [144:0] previous_output_payload;
  logic [JOURNAL_BITS-1:0] journal_packet;

  tri_oracle_raw32_frame_source_v1 dut (
    .clk, .rst_n, .abort_valid, .cfg_valid, .cfg_ready, .cfg_new_image, .cfg_tag_base, .cfg_layer, .cfg_epoch, .cfg_image_start, .cfg_input_rows, .cfg_raw_frame_base, .cfg_raw_frame_bytes, .cfg_metadata_base, .cfg_metadata_bytes, .cfg_gamma_base, .cfg_gamma_bytes, .cfg_gamma_exponent, .row_request_valid, .row_request_ready, .row_request_original_root, .row_request_input_rank, .row_request_tag, .row_request_layer, .row_request_epoch, .out_valid, .out_last, .out_error, .out_ready, .out_tag, .out_index, .out_count, .out_activation, .out_exponent, .out_outlier_mask, .out_outlier_negative, .out_normalized_negative, .read_req_valid, .read_req_ready, .read_req_address, .read_req_length, .read_rsp_valid, .read_rsp_last, .read_rsp_error, .read_rsp_ready, .read_rsp_data, .retire_valid, .retire_ready, .row_source_error, .producer_idle, .port_idle, .idle, .accepted_rows, .completed_rows
  );
  always #5 clk=~clk;
  always @(negedge clk)begin
    tick++;
    if(tick>200000000)$fatal(1,"FRAME_SOURCE_WATCHDOG");
  end
  always_comb begin
    read_req_ready=rst_n && data_loaded && !memory_busy && !read_rsp_valid && !hold_request && tick%5!=1;
    out_ready=rst_n && !hold_output && tick%7!=2 && tick%7!=3;

  end

  task automatic check(input logic condition,input string reason);
    if(condition!==1'b1)$fatal(1,"FRAME_SOURCE_%s episode=%0d tick=%0d",reason,episode_id,tick);
  endtask
  task automatic load_inputs;
    int fd,count,tail;
    fd=$fopen({input_root,"/raw_frame_i32_le.bin"},"rb");check(fd!=0,"MISSING_RAW_INPUT");
    count=$fread(raw_memory,fd);tail=$fgetc(fd);$fclose(fd);check(count==RAW_BYTES && tail==-1,"RAW_INPUT_LENGTH");
    fd=$fopen({input_root,"/gamma_i24_le.bin"},"rb");check(fd!=0,"MISSING_GAIN_INPUT");
    count=$fread(gamma_memory,fd);tail=$fgetc(fd);$fclose(fd);check(count==GAMMA_BYTES && tail==-1,"GAIN_INPUT_LENGTH");
    fd=$fopen({input_root,"/row_metadata_le.bin"},"rb");check(fd!=0,"MISSING_METADATA_INPUT");
    count=$fread(metadata_memory,fd);tail=$fgetc(fd);$fclose(fd);check(count==META_BYTES && tail==-1,"METADATA_INPUT_LENGTH");
    data_loaded=1;
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

  // These overlays affect the peer's response, not the immutable input arrays.
  // Modes1..8 each isolate one metadata validation predicate. Mode8 carries
  // exponent -33 and epsilon0, isolating the supported-unit range check.
  function automatic logic [63:0] response_word(input logic [63:0] address,input int beat,input logic is_metadata);
    logic [63:0] value;
    value=input_word(address+64'(beat)*8);
    if(is_metadata)begin
      if(beat==1)case(fault_mode)
        1:value^=64'h0000000000000100; // root bit8
        2:value^=64'h0000000000040000; // rank bit18
        3:value^=64'h0000000010000000; // original position bit28
        4:value^=64'h0000004000000000; // layer bit38
        5:value^=64'h0000080000000000; // epoch bit43
        6:value|=64'h0800000000000000; // reserved bit59
        8:value={value[63:8],8'hdf};   // unsupported signed unit -33
        default:begin end
      endcase
      if(beat==0 && fault_mode==7)value^=64'd1;
      if(beat==0 && fault_mode==8)value=0;
    end
    return value;
  endfunction

  // Only input bytes are supplied; no output reference/model or keep/map data.
  // Offers are registered after accepted edges and remain stable until ready.
  // The provider and DUT share reset only in explicitly labelled reset cases.
  always @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      memory_busy<=0;memory_is_metadata<=0;memory_address<=0;memory_length<=0;memory_beat<=0;memory_delay<=0;
      ghost_issued<=0;
      read_rsp_valid<=0;read_rsp_last<=0;read_rsp_error<=0;read_rsp_data<=0;
    end else begin
      if(read_req_valid && read_req_ready)begin
        check(!memory_busy && !read_rsp_valid,"MORE_THAN_ONE_BURST");
        check_request(read_req_address,read_req_length);
        memory_busy<=1;memory_address<=read_req_address;memory_length<=read_req_length;
        memory_is_metadata<=read_req_address>=META_BASE && read_req_address<META_BASE+META_BYTES;
        memory_beat<=0;memory_delay<=int'(tick%3)+1;requests<=requests+1;
      end
      if(inject_ghost && !ghost_issued)begin
        check(!memory_busy && !read_rsp_valid,"GHOST_REQUIRES_NO_OWNED_BURST");
        ghost_issued<=1;read_rsp_valid<=1;read_rsp_last<=1;read_rsp_error<=0;
        read_rsp_data<=64'hbad0c0de01234567;
      end
      if(memory_busy && !read_rsp_valid && !hold_response)begin
        if(memory_delay>0)memory_delay<=memory_delay-1;
        else begin
          read_rsp_valid<=1;read_rsp_data<=response_word(memory_address,memory_beat,memory_is_metadata);
          if(memory_is_metadata && fault_mode==9)read_rsp_last<=1; // early LAST at beat0
          else if(memory_is_metadata && fault_mode==10)read_rsp_last<=memory_beat==2; // third real LAST
          else read_rsp_last<=memory_beat==int'(memory_length)-1;
          read_rsp_error<=memory_is_metadata && fault_mode==11 && memory_beat==0;
        end
      end
      if(read_rsp_valid && read_rsp_ready)begin
        check(memory_busy,"UNSOLICITED_RESPONSE_MUST_NOT_BE_ACCEPTED");
        read_rsp_valid<=0;responses<=responses+1;
        if(read_rsp_last)memory_busy<=0;
        else begin memory_beat<=memory_beat+1;memory_delay<=int'(tick%3);end
      end
    end
  end

  always @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      previous_request_stall<=0;previous_response_stall<=0;previous_output_stall<=0;
      previous_request_payload<=0;previous_response_payload<=0;previous_output_payload<=0;
    end else begin
      if(previous_request_stall)check(read_req_valid && {read_req_address,read_req_length}===previous_request_payload,"WITHDRAWN_REQUEST");
      if(previous_response_stall)check(read_rsp_valid && {read_rsp_last,read_rsp_error,read_rsp_data}===previous_response_payload,"CHANGED_PROVIDER_RESPONSE");
      if(previous_output_stall)check(out_valid && {out_last,out_error,out_tag,out_index,out_count,out_activation,out_exponent,out_outlier_mask,out_outlier_negative,out_normalized_negative}===previous_output_payload,"CHANGED_OUTPUT_SKID");
      previous_request_stall<=read_req_valid && !read_req_ready;
      previous_response_stall<=read_rsp_valid && !read_rsp_ready;
      previous_output_stall<=out_valid && !out_ready;
      previous_request_payload<={read_req_address,read_req_length};
      previous_response_payload<={read_rsp_last,read_rsp_error,read_rsp_data};
      previous_output_payload<={out_last,out_error,out_tag,out_index,out_count,out_activation,out_exponent,out_outlier_mask,out_outlier_negative,out_normalized_negative};
      if(dut.row.cfg_valid && dut.row.cfg_ready)bcfg_count<=bcfg_count+1;
      if(dut.row.done_valid && dut.row.done_ready)begin
        bdone_count<=bdone_count+1;
        if(dut.row.done_error)bdone_errors<=bdone_errors+1;
      end
      if(dut.row.reader.stats_valid && dut.row.reader.stats_ready)statistics_words<=statistics_words+1;
      if(dut.row.reader.replay_valid && dut.row.reader.replay_ready)replay_words<=replay_words+1;
      if(out_valid && out_ready)begin
        check(!out_error && out_tag==32'h60000000+32'(outputs/256) &&
          out_index==10'(outputs%256) && out_count==8 && out_last==(outputs%256==255),"OUTPUT_CONTROL_METADATA");
        outputs<=outputs+1;
      end
    end
  end

  // Every edge, including reset. Never print this journal to stdout/stderr.
  // Only B's registered public payload is included; unoffered core arithmetic
  // payload is deliberately absent rather than dumping X or masking valid data.
  always @(posedge clk)if(journal_enabled)begin
    if(edge_count>=16777216)$fatal(1,"FRAME_SOURCE_JOURNAL_RECORD_LIMIT");
    journal_packet={clk,
      rst_n,
      abort_valid,
      cfg_valid,
      cfg_ready,
      cfg_new_image,
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
      cfg_gamma_exponent,
      row_request_valid,
      row_request_ready,
      row_request_original_root,
      row_request_input_rank,
      row_request_tag,
      row_request_layer,
      row_request_epoch,
      out_valid,
      out_last,
      out_error,
      out_ready,
      out_tag,
      out_index,
      out_count,
      out_activation,
      out_exponent,
      out_outlier_mask,
      out_outlier_negative,
      out_normalized_negative,
      read_req_valid,
      read_req_ready,
      read_req_address,
      read_req_length,
      read_rsp_valid,
      read_rsp_last,
      read_rsp_error,
      read_rsp_ready,
      read_rsp_data,
      retire_valid,
      retire_ready,
      row_source_error,
      producer_idle,
      port_idle,
      idle,
      accepted_rows,
      completed_rows,
      dut.row.normalizer.rst_n,
      dut.row.normalizer.cfg_ready,
      dut.row.normalizer.out_valid,
      dut.row.normalizer.base.state,
      dut.row.normalizer.out_ready,
      dut.row.normalizer.out_error,
      dut.row.reader.rst_n,
      dut.row.reader.cfg_valid,
      dut.row.reader.cfg_ready,
      dut.row.reader.cfg_tag,
      dut.row.reader.cfg_strips,
      dut.row.reader.cfg_raw_base,
      dut.row.reader.cfg_gamma_base,
      dut.row.reader.abort_valid,
      dut.row.reader.stats_valid,
      dut.row.reader.stats_ready,
      dut.row.reader.stats_last,
      dut.row.reader.stats_data,
      dut.row.reader.stats_gamma,
      dut.row.reader.replay_valid,
      dut.row.reader.replay_ready,
      dut.row.reader.replay_last,
      dut.row.reader.replay_data,
      dut.row.reader.replay_gamma,
      dut.row.reader.req_valid,
      dut.row.reader.req_ready,
      dut.row.reader.req_address,
      dut.row.reader.req_length,
      dut.row.reader.rsp_valid,
      dut.row.reader.rsp_ready,
      dut.row.reader.rsp_last,
      dut.row.reader.rsp_error,
      dut.row.reader.rsp_data,
      dut.row.reader.port_idle,
      dut.row.reader.idle,
      dut.row.reader.row_fault,
      dut.row.reader.done_valid,
      dut.row.reader.done_ready,
      dut.row.reader.done_error,
      dut.row.reader.done_tag,
      dut.row.reader.clear_valid,
      dut.row.reader.clear_ready,
      dut.state,
      dut.frame_active,
      dut.frame_fault,
      dut.metadata_offered,
      dut.metadata_owned,
      dut.metadata_beats,
      dut.metadata_packet,
      dut.row_active,
      dut.row_done_acknowledged,
      dut.row_root,
      dut.row_rank,
      dut.row_tag,
      dut.row_layer,
      dut.row_epoch,
      dut.row_raw_address,
      dut.metadata_address,
      dut.metadata_position,
      dut.saved_new_image,
      dut.saved_tag_base,
      dut.saved_layer,
      dut.saved_epoch,
      dut.saved_image_start,
      dut.saved_input_rows,
      dut.saved_raw_base,
      dut.saved_metadata_base,
      dut.saved_gamma_base,
      dut.saved_gamma_exponent,
      dut.unknown_response,
      dut.metadata_beat_fault,
      dut.metadata_validation_fault,
      dut.row_completion_fault,
      dut.immediate_fault,
      dut.row.cfg_valid,
      dut.row.cfg_ready,
      dut.row.cfg_tag,
      dut.row.cfg_strips,
      dut.row.cfg_raw_base,
      dut.row.cfg_gamma_base,
      dut.row.cfg_epsilon_q16,
      dut.row.cfg_gamma_exponent,
      dut.row.done_valid,
      dut.row.done_ready,
      dut.row.done_error,
      dut.row.done_tag,
      dut.row.state,
      dut.row.reader_success,
      dut.row.terminal_accepted,
      dut.row.fault_latched,
      dut.row.skid_valid,
      dut.row.idle,
      dut.row.port_idle,
      dut.row.row_fault,
      dut.row.abort_valid,
      {dut.metadata_offered,dut.metadata_owned,dut.row_active},
      fault_mode,hold_request,hold_output,hold_response,inject_ghost,
      memory_busy,memory_is_metadata,memory_address,memory_length,
      3'(memory_beat),4'(memory_delay),ghost_issued,
      32'(coupled_resets)};
    if($isunknown(journal_packet))$fatal(1,"FRAME_SOURCE_UNKNOWN_JOURNAL edge=%0d",edge_count);
    $fdisplay(journal_fd,"FSC_C episode=%0d edge=%0d data=%0792h",episode_id,edge_count,journal_packet);
    edge_count++;
  end
  task automatic configure_frame;
    @(negedge clk);check(producer_idle,"START_NOT_ROW_QUIET");cfg_valid=1;
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;
  endtask
  task automatic offer_row(input int rank);
    @(negedge clk);check(producer_idle && row_request_ready,"PREVIOUS_ROW_NOT_RETIRED");
    row_request_original_root=10'(rank);row_request_input_rank=10'(rank);
    row_request_tag=32'h60000000+32'(rank);row_request_layer=0;row_request_epoch=1;row_request_valid=1;
    do @(posedge clk);while(!row_request_ready);
    @(negedge clk);row_request_valid=0;
  endtask
  task automatic request_row(input int rank);
    offer_row(rank);
    while(!producer_idle)@(negedge clk);
    check(!row_source_error && accepted_rows==rank+1 && completed_rows==rank+1,"ROW_COMPLETION_BARRIER");
  endtask
  task automatic clean_sampled_edges;
    // The trailing Idle/quiet state must be in the journal, not merely checked
    // by a post-update testbench assertion after its last recorded edge.
    repeat(2)begin @(posedge clk);@(negedge clk);end
  endtask
  task automatic begin_episode(input int number,input string kind,input logic [5:0] mode);
    @(negedge clk);check(!journal_enabled,"OVERLAPPED_EPISODES");
    episode_id=number;fault_mode=mode;hold_request=0;hold_output=0;hold_response=0;inject_ghost=0;
    cfg_valid=0;row_request_valid=0;retire_valid=0;abort_valid=0;rst_n=0;
    requests=0;responses=0;outputs=0;bcfg_count=0;bdone_count=0;bdone_errors=0;
    statistics_words=0;replay_words=0;coupled_resets=0;
    $fdisplay(journal_fd,"FSC_CASE_BEGIN episode=%0d kind=%s first_edge=%0d",episode_id,kind,edge_count);
    journal_enabled=1;
    repeat(4)@(negedge clk);rst_n=1;repeat(2)@(negedge clk);
    check(idle && producer_idle && port_idle && cfg_ready,"INITIAL_COUPLED_RESET_QUIET");
    configure_frame();
  endtask
  task automatic end_episode(input string outcome);
    clean_sampled_edges();
    $fdisplay(journal_fd,"FSC_CASE_END episode=%0d outcome=%s next_edge=%0d accepted=%0d completed=%0d requests=%0d responses=%0d outputs=%0d bcfg=%0d bdone=%0d bdone_errors=%0d statistics=%0d replay=%0d coupled_resets=%0d",episode_id,outcome,edge_count,accepted_rows,completed_rows,requests,responses,outputs,bcfg_count,bdone_count,bdone_errors,statistics_words,replay_words,coupled_resets);
    journal_enabled=0;
  endtask
  task automatic retire_frame(input logic expected_error);
    while(!producer_idle)@(negedge clk);
    check(port_idle && !memory_busy && !read_rsp_valid && row_source_error==expected_error,"RETIRE_REQUIRES_ACTUAL_DRAIN");
    @(negedge clk);retire_valid=1;do @(posedge clk);while(!retire_ready);
    @(negedge clk);retire_valid=0;#1;
    check(!dut.frame_active && producer_idle && port_idle,"RETIRED_FRAME_NOT_QUIET");
    if(!expected_error)check(idle && cfg_ready && !row_source_error,"SOURCE_FRAME_RETIREMENT");
    else check(row_source_error && !cfg_ready,"FAULT_RETIREMENT_CANNOT_RECONFIGURE");
  endtask
  task automatic pulse_abort;
    // Called on an already sampled negative edge; do not skip the held target.
    abort_valid=1;
    repeat(2)begin @(posedge clk);check(row_source_error,"ABORT_NOT_IMMEDIATE");@(negedge clk);end
    abort_valid=0;
  endtask
  task automatic sample_held_request;
    while(!read_req_valid)@(negedge clk);
    repeat(2)begin
      @(posedge clk);check(read_req_valid && !read_req_ready,"REQUEST_TARGET_NOT_SAMPLED_HELD");@(negedge clk);
    end
  endtask
  task automatic sample_held_output;
    while(!out_valid)@(negedge clk);
    repeat(2)begin
      @(posedge clk);check(out_valid && !out_ready,"OUTPUT_TARGET_NOT_SAMPLED_HELD");@(negedge clk);
    end
  endtask
  task automatic coupled_reset;
    // Explicit peer reset may cancel owned transactions or an exposed offer.
    // It is never represented as a successful LAST drain or ordinary retry.
    rst_n=0;coupled_resets++;
    cfg_valid=0;row_request_valid=0;retire_valid=0;abort_valid=0;
    hold_request=0;hold_output=0;hold_response=0;inject_ghost=0;
    repeat(4)@(negedge clk);rst_n=1;repeat(2)@(negedge clk);
    check(idle && producer_idle && port_idle && cfg_ready && !row_source_error && !memory_busy && !read_rsp_valid,"COUPLED_RESET_RECOVERY");
  endtask

  initial begin : run_corpus
    int probe;
    if(!$value$plusargs("FRAME_SOURCE_INPUT_ROOT=%s",input_root))$fatal(1,"FRAME_SOURCE_INPUT_ROOT_REQUIRED");
    if(!$value$plusargs("FRAME_SOURCE_JOURNAL=%s",journal_path))$fatal(1,"FRAME_SOURCE_JOURNAL_REQUIRED");
    if(!$value$plusargs("FRAME_SOURCE_CATALOG_SHA=%s",catalogue_sha) || catalogue_sha.len()!=64)$fatal(1,"FRAME_SOURCE_CATALOG_SHA_REQUIRED");
    probe=$fopen(journal_path,"rb");if(probe!=0)begin $fclose(probe);$fatal(1,"FRAME_SOURCE_PRESERVE_OLD_JOURNAL");end
    load_inputs();journal_fd=$fopen(journal_path,"w");check(journal_fd!=0,"JOURNAL_OPEN_FAILED");
    $fdisplay(journal_fd,"FSC_BEGIN schema=1 bits=%0d digits=%0d inputs=3 source_rows=576 synthetic_prefix_rows=5 catalogue=%s input_manifest=8d0abf0909d5dcdba34cca9e5acf27df6f4343e809df5c39d4ca010dc11261e2",JOURNAL_BITS,JOURNAL_DIGITS,catalogue_sha);
    begin_episode(0,"positive576",0);
    for(int rank=0;rank<576;rank++)request_row(rank);
    check(outputs==147456 && statistics_words==147456 && replay_words==147456 && bcfg_count==576 && bdone_count==576 && bdone_errors==0 &&
      requests==590400 && responses==2065536 && !memory_busy && !read_rsp_valid && port_idle,"COMPLETE_POSITIVE_COUNTS");
    retire_frame(0);
    positive_rows=576;positive_requests=requests;positive_responses=responses;positive_outputs=outputs;
    $display("FRAME_SOURCE_POSITIVE_CORPUS rows=576 output_strips=%0d read_requests=%0d read_responses=%0d first_frame_unit_only=1",outputs,requests,responses);
    end_episode("complete_rows_retired");

    // Exact metadata-only faults: no raw/gamma traffic and no B configuration.
    for(int mode=1;mode<=11;mode++)begin
      case(mode)
        1:begin_episode(mode,"metadata_root_bit8",6'(mode));
        2:begin_episode(mode,"metadata_rank_bit18",6'(mode));
        3:begin_episode(mode,"metadata_position_bit28",6'(mode));
        4:begin_episode(mode,"metadata_layer_bit38",6'(mode));
        5:begin_episode(mode,"metadata_epoch_bit43",6'(mode));
        6:begin_episode(mode,"metadata_reserved_bit59",6'(mode));
        7:begin_episode(mode,"metadata_epsilon_bit0",6'(mode));
        8:begin_episode(mode,"metadata_raw_unit_minus33_epsilon0",6'(mode));
        9:begin_episode(mode,"metadata_early_last_beat0",6'(mode));
        10:begin_episode(mode,"metadata_missing_last_then_beat2_last",6'(mode));
        11:begin_episode(mode,"metadata_response_error_beat0",6'(mode));
      endcase
      offer_row(0);
      while(!producer_idle)@(negedge clk);
      check(row_source_error && bcfg_count==0 && bdone_count==0 && outputs==0 && accepted_rows==1 && completed_rows==0 && requests==1,"METADATA_FAULT_ADMITTED_B");
      if(mode==9)check(responses==1,"EARLY_LAST_COUNT");
      else if(mode==10)check(responses==3,"MISSING_LAST_REAL_DRAIN_COUNT");
      else check(responses==2,"METADATA_PAIR_COUNT");
      retire_frame(1);end_episode("metadata_fault_real_last_drained");
    end

    begin_episode(12,"unsolicited_response_await_demand",0);
    inject_ghost=1;
    while(!read_rsp_valid)@(negedge clk);
    repeat(2)begin @(posedge clk);check(row_source_error && !read_rsp_ready,"UNKNOWN_RESPONSE_NOT_QUARANTINED");@(negedge clk);end
    check(!producer_idle && !port_idle && !cfg_ready && !row_request_ready && !retire_ready && requests==0 && responses==0,"UNKNOWN_ASSOCIATION_FALSE_QUIET");
    coupled_reset();end_episode("unknown_association_coupled_reset");

    begin_episode(13,"unsolicited_response_held_metadata_request",0);
    hold_request=1;offer_row(0);sample_held_request();inject_ghost=1;
    while(!read_rsp_valid)@(negedge clk);
    repeat(2)begin @(posedge clk);check(read_req_valid && !read_req_ready && row_source_error && !read_rsp_ready,"QUARANTINE_WITHDREW_HELD_REQUEST");@(negedge clk);end
    check(!producer_idle && !port_idle && requests==0 && responses==0,"HELD_UNKNOWN_ASSOCIATION_FALSE_QUIET");
    coupled_reset();end_episode("held_offer_unknown_association_coupled_reset");

    begin_episode(14,"abort_held_metadata_request",0);
    hold_request=1;offer_row(0);sample_held_request();pulse_abort();
    repeat(2)begin @(posedge clk);check(read_req_valid && !read_req_ready && row_source_error,"ABORT_WITHDREW_HELD_METADATA");@(negedge clk);end
    hold_request=0;
    while(!producer_idle)@(negedge clk);
    check(requests==1 && responses==2 && bcfg_count==0 && outputs==0,"HELD_METADATA_NOT_REAL_LAST_DRAINED");
    retire_frame(1);end_episode("aborted_offer_accepted_and_real_last_drained");

    begin_episode(15,"abort_held_normalized_output",0);
    hold_output=1;offer_row(0);sample_held_output();pulse_abort();
    repeat(2)begin @(posedge clk);check(out_valid && !out_ready && row_source_error,"ABORT_WITHDREW_HELD_OUTPUT");@(negedge clk);end
    hold_output=0;
    while(!producer_idle)@(negedge clk);
    check(bcfg_count==1 && bdone_count==1 && bdone_errors==1 && completed_rows==0 && outputs>=1 && !memory_busy && !read_rsp_valid,"ROW_ABORT_COMPLETION_BARRIER");
    retire_frame(1);end_episode("held_output_and_owned_reads_drained");

    begin_episode(16,"coupled_reset_owned_metadata",0);
    hold_response=1;offer_row(0);
    while(!(memory_busy && dut.metadata_owned && !read_rsp_valid))@(negedge clk);
    repeat(2)begin @(posedge clk);check(memory_busy && dut.metadata_owned && !read_rsp_valid,"OWNED_METADATA_RESET_TARGET_NOT_SAMPLED");@(negedge clk);end
    check(requests==1 && responses==0 && !port_idle,"OWNED_METADATA_WAS_NOT_PENDING");
    coupled_reset();end_episode("owned_metadata_cancelled_only_by_coupled_reset");

    begin_episode(17,"coupled_reset_held_normalized_output",0);
    hold_output=1;offer_row(0);sample_held_output();
    check(bcfg_count==1 && outputs==0,"HELD_OUTPUT_RESET_TARGET_WRONG");
    coupled_reset();end_episode("held_output_cancelled_only_by_coupled_reset");

    begin_episode(18,"postreset_two_successive_rows_then_abort_retire",0);
    request_row(0);request_row(1);
    check(outputs==512 && statistics_words==512 && replay_words==512 && bcfg_count==2 && bdone_count==2 && bdone_errors==0 && accepted_rows==2 && completed_rows==2,"TWO_ROW_RECOVERY_COUNTS");
    pulse_abort();retire_frame(1);end_episode("two_rows_complete_partial_frame_aborted_and_retired");

    $fdisplay(journal_fd,"FSC_END episodes=19 records=%0d positive_rows=%0d positive_requests=%0d positive_responses=%0d positive_outputs=%0d source_retire=1",edge_count,positive_rows,positive_requests,positive_responses,positive_outputs);
    $fflush(journal_fd);$fclose(journal_fd);
    $display("FRAME_SOURCE_BENCH_PASS episodes=19 positive_rows=576 full_frame_verified=0");
    $finish;
  end
endmodule
