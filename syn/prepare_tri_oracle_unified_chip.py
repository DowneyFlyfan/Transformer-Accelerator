"""Connect the mapped command controller to the unified-read decoder."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_chip_command_layer import (
    HOST, LAYER, OPERATIONS, TOP, WIRES, connect, declaration, declared_ports, instance,
)
from prepare_tri_oracle_packed_tensor import rewrite
from verify_tri_oracle_packed_down_weights import ROOT, sha256


PHYSICAL = ROOT / ".cache/physical"
DECODER = PHYSICAL / "context_external/shared_decoder"
REFERENCE = DECODER / "chip_command_context_source"
DISPATCH = PHYSICAL / "chip_dispatch/mapped_flat/netlist.v"
PACKED_PARAM = " #(.PACKED_DOWN_WEIGHTS(PACKED_DOWN_WEIGHTS))"


def chip_wrapper(source, descriptors):
    parameter = " #(\n  parameter bit PACKED_DOWN_WEIGHTS=0\n)"
    ports = declared_ports(rewrite(source, ((f"module {LAYER}{parameter}", f"module {LAYER}"),)))
    external, connections, actual, tag_defaults = connect(ports)
    assert json.loads(json.dumps(actual)) == descriptors
    assert external["req_wide"] == ("output", 1)
    assert external["req_length"] == ("output", 6)
    assert external["rsp_data"] == ("input", 512)
    assert not any(name.startswith("wide_") for name in external)
    parameters = " #(\n  parameter bit PACKED_DOWN_WEIGHTS=1\n)"
    header = ",\n".join(declaration(name, shape) for name, shape in external.items())
    wires = "".join(f"  logic {shape} {name};\n" for name, shape in WIRES.items())
    control = {name: name for name in ("clk", "rst_n", *HOST, *WIRES)}
    code = (f"`timescale 1ns/1ps\nmodule {TOP}{parameters} (\n{header}\n);\n"
            + wires + "".join(tag_defaults) + instance("tri_oracle_chip_dispatch", "dispatch", control)
            + instance(LAYER + PACKED_PARAM, "layer", connections) + "endmodule\n")
    return code, external


def feedforward_bench(source, descriptor, external):
    pattern = re.compile(rf"(?ms)^  {LAYER} #\(\.PACKED_DOWN_WEIGHTS\(PACKED\)\) dut \(\n(.*?)^  \);")
    block, = pattern.finditer(source)
    ports = re.findall(r"\.(\w+)\(([^()]*)\)", block[1])
    assert re.sub(r"\s|,", "", block[1]) == "".join(f".{name}({value})".replace(" ", "")
                                                   for name, value in ports)
    names = dict(ports)
    assert len(names) == len(ports)
    controlled = {name for _, request, completion, tags, fields in OPERATIONS
                  for name in (*request, *completion, *tags, *fields)}
    assert controlled <= names.keys()
    assert all(names[name] == name for name in ("cfg_tag", *descriptor["fields"]))
    host = {
        "command_valid": "command_valid", "command_ready": "cfg_ready", "command_opcode": "3'd0",
        "command_tag": "cfg_tag", "payload_valid": "payload_valid", "payload_ready": "payload_ready",
        "payload_last": "payload_last", "payload_data": "payload_data", "response_valid": "done_valid",
        "response_ready": "done_ready", "response_error": "done_error", "response_opcode": "response_opcode",
        "response_tag": "done_tag",
    }
    kept = {name: value for name, value in ports if name not in controlled}
    connections = kept | host
    assert connections.keys() == external.keys()
    generated = instance(TOP + " #(.PACKED_DOWN_WEIGHTS(PACKED))", "dut", connections).rstrip()
    source = (source[:block.start()] + generated + source[block.end():]).replace("dut.layer", "dut.layer.layer")

    words = descriptor["words"]
    assert descriptor["opcode"] == 0 and words == 15 and descriptor["payload_bits"] == 950
    fields = ",".join(reversed(descriptor["fields"]))
    source = source.replace("32'h39300001", "expected_frame_tag")
    return rewrite(source, (
        ("  logic rst_n=0,cfg_valid=0,done_ready=0;", """  logic rst_n=0,done_ready=0;
  logic command_valid=0,payload_valid=0,payload_last=0,loading_command=0;
  logic [63:0] payload_data;
  logic [31:0] expected_frame_tag;
  wire payload_ready;
  wire [2:0] response_opcode;
  int command_count=0,response_count=0;"""),
        ("  task automatic configure;", "  task automatic configure;\n    logic [959:0] descriptor;"),
        ("cfg_tag=expected_frame_tag;", """cfg_tag=inject_fault ? 32'h3930dead : 32'h39300001;
    expected_frame_tag=cfg_tag;"""),
        ("""    cfg_valid=1;@(posedge clk);if(!cfg_ready)$fatal(1,"BATCH408_CONFIG_NOT_ACCEPTED");
    @(negedge clk);cfg_valid=0;cfg_tag='1;""", f"""    descriptor=960'({{{fields}}});
    loading_command=1;command_valid=1;
    @(posedge clk);if(cfg_ready!==1'b1)$fatal(1,"UNIFIED_CHIP_FEEDFORWARD_HEADER");
    @(negedge clk);command_valid=0;
    for(int word=0;word<{words};word++)begin
      payload_valid=1;payload_last=(word=={words-1});payload_data=descriptor[word*64+:64];
      @(posedge clk);if(payload_ready!==1'b1)$fatal(1,"UNIFIED_CHIP_FEEDFORWARD_PAYLOAD word=%0d",word);
      @(negedge clk);
    end
    payload_valid=0;payload_last=0;payload_data='x;loading_command=0;
    @(posedge clk);
    if(dut.layer_command_valid!==6'b000001 || dut.layer_command_ready[0]!==1'b1 ||
       dut.layer_command_tag!==cfg_tag || dut.layer_command_payload[959:0]!==descriptor)
      $fatal(1,"UNIFIED_CHIP_FEEDFORWARD_LOWER_ISSUE");
    command_count++;
    @(negedge clk);cfg_tag='1;"""),
        ("    cycle<=cycle+1;", """    if(!loading_command) cycle<=cycle+1;
    if(done_valid && (response_opcode!==3'd0 || done_tag!==expected_frame_tag || cfg_ready!==1'b0))
      $fatal(1,"UNIFIED_CHIP_FEEDFORWARD_COMPLETION_OWNERSHIP");
    if(done_valid && done_ready)begin
      response_count++;
      $display("UNIFIED_CHIP_FEEDFORWARD_RESPONSE tag=%h error=%0d",done_tag,done_error);
    end"""),
        ('    $fdisplay(progress_file,"BATCH408_DONE");', """    if(command_count!==(FAULT==0 ? 1 : 2) || response_count!==command_count || !cfg_ready)
      $fatal(1,"UNIFIED_CHIP_FEEDFORWARD_COMMAND_COUNT");
    $display("UNIFIED_CHIP_FEEDFORWARD_PASS descriptor_words=15 commands=%0d responses=%0d",command_count,response_count);
    $fdisplay(progress_file,"BATCH408_DONE");"""),
    ))


