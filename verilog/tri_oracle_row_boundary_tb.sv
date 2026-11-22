`timescale 1ns/1ps
module tri_oracle_row_boundary_tb;
  logic clk=0; always #5 clk=~clk;
  logic rst_n=0,cfg_valid=0,cfg_ready;
  logic [31:0] cfg_tag=0;
  logic [4:0] cfg_tokens=0;
  logic [6:0] cfg_count=0;
  logic [1279:0] cfg_channels=0;
  logic [95:0] cfg_gate_shifts=0,cfg_up_shifts=0,cfg_down_shifts=0;
  logic [479:0] cfg_row_units=0;
  logic out_valid,out_ready=0,out_last,done_valid,done_ready=0,done_error;
  logic [31:0] out_tag,done_tag;
  logic [3:0] out_token;
  logic [6:0] out_count;
  logic [1279:0] out_channels,out_gated,out_down_wide;
  logic [639:0] out_down_input,out_correction;
  logic projection_ready=1,projection_valid=0,projection_last=0;
  logic [31:0] projection_tag=0,projection_done_tag=0;
  logic [3:0] projection_token=0;
  logic [6:0] projection_count=0;
  logic [1279:0] projection_channels=0;
  logic [5119:0] projection_data=0;
  logic projection_done_valid=0,projection_done_error=0;
  logic projection_out_ready,projection_done_ready;
  logic [5119:0] raw_words[29];
  logic [1279:0] gated_words[29],wide_words[29];
  logic [639:0] coarse_words[29],correction_words[29];
  logic [479:0] units[6];
  logic [95:0] gate_shifts[6],up_shifts[6],down_shifts[6];
  logic [31:0] accepted_tag;
  logic [1279:0] accepted_channels;
  logic [4:0] accepted_tokens;
  logic [6:0] accepted_count;
  int cycle=0,case_number=0,success_packets=0,errors=0,next_tag=0;
  bit expect_error=0;
  string fixture;
  tri_oracle_row_nonlinear dut(.*);

  always @(posedge clk) begin
    cycle<=cycle+1;
    if(cycle>100000)$fatal(1,"ROW_BOUNDARY_TIMEOUT case=%0d",case_number);
    if(rst_n && expect_error && (out_valid!==1'b0 || dut.activation_in_valid!==1'b0))
      $fatal(1,"ROW_BOUNDARY_REJECTED_DESCRIPTOR_EXECUTED case=%0d",case_number);
  end

  task automatic defaults();
    while(cfg_ready!==1'b1)@(negedge clk);
    cfg_tag=32'hb0a00000+32'(next_tag);next_tag++;cfg_tokens=1;cfg_count=1;
    cfg_channels=1280'h101;cfg_gate_shifts=0;cfg_up_shifts=0;cfg_down_shifts=0;cfg_row_units=0;
    projection_ready=1;projection_valid=0;projection_done_valid=0;projection_done_error=0;
  endtask

  task automatic accept_config();
    accepted_tag=cfg_tag;accepted_channels=cfg_channels;accepted_tokens=cfg_tokens;accepted_count=cfg_count;
    cfg_valid=1;@(negedge clk);cfg_valid=0;
  endtask

  task automatic complete(input bit error_value,input bit wrong_tag=0,input bit upstream_error=0);
    while(projection_done_ready!==1'b1)@(negedge clk);
    projection_done_tag=wrong_tag ? accepted_tag^32'h1 : accepted_tag;
    projection_done_error=upstream_error;projection_done_valid=1;
    @(negedge clk);projection_done_valid=0;
    while(done_valid!==1'b1)@(negedge clk);
    repeat(5)begin
      if(done_valid!==1'b1 || done_error!==error_value || done_tag!==accepted_tag || cfg_ready!==1'b0)
        $fatal(1,"ROW_BOUNDARY_BAD_COMPLETION case=%0d want_error=%0d actual_error=%0b",case_number,error_value,done_error);
      @(negedge clk);
    end
    done_ready=1;@(negedge clk);done_ready=0;expect_error=0;
    if(error_value)errors++;
  endtask

  task automatic send_packet(input int token_index,input int fault,input logic [5119:0] raw);
    while(projection_out_ready!==1'b1)@(negedge clk);
    projection_tag=accepted_tag;projection_token=4'(token_index);projection_count=accepted_count;
    projection_channels=accepted_channels;projection_last=token_index+1==int'(accepted_tokens);
    projection_data=raw;
    case(fault)
      1:projection_tag=accepted_tag^32'h1;
      2:projection_count=accepted_count+1;
      3:projection_token=4'(token_index+1);
      4:projection_channels=accepted_channels^1280'h1;
      5:projection_last=~projection_last;
      default:;
    endcase
    projection_valid=1;@(negedge clk);projection_valid=0;
  endtask

  task automatic receive_packet(input int token_index,input logic [1279:0] gated,input logic [1279:0] wide,
      input logic [639:0] coarse,input logic [639:0] correction);
    while(out_valid!==1'b1)@(negedge clk);
    repeat(7)begin
      if(out_valid!==1'b1 || out_tag!==accepted_tag || out_token!==4'(token_index) ||
         out_last!==(token_index+1==int'(accepted_tokens)) || out_count!==accepted_count ||
         out_channels!==accepted_channels || out_gated!==gated || out_down_wide!==wide ||
         out_down_input!==coarse || out_correction!==correction)
        $fatal(1,"ROW_BOUNDARY_OUTPUT_OR_STALL_MISMATCH case=%0d token=%0d",case_number,token_index);
      @(negedge clk);
    end
    out_ready=1;@(negedge clk);out_ready=0;success_packets++;
  endtask

  task automatic good_recovery();
    defaults();cfg_count=80;cfg_gate_shifts=gate_shifts[0];cfg_up_shifts=up_shifts[0];cfg_down_shifts=down_shifts[0];
    accept_config();send_packet(0,0,raw_words[0]);
    receive_packet(0,gated_words[0],wide_words[0],coarse_words[0],correction_words[0]);complete(0);
  endtask

  initial begin
    if(!$value$plusargs("FIXTURE=%s",fixture))$fatal(1,"ROW_BOUNDARY_MISSING_FIXTURE");
    $readmemh({fixture,"/raw.hex"},raw_words);$readmemh({fixture,"/gated.hex"},gated_words);
    $readmemh({fixture,"/wide.hex"},wide_words);$readmemh({fixture,"/coarse.hex"},coarse_words);
    $readmemh({fixture,"/correction.hex"},correction_words);$readmemh({fixture,"/row_units.hex"},units);
    $readmemh({fixture,"/gate_shifts.hex"},gate_shifts);$readmemh({fixture,"/up_shifts.hex"},up_shifts);
    $readmemh({fixture,"/down_shifts.hex"},down_shifts);
    repeat(4)@(negedge clk);rst_n=1;@(negedge clk);

    // Accepted row offsets, shifts and metadata must survive changing every
    // input after the configuration handshake. Also test admission backpressure.
    defaults();cfg_tokens=3;cfg_count=80;cfg_row_units=units[1];
    cfg_gate_shifts=gate_shifts[1];cfg_up_shifts=up_shifts[1];cfg_down_shifts=down_shifts[1];
    cfg_channels=0;for(int lane=0;lane<80;lane++)cfg_channels[lane*16+:16]=16'(257+lane);
    projection_ready=0;cfg_valid=1;#1;
    repeat(4)begin
      if(cfg_ready!==1'b0 || out_valid!==1'b0 || done_valid!==1'b0)$fatal(1,"ROW_BOUNDARY_EARLY_ACCEPT");
      @(negedge clk);
    end
    projection_ready=1;#1;if(cfg_ready!==1'b1)$fatal(1,"ROW_BOUNDARY_NO_ADMISSION");
    accept_config();
    cfg_valid=1;cfg_tag='1;cfg_count='1;cfg_tokens='1;cfg_channels=0;cfg_row_units='1;
    cfg_gate_shifts='1;cfg_up_shifts='1;cfg_down_shifts='1;
    for(int token_index=0;token_index<3;token_index++)begin
      send_packet(token_index,0,raw_words[3+token_index]);
      receive_packet(token_index,gated_words[3+token_index],wide_words[3+token_index],coarse_words[3+token_index],correction_words[3+token_index]);
    end
    cfg_valid=0;complete(0);$display("ROW_BOUNDARY_PASS case=0 captured_configuration_and_admission");case_number++;

    // The largest legal sum 56+7=63 must not be rejected. All raw values
    // become zero under this shift, including signed32 endpoints.
    defaults();cfg_tokens=2;cfg_count=80;cfg_gate_shifts={16{6'd56}};cfg_up_shifts={16{6'd56}};
    cfg_row_units='1;accept_config();
    for(int token_index=0;token_index<2;token_index++)begin
      send_packet(token_index,0,raw_words[7]);receive_packet(token_index,0,0,0,0);
    end
    complete(0);$display("ROW_BOUNDARY_PASS case=1 effective_shift63");case_number++;

    // Inactive channels and token slots must not make a legal descriptor fail.
    defaults();cfg_gate_shifts={16{6'd63}};cfg_up_shifts={16{6'd63}};
    cfg_row_units='1;cfg_row_units[5:0]=0;accept_config();
    send_packet(0,0,0);receive_packet(0,0,0,0,0);complete(0);
    $display("ROW_BOUNDARY_PASS case=2 inactive_channel_offsets");case_number++;
    defaults();cfg_gate_shifts={16{6'd63}};cfg_up_shifts={16{6'd63}};
    cfg_gate_shifts[5:0]=0;cfg_up_shifts[5:0]=0;cfg_row_units='1;accept_config();
    send_packet(0,0,0);receive_packet(0,0,0,0,0);complete(0);
    $display("ROW_BOUNDARY_PASS case=3 inactive_token_bases");case_number++;

    // Six invalid descriptors: both overflow paths and both sides of both
    // shape ranges. They drain upstream completion, hold an error, and recover
    // without any external reset. The recovery must perform real computation.
    for(int kind=0;kind<6;kind++)begin
      defaults();
      case(kind)
        0:begin cfg_gate_shifts[5:0]=57;cfg_row_units[2:0]=7;end
        1:begin cfg_up_shifts[5:0]=57;cfg_row_units[5:3]=7;end
        2:cfg_tokens=0;
        3:cfg_tokens=17;
        4:cfg_count=0;
        5:cfg_count=81;
      endcase
      expect_error=1;accept_config();
      repeat(8)begin
        if(projection_done_ready!==1'b1 || done_valid!==1'b0)$fatal(1,"ROW_BOUNDARY_BAD_ERROR_DRAIN case=%0d",case_number);
        @(negedge clk);
      end
      send_packet(0,0,raw_words[0]);complete(1);good_recovery();
      $display("ROW_BOUNDARY_PASS case=%0d invalid_config_kind=%0d recovered",case_number,kind);case_number++;
    end

    for(int fault=1;fault<=5;fault++)begin
      defaults();accept_config();send_packet(0,fault,raw_words[0]);expect_error=1;
      complete(1);good_recovery();
      $display("ROW_BOUNDARY_PASS case=%0d projection_fault=%0d recovered",case_number,fault);case_number++;
    end

    for(int fault=0;fault<3;fault++)begin
      defaults();accept_config();
      if(fault!=2)begin send_packet(0,0,0);receive_packet(0,0,0,0,0);end
      complete(1,fault==0,fault==1);good_recovery();
      $display("ROW_BOUNDARY_PASS case=%0d completion_fault=%0d recovered",case_number,fault);case_number++;
    end
    if(case_number!=18 || errors!=14 || success_packets!=23)$fatal(1,"ROW_BOUNDARY_WRONG_TOTAL cases=%0d errors=%0d packets=%0d",case_number,errors,success_packets);
    $display("ROW_BOUNDARY_ALL_PASS cases=18 errors=14 success_packets=23 external_resets=1");$finish;
  end
endmodule
