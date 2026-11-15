`timescale 1ns/1ps

module tri_oracle_indexed_dispatch_tb;
  logic clk=0, rst_n=0;
  always #5 clk=~clk;
  logic command_valid=0, command_ready;
  logic [2:0] command_opcode;
  logic [31:0] command_tag='0;
  logic payload_valid=0, payload_ready, payload_last=0;
  logic [63:0] payload_data;
  logic response_valid, response_ready=0, response_error;
  logic [2:0] response_opcode;
  logic [31:0] response_tag, layer_command_tag;
  logic [7:0] layer_command_valid, layer_command_ready='0;
  logic [7:0] layer_done_valid='0, layer_done_ready, layer_done_error='0;
  wire [255:0] layer_done_tag={8{command_tag}};
  logic [1663:0] layer_command_payload;
  logic layer_feedforward_indexed;
  logic [1663:0] descriptor;

`ifdef EXISTING_DISPATCH
  assign layer_feedforward_indexed=1'b0;
  tri_oracle_chip_dispatch dut (
    .clk,.rst_n,.command_valid,.command_ready,.command_opcode,.command_tag,
    .payload_valid,.payload_ready,.payload_data,.payload_last,
    .response_valid,.response_ready,.response_error,.response_opcode,.response_tag,
    .layer_command_valid,.layer_command_ready,.layer_command_tag,.layer_command_payload,
    .layer_done_valid,.layer_done_ready,.layer_done_error,.layer_done_tag
  );
`else
  tri_oracle_indexed_chip_dispatch dut (.*);
`endif

  task automatic start(input logic [2:0] opcode);
    if (!command_ready) $fatal(1,"INDEXED_DISPATCH_HEADER_NOT_READY");
    command_opcode=opcode;
    command_tag++;
    command_valid=1;
    @(negedge clk);
    command_valid=0;
  endtask

  task automatic word(input logic [63:0] data, input logic last_word);
    if (!payload_ready || layer_command_valid!==0 || response_valid!==0)
      $fatal(1,"INDEXED_DISPATCH_WORD_NOT_READY");
    payload_valid=1;
    payload_data=data;
    payload_last=last_word;
    @(negedge clk);
    payload_valid=0;
    payload_last=0;
  endtask

  task automatic check_issue(input logic [2:0] opcode, input int words, input logic is_indexed);
    for (int stall=0; stall<3; stall++) begin
      if (layer_command_valid!==(8'b1<<opcode) || layer_command_tag!==command_tag ||
          layer_feedforward_indexed!==is_indexed)
        $fatal(1,"INDEXED_DISPATCH_ISSUE opcode=%0d indexed=%0d",opcode,is_indexed);
      for (int i=0; i<words; i++)
        if (layer_command_payload[64*i+:64]!==descriptor[64*i+:64])
          $fatal(1,"INDEXED_DISPATCH_BASE_PAYLOAD opcode=%0d word=%0d",opcode,i);
      @(negedge clk);
    end
    layer_command_ready=8'b1<<opcode;
    @(negedge clk);
    layer_command_ready='0;
    layer_done_valid=8'b1<<opcode;
    #1;
    if ({response_valid,response_error,response_opcode,response_tag}!=={1'b1,1'b0,opcode,command_tag}
        || layer_done_ready!==0 || layer_feedforward_indexed!==is_indexed)
      $fatal(1,"INDEXED_DISPATCH_BACKPRESSURE_RESPONSE");
    response_ready=1;
    @(negedge clk);
    response_ready=0;
    layer_done_valid='0;
    if (!command_ready) $fatal(1,"INDEXED_DISPATCH_COMPLETE");
  endtask

  task automatic send_base(input int words, input logic terminate);
    for (int i=0; i<words; i++) word(descriptor[64*i+:64],terminate && i==words-1);
  endtask

  task automatic check_error;
    if ({response_valid,response_error,response_opcode,response_tag}!=={1'b1,1'b1,3'd0,command_tag}
        || layer_command_valid!==0 || layer_feedforward_indexed!==0)
      $fatal(1,"INDEXED_DISPATCH_MALFORMED_WAS_NOT_REJECTED");
    response_ready=1;
    @(negedge clk);
    response_ready=0;
  endtask

  initial begin
    int words[8]='{15,9,1,1,3,3,5,26};
    for (int i=0; i<26; i++) descriptor[64*i+:64]=64'hfedc9876_5410abcd ^ (64'(i)<<54);
    repeat (2) @(negedge clk);
    rst_n=1;
    for (int opcode=0; opcode<8; opcode++) begin
      start(3'(opcode));
      send_base(words[opcode],1);
      check_issue(3'(opcode),words[opcode],0);
    end
    start(0);
    send_base(15,0);
    repeat (3) @(negedge clk);
    word(64'h1,1);
    check_issue(0,15,1);
    if (layer_command_payload[1663:960]!==descriptor[1663:960])
      $fatal(1,"INDEXED_EXTENSION_MODIFIED_BASE_PAYLOAD");

    // The mode clears on a new raw command even though the payload holds
    // stale upper words from the preceding grouped-attention command.
    descriptor=~descriptor;
    start(0);
    send_base(15,1);
    check_issue(0,15,0);
    start(0);
    send_base(14,1);
    check_error();
    start(0);
    send_base(15,0);
    word(64'h8000_0000_0000_0001,1);
    check_error();
    start(0);
    send_base(15,0);
    word(64'h1,0);
    word(64'h1,1);
    check_error();
    $display("INDEXED_DISPATCH_PASS ordinary=9 indexed=1 malformed=3");
    $finish;
  end
endmodule
