module softmax_tb;

  // Real self-attention parameters:
  // Q/K/V = 8-bit signed, DIM = 8
  // score = QK^T / sqrt(DIM) → 13-bit signed
  parameter int N      = 8;
  parameter int IN_BW  = 13;
  parameter int LUT_AW = 6;
  parameter int EXP_BW = 16;
  parameter int OUT_BW = 16;

  parameter int Q_BW   = 8;
  parameter int DIM    = 8;
  parameter int NUM_TESTS = 200;

  logic                     clk, rst_n;
  logic                     valid_in, valid_out;
  logic signed [IN_BW-1:0] in  [N];
  logic        [OUT_BW-1:0] out [N];

  softmax #(
      .N(N), .IN_BW(IN_BW), .LUT_AW(LUT_AW),
      .EXP_BW(EXP_BW), .OUT_BW(OUT_BW)
  ) dut (
      .clk(clk), .rst_n(rst_n), .valid_in(valid_in),
      .in(in), .out(out), .valid_out(valid_out)
  );

  initial clk = 0;
  always #5 clk = ~clk;

  // Storage for checking
  logic signed [IN_BW-1:0] saved_in [NUM_TESTS][N];
  int test_id_in, test_id_out;
  int pass_count, fail_count;
  int total_max_err, total_sum_dev;

  // Generate QK^T / sqrt(DIM) scores
  // Q_row[DIM] * K[N][DIM]^T → scores[N]
  // Approximate sqrt(8) ≈ 2.83, use shift-based division
  task automatic gen_attn_scores(
      output logic signed [IN_BW-1:0] scores [N]);
    int q_row [DIM];
    int k_mat [N][DIM];
    int dot;
    real sqrt_dim;
    sqrt_dim = $sqrt(real'(DIM));
    // Random Q row
    for (int d = 0; d < DIM; d++)
      q_row[d] = $urandom_range(0, 253) - 127;
    // Random K matrix
    for (int j = 0; j < N; j++)
      for (int d = 0; d < DIM; d++)
        k_mat[j][d] = $urandom_range(0, 253) - 127;
    // Compute dot products
    for (int j = 0; j < N; j++) begin
      dot = 0;
      for (int d = 0; d < DIM; d++)
        dot += q_row[d] * k_mat[j][d];
      // Divide by sqrt(DIM), clamp to IN_BW
      scores[j] = IN_BW'($rtoi(real'(dot) / sqrt_dim));
    end
  endtask

  // Check one result against golden softmax
  task automatic check_result(input int tid);
    real exp_vals [N];
    real exp_sum;
    real expected [N];
    int  exp_int  [N];
    int  out_sum;
    int  err, max_err;
    int  sum_dev;
    real max_in;
    // 5% tolerance for LUT_AW=5
    int  tolerance = (1 << OUT_BW) / 20;

    // Find max for numerical stability
    max_in = real'(saved_in[tid][0]);
    for (int i = 1; i < N; i++)
      if (real'(saved_in[tid][i]) > max_in)
        max_in = real'(saved_in[tid][i]);

    // Compute golden softmax with max subtraction
    exp_sum = 0.0;
    for (int i = 0; i < N; i++) begin
      exp_vals[i] = $exp(real'(saved_in[tid][i]) - max_in);
      exp_sum += exp_vals[i];
    end
    for (int i = 0; i < N; i++) begin
      expected[i] = exp_vals[i] / exp_sum;
      exp_int[i]  = $rtoi(expected[i] * real'(1 << OUT_BW));
    end

    // Evaluate
    max_err = 0;
    out_sum = 0;
    for (int i = 0; i < N; i++) begin
      err = int'(out[i]) - exp_int[i];
      if (err < 0) err = -err;
      if (err > max_err) max_err = err;
      out_sum += int'(out[i]);
    end
    sum_dev = out_sum - (1 << OUT_BW);
    if (sum_dev < 0) sum_dev = -sum_dev;

    // Track stats
    if (max_err > total_max_err) total_max_err = max_err;
    if (sum_dev > total_sum_dev) total_sum_dev = sum_dev;

    if (max_err <= tolerance) begin
      pass_count++;
    end else begin
      fail_count++;
      $display("[FAIL] Test %0d: max_err=%0d (tol=%0d), "
               + "sum=%0d", tid, max_err, tolerance, out_sum);
      for (int i = 0; i < N; i++)
        $display("  in[%0d]=%0d  out=%5d  exp=%5d  (%.4f)",
                 i, saved_in[tid][i], out[i],
                 exp_int[i], expected[i]);
    end
  endtask

  // Pipeline: send inputs continuously, check outputs as
  // they arrive. Use valid_out to know when to check.
  initial begin
    $dumpfile("softmax_tb.vcd");
    $dumpvars(0, softmax_tb);

    rst_n       = 0;
    valid_in    = 0;
    test_id_in  = 0;
    test_id_out = 0;
    pass_count  = 0;
    fail_count  = 0;
    total_max_err = 0;
    total_sum_dev = 0;
    for (int i = 0; i < N; i++) in[i] = 0;

    repeat (5) @(posedge clk);
    rst_n = 1;
    repeat (2) @(posedge clk);

    // Feed all test vectors
    for (int t = 0; t < NUM_TESTS; t++) begin
      logic signed [IN_BW-1:0] scores [N];
      gen_attn_scores(scores);
      // Save and drive
      for (int i = 0; i < N; i++) begin
        saved_in[t][i] = scores[i];
        in[i] = scores[i];
      end
      valid_in = 1;
      @(posedge clk);
      valid_in = 0;
      for (int i = 0; i < N; i++) in[i] = '0;
      // Wait enough cycles between tests for pipeline
      repeat (3) @(posedge clk);
    end

    // Wait for all outputs to flush
    repeat (50) @(posedge clk);

    $display("");
    $display("============================================");
    $display("  Self-Attention Softmax TB Summary");
    $display("  Q/K=%0d-bit, DIM=%0d, N=%0d, IN_BW=%0d",
             Q_BW, DIM, N, IN_BW);
    $display("  EXP_BW=%0d, LUT_AW=%0d, OUT_BW=%0d",
             EXP_BW, LUT_AW, OUT_BW);
    $display("  Tests: %0d", NUM_TESTS);
    $display("============================================");
    $display("  PASS: %0d / %0d", pass_count, NUM_TESTS);
    $display("  FAIL: %0d / %0d", fail_count, NUM_TESTS);
    $display("  Max element error:  %0d / %0d (%.2f%%)",
             total_max_err, 1 << OUT_BW,
             real'(total_max_err) / real'(1<<OUT_BW) * 100.0);
    $display("  Max sum deviation:  %0d / %0d (%.2f%%)",
             total_sum_dev, 1 << OUT_BW,
             real'(total_sum_dev) / real'(1<<OUT_BW) * 100.0);
    $display("  Tolerance (5%%):    %0d",
             (1 << OUT_BW) / 20);
    $display("============================================");
    if (fail_count == 0)
      $display("  >> ALL TESTS PASSED");
    else
      $display("  >> SOME TESTS FAILED");
    $display("");
    $finish;
  end

  // Output checker: triggered on valid_out
  always @(posedge clk) begin
    if (valid_out && test_id_out < NUM_TESTS) begin
      check_result(test_id_out);
      test_id_out++;
    end
  end

endmodule
