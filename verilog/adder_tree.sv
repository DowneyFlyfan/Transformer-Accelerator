module adder_tree #(
    parameter int BW = 8,
    parameter int NUM = 8,
    parameter int OUT_BW = BW + $clog2(NUM)
    // NOTE: Delay = Stage = 3
) (
    input logic clk,
    input logic signed [BW-1:0] in[NUM],
    output logic signed [OUT_BW-1:0] out
);
  localparam int Stage = $clog2(NUM);
  logic signed [OUT_BW-1:0] tree[Stage][NUM];

  always_comb begin
    out = tree[Stage-1][0];
  end

  always_ff @(posedge clk) begin
    for (int i = 0; i < NUM / 2; i++) begin : tree_prefill
      tree[0][i] <= OUT_BW'($signed(in[2*i]))
                  + OUT_BW'($signed(in[2*i+1]));
    end
    for (int j = 0; j < Stage - 1; j++) begin : tree_stages
      for (int k = 2 ** (Stage - 2 - j) - 1; k >= 0; k--) begin
        tree[j+1][k] <= tree[j][2*k] + tree[j][2*k+1];
      end
    end
  end

endmodule
