`timescale 1ns/1ps
// A shared address for the single-port weight banks. Read on the first memory
// edge of each core cycle and write on the second. Clock and core clock must
// come from tri_oracle_weight_phase_clock and share a synchronous reset release.
// The arbiter offers at most one write lane. The originating buffer holds that
// lane's data and mask through the write edge and retires it at the next core edge.
module tri_oracle_weight_phase_port #(
  parameter int BANKS = 16
) (
  input logic memory_clk, core_clk, rst_n,
  input logic read_valid,
  input logic [4:0] read_address,
  input logic [BANKS-1:0] read_banks,
  input logic [1:0] write_select,
  input logic [4:0] write_address,
  input logic [BANKS-1:0] write_banks,
  output logic [1:0] active_write_lane, write_retired,
  output logic [4:0] memory_address,
  output logic [BANKS-1:0] memory_ce_n,
  output logic memory_we_n
);
  logic valid_write;
  assign valid_write = (^write_select) && (|write_banks);

  // The phase bit reflects the previous falling edge until this edge samples
  // all address and enable inputs. Leave a half period of setup at the macros.
  always_ff @(negedge memory_clk or negedge rst_n) begin
    if (!rst_n) begin
      active_write_lane <= '0;
      memory_address <= '0;
      memory_ce_n <= '1;
      memory_we_n <= 1;
    end else if (!core_clk) begin
      active_write_lane <= '0;
      memory_address <= read_address;
      memory_ce_n <= ~(read_banks & {BANKS{read_valid}});
      memory_we_n <= 1;
    end else begin
      active_write_lane <= valid_write ? write_select : 2'b00;
      memory_address <= write_address;
      memory_ce_n <= valid_write ? ~write_banks : {BANKS{1'b1}};
      memory_we_n <= !valid_write;
    end
  end

  // Capture retirement from the same rising edge that commits the write.
  // The intervening core edge sees it before the following memory read clears it.
  always_ff @(posedge memory_clk or negedge rst_n) begin
    if (!rst_n) write_retired <= '0;
    else write_retired <= active_write_lane;
  end
endmodule
