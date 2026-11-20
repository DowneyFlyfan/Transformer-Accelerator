`timescale 1ns/1ps

module tri_oracle_selectable_bank_writeback_tb;
  localparam logic [63:0] TableBase = 64'h0000000040000000;
  localparam logic [63:0] ProjectionBase = 64'h0000000070000000;
  logic clk=0, rst_n=0, lease_granted=1;
  always #5 clk=~clk;
  logic frame_cfg_valid=0, frame_cfg_ready, frame_active, frame_abort=0;
  logic frame_channel_scales=0;
  logic [9:0] frame_down_shifts;
  logic [63:0] frame_scale_base;
  logic in_valid=0, in_ready, packet_error, in_last;
  logic [31:0] in_tag;
  logic [3:0] in_token;
  logic [15:0] in_start;
  logic [7:0] in_count;
  logic [5119:0] in_data;
  logic bank_read_valid, bank_read_ready, bank_response_valid=0, bank_response_ready;
  logic [8:0] bank_read_row;
  logic [231:0] bank_response_data='0;
  logic req_valid, req_ready, rsp_valid, rsp_ready, rsp_last, rsp_error;
  logic [63:0] req_address, rsp_data;
  logic [4:0] req_length;
  logic out_valid, out_ready, out_last;
  logic [31:0] out_tag;
  logic [3:0] out_token, out_count;
  logic [15:0] out_start;
  logic [127:0] out_data;
  logic projection_valid=0, projection_ready, projection_rsp_valid, projection_rsp_ready;
  logic projection_rsp_last, projection_rsp_error;
  logic [63:0] projection_rsp_data;
  logic mem_req_valid, mem_req_ready, mem_rsp_valid=0, mem_rsp_ready;
  logic [63:0] mem_req_address, mem_rsp_data;
  logic [4:0] mem_req_length;
  logic mem_rsp_last, mem_rsp_error;
  bit expected_mode=0, hold_memory=0, force_output_stall=0, extra_scale_tail=0;
  logic [9:0] expected_shifts;
  logic [63:0] owned_address;
  bit owned_scale, competitor_done=0, held_output=0;
  logic [184:0] held_record;
  int cycles=0, bank_delay=0, bank_rows=0, packet_bank_reads=0, packet_outputs=0;
  int memory_delay=0, remaining=0, memory_beat=0, scale_requests=0, scale_beats=0;
  int projection_requests=0, projection_beats=0, blocked_scale_cycles=0;
  int output_values=0, output_strips=0, configurations=0, stalled_outputs=0;

`ifdef BASE_WRITEBACK
  assign req_valid=0;
  assign req_address='0;
  assign req_length='0;
  assign rsp_ready=0;
  tri_oracle_decoder_bank_writeback dut (
    .clk, .rst_n, .lease_granted, .frame_cfg_valid, .frame_abort, .frame_down_shifts,
    .frame_cfg_ready, .frame_active, .in_valid, .in_ready, .packet_error,
    .in_tag, .in_token, .in_start, .in_count, .in_last, .in_data,
    .bank_read_valid, .bank_read_ready, .bank_read_row,
    .bank_response_valid, .bank_response_ready, .bank_response_data,
    .out_valid, .out_ready, .out_tag, .out_token, .out_start, .out_count, .out_last, .out_data
  );
