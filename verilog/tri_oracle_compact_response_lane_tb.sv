`timescale 1ns/1ps

module tri_oracle_compact_response_lane_tb;
  bit clk=0, rst_n=0;
  always #5 clk=!clk;
  logic [2:0] req_valid=0, req_ready, rsp_valid, rsp_ready=0, rsp_last, rsp_error;
  logic [2:0][63:0] req_address='{64'h3000000,64'h4000000,64'h2000000};
  logic [2:0][5:0] req_length='{6'd3,6'd1,6'd2};
  logic [1087:0] rsp_data;
  wire primary_wide=1'b1;
  logic wr_req_valid=0,wr_req_ready,wr_data_valid=0,wr_data_ready,wr_data_last=0;
  wire [63:0] wr_address=64'h8000000,wr_data=0;
  wire [4:0] wr_length=0;
  wire [7:0] wr_strobe=0;
  logic wr_rsp_valid,wr_rsp_ready=0,wr_rsp_error;
  logic tx_valid;
  wire tx_ready=1'b1;
  logic [21:0] tx_data;
  logic [1:0] mem_rsp_valid,mem_rsp_ready,mem_rsp_last,mem_rsp_error;
  logic [1:0][511:0] mem_rsp_data;
  logic [1:0] in_valid=0,in_ready,in_last=0,in_error=0,in_compact=0;
  logic [1:0][2:0] in_words=0;
  logic [1:0][447:0] in_data=0;
  int checks=0, overlaps=0;
  localparam logic [127:0] INDEX=128'h0000000000003d81_23456789abcdef01;
  localparam logic [63:0] SCALAR=64'h19cde8406780fab1;

  tri_oracle_memory_io_link dut (.*);
  for (genvar lane=0; lane<2; lane++) begin: lanes
    tri_oracle_compact_response_lane rx (
      .clk,.rst_n,.in_valid(in_valid[lane]),.in_ready(in_ready[lane]),
      .in_compact(in_compact[lane]),.in_data(in_data[lane]),.in_words(in_words[lane]),
      .in_last(in_last[lane]),.in_error(in_error[lane]),
      .out_valid(mem_rsp_valid[lane]),.out_ready(mem_rsp_ready[lane]),
      .out_data(mem_rsp_data[lane]),.out_last(mem_rsp_last[lane]),.out_error(mem_rsp_error[lane])
    );
  end

  function automatic logic [447:0] chunk(input int start);
    for (int i=0;i<7;i++) chunk[64*i+:64]=64'hbe321f4300210000+64'(start+i);
  endfunction
  function automatic logic [511:0] beat(input int start);
    for (int i=0;i<8;i++) beat[64*i+:64]=64'hbe321f4300210000+64'(start+i);
  endfunction

  task automatic request(input int client);
    req_valid[client]=1;
    do @(posedge clk); while (!req_ready[client]);
    @(negedge clk); req_valid[client]=0;
  endtask

  task automatic send(
      input int lane,input logic [447:0] data,input logic [2:0] words,
      input bit compact,last,error
  );
    in_valid[lane]=1;
    in_data[lane]=data;
    in_words[lane]=words;
    in_compact[lane]=compact;
    in_last[lane]=last;
    in_error[lane]=error;
    do @(posedge clk); while (!in_ready[lane]);
    @(negedge clk); in_valid[lane]=0;
  endtask

  task automatic read_beat(input int client,input logic [511:0] expected,input bit last,error);
    do @(negedge clk); while (!rsp_valid[client]);
    repeat (3) begin
      logic [511:0] value;
      case (client)
        0: value=rsp_data[511:0];
        1: value=rsp_data[1023:512];
        2: value={448'b0,rsp_data[1087:1024]};
        default: $fatal(1,"RESPONSE_TEST_CLIENT");
      endcase
      if (!rsp_valid[client] || rsp_last[client]!==last || rsp_error[client]!==error || value!==expected)
        $fatal(1,"COMPACT_RESPONSE_MISMATCH client=%0d last=%b got_last=%b error=%b got_error=%b",
               client,last,rsp_last[client],error,rsp_error[client]);
      @(negedge clk);
    end
    rsp_ready[client]=1;
    @(negedge clk); rsp_ready[client]=0;
    checks++;
  endtask

  always @(posedge clk) if (rst_n) begin
    if (wr_rsp_valid && (rsp_valid[0] || rsp_valid[2]))
      $fatal(1,"COMPACT_RESPONSE_OWNERSHIP_COLLISION");
    if (wr_rsp_valid && rsp_valid[1]) overlaps++;
  end

  initial begin
    repeat (3) @(negedge clk);
    rst_n=1;
    request(0);
    request(1);
    send(0,chunk(0),3'd7,0,0,0);
    send(0,chunk(7),3'd7,0,0,0);
    send(1,{320'b0,INDEX},3'd2,1,1,0);
    fork
      send(0,chunk(14),3'd2,0,1,1);
      read_beat(0,beat(0),0,0);
      read_beat(1,{384'b0,INDEX},1,0);
    join
    read_beat(0,beat(8),1,1);

    wr_req_valid=1;
    do @(posedge clk); while (!wr_req_ready);
    @(negedge clk); wr_req_valid=0;
    request(1);
    send(0,'0,3'd0,1,1,1);
    // The earlier index format still reports a malformed one-word index.
    send(1,{320'b0,INDEX},3'd1,1,1,0);
    read_beat(1,{384'b0,INDEX},1,1);
    if (!wr_rsp_valid || wr_rsp_error!==1'b1 || overlaps==0)
      $fatal(1,"COMPACT_SHORT_WRITE_ACK");
    wr_rsp_ready=1;
    @(negedge clk); wr_rsp_ready=0;

    request(2);
    for (int word=0;word<3;word++) begin
      send(0,{384'b0,SCALAR+64'(word)},3'd0,1,word==2,word==1);
      read_beat(2,{448'b0,SCALAR+64'(word)},word==2,word==1);
    end
    if (checks!=7 || |rsp_valid || wr_rsp_valid)
      $fatal(1,"COMPACT_RESPONSE_COUNT checks=%0d",checks);
    $display("COMPACT_RESPONSE_LANE_PASS wide=2 indexes=2 scalar=3 write_acks=1 overlap=%0d",overlaps);
    $finish;
  end

  initial begin
    repeat (500) @(negedge clk);
    $fatal(1,"COMPACT_RESPONSE_TIMEOUT checks=%0d",checks);
  end
endmodule
