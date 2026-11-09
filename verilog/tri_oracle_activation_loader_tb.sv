`timescale 1ns / 1ps
// Updated to modern SystemVerilog
module tri_oracle_activation_loader_tb;
  localparam int WordWidth = 64;
  localparam int StripWidth = 2 * WordWidth;
  localparam int TimeoutCycles = 60000;
  logic clk = 1'b0, rst_n = 1'b0, cfg_valid = 1'b0, cfg_ready;
  logic [31:0] cfg_tag = '0, done_tag;
  logic [9:0] cfg_strips = '0;
  logic [63:0] cfg_raw_base = '0, cfg_gamma_base = '0;
  logic stats_valid, stats_ready, stats_last;
  logic [127:0] stats_data;
  logic replay_valid, replay_ready, replay_last;
  logic [127:0] replay_data, replay_gamma;
  logic done_valid, done_ready = 1'b0, done_error;
  logic req_valid, req_ready;
  logic [63:0] req_address;
  logic [ 4:0] req_length;
  logic rsp_valid, rsp_ready, rsp_last, rsp_error;
  logic [63:0] rsp_data;
  bit memory_active = 1'b0, use_stalls = 1'b1, force_request_stall = 1'b0;
  bit memory_gamma = 1'b0, memory_fault = 1'b0;
  int memory_index = 0, memory_beat = 0;
  int cycles = 0, request_count = 0, stats_count = 0, replay_count = 0;
  int expected_strips = 0, fault_request = -1, fault_mode = 0, passed = 0;
  int request_stalls = 0, stats_stalls = 0, replay_stalls = 0, done_stalls = 0;
  logic [63:0] expected_raw_base, expected_gamma_base;
  logic [31:0] expected_tag;
  bit held_request = 1'b0, held_stats = 1'b0, held_replay = 1'b0;
  logic [68:0] held_request_value;
  logic [StripWidth:0] held_stats_value;
  logic [2*StripWidth:0] held_replay_value;

  always #5 clk = !clk;
  tri_oracle_activation_loader dut (.*);

  function automatic logic [StripWidth-1:0] raw_word(input int index);
    raw_word = {
      64'hfedc_ba98_7654_3210 ^ WordWidth'(index), 64'h8000_0001_7fff_ffff + WordWidth'(index)
    };
  endfunction
  function automatic logic [StripWidth-1:0] gamma_word(input int index);
    gamma_word = {
      64'h0000_ffff_1234_8000 + WordWidth'(index), 64'h7fff_8001_0001_0000 ^ WordWidth'(index)
    };
  endfunction

  always_comb begin
    req_ready = !memory_active && !force_request_stall && (!use_stalls || cycles % 4 != 0);
    stats_ready = !use_stalls || cycles % 7 > 2;
    replay_ready = !use_stalls || cycles % 6 > 2;
    rsp_valid = rst_n && memory_active && (!use_stalls || cycles % 5 != 2);
    rsp_last = memory_beat == 1;
    if (memory_fault && fault_mode == 1) rsp_last = 1'b1;
    if (memory_fault && fault_mode == 2) rsp_last = memory_beat == 2;
    rsp_error = memory_fault &&
            ((fault_mode == 3 && memory_beat == 0) ||
             (fault_mode == 4 && memory_beat == 1));
    rsp_data = WordWidth'((memory_gamma ? gamma_word(memory_index) : raw_word(memory_index)) >>
                          (memory_beat == 0 ? 0 : WordWidth));
  end

  always @(posedge clk) begin : monitor
    logic [63:0] expected_address;
    int ordinal;
    cycles = cycles + 1;
    if (!rst_n) begin
      memory_active = 1'b0;
      memory_beat = 0;
      request_count = 0;
      stats_count = 0;
      replay_count = 0;
      held_request = 1'b0;
      held_stats = 1'b0;
      held_replay = 1'b0;
    end else begin
      if (held_request && {req_valid, req_address, req_length} !== {1'b1, held_request_value})
        $fatal(1, "Request changed while stalled");
      if (held_stats && {stats_valid, stats_last, stats_data} !== {1'b1, held_stats_value})
        $fatal(1, "Statistics changed while stalled");
      if (held_replay && {replay_valid, replay_last, replay_data, replay_gamma} !==
                {1'b1, held_replay_value})
        $fatal(1, "Replay changed while stalled");
      held_request = req_valid && !req_ready;
      held_request_value = {req_address, req_length};
      held_stats = stats_valid && !stats_ready;
      held_stats_value = {stats_last, stats_data};
      held_replay = replay_valid && !replay_ready;
      held_replay_value = {replay_last, replay_data, replay_gamma};
      if (held_request) request_stalls++;
      if (held_stats) stats_stalls++;
      if (held_replay) replay_stalls++;
      if (done_valid && !done_ready) done_stalls++;
      if (done_valid && memory_active) $fatal(1, "Completion preceded actual LAST");
      if (req_valid && req_ready) begin
        if (memory_active) $fatal(1, "Overlapping memory transaction");
        if (request_count < expected_strips) begin
          memory_index = request_count;
          memory_gamma = 1'b0;
        end else begin
          ordinal = request_count - expected_strips;
          memory_index = ordinal / 2;
          memory_gamma = ordinal % 2 != 0;
        end
        expected_address = (memory_gamma ? expected_gamma_base : expected_raw_base)
                    + WordWidth'(memory_index * 16);
        if (req_address !== expected_address || req_length !== 5'd2)
          $fatal(
              1,
              "Wrong read request %0d address=%h expected=%h length=%0d",
              request_count,
              req_address,
              expected_address,
              req_length
          );
        memory_fault  = request_count == fault_request;
        memory_beat   = 0;
        memory_active = 1'b1;
        request_count = request_count + 1;
      end else if (rsp_valid && rsp_ready) begin
        if (rsp_last) memory_active = 1'b0;
        else memory_beat = memory_beat + 1;
      end
      if (stats_valid && stats_ready) begin
        if (stats_data !== raw_word(
                stats_count
            ) || stats_last !== (stats_count + 1 == expected_strips))
          $fatal(1, "Wrong statistics strip %0d", stats_count);
        stats_count = stats_count + 1;
      end
      if (replay_valid && replay_ready) begin
        if (stats_count != expected_strips) $fatal(1, "Replay before full statistics");
        if (replay_data !== raw_word(
                replay_count
            ) || replay_gamma !== gamma_word(
                replay_count
            ) || replay_last !== (replay_count + 1 == expected_strips))
          $fatal(1, "Wrong raw/coefficient replay strip %0d", replay_count);
        replay_count = replay_count + 1;
      end
    end
  end

  task automatic start_case(input int tag, strips, fault, mode, input logic [63:0] raw_base,
                            gamma_base);
    @(negedge clk);
    if (!cfg_ready) $fatal(1, "Configuration not ready for a fresh token");
    request_count = 0;
    stats_count = 0;
    replay_count = 0;
    expected_strips = strips;
    fault_request = fault;
    fault_mode = mode;
    expected_tag = 32'(tag);
    expected_raw_base = raw_base;
    expected_gamma_base = gamma_base;
    cfg_tag = 32'(tag);
    cfg_strips = 10'(strips);
    cfg_raw_base = raw_base;
    cfg_gamma_base = gamma_base;
    cfg_valid = 1'b1;
    @(negedge clk);
    cfg_valid = 1'b0;
    // The old context must be independent of every live configuration input.
    cfg_tag = ~cfg_tag;
    cfg_strips = '0;
    cfg_raw_base = 64'hffff_ffff_ffff_ffff;
    cfg_gamma_base = 64'hffff_ffff_ffff_ffff;
  endtask

  task automatic finish_case(input int wanted_stats, wanted_replay, wanted_requests,
                             input bit wanted_error);
    int waited;
    waited = 0;
    while (!done_valid && waited < TimeoutCycles) begin
      @(negedge clk);
      waited++;
    end
    if (!done_valid) $fatal(1, "Loader timed out without terminal completion");
    repeat (4) begin
      if (!done_valid || done_error !== wanted_error || done_tag !== expected_tag || cfg_ready ||
                stats_count != wanted_stats || replay_count != wanted_replay ||
                request_count != wanted_requests || memory_active || req_valid ||
                stats_valid || replay_valid)
        $fatal(
            1,
            "Bad terminal tag=%h error=%b counts=%0d/%0d/%0d",
            done_tag,
            done_error,
            stats_count,
            replay_count,
            request_count
        );
      @(negedge clk);
    end
    done_ready = 1'b1;
    @(negedge clk);
    done_ready = 1'b0;
    if (!cfg_ready || done_valid) $fatal(1, "Completion acknowledgement did not release");
    passed++;
    $display("ACTIVATION_LOADER_CASE_PASS tag=%h error=%0d requests=%0d", expected_tag,
             wanted_error, request_count);
  endtask

  task automatic run_case(input int tag, strips, fault, mode, input logic [63:0] raw_base,
                          gamma_base, input int wanted_stats, wanted_replay, wanted_requests,
                          input bit wanted_error);
    start_case(tag, strips, fault, mode, raw_base, gamma_base);
    finish_case(wanted_stats, wanted_replay, wanted_requests, wanted_error);
  endtask

  task automatic reset_peer;
    @(negedge clk);
    rst_n = 1'b0;
    cfg_valid = 1'b0;
    repeat (2) @(negedge clk);
    if (req_valid || stats_valid || replay_valid || done_valid)
      $fatal(1, "Reset leaked an old context");
    rst_n = 1'b1;
    @(negedge clk);
  endtask

  initial begin
    repeat (3) @(negedge clk);
    rst_n = 1'b1;
    use_stalls = 1'b0;
    run_case(1, 1, -1, 0, 64'h1000, 64'h4000, 1, 1, 3, 0);
    use_stalls = 1'b1;
    run_case(2, 2, -1, 0, 64'h1000, 64'h4000, 2, 2, 6, 0);
    run_case(3, 512, -1, 0, 64'h1000, 64'h20000, 512, 512, 1536, 0);
    run_case(4, 1, -1, 0, 64'hffff_ffff_ffff_fff0, 64'h4000, 1, 1, 3, 0);
    run_case(5, 1, -1, 0, 64'h1000, 64'hffff_ffff_ffff_fff0, 1, 1, 3, 0);
    run_case(6, 2, -1, 0, 64'h1008, 64'h4008, 2, 2, 6, 0);
    run_case(7, 2, -1, 0, 64'hffff_ffff_ffff_ffe0, 64'h4000, 2, 2, 6, 0);
    run_case(10, 0, -1, 0, 64'h1000, 64'h4000, 0, 0, 0, 1);
    run_case(11, 513, -1, 0, 64'h1000, 64'h4000, 0, 0, 0, 1);
    run_case(12, 2, -1, 0, 64'h1001, 64'h4000, 0, 0, 0, 1);
    run_case(13, 2, -1, 0, 64'h1000, 64'h4004, 0, 0, 0, 1);
    run_case(14, 2, -1, 0, 64'hffff_ffff_ffff_fff0, 64'h4000, 0, 0, 0, 1);
    run_case(15, 2, -1, 0, 64'h1000, 64'hffff_ffff_ffff_fff0, 0, 0, 0, 1);
    run_case(20, 2, 0, 1, 64'h1000, 64'h4000, 0, 0, 1, 1);
    run_case(21, 2, 1, 2, 64'h1000, 64'h4000, 1, 0, 2, 1);
    run_case(22, 2, 2, 3, 64'h1000, 64'h4000, 2, 0, 3, 1);
    run_case(23, 2, 3, 4, 64'h1000, 64'h4000, 2, 0, 4, 1);
    run_case(24, 2, 5, 2, 64'h1000, 64'h4000, 2, 1, 6, 1);
    force_request_stall = 1'b1;
    start_case(30, 2, -1, 0, 64'h1000, 64'h4000);
    wait (req_valid);
    repeat (3) @(negedge clk);
    reset_peer();
    force_request_stall = 1'b0;
    run_case(31, 1, -1, 0, 64'h1000, 64'h4000, 1, 1, 3, 0);
    start_case(32, 2, -1, 0, 64'h1000, 64'h4000);
    wait (memory_active && memory_beat == 1);
    reset_peer();
    run_case(33, 1, -1, 0, 64'h1000, 64'h4000, 1, 1, 3, 0);
    if (passed != 20 || request_stalls == 0 || stats_stalls == 0 ||
            replay_stalls == 0 || done_stalls == 0)
      $fatal(1, "Missing context or actual backpressure coverage");
    $display("ACTIVATION_LOADER_PASS cases=%0d reset_recoveries=2 stalls=%0d/%0d/%0d/%0d", passed,
             request_stalls, stats_stalls, replay_stalls, done_stalls);
    $finish;
  end

  initial begin
    #(TimeoutCycles * 30);
    $fatal(1, "Loader global watchdog");
  end
endmodule
