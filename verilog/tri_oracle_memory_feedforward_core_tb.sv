`timescale 1ns / 1ps
// Updated to modern SystemVerilog
module tri_oracle_memory_feedforward_core_tb;
  localparam int CachedMode = 1;
  logic clk = 0;
  always #5 clk = ~clk;
  logic rst_n = 0, cfg_valid = 0, cfg_ready;
  logic [31:0] cfg_tag = 0, cfg_epsilon_q16 = 0;
  logic [63:0] cfg_activation_base = 0, cfg_weight_base = 0, cfg_up_weight_base = 0;
  logic [63:0] cfg_down_weight_base = 0, cfg_gate_sign_base = 0, cfg_up_sign_base = 0;
  logic [5:0] cfg_gate_shift = 0, cfg_up_shift = 0, cfg_down_shift = 4;
  logic [5:0] cfg_activation_shift = 17;
  logic [63:0] cfg_raw_base = 0, cfg_gamma_base = 0;
  logic [ 9:0] cfg_features = 0;
  logic [16:0] cfg_dense_features = 0;
  logic [15:0] cfg_output_start = 0;
  logic [ 8:0] cfg_output_count = 0;
  logic group_valid = 0, group_ready, group_last = 0;
  logic [10:0] group_id = 0;
  logic out_valid, out_ready = 0, out_last, out_fallback, out_error;
  logic [31:0] out_tag;
  logic [5:0] out_count;
  logic [511:0] out_channels;
  logic [1023:0] out_data;
  logic req_valid, req_ready, rsp_valid = 0, rsp_ready, rsp_last = 0, rsp_error = 0;
  logic [63:0] req_address, rsp_data = 0;
  logic [4:0] req_length;
  localparam logic [63:0] ActBase=64'h1000,GateBase=64'h100000,
        UpBase=64'h40000000,DownBase=64'h80000000,
        GateSignBase=64'h100000000,UpSignBase=64'h200000000,
        RawBase=64'h300010000,GammaBase=64'h400020000;
  logic [63:0] source_raw_base = RawBase, source_gamma_base = GammaBase;
  int raw_requests = 0, gamma_requests = 0;
  int cycle = 0, features = 0, dense = 0, outputs = 0, output_start = 0, mode = 0, fault = 0;
  int requests = 0, sign_requests = 0, compute_requests = 0, down_requests = 0;
  int beat = 0, length = 0, active_phase = 0, checked = 0;
  bit memory_active = 0, memory_error = 0, fault_done = 0;
  bit force_request_stall = 0, poisoned_hold_exercised = 0;
  logic [63:0] address = 0;
  logic [65535:0] gate_rows = '0, up_rows = '0;
  logic held_request = 0;
  logic [68:0] saved_request;
  tri_oracle_memory_feedforward_core dut (.*);
  always_comb
    req_ready=!memory_active && !rsp_valid && !force_request_stall &&
        (fault==9 || fault==10 || fault==14 ? cycle%64<2 : cycle%4!=0);

  function automatic bit allowed(input int channel);
    if (mode == 1) allowed = 0;
    else if (mode == 0) allowed = channel < 32 ? channel % 2 == 0 : channel % 2 == 1;
    else allowed = channel < dense;
  endfunction
  function automatic int gate_weight(input int channel, feature);
    gate_weight = (!allowed(channel) && feature == 1) ? -16 : 16;
  endfunction
  function automatic int up_weight(input int channel, feature);
    int value;
    begin
      value = channel % 3 == 0 ? -1 : (channel % 3 == 1 ? 1 : 2);
      up_weight = (!allowed(channel) && feature == 1) ? -value : value;
    end
  endfunction
  function automatic int down_weight(input int row, column);
    down_weight = (row * 3 + column * 7) % 255 - 127;
  endfunction
  function automatic logic [127:0] raw_strip(input int index);
    if (mode == 4) raw_strip = '0;
    else if (mode == 3) raw_strip = {8{16'd1}};
    else raw_strip = index == 0 ? 128'h00000000000000000000000000100010 : 128'b0;
  endfunction

  always @(posedge clk) begin : external_memory
    int phase, channel, feature, value, group_number, pair_number;
    logic [63:0] offset, cursor, bytes, total;
    bit inject;
    if (!rst_n) begin
      cycle <= 0;
      memory_active <= 0;
      rsp_valid <= 0;
      held_request <= 0;
    end else begin
      cycle <= cycle + 1;
      if (out_valid && out_error && memory_active) $fatal(1, "ERROR_VISIBLE_BEFORE_RESPONSE_LAST");
      if (held_request && {req_valid, req_address, req_length} !== {1'b1, saved_request})
        $fatal(1, "MEMORY_FF_REQUEST_CHANGED_WHILE_STALLED");
      held_request  <= req_valid && !req_ready;
      saved_request <= {req_address, req_length};
      if (req_valid && req_ready) begin
        if (fault_done) $fatal(1, "MEMORY_FF_EXTERNAL_REQUEST_AFTER_FAULT");
        if ($isunknown(
                {req_address, req_length}
            ) || req_length == 0 || req_length > 16 || req_address[2:0] != 0)
          $fatal(1, "MEMORY_FF_BAD_REQUEST");
        phase=req_address>=source_raw_base && {1'b0,req_address}<
                    {1'b0,source_raw_base}+65'(features)*16 ? 7 :
                    (req_address>=source_gamma_base && {1'b0,req_address}<
                    {1'b0,source_gamma_base}+65'(features)*16 ? 8 :
                    (req_address>=UpSignBase?6:(req_address>=GateSignBase?5:
                    (req_address>=DownBase?3:(req_address>=UpBase?2:
                    (req_address>=GateBase?1:0))))));
        bytes = 64'(req_length) * 8;
        if (phase == 7 || phase == 8) begin
          offset = req_address - (phase == 7 ? source_raw_base : source_gamma_base);
          total  = 64'(features) * 16;
          if (req_length != 2 || offset >= total || bytes > total - offset)
            $fatal(1, "SOURCE_READ_RANGE");
          if (phase == 7) begin
            if(offset!=64'((raw_requests<features?raw_requests:
                            raw_requests-features)*16))
              $fatal(1, "SOURCE_RAW_ORDER");
            raw_requests++;
          end else begin
            if (offset != 64'(gamma_requests * 16) || raw_requests != features + gamma_requests + 1)
              $fatal(1, "SOURCE_COEFFICIENT_ORDER");
            gamma_requests++;
          end
        end else if (phase >= 5) begin
          offset = req_address - (phase == 5 ? GateSignBase : UpSignBase);
          total  = 64'(dense) * 64'(features);
          if(mode==3 || req_length!=1 || offset>=total || bytes>total-offset ||
                        offset%(64'(features)*32)!=0)
            $fatal(1, "MEMORY_FF_SIGN_READ_OUTSIDE_OUTLIERS");
          sign_requests++;
        end else if (phase == 1 || phase == 2) begin
          offset = req_address - (phase == 1 ? GateBase : UpBase);
          total  = 64'(dense) * 64'(features) * 8;
          if (offset >= total || bytes > total - offset) $fatal(1, "MEMORY_FF_WEIGHT_RANGE");
          channel = int'(offset / (64'(features) * 8));
          if (!allowed(channel)) $fatal(1, "MEMORY_FF_FETCHED_SKIPPED_ROW");
          if (phase == 1) gate_rows[channel] = 1;
          else up_rows[channel] = 1;
          compute_requests++;
        end else if (phase == 3) begin
          offset = req_address - DownBase;
          if(req_length!=1 || offset<64'(output_start)*64'(dense) ||
                        offset+bytes>(64'(output_start)+64'(outputs))*64'(dense))
            $fatal(1, "MEMORY_FF_DOWN_RANGE");
          down_requests++;
          compute_requests++;
        end else begin
          if (CachedMode != 0) $fatal(1, "CACHED_FF_EXTERNAL_ACTIVATION_REQUEST");
          offset = req_address - ActBase;
          total  = 64'(features) * 8;
          if (req_address < ActBase || offset >= total || bytes > total - offset)
            $fatal(1, "MEMORY_FF_ACTIVATION_RANGE");
          compute_requests++;
        end
        inject=(fault==phase && phase>=1 && phase<=6) ||
                    (fault==4 && phase==3 && down_requests>=128) ||
                    (fault==8 && phase==7 && raw_requests==1) ||
                    (fault==11 && phase==7 && raw_requests==features+1) ||
                    ((fault==12 || fault==13 || fault==15) && phase==8 && gamma_requests==1);
        if (inject) fault_done <= 1;
        address <= req_address;
        active_phase <= phase;
        length<=inject && fault==13 ? 1 : int'(req_length)+
                    (inject && (fault==4 || fault==6 || fault==15)?2:0);
        memory_error <= inject && fault != 4 && fault != 6 && fault != 13 && fault != 15;
        beat <= 0;
        memory_active <= 1;
        requests++;
      end
      if (memory_active && !rsp_valid && cycle % 3 != 0) begin
        rsp_valid <= 1;
        rsp_last  <= beat == length - 1;
        rsp_error <= memory_error && beat == 0;
        cursor = address + 64'(beat) * 8;
        if (active_phase == 7 || active_phase == 8) begin
          offset = cursor - (active_phase == 7 ? source_raw_base : source_gamma_base);
          if (active_phase == 8) rsp_data <= {4{16'd32767}};
          else begin
            rsp_data <= 64'(raw_strip(int'(offset / 16)) >> (offset[3] ? 64 : 0));
            if (fault == 7 && raw_requests > features && int'(offset / 16) == features - 1)
              rsp_data <= 64'(raw_strip(
                  int'(offset / 16)
              ) >> (offset[3] ? 64 : 0)) ^ 64'(offset[3] == 0);
          end
        end else if (active_phase >= 5) begin
          offset = address - (active_phase == 5 ? GateSignBase : UpSignBase);
          group_number = int'(offset / (64'(features) * 32));
          pair_number = int'((offset % (64'(features) * 32)) / 8);
          for (int half = 0; half < 2; half++) begin
            feature = pair_number * 2 + half;
            for (int row = 0; row < 32; row++) begin
              channel = group_number * 32 + row;
              value = active_phase == 5 ? gate_weight(channel, feature) :
                  up_weight(channel, feature);
              rsp_data[half*32+row] <= value < 0;
            end
          end
        end else begin
          for (int lane = 0; lane < 8; lane++) begin
            if (active_phase == 3) begin
              offset  = address - DownBase;
              channel = int'(offset / 64'(dense));
              feature = int'(offset % 64'(dense)) + lane;
              value   = down_weight(channel, feature);
            end else if (active_phase == 1 || active_phase == 2) begin
              offset = cursor - (active_phase == 1 ? GateBase : UpBase);
              channel = int'(offset / (64'(features) * 8));
              feature = int'(offset % (64'(features) * 8)) + lane;
              value = active_phase == 1 ? gate_weight(channel, feature) :
                  up_weight(channel, feature);
            end else value = 1;
            rsp_data[lane*8+:8] <= 8'(value);
          end
        end
      end
      if (rsp_valid && rsp_ready) begin
        rsp_valid <= 0;
        beat <= beat + 1;
        if (rsp_last) memory_active <= 0;
      end
    end
  end

  task automatic configure(input int count, dense_count, result_count, start, test_mode, fault_mode,
                           input logic [31:0] tag, input int layout_fault = 0);
    int timeout;
    begin
      @(negedge clk);
      cfg_valid = 1;
      cfg_tag = tag;
      cfg_features = 10'(count);
      cfg_dense_features = 17'(dense_count);
      cfg_output_count = 9'(result_count);
      cfg_output_start = 16'(start);
      cfg_activation_base = ActBase;
      cfg_weight_base = GateBase;
      cfg_up_weight_base = UpBase;
      cfg_down_weight_base = DownBase;
      cfg_gate_sign_base = GateSignBase;
      cfg_up_sign_base = UpSignBase;
      cfg_activation_shift = 17;
      cfg_raw_base = RawBase;
      cfg_gamma_base = GammaBase;
      if (layout_fault == 1) cfg_gate_sign_base = ActBase;
      if (layout_fault == 2) cfg_activation_base = 64'hfffffffffffffff8;
      if (layout_fault == 3) cfg_weight_base = ActBase + 64'd8;
      if (layout_fault == 4) cfg_activation_base = 64'hffffffffffffff68;
      if (layout_fault == 5) cfg_raw_base = RawBase + 1;
      if (layout_fault == 6) cfg_gamma_base = 64'hfffffffffffffff0;
      source_raw_base = cfg_raw_base;
      source_gamma_base = cfg_gamma_base;
      raw_requests = 0;
      gamma_requests = 0;
      cfg_epsilon_q16 = 0;
      cfg_gate_shift = 0;
      cfg_up_shift = 0;
      cfg_down_shift = 4;
      features = count;
      dense = dense_count;
      outputs = result_count;
      output_start = start;
      mode = test_mode;
      fault = fault_mode;
      fault_done = 0;
      requests = 0;
      sign_requests = 0;
      force_request_stall = 0;
      poisoned_hold_exercised = 0;
      compute_requests = 0;
      down_requests = 0;
      gate_rows = '0;
      up_rows = '0;
      timeout = 0;
      @(posedge clk);
      while (!cfg_ready && timeout < 100) begin
        @(posedge clk);
        timeout++;
      end
      if (!cfg_ready) $fatal(1, "MEMORY_FF_CONFIG_TIMEOUT");
      @(negedge clk);
      cfg_valid = 0;
      cfg_tag = '1;
      cfg_features = 0;
      cfg_dense_features = 0;
      cfg_output_count = 0;
      cfg_output_start = '1;
      cfg_gate_shift = '1;
      cfg_up_shift = '1;
      cfg_down_shift = '1;
      cfg_activation_base = '1;
      cfg_weight_base = '1;
      cfg_up_weight_base = '1;
      cfg_down_weight_base = '1;
      cfg_gate_sign_base = '1;
      cfg_up_sign_base = '1;
      cfg_epsilon_q16 = '1;
      cfg_activation_shift = '1;
      cfg_raw_base = '1;
      cfg_gamma_base = '1;
    end
  endtask
  task automatic frame(input int id, input bit last);
    int timeout;
    begin
      @(negedge clk);
      group_valid = 1;
      group_id = 11'(id);
      group_last = last;
      timeout = 0;
      @(posedge clk);
      while (group_ready !== 1'b1 && timeout < 100000) begin
        @(posedge clk);
        timeout++;
      end
      if (group_ready !== 1'b1) $fatal(1, "MEMORY_FF_GROUP_TIMEOUT");
      @(negedge clk);
      group_valid = 0;
      group_id = '1;
      group_last = !last;
    end
  endtask
  task automatic tensor(input int groups);
    begin
      if (CachedMode == 0 || (fault != 7 && fault != 8))
        for (int id = 0; id < groups; id++) frame(id, id == groups - 1);
    end
  endtask
  task automatic result(input bit error, input logic [31:0] tag);
    int offset, count, timeout, expected, value;
    bit last;
    logic [1576:0] held;
    begin
      offset = 0;
      do begin
        count = error ? 0 : ((outputs - offset > 32) ? 32 : outputs - offset);
        last = error || offset + count == outputs;
        timeout = 0;
        while (out_valid !== 1'b1 && timeout < 300000) begin
          @(negedge clk);
          timeout++;
        end
        if (out_valid !== 1'b1) $fatal(1, "MEMORY_FF_RESULT_TIMEOUT tag=%h", tag);
        if({out_tag,out_error,out_fallback,out_count,out_last}!=={tag,error,1'b0,6'(count),last})
          $fatal(
              1,
              "MEMORY_FF_METADATA tag=%h count=%0d error=%b last=%b fallback=%b",
              out_tag,
              out_count,
              out_error,
              out_last,
              out_fallback
          );
        for (int row = 0; row < 32; row++) begin
          expected = 0;
          if (row < count) begin
            if (out_channels[row*16+:16] !== 16'(output_start + offset + row))
              $fatal(1, "MEMORY_FF_CHANNEL_ID");
            for (int column = 0; column < dense; column++)
            if (allowed(column)) begin
              // For H=152, gate=2432: positive SiLU tail is exact.
              // up=-152/152/304 -> gated=-1444/1444/2888 Q8.
              // Round/shift4 and signed8 saturation: -90/90/127.
              if (features == 19 && CachedMode == 0)
                value = column % 3 == 0 ? -90 : (column % 3 == 1 ? 90 : 127);
              else value = column % 3 == 0 ? -128 : 127;
              expected += value * down_weight(output_start + offset + row, column);
            end
          end
          if (out_data[row*32+:32] !== 32'(expected))
            $fatal(
                1,
                "MEMORY_FF_SUM row=%0d got=%0d expected=%0d",
                row,
                $signed(
                    out_data[row*32+:32]
                ),
                expected
            );
        end
        if (error && out_channels !== 512'b0) $fatal(1, "MEMORY_FF_ERROR_CHANNELS");
        held = {out_count, out_last, out_error, out_fallback, out_tag, out_channels, out_data};
        @(negedge clk);
        cfg_valid   = 1;
        group_valid = 1;
        repeat (5) begin
          @(posedge clk);
          #1;
          if (!out_valid || cfg_ready || group_ready ||
              {out_count, out_last, out_error, out_fallback, out_tag,
               out_channels, out_data} !== held)
            $fatal(1, "MEMORY_FF_HELD_RESULT_CHANGED");
        end
        @(negedge clk);
        cfg_valid   = 0;
        group_valid = 0;
        out_ready   = 1;
        @(negedge clk);
        out_ready = 0;
        offset = error ? outputs : offset + count;
      end while (!error && offset < outputs);
      if (error && memory_active) $fatal(1, "ERROR_BEFORE_RESPONSE_LAST");
      if (!error) begin
        if (raw_requests != 2 * features || gamma_requests != features)
          $fatal(1, "SOURCE_TRAFFIC_COUNT");
        for (int channel = 0; channel < dense; channel++)
        if (gate_rows[channel] !== allowed(channel) || up_rows[channel] !== allowed(channel))
          $fatal(1, "MEMORY_FF_MISSING_OR_EXTRA_ROW");
        if (sign_requests != (mode == 3 ? 0 : 2 * (dense / 32)))
          $fatal(1, "MEMORY_FF_SIGN_REQUEST_COUNT");
      end
      checked++;
      $display("MEMORY_FF_CASE_PASS tag=%h error=%b cycles=%0d sign=%0d compute=%0d", tag, error,
               cycle, sign_requests, compute_requests);
    end
  endtask
  task automatic shared_reset;
    begin
      @(negedge clk);
      rst_n = 0;
      cfg_valid = 0;
      group_valid = 0;
      out_ready = 0;
      repeat (2) @(negedge clk);
      rst_n = 1;
      repeat (4) begin
        @(posedge clk);
        #1;
        if (out_valid || req_valid || rsp_ready || !cfg_ready || group_ready)
          $fatal(1, "MEMORY_FF_RESET_LEFT_CONTEXT");
      end
    end
  endtask
  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    configure(19, 64, 35, 17, 0, 0, 32'h100);
    tensor(2);
    result(0, 32'h100);
    configure(19, 96, 35, 17, 2, 10, 32'h101);
    if (CachedMode == 0) tensor(3);
    else begin
      frame(0, 0);
      wait (group_ready && req_valid && !req_ready && !memory_active);
      force_request_stall = 1;
      frame(3, 1);
      repeat (12) begin
        @(negedge clk);
        if (!req_valid || req_ready) $fatal(1, "CACHED_FF_POISON_WITHDREW_REQUEST");
      end
      poisoned_hold_exercised = 1;
      force_request_stall = 0;
    end
    result(1, 32'h101);
    if (!poisoned_hold_exercised) $fatal(1, "MEMORY_FF_POISON_HOLD_NOT_REACHED");
    configure(19, 192, 65, 31, 2, 9, 32'h200);
    tensor(6);
    result(0, 32'h200);
    configure(19, 32, 480, 0, 2, 0, 32'h300);
    tensor(1);
    result(0, 32'h300);
    configure(19, 64, 33, 0, 1, 0, 32'h400);
    tensor(2);
    result(0, 32'h400);
    if (compute_requests != 0) $fatal(1, "MEMORY_FF_ALL_SKIPPED_COMPUTED");
    configure(19, 64, 35, 17, 3, 0, 32'h401);
    tensor(2);
    result(0, 32'h401);
    configure(19, 64, 35, 17, 0, 1, 32'h501);
    tensor(2);
    result(1, 32'h501);
    configure(19, 64, 35, 17, 0, 2, 32'h502);
    tensor(2);
    result(1, 32'h502);
    configure(19, 64, 35, 17, 0, 3, 32'h503);
    tensor(2);
    result(1, 32'h503);
    configure(19, 32, 35, 17, 2, 4, 32'h504);
    tensor(1);
    result(1, 32'h504);
    configure(19, 64, 35, 17, 0, 5, 32'h505);
    tensor(2);
    result(1, 32'h505);
    configure(19, 64, 35, 17, 0, 6, 32'h506);
    tensor(2);
    result(1, 32'h506);
    configure(19, 64, 35, 17, 0, 7, 32'h507);
    tensor(2);
    result(1, 32'h507);
    configure(19, 64, 35, 17, 0, 8, 32'h508);
    tensor(2);
    result(1, 32'h508);
    configure(512, 32, 1, 65535, 2, 0, 32'h600);
    tensor(1);
    result(0, 32'h600);
    configure(19, 32, 481, 0, 2, 0, 32'h700);
    result(1, 32'h700);
    configure(19, 64, 3, 0, 2, 0, 32'h900);
    fork
      tensor(2);
    join_none
    wait (memory_active && active_phase == 5);
    disable fork;
    shared_reset();
    configure(19, 32, 3, 0, 2, 0, 32'h901);
    tensor(1);
    result(0, 32'h901);
    configure(19, 64, 3, 0, 2, 0, 32'h902);
    fork
      tensor(2);
    join_none
    wait (memory_active && active_phase == 1);
    disable fork;
    shared_reset();
    configure(19, 32, 3, 0, 2, 0, 32'h903);
    tensor(1);
    result(0, 32'h903);
    configure(19, 64, 35, 17, 0, 0, 32'h904);
    tensor(2);
    result(0, 32'h904);
    configure(19, 32, 3, 0, 2, 0, 32'h905);
    frame(1, 1);
    result(1, 32'h905);
    if (requests != 3 * features || sign_requests != 0 || compute_requests != 0)
      $fatal(1, "MEMORY_FF_INVALID_GROUP_STARTED_EXECUTION_READ");
    if (CachedMode != 0) begin
      configure(19, 32, 3, 0, 2, 0, 32'hf01, 1);
      result(1, 32'hf01);
      configure(19, 32, 3, 0, 2, 0, 32'hf02, 2);
      result(1, 32'hf02);
      configure(19, 32, 3, 0, 2, 0, 32'hf03, 3);
      result(1, 32'hf03);
      configure(19, 32, 3, 0, 2, 0, 32'hf04, 4);
      tensor(1);
      result(0, 32'hf04);
    end
    configure(19, 32, 3, 0, 2, 11, 32'h1002);
    result(1, 32'h1002);
    configure(19, 32, 3, 0, 2, 12, 32'h1003);
    result(1, 32'h1003);
    configure(19, 32, 3, 0, 2, 13, 32'h1004);
    result(1, 32'h1004);
    configure(19, 32, 3, 0, 2, 15, 32'h1005);
    result(1, 32'h1005);
    configure(19, 32, 3, 0, 4, 0, 32'h1010);
    result(1, 32'h1010);
    if (raw_requests != 2 * features || gamma_requests != features)
      $fatal(1, "NUMERICAL_ERROR_DID_NOT_DRAIN_READER");
    configure(19, 32, 3, 0, 4, 14, 32'h1011);
    wait (raw_requests == features && req_valid && !req_ready && !memory_active);
    force_request_stall = 1;
    repeat (12) begin
      @(negedge clk);
      if (!req_valid || req_ready || out_valid)
        $fatal(1, "PREPARATION_ERROR_WITHDREW_PRESENTED_READ");
    end
    if (!dut.core_out_valid) $fatal(1, "PREPARATION_ERROR_NOT_REACHED_DURING_STALL");
    force_request_stall = 0;
    result(1, 32'h1011);
    configure(19, 32, 3, 0, 2, 0, 32'h1020, 5);
    result(1, 32'h1020);
    if (requests != 0) $fatal(1, "BAD_RAW_ALLOCATION_READ_MEMORY");
    configure(19, 32, 3, 0, 2, 0, 32'h1021, 6);
    result(1, 32'h1021);
    if (requests != 0) $fatal(1, "BAD_COEFFICIENT_ALLOCATION_READ_MEMORY");
    configure(19, 32, 3, 0, 2, 0, 32'h1030);
    wait (memory_active && active_phase == 7);
    shared_reset();
    configure(19, 32, 3, 0, 2, 0, 32'h1031);
    tensor(1);
    result(0, 32'h1031);
    configure(19, 32, 3, 0, 2, 0, 32'h1032);
    wait (memory_active && active_phase == 8);
    shared_reset();
    configure(19, 32, 3, 0, 2, 0, 32'h1033);
    tensor(1);
    result(0, 32'h1033);
    if (checked != 34) $fatal(1, "WRONG_MEMORY_DRIVEN_CASE_INVENTORY %0d", checked);
    $display("MEMORY_FEEDFORWARD_PASS cases=%0d", checked);
    $finish;
  end
  initial begin
    #100000000;
    $fatal(1, "MEMORY_FF_WATCHDOG");
  end
endmodule
