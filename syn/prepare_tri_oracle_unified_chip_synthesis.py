"""Prepare a synthesis bundle that preserves the mapped banks and attention logic."""

import argparse
from hashlib import sha256 as digest_bytes
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_wac_parent_hdl_export import declarations
from prepare_tri_oracle_chip_command_layer import TOP
from prepare_tri_oracle_unified_chip import DECODER, DISPATCH, PHYSICAL, ROOT
from verify_tri_oracle_unified_chip_inventory import CHIP, REFERENCE, pin, verify


BASELINE = DECODER / "linked_context_decoder_complete_attention"
STD_CELL = PHYSICAL / "library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib"
CONSTRAINT_TEMPLATE = DECODER / "mapped_context_shell/map.tcl"
PROBE_TOP = "tri_oracle_unified_chip_cut_probe_tb"
ARBITERS = {
    "external_read_mux": "tri_oracle_external_read_mux",
    "external_write_mux": "tri_oracle_external_write_mux",
    "context_external/shared_transport": "tri_oracle_context_memory_fabric",
}


def definition(code, module):
    match, = re.finditer(rb"(?m)^module\s+" + re.escape(module.encode()) + rb"\s*\(", code)
    end = code.find(b"\nendmodule", match.end())
    assert end > match.end(), module
    return code[match.start():end + len(b"\nendmodule")].decode()


def stub_from_netlist(name, ports):
    declarations = []
    for port, (direction, span) in ports.items():
        vector = "" if span is None else f"[{span[0]}:{span[1]}] "
        declarations.append(f"  {direction} {vector}{port};\n")
    return (f"module {name} ({', '.join(ports)});\n" + "".join(declarations)
            + "  // cadence black_box\nendmodule\n")


def stub_from_source(source, module):
    start, = re.finditer(rf"(?m)^module {module}\b", source)
    end = source.index("\n);", start.end()) + len("\n);")
    header = source[start.start():end]
    assert "endmodule" not in header and header.count("module ") == 1
    return header + "\n  // cadence black_box\nendmodule\n"


def synth_constraints(bundle, libraries, cuts):
    text = CONSTRAINT_TEMPLATE.read_text()
    changes = {
        "read_libs ": "read_libs {" + " ".join(map(str, libraries)) + "}",
        "read_hdl ": f"read_hdl -sv {{{bundle}}}",
        "elaborate ": f"elaborate {TOP}",
        "if {[llength $cuts] ": (
            "if {[llength $cuts] != " + str(cuts) + '} {error "Unexpected preserved hierarchy count"}'
        ),
        "write_hdl ": "write_hdl -suffix _unified_chip > netlist.v",
        "puts ": "puts TRI_ORACLE_UNIFIED_CHIP_PARTITION_MAPPED",
    }
    lines = text.splitlines()
    for prefix, replacement in changes.items():
        matching, = [index for index, line in enumerate(lines) if line.startswith(prefix)]
        lines[matching] = replacement
    return "\n".join(lines) + "\n"


def preflight_probe(wrapper, cuts):
    header = wrapper.split(");", 1)[0]
    ports = re.findall(r"(?m)^\s*(input|output) logic\s*(?:\[\d+:0\]\s*)?(\w+)\s*,?$", header)
    assert ports and len({name for _, name in ports}) == len(ports)
    zero = "'0"
    connections = ",\n".join(f"    .{name}({zero if direction == 'input' else ''})"
                             for direction, name in ports)
    code = f"""module {PROBE_TOP};
  {TOP} dut (
{connections}
  );
  initial begin
    #1;
    $display("UNIFIED_CHIP_CUT_PREFLIGHT_PASS");
    $finish;
  end
endmodule
module tri_oracle_cut_shape_probe #(parameter string MASTER="", parameter bit WIDTHS_MATCH=0) ();
  initial begin
    if (!WIDTHS_MATCH) $fatal(1,"UNIFIED_CHIP_CUT_PORT_WIDTH %m");
    $display("UNIFIED_CHIP_CUT %s %m",MASTER);
  end
endmodule
"""
    bindings = []
    for cut in cuts.values():
        tests = []
        for name, (_, span) in cut["ports"].items():
            assert re.fullmatch(r"[A-Za-z_]\w*(?:\[\w+\])*", name), name
            expression = re.sub(r"\[([A-Za-z_]\w*)\]", r".\1", name)
            width = 1 if span is None else abs(span[0] - span[1]) + 1
            tests.append(f"($bits({expression})=={width})")
        master = cut["source_module"]
        bindings.append(f'bind {master} tri_oracle_cut_shape_probe #(.MASTER("{master}"),\n'
                        f'  .WIDTHS_MATCH({" && ".join(tests)})) cut_probe ();\n')
    return "`timescale 1ns/1ps\n" + code + "\n".join(bindings)


