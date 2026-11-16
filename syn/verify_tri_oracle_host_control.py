"""Relocate the context and value cache with host packets on the mapped chip."""

import argparse
import json
from pathlib import Path
import re
import shlex

import link_tri_oracle_chip_packet_io as link
import verify_tri_oracle_host_attention as attention
import verify_tri_oracle_host_rotary as rotary
from link_tri_oracle_indexed_whole_chip import module_at, pins, spans
from link_tri_oracle_narrow_host import declarations, width
from measure_tri_oracle_serial_memory_requests import digest, read, replace


BASE = link.ROOT / "token_sign_dma"
RECORD = Path("records/tri_oracle_token_sign_dma.json")
RTL = Path("verilog/tri_oracle_host_control.sv")
TEST = Path("verilog/tri_oracle_host_control_tb.sv")
RX = "tri_oracle_host_control_rx"
TX = "tri_oracle_host_control_tx"
BASE_PORTS = ("context_base", "value_read_base")
HEAD_PORTS = {"head_done_id": 5, "head_done_inner": 18, "head_done_recent": 18, "head_done_streaming": None}
VALUE_BASE = 0x02600000
CONTEXT_BASE = 0x34000100


def outer_ports(source):
    _, port_text = source.split("(\n", 1)
    declaration = re.compile(r"  (input|output) wire(?: \[(\d+):0\])? (\w+),?")
    parsed = {}
    for line in port_text.split("\n);", 1)[0].splitlines():
        match = declaration.fullmatch(line)
        assert match, line
        direction, msb, name = match.groups()
        assert name not in parsed
        parsed[name] = direction.upper(), int(msb) + 1 if msb else None
    return parsed


def original_links(base, named):
    observed = pins(base.encode(), *named)
    return {name: net.decode() for name, net in observed.items()}


def replace_instance(source, old, new, before, after):
    old_pattern = rf"(?ms)^  {old[0]} {old[1]} \(.*?^  \);\n"
    old_text, = re.findall(old_pattern, source)
    assert original_links(old_text, old) == before
    result = replace(source, old_text, link.instance(*new, after))
    assert original_links(result, new) == after
    return result


def check_mapped(path, master, ports):
    netlist = path.read_bytes()
    index = spans(netlist)
    assert set(index) == {master}
    assert link.ports(module_at(netlist, index, master)) == ports


