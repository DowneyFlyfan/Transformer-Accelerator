"""Verify attention-row output on the mapped whole-chip host packet link."""

import argparse
import json
from pathlib import Path
import re
import shlex

import link_tri_oracle_chip_packet_io as link
import verify_tri_oracle_host_rotary as rotary
from link_tri_oracle_indexed_whole_chip import module_at, pins, spans
from link_tri_oracle_narrow_host import declarations, width
from measure_tri_oracle_serial_memory_requests import digest, read, replace


TX = "tri_oracle_host_attention_tx"
WRAPPER = "tri_oracle_chip_attention_packet_io"
BASE = link.ROOT / "host_rotary_link"
PREVIOUS = Path("records/tri_oracle_host_rotary_packets.json")
HOST_AUDIT = Path("records/tri_oracle_xcelium_attention_fixture_host_audit.json")
TEMPLATE = Path("verilog/tri_oracle_packet_attention_tb.svh")
RTL = Path(f"verilog/{TX}.sv")
UNIT = Path(f"verilog/{TX}_tb.sv")
CONNECTED = {
    "clk", "rst_n", "sign_valid", "sign_ready", "sign_data", "map_valid", "map_last", "map_index", "map_origin",
    "head_done_streaming", "head_done_id", "head_done_inner", "head_done_recent",
    "memory_tx_data", "memory_tx_valid", "memory_tx_ready", "memory_mem_rsp_valid", "memory_mem_rsp_ready",
    "memory_mem_rsp_last", "memory_mem_rsp_data",
}
INPUTS = {"map_ready": "1'b1", "context_base": "ContextBase", "value_read_base": "ValueBase"}


def wrap(mapped, previous_ports):
    ports = previous_ports.copy()
    assert ports.pop("result_values") == ("OUTPUT", 2048)
    signals = {
        "clk": "clk", "rst_n": "rst_n", "result_values": "result_values",
        "link_valid": "source_valid", "link_ready": "source_ready", "link_last": "source_last", "link_data": "source_data",
        "tx_valid": "host_tx_valid", "tx_ready": "host_tx_ready", "tx_last": "host_tx_last", "tx_data": "host_tx_data",
    }
    data = mapped.read_bytes()
    index = spans(data)
    assert set(index) == {TX}
    mapped_ports = link.ports(module_at(data, index, TX))
    expected = {pin: previous_ports[net] for pin, net in signals.items() if not pin.startswith("link_")}
    expected["result_values"] = ("INPUT", 2048)
    expected.update(link_valid=("INPUT", None), link_ready=("OUTPUT", None),
                    link_last=("INPUT", None), link_data=("INPUT", 16))
    assert mapped_ports == expected
    source = {name: name for name in previous_ports}
    for pin in ("valid", "ready", "last", "data"):
        source[f"host_tx_{pin}"] = signals[f"link_{pin}"]
    text = f"module {WRAPPER} (\n" + ",\n".join(declarations(ports)) + "\n);\n"
    text += "  wire [2047:0] result_values;\n  wire source_valid, source_last, source_ready;\n  wire [15:0] source_data;\n"
    text += link.instance(rotary.WRAPPER, "chip", source) + link.instance(TX, "attention_tx", signals)
    for master, instance, wiring in ((rotary.WRAPPER, "chip", source), (TX, "attention_tx", signals)):
        assert pins(text.encode(), master, instance) == {pin: net.encode() for pin, net in wiring.items()}
    return text + "endmodule\n", ports


def prepare(output, phase, evidence):
    def pin(path, expected=None):
        evidence[str(path)] = digest(path)
        assert expected is None or evidence[str(path)] == expected, path
        return path

    prior = read(pin(PREVIOUS))
    audit = read(pin(HOST_AUDIT))
    prepared = read(pin(link.ROOT / "prepared.json"))
    fixture = Path(prepared["fixture"]).relative_to(Path.cwd())
    for kind in ("map.hex", "signs.hex", "rows.txt", "expected.hex"):
        path = fixture / kind
        pin(path, prepared["evidence_sha256"][str(path)])
        assert evidence[str(path)] == audit["evidence_sha256"][str(path)], path
    assert len((fixture / "expected.hex").read_text().splitlines()) == 40 * 409

    old, _, _, _, pre_rotary_ports, _, _, _, _ = link.load()
    assert evidence.setdefault(str(old), digest(old)) == prior["cold_netlist_sha256"] == prepared["cold_netlist_sha256"]
    for name in ("genus/netlist.v", "rotary_wrapper.v", "wrapper_bundle.sv"):
        path = BASE / name
        pin(path, prior["evidence_sha256"][str(path)])
    expected_rotary, rotary_ports = rotary.wrapper_text(pre_rotary_ports, BASE / "genus/netlist.v")
    assert (BASE / "rotary_wrapper.v").read_text() == expected_rotary
    assert width(rotary_ports) == prior["top_level_signal_bits"]

    mapped = pin(output / "genus/netlist.v")
    wrapper = output / "attention_wrapper.v"
    bench = output / "attention_tb.sv"
    wrap_text, ports = wrap(mapped, rotary_ports)
    connected = CONNECTED | {name for name in ports if name.startswith("host_")}
    assert connected | INPUTS.keys() <= ports.keys()
    connections = {name: name if name in connected else INPUTS.get(name, "'0" if direction == "INPUT" else "")
                   for name, (direction, _) in ports.items()}
    bench_text = replace(pin(TEMPLATE).read_text(), "  // CHIP_INSTANCE", link.instance(WRAPPER, "dut", connections).rstrip())
    new_includes = "".join(f'`include "{path.resolve()}"\n' for path in (mapped, wrapper, bench))
    bundle = replace((BASE / "wrapper_bundle.sv").read_text(), f'`include "{(BASE / "projection_tb.sv").resolve()}"\n', new_includes)
    for line in re.findall(r'(?m)^`include "([^"]+)"$', bundle):
        path = Path(line).relative_to(Path.cwd())
        if str(path) in prior["evidence_sha256"]:
            pin(path, prior["evidence_sha256"][str(path)])
        else:
            assert path in {mapped, wrapper, bench}, path
    for path, content in ((wrapper, wrap_text), (bench, bench_text), (output / "wrapper_bundle.sv", bundle)):
        if phase == "prepare":
            with path.open("x") as stream:
                stream.write(content)
        else:
            assert path.read_text() == content, path
            pin(path)
    return fixture, prior, width(ports), pin


