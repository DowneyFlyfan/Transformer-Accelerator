"""Connect the compact sign predictor to both packed weight read lanes."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_packed_sign_predictor import ROOT, rewrite, sha


PHYSICAL = ROOT / ".cache/physical"
CHIP = PHYSICAL / "wide_weight_loader/parallel_chip_v3"
PREDICTOR = PHYSICAL / "ranked_sign_slots/banked_observation_32"
NORMALIZER = PHYSICAL / "wac_core_local_outlier_v2/tri_oracle_batched_normalize405.sv"
LEARNED = "tri_oracle_batched_learned406.sv"
LAYER = "tri_oracle_shared_layer437.sv"
PACKED_NORMALIZER = "tri_oracle_packed_normalize405"


def normalizer(source):
    return rewrite(source, (
        ("module tri_oracle_batched_normalize405", f"module {PACKED_NORMALIZER}"),
        ("cfg_gate_sign_base, cfg_up_sign_base, cfg_activation_base", "cfg_sign_base, cfg_activation_base"),
        ("""    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,
    output logic rsp_ready,
    input logic rsp_last, rsp_error,
    input logic [63:0] rsp_data,""", """    output logic [1:0] req_valid,
    input logic [1:0] req_ready,
    output logic [63:0] req_address,
    output logic [5:0] req_length,
    input logic [1:0] rsp_valid,
    output logic [1:0] rsp_ready,
    input logic [1:0] rsp_last, rsp_error,
    input logic [1:0][511:0] rsp_data,"""),
        ("activation_end, gate_sign_end, up_sign_end, sign_bytes", "activation_end, sign_end, sign_bytes"),
        ("""        sign_bytes = (65'(cfg_groups) * 65'(cfg_strips)) << 5;
        gate_sign_end = {1'b0, cfg_gate_sign_base} + sign_bytes - 65'd1;
        up_sign_end = {1'b0, cfg_up_sign_base} + sign_bytes - 65'd1;""",
         """        sign_bytes = (65'(cfg_groups) * 65'(cfg_strips)) << 6;
        sign_end = {1'b0, cfg_sign_base} + sign_bytes - 65'd1;"""),
        ("""            cfg_gate_sign_base[2:0] != 0 || cfg_up_sign_base[2:0] != 0 ||
            activation_end[64] || gate_sign_end[64] || up_sign_end[64] ||
            ({1'b0, cfg_activation_base} <= gate_sign_end && {1'b0, cfg_gate_sign_base} <= activation_end) ||
            ({1'b0, cfg_activation_base} <= up_sign_end && {1'b0, cfg_up_sign_base} <= activation_end);""",
         """            cfg_sign_base[5:0] != 0 || activation_end[64] || sign_end[64] ||
            ({1'b0, cfg_activation_base} <= sign_end && {1'b0, cfg_sign_base} <= activation_end);"""),
        ("    tri_oracle_batched_outlier_replay404 #", "    tri_oracle_packed_outlier_replay #"),
        (".cfg_gate_sign_base(cfg_gate_sign_base), .cfg_up_sign_base(cfg_up_sign_base),",
         ".cfg_sign_base(cfg_sign_base),"),
    ))


def wide_connections():
    declarations = """    logic [1:0] sign_req_valid, sign_req_ready, sign_rsp_valid, sign_rsp_ready;
    logic [1:0] sign_rsp_last, sign_rsp_error;
    logic [63:0] sign_req_address;
    logic [5:0] sign_req_length;
    logic [1:0] weight_req_valid, weight_req_ready, weight_rsp_valid, weight_rsp_ready;
    logic [1:0] weight_rsp_last, weight_rsp_error;
    logic [1:0][63:0] weight_req_address;
    logic [1:0][5:0] weight_req_length;
    logic [1:0] lane_req_valid, lane_req_ready, lane_rsp_valid, lane_rsp_ready, lane_rsp_last, lane_rsp_error;
    logic [1:0][63:0] lane_req_address;
    logic [1:0][5:0] lane_req_length;
    logic [1:0][511:0] lane_rsp_data;

    assign {aux_req_valid, wide_req_valid} = lane_req_valid;
    assign lane_req_ready = {aux_req_ready, wide_req_ready};
    assign {aux_req_address, wide_req_address} = lane_req_address;
    assign {aux_req_length, wide_req_length} = lane_req_length;
    assign lane_rsp_valid = {aux_rsp_valid, wide_rsp_valid};
    assign {aux_rsp_ready, wide_rsp_ready} = lane_rsp_ready;
    assign lane_rsp_last = {aux_rsp_last, wide_rsp_last};
    assign lane_rsp_error = {aux_rsp_error, wide_rsp_error};
    assign lane_rsp_data = {aux_rsp_data, wide_rsp_data};

    if (PACKED_SIGN_PREDICTOR) begin : shared_wide_lanes
        for (genvar lane = 0; lane < 2; lane++) begin : lanes
            tri_oracle_wide_read_arbiter reads (
                .clk, .rst_n,
                .client_req_valid({sign_req_valid[lane], weight_req_valid[lane]}),
                .client_req_ready({sign_req_ready[lane], weight_req_ready[lane]}),
                .client_req_address({sign_req_address, weight_req_address[lane]}),
                .client_req_length({sign_req_length, weight_req_length[lane]}),
                .client_rsp_valid({sign_rsp_valid[lane], weight_rsp_valid[lane]}),
                .client_rsp_ready({sign_rsp_ready[lane], weight_rsp_ready[lane]}),
                .client_rsp_last({sign_rsp_last[lane], weight_rsp_last[lane]}),
                .client_rsp_error({sign_rsp_error[lane], weight_rsp_error[lane]}),
                .client_rsp_data(),
                .mem_req_valid(lane_req_valid[lane]), .mem_req_ready(lane_req_ready[lane]),
                .mem_req_address(lane_req_address[lane]), .mem_req_length(lane_req_length[lane]),
                .mem_rsp_valid(lane_rsp_valid[lane]), .mem_rsp_ready(lane_rsp_ready[lane]),
                .mem_rsp_last(lane_rsp_last[lane]), .mem_rsp_error(lane_rsp_error[lane]),
                .mem_rsp_data(lane_rsp_data[lane])
            );
        end
    end else begin : weight_only_lanes
        assign lane_req_valid = weight_req_valid;
        assign weight_req_ready = lane_req_ready;
        assign lane_req_address = weight_req_address;
        assign lane_req_length = weight_req_length;
        assign weight_rsp_valid = lane_rsp_valid;
        assign lane_rsp_ready = weight_rsp_ready;
        assign weight_rsp_last = lane_rsp_last;
        assign weight_rsp_error = lane_rsp_error;
    end
"""
    original = """    .aux_req_valid, .aux_req_ready, .aux_req_address, .aux_req_length, .aux_rsp_valid, .aux_rsp_ready, .aux_rsp_last, .aux_rsp_error, .aux_rsp_data,
    .wide_req_valid,.wide_req_ready,.wide_req_address,.wide_req_length,
    .wide_rsp_valid,.wide_rsp_ready,.wide_rsp_last,.wide_rsp_error,.wide_rsp_data,"""
    signals = ("req_valid", "req_ready", "req_address", "req_length", "rsp_valid", "rsp_ready",
               "rsp_last", "rsp_error", "rsp_data")
    compute = "\n".join(
        f"        .{prefix}_{signal}({'lane' if signal == 'rsp_data' else 'weight'}_{signal}[{lane}]),"
        for lane, prefix in enumerate(("wide", "aux")) for signal in signals
    )
    return declarations, original, compute


def learned_layer(source):
    before = source.index("    tri_oracle_batched_normalize405 #")
    after = source.index("\n\n    tri_oracle_batched_mask_packet399", before)
    legacy = source[before:after]
    packed = rewrite(legacy, (
        ("tri_oracle_batched_normalize405", PACKED_NORMALIZER),
        (".cfg_gate_sign_base(cfg_gate_sign_base), .cfg_up_sign_base(cfg_up_sign_base)",
         ".cfg_sign_base(cfg_gate_sign_base)"),
        ("""        .req_valid(predict_req_valid), .req_ready(predict_req_ready),
        .req_address(predict_req_address), .req_length(predict_req_length), .rsp_valid(predict_rsp_valid),
        .rsp_ready(predict_rsp_ready), .rsp_last(rsp_last), .rsp_error(rsp_error), .rsp_data(rsp_data),""",
         """        .req_valid(sign_req_valid), .req_ready(sign_req_ready),
        .req_address(sign_req_address), .req_length(sign_req_length), .rsp_valid(sign_rsp_valid),
        .rsp_ready(sign_rsp_ready), .rsp_last(sign_rsp_last), .rsp_error(sign_rsp_error), .rsp_data(lane_rsp_data),"""),
    ))
    declarations, old_connections, new_connections = wide_connections()
    branches = """    if (PACKED_SIGN_PREDICTOR) begin : packed_signs
        assign predict_req_valid = 0;
        assign predict_req_address = '0;
        assign predict_req_length = '0;
        assign predict_rsp_ready = 0;
""" + "\n".join("    " + line for line in packed.splitlines()) + "\n    end else begin : scalar_signs\n"
    branches += "\n".join("    " + line for line in legacy.splitlines()) + "\n    end"
    return rewrite(source[:before] + declarations + branches + source[after:], (
        ("  parameter bit PACKED_FEEDFORWARD_WEIGHTS=0,",
         "  parameter bit PACKED_FEEDFORWARD_WEIGHTS=0, PACKED_SIGN_PREDICTOR=0,"),
        ("{1'b0, cfg_gate_sign_base} + sign_bytes - 65'd1",
         "{1'b0, cfg_gate_sign_base} + (PACKED_SIGN_PREDICTOR ? sign_bytes << 1 : sign_bytes) - 65'd1"),
        ("cfg_gate_sign_base[2:0] != 0 || cfg_up_sign_base[2:0] != 0",
         "(PACKED_SIGN_PREDICTOR ? cfg_gate_sign_base[5:0] != 0 :\n"
         "             cfg_gate_sign_base[2:0] != 0 || cfg_up_sign_base[2:0] != 0)"),
        ("gate_sign_end[64] || up_sign_end[64]", "gate_sign_end[64] || (!PACKED_SIGN_PREDICTOR && up_sign_end[64])"),
        ("overlaps_scratch(cfg_gate_sign_base, gate_sign_end) || overlaps_scratch(cfg_up_sign_base, up_sign_end)",
         "overlaps_scratch(cfg_gate_sign_base, gate_sign_end) ||\n"
         "            (!PACKED_SIGN_PREDICTOR && overlaps_scratch(cfg_up_sign_base, up_sign_end))"),
        ("overlaps_activation(cfg_gate_sign_base, gate_sign_end) || overlaps_activation(cfg_up_sign_base, up_sign_end)",
         "overlaps_activation(cfg_gate_sign_base, gate_sign_end) ||\n"
         "            (!PACKED_SIGN_PREDICTOR && overlaps_activation(cfg_up_sign_base, up_sign_end))"),
        (old_connections, new_connections),
    ))


def directed_bench(source):
    feedforward = "dut.layer.layer.feedforward"
    return rewrite(source, (
        ("  int sign_requests=0,contended_cycles=0,valid_masks=0,abort_masks=0;",
         "  int sign_requests=0, sign_beats=0, contended_cycles=0,valid_masks=0,abort_masks=0;\n"
         "  int simultaneous_sign_weight_beats=0;\n"
         "  logic [65:0] trained_sign_reads[9152];\n"
         "  string sign_reads_path;"),
        ("""    assign wide_rsp_error[lane]=lane==FAULT_LANE && inject_fault && !fault_seen && wide_rsp_valid[lane] &&
      (FAULT==2 || (FAULT==3 && wide_address[lane]>=DOWN_BASE+64'(160*INTERMEDIATE)));""",
         """    assign wide_rsp_error[lane]=inject_fault && !fault_seen && wide_rsp_valid[lane] &&
      ((FAULT==4 && packed_sign_address(wide_address[lane])) ||
       (lane==FAULT_LANE && !packed_sign_address(wide_address[lane]) &&
        (FAULT==2 || (FAULT==3 && wide_address[lane]>=DOWN_BASE+64'(160*INTERMEDIATE)))));"""),
        ("  function automatic bit sign_address(input logic [63:0] address);",
         """  function automatic bit packed_sign_address(input logic [63:0] address);
    return address >= GATE_SIGN_BASE && address < GATE_SIGN_BASE + 64'(2*SIGN_BYTES);
  endfunction

  function automatic logic [511:0] packed_sign_line(input logic [63:0] address);
    int line, first_channel, first_feature;
    line = int'((address - GATE_SIGN_BASE) >> 6);
    first_channel = 32*(line/(HIDDEN/8));
    first_feature = 8*(line%(HIDDEN/8));
    for (int feature=0; feature<8; feature++)
      for (int channel=0; channel<32; channel++) begin
        packed_sign_line[(feature/2)*128+(feature%2)*32+channel] =
          gate_weight(first_channel+channel, first_feature+feature)<0;
        packed_sign_line[(feature/2)*128+64+(feature%2)*32+channel] =
          up_weight(first_channel+channel, first_feature+feature)<0;
      end
  endfunction

  function automatic bit packed_sign_lane(input logic [63:0] address);
    logic [4:0] bucket;
    bucket = '0;
    for (int first=6; first<64; first+=5)
      bucket ^= 5'(address>>first);
    return bucket >= 5'd9;
  endfunction

  function automatic bit sign_address(input logic [63:0] address);"""),
        ("""    if(wide_active[lane])begin
      branch=weight_branch(wide_address[lane]);""",
         """    if(wide_active[lane] && packed_sign_address(wide_address[lane]))
      wide_rsp_data[lane]=packed_sign_line(wide_address[lane]);
    else if(wide_active[lane])begin
      branch=weight_branch(wide_address[lane]);"""),
        (f"{feedforward}.predictor.activation_path.cfg_valid && {feedforward}.predictor.activation_path.cfg_ready",
         f"{feedforward}.packed_signs.predictor.activation_path.cfg_valid && "
         f"{feedforward}.packed_signs.predictor.activation_path.cfg_ready"),
        (f"{feedforward}.compute_req_valid && {feedforward}.predict_req_valid",
         f"|({feedforward}.weight_req_valid & {feedforward}.sign_req_valid)"),
        ("    if (&(wide_rsp_valid & wide_rsp_ready)) simultaneous_responses++;",
         "    if (&(wide_rsp_valid & wide_rsp_ready)) simultaneous_responses++;\n"
         f"    if ((|({feedforward}.sign_rsp_valid & {feedforward}.sign_rsp_ready)) &&\n"
         f"        (|({feedforward}.weight_rsp_valid & {feedforward}.weight_rsp_ready)))\n"
         "      simultaneous_sign_weight_beats++;"),
        ("""        if(!PACKED || branch<0 || (lane==0 && (read_active || req_valid)) || write_active || write_response ||
           activation_acks!=TOKENS*HIDDEN ||""",
         """        if(packed_sign_address(wide_req_address[lane])) begin
          logic [63:0] expected_address;
          logic [1:0] expected_lane;
          if (TRAINED) begin
            if (sign_requests >= 9152) $fatal(1,"DUAL_LANE_PACKED_SIGN_EXTRA");
            {expected_lane,expected_address}=trained_sign_reads[sign_requests];
          end else begin
            expected_address=GATE_SIGN_BASE+64'(64*((sign_requests/2)*(HIDDEN/8)
                             +((sign_requests%2)==0 ? 0 : HIDDEN/8-1)));
            expected_lane=2'b01 << packed_sign_lane(expected_address);
          end
          if(wide_req_length[lane]!=1 || activation_acks!=TOKENS*HIDDEN ||
             (lane==0 && (read_active || req_valid)) ||
             wide_req_address[lane]!==expected_address || expected_lane!==(2'b01<<lane))
            $fatal(1,"DUAL_LANE_PACKED_SIGN_REQUEST index=%0d lane=%0d address=%h wanted=%h",
                   sign_requests,lane,wide_req_address[lane],expected_address);
          sign_requests++;
        end else if(!PACKED || branch<0 || (lane==0 && (read_active || req_valid)) || write_active || write_response ||
           activation_acks!=TOKENS*HIDDEN ||"""),
        ("        wide_requests++;", "        if(!packed_sign_address(wide_req_address[lane]))wide_requests++;"),
        ("""        wide_beats++;
        lane_branch_beats[lane][branch]++;
        wide_branch_beats[branch]++;""", """        if(packed_sign_address(wide_address[lane]))sign_beats++;
        else begin
          wide_beats++;
          lane_branch_beats[lane][branch]++;
          wide_branch_beats[branch]++;
        end"""),
        ("(FAULT==4 && (sign_requests!=1 || read_beats!=2 || valid_masks!=0))",
         "(FAULT==4 && (sign_requests!=1 || sign_beats!=1 || read_beats!=0 || valid_masks!=0))"),
        ("      sign_requests=0;valid_masks=0;abort_masks=0;contended_cycles=0;",
         "      sign_requests=0;sign_beats=0;valid_masks=0;abort_masks=0;contended_cycles=0;\n"
         "      simultaneous_sign_weight_beats=0;"),
        ("""    if((TRAINED ? (sign_requests!=55616 || expected_sign_group!=INTERMEDIATE/32 ||
                   expected_sign_token!=0 || expected_sign_up) : sign_requests!=TOKENS*(INTERMEDIATE/32)*4) ||
        valid_masks!=GATE_GROUPS || abort_masks!=0 ||
        (INTERMEDIATE>=192 && contended_cycles==0))$fatal(1,"BATCH408_SHARED_BUS_INVENTORY");""",
         """    if(sign_requests!=(TRAINED ? 9152 : 2*(INTERMEDIATE/32)) || sign_beats!=sign_requests ||
       valid_masks!=GATE_GROUPS || abort_masks!=0)
      $fatal(1,"DUAL_LANE_PACKED_SIGN_INVENTORY req=%0d rsp=%0d masks=%0d",sign_requests,sign_beats,valid_masks);
    $display("DUAL_LANE_PACKED_SIGN_PASS requests=%0d responses=%0d overlap_cycles=%0d mixed_response_cycles=%0d",
             sign_requests,sign_beats,contended_cycles,simultaneous_sign_weight_beats);"""),
        ("""      $readmemh({raw_fixture,"/outlier_pairs.hex"},fixture_outlier_pairs);""",
         """      if (!$value$plusargs("SIGN_READS=%s",sign_reads_path))$fatal(1,"MISSING_TRAINED_SIGN_READS");
      $readmemh(sign_reads_path,trained_sign_reads);
      $readmemh({raw_fixture,"/outlier_pairs.hex"},fixture_outlier_pairs);"""),
    ))


def prepare(output):
    chip = CHIP / "prepared.json"
    predictor = ROOT / "records/wac_banked_ranked_observation_native_result.json"
    source = ROOT / "records/wac_parallel_chip_trained_source_result.json"
    expected = json.loads(chip.read_text())["input_sha256"]
    results = json.loads(predictor.read_text())["input_sha256"]
    assert all(sha(ROOT / name) == digest for name, digest in (expected | results).items())
    bundle = CHIP / "bundle.sv"
    included = [Path(name) for name in re.findall(r'(?m)^`include "([^"]+)"$', bundle.read_text())]
    assert included and NORMALIZER in included
    for path in included:
        assert expected[str(path.relative_to(ROOT))] == sha(path)
    replacements = {CHIP / LEARNED: learned_layer((CHIP / LEARNED).read_text()),
                    CHIP / LAYER: rewrite((CHIP / LAYER).read_text(), (
                        (".PACKED_FEEDFORWARD_WEIGHTS(PACKED_FEEDFORWARD_WEIGHTS),",
                         ".PACKED_FEEDFORWARD_WEIGHTS(PACKED_FEEDFORWARD_WEIGHTS),\n"
                         "        .PACKED_SIGN_PREDICTOR(PACKED_FEEDFORWARD_WEIGHTS),"),
                    ))}
    old_bench = CHIP / "trained_tb.sv"
    assert expected[str(old_bench.relative_to(ROOT))] == sha(old_bench)
    bench_source = directed_bench(old_bench.read_text())
    packed_source = normalizer(NORMALIZER.read_text())
    output.mkdir()
    for path, code in replacements.items():
        (output / path.name).write_text(code)
    packed = output / f"{PACKED_NORMALIZER}.sv"
    packed.write_text(packed_source)
    rtl = ROOT / "verilog"
    new_sources = [rtl / name for name in ("tri_oracle_packed_sign_fetch.sv", "tri_oracle_outlier_word_codec.sv",
                                          "tri_oracle_compact_outlier_words.sv", "tri_oracle_wide_read_arbiter.sv")]
    new_sources += [PREDICTOR / name for name in ("tri_oracle_packed_outlier_replay.sv", "tri_oracle_ranked_sign_slots.sv",
                                                "tri_oracle_ranked_sign_line_cache.sv")]
    tests = {CHIP / "attention_tb.sv", old_bench}
    output_sources = [output / path.name if path in replacements else path for path in included if path not in tests]
    output_sources.extend([*new_sources, packed])
    build = output / "bundle.sv"
    base_bundle = rewrite(bundle.read_text(), (
        *((f'`include "{path}"\n', "") for path in sorted(tests)),
        *((f'`include "{path}"\n', f'`include "{output / path.name}"\n') for path in replacements),
    ))
    build.write_text(base_bundle + "".join(f'`include "{path}"\n' for path in (*new_sources, packed)))
    bench = output / old_bench.name
    bench.write_text(bench_source)
    paths = {chip, predictor, source, bundle, Path(__file__).resolve(), *included, *output_sources, build, old_bench, bench}
    result = {
        "state": "dual_lane_packed_sign_chip_source_prepared",
        "packed_sign_base_field": "cfg_gate_sign_base",
        "input_sha256": {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)},
    }
    (output / "prepared.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], len(output_sources), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    prepare(parser.parse_args().output)
