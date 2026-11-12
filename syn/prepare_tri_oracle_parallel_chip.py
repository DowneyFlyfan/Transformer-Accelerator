"""Connect two packed weight read lanes to the source chip and compiled clusters."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_packed_tensor import rewrite
from verify_tri_oracle_packed_down_weights import ROOT, sha256


BASE = ROOT / ".cache/physical/wide_weight_loader/paired_chip"
WIDE_PORTS = """  output logic wide_req_valid,
  input logic wide_req_ready,
  output logic [63:0] wide_req_address,
  output logic [5:0] wide_req_length,
  input logic wide_rsp_valid,
  output logic wide_rsp_ready,
  input logic wide_rsp_last,wide_rsp_error,
  input logic [511:0] wide_rsp_data,
"""
AUX_PORTS = WIDE_PORTS.replace("wide_", "aux_")
AUX_NAMES = tuple(re.findall(r"aux_\w+", AUX_PORTS))
AUX_SIGNALS = ", ".join(f".{name}" for name in AUX_NAMES)
AUX_TIED_OFF = (
    ".aux_req_valid(), .aux_req_ready(1'b0), .aux_req_address(), .aux_req_length(), "
    ".aux_rsp_valid(1'b0), .aux_rsp_ready(), .aux_rsp_last(1'b0), .aux_rsp_error(1'b0), .aux_rsp_data('0)"
)


def pass_aux(source):
    connections = "    .wide_req_valid,.wide_req_ready,.wide_req_address,.wide_req_length,"
    return rewrite(source, (
        (WIDE_PORTS, WIDE_PORTS + AUX_PORTS),
        (connections, f"    {AUX_SIGNALS},\n{connections}"),
    ))


def through_tensor_parent(source):
    return rewrite(pass_aux(source), (
        (".wide_rsp_data('0), .*", f".wide_rsp_data('0), {AUX_TIED_OFF}, .*"),
    ))


def tensor(source):
    start = source.index("  logic packed_cfg_valid,")
    stop = source.index("  assign first_cluster", start)
    loader = """  logic [1:0] wide_load_valid;
  logic [1:0][4:0] wide_load_core;
  logic [1:0][9:0] wide_load_addr;
  logic [1:0][31:0] wide_load_enable;
  logic [1:0][1:0] wide_load_group;

  for (genvar lane=0; lane<2; lane++) begin : write_groups
    assign wide_load_group[lane] = {(|wide_load_enable[lane][31:16]),
                                    (|wide_load_enable[lane][31:24]) || (|wide_load_enable[lane][15:8])};
  end
  tri_oracle_parallel_weight_loader packed_loader (
    .clk,.rst_n(owner_rst_n),.cfg_valid(state==PACK_START),.cfg_ready(packed_ready),
    .cfg_paired(paired),.cfg_base(weight_base),.cfg_up_base(up_weight_base),
    .cfg_first_row(channels[15:0]),.cfg_dense_rows(dense_rows),.cfg_feature_words(feature_words),
    .cfg_count(count),.cfg_tile_start(tile_start),.cfg_keep(packed_keep),.cfg_active_words(active_words),
    .req_valid({aux_req_valid,wide_req_valid}),.req_ready({aux_req_ready,wide_req_ready}),
    .req_address({aux_req_address,wide_req_address}),.req_length({aux_req_length,wide_req_length}),
    .rsp_valid({aux_rsp_valid,wide_rsp_valid}),.rsp_ready({aux_rsp_ready,wide_rsp_ready}),
    .rsp_last({aux_rsp_last,wide_rsp_last}),.rsp_error({aux_rsp_error,wide_rsp_error}),
    .load_valid(wide_load_valid),.load_core(wide_load_core),.load_addr(wide_load_addr),
    .load_row_enable(wide_load_enable),.done_valid(packed_done),.done_ready(state==PACK_WAIT),
    .done_error(packed_done_error)
  );

