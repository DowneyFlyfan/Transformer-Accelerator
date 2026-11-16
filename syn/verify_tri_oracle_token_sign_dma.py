"""Verify the learned token map with sign fetches on the whole-chip memory link."""

import argparse
import json
from pathlib import Path
import re
import shlex

import link_tri_oracle_chip_packet_io as link
import verify_tri_oracle_host_attention as attention
import verify_tri_oracle_host_rotary as rotary
from audit_tri_oracle_physical_io_budget import INTERFACE
from link_tri_oracle_indexed_whole_chip import module_at, pins, spans
from link_tri_oracle_narrow_host import declarations, width
from measure_tri_oracle_serial_memory_requests import digest, read, replace


DMA = "tri_oracle_token_sign_dma"
BASE = link.ROOT / "host_attention_link"
RECORD = Path("records/tri_oracle_host_attention_packets.json")
RTL = Path(f"verilog/{DMA}.sv")
TEST = Path(f"verilog/{DMA}_tb.sv")
SIGN_PORTS = frozenset(INTERFACE["token_signs_and_origins"].split())


def bind_dma(core, adapters, outer, internal, mapped):
    used_signals = {name: outer[name] for name in ("sign_valid", "sign_ready", "sign_data")}
    removed = {name: outer[name] for name in SIGN_PORTS}
    exposed = {name: shape for name, shape in outer.items() if name not in removed}
    assert width(removed) == 2073
    aux = {"aux_" + field: core["aux_" + field] for field in link.MEMORY_FIELDS}
    dma_aux = {"dma_" + name: shape for name, shape in aux.items()}
    controls = {"merge_start": ("INPUT", None), "merge_finish": ("INPUT", None), "config_valid": ("INPUT", None)}
    signals = {
        "clk": "clk", "rst_n": "rst_n",
        **{name: name for name in controls | used_signals},
        "config_line": "payload_data[63:28]",
        **{"native_" + field: "aux_" + field for field in link.MEMORY_FIELDS},
        **{field: "dma_aux_" + field for field in link.MEMORY_FIELDS},
    }
    data = mapped.read_bytes()
    index = spans(data)
    assert set(index) == {DMA}
    expected = {"clk": ("INPUT", None), "rst_n": ("INPUT", None), "config_line": ("INPUT", 36)} | controls
    for port in link.MEMORY_FIELDS:
        direction, size = aux["aux_" + port]
        expected[port] = (direction, size)
        expected["native_" + port] = ("OUTPUT" if direction == "INPUT" else "INPUT", size)
    for name, (direction, size) in used_signals.items():
        expected[name] = ("OUTPUT" if direction == "INPUT" else "INPUT", size)
    assert link.ports(module_at(data, index, DMA)) == expected

    original = link.wrapper_text(core, adapters, outer, internal)
    text = replace(original, ",\n".join(declarations(outer)), ",\n".join(declarations(exposed)))
    chip = {name: name for name in core}
    chip.update(map_ready="1'b1", map_valid="", map_last="", map_index="", map_origin="")
    text = replace(text, link.instance(link.TOP, "accelerator", dict(zip(core, core, strict=True))),
                   link.instance(link.TOP, "accelerator", chip))
    previous_memory = adapters[link.MEMORY]
    memory = {pin: re.sub(r"\baux_\w+\b", lambda match: "dma_" + match[0], net)
              for pin, net in previous_memory.items()}
    assert set(name for name in memory if memory[name] != previous_memory[name]) == set(link.MEMORY_FIELDS)
    text = replace(text, link.instance(link.MEMORY, "memory_link", previous_memory),
                   link.instance(link.MEMORY, "memory_link", memory))
    wires = "".join(decl + ";\n" for decl in declarations(used_signals | dma_aux | controls, wires=True))
    assertions = (
        "  assign merge_start = command_valid && command_ready && command_opcode == 3'd2;\n"
        "  assign merge_finish = response_valid && response_opcode == 3'd2;\n"
        "  assign config_valid = payload_valid && payload_ready && payload_last;\n"
    )
    text = replace(text, "\n);\n", "\n);\n" + wires)
    text = replace(text, "\nendmodule\n", "\n" + assertions + link.instance(DMA, "sign_fetch", signals) + "endmodule\n")
    assert pins(text.encode(), DMA, "sign_fetch") == {pin: net.encode() for pin, net in signals.items()}
    assert pins(text.encode(), link.TOP, "accelerator") == {pin: net.encode() for pin, net in chip.items()}
    assert pins(text.encode(), link.MEMORY, "memory_link") == {pin: net.replace(" ", "").encode() for pin, net in memory.items()}
    return text, exposed


