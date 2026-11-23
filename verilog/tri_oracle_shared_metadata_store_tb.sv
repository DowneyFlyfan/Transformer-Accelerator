`timescale 1ns/1ps
module tri_oracle_shared_metadata_store_tb;
  logic clk=0,rst_n=0,ff_idle=1;
  always #5 clk=~clk;
  logic acquire_valid=0,acquire_ready,release_valid=0,release_ready,context_owned;
  logic [1:0] ff_ce_n=2'b11,ff_we_n=2'b11;
  logic [17:0] ff_address=0;
  logic [127:0] ff_write_data=0,ff_read_data;
  logic req_valid=0,req_write=0,req_ready;
  logic [9:0] req_word=0;
  logic [63:0] req_data=0,rsp_data;
  logic rsp_valid,rsp_error,rsp_ready=0;
  int context_reads=0,context_writes=0;
  int vendor_cell_count=0;
  bit lower_cell_seen=0,upper_cell_seen=0;
  tri_oracle_shared_metadata_store dut(.*);

  function automatic logic [63:0] initial_word(input int word_index);
    return 64'h13a57bde02468acf^(64'(word_index)<<21)^64'(word_index*17);
  endfunction
  function automatic logic [63:0] context_word(input int word_index);
    return 64'hd65cb0931f4a8e27^(64'(word_index)<<33)^64'(word_index*131);
  endfunction
  task automatic step;
    @(posedge clk);#2;
  endtask
  task automatic ff_access(input int word_index,input bit write_enable,input logic [63:0] value);
    int bank;bank=word_index/512;
    @(negedge clk);ff_ce_n=2'b11;ff_we_n=2'b11;
    ff_address[bank*9+:9]=9'(word_index%512);ff_write_data[bank*64+:64]=value;
    ff_ce_n[bank]=0;ff_we_n[bank]=!write_enable;step();
    if(!write_enable && ff_read_data[bank*64+:64]!==value)
      $fatal(1,"SHARED_METADATA_FF_WORD word=%0d got=%016h expected=%016h",word_index,ff_read_data[bank*64+:64],value);
    @(negedge clk);ff_ce_n=2'b11;ff_we_n=2'b11;
  endtask
  task automatic acquire;
    @(negedge clk);acquire_valid=1;
    if(!acquire_ready)$fatal(1,"SHARED_METADATA_ACQUIRE_NOT_READY");
    step();if(!context_owned)$fatal(1,"SHARED_METADATA_ACQUIRE_LOST");
    @(negedge clk);acquire_valid=0;
  endtask
  task automatic request(input int word_index,input bit write_enable,input logic [63:0] value,input bit bad);
    @(negedge clk);req_valid=1;req_write=write_enable;req_word=10'(word_index);req_data=value;
    if(!req_ready)$fatal(1,"SHARED_METADATA_REQUEST_NOT_READY");
    step();if(!rsp_valid || rsp_error!==bad || (!bad && !write_enable && rsp_data!==value) || ((bad || write_enable) && rsp_data!==64'b0))
      $fatal(1,"SHARED_METADATA_RESPONSE word=%0d data=%016h",word_index,rsp_data);
    @(negedge clk);req_valid=0;
    repeat(2)begin
      step();if(!rsp_valid || rsp_error!==bad || req_ready || !context_owned)
        $fatal(1,"SHARED_METADATA_RESPONSE_NOT_HELD");
      if(!bad && !write_enable && rsp_data!==value)$fatal(1,"SHARED_METADATA_HELD_DATA");
    end
    @(negedge clk);rsp_ready=1;step();
    @(negedge clk);rsp_ready=0;
    if(write_enable && !bad)context_writes++;
    if(!write_enable && !bad)context_reads++;
  endtask

  initial begin
    repeat(3)step();
    if(acquire_ready || req_ready || rsp_valid || context_owned || ff_read_data!==0)
      $fatal(1,"SHARED_METADATA_RESET_OUTPUTS");
    @(negedge clk);rst_n=1;
    for(int i=0;i<1024;i++)ff_access(i,1,initial_word(i));
    for(int i=0;i<1024;i++)ff_access(i,0,initial_word(i));
    // Acquiring requires the predictor to finish and both memory enables idle.
    @(negedge clk);ff_idle=0;acquire_valid=1;
    repeat(3)begin step();if(acquire_ready || context_owned)$fatal(1,"SHARED_METADATA_STOLE_BUSY_PREDICTOR");end
    @(negedge clk);ff_idle=1;ff_ce_n=2'b10;ff_we_n=2'b11;
    repeat(3)begin step();if(acquire_ready || context_owned)$fatal(1,"SHARED_METADATA_STOLE_ACTIVE_PORT");end
    @(negedge clk);ff_ce_n=2'b11;
    step();if(!context_owned)$fatal(1,"SHARED_METADATA_WAITED_ACQUIRE_MISSING");
    @(negedge clk);acquire_valid=0;
    // Hostile inactive predictor traffic cannot corrupt the owned context.
    ff_idle=0;ff_ce_n=2'b00;ff_we_n=2'b00;ff_address={9'd388,9'd17};ff_write_data='1;
    for(int i=0;i<832;i++)begin
      request(i,1,context_word(i),0);
      if(ff_read_data!==128'b0)$fatal(1,"SHARED_METADATA_INACTIVE_PREDICTOR_DATA");
    end
    request(832,1,64'hffffffffffffffff,1);
    request(1023,0,64'b0,1);
    for(int i=0;i<832;i++)request(i,0,context_word(i),0);
    @(negedge clk);ff_ce_n=2'b11;ff_we_n=2'b11;ff_idle=1;
    // Release must wait for the final response and beat a new request.
    @(negedge clk);req_valid=1;req_write=0;req_word=10'd511;step();
    @(negedge clk);req_valid=0;release_valid=1;
    repeat(3)begin step();if(release_ready || !rsp_valid || !context_owned)$fatal(1,"SHARED_METADATA_EARLY_RELEASE");end
    @(negedge clk);rsp_ready=1;step();
    @(negedge clk);rsp_ready=0;req_valid=1;req_word=10'd7;
    if(req_ready || !release_ready)$fatal(1,"SHARED_METADATA_RELEASE_PRIORITY");
    step();if(context_owned || rsp_valid)$fatal(1,"SHARED_METADATA_RELEASE_OR_GHOST_REQUEST");
    @(negedge clk);release_valid=0;req_valid=0;
    for(int i=0;i<1024;i++)ff_access(i,0,i<832?context_word(i):initial_word(i));
    // Rebuilding predictor flags uses precisely the same two physical memories.
    for(int i=0;i<1024;i++)ff_access(i,1,initial_word(i)^64'h1234);
    for(int i=0;i<1024;i++)ff_access(i,0,initial_word(i)^64'h1234);
    acquire();request(0,0,initial_word(0)^64'h1234,0);
    @(negedge clk);req_valid=1;req_write=0;req_word=10'd512;step();
    @(negedge clk);req_valid=0;rst_n=0;step();
    if(context_owned || rsp_valid || req_ready || acquire_ready || ff_read_data!==0)
      $fatal(1,"SHARED_METADATA_RESET_PENDING_RESPONSE");
    if(vendor_cell_count!=2 || !lower_cell_seen || !upper_cell_seen)$fatal(1,"SHARED_METADATA_VENDOR_CELL_COUNT");
    $display("SHARED_METADATA_STORE_PASS ff_words=1024 context_words=832 writes=%0d reads=%0d invalid_addresses=2 ownership=1 backpressure=1 rebuild=1 reset=1",context_writes,context_reads);
    $finish;
  end
  initial begin #1000000;$fatal(1,"SHARED_METADATA_UNIT_TIMEOUT");end
endmodule
