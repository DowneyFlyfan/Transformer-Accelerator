// Updated to modern SystemVerilog
// Pair members are checked against independent Boolean and sequential references.
`timescale 1ns / 1ps
module tri_oracle_memory_drive_pairs_tb ();
  localparam int PairSize = 2;
  localparam int OriginalMember = 0;
  localparam int ReplacementMember = 1;
  localparam int CombInputCount = 4;
  localparam int CombPatternCount = 1 << CombInputCount;
  localparam int SeqInputCount = 3;
  localparam int SeqPatternCount = 1 << SeqInputCount;
  localparam int CombFamilyCount = 6;
  localparam int CellFamilyCount = CombFamilyCount + 1;
  localparam int NorFamily = 0;
  localparam int BufferFamily = 1;
  localparam int AoiFamily = 2;
  localparam int NandFamily = 3;
  localparam int InrFamily = 4;
  localparam int InverterFamily = 5;
  localparam int ScanFamily = 6;
  localparam int A1Index = 0;
  localparam int A2Index = 1;
  localparam int B1Index = 2;
  localparam int B2Index = 3;
  localparam int DataIndex = 0;
  localparam int SiIndex = 1;
  localparam int SeIndex = 2;
  localparam time Step = 1ns;
  localparam time MaximumSimTime = 10us;

  logic [CombInputCount-1:0] comb_inputs;
  logic [SeqInputCount-1:0] seq_inputs;
  logic clk;
  logic candidate_clk;
  logic candidate_se;
  logic cell_outputs[CellFamilyCount][PairSize];
  logic reference_q;
  int unsigned pair_checks = 0;

  always_comb begin
`ifdef TRI_MEMORY_DRIVE_WRONG_CLOCK
    candidate_clk = ~clk;
`else
    candidate_clk = clk;
`endif
`ifdef TRI_MEMORY_DRIVE_WRONG_SCAN
    candidate_se = ~seq_inputs[SeIndex];
`else
    candidate_se = seq_inputs[SeIndex];
`endif
  end

`ifdef TRI_MEMORY_DRIVE_BOTH_WRONG
  CKND2D1BWP12T40P140 original_nor (
      .A1(comb_inputs[A1Index]),
      .A2(comb_inputs[A2Index]),
      .ZN(cell_outputs[NorFamily][OriginalMember])
  );
`else
  NR2D1BWP12T40P140 original_nor (
      .A1(comb_inputs[A1Index]),
      .A2(comb_inputs[A2Index]),
      .ZN(cell_outputs[NorFamily][OriginalMember])
  );
`endif
`ifdef TRI_MEMORY_DRIVE_WRONG_COMB
  CKND2D2BWP12T40P140 replacement_nor (
      .A1(comb_inputs[A1Index]),
      .A2(comb_inputs[A2Index]),
      .ZN(cell_outputs[NorFamily][ReplacementMember])
  );
`elsif TRI_MEMORY_DRIVE_BOTH_WRONG
  CKND2D2BWP12T40P140 replacement_nor (
      .A1(comb_inputs[A1Index]),
      .A2(comb_inputs[A2Index]),
      .ZN(cell_outputs[NorFamily][ReplacementMember])
  );
