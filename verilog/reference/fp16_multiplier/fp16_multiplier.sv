module fp16_multiplier #(
    parameter int BW = 16,
    parameter int SIGNIFICANT_BW = 10,
    parameter int EXP_BW = 5,
    parameter int MUL_BW = 2 * (SIGNIFICANT_BW + 1),

    // 1 prefill + $clog2(SIGNIFICANT_BW) reduction + 1 output
    parameter int ADDER_TREE_STAGE = $clog2(SIGNIFICANT_BW) + 1,
    parameter int PIPESTAGE = ADDER_TREE_STAGE + 1
) (
    input  logic                 clk,
    input  logic signed [BW-1:0] in1,
    input  logic signed [BW-1:0] in2,
    output logic        [BW-1:0] out
);
  localparam int ExpBias = (2 ** (EXP_BW - 1)) - 1;
  localparam int ExpAllOnes = (2 ** EXP_BW) - 1;
  localparam int ExpRegBw = EXP_BW + 2;
  localparam int TreeWidth = 2 ** (ADDER_TREE_STAGE - 1);

  localparam logic [BW-1:0] PosInf =
      {1'b0, EXP_BW'(ExpAllOnes), SIGNIFICANT_BW'(0)};
  localparam logic [BW-1:0] NegInf =
      {1'b1, EXP_BW'(ExpAllOnes), SIGNIFICANT_BW'(0)};
  localparam logic [BW-1:0] CanonicalNaN =
      {1'b0, EXP_BW'(ExpAllOnes), SIGNIFICANT_BW'(1)};
  localparam logic signed [ExpRegBw-1:0] ExpOvfThresh =
      ExpRegBw'(ExpAllOnes);

  // Pipeline registers
  logic [PIPESTAGE-1:0] sign_reg;
  logic signed [ExpRegBw-1:0] exp_reg [PIPESTAGE];
  logic [MUL_BW-1:0] tree [ADDER_TREE_STAGE][TreeWidth];

  // Input classification flags, pipelined
  logic [PIPESTAGE-1:0] flag_nan;
  logic [PIPESTAGE-1:0] flag_inf;
  logic [PIPESTAGE-1:0] flag_zero;
  logic [PIPESTAGE-1:0] flag_inf_x_zero;

  // Pre-computed normalization registers (between tree and out)
  logic                         product_ovf_reg;
  logic signed [ExpRegBw-1:0]   exp_shifted_reg;
  logic [SIGNIFICANT_BW-1:0]    man_shifted_reg;
  logic [SIGNIFICANT_BW-1:0]    man_unshifted_reg;

  always_ff @(posedge clk) begin

    // --- Input classification ---
    begin : Input_Classification
      logic in1_exp_max, in2_exp_max;
      logic in1_exp_zero, in2_exp_zero;
      logic in1_man_zero, in2_man_zero;
      logic in1_inf, in2_inf;
      logic in1_zero, in2_zero;

      in1_exp_max  = (in1[BW-2-:EXP_BW]
                      == ExpAllOnes[EXP_BW-1:0]);
      in2_exp_max  = (in2[BW-2-:EXP_BW]
                      == ExpAllOnes[EXP_BW-1:0]);
      in1_exp_zero = (in1[BW-2-:EXP_BW] == 0);
      in2_exp_zero = (in2[BW-2-:EXP_BW] == 0);
      in1_man_zero = (in1[SIGNIFICANT_BW-1:0] == 0);
      in2_man_zero = (in2[SIGNIFICANT_BW-1:0] == 0);

      in1_inf  = in1_exp_max && in1_man_zero;
      in2_inf  = in2_exp_max && in2_man_zero;
      in1_zero = in1_exp_zero && in1_man_zero;
      in2_zero = in2_exp_zero && in2_man_zero;

      flag_nan[0] <=
          (in1_exp_max && !in1_man_zero)
       || (in2_exp_max && !in2_man_zero);
      flag_inf[0] <= in1_inf || in2_inf;
      flag_zero[0] <= in1_zero || in2_zero;
      flag_inf_x_zero[0] <=
          (in1_inf && in2_zero)
       || (in2_inf && in1_zero);

      for (int i = 1; i < PIPESTAGE; i++) begin
        flag_nan[i]        <= flag_nan[i-1];
        flag_inf[i]        <= flag_inf[i-1];
        flag_zero[i]       <= flag_zero[i-1];
        flag_inf_x_zero[i] <= flag_inf_x_zero[i-1];
      end
    end

    // --- Sign pipeline ---
    begin : Sign_Pipeline
      sign_reg[0] <= in1[BW-1] ^ in2[BW-1];
      for (int i = 1; i < PIPESTAGE; i++)
        sign_reg[i] <= sign_reg[i-1];
    end

    // --- Exponent pipeline ---
    begin : Exp_Pipeline
      exp_reg[0] <=
          $signed({1'b0, in1[BW-2-:EXP_BW]})
        + $signed({1'b0, in2[BW-2-:EXP_BW]})
        - ExpBias;
      for (int i = 1; i < PIPESTAGE; i++)
        exp_reg[i] <= exp_reg[i-1];
    end

    // --- Mantissa multiplication via adder tree ---
    begin : Mantissa_Multiply
      logic [SIGNIFICANT_BW:0] m1, m2;
      logic in1_normal, in2_normal;

      in1_normal = !((in1[BW-2-:EXP_BW] == 0)
                  || (in1[BW-2-:EXP_BW]
                      == ExpAllOnes[EXP_BW-1:0]));
      in2_normal = !((in2[BW-2-:EXP_BW] == 0)
                  || (in2[BW-2-:EXP_BW]
                      == ExpAllOnes[EXP_BW-1:0]));

      m1 = {in1_normal, in1[SIGNIFICANT_BW-1:0]};
      m2 = {in2_normal, in2[SIGNIFICANT_BW-1:0]};

      for (int i = 0; i <= SIGNIFICANT_BW; i++)
        tree[0][i] <=
            m2[i] ? (MUL_BW'(m1) << i) : '0;

      for (int i = SIGNIFICANT_BW + 1; i < TreeWidth; i++)
        tree[0][i] <= '0;

      for (int j = 1; j < ADDER_TREE_STAGE; j++)
        for (int k = 0;
             k < TreeWidth / (2 ** j); k++)
          tree[j][k] <=
              tree[j-1][2*k] + tree[j-1][2*k+1];
    end

    // --- Normalization pre-compute (register tree output) ---
    begin : Norm_Precompute
      product_ovf_reg <=
          tree[ADDER_TREE_STAGE-1][0][MUL_BW-1];
      exp_shifted_reg <=
          exp_reg[ADDER_TREE_STAGE-1] + 1;
      man_shifted_reg <=
          tree[ADDER_TREE_STAGE-1][0][MUL_BW-2-:SIGNIFICANT_BW];
      man_unshifted_reg <=
          tree[ADDER_TREE_STAGE-1][0][MUL_BW-3-:SIGNIFICANT_BW];
    end

    // --- Output assembly (all reads from registers, no BA) ---
    begin : Output_Stage
      if (flag_nan[PIPESTAGE-1]
          || flag_inf_x_zero[PIPESTAGE-1]) begin
        out <= CanonicalNaN;

      end else if (flag_inf[PIPESTAGE-1]) begin
        out <= sign_reg[PIPESTAGE-1] ? NegInf : PosInf;

      end else if (flag_zero[PIPESTAGE-1]) begin
        out <= {sign_reg[PIPESTAGE-1], (BW-1)'(0)};

      end else if (product_ovf_reg) begin
        // Product >= 2.0: use shifted exp and mantissa
        if (exp_shifted_reg >= ExpOvfThresh)
          out <= sign_reg[PIPESTAGE-1]
                 ? NegInf : PosInf;
        else if (exp_shifted_reg <= 0)
          out <= {sign_reg[PIPESTAGE-1], (BW-1)'(0)};
        else
          out <= {sign_reg[PIPESTAGE-1],
                  exp_shifted_reg[EXP_BW-1:0],
                  man_shifted_reg};

      end else begin
        // Product in [1.0, 2.0): use original exp
        if (exp_reg[PIPESTAGE-1] >= ExpOvfThresh)
          out <= sign_reg[PIPESTAGE-1]
                 ? NegInf : PosInf;
        else if (exp_reg[PIPESTAGE-1] <= 0)
          out <= {sign_reg[PIPESTAGE-1], (BW-1)'(0)};
        else
          out <= {sign_reg[PIPESTAGE-1],
                  exp_reg[PIPESTAGE-1][EXP_BW-1:0],
                  man_unshifted_reg};
      end
    end

  end

endmodule
