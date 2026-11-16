"""Verify the serial projection inputs on the exact mapped normalizer and chip boundary."""

import argparse
import json
import mmap
from pathlib import Path
import re
import shlex

import link_tri_oracle_chip_packet_io as link
import verify_tri_oracle_host_attention as attention
import verify_tri_oracle_host_control as control
import verify_tri_oracle_host_rotary as rotary
from link_tri_oracle_indexed_whole_chip import module_at, spans
from link_tri_oracle_narrow_host import declarations, width
from measure_tri_oracle_serial_memory_requests import digest, read, replace


BASE = link.ROOT / "host_control"
RECORD = Path("records/tri_oracle_host_control.json")
TRAINED = Path("records/tri_oracle_repaired_native_trained_writeback.json")
PLACED = Path("records/tri_oracle_repacked_whole_chip_cold_reload.json")
RX = "tri_oracle_host_projection_rx"
NORMALIZER = "tri_oracle_native_reset_copy_0"
CUT_TOP = "tri_oracle_packet_projection_normalization_tb"
RTL = Path(f"verilog/{RX}.sv")
UNIT = Path(f"verilog/{RX}_tb.sv")
CUT_BENCH = Path(f"verilog/{CUT_TOP}.svh")
PROJECTION = {
    "operand_valid": "proj_operand_valid", "operand_ready": "proj_operand_ready",
    "residual_q32": "proj_residual_q32", "projection_shift": "proj_projection_shift",
    "gamma_valid": "proj_gamma_valid", "gamma_ready": "proj_gamma_ready", "gamma_data": "proj_gamma_data",
}
HIDDEN = frozenset(net for pin, net in PROJECTION.items() if pin not in {"operand_ready", "gamma_ready"})
MEMORY_MODEL = Path(".cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/"
                    "VERILOG/ts5n28hpcpsvta512x64m4f_130a_tt1v25c.v")
INSTANCE = re.compile(rb"(?m)^\s*(\w+)\s+(?:\\[^\s]+|[\w/$]+)\s*\(")


def include(path):
    return f'`include "{path.resolve()}"\n'


def exact_cut(cold):
    with cold.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        index = spans(data)
        chip = module_at(data, index, link.TOP)
        owned = control.original_links(chip.decode(), (NORMALIZER, "direct_projection"))
        assert all(owned[port] == wire for port, wire in PROJECTION.items())
        modules = {}
        pend = [NORMALIZER]
        while pend:
            name = pend.pop()
            if name in modules:
                continue
            main = module_at(data, index, name)
            modules[name] = main
            pend.extend(match[1].decode() for match in INSTANCE.finditer(main) if match[1].decode() in index)
    return b"\n".join(modules.values()) + b"\n", len(modules)


def scoreboard(source):
    source = replace(source, "output logic operand_valid,", "input logic operand_valid,")
    source = replace(source, "output logic [279:0] residual_q32,", "input logic [279:0] residual_q32,")
    source = replace(source, "output logic [4:0] projection_shift,", "input logic [4:0] projection_shift,")
    source = replace(source, "output logic gamma_valid,", "input logic gamma_valid,")
    source = replace(source, "output logic [127:0] gamma_data,", "input logic [127:0] gamma_data,")
    for name in ("residual_q32", "projection_shift", "operand_valid", "gamma_valid", "gamma_data"):
        expression, = re.findall(rf"(?m)^    assign {name} = .*;\n", source)
        source = replace(source, expression, "")
    source = replace(source, "if ({operand_token, operand_strip} !== 9'(inputs))",
                     "if ({operand_token, operand_strip} !== 9'(inputs) ||\n"
                     "                {projection_shift, residual_q32} !== {operands[348:344], operands[279:0]})")
    return replace(source, "if (gamma_strip !== 8'(gamma_count))", "if (gamma_strip !== 8'(gamma_count) ||\n"
                   "                gamma_data !== normalization_inputs[gamma_count][255:128])")