def prepare(output):
    chip_manifest = CHIP / "prepared.json"
    chip = json.loads(chip_manifest.read_text())
    assert chip["state"] == "unified_read_decoder_connected_to_mapped_chip_commands"
    pins = chip["input_sha256"]
    verify(pins)
    pin(pins, chip_manifest)
    source_audit = CHIP / "source_inventory/receipt.json"
    inventory = json.loads(source_audit.read_text())
    assert inventory["state"] == "unified_chip_elaborated_source_memory_and_arithmetic_inventory_verified"
    verify(inventory["input_sha256"])
    assert inventory["controller_sha256"] == chip["controller_sha256"]
    pin(pins, source_audit)

    baseline_receipt = BASELINE / "receipt.json"
    baseline = json.loads(baseline_receipt.read_text())
    mapped = BASELINE / "candidate.v"
    topology_path = BASELINE / "architecture_receipt.json"
    topology = json.loads(topology_path.read_text())
    assert topology["state"] == "mapped_decoder_array_and_service_topology_verified"
    assert topology["candidate_netlist_sha256"] == baseline["candidate_netlist_sha256"]
    pin(pins, mapped, baseline["candidate_netlist_sha256"])
    for path in (baseline_receipt, topology_path, CONSTRAINT_TEMPLATE):
        pin(pins, path)
    pin(pins, DISPATCH, chip["controller_sha256"])

    base_bundle = CHIP / "bundle.sv"
    includes = tuple(Path(name) for name in re.findall(r'(?m)^`include "([^"]+)"$', base_bundle.read_text()))
    assert all(str(path.relative_to(ROOT)) in pins for path in includes)
    wrapper, = [path for path in includes if path.name == "wrappers.sv"]
    attention, = [path for path in includes if path.name == "tri_oracle_attention_pipeline430.sv"]
    bank_paths = {
        f"layer.layer.feedforward.compute.compute.tensor.fabric.clusters[{bank}].unit."
        f"selected_bank{bank}.block_instance": (f"tri_oracle_native_cluster{bank}",
                                              topology["banks"][str(bank)]["mapped_master"])
        for bank in range(5)
    }
    cut_specs = {
        **bank_paths,
        "layer.layer.attention_pipeline": ("tri_oracle_attention_pipeline430", "tri_oracle_context_attention_pipeline"),
        "layer.shared_reads": ("tri_oracle_external_read_mux", "tri_oracle_external_read_mux"),
        "layer.shared_writes": ("tri_oracle_external_write_mux", "tri_oracle_external_write_mux"),
        "layer.context_memory": ("tri_oracle_context_memory_fabric", "tri_oracle_context_memory_fabric"),
        "dispatch": ("tri_oracle_chip_dispatch", "tri_oracle_chip_dispatch"),
    }
    assert len(cut_specs) == 10
    cuts, stubs = {}, []
    with mapped.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as code:
        for path, (name, target) in cut_specs.items():
            implementation = definition(DISPATCH.read_bytes() if path == "dispatch" else code, target)
            ports = declarations(implementation)[0]
            assert ports and set(direction for direction, _ in ports.values()) == {"input", "output"}
            cuts[path] = {"source_module": name, "mapped_master": target, "ports": ports,
                          "module_sha256": digest_bytes(implementation.encode()).hexdigest()}
            if path in bank_paths:
                stub = stub_from_source(wrapper.read_text(), name)
            elif path == "layer.layer.attention_pipeline":
                stub = stub_from_source(attention.read_text(), name)
            else:
                stub = stub_from_netlist(name, ports)
            stubs.append(stub)

    expected_mapped = {PHYSICAL / parent / "mapped/netlist.v" for parent in ARBITERS}
    expected_mapped |= {DISPATCH, DECODER.parent / "mapped/netlist.v"}
    assert {path for path in includes if path.name == "netlist.v"} == expected_mapped
    kept = [
        path for path in includes if path.suffix == ".sv" and path not in {wrapper, attention}
        and not path.name.endswith("_tb.sv") and "probe" not in path.stem
    ]
    assert len(kept) + len(expected_mapped) + 2 < len(includes)
    vendor_models = [path for path in includes if path.parent.name == "VERILOG"]
    assert len(vendor_models) == 6
    views = json.loads(REFERENCE.read_text())["input_sha256"]
    timing_libs = []
    for model in vendor_models:
        timing, = (Path(name) for name in views
                    if name.endswith("_ssg0p9v125c.lib") and Path(name).parent.parent == model.parent.parent)
        pin(pins, timing, views[str(timing)])
        timing_libs.append(timing)
    pin(pins, STD_CELL)

    output.mkdir()
    abstracts = output / "preserved.sv"
    abstracts.write_text("\n".join(stubs))
    bundle = output / "synthesis.sv"
    body = "".join(f'`include "{path}"\n' for path in (*kept, abstracts))
    bundle.write_text(body)
    preflight = output / "elaborate.sv"
    monitor = output / "cut_probe.sv"
    monitor.write_text(preflight_probe((CHIP / f"{TOP}.sv").read_text(), cuts))
    preflight.write_text("`define UNIT_DELAY\n" +
                        "".join(f'`include "{path}"\n' for path in vendor_models) + body +
                        f'`include "{monitor}"\n')
    constraints = output / "map.tcl"
    constraints.write_text(synth_constraints(bundle, (STD_CELL, *timing_libs), len(cuts)))
    for path in (abstracts, bundle, preflight, monitor, constraints, Path(__file__)):
        pin(pins, path)
    result = {
        "state": "unified_chip_synthesis_partition_prepared",
        "top": TOP, "preserved": cuts,
        "baseline_netlist_sha256": baseline["candidate_netlist_sha256"],
        "controller_sha256": chip["controller_sha256"],
        "source_training_receipt_required": str(CHIP / "image_trained/receipt.json"),
        "input_sha256": pins,
    }
    (output / "prepared.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result["state"], "preserved_blocks", len(cuts))


def verify_preflight(output, log):
    prepared = output / "prepared.json"
    result = json.loads(prepared.read_text())
    assert result["state"] == "unified_chip_synthesis_partition_prepared"
    pins = result["input_sha256"]
    verify(pins)
    text = log.read_text()
    assert text.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*(?:E|F),", text)
    assert text.splitlines().count("UNIFIED_CHIP_CUT_PREFLIGHT_PASS") == 1
    prefix = f"{PROBE_TOP}.dut."
    found = {}
    for name, path in re.findall(r"(?m)^UNIFIED_CHIP_CUT (\S+) (.+)$", text):
        path = re.sub(r"[\\\s]", "", path)
        assert path.startswith(prefix) and path.endswith(".cut_probe")
        instance = path.removeprefix(prefix).removesuffix(".cut_probe")
        assert instance not in found
        found[instance] = name
    assert found == {path: item["source_module"] for path, item in result["preserved"].items()}
    for path in (prepared, log):
        pin(pins, path)
    proof = {
        "state": "unified_chip_synthesis_partition_cut_widths_elaborated",
        "preserved_cuts": len(found),
        "declared_cut_ports_checked": sum(len(item["ports"]) for item in result["preserved"].values()),
        "source_training_receipt_required": result["source_training_receipt_required"],
        "input_sha256": pins,
    }
    (output / "preflight_receipt.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(proof["state"], proof["preserved_cuts"], proof["declared_cut_ports_checked"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "preflight"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.output.resolve())
    else:
        verify_preflight(args.output.resolve(), args.log.resolve())
