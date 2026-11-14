"""Connect the residual-bank fabric to the existing feed-forward scheduler."""

import argparse
from pathlib import Path

from prepare_tri_oracle_residual_bank_core import replace_once
from prepare_tri_oracle_residual_fabric import LINK, PORTS, TOP as FABRIC, add_ports


def extend(source, original, variant, child, child_variant):
    source = replace_once(source, f"module {original} ", f"module {variant} ")
    source = replace_once(source, f"  {child} #(", f"  {child_variant} #(")
    link = "    .head_request,.head_response,"
    source = replace_once(source, link, f"    {LINK},\n{link}")
    return add_ports(source, PORTS)


def prepare(output):
    rtl = Path(__file__).resolve().parents[1] / "verilog"
    tensor = extend(
        (rtl / "tri_oracle_batched_tensor390.sv").read_text(),
        "tri_oracle_batched_tensor390", "tri_oracle_residual_tensor",
        "tri_oracle_compute_fabric", FABRIC,
    )
    shared = extend(
        (rtl / "tri_oracle_batched_shared392.sv").read_text(),
        "tri_oracle_batched_shared392", "tri_oracle_residual_shared",
        "tri_oracle_batched_tensor390", "tri_oracle_residual_tensor",
    )
    frame = (rtl / "tri_oracle_batched_frame393.sv").read_text()
    public, header, implementation = frame.partition("module tri_oracle_batched_frame437")
    inner_frame = extend(
        header + implementation,
        "tri_oracle_batched_frame437", "tri_oracle_residual_frame_inner",
        "tri_oracle_batched_shared392", "tri_oracle_residual_shared",
    )
    # The original frame source supplies the attention interface to both variants.
    wrapper = "module tri_oracle_batched_frame393" + public.split("module tri_oracle_batched_frame393", 1)[1]
    wrapper = replace_once(wrapper, "module tri_oracle_batched_frame393 (", "module tri_oracle_residual_frame (")
    wrapper = replace_once(
        wrapper,
        "  tri_oracle_batched_frame437 implementation (",
        f"  tri_oracle_residual_frame_inner implementation (\n      {LINK},",
    )
    with output.open("x") as stream:
        stream.write("`timescale 1ns/1ps\n" + "\n".join((tensor, shared, inner_frame, add_ports(wrapper, PORTS))))