def wrapper(body, mapped):
    module = (attention.WRAPPER, "chip")
    ports = control.outer_ports(body)
    outer = {name: shape for name, shape in ports.items() if name not in HIDDEN}
    rx_links = {"clk": "clk", "rst_n": "rst_n", "rx_valid": "host_rx_valid", "rx_ready": "host_rx_ready",
                "rx_is_payload": "host_rx_is_payload", "rx_payload_last": "host_rx_payload_last",
                "rx_data": "host_rx_data", "forward_valid": "forward_valid", "forward_ready": "forward_ready"} | PROJECTION
    expected = {name: ports[wire] for name, wire in rx_links.items() if name not in PROJECTION and "forward_" not in name}
    expected.update(forward_valid=("OUTPUT", None), forward_ready=("INPUT", None))
    for pin, net in PROJECTION.items():
        direction, size = ports[net]
        expected[pin] = ("OUTPUT" if direction == "INPUT" else "INPUT", size)
    control.check_mapped(mapped, RX, expected)
    assert width(ports) - width(outer) == 415
    inner = {name: name for name in ports} | {"host_rx_valid": "forward_valid", "host_rx_ready": "forward_ready"}
    text = "module tri_oracle_chip_projection_packet_io (\n" + ",\n".join(declarations(outer)) + "\n);\n"
    text += "  wire forward_valid, forward_ready;\n"
    text += "".join(line + ";\n" for line in declarations({name: ports[name] for name in ports if name in HIDDEN}, wires=True))
    text += link.instance(*module, inner) + link.instance(RX, "projection_rx", rx_links) + "endmodule\n"
    for master, model in ((module, inner), ((RX, "projection_rx"), rx_links)):
        assert control.original_links(text, master) == model
    return text, outer


def prepare(output, phase, evidence):
    def pin(path, expected=None):
        if str(path) not in evidence:
            evidence[str(path)] = digest(path)
        assert expected is None or evidence[str(path)] == expected, path
        return path

    previous = read(pin(RECORD))
    placed = read(pin(PLACED))
    assert previous["cold_netlist_sha256"] == placed["cold_netlist_sha256"]
    cold, = (Path(path) for path in placed["evidence_sha256"] if path.endswith("/cold.v"))
    pin(cold, previous["cold_netlist_sha256"])
    mapped = pin(output / "genus/netlist.v")
    cut, cut_count = exact_cut(cold)
    assert cut_count >= 2 and len(cut) < 20_000_000
    trained = read(pin(TRAINED))
    manifest_path, = (Path(name) for name in trained["evidence_sha256"] if name.endswith("/whole_chip/inputs.json"))
    manifest = read(pin(manifest_path, trained["evidence_sha256"][str(manifest_path)]))
    inputs = {}
    for name in ("PACKETS", "VECTORS", "NORM_INPUTS", "NORM_EXPECTED"):
        value, = (argument.split("=", 1)[1] for argument in manifest["args"] if argument.startswith(f"+{name}="))
        inputs[name] = pin(Path(value), manifest["inputs"][value])
    peer, = (Path(name) for name in manifest["inputs"] if name.endswith("/direct_writer/projection_peer.sv"))
    peer_text = scoreboard(pin(peer, manifest["inputs"][str(peer)]).read_text())
    for model in (MEMORY_MODEL, rotary.MODEL):
        pin(model, previous["evidence_sha256"][str(model)])

    def baseline(name):
        path = BASE / name
        return pin(path, previous["evidence_sha256"][str(path)]).read_text()

    wrapper_text, ports = wrapper(baseline("attention_wrapper.v"), mapped)
    assert previous["top_level_signal_bits"] - width(ports) == 415
    bench = baseline("attention_tb.sv")
    original = (attention.WRAPPER, "dut")
    bench_pins = control.original_links(bench, original)
    bench = control.replace_instance(bench, original, ("tri_oracle_chip_projection_packet_io", "dut"),
                                     bench_pins, {name: net for name, net in bench_pins.items() if name in ports})
    bundle = baseline("wrapper_bundle.sv")
    for name in re.findall(r'(?m)^`include "([^"]+)"$', bundle):
        path = Path(name).relative_to(Path.cwd())
        pin(path, previous["evidence_sha256"][str(path)])
    whole_candidates = (mapped, output / "projection_wrapper.v", output / "attention_tb.sv")
    whole = replace(bundle, include(BASE / "attention_tb.sv"), "".join(include(path) for path in whole_candidates))
    cut_sources = (rotary.MODEL, MEMORY_MODEL, mapped, output / "projection_cut.v", output / "fixture_peer.sv", pin(CUT_BENCH))
    cut_bundle = "`define UNIT_DELAY\n" + "".join(include(path) for path in cut_sources)
    developed = {"projection_cut.v": cut, "fixture_peer.sv": peer_text.encode(),
                 "projection_cut_bundle.sv": cut_bundle.encode(), "projection_wrapper.v": wrapper_text.encode(),
                 "attention_tb.sv": bench.encode(), "wrapper_bundle.sv": whole.encode()}
    for name, expected in developed.items():
        path = output / name
        if phase == "prepare":
            with path.open("xb") as stream:
                stream.write(expected)
        else:
            assert path.read_bytes() == expected, path
            pin(path)
    return inputs, previous, cut_count, width(ports), pin


