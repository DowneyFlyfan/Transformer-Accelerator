"""Verify independent grouped-result retirement through the mapped host link."""

import argparse
import json
import mmap
from pathlib import Path
import re
import shlex

from link_tri_oracle_chip_packet_io import ROOT, TOP, instance, ports
from link_tri_oracle_indexed_whole_chip import module_at, spans
from measure_tri_oracle_serial_memory_requests import digest, read, replace
from verify_tri_oracle_host_control import original_links
from verify_tri_oracle_host_projection import INSTANCE, include
from verify_tri_oracle_host_rotary import MODEL
from verify_tri_oracle_host_writeback import TX as WRITEBACK


TX = "tri_oracle_host_grouped_tx"
BENCH = f"{TX}_tb"
BATCH = "tri_oracle_grouped_cluster_batch_cells"
TEST = Path(f"verilog/{BENCH}.sv")
RTL = Path(f"verilog/{TX}.sv")
SYNTH = Path(f"syn/tri_oracle_synthesize_host_grouped_tx.tcl")
MIXED = Path(".cache/residual_bank_command_binding/mixed/inputs.json")
ACTIVE = (0xf, 0xa, 0x5, 0x4, 0x9)
REFERENCE_SHA256 = "4cb588d54ffe6d3e67e356ce5090ba3bbb6dc9a0f875050d964e4f99427020cb"


def exact_batch(chip):
    with chip.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as netlist:
        index = spans(netlist)
        top = module_at(netlist, index, TOP).decode()
        connections = original_links(top, (BATCH, "batch"))
        assert connections["result_ready"] == "wb_out_ready"
        assert connections["result_data"] == "grouped_result_values"
        assert connections["result_valid"] == "grouped_out_valid"
        assert connections["result_last"] == "selected_result_last"
        body = module_at(netlist, index, BATCH)
        port_map = {}
        for name, (direction, bits) in ports(body).items():
            match = re.fullmatch(r"(cluster_result_(?:lane|data))\[([0-4])\]", name)
            if match:
                assert direction == "INPUT" and bits == (2 if match[1].endswith("lane") else 2048)
                port_map[f"\\{name} "] = name
            elif re.fullmatch(r"p\d+", name):
                # These are the flattened placement buffer outputs.
                assert (direction, bits) == ("OUTPUT", None)
                port_map[name] = ""
            else:
                port_map[name] = name
        modules, pending = {}, [BATCH]
        while pending:
            name = pending.pop()
            if name in modules:
                continue
            module = module_at(netlist, index, name)
            modules[name] = module
            pending.extend(child for match in INSTANCE.finditer(module)
                           if (child := match[1].decode()) in index)
    return b"\n".join(modules.values()) + b"\n", instance(BATCH, "batch", port_map)


def prepare(directory, phase, pin):
    placement = read(pin(Path("records/tri_oracle_repacked_whole_chip_cold_reload.json")))
    writeback = read(pin(Path("records/tri_oracle_host_writeback_packets.json")))
    assert placement["cold_netlist_sha256"] == writeback["cold_netlist_sha256"]
    (cold,) = (Path(name) for name in placement["evidence_sha256"] if name.endswith("/cold.v"))
    pin(cold, placement["cold_netlist_sha256"])
    standard = pin(MODEL, writeback["evidence_sha256"][str(MODEL)])
    previous_tx = ROOT / "host_writeback/genus/netlist.v"
    pin(previous_tx, writeback["evidence_sha256"][str(previous_tx)])
    old_data = previous_tx.read_bytes()
    assert set(spans(old_data)) == {WRITEBACK}
    mix = read(pin(MIXED))
    (fixture,) = (Path(arg.split("=", 1)[1]).relative_to(Path.cwd())
                  for arg in mix["args"] if arg.startswith("+ORACLE="))
    assert mix["inputs"][str(fixture.resolve())] == REFERENCE_SHA256
    pin(fixture, REFERENCE_SHA256)

    mapped_path = pin(directory / "genus/netlist.v")
    cut_path, mapped_test = directory / "batch.v", directory / "mapped_tb.sv"
    machinery, inst = exact_batch(cold)
    start, end = "  // BATCH_INSTANCE\n", "  // END_BATCH_INSTANCE\n"
    source = pin(TEST).read_text()
    old = source[source.index(start) + len(start):source.index(end)]
    test = replace(source, old, inst).encode()
    generated = {
        cut_path: machinery,
        mapped_test: test,
        directory / "mapped_bundle.sv": "".join(include(path) for path in
            (standard, cut_path, mapped_path, previous_tx, mapped_test)).encode(),
    }
    for path, content in generated.items():
        if phase == "prepare":
            with path.open("xb") as stream:
                stream.write(content)
        else:
            assert path.read_bytes() == content, path
            pin(path)
    return fixture, placement["cold_netlist_sha256"]