"""
    return rewrite(source[:start] + loader + source[stop:], (
        (WIDE_PORTS, WIDE_PORTS + AUX_PORTS),
        ("""    .clk(clk),.rst_n(backend_rst_n),.load_valid(load_valid || wide_load_valid),
    .load_core(wide_load_valid ? wide_load_core : load_core),
    .load_kind(wide_load_valid ? 2'b00 : load_kind),
    .load_addr(wide_load_valid ? wide_load_addr : load_addr),.load_payload(load_payload),
    .load_row_enable(wide_load_valid ? wide_load_enable : load_row_enable),.load_error(load_error),
    .wide_load_valid,.wide_load_group,.wide_load_payload(wide_rsp_data),""",
         """    .clk(clk),.rst_n(backend_rst_n),.load_valid,.load_core,.load_kind,.load_addr,
    .load_payload,.load_row_enable,.load_error,
    .wide_load_valid,.wide_load_core,.wide_load_addr,.wide_load_group,.wide_load_enable,
    .wide_load_payload({aux_rsp_data,wide_rsp_data}),"""),
    ))


def fabric(source):
    return rewrite(source, (
        ("""    input wire wide_load_valid,
    input wire [1:0] wide_load_group,
    input wire [511:0] wide_load_payload,
""", """    input wire [1:0] wide_load_valid,
    input wire [1:0][4:0] wide_load_core,
    input wire [1:0][9:0] wide_load_addr,
    input wire [1:0][1:0] wide_load_group,
    input wire [1:0][31:0] wide_load_enable,
    input wire [1:0][511:0] wide_load_payload,
"""),
        ("    for(genvar cluster=0;cluster<5;cluster=cluster+1)begin: clusters\n",
         """    for(genvar cluster=0;cluster<5;cluster=cluster+1)begin: clusters
        wire write_lane0 = wide_load_valid[0] && wide_load_core[0][4:2]==3'(cluster);
        wire write_lane1 = wide_load_valid[1] && wide_load_core[1][4:2]==3'(cluster);
        wire wide_write = write_lane0 || write_lane1;
"""),
        ("""            .load_valid(load_valid && load_core[4:2]==3'(cluster)),
            .load_core(load_core[1:0]),.load_kind(load_kind),
            .load_addr(load_addr),.load_payload(load_payload),.load_row_enable(load_row_enable),
            .load_error(load_errors[cluster]),
            .wide_load_valid(wide_load_valid && load_core[4:2]==3'(cluster)),
            .wide_load_group,.wide_load_payload,
""", """            .load_valid(wide_write || (load_valid && load_core[4:2]==3'(cluster))),
            .load_core(wide_write ? wide_load_core[write_lane1][1:0] : load_core[1:0]),
            .load_kind(wide_write ? 2'b00 : load_kind),
            .load_addr(wide_write ? wide_load_addr[write_lane1] : load_addr),.load_payload(load_payload),
            .load_row_enable(wide_write ? wide_load_enable[write_lane1] : load_row_enable),
            .load_error(load_errors[cluster]),
            .wide_load_valid(wide_write),.wide_load_group(wide_load_group[write_lane1]),
            .wide_load_payload(wide_load_payload[write_lane1]),
"""),
    ))


def boundary(source):
    declarations = AUX_PORTS.replace(" logic", "").replace(",\n", ";\n")
    return rewrite(source, (
        ("context_base, req_wide);", f"context_base, req_wide, {', '.join(AUX_NAMES)});"),
        ("  output req_wide;\n", "  output req_wide;\n" + declarations),
        ("    .wide_req_valid,.wide_req_ready,.wide_req_address,.wide_req_length,",
         f"    {AUX_SIGNALS},\n    .wide_req_valid,.wide_req_ready,.wide_req_address,.wide_req_length,"),
    ))


def commands(source):
    return rewrite(source, (
        ("  output logic req_wide,\n", "  output logic req_wide,\n" + AUX_PORTS),
        ("    .req_wide(req_wide)\n", f"    .req_wide(req_wide),\n    {AUX_SIGNALS}\n"),
    ))


def attention(source):
    return rewrite(source, (
        ("    .req_wide(mem_req_wide),", f"    .req_wide(mem_req_wide),\n    {AUX_TIED_OFF},"),
    ))


def bench(source):
    start = source.index("  bit wide_active=")
    stop = source.index("  int wide_branch_beats", start)
    source = source[:start] + """  bit [1:0] wide_active=0,wide_bubble=0,held_wide_req=0;
  logic [1:0][63:0] wide_address;
  int wide_beat[2],wide_length[2],wide_requests=0,wide_beats=0,scalar_down_beats=0;
  logic [1:0][69:0] prior_wide_req;
  wire [1:0] wide_req_valid,wide_rsp_ready,wide_req_ready,wide_rsp_valid,wide_rsp_last,wide_rsp_error;
  wire [1:0][63:0] wide_req_address;
  wire [1:0][5:0] wide_req_length;
  logic [1:0][511:0] wide_rsp_data;
  int simultaneous_responses=0;
  int lane_branch_beats[2][3];
  for (genvar lane=0;lane<2;lane++) begin : memory_lanes
    assign wide_req_ready[lane]=!wide_active[lane] && (cycle+lane)%7>=3;
    assign wide_rsp_valid[lane]=wide_active[lane] && !wide_bubble[lane];
    assign wide_rsp_last[lane]=wide_beat[lane]+1==wide_length[lane];
    assign wide_rsp_error[lane]=lane==FAULT_LANE && inject_fault && !fault_seen && wide_rsp_valid[lane] &&
      (FAULT==2 || (FAULT==3 && wide_address[lane]>=DOWN_BASE+64'(160*INTERMEDIATE)));
  end
""" + source[stop:]
    start = source.index("  always @(wide_address or wide_beat or wide_active)")
    stop = source.index("  wire bus_req_valid", start)
    body = source[start:stop].rstrip()
    body = re.sub(r"\b(wide_address|wide_beat|wide_active|wide_rsp_data)\b", r"\1[lane]", body)
    source = source[:start] + "  for (genvar lane=0;lane<2;lane++) begin : memory_data\n" + body + "\n  end\n\n" + source[stop:]
    start = source.index("  wire bus_req_ready")
    stop = source.index("  always @(posedge clk)", start)
    body = re.sub(
        r"\b(wide_active|wide_req_(?:valid|ready|address|length)|wide_rsp_(?:valid|ready|last|error|data))\b",
        r"\1[0]", source[start:stop],
    )
    source = source[:start] + body + source[stop:]
    start = source.index("    if(wide_active && wide_bubble)")
    stop = source.index("    if(read_active && read_bubble)", start)
    body = re.sub(
        r"\b(wide_active|wide_bubble|held_wide_req|prior_wide_req|wide_address|wide_beat|wide_length|"
        r"wide_req_(?:valid|ready|address|length)|wide_rsp_(?:valid|ready|last|error))\b",
        r"\1[lane]", source[start:stop],
    )
    body = rewrite(body, (
        ("read_active || req_valid ||", "(lane==0 && (read_active || req_valid)) ||"),
        ("      wide_beats++;", """      int branch;
      branch=weight_branch(wide_address[lane]);
      wide_beats++;
      lane_branch_beats[lane][branch]++;"""),
        ("wide_branch_beats[weight_branch(wide_address[lane])]++", "wide_branch_beats[branch]++"),
    ))
    source = (source[:start] +
              "    if (&(wide_rsp_valid & wide_rsp_ready)) simultaneous_responses++;\n"
              "    for (int lane=0; lane<2; lane++) begin\n" +
              "".join(f"  {line}" for line in body.splitlines(keepends=True)) +
              "    end\n" + source[stop:])
    aux = ", ".join(f".{name}({name.replace('aux_', 'wide_')}[1])" for name in AUX_NAMES)
    return rewrite(source, (
        ("  parameter int FAULT=", "  parameter int FAULT_LANE=0;\n  parameter int FAULT="),
        ("    .req_wide(bus_req_wide),", f"    .req_wide(bus_req_wide),\n    {aux},"),
        ("read_active && wide_active", "read_active && wide_active[0]"),
        ("if(wide_active || (PACKED && weight_branch", "if(wide_active[0] || (PACKED && weight_branch"),
        ("if(wide_active || (PACKED && (FAULT==2", "if((|wide_active) || (PACKED && (FAULT==2"),
        ("if(wide_active || (PACKED && (wide_requests", "if((|wide_active) || (PACKED && (wide_requests"),
        ("      wide_requests=0;wide_beats=0;scalar_down_beats=0;",
         """      wide_requests=0;wide_beats=0;scalar_down_beats=0;simultaneous_responses=0;
      foreach(lane_branch_beats[lane,branch])lane_branch_beats[lane][branch]=0;"""),
        ('    $display("PACKED_PAIR_BRANCHES', """    if (PACKED && simultaneous_responses==0) $fatal(1,"PARALLEL_CHIP_NO_DUAL_RESPONSE");
    $display("PARALLEL_CHIP_READS simultaneous_responses=%0d",simultaneous_responses);
    for (int lane=0;lane<2;lane++)begin
      for (int branch=0;branch<3;branch++)
        if (PACKED != (lane_branch_beats[lane][branch]>0)) $fatal(1,"PARALLEL_CHIP_MISSING_BRANCH");
      $display("PARALLEL_CHIP_BRANCHES lane=%0d gate=%0d up=%0d down=%0d",
        lane,lane_branch_beats[lane][0],lane_branch_beats[lane][1],lane_branch_beats[lane][2]);
    end
    $display("PACKED_PAIR_BRANCHES"""),
    ))


def prepare(output):
    evidence_path = ROOT / "records/wac_paired_chip_feedforward_result.json"
    evidence = json.loads(evidence_path.read_text())
    prepared_path = BASE / "prepared.json"
    assert evidence["evidence_sha256"][str(prepared_path.relative_to(ROOT))] == sha256(prepared_path)
    pins = json.loads(prepared_path.read_text())["input_sha256"]
    assert all(sha256(ROOT / path) == expected for path, expected in pins.items())
    bundle_path = BASE / "bundle.sv"
    bundle = bundle_path.read_text()
    transforms = {
        "tri_oracle_batched_tensor390.sv": tensor,
        "tri_oracle_compute_fabric.sv": fabric,
        "tri_oracle_batched_shared392.sv": pass_aux,
        "tri_oracle_batched_frame393.sv": through_tensor_parent,
        "tri_oracle_batched_learned406.sv": through_tensor_parent,
        "tri_oracle_shared_layer437.sv": lambda source: rewrite(source, ((WIDE_PORTS, WIDE_PORTS + AUX_PORTS),)),
        "tri_oracle_chip_command_layer.sv": commands,
        "boundary.sv": boundary,
        "attention_tb.sv": attention,
        "trained_tb.sv": bench,
    }
    includes = tuple(Path(name) for name in re.findall(r'(?m)^`include "([^"]+)"$', bundle))
    sources = [path for path in includes if path.name in transforms]
    assert len(sources) == len(transforms) and {path.name for path in sources} == transforms.keys()
    generated = {path: transforms[path.name](path.read_text()) for path in sources}
    output.mkdir()
    for path, source in generated.items():
        target = output / path.name
        target.write_text(source)
        bundle = rewrite(bundle, ((f'`include "{path}"', f'`include "{target}"'),))
    loader = ROOT / "verilog/tri_oracle_parallel_weight_loader.sv"
    (output / "bundle.sv").write_text(bundle + f'`include "{loader}"\n')
    files = (prepared_path, evidence_path, loader, Path(__file__), *sorted(output.iterdir()))
    (output / "prepared.json").write_text(json.dumps({
        "state": "source_chip_connects_two_packed_read_lanes_to_compiled_clusters",
        "input_sha256": pins | {str(path.relative_to(ROOT)): sha256(path) for path in files},
    }, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output.resolve())
