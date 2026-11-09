module mac_col #(
    parameter int IN_BW = 8,
    parameter int MULT_BW = 2 * IN_BW,
    parameter int DIM = 8,
    parameter int OUT_BW = MULT_BW + $clog2(DIM)

) (
    input logic clk,
    input logic rst_n,
    input logic signed [IN_BW-1:0] in_n[DIM],
    input logic [1:0] inst,

    // WARN: 1. q, k and v have different shapes based on model arch
    // - Currently, only q, k and v of same shape is supported
    // NOTE:
    // 00: Do Nothing
    // 01: write k
    // 10: write v
    // 11: Compute (Whether it's q*k or qk*v)

    output logic [OUT_BW-1:0] out_s,
    output logic valid_out
);

  localparam MacDelay = 4 + 3 + 1;  // WARN: Multiplication + Adder_Tree + k/v Save + Decode Delay
  logic [IN_BW-1:0] k_or_v[DIM];
  logic [MacDelay-1:0] valid_chain;

  mac #(
      .IN_BW(IN_BW),
      .DIM(DIM),
      .MULT_BW(MULT_BW),
      .OUT_BW(OUT_BW)
  ) mac_inst (
      .clk(clk),
      .in1(in_n),
      .in2(k_or_v),
      .out(out_s)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (~rst_n) begin
      for (int i = 0; i < DIM; i++) begin
        k_or_v[DIM] <= 0;
      end
      valid_chain <= 0;

    end else begin
      for (int i = 0; i < MacDelay; i++) begin
        valid_chain[i+1] <= valid_chain[i];
      end
      valid_out <= valid_chain[MacDelay-1];

      unique case (inst)
        2'b00: begin

        end
        2'b01: begin
          k_or_v <= in_n;
          valid_chain[0] <= 1'b1;
        end
        2'b10: begin
          k_or_v <= in_n;
          valid_chain[0] <= 1'b1;
        end
        2'b11: begin

        end
        default: begin

        end
      endcase
    end
  end

endmodule
