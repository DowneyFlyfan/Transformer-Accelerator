"""Connect the packed down-projection port through the context decoder."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_packed_tensor import adapter, fabric, rewrite, tensor
from verify_tri_oracle_packed_down_weights import ROOT, sha256


PHYSICAL = ROOT / ".cache/physical"
DECODER = PHYSICAL / "context_external/shared_decoder"
TRAINED = PHYSICAL / "shared_memory_layer_boundary/mapped_trained_replay"
WIDE_PORTS = """  output logic wide_req_valid,
  input logic wide_req_ready,
  output logic [63:0] wide_req_address,
  output logic [5:0] wide_req_length,
  input logic wide_rsp_valid,
  output logic wide_rsp_ready,
  input logic wide_rsp_last,wide_rsp_error,
  input logic [511:0] wide_rsp_data,
"""
WIDE_CONNECTIONS = """    .wide_req_valid,.wide_req_ready,.wide_req_address,.wide_req_length,
    .wide_rsp_valid,.wide_rsp_ready,.wide_rsp_last,.wide_rsp_error,.wide_rsp_data,
"""
WIDE_TIED_OFF = (
    ".wide_req_valid(), .wide_req_ready(1'b0), .wide_req_address(), .wide_req_length(), "
    ".wide_rsp_valid(1'b0), .wide_rsp_ready(), .wide_rsp_last(1'b0), "
    ".wide_rsp_error(1'b0), .wide_rsp_data('0), "
)
PACKED_PARAM = "  parameter bit PACKED_DOWN_WEIGHTS=0,\n"
PACKED_SETTING = "    .PACKED_DOWN_WEIGHTS(PACKED_DOWN_WEIGHTS),\n"


def wrapper(source, name, changes):
    declaration = f"module {name} #(\n"
    legacy, implementation = source.split(declaration)
    legacy = rewrite(legacy, ((".head_response(), .*", ".head_response(), " + WIDE_TIED_OFF + ".*"),))
    return legacy + declaration + PACKED_PARAM + rewrite(implementation, changes)


def shared_tensor(source):
    return rewrite(source, (
        ("input logic clk,rst_n,cfg_valid,cfg_paired,", "input logic clk,rst_n,cfg_valid,cfg_paired,cfg_packed_weights,"),
        ("  input logic [63:0] rsp_data,\n", "  input logic [63:0] rsp_data,\n" + WIDE_PORTS),
        (".cfg_paired(cfg_paired),", ".cfg_paired(cfg_paired),.cfg_packed_weights,"),
        ("    .req_valid(req_valid),", WIDE_CONNECTIONS + "    .req_valid(req_valid),"),
    ))


def frame(source):
    return wrapper(source, "tri_oracle_batched_frame437", (
        ("  input logic [63:0] rsp_data,\n", "  input logic [63:0] rsp_data,\n" + WIDE_PORTS),
        ("      cfg_intermediate_base[2:0]!=0", """      (PACKED_DOWN_WEIGHTS && (cfg_output_features[2:0]!=0 || cfg_down_base[5:0]!=0)) ||
      cfg_intermediate_base[2:0]!=0"""),
        ("    .cfg_ready(compute_ready),.cfg_paired(!attention_selected && launch_paired),",
         """    .cfg_ready(compute_ready),.cfg_paired(!attention_selected && launch_paired),
    .cfg_packed_weights(PACKED_DOWN_WEIGHTS && !attention_selected && state==DOWN_LAUNCH),"""),
        ("    .req_valid(req_valid),", WIDE_CONNECTIONS + "    .req_valid(req_valid),"),
    ))


def learned(source):
    return wrapper(source, "tri_oracle_batched_learned437", (
        ("    input logic [63:0] rsp_data,\n", "    input logic [63:0] rsp_data,\n" + WIDE_PORTS),
        ("            cfg_down_base[2:0] != 0", """            (PACKED_DOWN_WEIGHTS && (cfg_output_features[2:0]!=0 || cfg_down_base[5:0]!=0)) ||
            cfg_down_base[2:0] != 0"""),
        ("    tri_oracle_batched_frame437 #(\n", "    tri_oracle_batched_frame437 #(\n" + PACKED_SETTING),
        ("        .req_valid(compute_req_valid),", WIDE_CONNECTIONS + "        .req_valid(compute_req_valid),"),
    ))


def layer(source):
    return rewrite(source, (
        ("module tri_oracle_shared_layer437 #(\n", "module tri_oracle_shared_layer437 #(\n" + PACKED_PARAM),
        ("    input logic [63:0] rsp_data,\n", "    input logic [63:0] rsp_data,\n" + WIDE_PORTS),
        ("    tri_oracle_batched_learned437 #(\n", "    tri_oracle_batched_learned437 #(\n" + PACKED_SETTING),
    ))


def boundary(source):
    ports = [port for line in WIDE_PORTS.splitlines() for port in line.split()[-1].rstrip(",").split(",")]
    assert len(ports) == 9
    declarations = WIDE_PORTS.replace(" logic ", " ")
    declarations = "".join(line.removesuffix(",") + ";\n" for line in declarations.splitlines())
    return rewrite(source, (
        ("module tri_oracle_shared_memory_layer (", "module tri_oracle_shared_memory_layer #(\n" + PACKED_PARAM.rstrip(",\n") + "\n) ("),
        ("value_read_base, context_base);", "value_read_base, context_base, " + ", ".join(ports) + ");"),
        ("  input [63:0] context_base;\n", "  input [63:0] context_base;\n" + declarations),
        (".PERSIST_LAYER_CONTEXT(1)) layer (", ".PERSIST_LAYER_CONTEXT(1), .PACKED_DOWN_WEIGHTS(PACKED_DOWN_WEIGHTS)) layer (\n"
         + WIDE_CONNECTIONS.rstrip("\n")),
    ))


def trained_bench(source):
    return rewrite(source, (
        ("OUTPUTS=173", "OUTPUTS=168"),
        ("  parameter bit TRAINED=0;", "  parameter bit TRAINED=0, PACKED=1;"),
        ("  tri_oracle_shared_memory_layer dut (", """  bit wide_active=0,wide_bubble=0,held_wide_req=0;
  logic [63:0] wide_address;
  int wide_beat=0,wide_length=0,wide_requests=0,wide_beats=0,scalar_down_beats=0;
  logic [69:0] prior_wide_req;
  wire wide_req_valid,wide_rsp_ready;
  wire [63:0] wide_req_address;
  wire [5:0] wide_req_length;
  wire wide_req_ready=!wide_active && cycle%7>=3;
  wire wide_rsp_valid=wide_active && !wide_bubble;
  wire wide_rsp_last=wide_beat+1==wide_length;
  wire wide_rsp_error=inject_fault && !fault_seen && wide_rsp_valid &&
    (FAULT==2 || (FAULT==3 && wide_address>=DOWN_BASE+64'(160*INTERMEDIATE)));
  logic [511:0] wide_rsp_data;

  always @(wide_address or wide_beat or wide_active) begin : packed_weight
    int offset,first_row,feature;
    wide_rsp_data='0;
    if(wide_active)begin
      offset=int'(wide_address-DOWN_BASE)+wide_beat*64;
      first_row=8*(offset/(8*INTERMEDIATE));
      feature=(offset%(8*INTERMEDIATE))/8;
      for(int row=0;row<8;row++)
        for(int byte_index=0;byte_index<8;byte_index++)
          wide_rsp_data[row*64+byte_index*8+:8]=8'(down_weight(first_row+row,feature+byte_index));
    end
  end

  tri_oracle_shared_memory_layer #(.PACKED_DOWN_WEIGHTS(PACKED)) dut (
""" + WIDE_CONNECTIONS.rstrip(",\n") + ","),
        ("    .value_read_base(64'd0)\n", "    .value_read_base(64'd0), .context_base(64'h30000000)\n"),
        ("    if(read_active && read_bubble)read_bubble<=0;", """    if(wide_active && wide_bubble)wide_bubble<=0;
    if(held_wide_req && (!wide_req_valid || {wide_req_address,wide_req_length}!==prior_wide_req))
      $fatal(1,"PACKED_DECODER_REQUEST_CHANGED");
    held_wide_req=wide_req_valid && !wide_req_ready;
    if(held_wide_req)prior_wide_req={wide_req_address,wide_req_length};
    if(wide_req_valid && wide_req_ready)begin
      if(!PACKED || read_active || req_valid || write_active || write_response ||
         write_bytes!=TOKENS*INTERMEDIATE || !committed[TOKENS*INTERMEDIATE-1] ||
         wide_req_length==0 || wide_req_length>32 || wide_req_address[5:0]!=0 ||
         wide_req_address<DOWN_BASE ||
         wide_req_address+64'(wide_req_length)*64>DOWN_BASE+64'(OUTPUTS*INTERMEDIATE) ||
         int'(wide_req_address-DOWN_BASE)%(8*INTERMEDIATE)+int'(wide_req_length)*64>8*INTERMEDIATE)
        $fatal(1,"PACKED_DECODER_REQUEST address=%h",wide_req_address);
      wide_active<=1;wide_address<=wide_req_address;wide_beat<=0;wide_length<=int'(wide_req_length);
      wide_requests++;
    end
    if(wide_rsp_valid && wide_rsp_ready)begin
      wide_beats++;
      if(wide_rsp_error)fault_seen<=1;
      if(wide_rsp_last)wide_active<=0;
      else begin wide_beat<=wide_beat+1;wide_bubble<=cycle%5==0;end
    end
    if(read_active && read_bubble)read_bubble<=0;"""),
        ("      if(read_active || req_length==0", """      if(wide_active || (PACKED && req_address>=DOWN_BASE &&
         req_address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE)))$fatal(1,"PACKED_DECODER_SCALAR_OWNERSHIP");
      if(read_active || req_length==0"""),
        ("current=read_address+64'(read_beat*8);read_beats++;",
         """current=read_address+64'(read_beat*8);read_beats++;
      if(current>=DOWN_BASE && current<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE))scalar_down_beats++;"""),
        ("    $display(\"BATCH408_TRAINED_SCALAR_TRANSPORT_PASS\");", """    if(wide_active || (PACKED && (wide_requests==0 || wide_beats==0 || scalar_down_beats!=0)) ||
       (!PACKED && (wide_requests!=0 || wide_beats!=0 || scalar_down_beats==0)))
      $fatal(1,"PACKED_DECODER_FINAL_INVENTORY");
    $display("PACKED_DECODER_PASS packed=%0d trained=%0d outputs=%0d wide_bursts=%0d wide_beats=%0d scalar_down_beats=%0d cycles=%0d",
      PACKED,TRAINED,TOKENS*OUTPUTS,wide_requests,wide_beats,scalar_down_beats,cycle);"""),
        ("      inject_fault=0;seen=0;read_requests=0;read_beats=0;write_requests=0;write_bytes=0;",
         """      if(wide_active || (PACKED && (FAULT==2 || FAULT==3) && wide_beats==0))
        $fatal(1,"PACKED_DECODER_ABORT_WITH_PENDING_BURST");
      inject_fault=0;seen=0;read_requests=0;read_beats=0;write_requests=0;write_bytes=0;
      wide_requests=0;wide_beats=0;scalar_down_beats=0;"""),
    ))


def prepare(output):
    baseline = DECODER / "bundle.sv"
    inputs = DECODER / "inputs.json"
    pins = json.loads(inputs.read_text())
    linked = DECODER / "linked_context_decoder_complete_attention/receipt.json"
    assert json.loads(linked.read_text())["input_sha256"][str(inputs)] == sha256(inputs)
    bundle = baseline.read_text()
    includes = tuple(Path(item) for item in re.findall(r'(?m)^`include "([^"]+)"$', bundle))
    assert len(includes) == len(set(includes))
    for path in (baseline, *includes):
        assert sha256(path) == pins[str(path)], path
    transformations = {
        "tri_oracle_batched_tensor390.sv": tensor,
        "tri_oracle_compute_fabric.sv": fabric,
        "cluster_adapter.sv": adapter,
        "tri_oracle_batched_shared392.sv": shared_tensor,
        "tri_oracle_batched_frame393.sv": frame,
        "tri_oracle_batched_learned406.sv": learned,
        "tri_oracle_shared_layer437.sv": layer,
        "boundary.sv": boundary,
    }
    assert all(sum(path.name == name for path in includes) == 1 for name in transformations)
    output.mkdir()
    for path in includes:
        transform = transformations.get(path.name)
        if transform:
            variant = output / path.name
            variant.write_text(transform(path.read_text()))
            bundle = rewrite(bundle, ((f'`include "{path}"', f'`include "{variant}"'),))

    reference = ROOT / "records/wac_shared_memory_layer_trained_result.json"
    trained_receipt = TRAINED / "receipt.json"
    assert json.loads(reference.read_text())["evidence_sha256"][str(trained_receipt.relative_to(ROOT))] == sha256(trained_receipt)
    reference_bench = TRAINED / "trained_tb.sv"
    assert json.loads(trained_receipt.read_text())["input_sha256"][str(reference_bench)] == sha256(reference_bench)
    bench = output / "trained_tb.sv"
    bench.write_text(trained_bench(reference_bench.read_text()))
    support = [ROOT / "verilog" / (name + ".sv") for name in (
        "tri_oracle_wide_weight_loader", "tri_oracle_packed_weight_schedule",
    )]
    (output / "bundle.sv").write_text(bundle + "".join(f'`include "{path}"\n' for path in (*support, bench)))
    evidence = (baseline, inputs, linked, *includes, reference, trained_receipt, reference_bench,
                *support, *output.iterdir(), Path(__file__),
                Path(__file__).with_name("prepare_tri_oracle_packed_tensor.py"))
    result = {"state": "packed_weight_port_connected_to_context_decoder",
              "input_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in evidence}}
    (output / "prepared.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output.resolve())
