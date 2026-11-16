"""Verify packetized statistics and replay inputs on the mapped normalization path."""

import argparse
import json
from pathlib import Path
import re
import shlex

import link_tri_oracle_chip_packet_io as link
import verify_tri_oracle_host_control as control
import verify_tri_oracle_host_projection as projection
import verify_tri_oracle_host_rotary as rotary
from audit_tri_oracle_physical_io_budget import INTERFACE
from link_tri_oracle_indexed_whole_chip import module_at, spans
from link_tri_oracle_narrow_host import declarations, width
from measure_tri_oracle_serial_memory_requests import digest, read, replace


BASE = link.ROOT / "host_projection"
RECORD = Path("records/tri_oracle_host_projection_packets.json")
RX = "tri_oracle_host_normalization_rx"
WRAPPER = "tri_oracle_chip_projection_packet_io"
RMS = "tri_oracle_native_reset_copy_3"
TOP = "tri_oracle_packet_normalization_stream_tb"
RTL = Path(f"verilog/{RX}.sv")
BENCH = Path(f"verilog/{TOP}.svh")
STREAM_PORTS = set(INTERFACE["normalization_stream"].split()) - {"residual_token"}
HIDE = STREAM_PORTS - {"stats_ready", "replay_ready"}


def wrap(previous, mapped):
    ports = control.outer_ports(previous)
    assert all(ports[name][0] == "INPUT" for name in HIDE)
    assert width({name: ports[name] for name in HIDE}) == 388
    exposed = {name: shape for name, shape in ports.items() if name not in HIDE}
    old = (projection.RX, "projection_rx")
    old_links = control.original_links(previous, old)
    new_links = old_links | {name: name for name in sorted(STREAM_PORTS)}
    data = mapped.read_bytes()
    index = spans(data)
    assert set(index) == {RX}
    actual = link.ports(module_at(data, index, RX))
    assert actual.keys() == new_links.keys()
    for name in STREAM_PORTS:
        direction, bits = ports[name]
        assert actual[name] == ("OUTPUT" if direction == "INPUT" else "INPUT", bits)
    text = replace(previous, ",\n".join(declarations(ports)), ",\n".join(declarations(exposed)))
    wires = "".join(decl + ";\n" for decl in declarations({name: ports[name] for name in ports if name in HIDE}, wires=True))
    text = replace(text, "\n);\n", "\n);\n" + wires)
    text = control.replace_instance(text, old, (RX, "normalization_rx"), old_links, new_links)
    return text, exposed


