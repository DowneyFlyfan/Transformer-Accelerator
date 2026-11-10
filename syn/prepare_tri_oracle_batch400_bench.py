"""Reuse the frozen feedforward scoreboard with raw residuals and sign reads."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def integrated_bench():
    source = (ROOT / "verilog/tri_oracle_batched393_tb.sv").read_text()

    def replace(before, after):
        nonlocal source
        assert source.count(before) == 1, before
        source = source.replace(before, after)

    replace("module tri_oracle_batched393_tb;", "module tri_oracle_batched400_predictive_tb;")
    replace("tri_oracle_batched_frame393 dut(.*);", "tri_oracle_batched_predictive400 dut(.*);")
    replace("""  logic mask_valid=0,mask_last=0;
  wire mask_ready;
  logic [31:0] mask_tag=0;
  logic [15:0] mask_start=0;
  logic [6:0] mask_count=0;
  logic [1279:0] mask_bits=0;""", """  localparam logic [63:0] GATE_SIGN_BASE=64'h0000000bffffff00;
  localparam logic [63:0] UP_SIGN_BASE=64'h0000000dffffff00;
  logic [63:0] cfg_gate_sign_base=0,cfg_up_sign_base=0;
  logic [31:0] cfg_epsilon_q16=0;
  logic stats_valid=0,stats_last=0,replay_valid=0,replay_last=0;
  wire stats_ready,replay_ready;
  wire [3:0] residual_token;
  logic [127:0] stats_data=0,replay_data=0;
  int sign_requests=0,contended_cycles=0,valid_masks=0,abort_masks=0;
  bit verify_held_second=0,held_second_retired=0;
  logic [1279:0] held_second;
  localparam int SIGN_BYTES=INTERMEDIATE*HIDDEN/8;""")
    replace("""  function automatic bit kept(input int token,channel);
    if(TRAINED)return fixture_keep[token*INTERMEDIATE+channel]!=0;
    return channel!=7 && (token+channel)%5!=0;
  endfunction""", """  function automatic bit kept(input int token,channel);
    int gate_margin,up_margin,positive,negative;
    // Two equal, opposite nonzero residuals have normalized magnitude
    // sqrt(HIDDEN/2), above three in this literal fixture.
    positive=token+1;
    negative=HIDDEN-token-1;
    gate_margin=2*(int'(gate_weight(channel,positive)>=0)+int'(gate_weight(channel,negative)<0))-2;
    up_margin=2*(int'(up_weight(channel,positive)>=0)+int'(up_weight(channel,negative)<0))-2;
    return !(gate_margin<=0 && up_margin==0);
  endfunction
  function automatic bit sign_address(input logic [63:0] address);
    return (address>=GATE_SIGN_BASE && address<GATE_SIGN_BASE+64'(SIGN_BYTES)) ||
           (address>=UP_SIGN_BASE && address<UP_SIGN_BASE+64'(SIGN_BYTES));
  endfunction
  function automatic bit sign_fault_address(input logic [63:0] address);
    return (FAULT==4 && sign_address(address)) ||
           ((FAULT==7 || FAULT==11) && address>=GATE_SIGN_BASE+64'((FAULT==7 ? 12 : 20)*HIDDEN) &&
            address<GATE_SIGN_BASE+64'(SIGN_BYTES));
  endfunction
  function automatic logic [127:0] raw_strip(input int token,strip);
    raw_strip=0;
    for(int lane=0;lane<8;lane++)begin
      if(strip*8+lane==token+1)raw_strip[16*lane+:16]=16'sd1200;
      if(strip*8+lane==HIDDEN-token-1)raw_strip[16*lane+:16]=-16'sd1200;
    end
  endfunction""")
    replace("""      (FAULT==3 && read_address>=DOWN_BASE+64'(160*INTERMEDIATE) && read_address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE)));""",
        """      (FAULT==3 && read_address>=DOWN_BASE+64'(160*INTERMEDIATE) && read_address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE)) ||
      sign_fault_address(read_address));""")
    replace("  wire wr_rsp_valid=write_response;",
            "  wire wr_rsp_valid=write_response && (!(inject_fault && FAULT==11) || fault_seen);")
    replace("    if(current>=ACT_BASE && current<ACT_BASE+64'(TOKENS*HIDDEN))begin",
        """    if(sign_address(current))begin
      offset=int'(current-(current>=UP_SIGN_BASE ? UP_SIGN_BASE : GATE_SIGN_BASE))/8;
      row=(offset/(HIDDEN/2))*32;
      feature=2*(offset%(HIDDEN/2));
      for(int b=0;b<64;b++)
        rsp_data[b]=current>=UP_SIGN_BASE ? up_weight(row+b%32,feature+b/32)<0 :
                                          gate_weight(row+b%32,feature+b/32)<0;
    end else if(current>=ACT_BASE && current<ACT_BASE+64'(TOKENS*HIDDEN))begin""")
    replace("    cfg_intermediate_base=SCRATCH_BASE;cfg_activation_stride=HIDDEN;",
        """    cfg_intermediate_base=SCRATCH_BASE;cfg_activation_stride=HIDDEN;
    cfg_gate_sign_base=GATE_SIGN_BASE;cfg_up_sign_base=UP_SIGN_BASE;cfg_epsilon_q16=0;
    if(inject_fault && FAULT==8)cfg_intermediate_base=GATE_SIGN_BASE;
    if(inject_fault && FAULT==9)cfg_output_features=0;
    if(inject_fault && FAULT==10)cfg_activation_stride=HIDDEN+1;""")
    replace("    cfg_output_features='1;cfg_activation_base='1;cfg_gate_base='1;cfg_up_base='1;cfg_down_base='1;",
        """    cfg_output_features='1;cfg_activation_base='1;cfg_gate_base='1;cfg_up_base='1;cfg_down_base='1;
    cfg_gate_sign_base='1;cfg_up_sign_base='1;cfg_epsilon_q16='1;""")
    start = source.index("  task automatic send_masks;")
    end = source.index("  always @(posedge clk)if(rst_n)begin: bus_and_scoreboard", start)
    source = source[:start] + """  task automatic send_residuals;
    if(inject_fault && (FAULT==5 || FAULT==6 || FAULT==8 || FAULT==9 || FAULT==10))begin
      repeat(16)@(negedge clk);
      if(!done_valid || !done_error || req_valid || stats_ready || replay_ready)
        $fatal(1,"BATCH400_INVALID_DESCRIPTOR_WAITED_FOR_RESIDUAL");
      return;
    end
    for(int token=0;token<TOKENS;token++)begin
      for(int strip=0;strip<HIDDEN/8;strip++)begin
        stats_valid=1;stats_last=strip==HIDDEN/8-1;stats_data=raw_strip(token,strip);
        while(!stats_ready)begin
          if(done_valid)begin stats_valid=0;return;end
          @(negedge clk);
        end
        @(posedge clk);if(residual_token!==4'(token))$fatal(1,"BATCH400_STATS_TOKEN");
        @(negedge clk);
      end
      stats_valid=0;stats_data='1;
      for(int strip=0;strip<HIDDEN/8;strip++)begin
        replay_valid=1;replay_last=strip==HIDDEN/8-1;replay_data=raw_strip(token,strip);
        while(!replay_ready)begin
          if(done_valid)begin replay_valid=0;return;end
          @(negedge clk);
        end
        @(posedge clk);if(residual_token!==4'(token))$fatal(1,"BATCH400_REPLAY_TOKEN");
        @(negedge clk);
      end
      replay_valid=0;replay_data='1;
    end
  endtask
""" + source[end:]
    assert source.count("fork send_masks();wait(done_valid);join") == 2
    source = source.replace("fork send_masks();wait(done_valid);join", "fork send_residuals();wait(done_valid);join")
    replace("    cycle<=cycle+1;", """    cycle<=cycle+1;
    if(dut.compute_req_valid && dut.predict_req_valid)contended_cycles++;
    if(verify_held_second)begin
      if(!dut.compute_mask_valid || dut.compute_mask_count!=80 || dut.packet_mask_start!=80 ||
         dut.packet_mask_bits!==held_second)$fatal(1,"BATCH400_HELD_SECOND_CHANGED");
      if(dut.compute_mask_ready)begin verify_held_second=0;held_second_retired=1;end
    end
    if(dut.compute_mask_valid && dut.compute_mask_ready)begin
      if(dut.compute_mask_count==0)abort_masks++;
      else begin
        if(dut.packet_mask_start!=16'(valid_masks*80))$fatal(1,"BATCH400_MASK_ORDER");
        for(int token=0;token<TOKENS;token++)
          for(int row=0;row<int'(dut.compute_mask_count);row++)
            if(dut.packet_mask_bits[token*80+row]!==kept(token,valid_masks*80+row))
              $fatal(1,"BATCH400_MASK_BIT token=%0d channel=%0d",token,valid_masks*80+row);
        valid_masks++;
      end
    end
    if(dut.compute_rsp_valid && dut.predict_rsp_valid)$fatal(1,"BATCH400_DUAL_RESPONSE");""")
    replace("      end else if(!((req_address>=ACT_BASE && req_address<ACT_BASE+64'(TOKENS*HIDDEN)) ||",
        """      end else if(sign_address(req_address))begin
        if(req_length!=1)$fatal(1,"BATCH400_SIGN_BURST");
        sign_requests++;
      end else if(!((req_address>=ACT_BASE && req_address<ACT_BASE+64'(TOKENS*HIDDEN)) ||""")
    replace("      read_active<=1;read_address<=req_address;read_beat<=0;read_length<=int'(req_length);read_bubble<=0;read_requests++;",
        """      read_active<=1;read_address<=req_address;read_beat<=0;read_bubble<=0;read_requests++;
      if(inject_fault && !fault_seen && sign_fault_address(req_address))begin
        read_length<=2;
        if(FAULT==11)begin
          if(!dut.compute_mask_valid || dut.compute_mask_ready || dut.packet_mask_start!=80)
            $fatal(1,"BATCH400_NO_HELD_SECOND_AT_FAULT");
          verify_held_second=1;
          held_second=dut.packet_mask_bits;
        end
      end
      else read_length<=int'(req_length);""")
    replace("{cfg_ready,mask_ready,req_valid,rsp_ready,wr_req_valid,wr_data_valid,wr_rsp_ready,out_valid,done_valid}",
            "{cfg_ready,stats_ready,replay_ready,req_valid,rsp_ready,wr_req_valid,wr_data_valid,wr_rsp_ready,out_valid,done_valid}")
    replace("""      if((FAULT<4 && !fault_seen) || seen!=(FAULT==3 ? TOKENS : 0) || (FAULT>=4 && (read_requests!=0 || write_requests!=0)))$fatal(1,"BATCH393_EXPECTED_FAULT_PHASE");""",
        """      if(((FAULT<=4 || FAULT==7 || FAULT==11) && !fault_seen) || seen!=(FAULT==3 ? TOKENS : 0) ||
          (FAULT==4 && (sign_requests!=1 || read_beats!=2 || valid_masks!=0)) ||
          ((FAULT==5 || FAULT==6 || FAULT==8 || FAULT==9 || FAULT==10) &&
            (read_requests!=0 || write_requests!=0)) ||
          (FAULT==7 && (valid_masks!=1 || abort_masks!=1 || write_requests!=TOKENS)) ||
          (FAULT==11 && (!held_second_retired || valid_masks!=2 || abort_masks!=1 || write_requests!=2*TOKENS)))
        $fatal(1,"BATCH400_EXPECTED_FAULT_PHASE");
      if(FAULT==11)$display("BATCH400_HELD_SECOND_RETIRED_BEFORE_ABORT");
      $display("BATCH400_FAULT fault=%0d sign_requests=%0d valid_masks=%0d abort_masks=%0d writes=%0d",
        FAULT,sign_requests,valid_masks,abort_masks,write_requests);""")
    replace("      inject_fault=0;seen=0;read_requests=0;read_beats=0;write_requests=0;write_bytes=0;",
        """      inject_fault=0;seen=0;read_requests=0;read_beats=0;write_requests=0;write_bytes=0;
      sign_requests=0;valid_masks=0;abort_masks=0;contended_cycles=0;""")
    replace("    $display(\"BATCH393_PASS tokens=", """    if(sign_requests!=TOKENS*(INTERMEDIATE/32)*4 || valid_masks!=GATE_GROUPS || abort_masks!=0 ||
        (INTERMEDIATE>=192 && contended_cycles==0))$fatal(1,"BATCH400_SHARED_BUS_INVENTORY");
    $display("BATCH400_SHARED_BUS sign_requests=%0d valid_masks=%0d contended_cycles=%0d",
      sign_requests,valid_masks,contended_cycles);
    $display("BATCH393_PASS tokens=""")
    return source.replace("BATCH393_", "BATCH400_")


def hierarchy_bench():
    source = (ROOT / "verilog/tri_oracle_batch357_hierarchy.sv").read_text()
    assert source.count("activations!=40") == source.count("compiled_memories=600") == 1
    return source.replace("activations!=40", "activations!=42").replace("compiled_memories=600", "compiled_memories=602")


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(integrated_bench())
