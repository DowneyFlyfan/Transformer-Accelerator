"""Map rotary packets onto the proven cold-chip host link and verify the replay."""

import argparse
import json
from pathlib import Path
import re
import shlex

import link_tri_oracle_chip_packet_io as link
import verify_tri_oracle_packet_projection as projection
from link_tri_oracle_indexed_whole_chip import module_at, pins, spans
from link_tri_oracle_narrow_host import declarations, width
from measure_tri_oracle_serial_memory_requests import digest, read, replace


RX = "tri_oracle_host_rotary_rx"
WRAPPER = "tri_oracle_chip_rotary_packet_io"
BASE = link.ROOT / "chip_packet_projection"
OLD_RECORD = Path("records/tri_oracle_packet_projection.json")
CHIP_RECORD = Path("records/tri_oracle_chip_packet_io.json")
MODEL = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140.v")
RTL = Path(f"verilog/{RX}.sv")
TEST = Path(f"verilog/{RX}_tb.sv")
STIMULUS = """    for (int token = 0; token < Tokens; token++) begin
      angle_valid = 1;
      angle_last = token == Tokens - 1;
      angle_cos = cosines[token];
      angle_sin = sines[token];
      do @(posedge clk); while (!angle_ready);
      @(negedge clk);
    end
    angle_valid = 0;
"""
PACKETS = """    for (int token = 0; token < Tokens; token++) begin
      flit(token == Tokens - 1 ? 16'hA671 : 16'hA670, 0, 1);
      for (int word = 0; word < 32; word++) flit(cosines[token][word * 16 +: 16], 0, 0);
      for (int word = 0; word < 32; word++) flit(sines[token][word * 16 +: 16], 0, 0);
    end
"""


def wrapper_text(previous_ports, mapped):
    angles = {name for name in previous_ports if name.startswith("angle_")}
    terminal_ports = {name: spec for name, spec in previous_ports.items() if name not in angles}
    signals = {
        "clk": "clk", "rst_n": "rst_n", "rx_valid": "host_rx_valid", "rx_ready": "host_rx_ready",
        "rx_is_payload": "host_rx_is_payload", "rx_payload_last": "host_rx_payload_last", "rx_data": "host_rx_data",
        "link_valid": "command_rx_valid", "link_ready": "command_rx_ready", "angle_valid": "angle_valid",
        "angle_ready": "angle_ready", "angle_last": "angle_last", "angle_data": "angle_data",
    }
    data = mapped.read_bytes()
    mapped_ports = link.ports(module_at(data, spans(data), RX))
    assert mapped_ports.keys() == signals.keys()
    for port, net in signals.items():
        if port in ("link_valid", "link_ready", "angle_data"):
            continue
        direction, size = previous_ports[net]
        if net in angles:
            direction = "OUTPUT" if direction == "INPUT" else "INPUT"
        assert mapped_ports[port] == (direction, size), (port, net)
    assert mapped_ports["link_valid"] == ("OUTPUT", None) and mapped_ports["link_ready"] == ("INPUT", None)
    assert mapped_ports["angle_data"] == ("OUTPUT", 1024)
    assert angles == {"angle_valid", "angle_ready", "angle_last", "angle_cos", "angle_sin"}
    assert previous_ports["angle_cos"] == previous_ports["angle_sin"] == ("INPUT", 512)
    internals = {"angle_valid": "angle_valid", "angle_ready": "angle_ready", "angle_last": "angle_last",
                 "angle_cos": "angle_data[511:0]", "angle_sin": "angle_data[1023:512]",
                 "host_rx_valid": "command_rx_valid", "host_rx_ready": "command_rx_ready"}
    chip = {name: internals.get(name, name) for name in previous_ports}
    text = f"module {WRAPPER} (\n" + ",\n".join(declarations(terminal_ports)) + "\n);\n"
    text += "  wire angle_valid, angle_ready, angle_last, command_rx_valid, command_rx_ready;\n"
    text += "  wire [1023:0] angle_data;\n"
    text += link.instance(RX, "rotary_rx", signals) + link.instance(link.WRAPPER, "chip", chip)
    assert pins(text.encode(), RX, "rotary_rx") == {name: net.encode() for name, net in signals.items()}
    assert pins(text.encode(), link.WRAPPER, "chip") == {name: net.encode() for name, net in chip.items()}
    assert width(previous_ports) - width(terminal_ports) == 1027
    return text + "endmodule\n", terminal_ports