def prepare(output, phase, evidence):
    def pin(path, expected=None):
        if str(path) not in evidence:
            evidence[str(path)] = digest(path)
        assert expected is None or evidence[str(path)] == expected, path
        return path

    prior = read(pin(RECORD))

    def baseline(path):
        return pin(path, prior["evidence_sha256"][str(path)])

    inputs = read(BASE / "cut_inputs.json")
    assert inputs.keys() == {"PACKETS", "VECTORS", "NORM_INPUTS", "NORM_EXPECTED"}
    inputs = {name: baseline(Path(path)) for name, path in inputs.items()}
    mapped = pin(output / "genus/netlist.v")
    source = baseline(BASE / "projection_cut.v").read_bytes()
    index = spans(source)
    assert RMS in index and projection.NORMALIZER in index
    parent = module_at(source, index, "tri_oracle_native_reset_copy_2")
    assert control.original_links(parent.decode(), (RMS, "activation"))["stats_data"] == "norm_data"
    modules, todo = {}, [RMS]
    while todo:
        name = todo.pop()
        if name in modules:
            continue
        modules[name] = module_at(source, index, name)
        todo.extend(match[1].decode() for match in projection.INSTANCE.finditer(modules[name]) if match[1].decode() in index)
    cut = b"\n".join(modules.values()) + b"\n"

    old_net = baseline(BASE / "genus/netlist.v")
    old_data = old_net.read_bytes()
    projection_ports = link.ports(module_at(old_data, spans(old_data), projection.RX))
    mapped_data = mapped.read_bytes()
    replacement_ports = link.ports(module_at(mapped_data, spans(mapped_data), RX))
    assert {name: replacement_ports[name] for name in projection_ports} == projection_ports
    alias_text = f"module {projection.RX} (\n" + ",\n".join(declarations(projection_ports)) + "\n);\n"
    alias_text += link.instance(RX, "adapter", {name: name for name in projection_ports} |
                               {name: "1'b0" if name.endswith("_ready") else "" for name in sorted(STREAM_PORTS)})
    alias_text += "endmodule\n"

    wrapper, exposed = wrap(baseline(BASE / "projection_wrapper.v").read_text(), mapped)
    assert prior["top_level_signal_bits"] - width(exposed) == 388
    bench = baseline(BASE / "attention_tb.sv").read_text()
    target = (WRAPPER, "dut")
    original = control.original_links(bench, target)
    assert set(original) - HIDE == exposed.keys()
    bench = control.replace_instance(bench, target, target, original, {name: original[name] for name in exposed})

    include = projection.include
    rms_ports = link.ports(modules[RMS])
    reset_ports = {name for name in rms_ports if name.startswith("tri_reset_tree_0_n")}
    assert reset_ports and all(rms_ports[name] == ("INPUT", None) for name in reset_ports)
    stimulus = replace(pin(BENCH).read_text(), "  // RMS_INSTANCE", link.instance(RMS, "dut", {
        name: "rst_n" if name in reset_ports else name for name in rms_ports
    }).rstrip())
    generated = {"activation_cut.v": cut, "projection_alias.v": alias_text.encode(), "stream_tb.sv": stimulus.encode(),
                 "projection_wrapper.v": wrapper.encode(), "attention_tb.sv": bench.encode()}
    substitutions = {old_net: mapped} | {BASE / name: output / name for name in ("projection_wrapper.v", "attention_tb.sv")}
    for name in ("wrapper_bundle.sv", "projection_cut_bundle.sv"):
        bundle = baseline(BASE / name).read_text()
        for label in re.findall(r'(?m)^`include "([^"]+)"$', bundle):
            path = Path(label).relative_to(Path.cwd())
            baseline(path)
            if path in substitutions:
                revised = include(substitutions[path])
                if name == "projection_cut_bundle.sv" and path == old_net:
                    revised += include(output / "projection_alias.v")
                bundle = replace(bundle, include(path), revised)
        generated[name] = bundle.encode()
    model = baseline(rotary.MODEL)
    generated["stream_bundle.sv"] = "".join(include(path) for path in (
        model, mapped, output / "activation_cut.v", output / "stream_tb.sv"
    )).encode()
    for name, content in generated.items():
        path = output / name
        if phase == "prepare":
            with path.open("xb") as stream:
                stream.write(content)
        else:
            assert path.read_bytes() == content, path
            pin(path)
    return inputs, prior, width(exposed), pin