`else
  NR2D2BWP12T40P140 replacement_nor (
      .A1(comb_inputs[A1Index]),
      .A2(comb_inputs[A2Index]),
      .ZN(cell_outputs[NorFamily][ReplacementMember])
  );
`endif
  BUFFD1BWP12T40P140 original_buffer (
      .I(comb_inputs[A1Index]),
      .Z(cell_outputs[BufferFamily][OriginalMember])
  );
  BUFFD2BWP12T40P140 replacement_buffer (
      .I(comb_inputs[A1Index]),
      .Z(cell_outputs[BufferFamily][ReplacementMember])
  );
  AOI22D1BWP12T40P140 original_aoi (
      .A1(comb_inputs[A1Index]),
      .A2(comb_inputs[A2Index]),
      .B1(comb_inputs[B1Index]),
      .B2(comb_inputs[B2Index]),
      .ZN(cell_outputs[AoiFamily][OriginalMember])
  );
  AOI22D2BWP12T40P140 replacement_aoi (
      .A1(comb_inputs[A1Index]),
      .A2(comb_inputs[A2Index]),
      .B1(comb_inputs[B1Index]),
      .B2(comb_inputs[B2Index]),
      .ZN(cell_outputs[AoiFamily][ReplacementMember])
  );
  CKND2D1BWP12T40P140 original_nand (
      .A1(comb_inputs[A1Index]),
      .A2(comb_inputs[A2Index]),
      .ZN(cell_outputs[NandFamily][OriginalMember])
  );
  CKND2D2BWP12T40P140 replacement_nand (
      .A1(comb_inputs[A1Index]),
      .A2(comb_inputs[A2Index]),
      .ZN(cell_outputs[NandFamily][ReplacementMember])
  );
  INR2D1BWP12T40P140 original_inr (
      .A1(comb_inputs[A1Index]),
      .B1(comb_inputs[B1Index]),
      .ZN(cell_outputs[InrFamily][OriginalMember])
  );
  INR2D2BWP12T40P140 replacement_inr (
      .A1(comb_inputs[A1Index]),
      .B1(comb_inputs[B1Index]),
      .ZN(cell_outputs[InrFamily][ReplacementMember])
  );
  INVD1BWP12T40P140 original_inverter (
      .I (comb_inputs[A1Index]),
      .ZN(cell_outputs[InverterFamily][OriginalMember])
  );
  INVD2BWP12T40P140 replacement_inverter (
      .I (comb_inputs[A1Index]),
      .ZN(cell_outputs[InverterFamily][ReplacementMember])
  );
  SDFQD0BWP12T40P140 original_scan (
      .SI(seq_inputs[SiIndex]),
      .D (seq_inputs[DataIndex]),
      .SE(seq_inputs[SeIndex]),
      .CP(clk),
      .Q (cell_outputs[ScanFamily][OriginalMember])
  );
  SDFQD1BWP12T40P140 replacement_scan (
      .SI(seq_inputs[SiIndex]),
      .D (seq_inputs[DataIndex]),
      .SE(candidate_se),
      .CP(candidate_clk),
      .Q (cell_outputs[ScanFamily][ReplacementMember])
  );

  function automatic logic boolean_reference(input int unsigned family,
                                             input logic [CombInputCount-1:0] stimulus);
    case (family)
      NorFamily: return !(stimulus[A1Index] || stimulus[A2Index]);
      BufferFamily: return stimulus[A1Index];
      AoiFamily:
      return !((stimulus[A1Index] && stimulus[A2Index]) || (stimulus[B1Index] && stimulus[B2Index]));
      NandFamily: return !(stimulus[A1Index] && stimulus[A2Index]);
      InrFamily: return stimulus[A1Index] && !stimulus[B1Index];
      InverterFamily: return !stimulus[A1Index];
      default: $fatal(1, "Unknown independent Boolean reference family");
    endcase
  endfunction

  function automatic logic scan_reference(input logic [SeqInputCount-1:0] stimulus);
    return stimulus[SeIndex] ? stimulus[SiIndex] : stimulus[DataIndex];
  endfunction

  task automatic check_pair(input int unsigned family, input logic expected, input string phase);
    if (cell_outputs[family][OriginalMember] !== expected ||
        cell_outputs[family][ReplacementMember] !== expected) begin
      $fatal(1, "DRIVE_PAIR_MISMATCH family=%0d phase=%s old=%b new=%b expected=%b", family, phase,
             cell_outputs[family][OriginalMember], cell_outputs[family][ReplacementMember],
             expected);
    end
    pair_checks++;
  endtask

  initial begin
    comb_inputs = '0;
    seq_inputs = '0;
    clk = 1'b0;
    reference_q = 1'b0;
    #Step;
    for (int comb_case = 0; comb_case < CombPatternCount; comb_case++) begin
      comb_inputs = comb_case[CombInputCount-1:0];
      #Step;
      for (int family = 0; family < CombFamilyCount; family++) begin
        check_pair(family, boolean_reference(family, comb_inputs), "exhaustive_boolean");
      end
    end
    // Exercise every transition between the eight scan/data input combinations.
    for (int previous_case = 0; previous_case < SeqPatternCount; previous_case++) begin
      for (int next_case = 0; next_case < SeqPatternCount; next_case++) begin
        seq_inputs = previous_case[SeqInputCount-1:0];
        #Step;
        reference_q = scan_reference(seq_inputs);
        clk = 1'b1;
        #Step;
        check_pair(ScanFamily, reference_q, "preload_rising_edge");
        clk = 1'b0;
        #Step;
        check_pair(ScanFamily, reference_q, "preload_falling_edge_hold");
        seq_inputs = next_case[SeqInputCount-1:0];
        #Step;
        check_pair(ScanFamily, reference_q, "data_changes_while_clock_low");
        reference_q = scan_reference(seq_inputs);
        clk = 1'b1;
        #Step;
        check_pair(ScanFamily, reference_q, "next_rising_edge");
        seq_inputs = ~seq_inputs;
        #Step;
        check_pair(ScanFamily, reference_q, "data_changes_while_clock_high");
        clk = 1'b0;
        #Step;
        check_pair(ScanFamily, reference_q, "next_falling_edge_hold");
      end
    end
    $display("MEMORY_DRIVE_PAIRS_PASS families=%0d pair_checks=%0d", CellFamilyCount, pair_checks);
    $finish;
  end

  initial begin
    #MaximumSimTime;
    $fatal(1, "DRIVE_PAIR_TIMEOUT");
  end
endmodule
