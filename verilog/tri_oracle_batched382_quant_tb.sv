`timescale 1ns/1ps
// Pure conversion boundaries from the production wrapper. No clocked compute
// or memory behavior is claimed by this arithmetic-only test.
module tri_oracle_batched382_quant_tb;
  tri_oracle_batched_gated380 dut (
    .clk(1'b0),.rst_n(1'b0),.cfg_valid(1'b0),.cfg_tag(32'b0),.cfg_tokens(5'b0),
    .cfg_feature_words(10'b0),.cfg_dense_rows(17'b0),.cfg_count(7'b0),
    .cfg_channels(1280'b0),.cfg_keep(1280'b0),.cfg_activation_base(64'b0),
    .cfg_weight_base(64'b0),.cfg_up_weight_base(64'b0),.cfg_activation_stride(32'b0),
    .cfg_gate_shifts(96'b0),.cfg_up_shifts(96'b0),.cfg_down_shifts(96'b0),
    .out_ready(1'b0),.done_ready(1'b0),.req_ready(1'b0),
    .rsp_valid(1'b0),.rsp_last(1'b0),.rsp_error(1'b0),.rsp_data(64'b0));
  logic signed [31:0] values32[16];
  logic signed [15:0] values16[16];
  int checks=0;
  function automatic longint signed reference(input longint signed value,input int shift,bits);
    longint signed magnitude,rounded,limit;
    magnitude=value<0 ? -value : value;
    rounded=shift==0 ? magnitude : (magnitude+(64'sd1<<(shift-1)))>>shift;
    if(value<0)rounded=-rounded;
    limit=64'sd1<<(bits-1);
    if(rounded>=limit)return limit-1;
    if(rounded< -limit)return -limit;
    return rounded;
  endfunction
  task automatic check16(input logic signed [31:0] value,input int shift);
    if(dut.requantize16(value,6'(shift))!==16'(reference(64'($signed(value)),shift,16)))
      $fatal(1,"BATCH382_REQUANT16 value=%0d shift=%0d",value,shift);
    checks++;
  endtask
  task automatic check8(input logic signed [15:0] value,input int shift);
    if(dut.requantize8(value,6'(shift))!==8'(reference(64'($signed(value)),shift,8)))
      $fatal(1,"BATCH382_REQUANT8 value=%0d shift=%0d",value,shift);
    checks++;
  endtask
  initial begin
    longint signed half;
    values32='{32'sh80000000,32'sh7fffffff,-65536,65535,-32769,32768,-32768,32767,
               -129,128,-128,127,-2,-1,0,1};
    values16='{-32768,32767,-257,256,-256,255,-129,128,-128,127,-2,-1,0,1,2,3};
    #2;
    for(int shift=0;shift<64;shift++)for(int i=0;i<16;i++)begin
      check16(values32[i],shift);check8(values16[i],shift);
    end
    for(int shift=1;shift<=31;shift++)begin
      half=64'sd1<<(shift-1);
      for(int delta=-1;delta<=1;delta++)begin
        check16(32'(half+delta),shift);check16(32'(-half+delta),shift);
      end
    end
    for(int shift=1;shift<=15;shift++)begin
      half=64'sd1<<(shift-1);
      for(int delta=-1;delta<=1;delta++)begin
        check8(16'(half+delta),shift);check8(16'(-half+delta),shift);
      end
    end
    if(checks!=2324)$fatal(1,"BATCH382_INVENTORY");
    $display("BATCH382_QUANT_PASS shifts=64 exact_comparisons=2324 signed_minima_rounding_ties_saturation=1");$finish;
  end
endmodule
