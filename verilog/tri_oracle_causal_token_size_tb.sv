`timescale 1ns/1ps
// Stateless reference: count original positions in each requested prefix.
// It does not reproduce the implementation's cursor or location table.
module tri_oracle_causal_token_size_tb;
  parameter int unsigned MAX_TOKENS=17;
  localparam int INDEX_W=MAX_TOKENS>1?$clog2(MAX_TOKENS):1;
  localparam int COUNT_W=$clog2(MAX_TOKENS+1);
  logic clk=0;
  always #5 clk=~clk;
  logic rst_n=0,frame_valid=0,map_valid=0,map_last=0;
  logic query_valid=0,out_ready=0;
  logic [INDEX_W-1:0] map_origin=0,query_position=0;
  wire frame_ready,map_ready,query_ready,out_valid,out_last,error;
  wire [INDEX_W-1:0] out_origin;
  wire [COUNT_W-1:0] out_count;
  int reference_origin[MAX_TOKENS];
  int length,rows=0,words=0,stalls=0;
  tri_oracle_causal_token_size #(.MAX_TOKENS(MAX_TOKENS)) dut(.*);
  task automatic start_frame;
    @(negedge clk);frame_valid=1;
    do @(posedge clk);while(!frame_ready);
    @(negedge clk);frame_valid=0;
  endtask
  task automatic map_word(input int origin,input bit last_word);
    @(negedge clk);map_valid=1;map_origin=INDEX_W'(origin);map_last=last_word;
    do @(posedge clk);while(!map_ready);
    @(negedge clk);map_valid=0;map_last=0;
  endtask
  task automatic load_frame(input int selected_length,input int pattern);
    int root;
    length=selected_length;
    start_frame();root=0;
    for(int i=0;i<length;i++) begin
      if(pattern==0 || (pattern==2 && i%5==0)) root=i;
      reference_origin[i]=root;
      if(i%4==1) repeat(2) @(negedge clk);
      map_word(root,i==length-1);
    end
    if(error) $fatal(1,"CAUSAL_VALID_MAP_REJECTED");
  endtask
  task automatic check_prefix(input int position);
    int expected_counts[MAX_TOKENS];
    int expected_origins[MAX_TOKENS];
    int count,received,cycles;
    bit held;
    logic [INDEX_W+COUNT_W:0] held_payload;
    for(int i=0;i<MAX_TOKENS;i++) expected_counts[i]=0;
    for(int token=0;token<=position;token++) expected_counts[reference_origin[token]]++;
    count=0;
    for(int origin=0;origin<length;origin++)
      if(expected_counts[origin]>0) begin expected_origins[count]=origin;count++;end
    @(negedge clk);query_valid=1;query_position=INDEX_W'(position);
    do @(posedge clk);while(!query_ready);
    @(negedge clk);query_valid=0;
    received=0;cycles=0;held=0;
    while(received<count) begin
      out_ready=(cycles%5!=0 && cycles%5!=1);
      @(posedge clk);
      if(error) $fatal(1,"CAUSAL_VALID_QUERY_REJECTED");
      if(held && (!out_valid || {out_origin,out_count,out_last}!==held_payload))
        $fatal(1,"CAUSAL_STALLED_WORD_CHANGED");
      if(out_valid && out_ready) begin
        if(out_origin!==INDEX_W'(expected_origins[received]) ||
           out_count!==COUNT_W'(expected_counts[expected_origins[received]]) ||
           out_last!==(received==count-1))
          $fatal(1,"CAUSAL_SIZE_WORD prefix=%0d word=%0d got=%0d:%0d:%0d expected=%0d:%0d:%0d",
                 position,received,out_origin,out_count,out_last,
                 expected_origins[received],expected_counts[expected_origins[received]],received==count-1);
        received++;words++;
      end
      held=out_valid && !out_ready;
      if(held) begin held_payload={out_origin,out_count,out_last};stalls++;end
      @(negedge clk);cycles++;
      if(cycles>10*MAX_TOKENS+100) $fatal(1,"CAUSAL_QUERY_TIMEOUT");
    end
    out_ready=0;rows++;
  endtask
  task automatic exercise_queries;
    if(length<=33) begin
      for(int q=0;q<length;q++) check_prefix(q);
      for(int q=length-1;q>=0;q--) check_prefix(q);
    end else begin
      for(int q=0;q<17;q++) check_prefix(q*(length-1)/16);
      for(int q=16;q>=0;q--) check_prefix(q*(length-1)/16);
    end
    check_prefix(length-1);
    check_prefix(0);
    check_prefix(length-1);
  endtask
  initial begin
    repeat(2) @(negedge clk);rst_n=1;
    load_frame(MAX_TOKENS,0);exercise_queries(); // Every token survives.
    load_frame(MAX_TOKENS,1);exercise_queries(); // Maximum representable count.
    load_frame(MAX_TOKENS,2);exercise_queries(); // Several origins share runs.
    load_frame((MAX_TOKENS+1)/2,2);exercise_queries(); // Frame reuse and shorter length.
    if(MAX_TOKENS>1) begin
      load_frame(1,0);
      @(negedge clk);query_valid=1;query_position=1;
      do @(posedge clk);while(!query_ready);
      @(negedge clk);query_valid=0;
      if(!error || out_valid) $fatal(1,"CAUSAL_OUT_OF_RANGE_QUERY_ACCEPTED");
      repeat(3) @(posedge clk);
      if(query_ready || map_ready || !error) $fatal(1,"CAUSAL_ERROR_NOT_HELD");
      start_frame();map_word(1,1); // Origin cannot be in the future.
      if(!error) $fatal(1,"CAUSAL_FUTURE_ORIGIN_ACCEPTED");
    end
    if(MAX_TOKENS>2) begin
      start_frame();map_word(0,0);map_word(0,0);map_word(1,1);
      if(!error) $fatal(1,"CAUSAL_NONROOT_ORIGIN_ACCEPTED");
    end
    load_frame(MAX_TOKENS,0);
    @(negedge clk);query_valid=1;query_position=INDEX_W'(MAX_TOKENS-1);
    do @(posedge clk);while(!query_ready);
    @(negedge clk);query_valid=0;
    repeat(2) @(negedge clk);rst_n=0;
    @(negedge clk);rst_n=1;
    if(out_valid || error || query_ready) $fatal(1,"CAUSAL_RESET_DID_NOT_CANCEL_QUERY");
    load_frame(1,0);check_prefix(0);
    if(stalls<1 || rows<1 || words<1) $fatal(1,"CAUSAL_TEST_INVENTORY");
    $display("CAUSAL_SIZE_PASS max_tokens=%0d rows=%0d words=%0d stalled_cycles=%0d",MAX_TOKENS,rows,words,stalls);
    $finish;
  end
  initial begin #20000000;$fatal(1,"CAUSAL_SIZE_WATCHDOG");end
endmodule