def exercise_memory(text):
    text = replace(text, "  bit clk = 0, rst_n = 0;", "  localparam logic [63:0] SignBase = 64'h40000000;\n  bit clk = 0, rst_n = 0;")
    text = replace(text, "  logic sign_valid = 0, sign_ready, map_valid, map_last;\n"
                         "  logic [2047:0] sign_data = '0;\n  logic [9:0] map_index, map_origin;\n", "")
    text = replace(text, "  logic [1023:0] memory_mem_rsp_data;", """  logic [1023:0] memory_mem_rsp_data;
  logic [1:0] memory_mem_rsp_error;
  bit sign_fault = 0;
  int sign_reads, sign_vectors, sign_errors;""")
    text = replace(text, "  assign memory_mem_rsp_valid =", """  assign memory_mem_rsp_error = {reading[1] && sign_fault && read_remaining[1] == 4, 1'b0};
  assign memory_mem_rsp_valid =""")
    text = replace(text, "    slot = int'(address[15:6]);", """    if (address >= SignBase)
      return signs[int'((address - SignBase) >> 8)][int'(address[7:6]) * 512 +: 512];
    slot = int'(address[15:6]);""")
    text = replace(text, """    if (map_valid) begin
      if (maps >= ImageTokens || map_index !== 10'(maps) || map_origin !== golden_map[maps] ||
          map_last !== (maps == ImageTokens - 1)) $fatal(1, "PACKET_ATTENTION_MAP index=%0d", maps);
      maps++;
    end
""", "")
    start = text.index("        if (peer_req_length[lane] == 0")
    end = text.index("        read_address[lane] <= address;", start)
    original_check = text[start:end]
    text = replace(text, original_check, """        if (address >= SignBase) begin
          if (lane != 1 || !peer_wide || peer_req_length[lane] != 4 || sign_vectors >= ImageTokens ||
              address !== SignBase + 64'(sign_vectors * 256))
            $fatal(1, "SIGN_PACKET_ADDRESS lane=%0d token=%0d address=%h", lane, sign_vectors, address);
          sign_fault <= sign_reads == 0;
          sign_reads++;
        end else begin
""" + "".join("  " + line for line in original_check.splitlines(keepends=True)) + "        end\n")
    text = replace(text, "        read_address[lane] <= read_address[lane] +", """        if (read_address[lane] >= SignBase && read_remaining[lane] == 1) begin
          if (sign_fault) sign_errors++;
          else sign_vectors++;
          sign_fault <= 0;
        end
        read_address[lane] <= read_address[lane] +""")
    text = replace(text, "      context_words++;", "      context_words++;\n      if (peer_write_last) maps += 32;")
    text = replace(text, """    command(2, 32'h43020000, 1, 192'({12'd1536, 10'(image_start), 5'd0, 1'b1}));
    for (int index = 0; index < ImageTokens; index++) begin
      sign_valid = 1;
      sign_data = signs[index];
      do @(posedge clk); while (!sign_ready);
      @(negedge clk);
    end
    sign_valid = 0;
""", """    command(2, 32'h43020000, 1, 192'({SignBase[41:6], 12'd1536, 10'(image_start), 5'd0, 1'b1}));
""")
    text = replace(text, "    $display(\"PACKET_ATTENTION_CONTEXT_PASS", """    if (sign_reads != ImageTokens + 1 || sign_vectors != ImageTokens || sign_errors != 1)
      $fatal(1, "SIGN_PACKET_INVENTORY signs=%0d reads=%0d faults=%0d", sign_vectors, sign_reads, sign_errors);
    $display("TOKEN_SIGN_FETCH_PASS vectors=%0d bursts=%0d faults=%0d", sign_vectors, sign_reads, sign_errors);
    $fflush();
    $display("PACKET_ATTENTION_CONTEXT_PASS""")
    text = replace(text, "  initial begin\n    #10000000;", """  initial begin
    #200000;
    if (sign_vectors != ImageTokens || context_acks != 18)
      $fatal(1, "SIGN_PACKET_FRAME_TIMEOUT signs=%0d reads=%0d faults=%0d map_acks=%0d",
             sign_vectors, sign_reads, sign_errors, context_acks);
  end

  initial begin
    #10000000;""")
    return text


