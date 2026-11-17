`timescale 1ns/1ps
module tri_oracle_phase_chip_clock_tb;
  logic memory_clk = 1, rst_n = 1;
  logic core_clk, core_rst_n;
  always #431ps memory_clk = ~memory_clk;
  tri_oracle_phase_chip_clock clock_source (.*);

  initial begin
    realtime edge_time;
    int resets = 0, measured_periods = 0;
    #1ps;
    rst_n = 0;
    for (int trial = 0; trial < 16; trial++) begin
      @(posedge memory_clk);
      #((11+47*trial)*1ps);
      if ({core_clk, core_rst_n} !== 2'b00)
        $fatal(1, "PHASE_CLOCK_NOT_RESET trial=%0d", trial);
      rst_n = 1;
      repeat (2) begin
        @(posedge memory_clk);
        #1ps;
        if ({core_clk, core_rst_n} !== 2'b00)
          $fatal(1, "PHASE_CLOCK_EARLY_DIVIDER trial=%0d", trial);
      end
      @(negedge memory_clk);
      edge_time = $realtime;
      #1ps;
      if ({core_clk, core_rst_n} !== 2'b10)
        $fatal(1, "PHASE_CLOCK_FIRST_EDGE trial=%0d", trial);
      @(posedge core_clk);
      if ($rtoi(($realtime-edge_time)*1000.0+0.5) != 1724 || memory_clk !== 0)
        $fatal(1, "PHASE_CLOCK_BAD_START_PERIOD trial=%0d", trial);
      #1ps;
      if (core_rst_n !== 1)
        $fatal(1, "PHASE_CLOCK_LATE_RELEASE trial=%0d", trial);
      repeat (4) begin
        @(posedge core_clk);
        edge_time = $realtime;
        @(negedge core_clk);
        if ($rtoi(($realtime-edge_time)*1000.0+0.5) != 862 || memory_clk !== 0)
          $fatal(1, "PHASE_CLOCK_BAD_DUTY trial=%0d", trial);
        edge_time = $realtime;
        @(posedge core_clk);
        if ($rtoi(($realtime-edge_time)*1000.0+0.5) != 862 || memory_clk !== 0)
          $fatal(1, "PHASE_CLOCK_BAD_DUTY trial=%0d", trial);
        measured_periods++;
      end
      #((17+97*trial)*1ps);
      rst_n = 0;
      #1ps;
      if ({core_clk, core_rst_n} !== 2'b00)
        $fatal(1, "PHASE_CLOCK_ASYNC_RESET trial=%0d", trial);
      resets++;
    end
    $display("PHASE_CLOCK_PASS resets=%0d duty_checks=%0d", resets, measured_periods);
    $finish;
  end
  initial begin
    #1us;
    $fatal(1, "PHASE_CLOCK_TIMEOUT");
  end
endmodule
