module int_multiplier #(
    parameter int BW = 8
    // NOTE: Delay = Stage = 4
) (
    input  logic                   clk,
    input  logic signed [  BW-1:0] in1,
    input  logic signed [  BW-1:0] in2,
    output logic        [2*BW-1:0] out
);

  localparam int Stage = $clog2(BW) + 1;
  logic [2*BW-1:0] adder_tree[Stage][BW];

  always_ff @(posedge clk) begin
    for (int i = 0; i < BW; i++) begin : adder_tree_prefill
      adder_tree[0][i] <= in2[i]
          ? ((2*BW)'($signed(in1)) << i) : '0;
    end
    for (int j = 1; j < Stage; j++) begin : adder_tree_stages
      for (int k = 2 ** (Stage - 1 - j) - 1; k >= 0; k--) begin : adder_tree_stages
        adder_tree[j][k] <= adder_tree[j-1][2*k] + adder_tree[j-1][2*k+1];
      end
    end
  end

  always_comb begin
    out = adder_tree[Stage-1][0];
  end

endmodule