def prepare(output, phase):
    fixture, cold, evidence = projection.prepare(BASE, "verify")

    def pin(path, expected=None):
        evidence[str(path)] = digest(path)
        assert expected is None or evidence[str(path)] == expected, path
        return path

    prior = read(pin(OLD_RECORD))
    assert prior["cold_netlist_sha256"] == cold
    for path in (BASE / "projection_tb.sv", BASE / "wrapper_bundle.sv", BASE / "native/xrun.log"):
        pin(path, prior["evidence_sha256"][str(path)])
    mapped = pin(output / "genus/netlist.v")
    previous_ports = link.load()[4]
    wrap, ports = wrapper_text(previous_ports, mapped)
    original_bench = (BASE / "projection_tb.sv").read_text()
    start = original_bench.index(f"  {link.WRAPPER} dut (\n")
    end = original_bench.index("\n  );\n", start) + len("\n  );\n")
    previous_pins = pins(original_bench.encode(), link.WRAPPER, "dut")
    assert previous_pins.keys() == previous_ports.keys()
    bench = replace(original_bench, original_bench[start:end], link.instance(
        WRAPPER, "dut", {name: previous_pins[name].decode() for name in ports}))
    bench = replace(bench, STIMULUS, PACKETS)
    bench = replace(bench, "  logic angle_valid = 0, angle_last = 0, angle_ready;\n"
                           "  logic [511:0] angle_cos = '0, angle_sin = '0;\n", "")
    wrapper = output / "rotary_wrapper.v"
    bench_path = output / "projection_tb.sv"
    include = lambda path: f'`include "{path.resolve()}"\n'
    bundle = replace((BASE / "wrapper_bundle.sv").read_text(), include(BASE / "projection_tb.sv"),
                     "".join(include(path) for path in (mapped, wrapper, bench_path)))
    for path, content in ((wrapper, wrap), (bench_path, bench), (output / "wrapper_bundle.sv", bundle)):
        if phase == "prepare":
            with path.open("x") as stream:
                stream.write(content)
        else:
            assert path.read_text() == content, path
            pin(path)
    return fixture, cold, evidence, len(ports), width(ports), pin


def verify(output, fixture, cold, evidence, port_count, signal_bits, pin):
    proof = projection.verify(output, fixture, cold, evidence)
    prior = read(OLD_RECORD)
    chip = read(pin(CHIP_RECORD))
    assert chip["cold_netlist_sha256"] == cold
    assert chip["new_digital_boundary_signal_bits"] - signal_bits == 1027
    for key in ("vectors", "acks", "writes", "read_bursts", "activation_words", "weight_words"):
        assert proof["trained_projection"][key] == prior["trained_projection"][key]
    for path in (RTL, TEST, Path(f"syn/tri_oracle_synthesize_host_rotary_rx.tcl"), Path(__file__)):
        pin(path)
    mapped = output / "genus"
    log = pin(mapped / "console.log").read_text()
    assert "TRI_ORACLE_HOST_ROTARY_RX_GENUS_FINISHED" in log
    assert "No unresolved references" in pin(mapped / "mapped_check.rpt").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", pin(mapped / "constraints.sdc").read_text())
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(mapped / "timing.rpt").read_text())))
    assert slack >= 0
    area = pin(mapped / "area.rpt").read_text()
    assert "Operating conditions:   ssg0p9v125c" in area
    (cells, area_um2), = re.findall(rf"(?m)^\s*{RX}\s+NA\s+(\d+)\s+([\d.]+)", area)

    def replay(folder, sources):
        path = output / folder
        history = pin(path / "xrun.history").read_text()
        command = re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1]
        names = {(path / word).resolve() for word in shlex.split(command) if word.endswith((".v", ".sv"))}
        assert all(source.resolve() in names for source in sources)
        log = pin(path / "console.log").read_text()
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        result, = re.findall(r"(?m)^HOST_ROTARY_RX_PASS (.+)$", log)
        return result

    expected = "vectors=2 commands=1 payloads=1 blocked=5"
    assert replay("rtl", (RTL, TEST)) == replay("mapped", (mapped / "netlist.v", MODEL, TEST)) == expected
    assert "HOST_ROTARY_RX_TIMEOUT\nSimulation terminated via $fatal(1)" in pin(output / "red/console.log").read_text()

    def simulated_ns(path):
        result, = re.findall(r"Simulation complete via \$finish\(1\) at time (\d+) NS", path.read_text())
        return int(result)

    old_ns = simulated_ns(BASE / "native/xrun.log")
    new_ns = simulated_ns(output / "native/xrun.log")
    proof.update(
        state="mapped_host_rotary_packets_verified_on_cold_whole_chip",
        top_level_ports=port_count,
        top_level_signal_bits=signal_bits,
        removed_rotary_signal_bits=1027,
        modeled_pad_sites_with_two_edge_receive=chip["modeled_pad_sites_with_two_edge_receive"] - 1027,
        clear_sites_in_current_floorplan=chip["clear_sites_in_current_floorplan"],
        rotary_vectors=16,
        rotary_link_words=16 * 65,
        projection_cycles={"parallel_angles": old_ns // 10, "packet_angles": new_ns // 10,
                           "delta": (new_ns - old_ns) // 10},
        isolated_mapping={"cells": int(cells), "area_um2": float(area_um2),
                          "target_period_ns": 1.72414, "worst_setup_slack_ps": slack},
        scope="One trained query projection for 16 tokens on the cold whole chip with the mapped host rotary "
              "adapter and the existing command and memory links. Directed replay checks backpressure, reset "
              "and both legacy record types. Physical interface timing, remaining parallel ports and "
              "full-model execution remain unverified.",
    )
    return proof


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = prepare(args.directory, args.phase)
    if args.phase == "prepare":
        print(result[0].resolve())
    else:
        print(json.dumps(verify(args.directory, *result), indent=2, sort_keys=True))
