`timescale 1ns / 1ps
// An independent transaction peer supplies completed projection sums.
// This bench checks controller integration, not twenty-core matrix execution.
module tri_oracle_fabric_gated_executor_tb;
  logic clk = 0;
  always #5 clk = ~clk;
  logic rst_n = 0;
  logic in_valid = 0, in_ready, in_last = 0, in_fallback = 0;
  logic [31:0] in_tag = 0;
  logic [2559:0] in_channels = 0;
  logic [7:0] in_count = 0;
  logic [63:0] in_activation_base = 0, in_weight_base = 0, in_up_weight_base = 0;
  logic [9:0] in_features = 0;
  logic [5:0] in_gate_shift = 0, in_up_shift = 0;
  logic out_valid, out_ready = 0, out_last, out_fallback, out_error;
  logic [31:0] out_tag;
  logic [7:0] out_count;
  logic [2559:0] out_channels;
  logic [5119:0] out_data;
  logic projection_in_valid, projection_in_ready = 0;
  logic projection_in_last, projection_in_fallback;
  logic [31:0] projection_in_tag;
  logic [2559:0] projection_in_channels;
  logic [7:0] projection_in_count;
  logic [63:0] projection_in_activation_base, projection_in_weight_base;
  logic [9:0] projection_in_features;
  logic projection_out_valid = 0, projection_out_ready;
  logic projection_out_last = 0, projection_out_fallback = 0, projection_out_error = 0;
  logic [31:0] projection_out_tag = 0;
  logic [2559:0] projection_out_channels = 0;
  logic [7:0] projection_out_count = 0;
  logic [5119:0] projection_out_data = 0;
  int cases = 0, requests = 0, sequence_id = 0, exact_input_checks = 0;
  int count, gate_shift, up_shift, seed;
  logic [31:0] tag;
  logic [2559:0] channels;
  logic last, fallback;

  tri_oracle_fabric_gated_executor dut (.*);

  function automatic int raw_value(input int row, phase, salt);
    if (row % 19 == 0) return phase == 0 ? 32'sh7fffffff : 32'sh80000000;
    if (row % 19 == 1) return phase == 0 ? 32'sh80000000 : 32'sh7fffffff;
    case (row % 19)
      2: return phase == 0 ? 32767 : -32768;
      3: return phase == 0 ? 32768 : -32769;
      4: return phase == 0 ? -32768 : 32767;
      5: return phase == 0 ? -32769 : 32768;
      6: return phase == 0 ? 65535 : -65537;
      7: return phase == 0 ? -65537 : 65535;
      8: return phase == 0 ? 3 : -3;
    endcase
    return phase == 0 ? ((row % 17)-8)*1024 + salt*3 :
                       ((row % 13)-6)*256 + salt*5;
  endfunction

  // Check exact code values before the approximate nonlinear unit. The oracle
  // uses real arithmetic, independently of the controller's integer shifts.
  always @(posedge clk) begin : exact_quantized_inputs
    int row;
    if (rst_n && dut.activation_unit.in_valid && dut.activation_unit.in_ready) begin
      row = int'(dut.activation_unit.in_tag);
      if (row >= count || dut.activation_unit.in_gate !==
          16'(rounded_code(raw_value(row, 0, seed), gate_shift)) ||
          dut.activation_unit.in_up !== 16'(rounded_code(raw_value(row, 1, seed), up_shift)))
        $fatal(1, "exact requantization mismatch row=%0d", row);
      exact_input_checks++;
    end
  end

  function automatic int rounded_code(input int raw, shift);
    real scaled;
    longint signed rounded;
    scaled = real'(raw)/(2.0**shift);
    rounded = scaled < 0 ? -longint'($floor(-scaled+0.5)) :
                           longint'($floor(scaled+0.5));
    return rounded > 32767 ? 32767 : rounded < -32768 ? -32768 : int'(rounded);
  endfunction

  function automatic int mathematical_result(input int row);
    real x, value;
    int g, u, rounded;
    g = rounded_code(raw_value(row, 0, seed), gate_shift);
    u = rounded_code(raw_value(row, 1, seed), up_shift);
    x = real'(g)/256.0;
    value = (x/(1.0+$exp(-x)))*real'(u);
    rounded = value < 0 ? -$rtoi(-value+0.5) : $rtoi(value+0.5);
    return rounded > 32767 ? 32767 : rounded < -32768 ? -32768 : rounded;
  endfunction

  task automatic launch(input int n, gs, us, invalid = 0);
    while (!in_ready) @(negedge clk);
    count = n;
    gate_shift = gs;
    up_shift = us;
    seed = sequence_id+1;
    tag = 32'h12340000+32'(sequence_id);
    last = sequence_id % 2 == 0;
    fallback = sequence_id % 3 == 0;
    channels = 0;
    for (int r = 0; r < 160; r++) channels[r*16+:16] = 16'(5631-r*3);
    in_count = 8'(n);
    in_gate_shift = 6'(gs);
    in_up_shift = 6'(us);
    in_tag = tag;
    in_channels = channels;
    in_last = last;
    in_fallback = fallback;
    in_features = invalid == 1 ? 10'd0 : invalid == 2 ? 10'd513 : 10'd256;
    in_activation_base = invalid == 5 ? 64'h1001 :
                         invalid == 7 ? 64'hfffffffffffffff8 : 64'h1000;
    in_weight_base = invalid == 6 ? 64'h200001 :
                     invalid == 8 ? 64'hfffffffffffffff8 : 64'h200000;
    in_up_weight_base = invalid == 3 ? 64'h400001 :
                        invalid == 4 ? 64'hfffffffffffffff8 : 64'h400000;
    in_valid = 1;
    @(negedge clk);
    in_valid = 0;
    // Requests must use captured inputs despite the next producer changing them.
    in_tag = ~tag;
    in_channels = ~channels;
    in_count = 0;
    in_weight_base = 0;
    in_up_weight_base = 0;
    sequence_id++;
  endtask

  task automatic serve(input int phase, fault = 0);
    logic [2739:0] held;
    while (!projection_in_valid) @(negedge clk);
    held = {projection_in_last, projection_in_fallback, projection_in_tag,
            projection_in_channels, projection_in_count, projection_in_activation_base,
            projection_in_weight_base, projection_in_features};
    repeat (3) begin
      @(negedge clk);
      if (!projection_in_valid || held !==
          {projection_in_last, projection_in_fallback, projection_in_tag,
           projection_in_channels, projection_in_count, projection_in_activation_base,
           projection_in_weight_base, projection_in_features})
        $fatal(1, "projection request changed during a stall");
    end
    if (projection_in_tag !== tag || projection_in_count !== 8'(count) ||
        projection_in_channels !== channels || projection_in_features !== 10'd256 ||
        projection_in_activation_base !== 64'h1000 ||
        projection_in_weight_base !== (phase == 0 ? 64'h200000 : 64'h400000) ||
        projection_in_last !== last || projection_in_fallback !== fallback)
      $fatal(1, "projection request does not describe the captured packet");
    projection_in_ready = 1;
    @(negedge clk);
    projection_in_ready = 0;
    requests++;
    repeat (2) @(negedge clk);
    projection_out_tag = fault == 2 ? tag ^ 32'd1 : tag;
    projection_out_count = fault == 3 ? 8'(count-1) : 8'(count);
    projection_out_channels = fault == 4 ? channels ^ 2560'd1 : channels;
    projection_out_last = fault == 5 ? !last : last;
    projection_out_fallback = fault == 6 ? !fallback : fallback;
    projection_out_error = fault == 1;
    projection_out_data = 0;
    for (int r = 0; r < count; r++)
      projection_out_data[r*32+:32] = 32'(raw_value(r, phase, seed));
    projection_out_valid = 1;
    @(posedge clk);
    while (!projection_out_ready) @(posedge clk);
    @(negedge clk);
`ifdef TRI_ORACLE_VERIFY_PROJECTION_CAPTURE
    if ((phase == 0 ? dut.gate_values : dut.up_values) !== projection_out_data)
      $fatal(1, "PROJECTION_CAPTURE_MISMATCH phase=%0d fault=%0d", phase, fault);
    if (fault != 0 && dut.activation_unit.in_valid)
      $fatal(1, "failed projection reached activation phase=%0d fault=%0d", phase, fault);
