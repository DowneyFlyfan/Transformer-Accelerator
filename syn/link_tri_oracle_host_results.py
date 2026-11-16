"""Bind independently mapped grouped and writeback transmitters to the cold chip."""

import argparse
import hashlib
import json
import mmap
from pathlib import Path
import re
import shlex

import link_tri_oracle_chip_packet_io as chip
from audit_tri_oracle_physical_io_budget import INTERFACE
from link_tri_oracle_indexed_whole_chip import module_at, spans, update_instance
from link_tri_oracle_narrow_host import declarations, width
from measure_tri_oracle_serial_memory_requests import digest, read, replace
from verify_tri_oracle_host_control import original_links, outer_ports, replace_instance
from verify_tri_oracle_host_grouped import BATCH, TX as GROUP_TX
from verify_tri_oracle_host_normalization import WRAPPER
from verify_tri_oracle_host_projection import include
from verify_tri_oracle_host_writeback import TX as WRITEBACK_TX, WRITER


BASE = chip.ROOT / "host_normalization"
CONTROL = chip.ROOT / "host_control"
RESULT_TOP = "tri_oracle_chip_host_results_io"
GROUP = {
    "group_valid": ("OUTPUT", None),
    "group_ready": ("INPUT", None),
    "group_last": ("OUTPUT", None),
    "group_tag": ("OUTPUT", 32),
    "group_cluster": ("OUTPUT", 3),
    "group_lane": ("OUTPUT", 2),
    "group_values": ("OUTPUT", 2048),
}
GROUP_PINS = {"group_valid": "result_valid", "group_last": "result_last",
              "group_cluster": "result_cluster", "group_lane": "result_lane",
              "group_values": "result_data"}
WRITEBACK = frozenset(INTERFACE["writeback_result"].split()) - {"wb_frame_active", "wb_packet_error"}
HOST = ("valid", "ready", "last", "data")


def patch_cold(source):
    original = source.decode()
    bank = original_links(original, (WRITER, "bank_writeback"))
    batch = original_links(original, (BATCH, "batch"))
    assert batch["result_ready"] == bank["out_ready"] == "wb_out_ready"
    assert "wire [31:0] layer_command_tag;" in original
    sources = {group: batch[port] for group, port in GROUP_PINS.items()} | {"group_tag": "layer_command_tag"}
    assert all(len(re.findall(rb"\b" + name.encode() + rb"\b", source)) == 0 for name in GROUP)
    header, _, body = source.partition(b");")
    header += b"".join(b",\n\t" + name.encode() for name in GROUP)
    declared = b"".join(f"   {direction.lower()} {'[' + str(bits-1) + ':0] ' if bits else ''}{name};\n".encode()
                        for name, (direction, bits) in GROUP.items())
    aliases = b"".join(f"   assign {port} = {net};\n".encode() for port, net in sources.items())
    connected = update_instance(header + b");\n" + declared + body, BATCH, "batch",
                                update={"result_ready": b"group_ready"})
    assert chip.ports(connected) == chip.ports(source) | GROUP
    assert original_links(connected.decode(), (BATCH, "batch")) == batch | {"result_ready": "group_ready"}
    assert original_links(connected.decode(), (WRITER, "bank_writeback")) == bank
    assert connected.endswith(b"endmodule")
    return connected.removesuffix(b"endmodule") + aliases + b"endmodule"


def extend_wrapper(source, child):
    external = outer_ports(source)
    original = original_links(source, child)
    assert not external.keys() & GROUP.keys() and not original.keys() & GROUP.keys()
    revised = replace(source, ",\n".join(declarations(external)), ",\n".join(declarations(external | GROUP)))
    return replace_instance(revised, child, child, original, original | {name: name for name in GROUP})


