`timescale 1ns/1ps
// Catches local/external source confusion, wrong burst strides, dropped held
// responses, partial invalid bursts and release before the consumer drains.
module tri_oracle_serial_context_memory_tb;
  localparam logic [63:0] BASE=64'h10000;
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
  int external_requests=0;
  logic word_req_valid,word_req_ready,word_rsp_valid,word_rsp_ready,word_rsp_error;
  logic [9:0] word_req_word;
  logic [63:0] word_rsp_data;
  logic finish_valid,finish_ready,memory_finish_valid,memory_finish_ready,client_idle=1,window_idle;
  logic done_valid,done_ready,done_error,inject_word_error=0;
  logic [2055:0] rows[96];logic [63:0] codes[768];logic [8:0] units[3];
  string rows_file,codes_file,units_file;
  int frames,checked_words=0,word_requests=0,bursts=0;
  logic host_rx_valid=0,host_rx_ready,host_rx_is_payload=0,host_rx_payload_last=0;
  logic [15:0] host_rx_data=0;
  logic context_control_valid,context_control_ready,context_control_finish;
  logic host_tx_valid,host_tx_last,host_tx_ready=0;
  logic [15:0] host_tx_data;
  logic release_waiting=0;
  int host_words=0,release_count=0,completion_count=0;
  tri_oracle_host_context_rx receiver (
    .clk,.rst_n,.rx_valid(host_rx_valid),.rx_ready(host_rx_ready),.rx_is_payload(host_rx_is_payload),
    .rx_payload_last(host_rx_payload_last),.rx_data(host_rx_data),.forward_valid(),.forward_ready(1'b1),
    .control_valid(),.control_ready(1'b1),.control_action(),
    .context_control_valid,.context_control_ready,.context_control_finish,
    .operand_valid(),.operand_ready(1'b0),.residual_q32(),.projection_shift(),
    .gamma_valid(),.gamma_ready(1'b0),.gamma_data(),.stats_valid(),.stats_last(),.stats_ready(1'b0),.stats_data(),
    .replay_valid(),.replay_last(),.replay_ready(1'b0),.replay_data(),.replay_gamma()
  );
  tri_oracle_host_context_link host_link (
    .clk,.rst_n,.control_valid(context_control_valid),.control_ready(context_control_ready),
    .control_finish(context_control_finish),.context_valid,.lease_active,.metadata_needs_rebuild,
    .context_tag,.context_query,.context_exponent,.finish_valid,.finish_ready,.done_valid,.done_ready,.done_error,
    .source_valid(1'b0),.source_last(1'b0),.source_data(16'b0),.source_ready(),
    .tx_valid(host_tx_valid),.tx_last(host_tx_last),.tx_data(host_tx_data),.tx_ready(host_tx_ready)
  );
  always @(posedge clk)if(rst_n)begin
    if(release_waiting && lease_active && host_tx_valid)$fatal(1,"SERIAL_CONTEXT_EARLY_FINISH_REPLY");
    if(memory_finish_valid && memory_finish_ready)release_count++;
    if(done_valid && done_ready)completion_count++;
  end
  assign external_req_ready=1'b0;

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
    .external_rsp_valid(1'b0),.external_rsp_last(1'b0),.external_rsp_error(1'b0),
    .external_rsp_ready,.external_rsp_data(512'b0),
    .word_req_valid,.word_req_ready,.word_req_word,.word_rsp_valid,.word_rsp_ready,
    .word_rsp_error(word_rsp_error || inject_word_error),.word_rsp_data,
    .finish_valid,.finish_ready,.memory_finish_valid,.memory_finish_ready,.idle(window_idle)
  );
  always @(posedge clk)if(rst_n)begin
    if(word_req_valid && word_req_ready)word_requests++;
    if(external_req_valid)$fatal(1,"SERIAL_CONTEXT_LOCAL_READ_LEAK");
    if(memory_finish_valid && memory_finish_ready && (req_valid && req_ready))
      $fatal(1,"WINDOW_FINISH_ACCEPTED_NEW_READ");
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
  task automatic host_control(input bit close_frame);
    @(negedge clk);host_rx_valid=1;host_rx_is_payload=0;host_rx_payload_last=1;
    host_rx_data=close_frame ? 16'ha686 : 16'ha685;
    for(int n=0;n<100;n++)begin @(posedge clk);if(host_rx_ready)break;end
    if(!host_rx_ready)$fatal(1,"SERIAL_CONTEXT_HEADER_TIMEOUT");
    @(negedge clk);host_rx_valid=0;
  endtask
  task automatic host_word(input logic [15:0] expected,input bit last);
    for(int n=0;n<100;n++)begin @(negedge clk);if(host_tx_valid)break;end
    repeat(3)begin
      @(posedge clk);
      if(!host_tx_valid || host_tx_data!==expected || host_tx_last!==last)
        $fatal(1,"SERIAL_CONTEXT_REPLY_WORD expected=%h actual=%h",expected,host_tx_data);
      @(negedge clk);
    end
    host_tx_ready=1;@(posedge clk);@(negedge clk);host_tx_ready=0;host_words++;
  endtask
  task automatic host_reply(input logic [27:0] status,input logic [31:0] tag,input bit action);
    host_word(16'ha687,0);host_word(status[15:0],0);host_word({4'b0,status[27:16]},0);
    host_word(tag[15:0],0);host_word(tag[31:16],0);host_word({15'b0,action},1);
  endtask
  initial begin
    if(!$value$plusargs("ROWS=%s",rows_file)||!$value$plusargs("CODES=%s",codes_file)||
       !$value$plusargs("UNITS=%s",units_file)||!$value$plusargs("FRAMES=%d",frames)||frames<1||frames>3)
      $fatal(1,"SERIAL_CONTEXT_ARGUMENTS");
    $readmemh(rows_file,rows,0,frames*32-1);$readmemh(codes_file,codes,0,frames*256-1);$readmemh(units_file,units,0,frames-1);
    repeat(3)@(negedge clk);rst_n=1;@(negedge clk);
    for(int frame=0;frame<frames;frame++)begin
      fill_frame(frame,13+frame);
      host_control(0);
      host_reply({1'b0,1'b0,1'b0,1'b0,1'b0,1'b1,1'b1,1'b1,11'(13+frame),units[frame]},32'hc8200000+32'(13+frame),0);
      client_idle=0;host_control(1);release_waiting=1;
      for(int start=0;start<256;start+=16)local_burst(frame,start,16);
      // Command completion alone must not release a final unconsumed bus response.
      request(BASE,1,0);wait_response();client_idle=1;
      repeat(3)begin
        if(finish_ready || memory_finish_valid || !lease_active || !rsp_valid || rsp_error || !rsp_last ||
           rsp_data!=={448'b0,codes[frame*256]})$fatal(1,"SERIAL_CONTEXT_FINAL_HELD_READ");
        @(negedge clk);
      end
      rsp_ready=1;@(negedge clk);rsp_ready=0;checked_words++;
      host_reply({1'b0,1'b1,1'b0,1'b0,1'b1,1'b1,1'b0,1'b0,11'(13+frame),units[frame]},32'hc8200000+32'(13+frame),1);
      release_waiting=0;
      if(lease_active || context_valid || done_valid || !cfg_ready || !window_idle || !metadata_needs_rebuild)
        $fatal(1,"SERIAL_CONTEXT_POST_RELEASE");
    end
    if(checked_words!=frames*257 || host_words!=frames*12 || release_count!=frames || completion_count!=frames || external_requests!=0)
      $fatal(1,"SERIAL_CONTEXT_INVENTORY");
    $display("SERIAL_CONTEXT_MEMORY_PASS frames=%0d code_words=%0d host_words=%0d releases=%0d completions=%0d",frames,checked_words,host_words,release_count,completion_count);
    $finish;
  end
  initial begin #2000000;$fatal(1,"SERIAL_CONTEXT_TIMEOUT");end
endmodule