`endif
    projection_out_valid = 0;
    projection_out_error = 0;
  endtask

  task automatic check_result(input bit error_expected);
    logic [7722:0] held;
    int actual, expected, tolerance, u;
    while (!out_valid) @(negedge clk);
    if (out_error !== error_expected || out_tag !== tag ||
        out_count !== (error_expected ? 8'd0 : 8'(count)))
      $fatal(1, "result metadata/error mismatch");
    if (out_last !== (error_expected || last) ||
        out_fallback !== (!error_expected && fallback)) $fatal(1, "frame flags mismatch");
    if (error_expected) begin
      if (out_data !== 0 || out_channels !== 0) $fatal(1, "failed packet exposed payload");
    end else begin
      if (out_channels !== channels) $fatal(1, "selected channel identifiers changed");
      for (int r = 0; r < count; r++) begin
        actual = int'($signed(out_data[r*32+:32]));
        expected = mathematical_result(r);
        if ($test$plusargs("CORRUPT_REFERENCE") && r == 2) expected += 10000;
        u = rounded_code(raw_value(r, 1, seed), up_shift);
        tolerance = (2*(u < 0 ? -u : u)+255)/256+1;
        if ((^out_data[r*32+:32]) === 1'bx ||
            actual-expected > tolerance || expected-actual > tolerance)
          $fatal(1, "gated mathematical mismatch row=%0d got=%0d expected=%0d", r,
                 actual, expected);
      end
      for (int r = count; r < 160; r++)
        if (out_data[r*32+:32] !== 0) $fatal(1, "inactive output lane is not zero");
    end
    held = {out_last, out_fallback, out_error, out_tag, out_count, out_channels, out_data};
    repeat (5) begin
      @(negedge clk);
      if (!out_valid || held !==
          {out_last, out_fallback, out_error, out_tag, out_count, out_channels, out_data})
        $fatal(1, "blocked gated result changed");
      if (in_ready || projection_in_valid) $fatal(1, "overlapping packet ownership");
    end
    out_ready = 1;
    @(negedge clk);
    out_ready = 0;
    cases++;
  endtask

  initial begin
    repeat (3) @(negedge clk);
    rst_n = 1;
    for (int n = 0; n < 7; n++) begin
      case (n)
        0: count = 0;
        1: count = 1;
        2: count = 31;
        3: count = 32;
        4: count = 33;
        5: count = 159;
        6: count = 160;
      endcase
      launch(count, n == 5 ? 32 : n == 6 ? 33 : n, n == 5 ? 32 : n);
      if (count > 0) begin serve(0); serve(1); end
      check_result(0);
    end
    launch(33, 31, 31);
    serve(0);
    serve(1);
    check_result(0);
    launch(33, 63, 63);
    serve(0);
    serve(1);
    check_result(0);
    for (int fault = 1; fault <= 6; fault++) begin
      launch(32, 1, 1);
      serve(0, fault);
      check_result(1);
      launch(160, 2, 3);
      serve(0);
      serve(1, fault);
      check_result(1);
    end
    for (int invalid = 1; invalid <= 8; invalid++) begin
      launch(32, 0, 0, invalid);
      check_result(1);
    end
    launch(161, 0, 0);
    check_result(1);
    // Reset cancels a packet after full sums arrive but before activation drains.
    launch(160, 0, 0);
    serve(0);
    serve(1);
    repeat (10) @(negedge clk);
    rst_n = 0;
    repeat (2) @(negedge clk);
    if (out_valid || projection_in_valid) $fatal(1, "reset leaked a pending packet");
    rst_n = 1;
    launch(33, 0, 0);
    serve(0);
    serve(1);
    check_result(0);
    if (exact_input_checks < 500) $fatal(1, "exact quantization checks did not execute");
    $display("FABRIC_GATED_EXACT_QUANTIZATION_PASS checks=%0d", exact_input_checks);
`ifdef TRI_ORACLE_VERIFY_PROJECTION_CAPTURE
    $display("FABRIC_GATED_LOCAL_CAPTURE_PASS packets=%0d", requests);
`endif
    $display("FABRIC_GATED_CONTROLLER_PASS cases=%0d projection_requests=%0d", cases, requests);
    $finish;
  end

  initial begin
    #1000000;
    $fatal(1, "fabric gated controller watchdog");
  end
endmodule