def wrappers(output, rx, tx, core_text, rotary_text, attention_text):
    clocks = {"clk": ("INPUT", None), "rst_n": ("INPUT", None)}
    expected_rx = clocks | {"config_enable": ("INPUT", None), "link_ready": ("INPUT", None),
                            "link_valid": ("OUTPUT", None), "angle_ready": ("INPUT", None),
                            "angle_valid": ("OUTPUT", None), "angle_last": ("OUTPUT", None),
                            "angle_data": ("OUTPUT", 1024)}
    expected_tx = clocks | {"source_valid": ("INPUT", None), "source_last": ("INPUT", None),
                            "source_ready": ("OUTPUT", None), "source_data": ("INPUT", 16),
                            "result_values": ("INPUT", 2048), "head_values": ("INPUT", 42)}
    old_ports = outer_ports(attention_text)
    for name in ("rx_valid", "rx_ready", "rx_is_payload", "rx_payload_last", "rx_data"):
        expected_rx[name] = old_ports[f"host_{name}"]
    for name in ("tx_valid", "tx_ready", "tx_last", "tx_data"):
        expected_tx[name] = old_ports[f"host_{name}"]
    for name in BASE_PORTS:
        assert old_ports[name] == ("INPUT", 64)
        expected_rx[name] = ("OUTPUT", 64)
    assert {name: old_ports[name] for name in HEAD_PORTS} == {name: ("OUTPUT", bits) for name, bits in HEAD_PORTS.items()}
    check_mapped(rx, RX, expected_rx)
    check_mapped(tx, TX, expected_tx)

    inner = outer_ports(core_text)
    assert "host_config_enable" not in inner
    core_text = replace(core_text, ",\n".join(declarations(inner)), ",\n".join(
        declarations(inner | {"host_config_enable": ("OUTPUT", None)})))
    core_text = replace(core_text, "\nendmodule\n", "\n  assign host_config_enable = command_ready && !command_valid;\nendmodule\n")

    middle = outer_ports(rotary_text)
    middle_ports = {name: shape for name, shape in middle.items() if name not in BASE_PORTS}
    rotary_text = replace(rotary_text, ",\n".join(declarations(middle)), ",\n".join(declarations(middle_ports)))
    rotary_text = replace(rotary_text, "\n);\n", "\n);\n  wire config_enable;\n  wire [63:0] context_base, value_read_base;\n")
    source_inner = (link.WRAPPER, "chip")
    before = original_links(rotary_text, source_inner)
    rotary_text = replace_instance(rotary_text, source_inner, source_inner, before, before | {"host_config_enable": "config_enable"})
    old_rx = (rotary.RX, "rotary_rx")
    before = original_links(rotary_text, old_rx)
    rotary_text = replace_instance(rotary_text, old_rx, (RX, "control_rx"), before,
                                   before | {name: name for name in (*BASE_PORTS, "config_enable")})

    removed = set(BASE_PORTS) | HEAD_PORTS.keys()
    outer = {name: shape for name, shape in old_ports.items() if name not in removed}
    attention_text = replace(attention_text, ",\n".join(declarations(old_ports)), ",\n".join(declarations(outer)))
    head_wires = "".join(line + ";\n" for line in declarations({name: old_ports[name] for name in HEAD_PORTS}, wires=True))
    attention_text = replace(attention_text, "\n);\n", "\n);\n" + head_wires)
    old_middle = (rotary.WRAPPER, "chip")
    before = original_links(attention_text, old_middle)
    attention_text = replace_instance(attention_text, old_middle, old_middle, before,
                                      {name: net for name, net in before.items() if name not in BASE_PORTS})
    old_tx = (attention.TX, "attention_tx")
    before = original_links(attention_text, old_tx)
    source = {name.replace("link_", "source_", 1): net for name, net in before.items()}
    source["head_values"] = "{" + ",".join(HEAD_PORTS) + "}"
    attention_text = replace_instance(attention_text, old_tx, (TX, "control_tx"), before, source)

    assert width(old_ports) - width(outer) == 170
    return {output / "wrapper.v": core_text, output / "rotary_wrapper.v": rotary_text,
            output / "attention_wrapper.v": attention_text}, outer


def relocated_bench(text):
    old = (attention.WRAPPER, "dut")
    before = original_links(text, old)
    removed = set(BASE_PORTS) | HEAD_PORTS.keys()
    assert removed <= before.keys()
    text = replace_instance(text, old, old, before, {name: value for name, value in before.items() if name not in removed})
    text = replace(text, "ContextBase = 64'h30000000", f"ContextBase = 64'h{CONTEXT_BASE:08x}")
    text = replace(text, "ValueBase = CacheBase + (64'd36 << 16)", f"ValueBase = 64'h{VALUE_BASE:08x}")
    text = replace(text, "  logic [319:0] packed_map[18];", """  logic [319:0] packed_map[18];
  logic [63:0] stored_context[90];
  int restored_bursts, restored_words;""")
    text = replace(text, "\n    if (address >= SignBase)\n", """
    if (address >= ContextBase && address < ContextBase + 720)
      return {448'd0, stored_context[int'((address - ContextBase) >> 3)]};
    if (address >= SignBase)
""")
    text = replace(text, "          sign_reads++;\n        end else begin", """          sign_reads++;
        end else if (address >= ContextBase) begin
          if (lane != 0 || peer_wide || peer_req_length[lane] != 5 || restored_bursts >= 18 ||
              address !== ContextBase + 64'(restored_bursts * 40))
            $fatal(1, "HOST_CONTROL_RESTORE_ADDRESS %h", address);
          restored_bursts++;
        end else begin""")
    text = replace(text, "        read_address[lane] <= read_address[lane] +", """        if (read_address[lane] >= ContextBase && read_address[lane] < ContextBase + 720)
          restored_words++;
        read_address[lane] <= read_address[lane] +""")
    text = replace(text, "      context_words++;", "      stored_context[context_words] <= peer_write_data;\n      context_words++;")
    text = replace(text, "error || opcode != 5, 2", "error || (opcode != 4 && opcode != 5), 2")
    text = replace(text, "    logic [2047:0] expected, assembled;", """    logic [2047:0] expected, assembled;
    logic [127:0] addresses;
    logic [47:0] head_expected, head_received;""")
    text = replace(text, "    command(5, 32'h43010001, 1, '0);", """    addresses = {ValueBase, ContextBase};
    flit(16'hA674, 0, 1);
    for (int word = 0; word < 8; word++) flit(addresses[word * 16 +: 16], 0, 0);
    command(5, 32'h43010001, 1, '0);""")
    text = replace(text, "    command(4, 32'h43011111", """    command(3, 32'h43030010, 1, '0);
    response(3, 32'h43030010, 0);
    if (restored_bursts != 18 || restored_words != 90)
      $fatal(1, "HOST_CONTROL_RESTORE_COUNTS bursts=%0d words=%0d", restored_bursts, restored_words);
    $display("HOST_CONTROL_RELOCATED_PASS context=%h value=%h restored_words=%0d", ContextBase, ValueBase, restored_words);
    $fflush();
    command(4, 32'h43011111""")
    text = replace(text, """    while (!host_tx_valid) @(negedge clk);
    if ({head_done_id, head_done_inner, head_done_recent, head_done_streaming} !==
        {5'd0, 18'(inner), 18'(recent), 1'(streaming)}) $fatal(1, "PACKET_ATTENTION_PREDICTION");
    response(4, 32'h43011111, 0);
""", """    response(4, 32'h43011111, 0);
    head_expected = {6'd0, 5'd0, 18'(inner), 18'(recent), 1'(streaming)};
    for (int word = 0; word < 3; word++)
      receive(head_expected[word * 16 +: 16], word == 2, 2, head_received[word * 16 +: 16]);
    $display("HOST_CONTROL_HEAD_PASS prediction=%012h", head_received);
""")
    return replace(text, "host_words != 271", "host_words != 277")


