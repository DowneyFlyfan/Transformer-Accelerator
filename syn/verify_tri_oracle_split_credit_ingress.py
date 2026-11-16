"""Prepare and verify a separate falling-edge head against the shared head."""

import argparse
import json
from pathlib import Path
import re

from verify_tri_oracle_credit_bypass import (
    BEFORE, CAPTURE, CELL_MODEL, CLAIM, CREDIT_TEST, DECODER, FIFO, GEARBOX, INGRESS, ROOT,
    TRIAL as SHARED, arguments, check as shared_check, digest, generated as shared_sources, replace,
)


TRIAL = SHARED.with_name("split_credit_ingress")
BASELINE_RECORD = Path("records/tri_oracle_credit_bypass_ingress.json")
FIXTURES = ("down_index.bin", "down_payload.bin", "projected.hex")


def sources():
    candidate = shared_sources()
    queue = replace(candidate[FIFO], "parameter int DEPTH = 8",
                    "parameter int DEPTH = 8,\n  parameter bit SPLIT_HEAD = 0")
    ordinary = """  always_ff @(posedge clk) begin
    if (store) entries[write_ptr[ADDRESS_BITS-1:0]] <= write_data;
    if (bypass) read_data <= write_data;
    else if (pop) read_data <= entries[read_ptr[ADDRESS_BITS-1:0]];
  end"""
    split = """  if (SPLIT_HEAD) begin : split_head
    logic [WIDTH-1:0] direct_data, queued_data;
    logic head_from_input;

    always_ff @(posedge clk) begin
      // The write pointer addresses a free slot whenever the queue is
      // not full. Only advancing the pointer makes its data visible.
      if (!full) entries[write_ptr[ADDRESS_BITS-1:0]] <= write_data;
      if (read_enable) begin
        direct_data <= write_data;
        head_from_input <= empty;
      end
      if (pop) queued_data <= entries[read_ptr[ADDRESS_BITS-1:0]];
    end

    assign read_data = head_from_input ? direct_data : queued_data;
  end else begin : shared_head
    always_ff @(posedge clk) begin
      if (store) entries[write_ptr[ADDRESS_BITS-1:0]] <= write_data;
      if (bypass) read_data <= write_data;
      else if (pop) read_data <= entries[read_ptr[ADDRESS_BITS-1:0]];
    end
  end"""
    candidate[FIFO] = replace(queue, ordinary, split)
    name = f"{INGRESS}.sv"
    candidate[name] = replace(candidate[name], ".DEPTH(CREDIT_DEPTH))",
                              ".DEPTH(CREDIT_DEPTH), .SPLIT_HEAD(lane == 1))")
    candidate[name] = replace(candidate[name], ".read_enable(dequeue)", ".read_enable(reload)")
    return {name: text.replace(str(ROOT / SHARED), str(ROOT / TRIAL))
            for name, text in candidate.items()}


def prepare():
    TRIAL.mkdir(parents=True, exist_ok=True)
    for name, text in sources().items():
        path = TRIAL / name
        if path.exists():
            assert path.read_text() == text, path
        else:
            path.write_text(text)
    for folder in ("trained_rtl", "trained_mapped"):
        (TRIAL / folder).mkdir(exist_ok=True)
        for name in FIXTURES:
            path = TRIAL / folder / name
            source = (SHARED / folder / name).resolve(strict=True)
            if path.is_symlink() or path.exists():
                assert path.resolve(strict=True) == source, path
            else:
                path.symlink_to(source)