def verify(output, fixture, prior, signal_bits, pin):
    native = output / "native"
    dump = pin(output / "rows.hex")
    reference = (fixture / "rows.txt").read_text().splitlines()[2:4]
    assert dump.read_text().splitlines() == [row.split()[3].lower() for row in reference]
    log_path = pin(native / "xrun.log")
    log = log_path.read_text()
    status = read(pin(output / "native_status.json"))
    assert status["native_exit_status"] == 0 and status["stop_reason"] is None and status["log_sha256"] == digest(log_path)
    history = pin(native / "xrun.history").read_text()
    argv = shlex.split(re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1])
    assert argv[argv.index("-top") + 1] == link.BENCH
    assert str((output / "wrapper_bundle.sv").resolve()) in argv
    assert f"+FIXTURE={fixture.resolve()}" in argv and f"+DUMP={dump.resolve()}" in argv
    assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
    (reads, wide, auxiliary), = re.findall(
        r"(?m)^COLD_PACKET_ATTENTION_PASS rows=2 host_words=271 maps=576 context_words=90 "
        r"reads=(\d+) value_reads=206 wide=(\d+) auxiliary=(\d+)$", log)
    assert 0 < int(wide) <= int(reads) and 0 <= int(auxiliary) <= int(wide)

    mapped = output / "genus"
    assert "TRI_ORACLE_HOST_ATTENTION_TX_GENUS_FINISHED" in pin(mapped / "console.log").read_text()
    assert "No unresolved references" in pin(mapped / "mapped_check.rpt").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", pin(mapped / "constraints.sdc").read_text())
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(mapped / "timing.rpt").read_text())))
    assert slack >= 0
    area = pin(mapped / "area.rpt").read_text()
    assert "Operating conditions:   ssg0p9v125c" in area
    (cells, area_um2), = re.findall(rf"(?m)^\s*{TX}\s+NA\s+(\d+)\s+([\d.]+)", area)

    for mode, required in (("rtl", (RTL, Path("verilog/tri_oracle_host_command_link.sv"))),
                           ("mapped", (mapped / "netlist.v", link.HOST_NETLIST, rotary.MODEL))):
        location = output / mode
        unit_log = pin(location / "console.log").read_text()
        assert "HOST_ATTENTION_TX_PASS completed=5 words=275 held=94" in unit_log
        assert unit_log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", unit_log)
        unit_history = pin(location / "xrun.history").read_text()
        command = shlex.split(re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", unit_history)[-1])
        assert all(str(pin(path).resolve()) in command for path in (*required, UNIT))
    assert "ATTENTION_TX_STALL expected=0005 last=0 actual=0005 last=1" in pin(output / "red/console.log").read_text()
    pin(Path(__file__))
    pin(Path("syn/tri_oracle_synthesize_host_attention_tx.tcl"))
    assert prior["top_level_signal_bits"] - signal_bits == 2048
    return {
        "state": "mapped_attention_row_packets_verified_on_cold_whole_chip",
        "cold_netlist_sha256": prior["cold_netlist_sha256"],
        "removed_attention_signal_bits": 2048,
        "top_level_signal_bits": signal_bits,
        "modeled_pad_sites_with_two_edge_receive": prior["modeled_pad_sites_with_two_edge_receive"] - 2048,
        "clear_sites_in_current_floorplan": prior["clear_sites_in_current_floorplan"],
        "attention_rows": 2, "attention_output_bytes": 512, "result_words_per_row": 128,
        "context_write_bytes": 720, "checked_token_origins": 576, "observed_read_bursts": int(reads),
        "observed_attention_value_bursts": 206, "wide_read_bursts": int(wide),
        "auxiliary_read_bursts": int(auxiliary), "native_resources": status,
        "isolated_mapping": {"cells": int(cells), "area_um2": float(area_um2),
                             "target_period_ns": 1.72414, "worst_setup_slack_ps": slack},
        "scope": "Two trained attention rows from head zero are generated through the cold whole-chip dispatcher "
                 "and returned over its host packet link. The chip builds the token table and predicts the head type. "
                 "External memory supplies pinned query, key and value vectors from the trained fixture. The physical "
                 "interface, parallel sign inputs, and full trained execution still need qualification.",
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
        print(prepared[0].resolve())
    else:
        record = verify(args.directory, *prepared)
        print(json.dumps(record | {"evidence_sha256": evidence}, indent=2, sort_keys=True))
