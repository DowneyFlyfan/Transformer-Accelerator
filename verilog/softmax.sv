// Softmax via base-2 conversion + small LUT
// Pipeline: max_tree → sub → ×log2e → LUT+shift → sum → recip_LUT → norm
module softmax #(
    parameter int N      = 8,   // Number of input elements
    parameter int IN_BW  = 8,   // Signed integer input bit width
    // NOTE: LUT_AW is input resolution (step size)
    // EXP_BW is output resolution (Quantization Accuracy)
    parameter int LUT_AW = 5,   // LUT address width (2^5 = 32 entries),
    parameter int EXP_BW = 16,  // Internal exp value bit width
    parameter int OUT_BW = 16   // Output Q0.OUT_BW unsigned
) (
    input  logic                     clk,
    input  logic                     rst_n,
    input  logic                     valid_in,
    input  logic signed [ IN_BW-1:0] in       [N],
    output logic        [OUT_BW-1:0] out      [N],
    output logic                     valid_out
);

  // ================ Constants ================
  localparam int MaxStage = $clog2(N);
  localparam int MultDelay1 = $clog2(IN_BW) + 1;
  localparam int MultDelay2 = $clog2(EXP_BW) + 1;
  localparam int LutSize = 1 << LUT_AW;
  localparam int SumBW = EXP_BW + MaxStage;
  localparam int MsbBW = $clog2(SumBW);
  localparam int TotalDelay = 2 * MaxStage + MultDelay1 + MultDelay2 + 5;

  // log2(e) ≈ 1.4427 in signed Q2.(IN_BW-2)
  //   1 sign bit + 1 integer bit + (IN_BW-2) fractional bits
  //   e.g. IN_BW=8: LOG2E = round(1.4427 * 64) = 92
  localparam int ScaleBW = IN_BW - 2;
  localparam logic signed [IN_BW-1:0] LOG2E = IN_BW'($rtoi(1.4427 * real'(1 << ScaleBW)));

  // ================ LUTs (synthesized as ROM) ================
  // Constant functions evaluated at elaboration time,
  // then stored as localparam arrays → pure ROM in synthesis

  typedef logic [EXP_BW-1:0] lut_arr_t[LutSize];

  // exp_lut[i] = 2^(i/LutSize) in Q1.(EXP_BW-2)
  //   range [1.0, 2.0), 1.0 ↔ 2^(EXP_BW-2)
  function automatic lut_arr_t init_exp_lut();
    lut_arr_t lut;
    for (int i = 0; i < LutSize; i++)
    lut[i] = EXP_BW'($rtoi($pow(2.0, real'(i) / real'(LutSize)) * real'(1 << (EXP_BW - 2))));
    return lut;
  endfunction

  // recip_lut[i] = 1/x for x ∈ [0.5,1.0) in Q2.(EXP_BW-3)
  //   range (1.0, 2.0], 1.0 ↔ 2^(EXP_BW-3)
  function automatic lut_arr_t init_recip_lut();
    lut_arr_t lut;
    for (int i = 0; i < LutSize; i++)
    lut[i] =
        EXP_BW'($rtoi((1.0 / (0.5 + real'(i) / real'(2 * LutSize))) * real'(1 << (EXP_BW - 3))));
    return lut;
  endfunction

  localparam lut_arr_t ExpLut = init_exp_lut();
  localparam lut_arr_t RecipLut = init_recip_lut();

  // ========================================================
  // P1: Max Comparator Tree  (MaxStage cycles)
  // ========================================================
  logic signed [IN_BW-1:0] cmp [MaxStage+1][N];
  logic signed [IN_BW-1:0] in_d[  MaxStage][N];

  always_comb begin
    for (int i = 0; i < N; i++) cmp[0][i] = in[i];
  end

  always_ff @(posedge clk) begin
    // Comparator tree: keep the larger of each pair
    for (int s = 0; s < MaxStage; s++)
    for (int i = 0; i < (N >> (s + 1)); i++)
    cmp[s+1][i] <= (cmp[s][2*i] > cmp[s][2*i+1]) ? cmp[s][2*i] : cmp[s][2*i+1];
    // Delay raw inputs to align with max output
    for (int i = 0; i < N; i++) in_d[0][i] <= in[i];
    for (int s = 1; s < MaxStage; s++) for (int i = 0; i < N; i++) in_d[s][i] <= in_d[s-1][i];
  end

  // ========================================================
  // P2: Subtract Max  (1 cycle)
  //   diff[i] = x[i] - max  ∈ (-∞, 0]
  // ========================================================
  logic signed [IN_BW-1:0] diff[N];

  always_ff @(posedge clk)
    for (int i = 0; i < N; i++)
      diff[i] <= in_d[MaxStage-1][i] - cmp[MaxStage][0];

  // ========================================================
  // P3: Multiply by log2(e) via int_multiplier
  //   y = (x-max) * log2(e)        (MultDelay1 cycles)
  // ========================================================
  logic [2*IN_BW-1:0] y_raw[N];

  for (genvar i = 0; i < N; i++) begin : g_log2e
    int_multiplier #(
        .BW(IN_BW)
    ) u_log2e (
        .clk(clk),
        .in1(diff[i]),
        .in2(LOG2E),
        .out(y_raw[i])
    );
  end

  // ========================================================
  // P4: Split into integer + fraction  (1 cycle)
  //   y_raw is 2*IN_BW bits, with ScaleBW fractional bits
  //   (from LOG2E's Q2.ScaleBW format)
  //   y_int  = floor(y)   (negative or zero)
  //   y_frac = top LUT_AW bits of fractional part → LUT addr
  // ========================================================
  logic signed [ IN_BW-1:0] y_int [N];
  logic        [LUT_AW-1:0] y_frac[N];

  always_ff @(posedge clk)
    for (int i = 0; i < N; i++) begin
      y_int[i]  <= IN_BW'($signed(y_raw[i]) >>> ScaleBW);
      y_frac[i] <= y_raw[i][(ScaleBW-1)-:LUT_AW];
    end

  // ========================================================
  // P5: exp(x-max) = 2^y_int * 2^y_frac  (1 cycle)
  //   LUT gives 2^frac, barrel shift gives 2^int
  //   Since y_int ≤ 0, shift RIGHT by |y_int|
  // ========================================================
  logic [EXP_BW-1:0] ev[N];

  always_ff @(posedge clk)
    for (int i = 0; i < N; i++)
      // NOTE: 2^-15 is almost 0
      ev[i] <= (y_int[i] < -(EXP_BW - 1)) ? '0 : ExpLut[y_frac[i]] >> ($unsigned(
          -y_int[i]
      ));

  // ========================================================
  // P6: Sum all exp values via adder_tree  (MaxStage cycles)
  //   Also delay ev[] in parallel to stay aligned
  // ========================================================
  logic signed [EXP_BW-1:0] ev_signed[N];
  logic signed [ SumBW-1:0] esum;

  always_comb for (int i = 0; i < N; i++) ev_signed[i] = $signed(ev[i]);

  adder_tree #(
      .BW (EXP_BW),
      .NUM(N)
  ) u_sum (
      .clk(clk),
      .in (ev_signed),
      .out(esum)
  );

  // Delay ev[] by MaxStage cycles to match sum latency
  // NOTE: Maybe Don't have to be delayed if it's co-designed
  // TODO: Have to think about it
  logic [EXP_BW-1:0] ev_pipe[MaxStage][N];

  always_ff @(posedge clk) begin
    for (int i = 0; i < N; i++) ev_pipe[0][i] <= ev[i];
    for (int s = 1; s < MaxStage; s++) for (int i = 0; i < N; i++) ev_pipe[s][i] <= ev_pipe[s-1][i];
  end

  // ========================================================
  // P7: Reciprocal via LUT  (1 cycle)
  //   1. Leading-one detector → normalize sum to [0.5, 1)
  //   2. Top bits index recip_lut
  // ========================================================
  logic [ MsbBW-1:0] msb_pos;
  logic [ SumBW-1:0] snorm;
  logic [LUT_AW-1:0] ridx;

  // Priority encoder: find MSB position
  always_comb begin
    msb_pos = '0;
    for (int i = 0; i < SumBW; i++) if (esum[i]) msb_pos = MsbBW'(i);
    // Normalize so leading-1 sits at MSB
    snorm = esum << (SumBW - 1 - msb_pos);
    ridx  = snorm[SumBW-2-:LUT_AW];
  end

  logic [EXP_BW-1:0] rval;
  logic [ MsbBW-1:0] rshift;
  logic [EXP_BW-1:0] ev_aligned[N];

  always_ff @(posedge clk) begin
    rval   <= RecipLut[ridx];
    rshift <= msb_pos;
    for (int i = 0; i < N; i++) ev_aligned[i] <= ev_pipe[MaxStage-1][i];
  end

  // ========================================================
  // P8: Normalize  exp[i] × (1/sum)  via int_multiplier
  //   (MultDelay2 cycles)
  // ========================================================
  // Treat positive values as signed with MSB = 0
  logic signed [EXP_BW-1:0] ev_s2[N];
  // TODO: Have to think about it
  logic signed [EXP_BW-1:0] rv_s;

  always_comb begin
    for (int i = 0; i < N; i++) ev_s2[i] = $signed({1'b0, ev_aligned[i][EXP_BW-2:0]});
    rv_s = $signed({1'b0, rval[EXP_BW-2:0]});
  end

  logic [2*EXP_BW-1:0] prod[N];

  for (genvar i = 0; i < N; i++) begin : g_norm
    int_multiplier #(
        .BW(EXP_BW)
    ) u_norm (
        .clk(clk),
        .in1(ev_s2[i]),
        .in2(rv_s),
        .out(prod[i])
    );
  end

  // Pipeline rshift through multiplier latency
  logic [MsbBW-1:0] rs_pipe[MultDelay2];

  always_ff @(posedge clk) begin
    rs_pipe[0] <= rshift;
    for (int s = 1; s < MultDelay2; s++) rs_pipe[s] <= rs_pipe[s-1];
  end

  // ========================================================
  // P9: Final shift → Q0.OUT_BW output  (1 cycle)
  //
  //   ev scale:    2^(EXP_BW-2) = 1.0
  //   recip scale: 2^(EXP_BW-3) = 1.0  (before msb_pos adj)
  //   product = softmax_i * 2^(msb_pos + EXP_BW - 2)
  //   shift   = msb_pos + EXP_BW - 2 - OUT_BW
  // ========================================================
  localparam int ShiftBW = (2 * EXP_BW > OUT_BW) ? 2 * EXP_BW : OUT_BW + 1;

  always_ff @(posedge clk)
    for (int i = 0; i < N; i++) begin
      logic [ShiftBW-1:0] shifted;
      logic signed [31:0] sh_amt;
      sh_amt = int'(rs_pipe[MultDelay2-1]) + EXP_BW - 2 - OUT_BW;
      if (sh_amt >= 0) shifted = ShiftBW'(prod[i] >> sh_amt);
      else shifted = ShiftBW'(prod[i]) << (-sh_amt);
      // Saturate: check overflow above OUT_BW
      if (|shifted[ShiftBW-1:OUT_BW]) out[i] <= {OUT_BW{1'b1}};
      else out[i] <= shifted[OUT_BW-1:0];
    end

  // ========================================================
  // Valid shift register
  // ========================================================
  logic [TotalDelay-1:0] vsr;

  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) vsr <= '0;
    else vsr <= {vsr[TotalDelay-2:0], valid_in};

  always_comb valid_out = vsr[TotalDelay-1];

endmodule