def result_wrapper(outer, path_group, path_writeback):
    original = outer_ports(outer)
    exposed = {name: spec for name, spec in original.items() if name not in WRITEBACK}
    wrapped = f"module {RESULT_TOP} (\n" + ",\n".join(declarations(exposed)) + "\n);\n"
    for name in WRITEBACK:
        assert name.startswith("wb_out_")
    local = {name: original[name] for name in original if name in WRITEBACK} | GROUP
    wrapped += "".join(line + ";\n" for line in declarations(local, wires=True))
    for prefix in ("ordinary", "combined"):
        wrapped += f"  wire {prefix}_valid, {prefix}_ready, {prefix}_last;\n"
        wrapped += f"  wire [15:0] {prefix}_data;\n"
    bindings = {name: name for name in original | GROUP}
    bindings.update({f"host_tx_{field}": f"ordinary_{field}" for field in HOST})
    wrapped += chip.instance(WRAPPER, "normalization", bindings)

    def link(label, prefix):
        return {f"{label}_{field}": f"{prefix}_{field}" for field in HOST}

    common = {"clk": "clk", "rst_n": "rst_n"}
    grouped = common | link("source", "ordinary") | {name: name for name in GROUP} | link("tx", "combined")
    writeback = common | link("source", "combined") | {
        name.replace("_out_", "_"): name for name in original if name in WRITEBACK
    } | link("tx", "host_tx")
    for master, label, path, ports in (
        (GROUP_TX, "grouped_tx", path_group, grouped),
        (WRITEBACK_TX, "writeback_tx", path_writeback, writeback),
    ):
        mapped = path.read_bytes()
        assert set(spans(mapped)) == {master}
        assert chip.ports(mapped).keys() == ports.keys()
        wrapped += chip.instance(master, label, ports)
    return wrapped + "endmodule\n", exposed


def prepare(output, phase):
    evidence = {}

    def pin(path, expected=None):
        if str(path) not in evidence:
            evidence[str(path)] = digest(path)
        assert expected is None or evidence[str(path)] == expected, path
        return path

    def record(name):
        return read(pin(Path(f"records/tri_oracle_host_{name}_packets.json")))

    normalization, grouped, writeback = map(record, ("normalization", "grouped", "writeback"))
    assert len({item["cold_netlist_sha256"] for item in (normalization, grouped, writeback)}) == 1
    placement = read(pin(Path("records/tri_oracle_repacked_whole_chip_cold_reload.json")))
    (cold,) = (Path(name) for name in placement["evidence_sha256"] if name.endswith("/cold.v"))
    pin(cold, normalization["cold_netlist_sha256"])
    grouped_map = chip.ROOT / "host_grouped/genus/netlist.v"
    writeback_map = chip.ROOT / "host_writeback/genus/netlist.v"
    pin(grouped_map, grouped["evidence_sha256"][str(grouped_map)])
    pin(writeback_map, writeback["evidence_sha256"][str(writeback_map)])

    def norm(path):
        return pin(path, normalization["evidence_sha256"][str(path)])

    revised_cold = output / "cold_results.v"
    with cold.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        index = spans(data)
        start, stop = index[chip.TOP]
        revised = patch_cold(module_at(data, index, chip.TOP))
        parts = [*(memoryview(data)[pos:min(pos + 2**22, start)] for pos in range(0, start, 2**22)),
                 revised,
                 *(memoryview(data)[pos:pos + 2**22] for pos in range(stop, len(data), 2**22))]
        expected = hashlib.sha256()
        if phase == "prepare":
            with revised_cold.open("xb") as target:
                for chunk in parts:
                    target.write(chunk)
                    expected.update(chunk)
        else:
            for chunk in parts:
                expected.update(chunk)
        del parts, chunk
    pin(revised_cold, expected.hexdigest())
    generated = {}
    substitutions = {cold: revised_cold}
    wrappers = {
        CONTROL / "wrapper.v": (chip.TOP, "accelerator"),
        CONTROL / "rotary_wrapper.v": (chip.WRAPPER, "chip"),
        CONTROL / "attention_wrapper.v": ("tri_oracle_chip_rotary_packet_io", "chip"),
        BASE / "projection_wrapper.v": ("tri_oracle_chip_attention_packet_io", "chip"),
    }
    for old, child in wrappers.items():
        new = output / old.name
        substitutions[old] = new
        generated[new] = extend_wrapper(norm(old).read_text(), child).encode()
    wrapped, exposed = result_wrapper(norm(BASE / "projection_wrapper.v").read_text(), grouped_map, writeback_map)
    generated[output / "results_wrapper.v"] = wrapped.encode()
    source = norm(BASE / "attention_tb.sv").read_text()
    old = (WRAPPER, "dut")
    links = original_links(source, old)
    assert set(links) - WRITEBACK == exposed.keys()
    bench = output / "attention_tb.sv"
    generated[bench] = replace_instance(source, old, (RESULT_TOP, "dut"), links, {name: links[name] for name in exposed}).encode()
    bundle = norm(BASE / "wrapper_bundle.sv").read_text()
    for label in re.findall(r'(?m)^`include "([^"]+)"$', bundle):
        path = Path(label).relative_to(Path.cwd())
        if path != cold:
            norm(path)
        if path == BASE / "attention_tb.sv":
            addition = "".join(include(item) for item in (grouped_map, writeback_map,
                                                            output / "results_wrapper.v", bench))
            bundle = replace(bundle, include(path), addition)
        elif path in substitutions:
            bundle = replace(bundle, include(path), include(substitutions[path]))
    generated[output / "wrapper_bundle.sv"] = bundle.encode()
    for path, data in generated.items():
        if phase == "prepare":
            with path.open("xb") as stream:
                stream.write(data)
        else:
            assert path.read_bytes() == data, path
        pin(path)
    removed = normalization["top_level_signal_bits"] - width(exposed)
    assert removed == writeback["parallel_writeback_signals_targeted"] == 187
    modeled = normalization["modeled_pad_sites_with_two_edge_receive"] - removed
    free = normalization["clear_sites_in_current_floorplan"]
    pin(Path(__file__).resolve().relative_to(Path.cwd()))
    return {
        "state": "host_grouped_and_writeback_connection_verified_structurally",
        "baseline_cold_netlist_sha256": normalization["cold_netlist_sha256"],
        "top_level_signal_bits": width(exposed),
        "parallel_signals_removed": removed,
        "modeled_pad_sites": modeled,
        "clear_sites_in_current_floorplan": free,
        "site_shortfall": modeled - free,
        "evidence_sha256": evidence,
    }


