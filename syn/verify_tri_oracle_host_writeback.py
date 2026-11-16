"""Verify the host writeback transmitter with the exact mapped bank writer."""

import argparse
import json
import mmap
from pathlib import Path
import re
import shlex

from link_tri_oracle_chip_packet_io import ROOT, TOP, ports
from link_tri_oracle_indexed_whole_chip import module_at, spans
from measure_tri_oracle_serial_memory_requests import digest, read
from verify_tri_oracle_host_control import original_links
from verify_tri_oracle_host_projection import INSTANCE, include
from verify_tri_oracle_host_rotary import MODEL


TX = "tri_oracle_host_writeback_tx"
BENCH = f"{TX}_tb"
WRITER = "tri_oracle_decoder_bank_writeback"
RTL = Path(f"verilog/{TX}.sv")
TEST = Path(f"verilog/{BENCH}.sv")
SYNTH = Path(f"syn/tri_oracle_synthesize_host_writeback_tx.tcl")
NORM = ROOT / "host_normalization"
FIXTURE = Path(".cache/placement_coordinate_reuse/trained_layer11_boundary/"
               "live_chip_bridge_tail_checked/bridge_handoff.hex")


def exact_bank_writer(path):
    with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as netlist:
        index = spans(netlist)
        top = module_at(netlist, index, TOP).decode()
        bank = original_links(top, (WRITER, "bank_writeback"))
        grouped = original_links(top, ("tri_oracle_grouped_cluster_batch_cells", "batch"))
        assert bank["out_ready"] == grouped["result_ready"] == "wb_out_ready"
        assert bank["out_valid"] == "wb_out_valid" and grouped["result_valid"] == "grouped_out_valid"
        modules, pending = {}, [WRITER]
        while pending:
            name = pending.pop()
            if name in modules:
                continue
            body = module_at(netlist, index, name)
            modules[name] = body
            pending.extend(child for match in INSTANCE.finditer(body)
                           if (child := match[1].decode()) in index)
    return b"\n".join(modules.values()) + b"\n"


