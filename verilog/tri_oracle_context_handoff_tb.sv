`timescale 1ns/1ps
// Catches premature acquisition/release, missing arbitration, changed held
// configuration, wrong packing order and failure to recover from a bad row.
module tri_oracle_context_handoff_tb;
  logic clk=0,rst_n=0;always #5 clk=~clk;
  logic cfg_valid=0,cfg_ready;
  logic [31:0] cfg_tag=0,context_tag;
  logic [10:0] cfg_query=0,context_query;
  logic signed [8:0] cfg_zero_exponent=0,context_exponent;
  logic row_valid=0,row_ready,row_error=0;
  logic [10:0] row_query=0;
  logic [4:0] row_head=0;
  logic [2047:0] row_data=0;
  logic signed [7:0] row_value_exponent=0;
  logic metadata_idle=0,metadata_block,metadata_needs_rebuild,metadata_rebuilt=0,lease_active;
  logic [5:0] metadata_ce_n='1,metadata_we_n='1;
  logic [53:0] metadata_address=0;
  logic [767:0] metadata_write_data=0,metadata_write_mask='1,metadata_read_data;
  logic context_valid,read_req_valid=0,read_req_ready,read_rsp_valid,read_rsp_ready=0,read_rsp_error;
  logic [9:0] read_req_word=0;
  logic [63:0] read_rsp_data;
  logic finish_valid=0,finish_ready,done_valid,done_ready=0,done_error;
  logic [2055:0] rows[96];logic [63:0] codes[768];logic [8:0] units[3];
  string rows_file,codes_file,units_file;
  int frames,checks=0;

  tri_oracle_context_handoff dut (
    .clk,.rst_n,.cfg_valid,.cfg_ready,.cfg_tag,.cfg_query,.cfg_zero_exponent,
    .row_valid,.row_ready,.row_error,.row_query,.row_head,.row_data,.row_value_exponent,
    .metadata_idle,.metadata_block,.metadata_needs_rebuild,.metadata_rebuilt,.lease_active,
    .metadata_ce_n,.metadata_we_n,.metadata_address,.metadata_write_data,.metadata_write_mask,.metadata_read_data,
    .context_valid,.context_tag,.context_query,.context_exponent,
    .read_req_valid,.read_req_ready,.read_req_word,.read_rsp_valid,.read_rsp_ready,.read_rsp_error,.read_rsp_data,
    .finish_valid,.finish_ready,.done_valid,.done_ready,.done_error
  );

  task automatic begin_frame(input int query);
    @(negedge clk);cfg_query=11'(query);cfg_tag=32'hc7100000+32'(query);cfg_zero_exponent=0;cfg_valid=1;
    @(posedge clk);if(!cfg_ready)$fatal(1,"CONTEXT_CTL_CONFIG_NOT_READY");
    @(negedge clk);cfg_valid=0;cfg_query='1;cfg_tag='1;cfg_zero_exponent=127;
  endtask
  task automatic wait_lease;
    for(int i=0;i<20;i++)begin
      @(negedge clk);if(lease_active)return;
    end
    $fatal(1,"CONTEXT_CTL_NO_ACQUIRE");
  endtask
  task automatic send_row(input int head,input int query,input logic [2055:0] value,input logic bad);
    @(negedge clk);row_head=5'(head);row_query=11'(query);{row_value_exponent,row_data}=value;
    row_error=bad;row_valid=1;
    for(int i=0;i<256;i++)begin
      @(posedge clk);
      if(row_ready)begin @(negedge clk);row_valid=0;row_error=0;return;end
      if(context_valid || !lease_active || cfg_ready)$fatal(1,"CONTEXT_CTL_ROW_OWNERSHIP");
    end
    $fatal(1,"CONTEXT_CTL_ROW_TIMEOUT");
  endtask
  task automatic wait_context(input int frame,input int query);
    for(int i=0;i<10000;i++)begin
      @(negedge clk);
      if(done_valid)$fatal(1,"CONTEXT_CTL_FALSE_TERMINAL error=%b",done_error);
      if(context_valid)begin
        if(!lease_active || context_exponent!==units[frame] || context_query!==11'(query) || context_tag!==32'hc7100000+32'(query))
          $fatal(1,"CONTEXT_CTL_CONTEXT_METADATA");
        return;
      end
    end
    $fatal(1,"CONTEXT_CTL_CONVERT_TIMEOUT");
  endtask
  task automatic read_word(input int address,input logic [63:0] expected,input logic expected_error);
    @(negedge clk);read_req_word=10'(address);read_req_valid=1;
    @(posedge clk);if(!read_req_ready)$fatal(1,"CONTEXT_CTL_READ_NOT_ACCEPTED");
    @(negedge clk);read_req_valid=0;finish_valid=1;
    repeat(3)begin
      @(posedge clk);
      if(!read_rsp_valid || read_rsp_error!==expected_error || read_rsp_data!==expected || finish_ready || !lease_active)
        $fatal(1,"CONTEXT_CTL_EARLY_FINISH_OR_BAD_READ word=%0d got=%h want=%h",address,read_rsp_data,expected);
      @(negedge clk);
    end
    finish_valid=0;read_rsp_ready=1;@(negedge clk);read_rsp_ready=0;checks++;
    if(read_rsp_valid)$fatal(1,"CONTEXT_CTL_EXTRA_RESPONSE");
  endtask
  task automatic finish_frame(input logic error_expected);
    @(negedge clk);finish_valid=1;read_req_valid=1;
    @(posedge clk);if(!finish_ready || read_req_ready)$fatal(1,"CONTEXT_CTL_FINISH_PRIORITY");
    @(negedge clk);finish_valid=0;read_req_valid=0;
    for(int i=0;i<20;i++)begin @(negedge clk);if(done_valid)break;end
    repeat(3)begin
      @(posedge clk);
      if(!done_valid || done_error!==error_expected || lease_active || context_valid || !metadata_needs_rebuild || !metadata_block)
        $fatal(1,"CONTEXT_CTL_TERMINAL");
      @(negedge clk);
    end
    done_ready=1;@(negedge clk);done_ready=0;
    if(done_valid || !cfg_ready || metadata_block)$fatal(1,"CONTEXT_CTL_TERMINAL_DRAIN");
  endtask
  task automatic error_terminal;
    for(int i=0;i<10000;i++)begin
      @(negedge clk);
      if(context_valid)$fatal(1,"CONTEXT_CTL_BAD_FRAME_EXPOSED");
      if(done_valid)break;
    end
    if(!done_valid || !done_error || lease_active || !metadata_needs_rebuild)$fatal(1,"CONTEXT_CTL_ERROR_NOT_DRAINED");
    repeat(3)begin @(posedge clk);if(!done_valid || !done_error)$fatal(1,"CONTEXT_CTL_ERROR_NOT_HELD");@(negedge clk);end
    done_ready=1;@(negedge clk);done_ready=0;
    if(!cfg_ready)$fatal(1,"CONTEXT_CTL_ERROR_RECOVERY");
  endtask
  task automatic reset_transaction;
    @(negedge clk);rst_n=0;cfg_valid=0;row_valid=0;row_error=0;
    read_req_valid=0;read_rsp_ready=0;finish_valid=0;done_ready=0;
    metadata_rebuilt=0;metadata_ce_n='1;metadata_we_n='1;
    repeat(3)begin
      @(posedge clk);
      if(lease_active || context_valid || done_valid || read_rsp_valid || cfg_ready || !metadata_block || !metadata_needs_rebuild)
        $fatal(1,"CONTEXT_CTL_RESET_LEAK");
      @(negedge clk);
    end
    rst_n=1;@(negedge clk);
    if(!cfg_ready || lease_active || context_valid || done_valid || read_rsp_valid || !metadata_needs_rebuild)
      $fatal(1,"CONTEXT_CTL_RESET_RECOVERY");
  endtask
  initial begin
    logic [2055:0] bad_row;
    if(!$value$plusargs("ROWS=%s",rows_file)||!$value$plusargs("CODES=%s",codes_file)||
       !$value$plusargs("UNITS=%s",units_file)||!$value$plusargs("FRAMES=%d",frames)||frames<1||frames>3)$fatal(1,"CONTEXT_CTL_ARGUMENTS");
    $readmemh(rows_file,rows,0,frames*32-1);$readmemh(codes_file,codes,0,frames*256-1);$readmemh(units_file,units,0,frames-1);
    repeat(3)@(negedge clk);rst_n=1;
    if(!metadata_needs_rebuild)$fatal(1,"CONTEXT_CTL_RESET_INVALIDITY");
    metadata_rebuilt=1;@(negedge clk);metadata_rebuilt=0;
    if(metadata_needs_rebuild)$fatal(1,"CONTEXT_CTL_REBUILD_ACK");
    for(int frame=0;frame<frames;frame++)begin
      metadata_idle=0;metadata_ce_n='1;begin_frame(frame);
      repeat(4)begin @(posedge clk);if(lease_active || row_ready || !metadata_block)$fatal(1,"CONTEXT_CTL_QUIESCENCE");@(negedge clk);end
      metadata_idle=1;metadata_ce_n=6'b111110;
      repeat(3)begin @(posedge clk);if(lease_active)$fatal(1,"CONTEXT_CTL_PENDING_METADATA");@(negedge clk);end
      metadata_ce_n='1;wait_lease();
      metadata_rebuilt=1;metadata_ce_n=0;metadata_we_n=0;metadata_write_mask=0;metadata_write_data='1;
      read_req_valid=1;
      for(int i=0;i<32;i++)begin
        if(read_req_ready || !metadata_needs_rebuild || metadata_read_data!==0)$fatal(1,"CONTEXT_CTL_LEASE_FENCE");
        send_row((17*i+31)%32,frame,rows[frame*32+(17*i+31)%32],0);
      end
      read_req_valid=0;metadata_rebuilt=0;metadata_ce_n='1;metadata_we_n='1;
      wait_context(frame,frame);
      cfg_valid=1;repeat(3)begin @(posedge clk);if(cfg_ready || !context_valid)$fatal(1,"CONTEXT_CTL_BUSY_CONFIG");@(negedge clk);end cfg_valid=0;
      for(int word=0;word<256;word++)read_word(word,codes[frame*256+word],0);
      finish_frame(0);
      metadata_rebuilt=1;@(negedge clk);metadata_rebuilt=0;
      if(metadata_needs_rebuild)$fatal(1,"CONTEXT_CTL_REBUILD_RECOVERY");
    end
    // Duplicate-head framing must fail without presenting a valid context.
    begin_frame(100);wait_lease();send_row(0,100,rows[0],0);send_row(0,100,rows[0],0);error_terminal();
    // A result for a different query and a producer-reported error are rejected.
    begin_frame(101);wait_lease();send_row(0,102,rows[0],0);error_terminal();
    begin_frame(102);wait_lease();send_row(0,102,rows[0],1);error_terminal();
    // Outside the signed25 lossless bound: fail before conversion.
    bad_row='0;bad_row[31:0]=32'h01000000;
    begin_frame(103);wait_lease();send_row(0,103,bad_row,0);error_terminal();
    // All-zero raw rows with unsupported transfer units fail in the converter.
    bad_row='0;bad_row[2055:2048]=-8'sd100;
    begin_frame(104);wait_lease();for(int h=0;h<32;h++)send_row(h,104,bad_row,0);error_terminal();
    // Recovery after conversion failure, then a bad projection-read address.
    begin_frame(105);wait_lease();for(int h=0;h<32;h++)send_row(h,105,rows[h],0);wait_context(0,105);
    read_word(256,0,1);finish_frame(1);
    // Reset must cancel a partially packed held source row and every memory lease.
    begin_frame(106);wait_lease();row_head=0;row_query=106;{row_value_exponent,row_data}=rows[0];row_valid=1;
    repeat(14)@(negedge clk);
    if(row_ready || !lease_active)$fatal(1,"CONTEXT_CTL_RESET_PACK_SETUP");
    reset_transaction();
    // Recover, reach a held read response, and reset without consuming it.
    begin_frame(107);wait_lease();for(int h=0;h<32;h++)send_row(h,107,rows[h],0);wait_context(0,107);
    read_req_word=5;read_req_valid=1;@(posedge clk);if(!read_req_ready)$fatal(1,"CONTEXT_CTL_RESET_READ_SETUP");
    @(negedge clk);read_req_valid=0;
    repeat(2)begin @(posedge clk);if(!read_rsp_valid || read_rsp_data!==codes[5])$fatal(1,"CONTEXT_CTL_RESET_HELD_SETUP");@(negedge clk);end
    reset_transaction();
    begin_frame(108);wait_lease();for(int h=0;h<32;h++)send_row(h,108,rows[h],0);wait_context(0,108);
    read_word(0,codes[0],0);read_word(255,codes[255],0);finish_frame(0);
    $display("CONTEXT_CONTROLLER_PASS frames=%0d code_words=%0d recovery_words=2 malformed_frames=5 read_address_faults=1 reset_phases=2",frames,checks-3);
    $finish;
  end
  initial begin #6000000;$fatal(1,"CONTEXT_CTL_TIMEOUT");end
endmodule
