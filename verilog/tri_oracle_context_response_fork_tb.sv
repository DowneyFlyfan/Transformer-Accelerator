`timescale 1ns/1ps
// A lost row acknowledgment recaptures a head under host backpressure.
// Wrong descriptor sampling changes hardware-produced context bytes or units.
module tri_oracle_context_response_fork_tb;
  logic clk=0,rst_n=0;always #5 clk=~clk;
  logic command_valid=0,command_ready=0,payload_valid=0,payload_ready=0,payload_last=0;
  logic [2:0] command_opcode=0;
  logic [31:0] command_tag=0;
  logic [63:0] payload_data=0;
  logic source_valid=0,source_ready,source_error=0;
  logic [2:0] source_opcode=0;
  logic [31:0] source_tag=0;
  logic [2047:0] source_values=0;
  logic response_valid,response_ready=0,response_error;
  logic [2:0] response_opcode;
  logic [31:0] response_tag;
  logic [2047:0] response_values;
  logic cfg_valid,cfg_ready;
  logic [31:0] cfg_tag,context_tag;
  logic [10:0] cfg_query,context_query;
  logic signed [8:0] cfg_zero_exponent,context_exponent;
  logic row_valid,row_ready,row_error;
  logic [10:0] row_query;
  logic [4:0] row_head;
  logic [2047:0] row_data;
  logic signed [7:0] row_value_exponent;
  logic metadata_idle=1,metadata_block,metadata_needs_rebuild,lease_active;
  logic [767:0] metadata_read_data;
  logic context_valid,read_req_valid=0,read_req_ready,read_rsp_valid,read_rsp_ready=0,read_rsp_error;
  logic [9:0] read_req_word=0;
  logic [63:0] read_rsp_data;
  logic finish_valid=0,finish_ready,done_valid,done_ready=0,done_error;
  logic frame_open,projection_active;
  logic signed [8:0] descriptor_zero_exponent=0;
  logic [2055:0] rows[96];logic [63:0] codes[768];logic [8:0] units[3];
  string rows_file,codes_file,units_file;
  int frames,captures=0,configs=0,host_transfers=0,source_transfers=0,words_checked=0,bypasses=0;
  int expected_head=0,expected_query=0;
  logic [2055:0] expected_row=0;
  logic expected_row_error=0;

  tri_oracle_context_response_fork fork_dut (
    .clk,.rst_n,.command_valid,.command_ready,.command_opcode,.command_tag,
    .payload_valid,.payload_ready,.payload_data,.payload_last,
    .source_valid,.source_ready,.source_error,.source_opcode,.source_tag,.source_values,
    .response_valid,.response_ready,.response_error,.response_opcode,.response_tag,.response_values,
    .cfg_valid,.cfg_ready,.cfg_tag,.cfg_query,.cfg_zero_exponent,
    .row_valid,.row_ready,.row_error,.row_query,.row_head,.row_data,.row_value_exponent,
    .context_done_accepted(done_valid && done_ready),.frame_open,.projection_active
  );
  tri_oracle_context_handoff controller (
    .clk,.rst_n,.cfg_valid,.cfg_ready,.cfg_tag,.cfg_query,.cfg_zero_exponent,
    .row_valid,.row_ready,.row_error,.row_query,.row_head,.row_data,.row_value_exponent,
    .metadata_idle,.metadata_block,.metadata_needs_rebuild,.metadata_rebuilt(1'b0),.lease_active,
    .metadata_ce_n(6'b111111),.metadata_we_n(6'b111111),.metadata_address(54'b0),
    .metadata_write_data(768'b0),.metadata_write_mask({768{1'b1}}),.metadata_read_data,
    .context_valid,.context_tag,.context_query,.context_exponent,
    .read_req_valid,.read_req_ready,.read_req_word,.read_rsp_valid,.read_rsp_ready,.read_rsp_error,.read_rsp_data,
    .finish_valid,.finish_ready,.done_valid,.done_ready,.done_error
  );
  always @(posedge clk)if(rst_n)begin
    if(cfg_valid && cfg_ready)configs++;
    if(row_valid && row_ready)begin
      if(row_head!==5'(expected_head) || row_query!==11'(expected_query) ||
         {row_value_exponent,row_data}!==expected_row || row_error!==expected_row_error)
        $fatal(1,"FORK_ROW_METADATA_OR_DATA");
      captures++;
    end
    if(response_valid && response_ready)host_transfers++;
    if(source_valid && source_ready)source_transfers++;
  end
  task automatic descriptor(input int op,head,query,count,input bit capture,input logic [2055:0] value);
    logic [191:0] bits;
    bits='0;bits[4:0]=5'(head);bits[15:5]=11'(query);bits[169:162]=value[2055:2048];
    bits[170]=capture;bits[179:171]=descriptor_zero_exponent;
    @(negedge clk);command_opcode=3'(op);command_tag=32'hcf000000+32'(query*64+head);
    command_valid=1;command_ready=0;
    repeat(2)@(negedge clk);
    command_ready=1;@(negedge clk);command_valid=0;command_ready=0;
    for(int i=0;i<count;i++)begin
      payload_valid=1;payload_ready=0;payload_last=i==count-1;
      payload_data=i<3 ? bits[i*64+:64] : 64'hfeed;
      repeat(2)@(negedge clk);
      payload_ready=1;@(negedge clk);payload_ready=0;
    end
    payload_valid=0;payload_last=0;payload_data='1;
  endtask
  task automatic respond(input bit capture,input bit error,input int response_op,query,head,input logic [2055:0] value);
    int before_rows,before_cfg;
    before_rows=captures;before_cfg=configs;
    expected_head=head;expected_query=query;expected_row=value;expected_row_error=error || response_op!=5;
    source_opcode=3'(response_op);source_tag=command_tag;source_error=error;
    source_values=value[2047:0];source_valid=1;response_ready=0;
    if(capture)begin
      for(int i=0;i<512;i++)begin
        @(negedge clk);
        if(captures==before_rows+1)break;
        if(response_valid || source_ready)$fatal(1,"FORK_HOST_BEFORE_CAPTURE");
      end
      if(captures!=before_rows+1)$fatal(1,"FORK_CAPTURE_TIMEOUT");
    end else begin
      repeat(3)@(negedge clk);
      if(captures!=before_rows || configs!=before_cfg)$fatal(1,"FORK_FALSE_CAPTURE");
      bypasses++;
    end
    repeat(8)begin
      @(negedge clk);
      if(!response_valid || source_ready || response_error!==error || response_opcode!==3'(response_op) ||
         response_tag!==command_tag || response_values!==value[2047:0] || captures!=before_rows+int'(capture))
        $fatal(1,"FORK_HELD_RESPONSE_OR_DUPLICATE");
    end
    response_ready=1;
    @(posedge clk);if(!source_ready)$fatal(1,"FORK_SOURCE_NOT_DRAINED");
    @(negedge clk);source_valid=0;response_ready=0;
    #1; // Allow continuous output assignments to settle after source deassertion.
    if(row_valid || response_valid)$fatal(1,"FORK_STALE_RESPONSE");
  endtask
  task automatic send_head(input int frame,head,query);
    descriptor(5,head,query,3,1,rows[frame*32+head]);
    respond(1,0,5,query,head,rows[frame*32+head]);
  endtask
  task automatic wait_context(input int frame,query,first_head);
    for(int i=0;i<10000;i++)begin
      @(negedge clk);
      if(done_valid)$fatal(1,"FORK_FALSE_FRAME_ERROR");
      if(context_valid)begin
        if(context_exponent!==units[frame] || context_query!==11'(query) ||
           context_tag!==32'hcf000000+32'(query*64+first_head) || !frame_open)
          $fatal(1,"FORK_CONTEXT_METADATA");
        return;
      end
    end
    $fatal(1,"FORK_NO_CONTEXT");
  endtask
  task automatic drain_terminal(input bit error);
    for(int i=0;i<10000;i++)begin @(negedge clk);if(done_valid)break;end
    if(!done_valid || done_error!==error)$fatal(1,"FORK_TERMINAL");
    done_ready=1;@(negedge clk);done_ready=0;
    if(frame_open || !cfg_ready)$fatal(1,"FORK_FRAME_NOT_CLOSED");
  endtask
  task automatic reset_all;
    @(negedge clk);rst_n=0;source_valid=0;response_ready=0;command_valid=0;payload_valid=0;
    finish_valid=0;done_ready=0;read_req_valid=0;read_rsp_ready=0;
    repeat(3)begin
      @(negedge clk);
      if(cfg_valid || row_valid || response_valid || source_ready || frame_open || projection_active || lease_active)
        $fatal(1,"FORK_RESET_LEAK");
    end
    rst_n=1;@(negedge clk);
  endtask
  initial begin
    int count_before;
    if(!$value$plusargs("ROWS=%s",rows_file)||!$value$plusargs("CODES=%s",codes_file)||
       !$value$plusargs("UNITS=%s",units_file)||!$value$plusargs("FRAMES=%d",frames)||frames<1||frames>3)$fatal(1,"FORK_ARGUMENTS");
    $readmemh(rows_file,rows,0,frames*32-1);$readmemh(codes_file,codes,0,frames*256-1);$readmemh(units_file,units,0,frames-1);
    reset_all();
    for(int frame=0;frame<frames;frame++)begin
      count_before=configs;
      for(int i=0;i<32;i++)begin
        send_head(frame,(17*i+31)%32,frame);
        if(i==3)begin
          descriptor(5,8,999,3,0,rows[8]);respond(0,0,5,999,8,rows[8]);
        end
      end
      wait_context(frame,frame,31);
      if(configs!=count_before+1)$fatal(1,"FORK_CONFIG_NOT_ONCE");
      for(int word=0;word<256;word++)begin
        read_req_word=10'(word);read_req_valid=1;
        @(posedge clk);if(!read_req_ready)$fatal(1,"FORK_READ_NOT_READY");
        @(negedge clk);read_req_valid=0;
        if(!read_rsp_valid || read_rsp_error || read_rsp_data!==codes[frame*256+word])$fatal(1,"FORK_CONTEXT_BYTES word=%0d",word);
        read_rsp_ready=1;@(negedge clk);read_rsp_ready=0;words_checked++;
      end
      finish_valid=1;@(posedge clk);if(!finish_ready)$fatal(1,"FORK_FINISH_NOT_READY");
      @(negedge clk);finish_valid=0;drain_terminal(0);
    end
    // The first captured descriptor owns the zero unit for the entire frame.
    descriptor_zero_exponent=-9'sd9;
    for(int h=0;h<32;h++)begin
      descriptor(5,h,130,3,1,2056'b0);respond(1,0,5,130,h,2056'b0);
      descriptor_zero_exponent=9'sd18;
    end
    for(int i=0;i<10000;i++)begin @(negedge clk);if(context_valid)break;end
    if(!context_valid || context_exponent!==-9'sd9 || context_query!==11'd130 ||
       context_tag!==32'hcf002080)$fatal(1,"FORK_ZERO_UNIT_NOT_CAPTURED");
    read_req_word=0;read_req_valid=1;@(posedge clk);if(!read_req_ready)$fatal(1,"FORK_ZERO_READ");
    @(negedge clk);read_req_valid=0;
    if(!read_rsp_valid || read_rsp_error || read_rsp_data!==64'd0)$fatal(1,"FORK_ZERO_DATA");
    read_rsp_ready=1;@(negedge clk);read_rsp_ready=0;
    finish_valid=1;@(posedge clk);if(!finish_ready)$fatal(1,"FORK_ZERO_FINISH");
    @(negedge clk);finish_valid=0;drain_terminal(0);descriptor_zero_exponent=0;
    descriptor(5,1,100,2,1,rows[1]);respond(0,1,5,100,1,rows[1]);
    descriptor(5,2,100,4,1,rows[2]);respond(0,1,5,100,2,rows[2]);
    descriptor(6,3,100,5,1,rows[3]);respond(0,0,6,100,3,rows[3]);
    descriptor(7,4,100,26,1,rows[4]);respond(0,0,7,100,4,rows[4]);
    descriptor(1,5,100,9,1,rows[5]);
    if(!projection_active)$fatal(1,"FORK_PROJECTION_NOT_ACTIVE");
    respond(0,0,1,100,5,rows[5]);if(projection_active)$fatal(1,"FORK_PROJECTION_NOT_CLOSED");
    descriptor(5,0,101,3,1,rows[0]);respond(1,1,5,101,0,rows[0]);drain_terminal(1);
    send_head(0,0,102);descriptor(5,1,103,3,1,rows[1]);respond(1,0,5,103,1,rows[1]);drain_terminal(1);
    descriptor(5,0,104,3,1,rows[0]);respond(1,0,4,104,0,rows[0]);drain_terminal(1);
    // Cancel once before row acceptance and once after acceptance while host-held.
    for(int phase=0;phase<2;phase++)begin
      descriptor(5,0,110+phase,3,1,rows[0]);expected_head=0;expected_query=110+phase;expected_row=rows[0];expected_row_error=0;
      source_valid=1;source_opcode=5;source_tag=command_tag;source_values=rows[0][2047:0];source_error=0;
      count_before=captures;
      if(phase==0)begin repeat(20)@(negedge clk);if(captures!=count_before || !lease_active)$fatal(1,"FORK_RESET_PACK_SETUP");end
      else begin
        for(int i=0;i<512;i++)begin @(negedge clk);if(captures==count_before+1)break;end
        if(captures!=count_before+1 || !response_valid)$fatal(1,"FORK_RESET_HELD_SETUP");
      end
      reset_all();
    end
    for(int h=0;h<32;h++)send_head(0,h,120);wait_context(0,120,0);
    finish_valid=1;@(posedge clk);if(!finish_ready)$fatal(1,"FORK_RECOVERY_FINISH");
    @(negedge clk);finish_valid=0;drain_terminal(0);
    if(host_transfers!=source_transfers)$fatal(1,"FORK_RESPONSE_COUNT");
    $display("CONTEXT_RESPONSE_FORK_PASS frames=%0d code_words=%0d bypasses=%0d source_host_transfers=%0d resets=2 zero_unit_frame=1",frames,words_checked,bypasses,host_transfers);
    $finish;
  end
  initial begin #6000000;$fatal(1,"FORK_TIMEOUT");end
endmodule