def expected_dump(fixture):
    rows = [int(row, 16) for row in fixture.read_text().splitlines()]
    assert len(rows) == 512 and all(row >> 488 & 31 == 11 and row.bit_length() <= 621 for row in rows)
    strips = []
    for start in range(0, 2048, 160):
        for token in range(2):
            for offset in range(start, min(start + 160, 2048), 8):
                row = rows[256 * token + offset // 8]
                flags = 128 | token | (256 if len(strips) == 511 else 0)
                strips.append(f"39300001{offset:04x}{flags:04x}{row >> 493:032x}a67e")
    assert len(strips) == 512
    return strips


def prepare(directory, phase, pin):
    placed = read(pin(Path("records/tri_oracle_repacked_whole_chip_cold_reload.json")))
    norm = read(pin(Path("records/tri_oracle_host_normalization_packets.json")))
    assert placed["cold_netlist_sha256"] == norm["cold_netlist_sha256"]
    (cold,) = (Path(name) for name in placed["evidence_sha256"] if name.endswith("/cold.v"))
    pin(cold, norm["cold_netlist_sha256"])
    training = read(pin(Path("records/tri_oracle_mapped_parent_live_writeback.json")))
    pin(FIXTURE, training["evidence_sha256"][str(FIXTURE)])
    pin(MODEL, norm["evidence_sha256"][str(MODEL)])
    wrapper = NORM / "projection_wrapper.v"
    pin(wrapper, norm["evidence_sha256"][str(wrapper)])
    mapped = pin(directory / "genus/netlist.v")
    cut = directory / "bank_writer.v"
    sources = (MODEL, cut, mapped, pin(TEST))
    generated = {
        cut: exact_bank_writer(cold),
        directory / "mapped_bundle.sv": "".join(include(path) for path in sources).encode(),
    }
    for path, content in generated.items():
        if phase == "prepare":
            with path.open("xb") as stream:
                stream.write(content)
        else:
            assert path.read_bytes() == content, path
            pin(path)
    return norm, mapped


def verify(directory, norm, mapped, pin):
    def simulation(name, required):
        run = directory / name
        history = pin(run / "xrun.history").read_text()
        argv = shlex.split(re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1])
        assert argv[argv.index("-top") + 1] == BENCH
        assert all(str(pin(path).resolve()) in argv for path in required)
        assert f"+FIXTURE={FIXTURE.resolve()}" in argv
        dump = pin(run / "strips.hex")
        assert f"+DUMP={dump.resolve()}" in argv
        log = pin(run / "console.log").read_text()
        return log, dump

    expected = expected_dump(FIXTURE)
    red, dump = simulation("red", (directory / "red/baseline.sv", TEST))
    assert "HOST_WRITEBACK_DELIVERY strips=0 accepted=512 reads=512 responses=18" in red
    assert "Simulation terminated via $fatal(1)" in red and dump.stat().st_size == 0
    unlocked = directory / "preempt/unlocked.sv"
    original = pin(RTL).read_text()
    lock = "source_in_progress <= !(tx_ready && source_last);"
    assert original.count(lock) == 1
    assert pin(unlocked).read_text() == original.replace(lock, "source_in_progress <= 1'b0;")
    preempt, _ = simulation("preempt", (unlocked, TEST))
    assert "HOST_COMMAND_RESPONSE_LENGTH response=0 words=14" in preempt
    assert "Simulation terminated via $fatal(1)" in preempt
    results = {}
    for name, required in {
        "rtl": (RTL, TEST, *(Path(f"verilog/tri_oracle_decoder_{part}.sv")
                              for part in ("bank_writeback", "writeback_bridge", "residual_writeback"))),
        "mapped": (directory / "mapped_bundle.sv",),
    }.items():
        log, dump = simulation(name, required)
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        (stalls, concurrent), = re.findall(
            r"^HOST_WRITEBACK_TX_PASS strips=512 values=4096 responses=18 stalled=(\d+) contended=(\d+)$",
            log, re.M)
        assert int(stalls) > 0 and int(concurrent) > 0
        assert dump.read_text().splitlines() == expected
        results[name] = {"stalled_words": int(stalls), "simultaneous_source_cycles": int(concurrent)}

    genus = directory / "genus"
    assert "TRI_ORACLE_HOST_WRITEBACK_TX_GENUS_FINISHED" in pin(genus / "console.log").read_text()
    assert "No unresolved references" in pin(genus / "mapped_check.rpt").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", pin(genus / "constraints.sdc").read_text())
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(genus / "timing.rpt").read_text())))
    assert slack >= 0
    area = pin(genus / "area.rpt").read_text()
    assert "Operating conditions:   ssg0p9v125c" in area
    (cells, area_um2), = re.findall(rf"(?m)^\s*{TX}\s+NA\s+(\d+)\s+([\d.]+)", area)
    data = mapped.read_bytes()
    index = spans(data)
    assert set(index) == {TX}
    assert ports(module_at(data, index, TX))["wb_data"] == ("INPUT", 128)
    for path in (SYNTH, Path(__file__).resolve().relative_to(Path.cwd())):
        pin(path)
    return {
        "state": "mapped_writeback_transmitter_verified_with_exact_mapped_bank_writer",
        "cold_netlist_sha256": norm["cold_netlist_sha256"],
        "trained_writeback_strips": 512,
        "trained_values": 4096,
        "host_response_frames": 18,
        "words_per_writeback_strip": 13,
        "current_modeled_pads": norm["modeled_pad_sites_with_two_edge_receive"],
        "parallel_writeback_signals_targeted": norm["remaining_parallel_signal_bits_by_role"]["writeback_result"] - 2,
        "negative_cases": ["writeback_dropped", "command_frame_interleaved"],
        "simulations": results,
        "isolated_mapping": {"target_period_ns": 1.72414, "worst_setup_slack_ps": slack,
                             "cells": int(cells), "area_um2": float(area_um2)},
        "scope": "Exact bank writer from the cold chip export and the standalone transmitter. "
                 "The stimulus supplies archived trained codes and bank responses. Synthetic command "
                 "frames exercise arbitration, including source gaps and backpressure. "
                 "Whole-chip binding, grouped result readiness, and pad count are unqualified.",
    }


def main():
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    evidence = {}

    def pin(path, expected=None):
        name = str(path)
        if name not in evidence:
            evidence[name] = digest(path)
        assert expected is None or evidence[name] == expected, path
        return path

    norm, mapped = prepare(args.directory, args.phase, pin)
    if args.phase == "verify":
        print(json.dumps(verify(args.directory, norm, mapped, pin) | {"evidence_sha256": evidence},
                         indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