def attention_bench(source):
    return rewrite(source, (
        (f"    {TOP} dut (", f"""    wire mem_req_wide;
    wire [5:0] unified_req_length;
    assign mem_req_length=unified_req_length[4:0];
    always @(posedge clk) if(rst_n && mem_req_valid &&
      (mem_req_wide!==1'b0 || unified_req_length[5]!==1'b0))
        $fatal(1,"UNIFIED_CHIP_ATTENTION_READ_WIDTH");
    {TOP} dut (
    .req_wide(mem_req_wide),"""),
        ("    .req_length(mem_req_length),", "    .req_length(unified_req_length),"),
        ("    .rsp_data(mem_rsp_data),", "    .rsp_data({448'b0,mem_rsp_data}),"),
    ))


def prepare(source, output):
    verified = ROOT / "records/wac_unified_decoder_read_result.json"
    verified_pins = json.loads(verified.read_text())["evidence_sha256"]
    prepared = source / "prepared.json"
    source_files = (prepared, source / "boundary.sv", source / "bundle.sv", source / "trained_tb.sv")
    for path in source_files:
        assert verified_pins[str(path.relative_to(ROOT))] == sha256(path)
    pins = json.loads(prepared.read_text())["input_sha256"]
    assert all(sha256(ROOT / name) == expected for name, expected in pins.items())

    ref_manifest = REFERENCE / "prepared.json"
    ref = json.loads(ref_manifest.read_text())
    chip_attn = DECODER / "chip_command_context_full_source/receipt.json"
    chip_proof = json.loads(chip_attn.read_text())
    assert chip_proof["state"] == "mapped_chip_controller_passed_full_source_context_attention_replay"
    assert chip_proof["replay"]["native_exit_status"] == 0
    ref_bench = REFERENCE / "attention_tb.sv"
    old_bench = DECODER / "attention_tb.sv"
    for path in (DISPATCH, ref_bench):
        assert chip_proof["input_sha256"][str(path)] == ref["input_sha256"][str(path)] == sha256(path)
    assert chip_proof["controller_sha256"] == sha256(DISPATCH)
    code, external = chip_wrapper((source / "boundary.sv").read_text(), ref["operations"])

    output.mkdir()
    wrapper = output / f"{TOP}.sv"
    feedforward = output / "trained_tb.sv"
    attention = output / "attention_tb.sv"
    wrapper.write_text(code)
    feedforward.write_text(feedforward_bench((source / "trained_tb.sv").read_text(), ref["operations"][0], external))
    attention.write_text(attention_bench(ref_bench.read_text()))
    bundle = rewrite((source / "bundle.sv").read_text(), (
        (f'`include "{source / "trained_tb.sv"}"', f'`include "{feedforward}"'),
        (f'`include "{old_bench}"', f'`include "{attention}"'),
    ))
    (output / "bundle.sv").write_text(bundle + "".join(f'`include "{path}"\n' for path in (DISPATCH, wrapper)))
    evidence = (verified, *source_files, ref_manifest, ref_bench, chip_attn, DISPATCH,
                *output.iterdir(), Path(__file__), Path(__file__).with_name("prepare_tri_oracle_chip_command_layer.py"))
    result = {
        "state": "unified_read_decoder_connected_to_mapped_chip_commands",
        "controller_sha256": sha256(DISPATCH),
        "external_signals": sum(width for _, width in external.values()),
        "operations": ref["operations"],
        "input_sha256": pins | {str(path.relative_to(ROOT)): sha256(path) for path in evidence},
    }
    (output / "prepared.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.source.resolve(), args.output.resolve())
