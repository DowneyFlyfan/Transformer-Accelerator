`timescale 1ns/1ps
module tri_oracle_prediction_packet_stream_tb;
  logic clk=0;always #5 clk=~clk;
  logic rst_n=0,cfg_valid=0,in_valid=0,in_last=0,in_group_last=0;
  logic [31:0] cfg_tag=0;
  logic [9:0] cfg_features=0;
  logic [16:0] cfg_dense_rows=0;
  logic [10:0] in_group=0;
  logic [127:0] norm_activations=0;
  logic [255:0] gate_weight_signs=0,up_weight_signs=0;
  wire cfg_ready,in_ready,out_valid,out_last,out_error,out_fallback;
  wire [31:0] out_tag;
  wire [7:0] out_count;
  wire [2559:0] out_channels;
  int cycle=0,completed=0,total=0,seen=0,expected_ids[65536],features=0,dense=0,pattern=0;
  int good_stalls=0,error_stalls=0;
  bit frame_done=0,expect_error=0,held=0,force_hold=0;
  logic [31:0] tag=0;
  logic [2602:0] saved_packet=0;
  wire out_ready=!force_hold && cycle%23>=11;
  tri_oracle_prediction_packet_stream dut(.*);
  function automatic bit keep(input int channel,mode);
    case(mode)
      0:return channel%2==0;
      1:return 1;
      2:return channel==0 || channel==33;
      default:return 0;
    endcase
  endfunction
  always @(posedge clk) begin: scoreboard
    int amount,value;
    cycle<=cycle+1;
    if(!rst_n) held=0;
    else begin
      if(held && (!out_valid || {out_last,out_error,out_fallback,out_tag,out_count,out_channels}!==saved_packet))
        $fatal(1,"PREDICTION_PACKET_STALLED_CHANGE");
      if(out_valid && !out_ready) begin
        saved_packet={out_last,out_error,out_fallback,out_tag,out_count,out_channels};
        if(out_error) error_stalls++;else good_stalls++;
      end
      held=out_valid && !out_ready;
    end
    if(rst_n && out_valid && out_ready) begin
      if(out_tag!==tag || out_error!==expect_error || out_fallback!==0) $fatal(1,"PREDICTION_PACKET_METADATA");
      amount=expect_error?0:(total-seen>160?160:total-seen);
      if(out_count!==8'(amount) || out_last!==(expect_error || seen+amount==total))
        $fatal(1,"PREDICTION_PACKET_SHAPE seen=%0d total=%0d count=%0d",seen,total,out_count);
      for(int i=0;i<160;i++) begin
        value=i<amount?expected_ids[seen+i]:0;
        if($test$plusargs("CORRUPT_PACKET_REFERENCE") && i==0 && amount>0) value++;
        if(out_channels[i*16+:16]!==16'(value)) $fatal(1,"PREDICTION_PACKET_ID row=%0d",seen+i);
      end
      seen+=amount;
      if(out_last) begin frame_done=1;completed++;end
    end
  end
  task automatic configure(input int rows,strips,mode,input bit bad=0);
    begin
      @(negedge clk);while(!cfg_ready) @(negedge clk);
      dense=rows;features=strips;pattern=mode;expect_error=bad;frame_done=0;seen=0;total=0;tag=32'h10000000+32'(completed);
      if(bad) force_hold=1;
      for(int i=0;i<rows;i++) if(keep(i,mode)) begin expected_ids[total]=i;total++;end
      cfg_tag=tag;cfg_features=10'(strips);cfg_dense_rows=17'(rows);cfg_valid=1;
      @(posedge clk);if(!cfg_ready) $fatal(1,"PREDICTION_PACKET_CONFIG");
      @(negedge clk);cfg_valid=0;cfg_tag='1;cfg_features=0;cfg_dense_rows=0;
    end
  endtask
  task automatic group(input int index,input bit malformed=0);
    begin
      for(int strip=0;strip<features;strip++) begin
        @(negedge clk);in_valid=1;in_last=strip==features-1;in_group=11'(malformed?index+1:index);
        in_group_last=index==dense/32-1;norm_activations={8{16'd1024}};
        for(int row=0;row<32;row++) begin
          gate_weight_signs[row*8+:8]=keep(index*32+row,pattern)?8'h00:8'h55;
          up_weight_signs[row*8+:8]=gate_weight_signs[row*8+:8];
        end
        @(posedge clk);while(!in_ready) @(posedge clk);
        @(negedge clk);in_valid=0;in_group='1;norm_activations='1;gate_weight_signs='1;up_weight_signs='1;
      end
    end
  endtask
  task automatic finish_frame;
    int timeout;
    begin
      if(expect_error) begin wait(out_valid);repeat(11) @(negedge clk);force_hold=0;end
      timeout=0;while(!frame_done && timeout<3000) begin @(negedge clk);timeout++;end
      if(!frame_done) $fatal(1,"PREDICTION_PACKET_COMPLETION_TIMEOUT");
      $display("PREDICTION_PACKET_CASE_PASS case=%0d rows=%0d selected=%0d error=%0d",completed,dense,seen,expect_error);$fflush();
    end
  endtask
  task automatic frame(input int rows,strips,mode);
    configure(rows,strips,mode);
    for(int g=0;g<rows/32;g++) group(g);
    finish_frame();
  endtask
  initial begin
    repeat(3) @(negedge clk);rst_n=1;
    frame(5632,256,0);
    frame(320,3,1);
    frame(64,1,2);
    frame(32,1,3);
    configure(31,1,0,1);finish_frame();
    configure(32,0,0,1);finish_frame();
    configure(64,3,0,1);group(0,1);finish_frame();
    // Cancel a previously accepted prefix while another compactor packet is
    // buffered. First hold the complete160-ID packet for a sustained stall.
    force_hold=1;configure(320,3,1);
    for(int g=0;g<6;g++) group(g);
    wait(out_valid);repeat(11) @(negedge clk);force_hold=0;
    wait(seen==160);@(negedge clk);expect_error=1;force_hold=1;
    group(6,1);finish_frame();
    repeat(8) begin @(negedge clk);if(out_valid) $fatal(1,"PREDICTION_PACKET_IDS_AFTER_TERMINAL_ERROR");end
    force_hold=1;configure(32,1,1);group(0);wait(out_valid);
    @(negedge clk);rst_n=0;repeat(3) @(negedge clk);rst_n=1;force_hold=0;
    frame(64,2,2);
    if(completed!=9 || good_stalls<11 || error_stalls<11)
      $fatal(1,"PREDICTION_PACKET_COVERAGE cases=%0d success=%0d error=%0d",completed,good_stalls,error_stalls);
    $display("PREDICTION_PACKET_PASS cases=%0d success_stalls=%0d error_stalls=%0d",completed,good_stalls,error_stalls);$finish;
  end
  initial begin #10000000;$fatal(1,"PREDICTION_PACKET_WATCHDOG");end
endmodule
