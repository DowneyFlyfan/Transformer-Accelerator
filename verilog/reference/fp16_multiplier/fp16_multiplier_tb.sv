module fp16_multiplier_tb;

  localparam int BW = 16;
  localparam int SIGNIFICANT_BW = 10;
  localparam int EXP_BW = 5;
  localparam int ADDER_TREE_STAGE = $clog2(SIGNIFICANT_BW) + 1;
  localparam int PIPESTAGE = ADDER_TREE_STAGE + 1;
  localparam int EXP_BIAS = 15;

  // FP16 special value encodings
  localparam logic [BW-1:0] POS_INF  = 16'h7C00;
  localparam logic [BW-1:0] NEG_INF  = 16'hFC00;
  localparam logic [BW-1:0] POS_ZERO = 16'h0000;
  localparam logic [BW-1:0] NEG_ZERO = 16'h8000;
  localparam logic [BW-1:0] CANON_NAN = 16'h7C01;

  logic                 clk;
  logic signed [BW-1:0] in1;
  logic signed [BW-1:0] in2;
  logic        [BW-1:0] out;

  fp16_multiplier dut (
      .clk(clk),
      .in1(in1),
      .in2(in2),
      .out(out)
  );

  // Clock: 10ns period
  initial clk = 0;
  always #5 clk = ~clk;

  // Pipeline tracking queue
  logic [BW-1:0] expected_queue [$];
  logic [BW-1:0] in1_queue [$];
  logic [BW-1:0] in2_queue [$];

  int total_tests;
  int pass_count;
  int fail_count;

  // Convert FP16 bit pattern to real
  function automatic real fp16_to_real(
    input logic [BW-1:0] fp
  );
    logic          sign;
    logic [4:0]    exp_bits;
    logic [9:0]    mantissa;
    real           result;
    int            exponent;

    sign     = fp[15];
    exp_bits = fp[14:10];
    mantissa = fp[9:0];

    if (exp_bits == 5'b11111) begin
      // Inf or NaN — return large value as placeholder
      if (mantissa == 0)
        result = sign ? -65536.0 : 65536.0;
      else
        result = 0.0;  // NaN placeholder
    end else if (exp_bits == 0) begin
      // Zero or subnormal
      if (mantissa == 0) begin
        result = 0.0;
      end else begin
        // Subnormal: (-1)^s * 2^(-14) * 0.mantissa
        result = $itor(mantissa) / 1024.0;
        result = result * (2.0 ** (-14));
        if (sign) result = -result;
      end
    end else begin
      // Normal: (-1)^s * 2^(e-15) * 1.mantissa
      exponent = int'(exp_bits) - EXP_BIAS;
      result = 1.0 + $itor(mantissa) / 1024.0;
      result = result * (2.0 ** exponent);
      if (sign) result = -result;
    end

    return result;
  endfunction

  // Convert real to FP16 bit pattern (round to nearest even)
  function automatic logic [BW-1:0] real_to_fp16(
    input real val
  );
    logic          sign;
    logic [4:0]    exp_bits;
    logic [9:0]    mantissa;
    real           abs_val;
    int            exponent;
    real           frac;

    if (val == 0.0)
      return POS_ZERO;

    sign = (val < 0.0);
    abs_val = sign ? -val : val;

    // Find exponent: abs_val = frac * 2^exponent, 1.0 <= frac < 2.0
    exponent = 0;
    frac = abs_val;

    if (frac >= 2.0) begin
      while (frac >= 2.0) begin
        frac = frac / 2.0;
        exponent = exponent + 1;
      end
    end else if (frac < 1.0) begin
      while (frac < 1.0) begin
        frac = frac * 2.0;
        exponent = exponent - 1;
      end
    end
    // Now frac is in [1.0, 2.0), abs_val = frac * 2^exponent

    // Biased exponent
    exponent = exponent + EXP_BIAS;

    if (exponent >= 31) begin
      // Overflow to infinity
      return {sign, 5'b11111, 10'b0};
    end else if (exponent <= 0) begin
      // Underflow to zero (skip subnormals for simplicity)
      return {sign, 15'b0};
    end else begin
      exp_bits = exponent[4:0];
      // mantissa = (frac - 1.0) * 1024, truncated
      mantissa = int'((frac - 1.0) * 1024.0);
      return {sign, exp_bits, mantissa};
    end
  endfunction

  // Compute expected FP16 multiply result
  function automatic logic [BW-1:0] fp16_mul_ref(
    input logic [BW-1:0] a,
    input logic [BW-1:0] b
  );
    logic       a_sign, b_sign;
    logic [4:0] a_exp, b_exp;
    logic [9:0] a_man, b_man;
    logic       a_is_inf, b_is_inf;
    logic       a_is_nan, b_is_nan;
    logic       a_is_zero, b_is_zero;
    logic       r_sign;
    real        a_real, b_real, r_real;

    a_sign = a[15];     b_sign = b[15];
    a_exp  = a[14:10];  b_exp  = b[14:10];
    a_man  = a[9:0];    b_man  = b[9:0];

    a_is_inf  = (a_exp == 5'b11111) && (a_man == 0);
    b_is_inf  = (b_exp == 5'b11111) && (b_man == 0);
    a_is_nan  = (a_exp == 5'b11111) && (a_man != 0);
    b_is_nan  = (b_exp == 5'b11111) && (b_man != 0);
    a_is_zero = (a_exp == 0) && (a_man == 0);
    b_is_zero = (b_exp == 0) && (b_man == 0);
    r_sign    = a_sign ^ b_sign;

    // NaN propagation
    if (a_is_nan || b_is_nan)
      return CANON_NAN;

    // Inf * 0 = NaN
    if ((a_is_inf && b_is_zero) || (b_is_inf && a_is_zero))
      return CANON_NAN;

    // Inf * finite = Inf
    if (a_is_inf || b_is_inf)
      return r_sign ? NEG_INF : POS_INF;

    // Zero * finite = Zero (preserve sign per IEEE 754)
    if (a_is_zero || b_is_zero)
      return r_sign ? NEG_ZERO : POS_ZERO;

    // Normal * Normal
    a_real = fp16_to_real(a);
    b_real = fp16_to_real(b);
    r_real = a_real * b_real;

    return real_to_fp16(r_real);
  endfunction

  // Check if value is NaN
  function automatic logic is_nan(
    input logic [BW-1:0] fp
  );
    return (fp[14:10] == 5'b11111) && (fp[9:0] != 0);
  endfunction

  // Compare output with expected, allowing 1 ULP tolerance
  function automatic logic fp16_approx_eq(
    input logic [BW-1:0] actual,
    input logic [BW-1:0] expected
  );
    // Both NaN
    if (is_nan(actual) && is_nan(expected))
      return 1'b1;

    // Exact match
    if (actual == expected)
      return 1'b1;

    // Allow +-1 ULP (Unit in the Last Place) for rounding
    if (actual[15] == expected[15]) begin
      logic [14:0] a_mag, e_mag;
      a_mag = actual[14:0];
      e_mag = expected[14:0];
      if (a_mag > e_mag)
        return (a_mag - e_mag) <= 1;
      else
        return (e_mag - a_mag) <= 1;
    end

    return 1'b0;
  endfunction

  // Format FP16 for display
  function automatic string fp16_str(
    input logic [BW-1:0] fp
  );
    if (fp[14:10] == 5'b11111 && fp[9:0] == 0)
      return fp[15] ? "-Inf" : "+Inf";
    else if (fp[14:10] == 5'b11111)
      return "NaN";
    else begin
      real v;
      v = fp16_to_real(fp);
      return $sformatf("%f (0x%04h)", v, fp);
    end
  endfunction

  // Send one test vector and push expected result
  task automatic send_test(
    input logic [BW-1:0] a,
    input logic [BW-1:0] b,
    input logic [BW-1:0] exp_val
  );
    @(posedge clk);
    in1 <= $signed(a);
    in2 <= $signed(b);
    expected_queue.push_back(exp_val);
    in1_queue.push_back(a);
    in2_queue.push_back(b);
  endtask

  // Drain remaining pipeline results
  task automatic drain_pipeline();
    repeat (PIPESTAGE + 1) begin
      @(posedge clk);
    end
  endtask

  // Check output when valid
  task automatic check_output();
    logic [BW-1:0] exp_val;
    logic [BW-1:0] a_val, b_val;

    if (expected_queue.size() > 0) begin
      exp_val = expected_queue.pop_front();
      a_val   = in1_queue.pop_front();
      b_val   = in2_queue.pop_front();
      total_tests++;

      if (fp16_approx_eq(out, exp_val)) begin
        pass_count++;
      end else begin
        fail_count++;
        $display(
          "FAIL: %s * %s = %s, expected %s",
          fp16_str(a_val), fp16_str(b_val),
          fp16_str(out), fp16_str(exp_val)
        );
      end
    end
  endtask

  // FP16 encoding helper: build from sign, exponent, mantissa
  function automatic logic [BW-1:0] fp16_encode(
    input logic       sign,
    input int         biased_exp,
    input logic [9:0] mantissa
  );
    return {sign, biased_exp[4:0], mantissa};
  endfunction

  // Main test sequence
  initial begin
    logic [BW-1:0] a, b, expected;

    total_tests = 0;
    pass_count  = 0;
    fail_count  = 0;
    in1 = '0;
    in2 = '0;

    // Wait for reset settling
    repeat (2) @(posedge clk);

    // ========== Normal * Normal ==========
    $display("\n--- Normal * Normal ---");

    // 1.0 * 1.0 = 1.0
    a = fp16_encode(0, 15, 10'h000);  // 1.0
    b = fp16_encode(0, 15, 10'h000);  // 1.0
    send_test(a, b, fp16_mul_ref(a, b));

    // 2.0 * 3.0 = 6.0
    a = fp16_encode(0, 16, 10'h000);  // 2.0
    b = fp16_encode(0, 16, 10'h200);  // 3.0
    send_test(a, b, fp16_mul_ref(a, b));

    // 1.5 * 2.0 = 3.0
    a = fp16_encode(0, 15, 10'h200);  // 1.5
    b = fp16_encode(0, 16, 10'h000);  // 2.0
    send_test(a, b, fp16_mul_ref(a, b));

    // 0.5 * 0.5 = 0.25
    a = fp16_encode(0, 14, 10'h000);  // 0.5
    b = fp16_encode(0, 14, 10'h000);  // 0.5
    send_test(a, b, fp16_mul_ref(a, b));

    // -1.0 * 1.0 = -1.0
    a = fp16_encode(1, 15, 10'h000);  // -1.0
    b = fp16_encode(0, 15, 10'h000);  //  1.0
    send_test(a, b, fp16_mul_ref(a, b));

    // -2.0 * -3.0 = 6.0
    a = fp16_encode(1, 16, 10'h000);  // -2.0
    b = fp16_encode(1, 16, 10'h200);  // -3.0
    send_test(a, b, fp16_mul_ref(a, b));

    // 1.001 * 1.001 (small mantissa)
    a = fp16_encode(0, 15, 10'h001);
    b = fp16_encode(0, 15, 10'h001);
    send_test(a, b, fp16_mul_ref(a, b));

    // Large normal: 65504 (max FP16 normal)
    a = 16'h7BFF;  // 65504.0
    b = fp16_encode(0, 15, 10'h000);  // 1.0
    send_test(a, b, fp16_mul_ref(a, b));

    // ========== Zero tests ==========
    $display("--- Zero tests ---");

    // 0 * 1.0
    send_test(POS_ZERO, fp16_encode(0, 15, 10'h000),
              fp16_mul_ref(POS_ZERO, fp16_encode(0, 15, 10'h000)));

    // -0 * 1.0
    send_test(NEG_ZERO, fp16_encode(0, 15, 10'h000),
              fp16_mul_ref(NEG_ZERO, fp16_encode(0, 15, 10'h000)));

    // 0 * 0
    send_test(POS_ZERO, POS_ZERO,
              fp16_mul_ref(POS_ZERO, POS_ZERO));

    // ========== Infinity tests ==========
    $display("--- Infinity tests ---");

    // +Inf * 2.0 = +Inf
    send_test(POS_INF, fp16_encode(0, 16, 10'h000),
              fp16_mul_ref(POS_INF, fp16_encode(0, 16, 10'h000)));

    // -Inf * 2.0 = -Inf
    send_test(NEG_INF, fp16_encode(0, 16, 10'h000),
              fp16_mul_ref(NEG_INF, fp16_encode(0, 16, 10'h000)));

    // +Inf * -1.0 = -Inf
    send_test(POS_INF, fp16_encode(1, 15, 10'h000),
              fp16_mul_ref(POS_INF, fp16_encode(1, 15, 10'h000)));

    // +Inf * 0 = NaN
    send_test(POS_INF, POS_ZERO,
              fp16_mul_ref(POS_INF, POS_ZERO));

    // ========== NaN tests ==========
    $display("--- NaN tests ---");

    // NaN * 1.0 = NaN
    send_test(CANON_NAN, fp16_encode(0, 15, 10'h000),
              fp16_mul_ref(CANON_NAN, fp16_encode(0, 15, 10'h000)));

    // 1.0 * NaN = NaN
    send_test(fp16_encode(0, 15, 10'h000), CANON_NAN,
              fp16_mul_ref(fp16_encode(0, 15, 10'h000), CANON_NAN));

    // NaN * NaN = NaN
    send_test(CANON_NAN, CANON_NAN,
              fp16_mul_ref(CANON_NAN, CANON_NAN));

    // ========== Overflow test ==========
    $display("--- Overflow test ---");

    // 65504 * 2.0 = +Inf (overflow)
    a = 16'h7BFF;  // 65504.0
    b = fp16_encode(0, 16, 10'h000);  // 2.0
    send_test(a, b, fp16_mul_ref(a, b));

    // ========== Random tests ==========
    $display("--- Random tests ---");

    for (int r = 0; r < 500; r++) begin
      logic        rand_sign_a, rand_sign_b;
      logic [4:0]  rand_exp_a, rand_exp_b;
      logic [9:0]  rand_man_a, rand_man_b;

      rand_sign_a = $urandom_range(0, 1);
      rand_exp_a  = $urandom_range(1, 30);
      rand_man_a  = $urandom_range(0, 1023);
      rand_sign_b = $urandom_range(0, 1);
      rand_exp_b  = $urandom_range(1, 30);
      rand_man_b  = $urandom_range(0, 1023);

      a = {rand_sign_a, rand_exp_a, rand_man_a};
      b = {rand_sign_b, rand_exp_b, rand_man_b};
      send_test(a, b, fp16_mul_ref(a, b));
    end

    // Wait for pipeline to drain and checker to process all
    // remaining outputs (always_ff checker handles popping)
    while (expected_queue.size() > 0) begin
      @(posedge clk);
    end
    // One extra cycle to ensure last check completes
    @(posedge clk);

    // Final report
    $display("\n========== Test Summary ==========");
    $display("Total : %0d", total_tests);
    $display("Pass  : %0d", pass_count);
    $display("Fail  : %0d", fail_count);
    if (fail_count == 0)
      $display("ALL TESTS PASSED");
    else
      $display("SOME TESTS FAILED");
    $display("==================================\n");

    $finish;
  end

  // Output checker: after PIPESTAGE cycles, start checking
  int cycle_count;

  initial begin
    cycle_count = 0;
  end

  always_ff @(posedge clk) begin
    cycle_count <= cycle_count + 1;
    if (cycle_count >= PIPESTAGE + 4) begin
      check_output();
    end
  end

  // Waveform dump
  initial begin
    $dumpfile("fp16_multiplier_tb.vcd");
    $dumpvars(0, fp16_multiplier_tb);
  end

endmodule