def prepare(output, phase, evidence):
    def pin(path, expected=None):
        evidence[str(path)] = digest(path)
        assert expected is None or evidence[str(path)] == expected, path
        return path

    prior = read(pin(RECORD))
    prepared = read(pin(link.ROOT / "prepared.json"))
    assert prior["cold_netlist_sha256"] == prepared["cold_netlist_sha256"]
    fixture = Path(prepared["fixture"]).relative_to(Path.cwd())
    for kind in ("expected.hex", "map.hex", "signs.hex", "rows.txt"):
        path = fixture / kind
        pin(path, prior["evidence_sha256"][str(path)])
    cold, _, core, adapters, outer, internal, _, _, identities = link.load()
    assert identities[str(cold)] == prior["cold_netlist_sha256"]
    source = BASE / "wrapper_bundle.sv"
    base = pin(source, prior["evidence_sha256"][str(source)]).read_text()
    rot_netlist = link.ROOT / "host_rotary_link/genus/netlist.v"
    att_netlist = BASE / "genus/netlist.v"
    fetch_netlist = pin(output / "genus/netlist.v")
    inner, exposed = bind_dma(core, adapters, outer, internal, fetch_netlist)
    rot, exposed = rotary.wrapper_text(exposed, rot_netlist)
    att, exposed = attention.wrap(att_netlist, exposed)
    assert prior["top_level_signal_bits"] - width(exposed) == 2073
    remaining_roles = {role: width({name: exposed[name] for name in names.split() if name in exposed})
                       for role, names in INTERFACE.items() if role != "clock_and_reset"}
    remaining_roles = {role: bits for role, bits in remaining_roles.items() if bits}
    assert sum(remaining_roles.values()) == 1188
    connected = (attention.CONNECTED | {"memory_mem_rsp_error"}) - SIGN_PORTS
    tied = {name: value for name, value in attention.INPUTS.items() if name not in SIGN_PORTS}
    linked = {name: name if name in connected or name.startswith("host_") else
              tied.get(name, "'0" if direction == "INPUT" else "")
              for name, (direction, _) in exposed.items()}
    stimulus = exercise_memory(pin(attention.TEMPLATE).read_text())
    bench = replace(stimulus, "  // CHIP_INSTANCE", link.instance(attention.WRAPPER, "dut", linked).rstrip())
    wrappers = {output / "wrapper.v": inner, output / "rotary_wrapper.v": rot,
                output / "attention_wrapper.v": att, output / "attention_tb.sv": bench}
    replacements = {"wrapper.v", "rotary_wrapper.v", "attention_wrapper.v", "attention_tb.sv"}

    def include(path):
        return f'`include "{path.resolve()}"\n'

    for path_text in re.findall(r'(?m)^`include "([^"]+)"$', base):
        path = Path(path_text).relative_to(Path.cwd())
        pin(path, prior["evidence_sha256"][str(path)])
        if path.name in replacements:
            base = replace(base, include(path), (include(fetch_netlist) if path.name == "wrapper.v" else "") +
                           include(output / path.name))
    wrappers[output / "wrapper_bundle.sv"] = base
    for path, content in wrappers.items():
        if phase == "prepare":
            with path.open("x") as stream:
                stream.write(content)
        else:
            assert path.read_text() == content
            pin(path)
    return fixture, prior, width(exposed), remaining_roles, pin


