`timescale 1ns / 1ps
// Real five-cluster compiled-memory execution, with an independent byte-addressed
// memory peer and scalar dot products followed by a real-valued activation oracle.
module tri_oracle_gated_fabric_tb;
  localparam logic [63:0] ActBase = 64'h100002000;
  localparam logic [63:0] GateBase = 64'h200004000;
  localparam logic [63:0] UpBase = 64'h400006000;
  logic clk = 0;
  always #5 clk = ~clk;
  logic rst_n = 0, in_valid = 0, in_last = 0, in_fallback = 0;
  logic in_ready, out_valid, out_ready = 0, out_last, out_fallback, out_error;
  logic [31:0] in_tag = 0, out_tag;
  logic [2559:0] in_channels = 0, out_channels;
  logic [7:0] in_count = 0, out_count;
  logic [63:0] in_activation_base = ActBase;
  logic [63:0] in_weight_base = GateBase, in_up_weight_base = UpBase;
  logic [9:0] in_features = 0;
  logic [5:0] in_gate_shift = 4, in_up_shift = 5;
  logic [5119:0] out_data;
  logic req_valid, req_ready, rsp_valid = 0, rsp_last = 0, rsp_error = 0, rsp_ready;
  logic [63:0] req_address, rsp_data = 0;
  logic [4:0] req_length;
  int core_instances = 0, cluster_instances = 0;
  int weight_mask_memories = 0, activation_memories = 0, result_memories = 0;
  int cycle = 0, beat = 0, burst_length = 0;
  int strips = 0, rows = 0, seed = 0, cases = 0, reset_cases = 0;
  int weight_bytes[2], activation_bytes = 0, requests = 0;
  int expected[160], tolerance[160];
  int expected_dot[2][160], pending_matrix = -1, exact_dot_values = 0;
  bit memory_active = 0, weight_burst = 0, up_burst = 0;
  bit inject_error = 0, fault_fired = 0, inject_burst = 0, request_held = 0;
  bit force_request_stall = 0, force_response_gap = 0;
  logic [63:0] address = 0;
  logic [68:0] held_request;
  logic [2559:0] expected_channels;
  tri_oracle_gated_fabric dut (.*);

  always_comb
    req_ready = !memory_active && !rsp_valid && cycle % 4 != 0 && !force_request_stall;

  function automatic int activation_value(input int feature);
    return ((feature*17+seed*11) % 29)-14;
  endfunction

  // Verify integer matrix arithmetic exactly before nonlinear approximation.
  always @(posedge clk) begin : exact_projection_sums
    int reference_sum;
    if (!rst_n) pending_matrix = -1;
    else begin
      if (dut.projection_in_valid && dut.projection_in_ready) begin
        if (dut.projection_in_weight_base == GateBase) pending_matrix = 0;
        else if (dut.projection_in_weight_base == UpBase) pending_matrix = 1;
        else $fatal(1, "unrecognized projection matrix base");
      end
      if (dut.projection_out_valid && dut.projection_out_ready &&
          !dut.projection_out_error) begin
        if (pending_matrix < 0) $fatal(1, "projection result has no matrix owner");
        for (int r = 0; r < rows; r++) begin
          reference_sum = expected_dot[pending_matrix][r];
          if ($test$plusargs("CORRUPT_DOT_REFERENCE") && pending_matrix == 0 && r == 0)
            reference_sum++;
          if (dut.projection_out_data[r*32+:32] !== 32'(reference_sum))
            $fatal(1, "exact fabric dot mismatch matrix=%0d row=%0d got=%0d expected=%0d",
                   pending_matrix, r, $signed(dut.projection_out_data[r*32+:32]),
                   reference_sum);
          exact_dot_values++;
        end
      end
    end
  end

  function automatic int weight_value(input int channel, feature, phase);
    return phase == 0 ? ((channel*7+feature*13+seed*3) % 31)-15 :
                        ((channel*11+feature*5+seed*7) % 23)-11;
  endfunction

  function automatic int code_value(input int raw, shift);
    real value;
    int rounded;
    value = real'(raw)/(2.0**shift);
    rounded = value < 0 ? -$rtoi(-value+0.5) : $rtoi(value+0.5);
    return rounded > 32767 ? 32767 : rounded < -32768 ? -32768 : rounded;
  endfunction

  function automatic bit selected(input int channel);
    for (int r = 0; r < rows; r++)
      if (channel == int'(expected_channels[r*16+:16])) return 1;
    return 0;
  endfunction

  always @(posedge clk) begin : memory_peer
    logic [63:0] offset, cursor, base;
    bit activation_request, up_request;
    int channel, feature;
    if (!rst_n) begin
      cycle <= 0;
      memory_active <= 0;
      rsp_valid <= 0;
      request_held = 0;
    end else begin
      cycle <= cycle+1;
      if (out_valid && (memory_active || rsp_valid))
        $fatal(1, "gated result precedes memory-response drain");
      if (request_held && (req_valid !== 1'b1 ||
          {req_address, req_length} !== held_request)) $fatal(1, "unstable memory request");
      request_held = req_valid && !req_ready;
      held_request = {req_address, req_length};
      if (req_valid && req_ready) begin
        if (req_length == 0 || req_length > 16 || req_address[2:0] != 0)
          $fatal(1, "invalid memory request");
        memory_active <= 1;
        address <= req_address;
        burst_length <= int'(req_length);
        beat <= 0;
        activation_request = req_address >= ActBase &&
            req_address < ActBase+64'(strips*8);
        up_request = req_address >= UpBase;
        base = up_request ? UpBase : GateBase;
        weight_burst <= !activation_request;
        up_burst <= up_request;
        inject_burst <= inject_error && !fault_fired && !activation_request && up_request;
        if (inject_error && !fault_fired && !activation_request && up_request)
          fault_fired = 1;
        requests++;
        if (activation_request) begin
          if (req_address+64'(req_length*8) > ActBase+64'(strips*8))
            $fatal(1, "activation read exceeds the full vector");
          activation_bytes += int'(req_length)*8;
        end else begin
          if (req_address < base) $fatal(1, "weight address aliases the wrong matrix");
          offset = req_address-base;
          channel = int'(offset/64'(strips*8));
          if (!selected(channel) || offset % 64'(strips*8)+64'(req_length*8) >
              64'(strips*8)) $fatal(1, "weight row/stride mismatch");
          weight_bytes[up_request ? 1 : 0] += int'(req_length)*8;
        end
      end
      if (memory_active && !rsp_valid && cycle % 3 != 0 && !force_response_gap) begin
        rsp_valid <= 1;
        rsp_last <= beat == burst_length-1;
        rsp_error <= inject_burst && beat == 0;
        base = up_burst ? UpBase : GateBase;
        for (int lane = 0; lane < 8; lane++) begin
          cursor = address+64'(beat*8+lane);
          if (weight_burst) begin
            offset = cursor-base;
            channel = int'(offset/64'(strips*8));
            feature = int'(offset % 64'(strips*8));
            rsp_data[lane*8+:8] <= 8'(weight_value(channel, feature, up_burst ? 1 : 0));
          end else rsp_data[lane*8+:8] <= 8'(activation_value(int'(cursor-ActBase)));
        end
      end
      if (rsp_valid && rsp_ready) begin
        rsp_valid <= 0;
        if (rsp_last) memory_active <= 0;
        else beat <= beat+1;
      end
    end
  end

  task automatic run_case(input int feature_strips, row_count, case_seed, fault);
    int channel, gate_sum, up_sum, g, u, rounded, actual;
    real x, value;
    logic [7722:0] held;
    while (!in_ready) @(negedge clk);
    if (memory_active || rsp_valid) $fatal(1, "memory context was not drained");
    strips = feature_strips;
    rows = row_count;
    seed = case_seed;
    inject_error = fault != 0;
    fault_fired = 0;
    weight_bytes[0] = 0;
    weight_bytes[1] = 0;
    activation_bytes = 0;
    requests = 0;
    in_count = 8'(rows);
    in_features = 10'(strips);
    in_tag = 32'h6a7e0000+32'(cases);
    in_last = cases % 2 == 0;
    in_fallback = cases % 3 == 0;
    in_channels = 0;
    for (int r = 0; r < rows; r++) begin
      channel = 5631-r*17;
      in_channels[r*16+:16] = 16'(channel);
      gate_sum = 0;
      up_sum = 0;
      for (int f = 0; f < strips*8; f++) begin
        gate_sum += activation_value(f)*weight_value(channel, f, 0);
        up_sum += activation_value(f)*weight_value(channel, f, 1);
      end
      expected_dot[0][r] = gate_sum;
      expected_dot[1][r] = up_sum;
      g = code_value(gate_sum, int'(in_gate_shift));
      u = code_value(up_sum, int'(in_up_shift));
      x = real'(g)/256.0;
      value = x/(1.0+$exp(-x))*real'(u);
      rounded = value < 0 ? -$rtoi(-value+0.5) : $rtoi(value+0.5);
      expected[r] = rounded > 32767 ? 32767 : rounded < -32768 ? -32768 : rounded;
      tolerance[r] = (2*(u < 0 ? -u : u)+255)/256+1;
    end
    expected_channels = in_channels;
    in_valid = 1;
    @(negedge clk);
    in_valid = 0;
    while (!out_valid) @(negedge clk);
    if (out_tag !== in_tag || out_error !== (fault != 0) ||
        out_count !== (fault != 0 ? 8'd0 : 8'(rows))) $fatal(1, "gated fabric metadata");
    if (fault != 0) begin
      if (!fault_fired || !out_last || out_data !== 0 || out_channels !== 0)
        $fatal(1, "up-matrix memory error failed to abort the packet");
    end else begin
      if (out_channels !== expected_channels || out_last !== in_last ||
          out_fallback !== in_fallback) $fatal(1, "gated fabric identifiers or flags");
      if (weight_bytes[0] != rows*strips*8 || weight_bytes[1] != rows*strips*8 ||
          activation_bytes != 2*strips*8*((rows+31)/32))
        $fatal(1, "gate/up fabric traffic is not the expected complete projection");
      for (int r = 0; r < rows; r++) begin
        actual = int'($signed(out_data[r*32+:32]));
        if ((^out_data[r*32+:32]) === 1'bx || actual-expected[r] > tolerance[r] ||
            expected[r]-actual > tolerance[r])
          $fatal(1, "full fabric gated arithmetic row=%0d got=%0d expected=%0d",
                 r, actual, expected[r]);
      end
    end
    held = {out_last, out_fallback, out_error, out_tag, out_count, out_channels, out_data};
    repeat (5) begin
      @(negedge clk);
      if (!out_valid || held !==
          {out_last, out_fallback, out_error, out_tag, out_count, out_channels, out_data})
        $fatal(1, "gated fabric result changed under backpressure");
    end
    out_ready = 1;
    @(negedge clk);
    out_ready = 0;
    cases++;
    $display("GATED_FABRIC_CASE_PASS case=%0d strips=%0d rows=%0d error=%0d requests=%0d",
             cases, strips, rows, fault, requests);
  endtask

  task automatic reset_outstanding(input bit response_gap);
    while (!in_ready) @(negedge clk);
    strips = 4;
    rows = 33;
    seed = 19;
    inject_error = 0;
    fault_fired = 0;
    force_request_stall = !response_gap;
    force_response_gap = response_gap;
    in_count = 8'(rows);
    in_features = 10'(strips);
    in_tag = 32'hab070000+32'(reset_cases);
    in_channels = 0;
    for (int r = 0; r < rows; r++) in_channels[r*16+:16] = 16'(5631-r*17);
    expected_channels = in_channels;
    in_valid = 1;
    @(negedge clk);
    in_valid = 0;
    if (response_gap) begin
      while (!memory_active) @(negedge clk);
      if (rsp_valid) $fatal(1, "response-gap reset did not hold the response");
    end else begin
      while (!req_valid) @(negedge clk);
      if (req_ready) $fatal(1, "request-stall reset did not hold the request");
    end
    repeat (3) @(negedge clk);
    // Reset the controller, real fabric and its transaction peer together.
    rst_n = 0;
    repeat (2) @(negedge clk);
    if (out_valid || req_valid || rsp_valid || memory_active)
      $fatal(1, "coordinated reset leaked an outstanding memory transaction");
    force_request_stall = 0;
    force_response_gap = 0;
    rst_n = 1;
    reset_cases++;
    $display("GATED_FABRIC_OUTSTANDING_RESET_PASS response_gap=%0d", response_gap);
  endtask

  initial begin
    #1;
    if (core_instances != 20 || cluster_instances != 5 || weight_mask_memories != 360 ||
        activation_memories != 40 || result_memories != 200)
      $fatal(1, "wrong actual compiled hierarchy cores=%0d clusters=%0d memories=%0d/%0d/%0d",
             core_instances, cluster_instances, weight_mask_memories,
             activation_memories, result_memories);
    $display("GATED_FABRIC_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600");
    repeat (3) @(negedge clk);
    rst_n = 1;
    run_case(4, 1, 3, 0);
    run_case(68, 33, 7, 0);
    run_case(256, 160, 11, 0);
    run_case(4, 33, 13, 1);
    run_case(4, 33, 17, 0);
    reset_outstanding(0);
    run_case(4, 33, 23, 0);
    reset_outstanding(1);
    run_case(4, 33, 29, 0);
    if (reset_cases != 2) $fatal(1, "outstanding-transaction reset cases did not run");
    if (exact_dot_values != 619) $fatal(1, "exact dot-product coverage count mismatch");
    $display("GATED_FABRIC_EXACT_DOT_PRODUCTS_PASS values=%0d", exact_dot_values);
    $display("GATED_FABRIC_PASS cases=%0d cores=20 compiled_memories=600", cases);
    $finish;
  end

  initial begin
    #100000000;
    $fatal(1, "gated fabric watchdog");
  end
endmodule

module tri_oracle_gated_fabric_instance_count #(parameter int KIND = 0) ();
  initial begin
    case (KIND)
      0: $root.tri_oracle_gated_fabric_tb.core_instances++;
      1: $root.tri_oracle_gated_fabric_tb.cluster_instances++;
      2: $root.tri_oracle_gated_fabric_tb.weight_mask_memories++;
      3: $root.tri_oracle_gated_fabric_tb.activation_memories++;
      4: $root.tri_oracle_gated_fabric_tb.result_memories++;
    endcase
  end
endmodule

bind tri_oracle_sram_memory_compute tri_oracle_gated_fabric_instance_count
    #(.KIND(0)) count_actual_core ();
bind tri_oracle_sram_compute_cluster tri_oracle_gated_fabric_instance_count
    #(.KIND(1)) count_actual_cluster ();
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_gated_fabric_instance_count
    #(.KIND(2)) count_actual_weight_mask ();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_gated_fabric_instance_count
    #(.KIND(3)) count_actual_activation ();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_gated_fabric_instance_count
    #(.KIND(4)) count_actual_result ();
