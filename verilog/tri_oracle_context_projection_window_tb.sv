`timescale 1ns/1ps
// Catches local/external source confusion, wrong burst strides, dropped held
// responses, partial invalid bursts and release before the consumer drains.
module tri_oracle_context_projection_window_tb;
  localparam logic [63:0] BASE=64'h10000;
  localparam logic [511:0] EXTERNAL_DATA={8{64'hfedcba9876543210}};
  logic clk=0,rst_n=0;always #5 clk=~clk;
  logic cfg_valid=0,cfg_ready;
  logic [31:0] cfg_tag=0,context_tag;
  logic [10:0] cfg_query=0,context_query;
  logic signed [8:0] context_exponent;
  logic row_valid=0,row_ready;
  logic [4:0] row_head=0;
  logic [2047:0] row_data=0;
  logic signed [7:0] row_value_exponent=0;
  logic context_valid,lease_active,metadata_block,metadata_needs_rebuild;
  logic [767:0] metadata_read_data;
  logic req_valid=0,req_wide=0,req_ready,rsp_valid,rsp_ready=0,rsp_last,rsp_error;
  logic [63:0] req_address=0;
  logic [5:0] req_length=0;
  logic [511:0] rsp_data;
  logic external_req_valid,external_req_ready,external_req_wide,external_rsp_ready;
  logic [63:0] external_req_address;
  logic [5:0] external_req_length;
  logic external_active=0;
  int external_remaining=0,external_requests=0;
  logic word_req_valid,word_req_ready,word_rsp_valid,word_rsp_ready,word_rsp_error;
  logic [9:0] word_req_word;
  logic [63:0] word_rsp_data;
  logic finish_valid=0,finish_ready,memory_finish_valid,memory_finish_ready,client_idle=1,window_idle;
  logic done_valid,done_ready=0,done_error,inject_word_error=0;
  logic [2055:0] rows[96];logic [63:0] codes[768];logic [8:0] units[3];
  string rows_file,codes_file,units_file;
  int frames,checked_words=0,word_requests=0,bursts=0,invalids=0;
  assign external_req_ready=rst_n && !external_active;

  tri_oracle_context_handoff controller (
    .clk,.rst_n,.cfg_valid,.cfg_ready,.cfg_tag,.cfg_query,.cfg_zero_exponent(9'sd0),
    .row_valid,.row_ready,.row_error(1'b0),.row_query(cfg_query),.row_head,.row_data,.row_value_exponent,
    .metadata_idle(1'b1),.metadata_block,.metadata_needs_rebuild,.metadata_rebuilt(1'b0),.lease_active,
    .metadata_ce_n(6'b111111),.metadata_we_n(6'b111111),.metadata_address(54'b0),
    .metadata_write_data(768'b0),.metadata_write_mask({768{1'b1}}),.metadata_read_data,
    .context_valid,.context_tag,.context_query,.context_exponent,
    .read_req_valid(word_req_valid),.read_req_ready(word_req_ready),.read_req_word(word_req_word),
    .read_rsp_valid(word_rsp_valid),.read_rsp_ready(word_rsp_ready),.read_rsp_error(word_rsp_error),.read_rsp_data(word_rsp_data),
    .finish_valid(memory_finish_valid),.finish_ready(memory_finish_ready),.done_valid,.done_ready,.done_error
  );
  tri_oracle_context_projection_window dut (
    .clk,.rst_n,.projection_enabled(context_valid),.client_idle,
    .req_valid,.req_ready,.req_wide,.req_address,.req_length,
    .rsp_valid,.rsp_ready,.rsp_last,.rsp_error,.rsp_data,
    .external_req_valid,.external_req_ready,.external_req_wide,.external_req_address,.external_req_length,
    .external_rsp_valid(external_active),.external_rsp_last(external_remaining==1),.external_rsp_error(1'b0),
    .external_rsp_ready,.external_rsp_data(EXTERNAL_DATA),
    .word_req_valid,.word_req_ready,.word_req_word,.word_rsp_valid,.word_rsp_ready,
    .word_rsp_error(word_rsp_error || inject_word_error),.word_rsp_data,
    .finish_valid,.finish_ready,.memory_finish_valid,.memory_finish_ready,.idle(window_idle)
  );
  always @(posedge clk)begin
    if(!rst_n)begin external_active<=0;external_remaining<=0;end
    else begin
      if(word_req_valid && word_req_ready)word_requests++;
      if(external_req_valid && context_valid && !external_req_wide && external_req_address[63:12]==52'h10)
        $fatal(1,"WINDOW_LOCAL_READ_LEAK");
      if(external_req_valid && external_req_ready)begin
        if(external_req_address!==req_address || external_req_length!==req_length || external_req_wide!==req_wide)
          $fatal(1,"WINDOW_EXTERNAL_REQUEST_FIELDS");
        external_active<=1;external_remaining<=int'(external_req_length);external_requests++;
      end else if(external_active && external_rsp_ready)begin
        external_remaining<=external_remaining-1;external_active<=external_remaining!=1;
      end
      if(memory_finish_valid && memory_finish_ready && (req_valid && req_ready))
        $fatal(1,"WINDOW_FINISH_ACCEPTED_NEW_READ");
    end
  end
  task automatic fill_frame(input int frame,query);
    @(negedge clk);cfg_tag=32'hc8200000+32'(query);cfg_query=11'(query);cfg_valid=1;
    @(posedge clk);if(!cfg_ready)$fatal(1,"WINDOW_CONFIG_NOT_READY");
    @(negedge clk);cfg_valid=0;
    for(int i=0;i<32;i++)begin
      row_head=5'((17*i+31)%32);{row_value_exponent,row_data}=rows[frame*32+int'(row_head)];row_valid=1;
      for(int wait_cycles=0;wait_cycles<512;wait_cycles++)begin
        @(posedge clk);if(row_ready)break;
      end
      if(!row_ready)$fatal(1,"WINDOW_ROW_TIMEOUT");
      @(negedge clk);row_valid=0;
    end
    for(int i=0;i<10000;i++)begin @(negedge clk);if(context_valid)break;end
    if(!context_valid || !lease_active || context_exponent!==units[frame] || context_query!==11'(query) ||
       context_tag!==32'hc8200000+32'(query))$fatal(1,"WINDOW_CONTEXT_METADATA");
  endtask
  task automatic request(input logic [63:0] address,input int length,input bit wide);
    @(negedge clk);req_address=address;req_length=6'(length);req_wide=wide;req_valid=1;
    for(int i=0;i<100;i++)begin @(posedge clk);if(req_ready)break;end
    if(!req_ready)$fatal(1,"WINDOW_REQUEST_TIMEOUT");
    @(negedge clk);req_valid=0;
  endtask
  task automatic wait_response;
    for(int i=0;i<100;i++)begin
      @(negedge clk);
      if(rsp_valid)return;
      if(!lease_active || done_valid)$fatal(1,"WINDOW_RELEASED_DURING_READ");
    end
    $fatal(1,"WINDOW_RESPONSE_TIMEOUT");
  endtask
  task automatic local_burst(input int frame,start,length);
    request(BASE+64'(start*8),length,0);
    for(int beat=0;beat<length;beat++)begin
      wait_response();
      repeat(3)begin
        if(!rsp_valid || rsp_error || rsp_last!==(beat==length-1) || rsp_data!=={448'b0,codes[frame*256+start+beat]} ||
           finish_ready || !lease_active)$fatal(1,"WINDOW_LOCAL_BURST_DATA word=%0d",start+beat);
        @(negedge clk);
      end
      rsp_ready=1;@(negedge clk);rsp_ready=0;checked_words++;
    end
    bursts++;
    if(finish_ready || memory_finish_valid || !lease_active)$fatal(1,"WINDOW_FINISH_ACTIVE_CONSUMER");
  endtask
  task automatic invalid_burst(input logic [63:0] address,input int length);
    int before_words;
    before_words=word_requests;request(address,length,0);wait_response();
    repeat(3)begin
      if(!rsp_valid || !rsp_error || !rsp_last || rsp_data!==0 || word_requests!=before_words || finish_ready)
        $fatal(1,"WINDOW_INVALID_BURST_NOT_ATOMIC");
      @(negedge clk);
    end
    rsp_ready=1;@(negedge clk);rsp_ready=0;invalids++;
  endtask
  task automatic external_burst(input logic [63:0] address,input int length,input bit wide);
    int before_words,before_external;
    before_words=word_requests;before_external=external_requests;
    request(address,length,wide);
    client_idle=1;
    for(int beat=0;beat<length;beat++)begin
      wait_response();
      repeat(3)begin
        if(!rsp_valid || rsp_error || rsp_last!==(beat==length-1) || rsp_data!==EXTERNAL_DATA ||
           word_requests!=before_words || external_requests!=before_external+1 || finish_ready || !lease_active)
          $fatal(1,"WINDOW_EXTERNAL_RESPONSE_OR_RELEASE");
        @(negedge clk);
      end
      rsp_ready=1;@(negedge clk);rsp_ready=0;
    end
    client_idle=0;
  endtask
  task automatic finish_frame;
    @(negedge clk);client_idle=1;finish_valid=1;req_valid=1;req_address=BASE;req_length=1;req_wide=0;
    #1;if(!finish_ready || req_ready || word_req_valid)$fatal(1,"WINDOW_FINISH_PRIORITY");
    @(negedge clk);req_valid=0;finish_valid=0;
    for(int i=0;i<20;i++)begin @(negedge clk);if(done_valid)break;end
    if(!done_valid || done_error || lease_active || !metadata_needs_rebuild)$fatal(1,"WINDOW_TERMINAL");
    repeat(3)@(negedge clk);done_ready=1;@(negedge clk);done_ready=0;
    if(!cfg_ready || done_valid)$fatal(1,"WINDOW_TERMINAL_DRAIN");
  endtask
  task automatic reset_all;
    @(negedge clk);rst_n=0;cfg_valid=0;row_valid=0;req_valid=0;rsp_ready=0;
    finish_valid=0;done_ready=0;client_idle=1;inject_word_error=0;
    repeat(3)begin
      @(negedge clk);if(rsp_valid || word_req_valid || lease_active || done_valid || finish_ready)$fatal(1,"WINDOW_RESET_LEAK");
    end
    rst_n=1;@(negedge clk);
  endtask
  initial begin
    int length,before_words;
    if(!$value$plusargs("ROWS=%s",rows_file)||!$value$plusargs("CODES=%s",codes_file)||
       !$value$plusargs("UNITS=%s",units_file)||!$value$plusargs("FRAMES=%d",frames)||frames<1||frames>3)$fatal(1,"WINDOW_ARGUMENTS");
    $readmemh(rows_file,rows,0,frames*32-1);$readmemh(codes_file,codes,0,frames*256-1);$readmemh(units_file,units,0,frames-1);
    reset_all();
    for(int frame=0;frame<frames;frame++)begin
      fill_frame(frame,frame);client_idle=0;finish_valid=1;
      #1;if(finish_ready || memory_finish_valid)$fatal(1,"WINDOW_FINISH_ACTIVE_CONSUMER");
      for(int word=0;word<256;word+=length)begin
        length=(word%16)+1;if(length>256-word)length=256-word;
        local_burst(frame,word,length);
      end
      invalid_burst(BASE,0);invalid_burst(BASE,17);invalid_burst(BASE,32);invalid_burst(BASE,63);
      invalid_burst(BASE+2048,1);invalid_burst(BASE+4088,1);invalid_burst(BASE+2040,2);invalid_burst(BASE+1,1);
      external_burst(64'h20000000,3,0);external_burst(BASE,2,1);
      before_words=word_requests;inject_word_error=1;request(BASE+32,4,0);wait_response();
      if(!rsp_error || !rsp_last || rsp_data!==0)$fatal(1,"WINDOW_WORD_ERROR_NOT_FORWARDED");
      rsp_ready=1;@(negedge clk);rsp_ready=0;inject_word_error=0;
      repeat(3)@(negedge clk);
      if(word_requests!=before_words+1 || rsp_valid)$fatal(1,"WINDOW_WORD_ERROR_NOT_TERMINAL");
      finish_valid=0;finish_frame();
    end
    fill_frame(0,100);client_idle=0;request(BASE,3,0);wait_response();
    if(rsp_data!=={448'b0,codes[0]})$fatal(1,"WINDOW_RESET_SETUP");
    reset_all();fill_frame(0,101);client_idle=0;finish_valid=1;local_burst(0,255,1);
    finish_valid=0;finish_frame();
    $display("CONTEXT_PROJECTION_WINDOW_PASS frames=%0d code_words=%0d recovery_words=1 bursts=%0d invalid_bursts=%0d external_bursts=%0d word_error_bursts=%0d reset_phases=1",frames,checked_words-1,bursts,invalids,external_requests,frames);
    $finish;
  end
  initial begin #6000000;$fatal(1,"WINDOW_TIMEOUT");end
endmodule
