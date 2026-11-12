"""Prepare and check the dual-lane chip's preserved synthesis interfaces."""

import argparse
import json
from pathlib import Path
import re

from audit_tri_oracle_wac_parent_hdl_export import declarations
from prepare_tri_oracle_chip_command_layer import TOP
from prepare_tri_oracle_packed_tensor import rewrite
from prepare_tri_oracle_unified_chip_synthesis import PROBE_TOP, preflight_probe
from verify_tri_oracle_packed_down_weights import ROOT, sha256


BASE = ROOT / ".cache/physical/wide_weight_loader"
BASELINE = BASE / "unified_chip/synthesis"
ADAPTER = BASE / "parallel_loader/mapped_adapter"
LOADER = "tri_oracle_parallel_weight_loader"
LOADER_CUT = "layer.layer.feedforward.compute.compute.tensor.packed_loader.implementation"
AUX_PORTS = {
    "aux_req_valid": ("output", 1), "aux_req_ready": ("input", 1),
    "aux_req_address": ("output", 64), "aux_req_length": ("output", 6),
    "aux_rsp_valid": ("input", 1), "aux_rsp_ready": ("output", 1),
    "aux_rsp_last": ("input", 1), "aux_rsp_error": ("input", 1),
    "aux_rsp_data": ("input", 512),
}


def read(path):
    return json.loads(path.read_text())


def pin(pins, path, expected=None):
    current = sha256(path)
    name = str(path.relative_to(ROOT))
    assert expected is None or current == expected, path
    assert pins.setdefault(name, current) == current, path


def verify(pins):
    for path, digest in pins.items():
        assert sha256(ROOT / path) == digest, path


def includes(path):
    return tuple(Path(name) for name in re.findall(r'(?m)^`include "([^"]+)"$', path.read_text()))


def width(span):
    return 1 if span is None else abs(span[0] - span[1]) + 1


def loader_interface(pins, recorded):
    module = LOADER + "_mapped"
    mapped = ADAPTER / "mapped.v"
    adapter = ADAPTER / "adapter.sv"
    old = BASE / "parallel_loader/mapped/netlist.v"
    evidence = recorded["evidence_sha256"]
    for path in (adapter, old, ADAPTER / "console.log", ADAPTER / "exit_status"):
        pin(pins, path, evidence[str(path.relative_to(ROOT))])
    assert int((ADAPTER / "exit_status").read_text()) == 0
    assert (ADAPTER / "console.log").read_text().splitlines().count("PARALLEL_WEIGHT_LOADER_PASS tiles=6") == 1
    assert mapped.read_text() == rewrite(old.read_text(), ((f"module {LOADER}(", f"module {module}("),))
    pin(pins, mapped)

    ports, _ = declarations(mapped.read_text())
    split = {name for name in ports if re.fullmatch(r"\w+\[[01]\]", name)}
    assert split == {f"{name}[{lane}]" for name in
                     ("req_address", "req_length", "load_core", "load_addr", "load_row_enable")
                     for lane in range(2)}
    adapter_text = adapter.read_text()
    assert all(adapter_text.count(f".\\{name} ({name})") == 1 for name in split)
    signals = {name: f"\\{name} " if name in split else name for name in ports}
    declarations_sv = []
    for name, (direction, span) in ports.items():
        bounds = "" if span is None else f"[{span[0]}:{span[1]}] "
        declarations_sv.append(f"  {direction} {bounds}{signals[name]};")
    abstract = (f"module {module} ({', '.join(signals.values())});\n" +
                "\n".join(declarations_sv) + "\n  // cadence black_box\nendmodule\n")
    cut = {"source_module": module, "mapped_master": module, "ports": ports,
           "netlist_sha256": pins[str(mapped.relative_to(ROOT))], "split_pins": sorted(split)}
    tests = [f"$bits({signals[name]})=={width(span)}" for name, (_, span) in ports.items()]
    bind = (f'bind {module} tri_oracle_cut_shape_probe #(.MASTER("{module}"),\n'
            f'  .WIDTHS_MATCH({" && ".join(tests)})) cut_probe ();\n')
    return adapter, cut, abstract, bind