def verify_native(output, result):
    evidence = result["evidence_sha256"]
    native = output / "native"

    def pin(path, expected=None):
        evidence[str(path)] = digest(path)
        assert expected is None or evidence[str(path)] == expected, path
        return path

    prepared = read(pin(chip.ROOT / "prepared.json"))
    norm = read(pin(Path("records/tri_oracle_host_normalization_packets.json")))
    assert prepared["cold_netlist_sha256"] == result["baseline_cold_netlist_sha256"]
    log = native / "xrun.log"
    status = read(pin(output / "native_status.json"))
    assert status["native_exit_status"] == 0 and status["stop_reason"] is None
    transcript = pin(log, status["log_sha256"]).read_text()
    history = pin(native / "xrun.history").read_text()
    argv = shlex.split(re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1])
    assert argv[argv.index("-top") + 1] == chip.BENCH
    assert str((output / "wrapper_bundle.sv").resolve()) in argv
    assert f"+FIXTURE={Path(prepared['fixture']).resolve()}" in argv
    dump = pin(output / "rows.hex")
    assert f"+DUMP={dump.resolve()}" in argv
    assert "COLD_PACKET_ATTENTION_PASS rows=2 host_words=277 maps=576 context_words=90" in transcript
    assert transcript.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", transcript)
    baseline = BASE / "rows.hex"
    assert dump.read_bytes() == pin(baseline, norm["evidence_sha256"][str(baseline)]).read_bytes()
    return result | {
        "state": "whole_chip_attention_replayed_after_grouped_and_writeback_binding",
        "whole_chip_matched_attention_rows": 2,
        "native_resources": status,
        "scope": "Xcelium smoke drives the existing scalar attention commands through the integrated wrapper. "
                 "Active grouped and writeback packets are qualified at the mapped cuts. Active whole-chip "
                 "grouped and feed-forward execution, pad implementation and timing remain unqualified.",
    }


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify", "verify-native"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = prepare(args.directory, args.phase)
    if args.phase == "verify-native":
        result = verify_native(args.directory, result)
    print(json.dumps(result, indent=2, sort_keys=True))