def check():
    baseline = json.loads(BASELINE_RECORD.read_text())
    assert baseline == shared_check()
    paths = {BASELINE_RECORD, Path(__file__).resolve().relative_to(ROOT)}

    def pin(path):
        paths.add(path)
        return path

    for name, text in sources().items():
        assert pin(TRIAL / name).read_text() == text, name

    def replay(folder, top, inputs, orig_behavior, option=None):
        run = TRIAL / folder
        argv = arguments(pin(run / "xrun.history"))
        assert argv[argv.index("-top") + 1] == top
        assert all(str(pin(path).resolve()) in argv for path in inputs)
        assert option is None or option in argv
        log = pin(run / "console.log").read_text()
        assert log.count("Simulation complete via $finish(1)") == 1, folder
        assert not re.search(r"\*[EF],", log), folder
        baseline_log = SHARED / folder / "console.log"
        assert digest(baseline_log) == baseline["evidence_sha256"][str(baseline_log)]
        pattern = r"(?m)^(?:" + "|".join(orig_behavior) + r"|Simulation complete via \$finish\(1\)).*$"
        current = re.findall(pattern, log)
        previous = re.findall(pattern, baseline_log.read_text())
        assert len(current) == len(orig_behavior) + 1 and current == previous, folder

    rtl = (TRIAL / f"{INGRESS}.sv", TRIAL / FIFO, CAPTURE, GEARBOX, DECODER)
    gate = (TRIAL / "genus/netlist.v", CELL_MODEL)
    first = TRIAL / "first_chunk_tb.sv"
    for folder, inputs in (("first", rtl), ("first_mapped", gate)):
        replay(folder, "first_chunk_tb", (*inputs, first), ("FIRST_CHUNK_BYPASS_PASS ",))
    for tag, inputs in (("rtl", rtl), ("mapped", gate)):
        replay(tag + "4", INGRESS + "_tb", (*inputs, CREDIT_TEST),
               ("CREDIT_FULL_RATE_PASS ", "CREDIT_STALL_PASS "))
        replay(tag + "8", INGRESS + "_tb", (*inputs, CREDIT_TEST),
               ("CREDIT_DELAY_WINDOW_PASS ", "CREDIT_STALL_PASS "), "TRI_ORACLE_CREDIT_TEST_DELAY=8")
    io = TRIAL.parent / "memory_io_link/genus/netlist.v"
    replay("mixed", INGRESS + "_mixed_tb", (*gate, io, BEFORE / "mixed_tb.sv"),
           ("COMPACT_RESPONSE_LANE_PASS ",))
    for name in ("trained_rtl", "trained_mapped"):
        replay(name, "compact_index_replay_tb", (TRIAL / f"{name}.sv",),
               ("COMPACT_INDEX_MATRIX_PASS ", "STAGED_INDEXED_DOWN_MATRIX_PASS ",
                "NATIVE_MEMORY_IO_PASS ", "STAGED_WRITES_PASS "), "+FULL_MATRIX")
        for file in FIXTURES:
            candidate = (TRIAL / name / file).resolve(strict=True)
            assert candidate == (SHARED / name / file).resolve(strict=True)
            relative = candidate.relative_to(ROOT)
            assert digest(pin(relative)) == baseline["evidence_sha256"][str(relative)]

    genus = TRIAL / "genus"
    assert CLAIM in pin(genus / "console.log").read_text()
    assert "No unresolved references" in pin(genus / "mapped_check.rpt").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 -waveform \{0\.0 0\.86207\} ",
                     pin(genus / "constraints.sdc").read_text())
    timing = pin(genus / "timing.rpt").read_text()
    assert "ssg0p9v125c" in timing
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", timing)))
    area = pin(genus / "area.rpt").read_text()
    cells, cell_area = re.search(rf"(?m)^{INGRESS}\s+NA\s+(\d+)\s+(\d+\.\d+)", area).groups()
    assert slack >= baseline["mapped_setup_slack_ps_before"], slack

    linked = json.loads(pin(TRIAL / "linked.json").read_text())
    wrapper = pin(TRIAL / "chip_binding/credit_wrapper.v")
    comparison = pin(TRIAL / "reference_binding/credit_wrapper.v")
    assert wrapper.read_bytes() == comparison.read_bytes()
    for path in (gate[0], wrapper, pin(Path("syn/link_tri_oracle_credited_ingress.py"))):
        assert digest(path) == linked["evidence_sha256"][str(path.resolve())]
    assert (linked["signals"], linked["remaining_sites_before_power_spacing_and_board_requirements"]) == (531, 54)
    storage = json.loads(pin(TRIAL / "host_storage_check.json").read_text())
    assert storage["queue_and_head_transitions"] == 1152
    pin(Path("syn/check_tri_oracle_split_credit_storage.py"))

    return {
        "state": "split_falling_edge_head_verified_against_shared_bypass",
        "setup_slack_ps": {"initial_receiver": baseline["mapped_setup_slack_ps_before"],
                           "shared_bypass": baseline["mapped_setup_slack_ps_after"], "split_head": slack},
        "mapped_area_um2": {"shared_bypass": baseline["mapped_cell_area_um2_after"],
                            "split_head": float(cell_area)},
        "mapped_cell_count": int(cells),
        "trained_weight_tiles": baseline["trained_weight_tiles"],
        "trained_bytes": baseline["trained_weight_bytes"],
        "trained_fixture_cycles": baseline["trained_fixture_cycles_after"],
        "abstract_queue_transitions_checked_on_host_gpu": storage["queue_and_head_transitions"],
        "whole_chip_structural_signal_bits": linked["signals"],
        "signal_sites_remaining_before_power_spacing_and_package":
            linked["remaining_sites_before_power_spacing_and_board_requirements"],
        "scope": "Functional evidence covers the standalone digital receiver. The falling-edge lane uses "
                 "separate direct and queued data registers. The queue may write an unoccupied slot "
                 "speculatively. Timing is a slow-corner synthesis estimate. The whole-chip boundary "
                 "is checked structurally. "
                 "Whole-chip execution, placement, timing and power are unverified.",
        "evidence_sha256": {str(path): digest(path) for path in sorted(paths)},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="write sources under .cache")
    options = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    if options.prepare:
        prepare()
    else:
        print(json.dumps(check(), indent=2, sort_keys=True))