def verify(output, fixture, prior, signal_bits, remaining_roles, pin):
    log_path = pin(output / "native/xrun.log")
    log = log_path.read_text()
    status = read(pin(output / "native_status.json"))
    assert status["native_exit_status"] == 0 and status["stop_reason"] is None
    assert status["log_sha256"] == digest(log_path)
    dump = pin(output / "rows.hex")
    before = pin(BASE / "rows.hex", prior["evidence_sha256"][str(BASE / "rows.hex")])
    assert dump.read_bytes() == before.read_bytes()
    raw_history = pin(output / "native/xrun.history").read_text()
    argv = shlex.split(re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", raw_history)[-1])
    assert argv[argv.index("-top") + 1] == link.BENCH and str((output / "wrapper_bundle.sv").resolve()) in argv
    assert f"+FIXTURE={fixture.resolve()}" in argv and f"+DUMP={dump.resolve()}" in argv
    assert not re.search(r"\*[EF],", log) and log.count("Simulation complete via $finish(1)") == 1
    assert log.count("TOKEN_SIGN_FETCH_PASS vectors=576 bursts=577 faults=1") == 1
    assert log.count("COLD_PACKET_ATTENTION_PASS rows=2 host_words=271 maps=576 context_words=90 "
                     "reads=9274 value_reads=206 wide=989 auxiliary=783") == 1

    mapped = output / "genus"
    assert "TRI_ORACLE_SIGN_DMA_GENUS_FINISHED" in pin(mapped / "console.log").read_text()
    assert "No unresolved references" in pin(mapped / "mapped_check.rpt").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", pin(mapped / "constraints.sdc").read_text())
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(mapped / "timing.rpt").read_text())))
    assert slack >= 0
    area = pin(mapped / "area.rpt").read_text()
    assert "Operating conditions:   ssg0p9v125c" in area
    (cells, area_um2), = re.findall(rf"(?m)^\s*{DMA}\s+NA\s+(\d+)\s+([\d.]+)", area)
    for mode, sources in (("rtl", (RTL, TEST)), ("mapped", (mapped / "netlist.v", rotary.MODEL, TEST))):
        unit_log = pin(output / mode / "console.log").read_text()
        history = pin(output / mode / "xrun.history").read_text()
        command = shlex.split(re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1])
        assert all(str(pin(source).resolve()) in command for source in sources)
        assert "TOKEN_SIGN_DMA_PASS vectors=2 reads=5 native=2 retries=1" in unit_log
        assert unit_log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", unit_log)
    assert "TOKEN_SIGN_DMA_TIMEOUT" in pin(output / "red/console.log").read_text()
    assert "TOKEN_SIGN_DMA_TIMEOUT" in pin(output / "ready_dependency/console.log").read_text()
    for path in (Path(__file__), Path("syn/tri_oracle_synthesize_token_sign_dma.tcl")):
        pin(path)

    def context_time(text):
        match, = re.findall(r"(?m)^PACKET_ATTENTION_CONTEXT_PASS maps=576 at (\d+)\.00 ns$", text)
        return int(match)
    before_log = pin(BASE / "native/xrun.log", prior["evidence_sha256"][str(BASE / "native/xrun.log")]).read_text()
    return {
        "state": "mapped_token_sign_fetch_verified_through_the_cold_whole_chip_memory_link",
        "cold_netlist_sha256": prior["cold_netlist_sha256"],
        "removed_token_sign_and_map_signals": 2073, "top_level_signal_bits": signal_bits,
        "modeled_pad_sites_with_two_edge_receive": prior["modeled_pad_sites_with_two_edge_receive"] - 2073,
        "clear_sites_in_current_floorplan": prior["clear_sites_in_current_floorplan"],
        "remaining_parallel_signal_bits_by_role": remaining_roles,
        "sign_vectors": 576, "sign_bytes": 576 * 256, "retried_bursts": 1,
        "context_bytes_matched": 720, "attention_output_bytes_matched": 512,
        "merge_host_response_time_delta_cycles": (context_time(log) - context_time(before_log)) // 10,
        "isolated_mapping": {"cells": int(cells), "area_um2": float(area_um2),
                             "target_period_ns": 1.72414, "worst_setup_slack_ps": slack},
        "native_resources": status,
        "scope": "The mapped chip fetched 576 trained sign vectors, retried one transient response fault, wrote all "
                 "token origins and returned the same two attention rows. Signs and the projected query, key and value "
                 "operands were supplied by the external memory model. This verifies the transport and preserves "
                 "the need to qualify on-chip sign extraction, physical timing and full-model execution.",
    }


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    evidence = {}
    inputs = prepare(args.directory, args.phase, evidence)
    if args.phase == "prepare":
        print(inputs[0].resolve())
    else:
        print(json.dumps(verify(args.directory, *inputs) | {"evidence_sha256": evidence}, indent=2, sort_keys=True))
