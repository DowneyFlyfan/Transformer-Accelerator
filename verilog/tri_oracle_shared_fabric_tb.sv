`timescale 1ns / 1ps
// Updated to modern SystemVerilog
// Independent signed dot products through the real five four-core clusters.
module tri_oracle_shared_fabric_tb;
  localparam int Rows = 160;
  localparam int Lanes = 8;
  localparam int SumBits = 32;
  localparam int IdBits = 16;
  localparam int TimeoutCycles = 1500000;
  localparam int HoldCycles = 6;
  localparam int MaxBurst = 16;
  localparam logic [63:0] ActBase = 64'h100002000;
  localparam logic [63:0] WeightBase = 64'h200004000;
  logic clk = 0;
  always #5 clk = ~clk;
  logic rst_n = 0, in_valid = 0, in_last = 0, in_fallback = 0, out_ready = 0;
  logic in_is_down=0,in_accumulate=0,out_is_down;
  logic [1023:0] in_data=0;
  logic [16:0] in_dense_features=5632;
  logic [15:0] in_output_start=0,out_start;
  logic [7:0] in_output_count=0;
  logic [5:0] in_shift=0;
  logic [3:0] in_slot=0,out_slot;
  bit ref_is_down=0;
  int down_count=0,down_outputs=0,down_start=0,down_slot=0,down_stride=5632,down_shift=0,down_cases=0,invalid_down_cases=0;
  logic [511:0] down_ids;
  logic [1023:0] down_codes;
  longint signed down_golden[16][160];
  int core_instances=0,cluster_instances=0,weight_mask_memories=0,activation_memories=0,result_memories=0;
  logic [31:0] in_tag = 0;
  logic [7:0] in_count = 0;
  logic [2559:0] in_channels = 0;
  logic [63:0] in_activation_base = ActBase, in_weight_base = WeightBase;
  logic [9:0] in_features = 0;
  logic in_ready, out_valid, out_last, out_fallback, out_error;
  logic [31:0] out_tag;
  logic [7:0] out_count;
  logic [2559:0] out_channels;
  logic [5119:0] out_data;
  logic req_valid, req_ready, rsp_ready;
  logic [63:0] req_address;
  logic [ 4:0] req_length;
  logic rsp_valid = 0, rsp_last = 0, rsp_error = 0;
  logic [63:0] rsp_data = 0;
  int cycle = 0, strips = 0, rows = 0, seed = 0, fault_mode = 0;
  int fault_style = 0, fault_scope = 0;
  int checked = 0, requests = 0, activation_bytes = 0, weight_bytes = 0;
  int commands = 0, request_stalls = 0;
  int beat = 0, burst_length = 0;
  logic memory_active = 0, request_waited = 0, inject_burst = 0, fault_fired = 0;
  logic [  63:0] address = 0;
  logic [2559:0] expected_channels;
  logic [63:0] expected_activation_base, expected_weight_base;
  logic weight_burst = 0;
  logic [31:0] expected_tag;
  logic expected_last, expected_fallback;
  longint signed expected[Rows];
  logic request_held = 0;
  logic [68:0] held_request;
  int cluster_commands[5];
  int owner_requests[5];
  bit abort_offer_seen = 0, abort_accept_seen = 0;
  int after_fault_wait = 0;

  always_comb
    req_ready = !memory_active && !rsp_valid &&
      (request_waited || (fault_mode == 11 && fault_fired)) && cycle % 4 != 0 &&
      !(fault_mode == 10 && fault_fired && after_fault_wait < 8);
  for (genvar cluster = 0; cluster < 5; cluster++) begin : command_monitors
    always @(posedge clk) begin
      if (rst_n && dut.cluster_cmd_valid[cluster] &&
          dut.cluster_cmd_ready[cluster]) begin
        if (dut.cluster_cmd_output[cluster] !==
            4'(ref_is_down?down_slot:0))
          $fatal(1, "WRONG_CLUSTER_DESTINATION_SLOT");
        cluster_commands[cluster]++;
        commands++;
      end
    end
  end
  tri_oracle_shared_fabric dut (.*);

  function automatic int down_weight(input int row,column);
    return (row*3+column*7)%255-127;
  endfunction
  function automatic int down_activation(input int index);
    real value;
    int rounded;
    value=real'($signed(down_codes[index*32+:32]))/(2.0**down_shift);
    rounded=value>=0.0?$rtoi(value+0.5):-$rtoi(-value+0.5);
    return rounded>127?127:(rounded < -128 ? -128:rounded);
  endfunction

  function automatic int activation_value(input int feature);
    return ((feature * 17 + seed * 11) % 256) - 128;
  endfunction
  function automatic int weight_value(input int channel, feature);
    return ((channel * 7 + feature * 13 + seed * 3) % 256) - 128;
  endfunction
  function automatic bit selected(input int channel);
    selected = 0;
    for (int row = 0; row < rows && row < Rows; row++)
    if (channel == int'(expected_channels[row*IdBits+:IdBits])) selected = 1;
  endfunction

  always @(posedge clk) begin : memory_peer
    logic [63:0] offset, cursor;
    logic activation_request, inject_now, selected_down;
    int channel, feature;
    if (!rst_n) begin
      cycle <= 0;
      memory_active <= 0;
      rsp_valid <= 0;
      request_waited <= 0;
    end else begin
      cycle <= cycle + 1;
      if(!dut.child_rst_n && (memory_active || rsp_valid || req_valid || request_held))
        $fatal(1,"GLOBAL_RESET_BEFORE_ADVERTISED_OR_ACCEPTED_MEMORY_DRAIN");
      // This wait count drives ready; commit it after all clock-edge sampling.
      if (fault_fired && !memory_active) after_fault_wait <= after_fault_wait + 1;
      if (dut.fault_now && req_valid && !req_ready) abort_offer_seen = 1;
      if (dut.fault_now && ((req_valid && req_ready) || dut.busy)) abort_accept_seen = 1;
      if (out_valid && (memory_active || rsp_valid))
        $fatal(1, "EARLY_FABRIC_RESULT_WITH_OWNED_RESPONSE");
      if (req_valid !== 1'b0 && req_valid !== 1'b1) $fatal(1, "UNKNOWN_REQUEST_VALID");
      if (request_held && (req_valid !== 1'b1 || {req_address, req_length} !== held_request))
        $fatal(1, "UNSTABLE_MEMORY_REQUEST");
      request_held = req_valid && !req_ready;
      held_request = {req_address, req_length};
      if (request_held) request_stalls++;
      if (req_valid && !request_waited) request_waited <= 1;
      if (req_valid && req_ready) begin
        if (req_length == 0 || req_length > MaxBurst || req_address[2:0] != 0)
          $fatal(1, "BAD_REQUEST_SHAPE");
        request_waited <= 0;
        memory_active <= 1;
        address <= req_address;
        burst_length <= int'(req_length);
        beat <= 0;
        activation_request = !ref_is_down && req_address >= expected_activation_base &&
            {1'b0, req_address} < {1'b0, expected_activation_base} + 65'(strips * Lanes);
        weight_burst <= !activation_request;
        inject_now = fault_mode != 0 && !fault_fired &&
            ((fault_scope == 0 && activation_request) ||
             (fault_scope == 1 && !activation_request) ||
             (fault_scope == 2 && !activation_request && commands >= MaxBurst));
        inject_burst <= inject_now;
        fault_fired  <= fault_fired || inject_now;
        if (dut.offer_owner >= 5) $fatal(1, "BAD_MEMORY_OWNER");
        if (!ref_is_down && fault_mode == 0 && requests < (rows + 31) / 32 && dut.offer_owner !== 3'(requests))
          $fatal(1, "UNFAIR_INITIAL_MEMORY_OWNERS");
        requests++;
        owner_requests[dut.offer_owner]++;
        if(ref_is_down) begin
          if(req_length!==5'd1 || req_address<expected_weight_base) $fatal(1,"BAD_DOWN_GATHER_SHAPE");
          offset=req_address-expected_weight_base;
          channel=int'(offset/64'(down_stride));
          feature=int'(offset%64'(down_stride));
          selected_down=0;
          for(int i=0;i<down_count;i++)
            if(int'(down_ids[i*16+:16])/8==feature/8 && down_activation(i)!=0) selected_down=1;
          if(channel<down_start || channel>=down_start+down_outputs || !selected_down)
            $fatal(1,"DOWN_GATHER_UNUSED_ROW_OR_ORIGINAL_COLUMN");
        end else if (!activation_request) begin
          if (req_address < expected_weight_base) $fatal(1, "ALIASED_WEIGHT_BASE");
          offset  = req_address - expected_weight_base;
          channel = int'(offset / 64'(strips * Lanes));
          if (!selected(
                  channel
              ) || offset % 64'(strips * Lanes) + 64'(req_length * Lanes) > 64'(strips * Lanes))
            $fatal(1, "WRONG_ORIGINAL_WEIGHT_ROW_OR_STRIDE");
          weight_bytes += int'(req_length) * Lanes;
        end else begin
          if ({1'b0, req_address} + 65'(req_length * Lanes) >
              {1'b0, expected_activation_base} + 65'(strips * Lanes))
            $fatal(1, "PADDING_OR_ALIASED_ACTIVATION_READ");
          activation_bytes += int'(req_length) * Lanes;
        end
      end
      if (memory_active && !rsp_valid && cycle % 3 != 0) begin
        rsp_valid <= 1;
        rsp_error <= inject_burst && fault_style == 1 && beat == 0;
        if (inject_burst && fault_style == 2) rsp_last <= 1;
        else if (inject_burst && fault_style == 3) rsp_last <= beat == burst_length;
        else rsp_last <= beat == burst_length - 1;
        for (int lane = 0; lane < Lanes; lane++) begin
          cursor = address + 64'(beat * Lanes + lane);
          if(ref_is_down) begin
            offset=cursor-expected_weight_base;
            channel=int'(offset/64'(down_stride));feature=int'(offset%64'(down_stride));
            rsp_data[lane*8+:8]<=8'(down_weight(channel,feature));
          end else if (weight_burst) begin
            offset  = cursor - expected_weight_base;
            channel = int'(offset / 64'(strips * Lanes));
            feature = int'(offset % 64'(strips * Lanes));
            rsp_data[lane*8+:8] <= 8'(weight_value(channel, feature));
          end else
            rsp_data[lane*8+:8] <= 8'(activation_value(int'(cursor - expected_activation_base)));
        end
      end
      if (rsp_valid && rsp_ready) begin
        rsp_valid <= 0;
        if (rsp_last) memory_active <= 0;
        else beat <= beat + 1;
      end

    end
  end

  task automatic launch(input int feature_strips, row_count, fault, bad_config, case_seed);
    int channel;
    begin
      @(negedge clk);
      while(!in_ready) @(negedge clk);
      if (memory_active || rsp_valid) $fatal(1, "CONTEXT_NOT_IDLE");
      ref_is_down=0;in_is_down=0;
      strips = feature_strips;
      rows = row_count;
      seed = case_seed;
      fault_mode = fault;
      fault_style = fault >= 10 ? 1 : (fault == 0 ? 0 : (fault - 1) % 3 + 1);
      fault_scope = fault >= 10 ? 0 : (fault == 0 ? 0 : (fault - 1) / 3);
      fault_fired = 0;
      abort_offer_seen = 0;
      abort_accept_seen = 0;
      after_fault_wait = 0;
      for (int cluster = 0; cluster < 5; cluster++) begin
        cluster_commands[cluster] = 0;
        owner_requests[cluster]   = 0;
      end
      requests = 0;
      activation_bytes = 0;
      weight_bytes = 0;
      commands = 0;
      request_stalls = 0;
      in_channels = 0;
      for (int row = 0; row < Rows; row++) begin
        channel = row % 3 == 0 ? 65535 - row : (row % 3 == 1 ? row * 17 : 500 + row);
        in_channels[row*IdBits+:IdBits] = IdBits'(channel);
        expected[row] = 0;
        if (row < row_count && !(bad_config > 0 && bad_config < 6) &&
            bad_config != 8 && bad_config != 9 && fault == 0)
          for (int feature = 0; feature < feature_strips * Lanes; feature++)
          expected[row] += longint'(activation_value(
              feature
          )) * longint'(weight_value(
              channel, feature
          ));
      end
      if($test$plusargs("CORRUPT_PROJECTION_REFERENCE") && row_count>2 && fault==0 && bad_config==0)
        expected[2]+=1;
      expected_channels = in_channels;
      expected_tag = 32'hc1000000 + 32'(case_seed);
      expected_last = case_seed % 2 != 0;
      expected_fallback = case_seed % 3 == 0;
      in_tag = expected_tag;
      in_last = expected_last;
      in_fallback = expected_fallback;
      in_features = 10'(feature_strips);
      in_count = 8'(row_count);
      in_activation_base = ActBase;
      in_weight_base = WeightBase;
      case (bad_config)
        1: in_features = 513;
        2: in_count = 161;
        3: in_activation_base = ActBase + 1;
        4: in_weight_base = 64'hfffffffffffffff8;
        5: in_activation_base = 64'hfffffffffffffff8;
        6: in_activation_base = 64'hffffffffffffffff - 64'(feature_strips * Lanes) + 1;
        7: in_weight_base = 64'hffffffffffffffff - 64'(65536 * feature_strips * Lanes) + 1;
        8: in_features = 0;
        9: in_weight_base = WeightBase + 1;
        default: begin
        end
      endcase
      expected_activation_base = in_activation_base;
      expected_weight_base = in_weight_base;
      in_valid = 1;
      @(posedge clk);
      if (!in_ready) $fatal(1, "PACKET_NOT_ACCEPTED");
      @(negedge clk);
      in_valid = 0;
      in_is_down=1;
      in_features = '1;
      in_count = '1;
      in_tag = '1;
      in_channels = '1;
      in_activation_base = 0;
      in_weight_base = 0;
      in_last = !expected_last;
      in_fallback = !expected_fallback;
    end
  endtask

  task automatic run_case(input int feature_strips, row_count, fault, bad_config, case_seed);
    int timeout;
    logic expect_error;
    logic [7743:0] old;  // Held output packet before applying backpressure.
    begin
      launch(feature_strips, row_count, fault, bad_config, case_seed);
      timeout = 0;
      expect_error = fault != 0 || (bad_config > 0 && bad_config < 6) ||
                     bad_config == 8 || bad_config == 9;
      while (!out_valid && timeout < TimeoutCycles) begin
        @(negedge clk);
        timeout++;
      end
      if (out_valid !== 1'b1) $fatal(1, "PROJECTION_NOT_COMPLETED");
      if (memory_active || rsp_valid) $fatal(1, "EARLY_RESULT_WITH_OWNED_MEMORY_RESPONSE");
      if (fault != 0 && !fault_fired) $fatal(1, "MEMORY_FAULT_NOT_EXERCISED");
      if (fault >= 7 && fault <= 9 && commands < MaxBurst)
        $fatal(1, "LATER_TILE_FAULT_NOT_REACHED");
      if (fault == 10 && !abort_offer_seen) $fatal(1, "ABORT_DID_NOT_PRESERVE_OFFER");
      if (fault == 11 && !abort_accept_seen) $fatal(1, "ABORT_DID_NOT_DRAIN_ACCEPTED_REQUEST");
      if (out_error !== expect_error || out_tag !== expected_tag ||
          out_is_down!==0 || out_start!==0 || out_slot!==0 ||
          out_last !== (expect_error || expected_last) || out_fallback !== (!expect_error && expected_fallback) ||
          out_count !== 8'(expect_error ? 0 : row_count) || out_channels !== (expect_error?2560'b0:expected_channels))
        $fatal(1, "PROJECTION_METADATA_MISMATCH");
      for (int row = 0; row < Rows; row++)
      if (out_data[row*SumBits+:SumBits] !== (expect_error ? SumBits'(0) : SumBits'(expected[row])))
        $fatal(1, "PROJECTION_SUM_MISMATCH case=%0d row=%0d", case_seed, row);
      if (!expect_error && row_count != 0) begin
        if (activation_bytes != feature_strips * Lanes * ((row_count + 31) / 32) ||
            weight_bytes != feature_strips * Lanes * row_count)
          $fatal(1, "PROJECTION_TRAFFIC_MISMATCH");
        if (commands != ((feature_strips + 3) / 4) * ((row_count + 31) / 32) || request_stalls == 0)
          $fatal(1, "MISSING_REAL_CLUSTER_COMMANDS_OR_STALLS");
        for (int cluster = 0; cluster < 5; cluster++) begin
          if (cluster_commands[cluster] !=
              (row_count > cluster * 32 ? (feature_strips + 3) / 4 : 0))
            $fatal(1, "MISSING_CLUSTER_EXECUTION %0d", cluster);
          if (row_count > cluster * 32 && owner_requests[cluster] == 0)
            $fatal(1, "STARVED_MEMORY_OWNER %0d", cluster);
        end
      end else if (bad_config != 0 || row_count == 0)
        if (requests != 0) $fatal(1, "INVALID_OR_EMPTY_PACKET_READ_MEMORY");
      old = {out_is_down,out_start,out_slot,out_count, out_last, out_error, out_fallback, out_tag, out_channels, out_data};
      repeat (HoldCycles) begin
        @(negedge clk);
        if (out_valid !== 1'b1) $fatal(1, "UNSTABLE_PROJECTION_OUTPUT");
        if ({out_is_down,out_start,out_slot,out_count, out_last, out_error, out_fallback, out_tag, out_channels, out_data} !== old)
          $fatal(1, "UNSTABLE_PROJECTION_OUTPUT");
      end
      out_ready = 1;
      @(posedge clk);
      @(negedge clk);
      out_ready = 0;
      checked++;
      $display("FABRIC_PROJECTION_CASE_PASS seed=%0d error=%0d commands=%0d", case_seed,
               expect_error, commands);
      $fflush();
    end
  endtask

  task automatic run_down(input int count,outputs,start,slot,case_seed,
                          input bit append,last,error_expected=0,inject_memory_error=0,
                          input logic [31:0] context_tag=32'hd001);
    int timeout,expected_value;
    logic [7743:0] held;
    begin
      @(negedge clk);while(!in_ready) @(negedge clk);
      if(memory_active || rsp_valid) $fatal(1,"DOWN_CONTEXT_NOT_IDLE");
      ref_is_down=1;down_count=count;down_outputs=outputs;down_start=start;down_slot=slot;
      down_stride=case_seed==9?65536:5632;down_shift=case_seed%3==0?7:0;
      strips=0;rows=outputs;seed=case_seed;expected_weight_base=64'h100000;
      down_ids=0;down_codes=0;
      for(int i=0;i<count;i++) begin
        down_ids[i*16+:16]=16'(i==0?0:i==1?5631:i==2?1:(i*173+case_seed*7)%5632);
        down_codes[i*32+:32]=32'(i==3?32'sh7fffffff:i==4?32'sh80000000:(i*7+case_seed)%63-31);
      end
      if(!error_expected) begin
        if(!append) for(int row=0;row<160;row++) down_golden[slot][row]=0;
        for(int row=0;row<outputs;row++)
          for(int i=0;i<count;i++)
            down_golden[slot][row]+=longint'(down_activation(i))*longint'(down_weight(start+row,int'(down_ids[i*16+:16])));
      end
      fault_mode=inject_memory_error?1:0;fault_style=1;fault_scope=1;
      fault_fired=0;abort_offer_seen=0;abort_accept_seen=0;after_fault_wait=0;
      requests=0;commands=0;request_stalls=0;activation_bytes=0;weight_bytes=0;
      for(int c=0;c<5;c++) begin cluster_commands[c]=0;owner_requests[c]=0;end
      expected_tag=context_tag;expected_last=last;
      in_is_down=1;in_accumulate=append;in_last=last;in_fallback=1;in_tag=context_tag;
      in_count=8'(count);in_output_count=8'(outputs);in_output_start=16'(start);
      in_slot=4'(slot);in_shift=6'(down_shift);in_dense_features=17'(down_stride);
      in_channels={2048'b0,down_ids};in_data=down_codes;in_weight_base=expected_weight_base;
      in_valid=1;@(posedge clk);if(!in_ready) $fatal(1,"DOWN_NOT_ACCEPTED");
      @(negedge clk);in_valid=0;in_is_down=0;in_count='1;in_output_count=0;
      in_channels='1;in_data='1;in_slot=0;in_output_start=0;in_tag='1;in_weight_base=0;
      timeout=0;
      while(!out_valid && timeout<TimeoutCycles) begin @(negedge clk);timeout++;end
      if(!out_valid || memory_active || rsp_valid) $fatal(1,"DOWN_MISSING_OR_EARLY_RESULT");
      if(out_is_down!==1 || out_tag!==context_tag || out_error!==error_expected ||
         out_last!==(last || error_expected) || out_fallback!==0 ||
         out_count!==8'(error_expected?0:outputs) || out_start!==16'(start) ||
         out_slot!==4'(slot) || out_channels!==0) $fatal(1,"DOWN_FABRIC_METADATA_MISMATCH");
      for(int row=0;row<160;row++) begin
        expected_value=error_expected || row>=outputs?0:int'(down_golden[slot][row]);
        if($test$plusargs("CORRUPT_DOWN_REFERENCE") && row==2 && !error_expected) expected_value++;
        if(out_data[row*32+:32]!==32'(expected_value))
          $fatal(1,"DOWN_FABRIC_REFERENCE_MISMATCH row=%0d got=%0d expected=%0d",row,$signed(out_data[row*32+:32]),expected_value);
      end
      if(inject_memory_error && !fault_fired) $fatal(1,"DOWN_MEMORY_ERROR_NOT_EXERCISED");
      if(count==0 && requests!=0) $fatal(1,"EMPTY_DOWN_READ_MEMORY");
      if(!error_expected) for(int c=0;c<5;c++)
        if(cluster_commands[c]!=(outputs>c*32?1:0)) $fatal(1,"DOWN_BROADCAST_MISSING_OR_EXTRA_CLUSTER");
      held={out_is_down,out_start,out_slot,out_count,out_last,out_error,out_fallback,out_tag,out_channels,out_data};
      repeat(HoldCycles) begin
        @(negedge clk);
        if(!out_valid || in_ready || held!=={out_is_down,out_start,out_slot,out_count,out_last,out_error,out_fallback,out_tag,out_channels,out_data})
          $fatal(1,"DOWN_RESULT_CHANGED_UNDER_BACKPRESSURE");
      end
      out_ready=1;@(posedge clk);@(negedge clk);out_ready=0;
      checked++;down_cases++;
      $display("SHARED_FABRIC_DOWN_CASE_PASS seed=%0d error=%0d commands=%0d",case_seed,error_expected,commands);
      $fflush();
    end
  endtask

  task automatic invalid_down_case(input int kind);
    int timeout;
    logic [7743:0] held;
    begin
      @(negedge clk);while(!in_ready) @(negedge clk);
      ref_is_down=1;fault_mode=0;requests=0;commands=0;fault_fired=0;
      down_count=1;down_outputs=1;down_start=0;down_slot=15;down_stride=5632;down_shift=0;
      in_is_down=1;in_accumulate=0;in_last=0;in_fallback=1;in_tag=32'hbad00000+32'(kind);
      in_count=1;in_output_count=1;in_output_start=0;in_slot=15;in_shift=0;
      in_dense_features=5632;in_channels=0;in_data=1;in_weight_base=64'h100000;
      case(kind)
        0: in_count=33;
        1: in_output_count=0;
        2: in_output_count=161;
        3: in_slot=0;
        4: in_dense_features=0;
        5: in_dense_features=7;
        6: in_dense_features=65535;
        7: in_dense_features=65537;
        8: begin in_output_start=65535;in_output_count=2;end
        9: in_weight_base=64'h100001;
        10: in_channels[15:0]=5632;
        11: in_accumulate=1;
        default: $fatal(1,"UNKNOWN_INVALID_DOWN_CASE");
      endcase
      expected_tag=in_tag;down_slot=int'(in_slot);down_start=int'(in_output_start);
      in_valid=1;@(posedge clk);if(!in_ready) $fatal(1,"INVALID_DOWN_NOT_ACCEPTED");
      @(negedge clk);in_valid=0;in_is_down=0;in_tag=0;in_slot=0;
      timeout=0;while(!out_valid && timeout<100) begin @(negedge clk);timeout++;end
      if(!out_valid || out_error!==1 || out_last!==1 || out_fallback!==0 || out_is_down!==1 ||
         out_count!==0 || out_data!==0 || out_channels!==0 || out_tag!==expected_tag ||
         out_start!==16'(down_start) || out_slot!==4'(down_slot) || requests!=0 || commands!=0)
        $fatal(1,"INVALID_DOWN_FABRIC_GUARD_FAILED kind=%0d",kind);
      held={out_is_down,out_start,out_slot,out_count,out_last,out_error,out_fallback,out_tag,out_channels,out_data};
      repeat(HoldCycles) begin
        @(negedge clk);
        if(!out_valid || in_ready || held!=={out_is_down,out_start,out_slot,out_count,out_last,out_error,out_fallback,out_tag,out_channels,out_data})
          $fatal(1,"INVALID_DOWN_RESULT_CHANGED_UNDER_BACKPRESSURE");
      end
      out_ready=1;@(posedge clk);@(negedge clk);out_ready=0;
      checked++;invalid_down_cases++;
      $display("SHARED_FABRIC_INVALID_DOWN_CASE_PASS kind=%0d",kind);$fflush();
    end
  endtask

  initial begin
    repeat (2) @(negedge clk);
    if(core_instances!=20 || cluster_instances!=5 || weight_mask_memories!=360 ||
       activation_memories!=40 || result_memories!=200) $fatal(1,"SHARED_FABRIC_WRONG_ACTUAL_HIERARCHY");
    $display("SHARED_FABRIC_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600");
    rst_n = 1;
    if($test$plusargs("CONTEXT_SMOKE")) begin
      run_down(32,160,0,1,1,0,0);
      run_down(1,128,0,1,2,1,0,1);
      run_down(0,160,0,1,3,1,1,1);
      run_down(32,160,0,1,1,0,1);
      $display("SHARED_FABRIC_CONTEXT_RANGE_PASS cases=4");
      $finish;
    end
    if($test$plusargs("DOWN_SMOKE")) begin
      run_down(32,160,0,1,1,0,0);
      $fatal(1,"Corrupt down reference was not rejected");
    end
    if($test$plusargs("PROJECTION_SMOKE")) begin
      run_case(5,33,0,0,200);
      $fatal(1,"Corrupt projection reference was not rejected");
    end
    run_case(0, 0, 0, 0, 0);
    run_case(1, 1, 0, 0, 1);
    run_case(2, 31, 0, 0, 2);
    run_case(3, 32, 0, 0, 3);
    run_case(5, 33, 0, 0, 4);
    run_case(63, 64, 0, 0, 5);
    run_case(64, 65, 0, 0, 6);
    run_case(65, 129, 0, 0, 7);
    run_case(67, 160, 0, 0, 8);
    run_case(512, 160, 0, 0, 9);
    run_case(1, 1, 0, 0, 10);
    for (int fault = 1; fault <= 9; fault++) begin
      run_case(fault >= 7 ? 129 : 67, 65, fault, 0, 20 + fault);
      run_case(5, 33, 0, 0, 40 + fault);
    end
    for (int bad = 1; bad <= 5; bad++) run_case(67, 65, 0, bad, 60 + bad);
    run_case(3, 65, 0, 6, 70);
    run_case(67, 65, 0, 7, 71);
    for (int fault = 10; fault <= 11; fault++) begin
      run_case(67, 65, fault, 0, 80 + fault);
      run_case(5, 160, 0, 0, 90 + fault);
    end
    launch(67, 160, 0, 0, 110);
    wait (memory_active);
    @(negedge clk);
    rst_n = 0;
    request_held = 0;
    repeat (2) @(negedge clk);
    rst_n = 1;
    run_case(5, 160, 0, 0, 111);
    run_case(67, 65, 0, 8, 120);
    run_case(67, 65, 0, 9, 121);
    run_down(32,160,0,1,1,0,0);
    run_down(1,128,0,1,2,1,0,1);
    run_down(0,160,0,1,3,1,1,1);
    run_down(32,160,0,1,1,0,0);
    run_case(256,160,0,0,201);
    run_case(256,160,0,0,202);
    run_case(0,0,0,0,205);
    run_down(32,160,0,1,2,1,0);
    run_down(0,160,0,1,3,1,1);
    run_down(31,128,1920,13,4,0,0,0,0,32'hd013);
    run_down(7,33,65503,7,5,0,0,0,0,32'hd007);
    run_case(67,65,10,0,203);
    run_down(0,128,1920,13,4,1,0,1,0,32'hd013);
    run_down(32,160,0,1,6,0,1);
    run_down(32,160,0,1,7,0,0,1,1,32'hd011);
    run_down(32,160,0,1,8,0,1);
    run_down(1,1,65535,15,9,0,1,0,0,32'hd015);
    run_case(5,160,0,0,204);
    for(int kind=0;kind<12;kind++) invalid_down_case(kind);
    if (checked != 73 || down_cases!=13 || invalid_down_cases!=12) $fatal(1, "WRONG_SHARED_FABRIC_CASE_INVENTORY");
    $display("SHARED_FABRIC_PASS cases=%0d down_cases=%0d invalid_down_cases=%0d", checked,down_cases,invalid_down_cases);
    $finish;
  end
  initial begin
    #300000000;
    $fatal(1, "FABRIC_PROJECTION_WATCHDOG");
  end
endmodule

module tri_oracle_shared_fabric_instance_count #(parameter int KIND = 0) ();
  initial begin
    case (KIND)
      0: $root.tri_oracle_shared_fabric_tb.core_instances++;
      1: $root.tri_oracle_shared_fabric_tb.cluster_instances++;
      2: $root.tri_oracle_shared_fabric_tb.weight_mask_memories++;
      3: $root.tri_oracle_shared_fabric_tb.activation_memories++;
      4: $root.tri_oracle_shared_fabric_tb.result_memories++;
    endcase
  end
endmodule

bind tri_oracle_sram_memory_compute tri_oracle_shared_fabric_instance_count
    #(.KIND(0)) count_actual_core ();
bind tri_oracle_sram_compute_cluster tri_oracle_shared_fabric_instance_count
    #(.KIND(1)) count_actual_cluster ();
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_shared_fabric_instance_count
    #(.KIND(2)) count_actual_weight_mask ();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_shared_fabric_instance_count
    #(.KIND(3)) count_actual_activation ();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_shared_fabric_instance_count
    #(.KIND(4)) count_actual_result ();
