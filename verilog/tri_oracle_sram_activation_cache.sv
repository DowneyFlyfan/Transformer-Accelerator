// Updated to modern SystemVerilog
`timescale 1ns / 1ps
// Select this backend instead of the inferred cache. A build may explicitly bind
// TRI_ORACLE_SRAM_CACHE_BIND_PUBLIC to expose the original consumer module name.
module tri_oracle_sram_activation_cache (
    input logic clk,
    rst_n,
    cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [9:0] cfg_strips,
    input logic in_valid,
    output logic in_ready,
    input logic in_last,
    in_error,
    input logic [31:0] in_tag,
    input logic [9:0] in_index,
    input logic [3:0] in_count,
    input logic [127:0] in_norm_q8,
    input logic [7:0] in_outlier_mask,
    input logic [63:0] in_activation,
    output logic done_valid,
    input logic done_ready,
    output logic done_error,
    output logic [31:0] done_tag,
    input logic release_valid,
    output logic release_ready,
    input logic meta_req_valid,
    output logic meta_req_ready,
    input logic [8:0] meta_req_index,
    output logic meta_rsp_valid,
    input logic meta_rsp_ready,
    output logic meta_rsp_error,
    output logic [8:0] meta_rsp_index,
    output logic [31:0] meta_rsp_tag,
    output logic [127:0] meta_rsp_norm,
    input logic read_req_valid,
    output logic read_req_ready,
    input logic [8:0] read_req_index,
    input logic [4:0] read_req_length,
    output logic read_rsp_valid,
    input logic read_rsp_ready,
    output logic read_rsp_last,
    read_rsp_error,
    output logic [63:0] read_rsp_data
);
  // Fixed public widths match the original cache and the generated macro ports.
  localparam int CacheWords = 512;
  localparam int LaneCount = 8;
  localparam int NormBits = 16;
  localparam int ActivationBits = 64;
  localparam int MetadataBits = 16;
  localparam int WordAddressBits = 9;
  localparam int MaxBurstWords = 16;
  localparam int CounterBits = 10;
  localparam logic [CounterBits-1:0] CounterMaximum = '1;
  localparam logic signed [NormBits-1:0] OutlierThreshold = 16'sd768;
  localparam logic signed [NormBits-1:0] ProxyMagnitude = 16'sd769;

  logic busy, writing, committed, fault;
  logic [31:0] tag;
  logic [CounterBits-1:0] strips, seen;
  logic [LaneCount-1:0] incoming_signs, expected_outliers;
  logic word_bad, expected_last, read_bad;
  logic [WordAddressBits-1:0] read_index;
  logic [4:0] read_remaining;
  logic cache_write, activation_read, activation_advance, metadata_read;
  logic activation_ceb, metadata_ceb, memory_web;
  logic [WordAddressBits-1:0] activation_addr, metadata_addr;
  logic [ActivationBits-1:0] activation_q, held_activation;
  logic [MetadataBits-1:0] metadata_q, metadata_write_data;
  logic [LaneCount*NormBits-1:0] held_metadata;

  function automatic logic [LaneCount*NormBits-1:0] expand_proxy(
      input logic [MetadataBits-1:0] metadata);
    for (int lane = 0; lane < LaneCount; lane++) begin
      if (!metadata[lane]) expand_proxy[lane*NormBits+:NormBits] = '0;
      else if (metadata[lane+LaneCount]) expand_proxy[lane*NormBits+:NormBits] = -ProxyMagnitude;
      else expand_proxy[lane*NormBits+:NormBits] = ProxyMagnitude;
    end
  endfunction

  always_comb begin
    for (int lane = 0; lane < LaneCount; lane++) begin
      incoming_signs[lane] = in_norm_q8[lane*NormBits+NormBits-1];
      expected_outliers[lane] = $signed(in_norm_q8[lane*NormBits+:NormBits]) > OutlierThreshold ||
          $signed(in_norm_q8[lane*NormBits+:NormBits]) < -OutlierThreshold;
    end
    expected_last = {1'b0, seen} + 1'b1 == {1'b0, strips};
    word_bad = in_error || in_tag != tag || in_count != LaneCount || in_index != seen ||
               seen >= strips || in_last != expected_last || in_outlier_mask != expected_outliers;
    read_bad = read_req_length == 0 || read_req_length > MaxBurstWords ||
               11'(read_req_index) + 11'(read_req_length) > 11'(strips);
    cfg_ready = !busy;
    in_ready = busy && writing;
    done_tag = tag;
    release_ready = busy && !writing && !done_valid && !meta_rsp_valid && !read_rsp_valid;
    meta_req_ready = busy && committed && !done_valid && !release_valid &&
                     (!meta_rsp_valid || meta_rsp_ready);
    read_req_ready = busy && committed && !done_valid && !release_valid && !read_rsp_valid;
  end

  always_comb begin
    cache_write = rst_n && in_valid && in_ready && !fault && !word_bad;
    activation_advance = read_rsp_valid && read_rsp_ready && !read_rsp_last;
    activation_read = (read_req_valid && read_req_ready && !read_bad) || activation_advance;
    metadata_read = meta_req_valid && meta_req_ready && {1'b0, meta_req_index} < strips;
    activation_addr = activation_advance ? read_index + 1'b1 : read_req_index;
    metadata_addr = meta_req_index;
    if (cache_write) begin
      activation_addr = in_index[WordAddressBits-1:0];
      metadata_addr   = in_index[WordAddressBits-1:0];
    end
    activation_ceb = !rst_n || !(cache_write || activation_read);
    metadata_ceb = !rst_n || !(cache_write || metadata_read);
    memory_web = !cache_write;
    metadata_write_data = {incoming_signs, in_outlier_mask};
    meta_rsp_norm = meta_rsp_valid ? (meta_rsp_error ? '0 : expand_proxy(metadata_q)) :
        held_metadata;
    read_rsp_data = read_rsp_valid ? (read_rsp_error ? '0 : activation_q) : held_activation;
  end

  // Independent clocked-read memories preserve both simultaneous cache ports.
  TS5N28HPCPSVTA512X64M4F activation_memory (
      .CLK(clk),
      .CEB(activation_ceb),
      .WEB(memory_web),
      .A  (activation_addr),
      .D  (in_activation),
      .Q  (activation_q)
  );
  TS5N28HPCPSVTA512X16M4F metadata_memory (
      .CLK(clk),
      .CEB(metadata_ceb),
      .WEB(memory_web),
      .A  (metadata_addr),
      .D  (metadata_write_data),
      .Q  (metadata_q)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      busy <= 0;
      writing <= 0;
      committed <= 0;
      fault <= 0;
      tag <= '0;
      strips <= '0;
      seen <= '0;
      done_valid <= 0;
      done_error <= 0;
      meta_rsp_valid <= 0;
      meta_rsp_error <= 0;
      meta_rsp_index <= '0;
      meta_rsp_tag <= '0;
      held_metadata <= '0;
      read_rsp_valid <= 0;
      read_rsp_last <= 0;
      read_rsp_error <= 0;
      held_activation <= '0;
      read_index <= '0;
      read_remaining <= '0;
    end else begin
      // These small registers retain even inactive response values during refill.
      if (meta_rsp_valid) held_metadata <= meta_rsp_norm;
      if (read_rsp_valid) held_activation <= read_rsp_data;
      if (cfg_valid && cfg_ready) begin
        busy <= 1;
        writing <= 1;
        committed <= 0;
        fault <= cfg_strips == 0 || cfg_strips > CacheWords;
        tag <= cfg_tag;
        strips <= cfg_strips;
        seen <= '0;
        done_error <= 0;
      end
      if (in_valid && in_ready) begin
        fault <= fault || word_bad;
        if (seen != CounterMaximum) seen <= seen + 1'b1;
        if (in_last) begin
          writing <= 0;
          done_valid <= 1;
          done_error <= fault || word_bad;
          committed <= !fault && !word_bad;
        end
      end
      if (done_valid && done_ready) done_valid <= 0;
      if (meta_rsp_valid && meta_rsp_ready) meta_rsp_valid <= 0;
      if (meta_req_valid && meta_req_ready) begin
        meta_rsp_valid <= 1;
        meta_rsp_tag   <= tag;
        meta_rsp_index <= meta_req_index;
        meta_rsp_error <= {1'b0, meta_req_index} >= strips;
      end
      if (read_req_valid && read_req_ready) begin
        read_rsp_valid <= 1;
        read_rsp_error <= read_bad;
        read_rsp_last <= read_bad || read_req_length == 1;
        read_index <= read_req_index;
        read_remaining <= read_req_length;
      end
      if (read_rsp_valid && read_rsp_ready) begin
        if (read_rsp_last) read_rsp_valid <= 0;
        else begin
          read_index <= read_index + 1'b1;
          read_remaining <= read_remaining - 1'b1;
          read_rsp_last <= read_remaining == 2;
        end
      end
      if (release_valid && release_ready) begin
        busy <= 0;
        committed <= 0;
      end
    end
  end
endmodule

`ifdef TRI_ORACLE_SRAM_CACHE_BIND_PUBLIC
module tri_oracle_activation_cache (
    input logic clk,
    rst_n,
    cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [9:0] cfg_strips,
    input logic in_valid,
    output logic in_ready,
    input logic in_last,
    in_error,
    input logic [31:0] in_tag,
    input logic [9:0] in_index,
    input logic [3:0] in_count,
    input logic [127:0] in_norm_q8,
    input logic [7:0] in_outlier_mask,
    input logic [63:0] in_activation,
    output logic done_valid,
    input logic done_ready,
    output logic done_error,
    output logic [31:0] done_tag,
    input logic release_valid,
    output logic release_ready,
    input logic meta_req_valid,
    output logic meta_req_ready,
    input logic [8:0] meta_req_index,
    output logic meta_rsp_valid,
    input logic meta_rsp_ready,
    output logic meta_rsp_error,
    output logic [8:0] meta_rsp_index,
    output logic [31:0] meta_rsp_tag,
    output logic [127:0] meta_rsp_norm,
    input logic read_req_valid,
    output logic read_req_ready,
    input logic [8:0] read_req_index,
    input logic [4:0] read_req_length,
    output logic read_rsp_valid,
    input logic read_rsp_ready,
    output logic read_rsp_last,
    read_rsp_error,
    output logic [63:0] read_rsp_data
);
  tri_oracle_sram_activation_cache implementation (.*);
endmodule
`endif
