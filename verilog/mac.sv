module mac #(
    parameter int IN_BW = 8,
    parameter int DIM = 8,
    parameter int MULT_BW = 2 * IN_BW,
    parameter int OUT_BW = MULT_BW + $clog2(IN_BW)
    // NOTE: Delay = adder_tree + int_multiplier = 7
) (
    input logic clk,
    input logic signed [IN_BW-1:0] in1[DIM],
    input logic signed [IN_BW-1:0] in2[DIM],
    output logic signed [OUT_BW-1:0] out
);

  logic [MULT_BW-1:0] mult_result[DIM];

  for (genvar i = 0; i < DIM; i++) begin : g_multiplier
    int_multiplier #(
        .BW(DIM)
    ) int_multiplier_inst (
        .clk(clk),
        .in1(in1[i]),
        .in2(in2[i]),
        .out(mult_result[i])
    );
  end

  adder_tree #(
      .BW (MULT_BW),
      .NUM(DIM)
  ) adder_tree_inst (
      .clk(clk),
      .in (mult_result),
      .out(out)
  );
endmodule