def prepare(output, phase, evidence):
    def pin(path, expected=None):
        if str(path) not in evidence:
            evidence[str(path)] = digest(path)
        assert expected is None or evidence[str(path)] == expected, path
        return path

    prior = read(pin(RECORD))
    inputs = read(pin(link.ROOT / "prepared.json"))
    assert prior["cold_netlist_sha256"] == inputs["cold_netlist_sha256"]
    fixture = Path(inputs["fixture"]).relative_to(Path.cwd())
    for name in ("expected.hex", "map.hex", "signs.hex", "rows.txt"):
        path = fixture / name
        pin(path, prior["evidence_sha256"][str(path)])

    def previous(name):
        path = BASE / name
        return pin(path, prior["evidence_sha256"][str(path)]).read_text()

    rx, tx = (pin(output / mode / "netlist.v") for mode in ("rx", "tx"))
    changed, outer = wrappers(output, rx, tx, previous("wrapper.v"), previous("rotary_wrapper.v"), previous("attention_wrapper.v"))
    assert prior["top_level_signal_bits"] - width(outer) == 170
    changed[output / "attention_tb.sv"] = relocated_bench(previous("attention_tb.sv"))
    bundle_text = previous("wrapper_bundle.sv")
    substitutions = {
        link.ROOT / "host_rotary_link/genus/netlist.v": rx,
        link.ROOT / "host_attention_link/genus/netlist.v": tx,
        **{BASE / staged.name: staged for staged in changed},
    }
    for name in re.findall(r'(?m)^`include "([^"]+)"$', bundle_text):
        path = Path(name).relative_to(Path.cwd())
        pin(path, prior["evidence_sha256"][str(path)])
        if path in substitutions:
            bundle_text = replace(bundle_text, name, str(substitutions[path].resolve()))
    changed[output / "wrapper_bundle.sv"] = bundle_text
    for path, text in changed.items():
        if phase == "prepare":
            with path.open("x") as stream:
                stream.write(text)
        else:
            assert path.read_text() == text
            pin(path)
    return fixture, prior, width(outer), pin


