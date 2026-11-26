`timescale 1ns/1ps
// Synthetic controller-fault inputs only. The trained normalizer/TMU path is
// exercised by the parent bench. All memory operations use the real store.
module row_stage_contract_controls(output logic done = 0);
  logic clk=0,rst_n=0;
  always #5 clk=~clk;
  logic start_valid=0,start_ready,abort_valid=0,producer_idle=1,epoch_clear_valid=0;
  logic [31:0] start_tag=0;
  logic epoch_clear_ready,epoch_invalid;
  logic in_valid=0,in_ready,in_last=0,in_error=0;
  logic [31:0] in_tag=0;
  logic [9:0] in_index=0;
  logic [3:0] in_count=8;
  logic [63:0] in_activation=0;
  logic signed [8:0] in_exponent=-7;
  logic [7:0] in_negative=0;
  logic stage_acquire_valid,acquire_ready,context_owned;
  logic stage_release_valid,release_ready_memory;
  logic stage_req_valid,stage_req_ready,stage_req_write,stage_rsp_ready;
  logic [9:0] stage_req_word;
  logic [63:0] stage_req_data;
  logic ram_rsp_valid,ram_rsp_ready,ram_rsp_error;
  logic [63:0] ram_rsp_data;
  logic row_valid,row_ready=0,row_consumed,release_valid=0,release_ready,consumer_idle=1;
  logic [31:0] row_tag;
  logic signed [8:0] row_exponent;
  logic [2047:0] row_negative;
  logic lease_held;
  logic [8:0] accepted_words,acknowledged_words;
  logic ff_idle=1;
  logic [1:0] ff_ce_n=2'b11,ff_we_n=2'b11;
  logic [17:0] ff_address=0;
  logic [127:0] ff_write_data=0,ff_read_data;
  logic request_enable=1,response_enable=1,release_enable=1,inject_rsp_error=0;
  logic unexpected_release=0;
  logic ram_req_ready;
  wire ram_req_valid=stage_req_valid && request_enable;
  wire ram_release_valid=(stage_release_valid && release_enable) || unexpected_release;
  wire routed_rsp_valid=ram_rsp_valid && response_enable;
  wire routed_rsp_error=ram_rsp_error || inject_rsp_error;
  assign stage_req_ready=ram_req_ready && request_enable;
  assign ram_rsp_ready=stage_rsp_ready && response_enable;
  int passed=0,request_total=0,response_total=0;
  bit outstanding=0;
  localparam logic [63:0] Descriptor256=64'h4765_2301_a1b2_c3d4;
  localparam logic [63:0] Descriptor831=64'h27de_fedc_7654_3210;

  tri_oracle_normalized_row_stage stage (
    .clk,.rst_n,.start_valid,.start_ready,.start_tag,.abort_valid,.producer_idle,
    .epoch_clear_valid,.epoch_clear_ready,.epoch_invalid,
    .in_valid,.in_ready,.in_tag,.in_index,.in_count,.in_last,.in_error,
    .in_activation,.in_exponent,.in_negative,
    .memory_acquire_valid(stage_acquire_valid),.memory_acquire_ready(acquire_ready),
    .memory_context_owned(context_owned),.memory_release_valid(stage_release_valid),
    .memory_release_ready(release_ready_memory && release_enable),
    .memory_req_valid(stage_req_valid),.memory_req_ready(stage_req_ready),
    .memory_req_write(stage_req_write),.memory_req_word(stage_req_word),.memory_req_data(stage_req_data),
    .memory_rsp_valid(routed_rsp_valid),.memory_rsp_error(routed_rsp_error),.memory_rsp_ready(stage_rsp_ready),
    .row_valid,.row_ready,.row_tag,.row_exponent,.row_negative,.row_consumed,
    .release_valid,.release_ready,.consumer_idle,.lease_held,.accepted_words,.acknowledged_words
  );
  tri_oracle_shared_metadata_store memory (
    .clk,.rst_n,.ff_idle,.acquire_valid(stage_acquire_valid),.acquire_ready,
    .release_valid(ram_release_valid),.release_ready(release_ready_memory),.context_owned,
    .ff_ce_n,.ff_we_n,.ff_address,.ff_write_data,.ff_read_data,
    .req_valid(ram_req_valid),.req_write(stage_req_write),.req_ready(ram_req_ready),
    .req_word(stage_req_word),.req_data(stage_req_data),
    .rsp_valid(ram_rsp_valid),.rsp_error(ram_rsp_error),.rsp_ready(ram_rsp_ready),.rsp_data(ram_rsp_data)
  );

  function automatic logic [63:0] activation(input int word_index);
    case(word_index)
      0:return 64'h0000_0000_0000_0000;
      1:return 64'hffff_ffff_ffff_ffff;
      2:return 64'h8000_0000_0000_0000;
      3:return 64'h7fff_ffff_ffff_ffff;
      default:return 64'h8c71_25b4_019f_d362 ^ (64'(word_index)*64'h0101_0001_0400_0021);
    endcase
  endfunction
  function automatic logic [7:0] sign_byte(input int word_index);
    return 8'(word_index)^8'ha5;
  endfunction
  task automatic check(input logic condition,input string reason);
    if(condition!==1'b1)$fatal(1,"ROW_STAGE_CONTROL_%s accepted=%0d ack=%0d at=%0t",reason,accepted_words,acknowledged_words,$time);
  endtask
  task automatic tick;
    @(posedge clk);#2;
  endtask
  task automatic pass(input string name);
    passed++;
    $display("ROW_STAGE_CONTROL_PASS name=%s",name);
  endtask

  // Capture genuine pre-edge request/response handshakes independently. The
  // transport gates always gate valid AND ready, never synthesize a response.
  always @(posedge clk)begin
    if(!rst_n)outstanding=0;
    else begin
      if(ram_req_valid && ram_req_ready)begin
        if(outstanding || stage_req_write!==1'b1 || stage_req_word>=256)
          $fatal(1,"ROW_STAGE_CONTROL_BAD_OR_OVERLAPPED_REAL_REQUEST");
        outstanding=1;request_total++;
      end
      if(ram_rsp_valid && ram_rsp_ready)begin
        if(!outstanding || ram_rsp_error!==0)$fatal(1,"ROW_STAGE_CONTROL_UNMATCHED_REAL_RESPONSE");
        outstanding=0;response_total++;
      end
    end
    #2;
    if(rst_n && row_valid && (epoch_invalid || !lease_held || accepted_words!=256 || acknowledged_words!=256))
      $fatal(1,"ROW_STAGE_CONTROL_PREMATURE_COMMIT");
  end

  task automatic begin_row(input logic [31:0] tag);
    int waits;
    @(negedge clk);start_tag=tag;producer_idle=1;start_valid=1;
    waits=0;
    do begin
      @(posedge clk);waits++;
      if(waits>40)$fatal(1,"ROW_STAGE_CONTROL_START_TIMEOUT");
    end while(!start_ready);
    #2;check(context_owned && lease_held && !epoch_invalid,"ACQUIRE_JOIN");
    @(negedge clk);start_valid=0;producer_idle=0;
  endtask
  task automatic offer(input int word_index,input int fault=0);
    int waits;
    @(negedge clk);
    in_valid=1;in_tag=start_tag;in_index=10'(word_index);in_count=8;
    in_activation=activation(word_index);in_negative=sign_byte(word_index);
    in_exponent=-7;in_error=0;in_last=word_index==255;
    case(fault)
      1:in_tag=start_tag^32'h0000_0001;
      2:in_index=10'(word_index+1);
      3:in_count=7;
      4:in_last=1;
      5:begin in_error=1;in_last=1;end
      6:in_exponent=-6;
      7:in_last=0;
      default:begin end
    endcase
    waits=0;
    do begin
      @(posedge clk);waits++;
      if(waits>40)$fatal(1,"ROW_STAGE_CONTROL_INPUT_TIMEOUT");
    end while(!in_ready);
    #2;
    @(negedge clk);in_valid=0;
  endtask
  task automatic wait_acks(input int count);
    int waits;
    waits=0;
    while(acknowledged_words!=count)begin
      tick();waits++;
      if(waits>40)$fatal(1,"ROW_STAGE_CONTROL_ACK_TIMEOUT expected=%0d",count);
    end
  endtask
  task automatic send(input int word_index);
    offer(word_index);wait_acks(word_index+1);
  endtask
  task automatic send_prefix(input int count);
    for(int word_index=0;word_index<count;word_index++)send(word_index);
  endtask
  task automatic clear_epoch;
    int waits;
    @(negedge clk);in_valid=0;producer_idle=1;consumer_idle=1;abort_valid=0;
    row_ready=0;request_enable=1;response_enable=1;release_enable=1;inject_rsp_error=0;
    release_valid=1;waits=0;
    while(context_owned || lease_held || ram_rsp_valid || outstanding)begin
      tick();waits++;
      if(waits>40)$fatal(1,"ROW_STAGE_CONTROL_FAULT_DRAIN_TIMEOUT");
    end
    @(negedge clk);release_valid=0;epoch_clear_valid=1;
    waits=0;
    do begin
      @(posedge clk);waits++;
      if(waits>40)$fatal(1,"ROW_STAGE_CONTROL_CLEAR_TIMEOUT");
    end while(!epoch_clear_ready);
    #2;check(!epoch_invalid && !row_valid && !lease_held,"CLEAR_RECOVERY");
    @(negedge clk);epoch_clear_valid=0;
    #1;check(start_ready,"RESTART_READY");
  endtask
  task automatic delay_fault_release;
    @(negedge clk);release_valid=1;producer_idle=0;consumer_idle=1;
    repeat(3)begin tick();check(epoch_invalid && context_owned && !release_ready && !row_valid,"PRODUCER_DRAIN_REQUIRED");end
    clear_epoch();
  endtask
  task automatic metadata_fault(input int mode,input string name);
    int prior_requests;
    begin_row(32'hc017_1000+32'(mode));
    if(mode==6)send(0);
    if(mode==7)send_prefix(255);
    prior_requests=request_total;
    offer(mode==6 ? 1:(mode==7 ? 255:0),mode);
    check(epoch_invalid && !row_valid && request_total==prior_requests,"BAD_METADATA_NOT_WRITTEN");
    delay_fault_release();pass(name);
  endtask
  task automatic ff_word(input int index,input bit write_it,input logic [63:0] value);
    int bank;
    bank=index/512;
    @(negedge clk);check(!context_owned && !lease_held && !in_valid && !start_valid,"EXCLUSIVE_FF_OWNER");
    ff_idle=0;ff_ce_n=2'b11;ff_we_n=2'b11;
    ff_address[bank*9+:9]=9'(index%512);ff_write_data[bank*64+:64]=value;
    ff_ce_n[bank]=0;ff_we_n[bank]=!write_it;
    tick();
    if(!write_it)check(ff_read_data[bank*64+:64]===value,"DESCRIPTOR_RETENTION");
    @(negedge clk);ff_ce_n=2'b11;ff_we_n=2'b11;ff_idle=1;
  endtask
  task automatic healthy_row(input logic [31:0] tag,input bit stalls);
    logic [2047:0] wanted_signs;
    begin_row(tag);send_prefix(256);
    for(int word_index=0;word_index<256;word_index++)wanted_signs[word_index*8+:8]=sign_byte(word_index);
    #1;check(row_valid && !row_consumed && row_tag===tag && row_exponent===-9'sd7 && row_negative===wanted_signs,"HEALTHY_ROW_PAYLOAD");
    if(stalls)begin
      repeat(4)begin tick();check(row_valid && !row_consumed && row_tag===tag && row_negative===wanted_signs && lease_held,"CONSUMER_STABLE");end
      @(negedge clk);release_valid=1;
      tick();check(!release_ready && context_owned && row_valid,"NO_RELEASE_BEFORE_SIGN_ACCEPT");
      @(negedge clk);release_valid=0;
    end
    @(negedge clk);row_ready=1;producer_idle=1;
    tick();check(row_consumed && !row_valid && context_owned,"SIGN_ACCEPT_RETAINS_LEASE");
    @(negedge clk);row_ready=0;release_valid=1;
    if(stalls)begin
      consumer_idle=0;
      repeat(3)begin tick();check(!release_ready && context_owned && !stage_release_valid,"CONSUMER_DRAIN_REQUIRED");end
      @(negedge clk);consumer_idle=1;release_enable=0;
      repeat(3)begin tick();check(!release_ready && stage_release_valid && context_owned,"RELEASE_BACKPRESSURE");end
      @(negedge clk);release_enable=1;
    end
    tick();check(!context_owned && !lease_held && !row_valid,"HEALTHY_RELEASE");
    @(negedge clk);release_valid=0;
  endtask

  initial begin
    repeat(3)@(negedge clk);rst_n=1;
    // The descriptor words are outside the row's0..255 range. The separate FF
    // owner is used only before/after real stage leases, never concurrently.
    ff_word(256,1,Descriptor256);ff_word(831,1,Descriptor831);
    healthy_row(32'hc017_0001,1);
    for(int word_index=0;word_index<4;word_index++)ff_word(word_index,0,activation(word_index));
    pass("zero_and_extreme_word_data");
    ff_word(256,0,Descriptor256);ff_word(831,0,Descriptor831);
    healthy_row(32'hc017_0002,0);ff_word(256,0,Descriptor256);ff_word(831,0,Descriptor831);
    pass("two_row_leases_descriptor_retention_and_consumer_release_stalls");

    // Busy predictor prevents genuine acquisition. Abort must neither acquire
    // nor require releasing a lease that this stage never obtained.
    @(negedge clk);ff_idle=0;start_valid=1;start_tag=32'hc017_0100;
    repeat(3)begin tick();check(!start_ready && !context_owned && !lease_held,"BUSY_ACQUIRE_STALL");end
    @(negedge clk);abort_valid=1;
    tick();check(epoch_invalid && !context_owned && !lease_held,"ABORT_BEFORE_ACQUIRE");
    @(negedge clk);start_valid=0;ff_idle=1;abort_valid=0;
    clear_epoch();pass("offered_start_abort_before_acquire_clear");

    metadata_fault(1,"bad_tag");metadata_fault(2,"bad_index");metadata_fault(3,"bad_count");
    metadata_fault(4,"early_last");metadata_fault(5,"producer_terminal_error");
    metadata_fault(6,"changed_signed_exponent");metadata_fault(7,"missing_last_after255");

    begin_row(32'hc017_1900);
    @(negedge clk);request_enable=0;in_valid=1;in_tag=start_tag;in_index=0;
    in_count=8;in_last=0;in_error=0;in_activation=activation(0);in_negative=sign_byte(0);in_exponent=-7;
    repeat(3)begin
      tick();check(stage_req_valid && !stage_req_ready && !in_ready &&
                   accepted_words==0 && !ram_rsp_valid && stage_req_word==0 && stage_req_data===activation(0),"REQUEST_OFFER_STABLE");
    end
    @(negedge clk);abort_valid=1;
    tick();check(epoch_invalid && accepted_words==0 && !ram_rsp_valid && !row_valid,"ABORT_UNACCEPTED_REQUEST");
    @(negedge clk);in_valid=0;abort_valid=0;request_enable=1;
    delay_fault_release();pass("request_backpressure_and_abort_before_acceptance");

    begin_row(32'hc017_2001);response_enable=0;offer(0);
    check(accepted_words==1 && acknowledged_words==0 && ram_rsp_valid && !ram_rsp_ready,"REAL_RESPONSE_HELD");
    @(negedge clk);abort_valid=1;release_valid=1;
    tick();check(epoch_invalid && context_owned && !release_ready && !row_valid,"ABORT_RELEASE_CONFLICT");
    @(negedge clk);abort_valid=0;
    repeat(3)begin tick();check(lease_held && ram_rsp_valid && acknowledged_words==0 && !release_ready,"PENDING_RESPONSE_BLOCKS_RELEASE");end
    @(negedge clk);response_enable=1;
    wait_acks(1);delay_fault_release();pass("abort_pending_response_and_delayed_producer_drain");

    begin_row(32'hc017_2002);send_prefix(255);response_enable=0;offer(255);
    check(accepted_words==256 && acknowledged_words==255 && ram_rsp_valid && !row_valid,"FINAL_RESPONSE_HELD");
    @(negedge clk);abort_valid=1;response_enable=1;row_ready=1;release_valid=1;
    tick();check(epoch_invalid && acknowledged_words==256 && !row_consumed && !row_valid && context_owned,"ABORT_FINAL_ACK_NO_COMMIT");
    clear_epoch();pass("abort_coincident_final_ack_never_commits");

    begin_row(32'hc017_2003);response_enable=0;offer(0);
    @(negedge clk);inject_rsp_error=1;response_enable=1;
    tick();check(epoch_invalid && acknowledged_words==0 && !row_valid,"INJECTED_MATCHED_RESPONSE_ERROR");
    delay_fault_release();pass("matched_response_error_invalidates_epoch");

    // Coupled reset intentionally destroys local response ownership. This is
    // a system-epoch invalidation control, not an in-place recovery claim.
    begin_row(32'hc017_3000);response_enable=0;offer(0);
    @(negedge clk);rst_n=0;
    tick();check(!context_owned && !lease_held && !row_valid && !ram_rsp_valid,"COUPLED_RESET_PENDING_RESPONSE");
    @(negedge clk);response_enable=1;release_valid=0;row_ready=0;producer_idle=1;rst_n=1;
    healthy_row(32'hc017_3001,0);pass("coupled_reset_and_new_epoch_row");
    // Fault injection uses the real store release handshake, never context
    // force. The row is not consumed before ownership actually falls.
    begin_row(32'hc017_4000);send_prefix(256);
    check(row_valid && !row_consumed && context_owned,"OWNERSHIP_LOSS_PRECONDITION");
    @(negedge clk);producer_idle=1;unexpected_release=1;
    tick();check(!context_owned && !lease_held && !row_valid,"LOST_CONTEXT_BLOCKS_ROW_IMMEDIATELY");
    @(negedge clk);unexpected_release=0;row_ready=1;
    tick();check(epoch_invalid && !row_consumed && !row_valid,"NO_ROW_ACCEPT_ON_OWNERSHIP_FAULT_EDGE");
    clear_epoch();pass("real_store_lost_ownership_prevents_sign_consumption");
    ff_word(256,0,Descriptor256);ff_word(831,0,Descriptor831);
    check(passed==16 && request_total==1539 && response_total==1538 && !context_owned && !lease_held && !ram_rsp_valid && !outstanding,"FINAL_INVENTORY");
    $display("ROW_STAGE_CONTROL_SUMMARY cases=%0d actual_write_requests=%0d actual_write_responses=%0d",passed,request_total,response_total);
    done=1;
  end
  initial begin
    #5000000;
    if(!done)$fatal(1,"ROW_STAGE_CONTROL_WATCHDOG");
  end
endmodule
