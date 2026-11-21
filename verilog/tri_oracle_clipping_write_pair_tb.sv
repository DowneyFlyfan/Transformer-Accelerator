`timescale 1ns/1ps

module tri_oracle_clipping_write_pair_tb;
  logic clk=0, rst_n=0, enable=0;
  always #5 clk=~clk;
  logic packet_valid=0, packet_ready;
  logic [6:0] packet_count=0;
  logic [5:0] packet_shift=0;
  logic [16:0] packet_plane_bytes=0;
  logic [1279:0] packet_gated=0, expected_gated=0;
  logic in_req_valid=0, in_req_ready;
  logic [63:0] in_address=0;
  logic [4:0] in_length=0;
  logic in_data_valid=0, in_data_ready;
  logic [63:0] in_data=0;
  logic [7:0] in_strobe=0;
  logic in_data_last=0;
  logic in_rsp_valid, in_rsp_ready=0, in_rsp_error;
  logic mem_req_valid, mem_req_ready;
  logic [63:0] mem_address;
  logic [4:0] mem_length;
  logic mem_data_valid, mem_data_ready;
  logic [63:0] mem_data;
  logic [7:0] mem_strobe;
  logic mem_data_last;
  logic mem_rsp_valid=0, mem_rsp_ready, mem_rsp_error=0;
  int cycle=0, requests=0, beats=0, beat=0, length=0, delay=0;
  int fault_mode=0, expected_shift=0, expected_count=0, cases=0;
  int arithmetic_cases=0, expected_length=0, request_base=0,acknowledgements=0;
  logic active=0, expected_enable=0;
  logic [63:0] expected_address=0;
  logic [16:0] expected_plane_bytes=0;
  logic held_request=0, held_data=0;
  logic [68:0] prior_request;
  logic [72:0] prior_data;

`ifdef BASE_WRITE_PATH
  // The current frame exposes exactly this one-plane external write path.
  assign packet_ready=1;
  assign mem_req_valid=in_req_valid;
  assign in_req_ready=mem_req_ready;
  assign mem_address=in_address;
  assign mem_length=in_length;
  assign mem_data_valid=in_data_valid;
  assign in_data_ready=mem_data_ready;
  assign mem_data=in_data;
  assign mem_strobe=in_strobe;
  assign mem_data_last=in_data_last;
  assign in_rsp_valid=mem_rsp_valid;
  assign mem_rsp_ready=in_rsp_ready;
  assign in_rsp_error=mem_rsp_error;