def verify(output, inputs, prior, signals, pin):
    def native(folder, bench, sources, marker, log_name="console.log"):
        log = pin(folder / log_name).read_text()
        history = pin(folder / "xrun.history").read_text()
        argv = shlex.split(re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1])
        assert argv[argv.index("-top") + 1] == bench
        assert all(str(pin(path).resolve()) in argv for path in sources)
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        assert log.count(marker) == 1
        return argv

    stats = "PACKET_NORMALIZATION_STREAM_PASS stats=512 replay=512 rows=512 host_words=13312 held="
    cases = {
        "rtl": (RTL, output / "activation_cut.v", output / "stream_tb.sv", rotary.MODEL),
        "mapped": (output / "stream_bundle.sv",),
    }
    for name, sources in cases.items():
        folder = output / name
        argv = native(folder, TOP, sources, stats)
        dump = pin(folder / "normalized.hex")
        assert f"+DUMP={dump.resolve()}" in argv
        assert all(f"+{key}={inputs[key].resolve()}" in argv for key in ("NORM_INPUTS", "NORM_EXPECTED"))
        expected = [f"{int(word, 16) & ((1 << 216) - 1):054x}" for word in inputs["NORM_EXPECTED"].read_text().splitlines()]
        assert len(expected) == 512 and dump.read_text().splitlines() == expected
    assert "NORMALIZATION_STREAM_MISROUTED_FRAME" in pin(output / "red/console.log").read_text()
    argv = native(output / "projection", projection.CUT_TOP, (output / "projection_cut_bundle.sv",),
                  "PACKET_PROJECTION_NORMALIZATION_PASS operands=512 gamma=512 rows=512 bank_rows=512 host_words=14336 packets=64")
    assert all(f"+{key}={path.resolve()}" in argv for key, path in inputs.items())
    projection_out = pin(output / "projection/normalized.hex")
    assert f"+DUMP={projection_out.resolve()}" in argv
    baseline = BASE / "projection/normalized.hex"
    assert projection_out.read_bytes() == pin(baseline, prior["evidence_sha256"][str(baseline)]).read_bytes()

    argv = native(output / "native", link.BENCH, (output / "wrapper_bundle.sv",),
                  "COLD_PACKET_ATTENTION_PASS rows=2 host_words=277 maps=576 context_words=90 reads=9292 value_reads=206 wide=989 auxiliary=783",
                  log_name="xrun.log")
    dump = pin(output / "rows.hex")
    assert f"+DUMP={dump.resolve()}" in argv
    prepared = read(pin(link.ROOT / "prepared.json"))
    assert prepared["cold_netlist_sha256"] == prior["cold_netlist_sha256"]
    assert f"+FIXTURE={Path(prepared['fixture']).resolve()}" in argv
    baseline = BASE / "rows.hex"
    assert dump.read_bytes() == pin(baseline, prior["evidence_sha256"][str(baseline)]).read_bytes()
    status = read(pin(output / "native_status.json"))
    assert status["native_exit_status"] == 0 and status["stop_reason"] is None
    assert status["log_sha256"] == digest(output / "native/xrun.log")

    mapped = output / "genus"
    assert "TRI_ORACLE_HOST_NORMALIZATION_RX_GENUS_FINISHED" in pin(mapped / "console.log").read_text()
    assert "No unresolved references" in pin(mapped / "mapped_check.rpt").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", pin(mapped / "constraints.sdc").read_text())
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(mapped / "timing.rpt").read_text())))
    assert slack >= 0
    area = pin(mapped / "area.rpt").read_text()
    assert "Operating conditions:   ssg0p9v125c" in area
    (cells, area_um2), = re.findall(rf"(?m)^\s*{RX}\s+NA\s+(\d+)\s+([\d.]+)", area)
    for path in (Path(__file__), Path("syn/tri_oracle_synthesize_host_normalization_rx.tcl")):
        pin(path)
    roles = prior["remaining_parallel_signal_bits_by_role"].copy()
    roles["normalization_stream"] -= 388
    assert sum(roles.values()) == 215
    return {
        "state": "mapped_statistics_and_replay_streams_verified_over_host_packets",
        "cold_netlist_sha256": prior["cold_netlist_sha256"], "removed_parallel_input_signals": 388,
        "top_level_signal_bits": signals, "remaining_parallel_signal_bits_by_role": roles,
        "modeled_pad_sites_with_two_edge_receive": prior["modeled_pad_sites_with_two_edge_receive"] - 388,
        "clear_sites_in_current_floorplan": prior["clear_sites_in_current_floorplan"],
        "statistics_packets": 512, "replay_packets": 512, "normalized_components": 4096,
        "projection_regression_bank_rows": 512, "whole_chip_attention_rows": 2,
        "isolated_mapping": {"target_period_ns": 1.72414, "worst_setup_slack_ps": slack,
                             "cells": int(cells), "area_um2": float(area_um2)},
        "native_resources": status,
        "scope": "Active statistics and replay test uses the intact mapped RMS normalization subhierarchy and "
                 "trained strip fixture. The previous projection replay also passes with the shared receiver. The "
                 "whole-chip test uses the attention command path. The feed-forward controller's external stream "
                 "mode and a physical pad interface still need full-chip qualification.",
    }


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    evidence = {}
    result = prepare(args.directory, args.phase, evidence)
    if args.phase == "prepare":
        print(json.dumps({name: str(path.resolve()) for name, path in result[0].items()}))
    else:
        print(json.dumps(verify(args.directory, *result) | {"evidence_sha256": evidence}, indent=2, sort_keys=True))