def bench_variant(source):
    source = replace_once(source, "  wire out_ready=hold_done && cycle%11>=5;", """  wire out_ready;
  wire handoff_ready = hold_done && cycle%11>=5;
  wire handoff_valid, handoff_last, bypass_valid, bypass_ready;
  wire [31:0] handoff_tag;
  wire [3:0] handoff_token, handoff_count;
  wire [15:0] handoff_start;
  wire [127:0] handoff_data;
  wire [231:0] bypass_data;
  logic residual_reserved=0, frame_started=0;
  logic norm_cfg_valid=0, norm_cfg_token=0, attention_valid=0;
  logic [348:0] attention_operands;
  wire norm_cfg_ready, attention_ready, activation_valid, activation_last, activation_error;
  wire activation_ready = cycle%7>=2;
  wire [7:0] gamma_strip;
  wire [9:0] activation_index;
  wire [63:0] activation_data;
  wire residual_ce_n, residual_we_n;
  wire [8:0] residual_addr;
  wire [255:0] residual_d, residual_q;
  logic [620:0] residual_fixture [512];
  logic [708:0] attention_fixture [576];
  logic [255:0] gamma_fixture [512];
  logic [63:0] generated_activation [512];
  string residual_path, activated_fixture, attention_path, gamma_path;
  int accepted_strips=0, stalled_strips=0, activation_strips=0, attention_strips=0;
  wire read_strip = frame_started && out_valid && out_token<2 &&
                    handoff_start<2048 && handoff_start[2:0]==0;

  tri_oracle_residual_normalize_bank residual_memory (
      .clk, .rst_n, .lease_granted(residual_reserved),
      .cfg_valid(norm_cfg_valid), .cfg_ready(norm_cfg_ready), .cfg_token(norm_cfg_token),
      .cfg_tag(32'ha4010000 + 32'(norm_cfg_token)), .cfg_epsilon_q16(32'd43980465), .cfg_shift(6'd17),
      .in_valid(attention_valid), .in_ready(attention_ready), .residual_q32(attention_operands[279:0]),
      .projection_codes(attention_operands[343:280]), .projection_shift(attention_operands[348:344]),
      .gamma_valid(cycle%11>=5), .gamma_ready(), .gamma_strip,
      .gamma_data(gamma_fixture[{norm_cfg_token, gamma_strip}][255:128]),
      .out_valid(activation_valid), .out_ready(activation_ready), .out_last(activation_last),
      .out_error(activation_error), .out_index(activation_index), .out_activation(activation_data),
      .out_tag(), .out_count(), .out_norm_q8(), .out_outlier_mask(),
      .read_valid(read_strip), .read_ready(), .read_row({out_token[0], handoff_start[10:3]}),
      .response_valid(bypass_valid), .response_ready(bypass_ready), .response_data(bypass_data),
      .bank_ce_n(residual_ce_n), .bank_we_n(residual_we_n), .bank_addr(residual_addr),
      .bank_d(residual_d), .bank_q(residual_q)
  );
  tri_oracle_decoder_writeback_bridge bridge (
      .clk, .rst_n, .in_valid(out_valid), .in_ready(out_ready),
      .in_tag(out_tag), .in_token(out_token), .in_start(out_start), .in_count(out_count),
      .in_last(out_last), .in_data(out_data), .bypass_valid, .bypass_ready, .bypass_data,
      .down_shift(5'd11), .out_valid(handoff_valid), .out_ready(handoff_ready),
      .out_tag(handoff_tag), .out_token(handoff_token), .out_start(handoff_start),
      .out_count(handoff_count), .out_last(handoff_last), .out_data(handoff_data)
  );
  always @(posedge clk) if (rst_n && handoff_valid) begin
      int start, token, row, tile;
      tile = accepted_strips / 40;
      token = tile == 12 ? (accepted_strips-480)/16 : (accepted_strips/20)%2;
      start = tile*160 + (tile == 12 ? (accepted_strips-480)%16 : accepted_strips%20)*8;
      row = token*256 + start/8;
      if (accepted_strips>=512 || handoff_tag!==32'h39300001 ||
          handoff_token!==4'(token) || handoff_start!==16'(start) || handoff_count!==4'd8 ||
          handoff_last!==(accepted_strips==511) || bypass_data!==residual_fixture[row][231:0] ||
          handoff_data!==residual_fixture[row][620:493])
          $fatal(1, "RESIDUAL_SCHEDULE_MISMATCH strip=%0d token=%0d start=%0d", accepted_strips, token, start);
      if (handoff_ready) accepted_strips++;
      else stalled_strips++;
  end""")
    source = replace_once(source, "  tri_oracle_batched_frame393 dut(.*);",
                          "  tri_oracle_residual_frame dut(.*);" + """
  always @(posedge clk) if (rst_n) begin
      if (attention_valid && attention_ready) attention_strips++;
      if (activation_valid && activation_ready) begin
          if (activation_strips>=512 || activation_error || activation_index!==10'(activation_strips%256) ||
              activation_last!==(activation_strips%256==255))
              $fatal(1, "RESIDUAL_SCHEDULE_ACTIVATION_PROTOCOL row=%0d", activation_strips);
          for (int lane=0; lane<8; lane++)
              if (activation_data[8*lane +: 8] !== fixture_activation[8*activation_strips+lane])
                  $fatal(1, "RESIDUAL_SCHEDULE_ACTIVATION_DATA row=%0d lane=%0d", activation_strips, lane);
          generated_activation[activation_strips] = activation_data;
          activation_strips++;
      end
      if (req_valid && (activation_strips!=512 || !frame_started))
          $fatal(1, "RESIDUAL_SCHEDULE_ACTIVATION_NOT_COMMITTED");
  end""")
    source = replace_once(source, '      if(!$value$plusargs("FIXTURE=%s",fixture))', '''      if (!$value$plusargs("ACTIVATED=%s", activated_fixture) ||
          !$value$plusargs("RESIDUAL=%s", residual_path) ||
          !$value$plusargs("ATTENTION=%s", attention_path) ||
          !$value$plusargs("GAMMA=%s", gamma_path))
          $fatal(1, "RESIDUAL_SCHEDULE_FIXTURES");
      $readmemh(residual_path, residual_fixture);
      $readmemh(attention_path, attention_fixture);
      $readmemh(gamma_path, gamma_fixture);
      for (int row=0; row<512; row++)
          if (residual_fixture[row][492:488] !== 5'd11) $fatal(1, "RESIDUAL_SCHEDULE_SHIFT");
      if(!$value$plusargs("FIXTURE=%s",fixture))''')
    for name in ("activation", "expected"):
        old = f'$readmemh({{fixture,"/{name}.hex"}},'
        source = replace_once(source, old, old.replace("{fixture,", "{activated_fixture,"))
    source = replace_once(source, "  always_comb begin: read_word",
                          "  always @(read_address or read_beat or read_active) begin: read_word")
    source = replace_once(
        source, "      for(int b=0;b<8;b++)rsp_data[b*8+:8]=8'(activation(token,feature+b));",
        "      rsp_data=generated_activation[(token*HIDDEN+feature)/8];",
    )
    source = replace_once(source, "    repeat(3)@(negedge clk);rst_n=1;configure();", """    if (!TRAINED || FAULT!=0 || TOKENS!=2 || OUTPUTS!=2048)
        $fatal(1, "RESIDUAL_SCHEDULE_DESCRIPTOR");
    repeat(3) @(negedge clk);
    rst_n=1;
    residual_reserved=1;
    for (int token=0; token<2; token++) begin
        norm_cfg_token=1'(token);
        norm_cfg_valid=1;
        do @(posedge clk); while (norm_cfg_ready !== 1'b1);
        @(negedge clk);
        norm_cfg_valid=0;
        for (int strip=0; strip<256; strip++) begin
            attention_operands=attention_fixture[token*256+strip][348:0];
            attention_valid=1;
            do @(posedge clk); while (attention_ready !== 1'b1);
            @(negedge clk);
        end
        attention_valid=0;
        wait (activation_strips==(token+1)*256 && norm_cfg_ready);
        @(negedge clk);
    end
    if (attention_strips!=512 || activation_strips!=512)
        $fatal(1, "RESIDUAL_SCHEDULE_ACTIVATION_COUNT");
    $display("RESIDUAL_SCHEDULE_ACTIVATION_COMMITTED strips=512 bytes=4096");
    $fflush();
    frame_started=1;
    configure();""")
    return replace_once(source, '    $display("BATCH393_PASS tokens=', '''    if (accepted_strips!=512 || stalled_strips==0)
        $fatal(1, "RESIDUAL_SCHEDULE_COUNT got=%0d stalled=%0d", accepted_strips, stalled_strips);
    $display("RESIDUAL_SCHEDULE_PASS strips=%0d values=%0d stalls=%0d",
             accepted_strips, accepted_strips*8, stalled_strips);
    $display("BATCH393_PASS tokens=''')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--bench", type=Path)
    args = parser.parse_args()
    prepare(args.output)
    if args.bench:
        original = Path(__file__).resolve().parents[1] / "verilog/tri_oracle_batched393_tb.sv"
        with args.bench.open("x") as stream:
            stream.write(bench_variant(original.read_text()))