def prepare(candidate, output):
    pins = {}
    direct_path = ROOT / "records/wac_parallel_weight_loader_result.json"
    direct = read(direct_path)
    assert direct["state"] == "parallel_weight_loader_mapped_and_chip_directed_frames_exact"
    pin(pins, direct_path)
    source = candidate / "prepared.json"
    pin(pins, source, direct["evidence_sha256"][str(source.relative_to(ROOT))])
    prepared = read(source)
    assert prepared["state"] == "source_chip_connects_two_packed_read_lanes_to_compiled_clusters"
    pins.update(prepared["input_sha256"])
    verify(pins)

    inventory_path = ROOT / "records/wac_unified_chip_inventory_result.json"
    recorded = read(inventory_path)
    pin(pins, inventory_path)
    prior_setup, prior_check = BASELINE / "prepared.json", BASELINE / "preflight_receipt.json"
    for path in (prior_setup, prior_check):
        pin(pins, path, recorded["evidence_sha256"][str(path.relative_to(ROOT))])
    baseline, checked = read(prior_setup), read(prior_check)
    assert baseline["state"] == "unified_chip_synthesis_partition_prepared"
    assert checked["state"] == "unified_chip_synthesis_partition_cut_widths_elaborated"
    assert baseline["top"] == TOP
    preserved = baseline["preserved"]
    assert len(preserved) == checked["preserved_cuts"] == 10
    assert sum(len(item["ports"]) for item in preserved.values()) == checked["declared_cut_ports_checked"] == 607
    for path in (BASELINE / "preserved.sv", BASELINE / "synthesis.sv", BASELINE / "map.tcl"):
        pin(pins, path, baseline["input_sha256"][str(path.relative_to(ROOT))])
    adapter, new_cut, loader_stub, loader_bind = loader_interface(pins, direct)

    source_bundle = candidate / "bundle.sv"
    new_sources = includes(source_bundle)
    source_modules = [path for path in new_sources if path.suffix == ".sv"]
    replacements = {path.name: path for path in source_modules}
    assert len(replacements) == len(source_modules)
    kept = []
    for path in includes(BASELINE / "synthesis.sv"):
        if path.name in ("preserved.sv", "tri_oracle_wide_weight_loader.sv", "tri_oracle_packed_weight_schedule.sv"):
            continue
        assert path.name in replacements, path
        kept.append(replacements[path.name])
    assert all(str(path.relative_to(ROOT)) in pins for path in (*kept, *new_sources))
    top = replacements[f"{TOP}.sv"]
    assert top in kept
    top_code = rewrite(top.read_text(), (
        ("  input logic aux_rsp_last,aux_rsp_error,\n",
         "  input logic aux_rsp_last,\n  input logic aux_rsp_error,\n"),
    ))
    assert top_code.count("parameter bit PACKED_FEEDFORWARD_WEIGHTS=1") == 1
    header = top_code.split("\n);", 1)[0]
    auxiliary = {name: (direction, int(msb) + 1 if msb else 1)
                 for direction, msb, name in re.findall(
                     r"(?m)^  (input|output) logic (?:\[(\d+):0\] )?(aux_\w+),$", header)}
    assert auxiliary == AUX_PORTS
    base_probe = preflight_probe(top_code, preserved)
    checks = ["dut.PACKED_FEEDFORWARD_WEIGHTS!==1'b1"]
    checks += [f"$bits(dut.{name})!={bits} || $bits(dut.layer.{name})!={bits}"
               for name, (_, bits) in AUX_PORTS.items()]
    probe = rewrite(base_probe, (
        ("    #1;\n", "    #1;\n    if (" + " ||\n        ".join(checks) +
         ') $fatal(1,"PARALLEL_CHIP_AUX_PORT_WIDTH");\n'),
    )) + "\n" + loader_bind

    output.mkdir()
    active_top = output / top.name
    active_top.write_text(top_code)
    kept[kept.index(top)] = active_top
    stubs = output / "preserved.sv"
    stubs.write_text((BASELINE / "preserved.sv").read_text() + "\n" + loader_stub)
    synth = output / "synthesis.sv"
    synth.write_text("".join(f'`include "{path}"\n' for path in (*kept, adapter, stubs)))
    monitor = output / "cut_probe.sv"
    monitor.write_text(probe)
    models = [path for path in new_sources if path.parent.name == "VERILOG"]
    assert len(models) == 6
    preflight = output / "elaborate.sv"
    preflight.write_text("`define UNIT_DELAY\n" +
                         "".join(f'`include "{path}"\n' for path in (*models, synth, monitor)))
    map_script = output / "map.tcl"
    map_script.write_text(rewrite((BASELINE / "map.tcl").read_text(), (
        (str(BASELINE / "synthesis.sv"), str(synth)),
        ("[llength $cuts] != 10", "[llength $cuts] != 11"),
        ("_unified_chip", "_parallel_chip"),
        ("TRI_ORACLE_UNIFIED_CHIP_PARTITION_MAPPED", "TRI_ORACLE_PARALLEL_CHIP_PARTITION_MAPPED"),
    )))
    for path in (active_top, stubs, synth, monitor, preflight, map_script, Path(__file__)):
        pin(pins, path)
    result = {
        "state": "parallel_chip_synthesis_partition_prepared", "top": TOP,
        "mapped_decoder_sha256": baseline["baseline_netlist_sha256"],
        "controller_sha256": baseline["controller_sha256"],
        "packed_path_enabled": True, "auxiliary_ports": AUX_PORTS,
        "auxiliary_signal_bits": sum(bits for _, bits in AUX_PORTS.values()),
        "preserved": {**preserved, LOADER_CUT: new_cut},
        "source_training_receipt_required": str(candidate / "full_native/trained_receipt.json"),
        "input_sha256": pins,
    }
    (output / "prepared.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result["state"], len(result["preserved"]), result["auxiliary_signal_bits"])


def verify_preflight(output, log):
    prepared = output / "prepared.json"
    setup = read(prepared)
    assert setup["state"] == "parallel_chip_synthesis_partition_prepared"
    pins = setup["input_sha256"]
    verify(pins)
    text = log.read_text()
    assert text.splitlines().count("UNIFIED_CHIP_CUT_PREFLIGHT_PASS") == 1
    assert text.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*(?:E|F),", text)
    found = {}
    for master, path in re.findall(r"(?m)^UNIFIED_CHIP_CUT (\S+) (.+)$", text):
        instance = re.sub(r"[\\\s]", "", path)
        prefix, suffix = f"{PROBE_TOP}.dut.", ".cut_probe"
        assert instance.startswith(prefix) and instance.endswith(suffix)
        name = instance.removeprefix(prefix).removesuffix(suffix)
        assert name not in found
        found[name] = master
    assert found == {name: cut["source_module"] for name, cut in setup["preserved"].items()}
    for path in (prepared, log):
        pin(pins, path)
    report = {
        "state": "parallel_chip_preserved_synthesis_interfaces_verified",
        "checked_cuts": found,
        "declared_cut_ports_checked": sum(len(cut["ports"]) for cut in setup["preserved"].values()),
        "loader_split_ports_checked": len(setup["preserved"][LOADER_CUT]["split_pins"]),
        "auxiliary_signal_bits": setup["auxiliary_signal_bits"],
        "packed_path_enabled": setup["packed_path_enabled"],
        "source_training_receipt_required": setup["source_training_receipt_required"],
        "input_sha256": pins,
    }
    (output / "preflight_receipt.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report["state"], len(found), report["declared_cut_ports_checked"], report["auxiliary_signal_bits"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("output", type=Path)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.input.resolve(), args.output.resolve())
    else:
        verify_preflight(args.output.resolve(), args.input.resolve())