def verify(output, inputs, previous, cut_count, signal_bits, pin):
    def xcelium(location, sources, expected_log, filename="console.log"):
        history = pin(location / "xrun.history").read_text()
        argv = shlex.split(re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1])
        assert all(str(pin(source).resolve()) in argv for source in sources)
        text = pin(location / filename).read_text()
        assert text.count(expected_log) == 1
        assert text.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", text)
        return text, argv

    unit = "PROJECTION_RX_PASS forwarded=84 operands=1 gamma=1"
    xcelium(output / "rtl", (RTL, UNIT), unit)
    xcelium(output / "mapped", (output / "genus/netlist.v", rotary.MODEL, UNIT), unit)
    assert "PROJECTION_RX_MISROUTED_WORD a678" in pin(output / "red/console.log").read_text()
    _, argv = xcelium(output / "projection", (output / "projection_cut_bundle.sv",),
                       "PACKET_PROJECTION_NORMALIZATION_PASS operands=512 gamma=512 rows=512 bank_rows=512 host_words=14336 packets=64")
    assert argv[argv.index("-top") + 1] == CUT_TOP
    assert all(f"+{name}={path.resolve()}" in argv for name, path in inputs.items())
    dump = pin(output / "projection/normalized.hex")
    assert f"+DUMP={dump.resolve()}" in argv
    expected = [f"{int(word, 16) & ((1 << 216) - 1):054x}" for word in inputs["NORM_EXPECTED"].read_text().splitlines()]
    assert len(expected) == 512 and dump.read_text().splitlines() == expected

    status = read(pin(output / "native_status.json"))
    assert status["native_exit_status"] == 0 and status["stop_reason"] is None
    assert status["log_sha256"] == digest(pin(output / "native/xrun.log"))
    _, argv = xcelium(output / "native", (output / "wrapper_bundle.sv",),
        "COLD_PACKET_ATTENTION_PASS rows=2 host_words=277 maps=576 context_words=90 reads=9292 value_reads=206 wide=989 auxiliary=783",
        filename="xrun.log")
    assert argv[argv.index("-top") + 1] == link.BENCH
    whole = pin(output / "rows.hex")
    assert f"+DUMP={whole.resolve()}" in argv and f"+FIXTURE={Path(read(link.ROOT / 'prepared.json')['fixture']).resolve()}" in argv
    reference = BASE / "rows.hex"
    assert whole.read_bytes() == pin(reference, previous["evidence_sha256"][str(reference)]).read_bytes()

    mapped = output / "genus"
    assert "TRI_ORACLE_HOST_PROJECTION_RX_GENUS_FINISHED" in pin(mapped / "console.log").read_text()
    assert "No unresolved references" in pin(mapped / "mapped_check.rpt").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", pin(mapped / "constraints.sdc").read_text())
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(mapped / "timing.rpt").read_text())))
    assert slack >= 0
    area = pin(mapped / "area.rpt").read_text()
    (cells, area_um2), = re.findall(rf"(?m)^\s*{RX}\s+NA\s+(\d+)\s+([\d.]+)", area)
    for path in (Path(__file__), Path("syn/tri_oracle_synthesize_host_projection_rx.tcl")):
        pin(path)
    assert "Operating conditions:   ssg0p9v125c" in area
    roles = previous["remaining_parallel_signal_bits_by_role"].copy()
    roles["projection_residual_and_scale"] -= 286
    roles["projection_normalization_parameters"] -= 129
    return {
        "state": "mapped_projection_residual_and_gamma_received_over_host_packets",
        "cold_netlist_sha256": previous["cold_netlist_sha256"], "extracted_projection_modules": cut_count,
        "removed_parallel_input_signals": 415, "top_level_signal_bits": signal_bits,
        "remaining_parallel_signal_bits_by_role": roles,
        "modeled_pad_sites_with_two_edge_receive": previous["modeled_pad_sites_with_two_edge_receive"] - 415,
        "clear_sites_in_current_floorplan": previous["clear_sites_in_current_floorplan"],
        "matched_normalized_components": 4096, "matched_bank_rows": 512, "matched_attention_output_bytes": 512,
        "isolated_mapping": {"cells": int(cells), "area_um2": float(area_um2), "worst_setup_slack_ps": slack,
                             "target_period_ns": 1.72414},
        "native_resources": status,
        "scope": "The active normalization replay uses the exact mapped projection subhierarchy, four compiled memory "
                 "models and the trained two-token fixture. The whole-chip replay checks the existing attention path "
                 "through the new ingress filter. Projection request metadata, other parallel ports and physical "
                 "timing still require qualification.",
    }


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    evidence = {}
    prepared = prepare(args.directory, args.phase, evidence)
    if args.phase == "prepare":
        print(json.dumps({name: str(path.resolve()) for name, path in prepared[0].items()}))
    else:
        print(json.dumps(verify(args.directory, *prepared) | {"evidence_sha256": evidence}, indent=2, sort_keys=True))