def verify(directory, fixture, cold_sha, pin):
    def simulation(name, sources):
        run = directory / name
        history = pin(run / "xrun.history").read_text()
        argv = shlex.split(re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1])
        assert argv[argv.index("-top") + 1] == BENCH
        assert all(str(pin(path).resolve()) in argv for path in sources)
        dump = pin(run / "rows.hex")
        assert f"+FIXTURE={fixture.resolve()}" in argv and f"+DUMP={dump.resolve()}" in argv
        return pin(run / "console.log").read_text(), dump.read_text().splitlines()

    rtl_common = (TEST, Path("verilog/tri_oracle_grouped_cluster_batch.sv"), Path(f"verilog/{WRITEBACK}.sv"))
    red, empty = simulation("red", (directory / "red/baseline.sv", *rtl_common))
    assert not empty and "GROUPED_ACK_BEFORE_FINAL_WORD groups=0 word=0" in red
    assert "Simulation terminated via $fatal(1)" in red
    fixture_rows = fixture.read_text().splitlines()
    assert len(fixture_rows) == 20 and all(re.fullmatch(r"[0-9a-f]{512}", row) for row in fixture_rows)
    results = {}
    for name, sources in {"rtl": (RTL, *rtl_common), "mapped": (directory / "mapped_bundle.sv",)}.items():
        log, dump = simulation(name, sources)
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        (held, overlap), = re.findall(
            r"^GROUPED_HOST_TX_PASS groups=11 values=704 command_frames=4 writeback_frames=11 held=(\d+) overlap=(\d+)$",
            log, re.M)
        assert int(held) > 0 and int(overlap) > 0
        remaining = list(ACTIVE)
        assert len(dump) == 11
        for row in dump:
            cluster, lane, last, data = row.split()
            cluster, lane, last = int(cluster), int(lane), int(last)
            assert 0 <= cluster < 5 and 0 <= lane < 4 and remaining[cluster] & (1 << lane)
            remaining[cluster] &= ~(1 << lane)
            assert last == (remaining[cluster] == 0) and data == fixture_rows[4 * cluster + lane]
        assert not any(remaining)
        results[name] = {"held_host_words": int(held), "concurrent_writeback_cycles": int(overlap)}

    genus = directory / "genus"
    assert "TRI_ORACLE_HOST_GROUPED_TX_GENUS_FINISHED" in pin(genus / "console.log").read_text()
    assert "No unresolved references" in pin(genus / "mapped_check.rpt").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", pin(genus / "constraints.sdc").read_text())
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(genus / "timing.rpt").read_text())))
    assert slack >= 0
    area = pin(genus / "area.rpt").read_text()
    assert "Operating conditions:   ssg0p9v125c" in area
    (cells, area_um2), = re.findall(rf"(?m)^\s*{TX}\s+NA\s+(\d+)\s+([\d.]+)", area)
    for path in (SYNTH, Path(__file__).resolve().relative_to(Path.cwd())):
        pin(path)
    return {
        "state": "mapped_grouped_result_retirement_and_shared_host_link_verified",
        "cold_netlist_sha256": cold_sha,
        "cluster_count": len(ACTIVE),
        "grouped_attention_rows": 11,
        "trained_grouped_values": 704,
        "command_frames": 4,
        "writeback_frames": 11,
        "words_per_grouped_row": 132,
        "isolated_mapping": {"target_period_ns": 1.72414, "worst_setup_slack_ps": slack,
                             "cells": int(cells), "area_um2": float(area_um2)},
        "simulations": results,
        "scope": "Exact cold-chip mapped batch arbiter is connected to both mapped transmitters. The five "
                 "cluster inputs use the archived mixed-attention reference. Command and writeback "
                 "traffic are testbench stimuli. This proves packet retention and backpressure at "
                 "the cut, with the full-chip connection and physical interface still unqualified.",
    }


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    evidence = {}

    def pin(path, expected=None):
        if str(path) not in evidence:
            evidence[str(path)] = digest(path)
        assert expected is None or evidence[str(path)] == expected, path
        return path

    prepared = prepare(args.directory, args.phase, pin)
    if args.phase == "verify":
        print(json.dumps(verify(args.directory, *prepared, pin) | {"evidence_sha256": evidence},
                         indent=2, sort_keys=True))
