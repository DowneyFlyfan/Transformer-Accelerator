`timescale 1ns/1ps

// Controller boundary test; compute peer is a protocol/data model.
// Actual arrays/trained nonlinear execution require the mapped chip replay.
module tri_oracle_correction_frame_control_tb;
logic clk,rst_n,cfg_valid,cfg_correction_enable;
  logic cfg_ready;
  logic [31:0] cfg_tag;
  logic [4:0] cfg_tokens;
  logic [15:0] cfg_input_features,cfg_intermediate_features;
  logic [16:0] cfg_output_features;
  logic [63:0] cfg_activation_base,cfg_gate_base,cfg_up_base,cfg_down_base,cfg_intermediate_base;
  logic [31:0] cfg_activation_stride;
  logic [95:0] cfg_gate_shifts,cfg_up_shifts,cfg_down_shifts;
  logic mask_valid,mask_last;
  logic mask_ready;
  logic [31:0] mask_tag;
  logic [15:0] mask_start;
  logic [6:0] mask_count;
  logic [1279:0] mask_bits;
  logic out_valid;
  logic out_ready;
  logic [31:0] out_tag;
  logic [3:0] out_token;
  logic [15:0] out_start;
  logic [7:0] out_count;
  logic out_last;
  logic [5119:0] out_data;
  logic done_valid;
  logic done_ready;
  logic done_error;
  logic [31:0] done_tag;
  logic wr_req_valid;
  logic wr_req_ready;
  logic [63:0] wr_address;
  logic [4:0] wr_length;
  logic wr_data_valid;
  logic wr_data_ready;
  logic [63:0] wr_data;
  logic [7:0] wr_strobe;
  logic wr_data_last;
  logic wr_rsp_valid,wr_rsp_error;
  logic wr_rsp_ready;
  logic attention_enable,attention_cfg_valid;
  logic attention_cfg_ready;
  logic [31:0] attention_cfg_tag,attention_cfg_activation_stride;
  logic [4:0] attention_cfg_tokens;
  logic [9:0] attention_cfg_feature_words;
  logic [16:0] attention_cfg_dense_rows;
  logic [7:0] attention_cfg_count;
  logic [2559:0] attention_cfg_channels,attention_cfg_keep;
  logic [63:0] attention_cfg_activation_base,attention_cfg_weight_base;
  logic attention_out_ready,attention_done_ready;
  logic attention_out_valid,attention_out_last;
  logic [31:0] attention_out_tag;
  logic [3:0] attention_out_token;
  logic [7:0] attention_out_count;
  logic [2559:0] attention_out_channels;
  logic [5119:0] attention_out_data;
  logic attention_done_valid,attention_done_error;
  logic [31:0] attention_done_tag;
  logic compute_cfg_valid,compute_cfg_paired,compute_cfg_packed_weights;
  logic compute_ready;
  logic [31:0] compute_cfg_tag,compute_cfg_activation_stride;
  logic [4:0] compute_cfg_tokens;
  logic [9:0] compute_cfg_feature_words;
  logic [16:0] compute_cfg_dense_rows;
  logic [7:0] compute_cfg_count;
  logic [2559:0] compute_cfg_channels,compute_cfg_keep;
  logic [63:0] compute_cfg_activation_base,compute_cfg_weight_base,compute_cfg_up_weight_base;
  logic [95:0] compute_cfg_gate_shifts,compute_cfg_up_shifts,compute_cfg_down_shifts;
  logic compute_hold_primary,compute_append_correction,compute_clear_context;
  logic compute_out_valid,compute_last;
  logic compute_out_ready;
  logic [31:0] compute_tag;
  logic [3:0] compute_token;
  logic [7:0] compute_count;
  logic [2559:0] compute_channels;
  logic [5119:0] compute_data;
  logic [639:0] compute_down;
  logic compute_done_valid,compute_done_error;
  logic compute_done_ready;
  logic [31:0] compute_done_tag;
  localparam int Intermediate=96,Outputs=168,MaxTokens=16;
  localparam logic [63:0] ScratchBase=64'h600000;
  int cycle=0,tokens=2,fault=0,masks_sent=0,commands=0,write_requests=0,write_acks=0;
  int outputs_seen=0,frames=0,clear_seen=0,attention_cases=0,reset_cases=0;
  bit frame_active=0,expect_correction=0,expect_invalid=0,attention_probe=0;
  bit write_fault_seen=0;
  logic [63:0] scratch_base=ScratchBase;
  logic [7:0] scratch[0:2*MaxTokens*Intermediate-1];
  bit committed[0:2*MaxTokens*Intermediate-1],seen[0:MaxTokens-1][0:Outputs-1];
  logic [63:0] pending[0:9],pending_address;
  int pending_length=0,pending_beat=0,ack_delay=0;
  bit write_active=0,response_pending=0;
  typedef enum logic [1:0] {BackendIdle,BackendDelay,BackendOutput,BackendDone} backend_state_t;
  backend_state_t backend_state=BackendIdle;
  int backend_delay=0,result_token=0,result_tokens=0,result_count=0;
  bit result_paired=0,result_hold=0,result_append=0,result_attention=0;
  logic [31:0] result_tag;
  logic [2559:0] result_channels;
  logic [31:0] result_data[0:MaxTokens-1][0:159];
  bit context_valid=0;
  logic [31:0] context_tag;
  int context_tokens=0,context_count=0,context_first=0;
  logic held_output=0;
  logic [5180:0] held_packet;
  always #5 clk=~clk;

  tri_oracle_correction_frame_control dut (.*);

  function automatic integer gated(input integer channel,input integer token);
    if((channel+token)%7==0)return 0;
    case(channel%8)
      0:return 32767;
      1:return -32768;
      2:return 128+token;
      3:return -129-token;
      4:return 127;
      5:return -128;
      default:return (channel-48)*91+token*15;
    endcase
  endfunction
  function automatic integer wide_code(input integer value,input integer shift);
    integer magnitude,divisor;
    divisor=1<<shift;magnitude=value<0 ? -value : value;
    magnitude=(magnitude+divisor/2)/divisor;
    return value<0 ? -magnitude : magnitude;
  endfunction
  function automatic integer clip8(input integer value);
    return value>127 ? 127 : value< -128 ? -128 : value;
  endfunction
  function automatic integer weight(input integer output_row,input integer channel);
    return (output_row*13+channel*7)%9-4;
  endfunction
  function automatic integer expected_sum(input integer token,input integer output_row);
    integer value,coarse,correction,total;
    total=0;
    for(int channel=0;channel<Intermediate;channel++)begin
      value=wide_code(gated(channel,token),token%2);coarse=clip8(value);correction=clip8(value-coarse);
      total+=(coarse+(expect_correction ? correction : 0))*weight(output_row,channel);
    end
    return total;
  endfunction

  always_comb begin
    mask_valid=frame_active && !expect_invalid && masks_sent<2;
    mask_tag=cfg_tag;mask_start=16'(masks_sent*80);
    mask_count=masks_sent==0 ? 7'd80 : 7'd16;mask_last=masks_sent==1;mask_bits=0;
    for(int token=0;token<MaxTokens;token++)
      for(int row=0;row<80;row++)
        if(row<int'(mask_count))mask_bits[token*80+row]=(masks_sent*80+row+token)%7!=0;
    out_ready=cycle%7>=3;
    wr_req_ready=!write_active && !response_pending && ack_delay==0 && cycle%5>=2;
    wr_data_ready=write_active && cycle%7>=2;
    wr_rsp_valid=response_pending;
    wr_rsp_error=fault==2 && !write_fault_seen && pending_address>=scratch_base+64'(tokens*Intermediate);
    compute_ready=backend_state==BackendIdle && cycle%3!=0;
    compute_out_valid=backend_state==BackendOutput;
    compute_token=4'(result_token);compute_count=8'(result_count);compute_channels=result_channels;
    compute_tag=result_tag+(fault==1 && result_paired && result_token==0 ? 32'd1 : 32'd0);
    compute_last=result_token+1==result_tokens;
    compute_data=0;compute_down=0;
    for(int row=0;row<160;row++)begin
      if(row<result_count)begin
        if(result_paired)begin
          compute_data[row*32+:32]=32'(gated(int'(result_channels[row*16+:16]),result_token));
          if(row<80)compute_down[row*8+:8]=8'(clip8(wide_code(gated(int'(result_channels[row*16+:16]),result_token),result_token%2)));
        end else compute_data[row*32+:32]=result_data[result_token][row];
      end
    end
    compute_done_valid=backend_state==BackendDone;compute_done_tag=result_tag;
    compute_done_error=(fault==3 && !result_paired && result_hold) || (fault==4 && result_append);
  end

  always @(posedge clk)begin: backend_and_memory
    integer index,sum,plane,first_row;
    if(!rst_n)begin
      cycle<=0;backend_state<=BackendIdle;write_active<=0;response_pending<=0;ack_delay<=0;
      context_valid<=0;held_output<=0;
    end else begin
      cycle<=cycle+1;
      if(cycle>200000)$fatal(1,"CORRECTION_FRAME_TIMEOUT");
      if(backend_state!=BackendIdle && (compute_hold_primary!==result_hold || compute_append_correction!==result_append))
        $fatal(1,"CORRECTION_FRAME_COMMAND_FLAGS_CHANGED_WHILE_OWNED");
      if(compute_clear_context)begin
        if(backend_state!=BackendIdle)$fatal(1,"CORRECTION_FRAME_ABANDONED_COMPUTE");
        context_valid<=0;clear_seen++;
      end
      if(mask_valid && mask_ready)masks_sent<=masks_sent+1;
      if(compute_cfg_valid && compute_ready)begin
        commands++;
        if(!attention_probe)begin
          if(compute_cfg_feature_words!=(compute_cfg_paired ? 4 : 12) ||
             compute_cfg_dense_rows!=(compute_cfg_paired ? Intermediate : Outputs) ||
             compute_cfg_tokens!=5'(tokens) || !compute_cfg_packed_weights)
            $fatal(1,"CORRECTION_FRAME_COMPUTE_SHAPE");
          for(int token=0;token<tokens;token++)for(int row=0;row<int'(compute_cfg_count);row++)
            if(compute_cfg_keep[token*160+row]!==(!compute_cfg_paired ||
               (int'(compute_cfg_channels[row*16+:16])+token)%7!=0))$fatal(1,"CORRECTION_FRAME_MASK_NOT_PRESERVED");
        end
        result_tag<=compute_cfg_tag;result_tokens<=int'(compute_cfg_tokens);result_count<=int'(compute_cfg_count);
        result_channels<=compute_cfg_channels;result_token<=0;result_paired<=compute_cfg_paired;
        result_hold<=compute_hold_primary;result_append<=compute_append_correction;result_attention<=attention_probe;
        backend_delay<=3;backend_state<=BackendDelay;
        if(attention_probe)begin
          if(compute_hold_primary || compute_append_correction || compute_cfg_paired || compute_cfg_packed_weights)
            $fatal(1,"CORRECTION_FRAME_ATTENTION_MODE_CHANGED");
          for(int row=0;row<8;row++)result_data[0][row]<=32'h55aa0000+32'(row);
        end else if(compute_cfg_paired)begin
          if(compute_hold_primary || compute_append_correction)$fatal(1,"CORRECTION_FRAME_PAIRED_ACCUMULATION_MODE");
          if(compute_cfg_activation_base!=cfg_activation_base || compute_cfg_feature_words!=4 ||
             compute_cfg_dense_rows!=Intermediate || compute_cfg_tokens!=5'(tokens))$fatal(1,"CORRECTION_FRAME_GATE_DESCRIPTOR");
          context_valid<=0;
        end else begin
          for(int index=0;index<tokens*Intermediate*(expect_correction ? 2 : 1);index++)
            if(!committed[index])$fatal(1,"CORRECTION_FRAME_MISSING_CORRECTION_PLANE");
          if(compute_hold_primary!==(expect_correction && compute_cfg_activation_base==scratch_base) ||
             compute_append_correction!==(expect_correction && compute_cfg_activation_base==scratch_base+64'(tokens*Intermediate)))
            $fatal(1,"CORRECTION_FRAME_PRIMARY_OR_APPEND_MODE");
          for(int byte_index=0;byte_index<tokens*Intermediate*(expect_correction ? 2 : 1);byte_index++)
            if(!committed[byte_index])$fatal(1,"CORRECTION_FRAME_SCRATCH_NOT_ACKNOWLEDGED byte=%0d",byte_index);
          plane=compute_cfg_activation_base==scratch_base ? 0 : 1;
          if(compute_cfg_activation_base!=scratch_base+64'(plane*tokens*Intermediate) || plane>(expect_correction ? 1 : 0))
            $fatal(1,"CORRECTION_FRAME_DOWN_PLANE_ADDRESS");
          if(compute_hold_primary!==(expect_correction && plane==0) || compute_append_correction!==(expect_correction && plane==1))
            $fatal(1,"CORRECTION_FRAME_ACCUMULATOR_MODE");
          if(compute_cfg_feature_words!=12 || compute_cfg_activation_stride!=Intermediate || compute_cfg_dense_rows!=Outputs)
            $fatal(1,"CORRECTION_FRAME_DOWN_DESCRIPTOR");
          first_row=int'(compute_cfg_channels[15:0]);
          if(compute_append_correction && (!context_valid || context_tag!=compute_cfg_tag ||
             context_tokens!=int'(compute_cfg_tokens) || context_count!=int'(compute_cfg_count) || context_first!=first_row))
            $fatal(1,"CORRECTION_FRAME_STALE_APPEND_CONTEXT");
          for(int token=0;token<int'(compute_cfg_tokens);token++)begin
            for(int row=0;row<int'(compute_cfg_count);row++)begin
              sum=0;
              for(int channel=0;channel<Intermediate;channel++)begin
                index=plane*tokens*Intermediate+token*Intermediate+channel;
                sum+=int'($signed(scratch[index]))*weight(int'(compute_cfg_channels[row*16+:16]),channel);
              end
              result_data[token][row]<=32'(sum)+(compute_append_correction ? result_data[token][row] : 32'd0);
            end
          end
          context_valid<=compute_hold_primary;
          if(compute_hold_primary)begin
            context_tag<=compute_cfg_tag;context_tokens<=int'(compute_cfg_tokens);
            context_count<=int'(compute_cfg_count);context_first<=first_row;
          end
        end
      end
      case(backend_state)
        BackendDelay:if(backend_delay==1)backend_state<=result_hold ? BackendDone : BackendOutput;
                     else backend_delay<=backend_delay-1;
        BackendOutput:if(compute_out_valid && compute_out_ready)begin
          if(result_token+1==result_tokens)backend_state<=BackendDone;else result_token<=result_token+1;
        end
        BackendDone:if(compute_done_ready)backend_state<=BackendIdle;
        default:;
      endcase
      if(wr_req_valid && wr_req_ready)begin
        if(wr_address<scratch_base || wr_address+64'(wr_length)*8>scratch_base+64'(2*tokens*Intermediate) ||
           wr_length==0 || wr_length>10 || wr_address[2:0]!=0)$fatal(1,"CORRECTION_FRAME_WRITE_RANGE");
        pending_address<=wr_address;pending_length<=int'(wr_length);pending_beat<=0;write_active<=1;write_requests++;
      end
      if(wr_data_valid && wr_data_ready)begin
        if(wr_data_last!==(pending_beat+1==pending_length) || wr_strobe!=8'hff)$fatal(1,"CORRECTION_FRAME_WRITE_SHAPE");
        pending[pending_beat]<=wr_data;pending_beat<=pending_beat+1;
        if(wr_data_last)begin write_active<=0;ack_delay<=17;end
      end
      if(ack_delay!=0)begin ack_delay<=ack_delay-1;if(ack_delay==1)response_pending<=1;end
      if(wr_rsp_valid && wr_rsp_ready)begin
        if(wr_rsp_error)write_fault_seen<=1;
        else for(int beat=0;beat<pending_length;beat++)for(int lane=0;lane<8;lane++)begin
          index=int'(pending_address-scratch_base)+beat*8+lane;
          scratch[index]=pending[beat][lane*8+:8];committed[index]=1;
        end
        response_pending<=0;write_acks++;
      end
      if(held_output && (!out_valid || {out_tag,out_token,out_start,out_count,out_last,out_data}!==held_packet))
        $fatal(1,"CORRECTION_FRAME_OUTPUT_CHANGED_WHILE_STALLED");
      held_output<=out_valid && !out_ready;
      held_packet<={out_tag,out_token,out_start,out_count,out_last,out_data};
      if(frame_active && out_valid && out_ready)begin
        if(out_tag!=cfg_tag || int'(out_token)>=tokens || out_start>=Outputs ||
           out_count!=(out_start==0 ? 160 : 8) || out_last!==((out_start==160) && int'(out_token)+1==tokens))
          $fatal(1,"CORRECTION_FRAME_OUTPUT_METADATA");
        for(int row=0;row<int'(out_count);row++)begin
          index=int'(out_start)+row;
          if(seen[out_token][index] || out_data[row*32+:32]!==32'(expected_sum(int'(out_token),index)))
            $fatal(1,"CORRECTION_FRAME_RAW_OUTPUT token=%0d row=%0d got=%h expected=%h",out_token,index,out_data[row*32+:32],32'(expected_sum(int'(out_token),index)));
          seen[out_token][index]=1;outputs_seen++;
        end
      end
    end
  end

  task automatic begin_frame(input bit correction,input int token_count,input int fault_code,input int invalid_kind=0);
    @(negedge clk);tokens=token_count;fault=fault_code;expect_correction=correction;expect_invalid=invalid_kind!=0;
    frame_active=1;write_fault_seen=0;masks_sent=0;commands=0;write_requests=0;write_acks=0;outputs_seen=0;clear_seen=0;
    for(int index=0;index<2*MaxTokens*Intermediate;index++)begin scratch[index]=8'hde;committed[index]=0;end
    for(int token=0;token<MaxTokens;token++)for(int row=0;row<Outputs;row++)seen[token][row]=0;
    cfg_tag=cfg_tag+1;cfg_correction_enable=correction;cfg_tokens=5'(tokens);
    cfg_input_features=32;cfg_intermediate_features=Intermediate;cfg_output_features=Outputs;
    cfg_activation_base=64'h100000;cfg_gate_base=64'h200000;cfg_up_base=64'h300000;cfg_down_base=64'h400000;
    scratch_base=invalid_kind==2 ? 64'hffffffffffffff40 : ScratchBase;cfg_intermediate_base=scratch_base;
    if(invalid_kind==1)cfg_down_base=ScratchBase+64'(tokens*Intermediate);
    cfg_activation_stride=32;cfg_gate_shifts=0;cfg_up_shifts=0;cfg_down_shifts=0;
    for(int token=0;token<MaxTokens;token++)cfg_down_shifts[token*6+:6]=6'(token%2);
    cfg_valid=1;
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;
  endtask

  task automatic run_frame(input bit correction,input int token_count,input int fault_code,input int invalid_kind=0);
    bit want_error;
    begin_frame(correction,token_count,fault_code,invalid_kind);
    wait(done_valid);#1;want_error=fault_code!=0 || invalid_kind!=0;
    if(done_tag!=cfg_tag || done_error!==want_error)$fatal(1,"CORRECTION_FRAME_TERMINAL_ERROR fault=%0d invalid=%0d error=%0d",fault_code,invalid_kind,done_error);
    if(!want_error && (outputs_seen!=tokens*Outputs || commands!=(correction ? 6 : 4) ||
       write_acks!=(correction ? 4 : 2)*tokens || write_requests!=write_acks))$fatal(1,"CORRECTION_FRAME_FINAL_INVENTORY");
    if(invalid_kind!=0 && (commands!=0 || write_requests!=0))$fatal(1,"CORRECTION_FRAME_INVALID_ALLOCATION_EXECUTED");
    repeat(3)@(negedge clk);
    if(want_error && clear_seen==0)$fatal(1,"CORRECTION_FRAME_ERROR_CONTEXT_NOT_CLEARED");
    done_ready=1;@(posedge clk);@(negedge clk);done_ready=0;frame_active=0;
    if(context_valid || write_active || response_pending)$fatal(1,"CORRECTION_FRAME_CONTEXT_OR_WRITE_LEFT_LIVE");
    frames++;
  endtask

  task automatic reset_during_frame(input bit retained_context);
    begin_frame(1,2,0);
    if(retained_context)wait(context_valid && result_hold && backend_state==BackendDone);
    else begin
      wait(compute_out_valid && result_paired && !compute_out_ready);
      repeat(5)@(negedge clk);
    end
    @(negedge clk);rst_n=0;frame_active=0;cfg_valid=0;done_ready=0;
    repeat(3)@(negedge clk);rst_n=1;
    repeat(3)@(negedge clk);
    if(context_valid || write_active || response_pending || compute_hold_primary || compute_append_correction)
      $fatal(1,"CORRECTION_FRAME_RESET_LEFT_CONTEXT");
    reset_cases++;
    run_frame(1,2,0);
  endtask

  task automatic run_attention;
    @(negedge clk);attention_probe=1;attention_enable=1;attention_cfg_valid=1;
    attention_cfg_tag=32'h76543210;attention_cfg_tokens=1;attention_cfg_count=8;
    attention_cfg_feature_words=4;attention_cfg_dense_rows=8;attention_cfg_activation_stride=32;
    attention_cfg_activation_base=64'h800000;attention_cfg_weight_base=64'h900000;
    attention_cfg_channels=0;attention_cfg_keep='1;attention_out_ready=1;attention_done_ready=0;
    do @(posedge clk);while(!attention_cfg_ready);
    @(negedge clk);attention_cfg_valid=0;
    wait(attention_out_valid);#1;
    if(attention_out_tag!=attention_cfg_tag || attention_out_token!=0 || !attention_out_last || attention_out_count!=8)
      $fatal(1,"CORRECTION_FRAME_ATTENTION_METADATA");
    for(int row=0;row<8;row++)if(attention_out_data[row*32+:32]!==32'h55aa0000+32'(row))
      $fatal(1,"CORRECTION_FRAME_ATTENTION_DATA");
    wait(attention_done_valid);#1;
    if(attention_done_tag!=attention_cfg_tag || attention_done_error)$fatal(1,"CORRECTION_FRAME_ATTENTION_DONE");
    @(negedge clk);attention_done_ready=1;@(posedge clk);@(negedge clk);
    attention_done_ready=0;attention_enable=0;attention_probe=0;attention_cases++;
  endtask

`ifndef MAPPED_FRAME_CONTROL
  // A between-clock transient decode must not reset an owned memory write.
  // This deliberately emulates skew on the binary state bits; it is not a
  // routed-delay measurement. Mapped replay has a different state encoding.
  initial begin
    if($test$plusargs("INJECT_STATE_GLITCH"))begin
      wait(rst_n && frame_active && expect_correction && ack_delay>5 && dut.state==4'd8);
      @(negedge clk);#1;
      force dut.state[1:0]=2'b11;
      #0.1;
      if(dut.writer_rst_n!==1'b1)$fatal(1,"CORRECTION_FRAME_ASYNC_RESET_DURING_WRITE");
      force dut.state[1:0]=2'b00;
      #0.1;release dut.state[1:0];
      $display("CORRECTION_FRAME_STATE_GLITCH_IGNORED");
    end
  end
`endif

  initial begin
    clk=0;rst_n=0;cfg_valid=0;cfg_tag=0;cfg_correction_enable=0;done_ready=0;
    attention_enable=0;attention_cfg_valid=0;attention_out_ready=0;attention_done_ready=0;
    repeat(4)@(negedge clk);rst_n=1;
    run_frame(0,2,0);
    run_frame(1,2,0);
    run_attention();
    run_frame(1,2,1);run_frame(1,2,0);
    run_frame(1,2,2);run_frame(1,2,0);
    run_frame(1,2,3);run_frame(1,2,0);
    run_frame(1,2,4);run_frame(1,2,0);
    run_frame(1,2,0,1);run_frame(1,2,0,2);
    reset_during_frame(0);reset_during_frame(1);
    run_frame(1,16,0);run_frame(0,2,0);
    $display("CORRECTION_FRAME_CONTROL_PASS frames=%0d attention=%0d reset_cases=%0d max_tokens=16 outputs_per_token=168",frames,attention_cases,reset_cases);
    $finish(1);
  end
endmodule