`else
  tri_oracle_selectable_bank_writeback dut (.*);
`endif

  tri_oracle_narrow_read_arbiter shared_port (
    .clk, .rst_n, .client_req_valid({req_valid,projection_valid}),
    .client_req_ready({req_ready,projection_ready}),
    .client_req_address({req_address,ProjectionBase}), .client_req_length({req_length,5'd8}),
    .client_rsp_valid({rsp_valid,projection_rsp_valid}),
    .client_rsp_ready({rsp_ready,projection_rsp_ready}),
    .client_rsp_last({rsp_last,projection_rsp_last}),
    .client_rsp_error({rsp_error,projection_rsp_error}),
    .client_rsp_data({rsp_data,projection_rsp_data}),
    .mem_req_valid, .mem_req_ready, .mem_req_address, .mem_req_length,
    .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_last, .mem_rsp_error, .mem_rsp_data
  );

  function automatic logic [63:0] table_word(input int word_index);
    logic [63:0] word;
    word='0;
    for (int lane=0;lane<16;lane++) word[3*lane+:3]=3'((16*word_index+lane)%3);
    return word;
  endfunction

  function automatic logic signed [31:0] raw_value(input int index);
    if (index%8<2) return 32'sd8192;
    return 32'((index%2==0 ? 1 : -1)*8192*(index%7+1));
  endfunction

  function automatic logic [15:0] expected_value(input int index,input int token);
    logic signed [63:0] combined, rounded;
    int shift;
    shift=token==0 ? int'(expected_shifts[4:0]) : int'(expected_shifts[9:5]);
    if (expected_mode) shift-=index%3;
    combined=64'($signed(raw_value(index)))<<<shift;
    rounded=combined<0 ? -(((-combined)+4096)>>>13) : ((combined+4096)>>>13);
    if (rounded>32767) return 16'h7fff;
    if (rounded < -32768) return 16'h8000;
    return 16'(rounded);
  endfunction

  assign bank_read_ready=bank_delay==0 && !bank_response_valid && cycles%5!=0;
  assign out_ready=!force_output_stall && cycles%7>=3;
  assign projection_rsp_ready=cycles%3!=0;
  assign mem_req_ready=remaining==0 && !mem_rsp_valid && cycles%5>=2;
  assign mem_rsp_last=remaining==1;
  assign mem_rsp_error=0;
  assign mem_rsp_data=owned_scale ? table_word(int'((owned_address-TableBase)>>3)) :
                                      owned_address+64'(memory_beat)*8;

  always @(posedge clk) begin
    if (!rst_n) begin
      cycles<=0; bank_delay<=0; bank_response_valid<=0;
      memory_delay<=0; remaining<=0; mem_rsp_valid<=0;
      expected_mode<=0; expected_shifts<=0; held_output<=0;
    end else begin
      cycles<=cycles+1;
      if (frame_cfg_valid && frame_cfg_ready) begin
        expected_mode<=frame_channel_scales;
        expected_shifts<=frame_down_shifts;
        configurations++;
      end
      if (req_valid && !expected_mode) $fatal(1,"SELECTED_WRITER_SCALAR_ISSUED_SCALE_READ");
      if (req_valid && !req_ready) blocked_scale_cycles++;
      if (packet_error) $fatal(1,"SELECTED_WRITER_UNEXPECTED_PACKET_ERROR");
      if (bank_read_valid && bank_read_ready) begin
        if (bank_read_row!==9'(int'(in_token)*256+int'(in_start)/8+packet_bank_reads))
          $fatal(1,"SELECTED_WRITER_RESIDUAL_ROW");
        packet_bank_reads++; bank_rows++; bank_delay<=3;
      end
      if (bank_delay!=0) begin
        bank_delay<=bank_delay-1;
        if (bank_delay==1) bank_response_valid<=1;
      end
      if (bank_response_valid && bank_response_ready) bank_response_valid<=0;

      if (mem_req_valid && mem_req_ready) begin
        owned_address<=mem_req_address;
        owned_scale<=mem_req_address>=TableBase && mem_req_address<TableBase+1024;
        memory_beat<=0; memory_delay<=3;
        if (mem_req_address>=TableBase && mem_req_address<TableBase+1024) begin
          if (mem_req_address[2:0]!=0 || mem_req_length!=1)
            $fatal(1,"SELECTED_WRITER_SCALE_REQUEST");
          scale_requests++; remaining<=extra_scale_tail ? 3 : 1;
        end else begin
          if (mem_req_address!==ProjectionBase || mem_req_length!=8)
            $fatal(1,"SELECTED_WRITER_PROJECTION_REQUEST");
          projection_requests++; remaining<=8;
        end
      end
      if (memory_delay!=0) memory_delay<=memory_delay-1;
      if (remaining!=0 && memory_delay==0 && !mem_rsp_valid && !hold_memory)
        mem_rsp_valid<=1;
      if (mem_rsp_valid && mem_rsp_ready) begin
        mem_rsp_valid<=0; remaining<=remaining-1; memory_beat<=memory_beat+1;
        if (owned_scale) scale_beats++;
        else projection_beats++;
      end
      if (held_output && !frame_abort && lease_granted &&
          (!out_valid || {out_tag,out_token,out_start,out_count,out_last,out_data}!==held_record))
        $fatal(1,"SELECTED_WRITER_CHANGED_STALLED_OUTPUT");
      held_output<=out_valid && !out_ready;
      held_record<={out_tag,out_token,out_start,out_count,out_last,out_data};
      if (out_valid && !out_ready) stalled_outputs++;
      if (out_valid && out_ready) begin
        int count;
        count=int'(in_count)-packet_outputs*8;
        if (count>8) count=8;
        if (out_tag!==in_tag || out_token!==in_token ||
            out_start!==in_start+16'(packet_outputs*8) || out_count!==4'(count) ||
            out_last!==(in_last && packet_outputs*8+count==int'(in_count)))
          $fatal(1,"SELECTED_WRITER_OUTPUT_METADATA");
        for (int lane=0;lane<8;lane++) begin
          logic [15:0] wanted;
          wanted=lane<count ? expected_value(int'(out_start)+lane,int'(out_token)) : 16'd0;
          if (out_data[16*lane+:16]!==wanted)
            $fatal(1,"SELECTED_WRITER_VALUE mode=%0d start=%0d lane=%0d got=%h expected=%h",
                   expected_mode,out_start,lane,out_data[16*lane+:16],wanted);
        end
        packet_outputs++; output_strips++; output_values+=count;
      end
    end
  end

  task automatic configure(input bit channel,input int base0,input int base1);
    @(negedge clk);
    frame_channel_scales=channel; frame_down_shifts={5'(base1),5'(base0)};
    frame_scale_base=TableBase; frame_cfg_valid=1;
    do @(posedge clk); while (!frame_cfg_ready);
    @(negedge clk); frame_cfg_valid=0;
    // Future offers may change while the current frame still owns its mode.
    frame_channel_scales=!channel; frame_down_shifts='1; frame_scale_base=64'h123;
  endtask

  task automatic offer_packet(input int token,input int start,input int count,input bit last);
    @(negedge clk);
    packet_bank_reads=0; packet_outputs=0;
    in_token=4'(token); in_start=16'(start); in_count=8'(count); in_last=last;
    in_tag=32'h53430000+32'(configurations); in_data='0;
    for (int lane=0;lane<count;lane++) in_data[32*lane+:32]=raw_value(start+lane);
    in_valid=1;
    do @(posedge clk); while (!in_ready);
    @(negedge clk); in_valid=0;
  endtask

  initial begin : projection_competitor
    wait(rst_n);
    for (int request=0;request<37;request++) begin
      @(negedge clk); projection_valid=1;
      do @(posedge clk); while (!projection_ready);
      @(negedge clk); projection_valid=0;
      for (int beat=0;beat<8;beat++) begin
        do @(posedge clk); while (!(projection_rsp_valid && projection_rsp_ready));
        if (projection_rsp_error || projection_rsp_last!==(beat==7) ||
            projection_rsp_data!==ProjectionBase+64'(beat)*8)
          $fatal(1,"SELECTED_WRITER_MIXED_PROJECTION_RESPONSE");
      end
    end
    competitor_done=1;
  end

  initial begin : run
    int before_reads, before_values;
    repeat(4) @(negedge clk); rst_n=1;
    configure(0,4,5); before_reads=scale_requests;
    offer_packet(0,0,24,0); offer_packet(1,0,24,1);
    wait(!frame_active); if (scale_requests!=before_reads) $fatal(1,"SELECTED_WRITER_LEGACY_READS");
    $display("SELECTED_WRITER_SCALAR_PASS values=48 scale_reads=0");
    configure(1,4,5); before_reads=scale_requests;
    offer_packet(0,0,24,0); offer_packet(1,0,24,1);
    wait(!frame_active);
    if (scale_requests-before_reads!=4) $fatal(1,"SELECTED_WRITER_SCALE_CACHE");
    $display("SELECTED_WRITER_CHANNEL_PASS values=48 scale_reads=4");
    configure(0,2,3); before_reads=scale_requests;
    offer_packet(0,248,13,0); offer_packet(1,248,13,1);
    wait(!frame_active);
    if (scale_requests!=before_reads) $fatal(1,"SELECTED_WRITER_MODE_RETURN");
    $display("SELECTED_WRITER_PARTIAL_SCALAR_PASS values=26");

    // Abort a channel frame with an accepted, malformed three-beat response.
    // Offer a scalar frame while the old transaction is still held/draining.
    configure(1,4,5); force_output_stall=1; extra_scale_tail=1;
    @(negedge clk); before_reads=scale_requests; before_values=output_values;
    packet_bank_reads=0; packet_outputs=0; in_start=0; in_token=0; in_count=8; in_last=1;
    in_data='0; for (int lane=0;lane<8;lane++) in_data[32*lane+:32]=raw_value(lane);
    in_valid=1;
    wait(scale_requests>before_reads);
    @(negedge clk); hold_memory=1; frame_abort=1; in_valid=0;
    @(negedge clk); frame_abort=0;
    frame_channel_scales=0; frame_down_shifts={5'd3,5'd2}; frame_scale_base=0; frame_cfg_valid=1;
    repeat(4) begin
      @(negedge clk);
      if (frame_cfg_ready || !frame_active) $fatal(1,"SELECTED_WRITER_EARLY_MODE_SWITCH");
    end
    hold_memory=0;
    do @(posedge clk); while (!frame_cfg_ready);
    @(negedge clk); frame_cfg_valid=0; extra_scale_tail=0; force_output_stall=0;
    if (output_values!=before_values || scale_requests-before_reads!=1)
      $fatal(1,"SELECTED_WRITER_ABORT_LEAK");
    offer_packet(0,32,8,1); wait(!frame_active);
    $display("SELECTED_WRITER_ABORT_DRAIN_PASS drained_scale_beats=3 recovered_scalar_values=8");
    wait(competitor_done); repeat(5) @(negedge clk);
    if (output_values!=130 || output_strips!=17 || configurations!=5 ||
        projection_requests!=37 || projection_beats!=296 || blocked_scale_cycles==0 ||
        stalled_outputs==0 || remaining!=0 || bank_response_valid)
      $fatal(1,"SELECTED_WRITER_TOTALS values=%0d strips=%0d configurations=%0d",output_values,output_strips,configurations);
    $display("SELECTED_WRITER_PASS values=130 strips=17 frames=5 projection_requests=37 projection_beats=296");
    $finish;
  end
  initial begin #200000; $fatal(1,"SELECTED_WRITER_TIMEOUT"); end
endmodule
