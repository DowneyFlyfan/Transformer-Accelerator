"""Score compute using only activations written by the learned frontend."""

from pathlib import Path
import sys

from prepare_tri_oracle_batch400_bench import integrated_bench


def learned_bench():
    source = integrated_bench()

    def replace(before, after):
        nonlocal source
        assert source.count(before) == 1, before
        source = source.replace(before, after)

    replace("module tri_oracle_batched400_predictive_tb;", "module tri_oracle_batched406_learned_tb;")
    replace("tri_oracle_batched_predictive400 dut(.*);", "tri_oracle_batched_learned406 dut(.*);")
    replace("64'h00000001ffffc000", "64'h00000001ffffffc0")
    replace("  logic [127:0] stats_data=0,replay_data=0;", """  logic [127:0] stats_data=0,replay_data=0,replay_gamma=0;
  logic [95:0] cfg_activation_shifts=0;
  localparam int ACT_STRIDE=HIDDEN+64;
  localparam int ACT_SPAN=(TOKENS-1)*ACT_STRIDE+HIDDEN;
  byte unsigned activation_memory[TOKENS*HIDDEN];
  bit activation_committed[TOKENS*HIDDEN];
  int activation_golden[TOKENS][HIDDEN];
  int activation_bytes=0,activation_acks=0,activation_requests=0,normalizer_starts=0;
  bit write_is_activation=0;""")
    replace("""    if(TRAINED)return int'($signed(fixture_activation[token*HIDDEN+feature]));
    return (token*7+feature*3)%19-9;""", """    return activation_golden[token][feature];""")
    replace("""    raw_strip=0;
    for(int lane=0;lane<8;lane++)begin
      if(strip*8+lane==token+1)raw_strip[16*lane+:16]=16'sd1200;
      if(strip*8+lane==HIDDEN-token-1)raw_strip[16*lane+:16]=-16'sd1200;
    end
  endfunction""", """    for(int lane=0;lane<8;lane++)raw_strip[16*lane+:16]=16'(residual_value(token,strip*8+lane));
  endfunction
  function automatic int residual_value(input int token,feature);
    if(feature==token+1)return 1200;
    if(feature==HIDDEN-token-1)return -1200;
    return (token*29+feature*11)%61-30;
  endfunction
  function automatic int gamma_value(input int feature);
    return ((feature*13)%23-11)*97+1024;
  endfunction
  function automatic bit activation_address(input logic [63:0] address);
    return address>=ACT_BASE && address<ACT_BASE+64'(ACT_SPAN);
  endfunction""")
    replace("  wire wr_rsp_valid=write_response && (!(inject_fault && FAULT==11) || fault_seen);",
            """  wire wr_rsp_valid=write_response &&
    (write_is_activation || !(inject_fault && FAULT==11) || fault_seen);""")
    replace("  wire wr_rsp_error=inject_fault && FAULT==1 && !fault_seen;",
        """  wire wr_rsp_error=inject_fault && !fault_seen &&
    ((!write_is_activation && FAULT==1) ||
     (write_is_activation && ((FAULT==12 && activation_requests==1) ||
                               (FAULT==13 && activation_bytes==TOKENS*HIDDEN))));""")
    replace("""    end else if(current>=ACT_BASE && current<ACT_BASE+64'(TOKENS*HIDDEN))begin
      offset=int'(current-ACT_BASE);token=offset/HIDDEN;feature=offset%HIDDEN;
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=8'(activation(token,feature+b));""",
        """    end else if(activation_address(current))begin
      offset=int'(current-ACT_BASE);token=offset/ACT_STRIDE;feature=offset%ACT_STRIDE;
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=activation_memory[token*HIDDEN+feature+b];""")
    replace("    cfg_intermediate_base=SCRATCH_BASE;cfg_activation_stride=HIDDEN;",
            "    cfg_intermediate_base=SCRATCH_BASE;cfg_activation_stride=ACT_STRIDE;")
    replace("    if(inject_fault && FAULT==10)cfg_activation_stride=HIDDEN+1;",
            """    if(inject_fault && FAULT==10)cfg_activation_stride=HIDDEN+1;
    if(inject_fault && FAULT==14)cfg_activation_base=GATE_BASE;
    if(inject_fault && FAULT==15)cfg_activation_base=GATE_SIGN_BASE;
    for(int token=0;token<TOKENS;token++)cfg_activation_shifts[6*token+:6]=6'(14+token%2);""")
    replace("    cfg_gate_sign_base='1;cfg_up_sign_base='1;cfg_epsilon_q16='1;",
            "    cfg_gate_sign_base='1;cfg_up_sign_base='1;cfg_epsilon_q16='1;cfg_activation_shifts='1;")
    replace("if(inject_fault && (FAULT==5 || FAULT==6 || FAULT==8 || FAULT==9 || FAULT==10))begin",
            "if(inject_fault && (FAULT==5 || FAULT==6 || FAULT==8 || FAULT==9 || FAULT==10 || FAULT==14 || FAULT==15))begin")
    replace("        replay_valid=1;replay_last=strip==HIDDEN/8-1;replay_data=raw_strip(token,strip);",
        """        replay_valid=1;replay_last=strip==HIDDEN/8-1;replay_data=raw_strip(token,strip);
        if(inject_fault && FAULT==16 && token==0 && replay_last)replay_data[15:0]=16'sd32000;
        for(int lane=0;lane<8;lane++)replay_gamma[16*lane+:16]=16'(gamma_value(strip*8+lane));""")
    replace("      replay_valid=0;replay_data='1;", "      replay_valid=0;replay_data='1;replay_gamma='x;")
    replace("    cycle<=cycle+1;", """    cycle<=cycle+1;
    if(dut.predictor.activation_path.cfg_valid && dut.predictor.activation_path.cfg_ready)normalizer_starts++;
    if(dut.compute_started && (dut.predict_wr_req_valid || dut.predict_wr_data_valid || dut.predict_wr_rsp_ready))
      $fatal(1,"BATCH406_WRITE_OWNER_CHANGED");
    if(!dut.compute_started && (dut.compute_wr_req_valid || dut.compute_wr_data_valid || dut.compute_wr_rsp_ready))
      $fatal(1,"BATCH406_COMPUTE_WROTE_BEFORE_ACTIVATION");""")
    replace("""      if(read_active || req_length==0 || req_length>16 || req_address[2:0]!=0)$fatal(1,"BATCH400_READ_REQUEST");
      if(req_address>=SCRATCH_BASE""",
        """      if(read_active || req_length==0 || req_length>16 || req_address[2:0]!=0)$fatal(1,"BATCH400_READ_REQUEST");
      if(activation_acks!=TOKENS*HIDDEN)$fatal(1,"BATCH406_READ_BEFORE_ACTIVATION_ACK");
      if(activation_address(req_address))begin
        offset=int'(req_address-ACT_BASE);token=offset/ACT_STRIDE;row=offset%ACT_STRIDE;
        if(row+int'(req_length)*8>HIDDEN)$fatal(1,"BATCH406_ACTIVATION_PADDING_READ");
        for(int b=0;b<int'(req_length)*8;b++)
          if(!activation_committed[token*HIDDEN+row+b])$fatal(1,"BATCH406_UNCOMMITTED_ACTIVATION_READ");
      end else if(req_address>=SCRATCH_BASE""")
    replace("end else if(!((req_address>=ACT_BASE && req_address<ACT_BASE+64'(TOKENS*HIDDEN)) ||",
            "end else if(!(")
    start = source.index("    if(wr_req_valid && wr_req_ready)begin")
    end = source.index("    if(held_read_req", start)
    source = source[:start] + """    if(wr_req_valid && wr_req_ready)begin
      if(write_active || write_response || wr_length==0 || wr_address[2:0]!=0)
        $fatal(1,"BATCH406_WRITE_REQUEST");
      write_is_activation<=activation_address(wr_address);
      if(activation_address(wr_address))begin
        token=activation_bytes/HIDDEN;row=activation_bytes%HIDDEN;
        if(token>=TOKENS || wr_address!==ACT_BASE+64'(token)*ACT_STRIDE+64'(row) ||
           int'(wr_length)*8!=(HIDDEN-row>128 ? 128 : HIDDEN-row))
          $fatal(1,"BATCH406_ACTIVATION_WRITE_ADDRESS");
        activation_requests++;
      end else begin
        if(activation_acks!=TOKENS*HIDDEN || wr_length>10 ||
           wr_address<SCRATCH_BASE || wr_address+64'(wr_length)*8>SCRATCH_BASE+64'(TOKENS*INTERMEDIATE))
          $fatal(1,"BATCH406_INTERMEDIATE_WRITE_ADDRESS");
        offset=int'(wr_address-SCRATCH_BASE);row=offset%INTERMEDIATE;
        if(row%80!=0 || int'(wr_length)*8!=(INTERMEDIATE-row>80 ? 80 : INTERMEDIATE-row))
          $fatal(1,"BATCH400_WRITE_TILE_ADDRESS");
        write_requests++;
      end
      write_active<=1;write_address<=wr_address;write_beat<=0;write_length<=int'(wr_length);
    end
    if(wr_data_valid && wr_data_ready)begin
      if(!write_active || wr_strobe!==8'hff || wr_data_last!==(write_beat+1==write_length))
        $fatal(1,"BATCH400_WRITE_DATA_PROTOCOL");
      if(write_is_activation)begin
        for(int b=0;b<8;b++)begin
          token=(activation_bytes+b)/HIDDEN;row=(activation_bytes+b)%HIDDEN;
          if(wr_data[b*8+:8]!==8'(activation_golden[token][row]))
            $fatal(1,"BATCH406_GENERATED_ACTIVATION token=%0d feature=%0d got=%h expected=%h",
              token,row,wr_data[b*8+:8],8'(activation_golden[token][row]));
          activation_memory[activation_bytes+b]=wr_data[b*8+:8];
        end
        activation_bytes+=8;
      end else begin
        offset=int'(write_address-SCRATCH_BASE)+write_beat*8;
        for(int b=0;b<8;b++)begin
          token=(offset+b)/INTERMEDIATE;row=(offset+b)%INTERMEDIATE;
          if(wr_data[b*8+:8]!==8'(golden_down[token][row]))
            $fatal(1,"BATCH400_GATED_INTERMEDIATE token=%0d channel=%0d",token,row);
          scratch[offset+b]=wr_data[b*8+:8];writes[offset+b]++;write_bytes++;
        end
      end
      if(wr_data_last)begin write_active<=0;response_delay<=3;end
      else write_beat<=write_beat+1;
    end
    if(response_delay>0)begin response_delay<=response_delay-1;if(response_delay==1)write_response<=1;end
    if(wr_rsp_valid && wr_rsp_ready)begin
      if(wr_rsp_error)fault_seen<=1;
      else if(write_is_activation)begin
        for(int b=0;b<write_length*8;b++)activation_committed[activation_acks+b]=1;
        activation_acks+=write_length*8;
      end else for(int b=0;b<write_length*8;b++)committed[int'(write_address-SCRATCH_BASE)+b]=1;
      write_response<=0;
    end
""" + source[end:]
    replace("    int gate_dot,up_dot,gated;", """    int gate_dot,up_dot,gated,norm_code;
    real energy,scaled;""")
    replace("    end else for(int token=0;token<TOKENS;token++)begin",
        """    end else for(int token=0;token<TOKENS;token++)begin
      energy=0.0;
      for(int feature=0;feature<HIDDEN;feature++)energy+=real'(residual_value(token,feature)**2);
      for(int feature=0;feature<HIDDEN;feature++)begin
        scaled=256.0*residual_value(token,feature)/$sqrt(energy/HIDDEN);
        norm_code=scaled>=0.0 ? $rtoi(scaled+0.5) : -$rtoi(-scaled+0.5);
        if((norm_code>768 || norm_code< -768)!=(feature==token+1 || feature==HIDDEN-token-1))
          $fatal(1,"BATCH406_LITERAL_OUTLIER_FIXTURE");
        activation_golden[token][feature]=quant(norm_code*gamma_value(feature),14+token%2,8);
      end""")
    replace("      if(FAULT==11)$display", """      if((FAULT==12 && (!fault_seen || activation_requests!=1 || activation_acks!=0 ||
           sign_requests!=0 || write_requests!=0 || valid_masks!=0)) ||
         (FAULT==13 && (!fault_seen || activation_bytes!=TOKENS*HIDDEN ||
           activation_acks!=TOKENS*HIDDEN-((HIDDEN-1)%128+1) || sign_requests!=0 || write_requests!=0 || valid_masks!=0)) ||
         (FAULT==16 && (activation_requests!=1 || activation_acks!=128 ||
           sign_requests!=0 || write_requests!=0 || valid_masks!=0)) ||
         ((FAULT==5 || FAULT==6 || FAULT==8 || FAULT==9 || FAULT==10 || FAULT==14 || FAULT==15) &&
           (activation_requests!=0 || read_requests!=0 || normalizer_starts!=0)))
        $fatal(1,"BATCH406_ACTIVATION_FAULT_INVENTORY");
      $display("BATCH406_ACTIVATION_FAULT fault=%0d activation_acks=%0d activation_requests=%0d sign_reads=%0d",
        FAULT,activation_acks,activation_requests,sign_requests);
      if(FAULT==11)$display""")
    replace("      sign_requests=0;valid_masks=0;abort_masks=0;contended_cycles=0;",
        """      sign_requests=0;valid_masks=0;abort_masks=0;contended_cycles=0;
      activation_bytes=0;activation_acks=0;activation_requests=0;normalizer_starts=0;
      foreach(activation_committed[i])begin activation_committed[i]=0;activation_memory[i]='x;end""")
    replace("    $display(\"BATCH400_SHARED_BUS ", """    if(activation_bytes!=TOKENS*HIDDEN || activation_acks!=activation_bytes ||
       activation_requests!=TOKENS*((HIDDEN+127)/128) || normalizer_starts!=TOKENS)
      $fatal(1,"BATCH406_ACTIVATION_FINAL_INVENTORY");
    $display("BATCH406_ACTIVATION_PASS bytes=%0d bursts=%0d normalizations=%0d",
      activation_acks,activation_requests,normalizer_starts);
    $display("BATCH400_SHARED_BUS """)
    return source.replace("BATCH400_", "BATCH406_")


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(learned_bench())