`else
  tri_oracle_clipping_write_pair dut (.*);
`endif

  // Independent division-based oracle; hardware uses a signed barrel shift.
  function automatic integer rounded(input integer value,input integer shift);
    integer magnitude,divisor;
    if(shift>=17)return 0;
    divisor=1<<shift;
    magnitude=value<0 ? -value : value;
    magnitude=(magnitude+divisor/2)/divisor;
    return value<0 ? -magnitude : magnitude;
  endfunction
  function automatic integer clamp8(input integer value);
    return value>127 ? 127 : value< -128 ? -128 : value;
  endfunction
  function automatic logic [63:0] expected_word(input integer which,input integer word_index);
    integer value,wide,coarse,delta;
    logic [63:0] word;
    word=0;
    for(int lane=0;lane<8;lane++)begin
      value=int'($signed(expected_gated[(word_index*8+lane)*16+:16]));
      wide=rounded(value,expected_shift);coarse=clamp8(wide);delta=clamp8(wide-coarse);
      word[lane*8+:8]=8'(which==0 ? coarse : delta);
    end
    return word;
  endfunction

  assign mem_req_ready=!active && delay==0 && !mem_rsp_valid && cycle%5>=2;
  assign mem_data_ready=active && cycle%7>=3;

  always @(posedge clk)begin
    if(!rst_n)begin
      cycle<=0;requests<=0;beats<=0;beat<=0;length<=0;delay<=0;acknowledgements<=0;
      active<=0;mem_rsp_valid<=0;mem_rsp_error<=0;held_request<=0;held_data<=0;
    end else begin
      cycle<=cycle+1;
      if(cycle>20000)$fatal(1,"CLIPPING_WRITER_TIMEOUT");
      if(held_request && (!mem_req_valid || {mem_address,mem_length}!==prior_request))
        $fatal(1,"CLIPPING_WRITER_REQUEST_CHANGED_WHILE_STALLED");
      held_request<=mem_req_valid && !mem_req_ready;prior_request<={mem_address,mem_length};
      if(held_data && (!mem_data_valid || {mem_data,mem_strobe,mem_data_last}!==prior_data))
        $fatal(1,"CLIPPING_WRITER_DATA_CHANGED_WHILE_STALLED");
      held_data<=mem_data_valid && !mem_data_ready;prior_data<={mem_data,mem_strobe,mem_data_last};
      if(mem_req_valid && mem_length==0)$fatal(1,"CLIPPING_WRITER_ZERO_LENGTH_FORWARDED");
      if(delay!=0 && requests-request_base==2 && in_rsp_valid)
        $fatal(1,"CLIPPING_WRITER_COMPLETION_DURING_SECOND_ACK_DELAY");
      if(mem_req_valid && mem_req_ready)begin
        if(requests-request_base>=2 || (requests-request_base==1 && !expected_enable))$fatal(1,"CLIPPING_WRITER_EXTRA_REQUEST");
        if(mem_address!==(requests==request_base ? expected_address : expected_address+64'(expected_plane_bytes)) ||
           mem_length!==5'(expected_length))$fatal(1,"CLIPPING_WRITER_REQUEST_METADATA");
        requests<=requests+1;active<=1;beat<=0;length<=int'(mem_length);
      end
      if(mem_data_valid && mem_data_ready)begin
        if(!active || mem_data!==expected_word(requests-request_base-1,beat) || mem_strobe!==8'hff ||
           mem_data_last!==(beat+1==length))$fatal(1,"CLIPPING_WRITER_DATA_MISMATCH case=%0d pass=%0d beat=%0d actual=%h expected=%h",cases,requests-request_base-1,beat,mem_data,expected_word(requests-request_base-1,beat));
        beats<=beats+1;beat<=beat+1;
        if(mem_data_last)begin active<=0;delay<=requests-request_base==2 ? 25 : 3;end
      end
      if(delay!=0)begin
        delay<=delay-1;
        if(delay==1)begin
          mem_rsp_valid<=1;
          mem_rsp_error<=(fault_mode==1 && requests-request_base==1) || (fault_mode==2 && requests-request_base==2);
        end
      end
      if(mem_rsp_valid && mem_rsp_ready)begin mem_rsp_valid<=0;acknowledgements<=acknowledgements+1;end
    end
  end

  task automatic reset_both;
    @(negedge clk);rst_n=0;packet_valid=0;in_req_valid=0;in_data_valid=0;in_rsp_ready=0;
    repeat(3)@(negedge clk);
    rst_n=1;
  endtask

  task automatic transact(input bit mode,input int count,input int shift,input int fault,
                          input bit wrap_address,input bit bad_length,input int offset_case=0,input bit ready_early=0);
    int before_requests,before_beats,before_acknowledgements,want_requests,word_count;
    bit want_error;
    before_requests=requests;before_beats=beats;request_base=requests;before_acknowledgements=acknowledgements;
    @(negedge clk);
    enable=mode;expected_enable=mode;expected_count=count;expected_shift=shift;fault_mode=fault;
    expected_address=wrap_address ? 64'hfffffffffffffff8 : 64'h00000034ffffffc0+64'(cases)*4096;
    if(offset_case==3)expected_address=64'hfffffffffffffff8-64'd90112;
    expected_plane_bytes=offset_case==1 ? 17'd8 : offset_case==2 ? 17'(count) : 17'd90112;
    expected_length=count/8-(bad_length ? 1 : 0);
    expected_gated=0;
    for(int lane=0;lane<80;lane++)begin
      case(lane%16)
        0:expected_gated[lane*16+:16]=16'sh8000;
        1:expected_gated[lane*16+:16]=16'sh7fff;
        2:expected_gated[lane*16+:16]=-16'sd129;
        3:expected_gated[lane*16+:16]=16'sd128;
        4:expected_gated[lane*16+:16]=-16'sd128;
        5:expected_gated[lane*16+:16]=16'sd127;
        6:expected_gated[lane*16+:16]=-16'sd257;
        7:expected_gated[lane*16+:16]=16'sd255;
        default:expected_gated[lane*16+:16]=16'((lane-40)*113);
      endcase
    end
    packet_count=7'(count);packet_shift=6'(shift);packet_plane_bytes=expected_plane_bytes;
    packet_gated=expected_gated;packet_valid=1;
    do @(posedge clk);while(!packet_ready);
    @(negedge clk);packet_valid=0;packet_gated='x;packet_shift='x;packet_count='x;packet_plane_bytes='x;
    // Live upstream metadata may change after each accepted transfer.
    in_address=expected_address;in_length=5'(expected_length);in_req_valid=1;
    do @(posedge clk);while(!in_req_ready);
    @(negedge clk);in_req_valid=0;in_address='x;in_length='x;
    word_count=expected_length;
    for(int index=0;index<word_count;index++)begin
      in_data=expected_word(0,index);in_strobe=8'hff;in_data_last=index+1==word_count;in_data_valid=1;
      do @(posedge clk);while(!in_data_ready);
      @(negedge clk);in_data_valid=0;in_data='x;in_strobe='x;in_data_last='x;
      if(index%2==0)repeat(2)@(negedge clk);
    end
    if(ready_early)in_rsp_ready=1;
    want_requests=mode && fault!=1 && !wrap_address && !bad_length && offset_case!=1 && offset_case!=3 ? 2 : 1;
    want_error=fault!=0 || (mode && (wrap_address || bad_length || offset_case==1 || offset_case==3));
    wait(in_rsp_valid);#1;
    if(requests-before_requests!=want_requests)$fatal(1,"CLIPPING_WRITER_EARLY_COMPLETION expected_requests=%0d actual_requests=%0d",want_requests,requests-before_requests);
    if(mode && acknowledgements-before_acknowledgements!=want_requests)$fatal(1,"CLIPPING_WRITER_COMPLETION_BEFORE_MEMORY_ACK");
    if(beats-before_beats!=want_requests*word_count || in_rsp_error!==want_error)
      $fatal(1,"CLIPPING_WRITER_COMPLETION_METADATA");
    if(!ready_early)repeat(5)begin
      @(negedge clk);
      if(!in_rsp_valid || in_rsp_error!==want_error)$fatal(1,"CLIPPING_WRITER_COMPLETION_CHANGED_WHILE_STALLED");
    end
    in_rsp_ready=1;@(posedge clk);@(negedge clk);in_rsp_ready=0;
    if(acknowledgements-before_acknowledgements!=want_requests)$fatal(1,"CLIPPING_WRITER_ACKNOWLEDGEMENT_COUNT");
    cases++;
    // Reuse the live controller across successes, errors and mode changes.
    repeat(2)@(negedge clk);
    if(in_rsp_valid || mem_req_valid || mem_data_valid)$fatal(1,"CLIPPING_WRITER_STALE_TRANSACTION");
  endtask

  task automatic reject_zero_length;
    int old_requests,old_acknowledgements,wait_cycles;
    old_requests=requests;old_acknowledgements=acknowledgements;request_base=requests;
    @(negedge clk);enable=1;expected_enable=1;packet_count=8;packet_shift=0;
    packet_plane_bytes=90112;packet_gated=0;packet_valid=1;
    do @(posedge clk);while(!packet_ready);
    @(negedge clk);packet_valid=0;in_req_valid=1;in_address=64'h1000;in_length=0;in_rsp_ready=1;
    do @(posedge clk);while(!in_req_ready);
    @(negedge clk);in_req_valid=0;wait_cycles=0;
    while(!in_rsp_valid && wait_cycles<16)begin @(negedge clk);wait_cycles++;end
    if(!in_rsp_valid || !in_rsp_error || requests!=old_requests || acknowledgements!=old_acknowledgements)
      $fatal(1,"CLIPPING_WRITER_ZERO_LENGTH_LOCAL_REJECTION");
    @(posedge clk);@(negedge clk);in_rsp_ready=0;cases++;
    repeat(2)@(negedge clk);
  endtask

  initial begin
    integer reference_value;
    reset_both();
    if($test$plusargs("ZERO_ONLY"))begin reject_zero_length();$finish(1);end
`ifndef BASE_WRITE_PATH
`ifndef MAPPED_CLIP_WRITER
    for(int shift=0;shift<64;shift++)begin
      for(int value=-32768;value<32768;value++)begin
        reference_value=clamp8(rounded(value,shift)-clamp8(rounded(value,shift)));
        if(dut.clipped_remainder(16'(value),6'(shift))!==8'(reference_value))
          $fatal(1,"CLIPPING_WRITER_ARITHMETIC value=%0d shift=%0d",value,shift);
        arithmetic_cases++;
      end
    end
`endif
`endif
    transact(1,8,0,0,0,0);
    transact(0,32,1,0,0,0);
    transact(1,80,1,0,0,0,0,1);
    transact(1,32,7,0,0,0);
    transact(1,8,16,0,0,0);
    transact(1,80,17,0,0,0);
    transact(1,32,63,0,0,0);
    transact(1,32,0,1,0,0);
    transact(1,80,0,2,0,0);
    transact(1,8,0,0,1,0);
    transact(1,32,0,0,0,1);
    transact(1,80,0,0,0,0,1);
    transact(1,80,0,0,0,0,2);
    transact(1,80,0,0,0,0,3);
    reject_zero_length();
    transact(1,8,0,0,0,0);
    // Reset interrupts conversion; peer reset discards outstanding transactions.
    @(negedge clk);enable=1;packet_count=80;packet_shift=0;packet_plane_bytes=90112;
    packet_gated='1;packet_valid=1;
    repeat(13)@(negedge clk);
    reset_both();
    transact(1,8,0,0,0,0);
    transact(0,80,0,0,0,0);
    $display("CLIPPING_WRITE_PAIR_PASS packets=%0d arithmetic_cases=%0d primary_fault=1 secondary_fault=1 address_overflow=2 plane_overlap=1 zero_length=1 length_mismatch=1 reset_capture=1",cases,arithmetic_cases);
    $finish(1);
  end
endmodule