def verify(output, fixture, prior, bits, pin):
    dump = pin(output / "rows.hex")
    baseline = BASE / "rows.hex"
    assert dump.read_bytes() == pin(baseline, prior["evidence_sha256"][str(baseline)]).read_bytes()
    log_path = pin(output / "native/xrun.log")
    log = log_path.read_text()
    status = read(pin(output / "native_status.json"))
    assert status["native_exit_status"] == 0 and status["stop_reason"] is None and status["log_sha256"] == digest(log_path)
    history = pin(output / "native/xrun.history").read_text()
    argv = shlex.split(re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1])
    assert argv[argv.index("-top") + 1] == link.BENCH
    assert str((output / "wrapper_bundle.sv").resolve()) in argv
    assert f"+FIXTURE={fixture.resolve()}" in argv and f"+DUMP={dump.resolve()}" in argv
    assert not re.search(r"\*[EF],", log) and log.count("Simulation complete via $finish(1)") == 1
    assert log.count("TOKEN_SIGN_FETCH_PASS vectors=576 bursts=577 faults=1") == 1
    assert log.count(f"HOST_CONTROL_RELOCATED_PASS context={CONTEXT_BASE:016x} value={VALUE_BASE:016x} restored_words=90") == 1
    _, _, _, inner, recent, streaming = map(int, (fixture / "rows.txt").read_text().splitlines()[1].split())
    predicted = (inner << 19) | (recent << 1) | streaming
    assert log.count(f"HOST_CONTROL_HEAD_PASS prediction={predicted:012x}") == 1
    assert log.count("COLD_PACKET_ATTENTION_PASS rows=2 host_words=277 maps=576 context_words=90 reads=9292 value_reads=206 wide=989 auxiliary=783") == 1

    timing = {}
    for mode in ("rx", "tx"):
        stage = output / mode
        assert f"TRI_ORACLE_HOST_CONTROL_GENUS_FINISHED {mode}" in pin(stage / "console.log").read_text()
        assert "No unresolved references" in pin(stage / "mapped_check.rpt").read_text()
        assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", pin(stage / "constraints.sdc").read_text())
        slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(stage / "timing.rpt").read_text())))
        assert slack >= 0
        area = pin(stage / "area.rpt").read_text()
        assert "Operating conditions:   ssg0p9v125c" in area
        (cells, area_um2), = re.findall(rf"(?m)^\s*tri_oracle_host_control_{mode}\s+NA\s+(\d+)\s+([\d.]+)", area)
        timing[mode] = {"cells": int(cells), "area_um2": float(area_um2), "worst_setup_slack_ps": slack}
    modes = {"rtl": (RTL, TEST), "mapped": (output / "rx/netlist.v", output / "tx/netlist.v", rotary.MODEL, TEST)}
    for phase, required in modes.items():
        location = output / phase
        source = pin(location / "xrun.history").read_text()
        command = shlex.split(re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", source)[-1])
        assert all(str(pin(path).resolve()) in command for path in required)
        unit_log = pin(location / "console.log").read_text()
        assert not re.search(r"\*[EF],", unit_log) and unit_log.count("Simulation complete via $finish(1)") == 1
        assert "HOST_CONTROL_PASS legacy_words=3 rotary_words=64 head_words=3 attention_words=128" in unit_log
    assert "HOST_CONTROL_CONFIG_WHILE_BUSY" in pin(output / "red/console.log").read_text()
    for path in (Path(__file__), Path("syn/tri_oracle_synthesize_host_control.tcl")):
        pin(path)
    roles = dict(prior["remaining_parallel_signal_bits_by_role"])
    assert roles.pop("memory_base_addresses") == 128 and roles.pop("head_prediction_result") == 42
    return {
        "state": "mapped_host_address_configuration_and_head_results_verified_on_cold_whole_chip",
        "cold_netlist_sha256": prior["cold_netlist_sha256"],
        "removed_parallel_signals": 170, "top_level_signal_bits": bits,
        "modeled_pad_sites_with_two_edge_receive": prior["modeled_pad_sites_with_two_edge_receive"] - 170,
        "clear_sites_in_current_floorplan": prior["clear_sites_in_current_floorplan"],
        "remaining_parallel_signal_bits_by_role": roles,
        "configured_context_base": hex(CONTEXT_BASE), "configured_value_cache_base": hex(VALUE_BASE),
        "context_bytes_restored": 720, "matched_attention_output_bytes": 512,
        "prediction_words": 3, "target_period_ns": 1.72414, "isolated_mapping": timing,
        "native_resources": status,
        "scope": "The mapped chip accepted relocated context and value-memory bases over the host link. It wrote "
                 "and restored all 576 token origins, returned one trained head prediction over the link, and "
                 "reproduced two trained attention rows. A testbench supplied external memory. The new "
                 "boundary still needs placement qualification and a physical pad interface.",
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
        print(result[0].resolve())
    else:
        print(json.dumps(verify(args.directory, *result) | {"evidence_sha256": evidence}, indent=2, sort_keys=True))
