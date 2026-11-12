"""Expose a shared narrow/packed read port on the context decoder."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_packed_decoder import WIDE_CONNECTIONS, WIDE_PORTS
from prepare_tri_oracle_packed_tensor import rewrite
from verify_tri_oracle_packed_down_weights import ROOT, sha256


NARROW_PORTS = (
    "req_valid", "req_ready", "req_address", "req_length",
    "rsp_valid", "rsp_ready", "rsp_last", "rsp_error", "rsp_data",
)
READ_MUX = """  tri_oracle_packed_read_mux external_reads (
    .clk, .rst_n,
    .narrow_req_valid(narrow_req_valid), .narrow_req_ready(narrow_req_ready),
    .narrow_req_address(narrow_req_address), .narrow_req_length(narrow_req_length),
    .narrow_rsp_valid(narrow_rsp_valid), .narrow_rsp_ready(narrow_rsp_ready),
    .narrow_rsp_last(narrow_rsp_last), .narrow_rsp_error(narrow_rsp_error), .narrow_rsp_data(narrow_rsp_data),
    .wide_req_valid, .wide_req_ready, .wide_req_address, .wide_req_length,
    .wide_rsp_valid, .wide_rsp_ready, .wide_rsp_last, .wide_rsp_error, .wide_rsp_data,
    .mem_req_valid(req_valid), .mem_req_ready(req_ready), .mem_req_wide(req_wide),
    .mem_req_address(req_address), .mem_req_length(req_length),
    .mem_rsp_valid(rsp_valid), .mem_rsp_ready(rsp_ready), .mem_rsp_last(rsp_last),
    .mem_rsp_error(rsp_error), .mem_rsp_data(rsp_data)
  );
"""


def unified_boundary(source):
    names = [port for line in WIDE_PORTS.splitlines() for port in line.split()[-1].rstrip(",").split(",")]
    declarations = WIDE_PORTS.replace(" logic ", " ")
    declarations = "".join(line.removesuffix(",") + ";\n" for line in declarations.splitlines())
    header, body = source.split(declarations)
    header = rewrite(header, (
        ("context_base, " + ", ".join(names) + ");", "context_base, req_wide);"),
        ("  output req_valid;\n", "  output req_valid;\n  output req_wide;\n"),
        ("  output [4:0] req_length;", "  output [5:0] req_length;"),
        ("  input [63:0] rsp_data;", "  input [511:0] rsp_data;"),
    ))
    # The former narrow external pins are now internal nets. Explicit named
    # formals such as .rsp_data(layer_rsp_data) retain their original spelling.
    pattern = re.compile(r"(?<!\.)\b(" + "|".join(NARROW_PORTS) + r")\b")
    body = pattern.sub(lambda signal: "narrow_" + signal[0], body)
    wires = re.sub(r"\b(?:input|output)\b", "wire", declarations)
    narrow_wires = """  wire narrow_req_valid, narrow_req_ready;
  wire [63:0] narrow_req_address;
  wire [4:0] narrow_req_length;
  wire narrow_rsp_valid, narrow_rsp_ready, narrow_rsp_last, narrow_rsp_error;
  wire [63:0] narrow_rsp_data;
"""
    return header + wires + narrow_wires + rewrite(body, (("endmodule", READ_MUX + "endmodule"),))


def unified_bench(source):
    prefix = """  wire bus_req_valid,bus_req_wide,bus_rsp_ready;
  wire [63:0] bus_req_address;
  wire [5:0] bus_req_length;
  wire bus_req_ready = bus_req_wide ? wide_req_ready : req_ready;
  wire bus_rsp_valid = rsp_valid || wide_rsp_valid;
  wire bus_rsp_last = wide_active ? wide_rsp_last : rsp_last;
  wire bus_rsp_error = wide_active ? wide_rsp_error : rsp_error;
  wire [511:0] bus_rsp_data = wide_active ? wide_rsp_data : {448'b0,rsp_data};
  assign req_valid = bus_req_valid && !bus_req_wide;
  assign wide_req_valid = bus_req_valid && bus_req_wide;
  assign req_address = bus_req_address;
  assign wide_req_address = bus_req_address;
  assign req_length = bus_req_length[4:0];
  assign wide_req_length = bus_req_length;
  assign rsp_ready = bus_rsp_ready && read_active;
  assign wide_rsp_ready = bus_rsp_ready && wide_active;

  always @(posedge clk) if (rst_n) begin
    if (read_active && wide_active) $fatal(1,"UNIFIED_READ_MULTIPLE_OWNERS");
    if (bus_req_valid && !bus_req_wide && bus_req_length[5])
      $fatal(1,"UNIFIED_READ_NARROW_LENGTH");
  end

"""
    instance = "  tri_oracle_shared_memory_layer #(.PACKED_DOWN_WEIGHTS(PACKED)) dut (\n"
    changes = [
        (instance + WIDE_CONNECTIONS, prefix + instance + "    .req_wide(bus_req_wide),\n"),
    ]
    changes.extend((f"    .{port}({port}),\n", f"    .{port}(bus_{port}),\n") for port in NARROW_PORTS)
    return rewrite(source, changes)


def prepare(source, output):
    previous = ROOT / "records/wac_packed_decoder_feedforward_result.json"
    report = json.loads(previous.read_text())
    assert report["state"] == "packed_and_scalar_decoder_feedforward_matched_directed_reference"
    pins = report["evidence_sha256"]
    prepared = source / "prepared.json"
    boundary = source / "boundary.sv"
    bench = source / "trained_tb.sv"
    bundle = source / "bundle.sv"
    for path in (prepared, boundary, bench, bundle):
        assert sha256(path) == pins[str(path.relative_to(ROOT))], path
    inherited = json.loads(prepared.read_text())["input_sha256"]
    assert all(sha256(ROOT / path) == expected for path, expected in inherited.items())

    output.mkdir()
    (output / boundary.name).write_text(unified_boundary(boundary.read_text()))
    (output / bench.name).write_text(unified_bench(bench.read_text()))
    candidate = rewrite(bundle.read_text(), (
        (f'`include "{boundary}"', f'`include "{output / boundary.name}"'),
        (f'`include "{bench}"', f'`include "{output / bench.name}"'),
    ))
    context_record = ROOT / "records/wac_shared_context_transport_result.json"
    context_source = ROOT / ".cache/physical/context_external/shared_transport/tri_oracle_context_memory_fabric.sv"
    context_pins = json.loads(context_record.read_text())["evidence_sha256"]
    assert context_pins[str(context_source.relative_to(ROOT))] == sha256(context_source)
    # The decoder includes the mapped context fabric. Reuse its source owner
    # for the new port without also compiling a second context fabric.
    owner = output / "tri_oracle_scalar_request_owner.sv"
    modules = re.findall(r"(?ms)^module tri_oracle_scalar_request_owner\s*\(.*?^endmodule\b",
                         context_source.read_text())
    implementation, = modules
    owner.write_text("`timescale 1ns/1ps\n" + implementation + "\n")
    mux = ROOT / "verilog/tri_oracle_packed_read_mux.sv"
    (output / bundle.name).write_text(candidate + f'`include "{owner}"\n`include "{mux}"\n')
    evidence = {str(path.relative_to(ROOT)): sha256(path)
                for path in (previous, prepared, context_record, context_source, mux,
                             Path(__file__), *sorted(output.iterdir()))}
    (output / prepared.name).write_text(json.dumps({
        "state": "packed_decoder_unified_read_port_prepared",
        "input_sha256": inherited | evidence,
    }, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.source.resolve(), args.output.resolve())
