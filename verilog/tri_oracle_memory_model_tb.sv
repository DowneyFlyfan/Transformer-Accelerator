`timescale 1ns / 1ps
// Updated to modern SystemVerilog
// Pinned checkpoint slices; raw residuals and learned coefficients arrive only
// through the memory interface. No software statistics or replay input exists.
module tri_oracle_memory_model_tb;
  localparam int Features = 2048;
  localparam int StripLanes = 8;
  localparam int Strips = Features / StripLanes;
  localparam int GroupChannels = 32;
  localparam int Groups = 2;
  localparam int SelectedChannels = GroupChannels * Groups;
  localparam int DenseFeatures = 5632;
  localparam int Outputs = 35;
  localparam int WeightWords = SelectedChannels * Features;
  localparam int DownWords = Outputs * DenseFeatures;
  localparam int ByteBits = 8;
  localparam int RawBits = 16;
  localparam int SumBits = 32;
  localparam int MemoryBytes = 8;
  localparam int MemoryBits = ByteBits * MemoryBytes;
  localparam int RawLanesPerBeat = MemoryBits / RawBits;
  localparam int StripBytes = StripLanes * RawBits / ByteBits;
  localparam int SourceRequests = 3 * Strips;
  localparam int RawBytes = 2 * Features * RawBits / ByteBits;
  localparam int GammaBytes = Features * RawBits / ByteBits;
  localparam int SignGroupStride = Features / 2 * MemoryBytes;
  localparam int MaxBurst = 16;
  localparam int GroupTimeout = 300000;
  localparam int WatchdogNs = 6000000;
  localparam int ClockHalfPeriod = 5;
  localparam int RequestStallPeriod = 4;
  localparam int ResponseStallPeriod = 3;
  localparam int OutputStallPeriod = 5;
  localparam int MinimumOutputWait = 2;
  localparam int OutlierLimit = 768;
  localparam int HeldBits = 6 + 3 + SumBits + GroupChannels * (RawBits + SumBits);
  localparam int RequestBits = 64 + 5;
  localparam logic [SumBits-1:0] Tag = 32'h4d4f444c;
  localparam logic [63:0] ActBase = 64'h1000;
  localparam logic [63:0] GateBase = 64'h100000;
  localparam logic [63:0] UpBase = 64'h40000000;
  localparam logic [63:0] DownBase = 64'h80000000;
  localparam logic [63:0] GateSignBase = 64'h100000000;
  localparam logic [63:0] UpSignBase = 64'h200000000;
  localparam logic [63:0] RawBase = 64'h300010000;
  localparam logic [63:0] GammaBase = 64'h400020000;

  string fixture_directory = ".cache/model_reference/feedforward_fixture";
  int fixture_override;
  logic clk = 0;
  always #ClockHalfPeriod clk = ~clk;
  logic rst_n = 0, cfg_valid = 0, group_valid = 0, group_last = 0, out_ready = 0;
  logic cfg_ready, group_ready, out_valid, out_last, out_fallback, out_error;
  logic [10:0] group_id = 0;
  logic [SumBits-1:0] configuration[5];
  logic [SumBits-1:0] epsilon[1], activation_shift[1];
  logic [5:0] cfg_gate_shift, cfg_up_shift, cfg_down_shift;
  logic [RawBits-1:0] cfg_output_start;
  logic [8:0] cfg_output_count;
  logic [SumBits-1:0] out_tag;
  logic [5:0] out_count;
  logic [GroupChannels*RawBits-1:0] out_channels;
  logic [GroupChannels*SumBits-1:0] out_data;
  logic req_valid, req_ready, rsp_ready;
  logic [63:0] req_address;
  logic [ 4:0] req_length;
  logic rsp_valid = 0, rsp_last = 0;
  logic [MemoryBits-1:0] rsp_data = 0;
  int cycle = 0, requests = 0, beats = 0, length = 0, received = 0;
  int raw_bytes = 0, gamma_bytes = 0, source_requests = 0;
  int gate_bytes = 0, up_bytes = 0, activation_bytes = 0, down_bytes = 0;
  int skipped = 0, sign_bytes = 0;
  logic model_active = 0;
  logic request_waited = 0;
  int output_wait = 0;
  logic [63:0] address = 0;
  logic [ByteBits-1:0] gate_weights[WeightWords], up_weights[WeightWords];
  logic [ByteBits-1:0] down_weights[DownWords], skip_channels[SelectedChannels];
  logic [RawBits-1:0] raw_residual[Features], learned_gamma[Features];
  logic [RawBits-1:0] normalized[Features], groups[Groups];
  logic [SumBits-1:0] expected[Outputs];
  logic [HeldBits-1:0] held;
  logic stalled = 0;
  logic [RequestBits-1:0] held_request;
  logic request_stalled = 0;
  int request_stall_cycles = 0, output_stall_cycles = 0;

  always_comb begin
    cfg_gate_shift = configuration[0][5:0];
    cfg_up_shift = configuration[1][5:0];
    cfg_down_shift = configuration[2][5:0];
    cfg_output_start = configuration[3][RawBits-1:0];
    cfg_output_count = configuration[4][8:0];
    req_ready = !model_active && !rsp_valid && request_waited && cycle % RequestStallPeriod != 0;
  end

  tri_oracle_memory_feedforward_core dut (
      .clk(clk),
      .rst_n(rst_n),
      .cfg_valid(cfg_valid),
      .cfg_ready(cfg_ready),
      .cfg_tag(Tag),
      .cfg_epsilon_q16(epsilon[0]),
      .cfg_raw_base(RawBase),
      .cfg_gamma_base(GammaBase),
      .cfg_activation_base(ActBase),
      .cfg_weight_base(GateBase),
      .cfg_up_weight_base(UpBase),
      .cfg_down_weight_base(DownBase),
      .cfg_gate_sign_base(GateSignBase),
      .cfg_up_sign_base(UpSignBase),
      .cfg_gate_shift(cfg_gate_shift),
      .cfg_up_shift(cfg_up_shift),
      .cfg_down_shift(cfg_down_shift),
      .cfg_activation_shift(activation_shift[0][5:0]),
      .cfg_features(10'(Strips)),
      .cfg_dense_features(17'(DenseFeatures)),
      .cfg_output_start(cfg_output_start),
      .cfg_output_count(cfg_output_count),
      .group_valid(group_valid),
      .group_ready(group_ready),
      .group_id(group_id),
      .group_last(group_last),
      .out_valid(out_valid),
      .out_ready(out_ready),
      .out_last(out_last),
      .out_fallback(out_fallback),
      .out_error(out_error),
      .out_tag(out_tag),
      .out_count(out_count),
      .out_channels(out_channels),
      .out_data(out_data),
      .req_valid(req_valid),
      .req_ready(req_ready),
      .req_address(req_address),
      .req_length(req_length),
      .rsp_valid(rsp_valid),
      .rsp_last(rsp_last),
      .rsp_error(1'b0),
      .rsp_ready(rsp_ready),
      .rsp_data(rsp_data)
  );

  function automatic int selected_row(input int original);
    if (original / GroupChannels == int'(groups[0])) selected_row = original % GroupChannels;
    else if (original / GroupChannels == int'(groups[1]))
      selected_row = GroupChannels + original % GroupChannels;
    else selected_row = -1;
  endfunction

  function automatic bit raw_region(input logic [63:0] cursor);
    return cursor >= RawBase && cursor < RawBase + GammaBytes;
  endfunction

  function automatic bit gamma_region(input logic [63:0] cursor);
    return cursor >= GammaBase && cursor < GammaBase + GammaBytes;
  endfunction

  always_ff @(posedge clk) begin : memory_model
    int lane, original, row, column, index, phase, group_index, pair_index, feature;
    int source_strip;
    logic [63:0] cursor, offset, expected_address;
    if (!rst_n) begin
      cycle <= 0;
      model_active <= 0;
      rsp_valid <= 0;
      request_waited <= 0;
    end else begin
      cycle <= cycle + 1;
      if (req_valid && !request_waited) request_waited <= 1;
      if (req_valid && req_ready) begin
        request_waited <= 0;
        if (req_length == 0 || req_length > MaxBurst || req_address[2:0] != 0)
          $fatal(1, "model fixture invalid request");
        address <= req_address;
        length <= int'(req_length);
        beats <= 0;
        model_active <= 1;
        requests = requests + 1;
        if (raw_region(req_address) || gamma_region(req_address)) begin
          if (source_requests < Strips) begin
            source_strip = source_requests;
            expected_address = RawBase + 64'(source_strip * StripBytes);
          end else begin
            source_strip = (source_requests - Strips) / 2;
            expected_address = (source_requests % 2 == 0 ? RawBase : GammaBase) +
                               64'(source_strip * StripBytes);
          end
          if (source_requests >= SourceRequests || req_length != 2 ||
              req_address !== expected_address)
            $fatal(1, "raw/coefficient read ordering, stride or extent mismatch");
          if (raw_region(req_address)) raw_bytes += int'(req_length) * MemoryBytes;
          else gamma_bytes += int'(req_length) * MemoryBytes;
          source_requests++;
        end else begin
          if (source_requests != SourceRequests)
            $fatal(1, "compute requested memory before raw/coefficient preparation finished");
          if (req_address >= GateSignBase) begin
            phase = req_address >= UpSignBase ? 6 : 5;
            offset = req_address - (phase == 6 ? UpSignBase : GateSignBase);
            group_index = int'(offset / SignGroupStride);
            pair_index = int'((offset % SignGroupStride) / MemoryBytes);
            row = selected_row(group_index * GroupChannels);
            feature = pair_index * 2;
            if (req_length != 1 || row < 0 || feature >= Features || !(($signed(
                    normalized[feature]
                ) > OutlierLimit || $signed(
                    normalized[feature]
                ) < -OutlierLimit) || ($signed(
                    normalized[feature+1]
                ) > OutlierLimit || $signed(
                    normalized[feature+1]
                ) < -OutlierLimit)))
              $fatal(1, "model sign request outside selected outlier pairs");
            sign_bytes += MemoryBytes;
          end else if (req_address >= DownBase) down_bytes += int'(req_length) * MemoryBytes;
          else if (req_address >= UpBase) up_bytes += int'(req_length) * MemoryBytes;
          else if (req_address >= GateBase) gate_bytes += int'(req_length) * MemoryBytes;
          else $fatal(1, "model memory top requested external quantized activation");
        end
      end
      if (model_active && !rsp_valid && cycle % ResponseStallPeriod != 0) begin
        rsp_valid <= 1;
        rsp_last  <= beats == length - 1;
        if (raw_region(address) || gamma_region(address)) begin
          offset = address - (raw_region(address) ? RawBase : GammaBase);
          for (lane = 0; lane < RawLanesPerBeat; lane++) begin
            index = int'(offset / (RawBits / ByteBits)) + beats * RawLanesPerBeat + lane;
            if (index < 0 || index >= Features)
              $fatal(1, "raw/coefficient response outside source extent");
            rsp_data[lane*RawBits+:RawBits] <= raw_region(
                address
            ) ? raw_residual[index] : learned_gamma[index];
          end
        end else if (address >= GateSignBase) begin
          phase = address >= UpSignBase ? 6 : 5;
          offset = address - (phase == 6 ? UpSignBase : GateSignBase);
          group_index = int'(offset / SignGroupStride);
          pair_index = int'((offset % SignGroupStride) / MemoryBytes);
          for (int half = 0; half < 2; half++) begin
            feature = pair_index * 2 + half;
            for (int channel = 0; channel < GroupChannels; channel++) begin
              row = selected_row(group_index * GroupChannels + channel);
              if (row < 0 || feature >= Features) $fatal(1, "model sign response outside fixture");
              index = row * Features + feature;
              rsp_data[half*GroupChannels+channel] <= phase == 6 ?
                  up_weights[index][ByteBits-1] : gate_weights[index][ByteBits-1];
            end
          end
        end else
          for (lane = 0; lane < MemoryBytes; lane++) begin
            cursor = address + 64'(beats * MemoryBytes + lane);
            if (address >= DownBase) begin
              offset = cursor - DownBase;
              row = int'(offset / DenseFeatures) - int'(configuration[3]);
              column = int'(offset % DenseFeatures);
              if (row < 0 || row >= Outputs) $fatal(1, "model down row outside configured outputs");
              rsp_data[lane*ByteBits+:ByteBits] <= down_weights[row*DenseFeatures+column];
            end else begin
              phase = address >= UpBase ? 2 : 1;
              offset = cursor - (phase == 2 ? UpBase : GateBase);
              original = int'(offset / Features);
              column = int'(offset % Features);
              row = selected_row(original);
              if (row < 0 || skip_channels[row] != 0)
                $fatal(1, "model fetched unselected or predicted-skipped row %0d", original);
              index = row * Features + column;
              rsp_data[lane*ByteBits+:ByteBits] <= phase == 2 ? up_weights[index] :
                                                                          gate_weights[index];
            end
          end
      end
      if (rsp_valid && rsp_ready) begin
        rsp_valid <= 0;
        if (rsp_last) model_active <= 0;
        else beats <= beats + 1;
      end
    end
  end

  always @(negedge clk)
    if (rst_n) begin
      if (!out_valid) begin
        out_ready   = 0;
        output_wait = 0;
      end else if (output_wait < MinimumOutputWait) begin
        out_ready = 0;
        output_wait++;
      end else out_ready = cycle % OutputStallPeriod != 0;
    end
  always_ff @(posedge clk)
    if (rst_n) begin : scoreboard
      int lane, count;
      if (out_valid !== 1'b0 && out_valid !== 1'b1) $fatal(1, "unknown output-valid");
      if (req_valid !== 1'b0 && req_valid !== 1'b1) $fatal(1, "unknown request-valid");
      if (request_stalled && (req_valid !== 1'b1 || {req_address, req_length} !== held_request))
        $fatal(1, "request changed under backpressure");
      request_stalled = req_valid && !req_ready;
      held_request = {req_address, req_length};
      if (request_stalled) request_stall_cycles++;
      if (stalled && (out_valid !== 1'b1 ||
        {out_count, out_last, out_error, out_fallback, out_tag, out_channels, out_data} !== held))
        $fatal(1, "model output changed under backpressure");
      stalled = out_valid && !out_ready;
      if (stalled) output_stall_cycles++;
      held = {out_count, out_last, out_error, out_fallback, out_tag, out_channels, out_data};
      if (out_valid && out_ready) begin
        count = Outputs - received > GroupChannels ? GroupChannels : Outputs - received;
        if (out_error !== 1'b0 || out_fallback !== 1'b0 || out_tag !== Tag ||
          out_count !== 6'(count) || out_last !== (received + count == Outputs))
          $fatal(1, "model result metadata mismatch");
        for (lane = 0; lane < GroupChannels; lane++) begin
          if (lane < count) begin
            if (out_channels[lane*RawBits+:RawBits] !==
              RawBits'(int'(configuration[3]) + received + lane) ||
              out_data[lane*SumBits+:SumBits] !== expected[received+lane])
              $fatal(
                  1,
                  "model reference mismatch row=%0d got=%0d expected=%0d",
                  received + lane,
                  $signed(
                      out_data[lane*SumBits+:SumBits]
                  ),
                  $signed(
                      expected[received+lane]
                  )
              );
          end else if (out_data[lane*SumBits+:SumBits] !== SumBits'(0))
            $fatal(1, "nonzero padded output");
        end
        received = received + count;
      end
    end

  initial begin : stimulus
    int group_index, row, timeout;
    fixture_override = $value$plusargs("FIXTURE_DIR=%s", fixture_directory);
    $readmemh({fixture_directory, "/configuration.hex"}, configuration);
    $readmemh({fixture_directory, "/gate.hex"}, gate_weights);
    $readmemh({fixture_directory, "/up.hex"}, up_weights);
    $readmemh({fixture_directory, "/down.hex"}, down_weights);
    $readmemh({fixture_directory, "/norm.hex"}, normalized);
    $readmemh({fixture_directory, "/expected.hex"}, expected);
    $readmemh({fixture_directory, "/skip.hex"}, skip_channels);
    $readmemh({fixture_directory, "/groups.hex"}, groups);
    $readmemh({fixture_directory, "/raw_residual.hex"}, raw_residual);
    $readmemh({fixture_directory, "/epsilon_q16.hex"}, epsilon);
    $readmemh({fixture_directory, "/gamma.hex"}, learned_gamma);
    $readmemh({fixture_directory, "/activation_shift.hex"}, activation_shift);
    for (row = 0; row < SelectedChannels; row++) if (skip_channels[row] != 0) skipped++;
    repeat (2) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    cfg_valid = 1;
    @(posedge clk);
    if (!cfg_ready) $fatal(1, "model configuration blocked");
    @(negedge clk);
    cfg_valid = 0;
    for (group_index = 0; group_index < Groups; group_index++) begin
      @(negedge clk);
      group_valid = 1;
      group_id = groups[group_index][10:0];
      group_last = group_index == Groups - 1;
      timeout = 0;
      @(posedge clk);
      while (!group_ready && timeout < GroupTimeout) begin
        @(posedge clk);
        timeout++;
      end
      if (!group_ready) $fatal(1, "model memory-fed group stalled");
      @(negedge clk);
      group_valid = 0;
      group_id = '1;
      group_last = group_index != Groups - 1;
    end
    timeout = 0;
    while (received < Outputs && timeout < GroupTimeout) begin
      @(negedge clk);
      timeout++;
    end
    if (received != Outputs || requests == 0) $fatal(1, "model output missing");
    if (request_stall_cycles == 0 || output_stall_cycles == 0)
      $fatal(
          1,
          "missing backpressure coverage: request=%0d output=%0d",
          request_stall_cycles,
          output_stall_cycles
      );
    if (gate_bytes !== (SelectedChannels - skipped) * Features ||
        up_bytes !== (SelectedChannels - skipped) * Features)
      $fatal(1, "kept-row weight traffic does not match predicted mask");
    if (activation_bytes != 0) $fatal(1, "model activation traffic was not served locally");
    if (raw_bytes != RawBytes || gamma_bytes != GammaBytes || source_requests != SourceRequests)
      $fatal(1, "missing memory-driven raw/coefficient traffic");
    $display("SOURCE_TRAFFIC: raw_bytes=%0d gamma_bytes=%0d", raw_bytes, gamma_bytes);
    $display("STALL_COVERAGE: request_cycles=%0d output_cycles=%0d", request_stall_cycles,
             output_stall_cycles);
    $display({"WEIGHT_TRAFFIC: gate_bytes=%0d up_bytes=%0d dense_bytes_per_matrix=131072 ",
              "skipped_channels=%0d activation_bytes=%0d down_bytes=%0d"}, gate_bytes, up_bytes,
               skipped, activation_bytes, down_bytes);
    $display("HARDWARE_PREDICTION_TRAFFIC: sign_bytes=%0d", sign_bytes);
    repeat (10) @(negedge clk);
    $display({"PASS: pinned TinyLLaVA-v1 memory-fed layer0 slice,64 original channels,",
              "2048 features,5632 down stride,35 output sums; cycles=%0d requests=%0d"}, cycle,
               requests);
    $finish;
  end
  initial begin
    #WatchdogNs;
    $fatal(1, "model fixture watchdog");
  end
endmodule
