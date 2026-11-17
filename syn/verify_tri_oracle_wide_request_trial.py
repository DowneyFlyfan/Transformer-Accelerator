"""Check a full-flit-wide request link on the placed-receiver weight fixture."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_booth_packet_replay import replace_once
from prepare_tri_oracle_reference_projection_attention import replace_block
from verify_tri_oracle_booth_trained_credit_window import FIXTURES, TOP
from verify_tri_oracle_booth_trained_request_link import MATRIX, ROOT, TERMINAL, TX, digest


REFERENCE = Path("records/tri_oracle_corrected_booth_trained_request_link.json")
OVERLAP = Path("records/tri_oracle_corrected_booth_request_response_overlap.json")
PAD_CAPACITY = Path("records/tri_oracle_bonded_pad_capacity.json")
SYSTEM = Path("records/tri_oracle_bonded_system_budget.json")
SYNTH = Path("syn/tri_oracle_synthesize_memory_tx_credit.tcl")
MODULE = "tri_oracle_memory_tx_credit_wide"
RTL = Path(f"verilog/{MODULE}.sv")
PHASE_BENCH = Path("verilog/tri_oracle_memory_tx_credit_tb.sv")
PHASE_TOP = "tri_oracle_memory_tx_credit_tb"
TRAFFIC = re.compile(r"(?m)^TRAINED_REQUEST_LINK flits=(\d+) pad_beats=(\d+) inactive_source_cycles=(\d+)$")


def one_transfer_per_flit(log):
    row, = TRAFFIC.findall(log)
    flits, transfers, inactive_cycles = map(int, row)
    if flits != transfers:
        raise ValueError(f"Expected one transfer per flit, observed {transfers} transfers for {flits} flits")
    return flits, inactive_cycles


def phase_bench():
    bench = PHASE_BENCH.read_text()
    bench = replace_once(bench, f"{TX} #(.CREDITS(Credits)) sender", f"{MODULE} sender")
    bench = replace_once(bench, f"{TX} unsolicited_credit", f"{MODULE} unsolicited_credit")
    for word in ("pad_data", "peer_data", "head"):
        bench = replace_once(bench, f"logic [7:0] {word};", f"logic [21:0] {word};")
    bench = replace_once(bench, ".WIDTH(8)", ".WIDTH(22)")
    bench = bench.replace("3 * Words", "Words")
    return replace_block(bench, "  tri_oracle_flit_from_pads peer_decoder (", "  int received",
                         "  assign {recovered_valid, recovered_word} = {head_valid, head};\n"
                         "  assign head_ready = recovered_ready;\n\n")


def setup():
    reference = json.loads(REFERENCE.read_text())
    logs = reference["evidence_sha256"]
    baseline, = (ROOT / path for path in logs if path.endswith("/request_link_trained/xrun.log"))
    assert digest(baseline) == logs[str(baseline.relative_to(ROOT))]
    assert baseline.read_text().count(TERMINAL) == 1
    original = baseline.parent
    folder = original.with_name("wide_request_trial")
    evidence = {REFERENCE, baseline}
    for name in ("bundle.sv", "trained_tb.sv", "placed_request_tx.v"):
        path = original / name
        assert digest(path) == logs[str(path.relative_to(ROOT))]
        evidence.add(path)
    text = (original / "bundle.sv").read_text()
    fixtures = {name: (original / name).resolve(strict=True) for name in FIXTURES}
    for path in (*fixtures.values(), *(Path(path) for path in re.findall(r'(?m)^`include "([^"]+)"$', text))):
        assert digest(path) == logs[str(path.relative_to(ROOT))]
        evidence.add(path)
    bundle = replace_once(text, str(original / "placed_request_tx.v"), str(folder / "genus/netlist.v"))
    bundle = replace_once(bundle, str(original / "trained_tb.sv"), str(folder / "trained_tb.sv"))
    bench = (original / "trained_tb.sv").read_text()
    for old, new in (
        (f"{TX} boundary_control", f"{MODULE} boundary_control"),
        ("logic [7:0] pad_request_data;", "logic [21:0] pad_request_data;"),
        ("logic [7:0] flight_data", "logic [21:0] flight_data"),
        ("logic [7:0] head;", "logic [21:0] head;"),
        ("#(.WIDTH(8), .DEPTH(16)) request_queue", "#(.WIDTH(22), .DEPTH(16)) request_queue"),
        ("physical_flits != 3*serialized_words", "physical_flits != serialized_words"),
    ):
        bench = replace_once(bench, old, new)
    bench = replace_block(bench, "  tri_oracle_flit_from_pads #(.WORD_BITS(22), .PAD_BITS(8)) memory_peer (",
                          "  int physical_flits", "  assign {flit_valid, flit_data} = {head_valid, head};\n"
                          "  assign head_ready = flit_ready;\n")
    synthesis = replace_once(SYNTH.read_text(), "set root [file dirname [file dirname [file normalize [info script]]]]",
                              f"set root {{{ROOT}}}")
    start, end = "read_hdl -sv [list ", f"elaborate {TX}"
    synthesis = replace_block(synthesis, start, end, f"read_hdl -sv [file join $root {RTL}]\n")
    synthesis = replace_once(synthesis, end, f"elaborate {MODULE}")
    evidence.add(SYNTH)
    return folder, fixtures, {"bundle.sv": bundle, "trained_tb.sv": bench, "synthesize.tcl": synthesis}, baseline, evidence


def verify_phase(folder):
    source = folder / "phase_tb.sv"
    assert source.read_text() == phase_bench()
    cases = {}
    for label in ("rtl", "mapped"):
        stage = folder / f"phase_{label}"
        log, status = stage / "xrun.log", stage / "exit_status"
        transcript = log.read_text()
        assert int(status.read_text()) == 0
        assert transcript.count(TERMINAL) == 1 and not re.search(r"\*(?:E|F|SE),", transcript)
        assert f"\t-top {PHASE_TOP}\n" in transcript
        expected_source = RTL.resolve() if label == "rtl" else folder / "genus/netlist.v"
        assert f"\t{expected_source}\n" in transcript and f"\t{source}\n" in transcript
        assert "MEMORY_TX_UNSOLICITED_CREDIT_PASS" in transcript
        cases[label] = sorted(re.findall(
            r"(?m)^MEMORY_TX_CREDIT_(RATE|STALL)_PASS delay=(\d+) words=96 bytes=96 bubbles=(\d+)$",
            transcript))
        assert {(kind, int(delay)) for kind, delay, _ in cases[label]} == {
            (kind, delay) for kind in ("RATE", "STALL") for delay in (4, 8, 18)}
    assert cases["rtl"] == cases["mapped"]
    return cases["mapped"]


def verify():
    folder, fixtures, generated, baseline, evidence = setup()
    for name, text in generated.items():
        path = folder / name
        assert path.read_text() == text
        evidence.add(path)
    for name, original in fixtures.items():
        assert (folder / name).resolve(strict=True) == original
    genus = folder / "genus"
    assert int((folder / "genus_exit").read_text()) == int((folder / "exit_status").read_text()) == 0
    assert "TRI_ORACLE_MEMORY_TX_CREDIT_GENUS_FINISHED" in (folder / "genus.log").read_text()
    assert f"No unresolved references in design '{MODULE}'" in (genus / "mapped_check.rpt").read_text()
    assert "input [21:0] in_word;" in (genus / "netlist.v").read_text()
    assert "output [21:0] pad_data;" in (genus / "netlist.v").read_text()
    slack = list(map(int, re.findall(r"Slack:=\s+(-?\d+)", (genus / "pad_setup.rpt").read_text())))
    assert slack and min(slack) >= 0
    log = (folder / "xrun.log").read_text()
    assert log.count(TERMINAL) == 1 and not re.search(r"\*(?:E|F|SE),", log)
    assert all(f"\t{argument}\n" in log for argument in
               (f"-top {TOP}", str(folder / "bundle.sv"), "+FULL_MATRIX"))
    for option in ("TRI_ORACLE_TRAINED_WINDOW=8", "TRI_ORACLE_TRAINED_RETURN=7"):
        assert option in log
    base_log = baseline.read_text()
    assert MATRIX.findall(log) == MATRIX.findall(base_log)
    assert "STAGED_INDEXED_DOWN_MATRIX_PASS cases=78 exact_bytes=11534336 " in log
    assert "NATIVE_MEMORY_IO_PASS acks=16 faults=2 " in log
    flits, inactive_cycles = one_transfer_per_flit(log)
    base_flits, base_transfers, _ = map(int, TRAFFIC.findall(base_log)[0])
    assert flits == base_flits and base_transfers == 3 * base_flits
    phase = verify_phase(folder)
    overlap, limits, digital = (json.loads(path.read_text()) for path in (OVERLAP, PAD_CAPACITY, SYSTEM))
    reads = overlap["archived_weight_read_requests"] + overlap["archived_sign_line_read_requests"]
    fragments = overlap["archived_response_fragments_after_compact_indexes"]
    lower = (fragments + 2 * reads + 1) // 2
    digital_pins = digital["separate_wrapper"]["digital_signal_bits"] + 14
    with_supplies = digital_pins + digital["separate_wrapper"]["supply_and_ground_reservations"]
    geometric = limits["scenarios"]["pad50_optimistic_shared_filler"]["sites"]
    reference_cycles, candidate_cycles = (
        int(re.findall(r"(?m)^DUAL_GROUP_MATRIX_WRITES writes=90112 cycles=(\d+)$", transcript)[0])
        for transcript in (base_log, log))
    evidence.update((OVERLAP, PAD_CAPACITY, SYSTEM, RTL, Path(__file__), folder / "genus.log",
                     folder / "genus_exit", folder / "exit_status", folder / "xrun.log",
                     PHASE_BENCH, folder / "phase_tb.sv",
                     *(folder / f"phase_{label}" / name for label in ("rtl", "mapped") for name in ("xrun.log", "exit_status")),
                     *(genus / name for name in ("mapped_check.rpt", "netlist.v", "area.rpt", "pad_setup.rpt"))))
    return {
        "state": "wide_request_link_synthesized_and_replayed_with_placed_response_receiver",
        "cold_receiver_netlist_sha256": json.loads(REFERENCE.read_text())["cold_netlist_sha256"],
        "trained_weight_tiles": 78, "verified_weight_bytes": 11534336,
        "baseline_cycles": reference_cycles, "wide_request_cycles": candidate_cycles,
        "cycles_saved": reference_cycles - candidate_cycles,
        "reference_request_transfers": base_transfers, "wide_request_transfers": flits,
        "inactive_cycles_with_request_offered": inactive_cycles,
        "forwarded_clock_capture_cases": phase,
        "slow_library_wire_free_pad_setup_ps": min(slack),
        "digital_signal_pins": digital_pins, "signal_and_illustrative_supply_pins": with_supplies,
        "optimistic_archived_pad_sites": geometric,
        "optimistic_read_cycles_no_same_lane_overlap": lower,
        "archived_paper_window_cycles": overlap["paper_window_cycles"],
        "scope": "Standalone mapped outbound link, archived mapped I/O and loader, and receiver extracted "
                 "from the placed chip. The replay models off-chip flight and credit delays. The pad estimate "
                 "uses an archived geometry screen. The latency floor omits all stalls and other operations.",
        "evidence_sha256": {str(path.relative_to(ROOT) if path.is_absolute() else path): digest(path)
                            for path in evidence},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "prepare", "phase-bench", "verify"))
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    if args.phase == "baseline":
        _, _, _, log, _ = setup()
        one_transfer_per_flit(log.read_text())
    elif args.phase == "phase-bench":
        folder, _, _, _, _ = setup()
        for label in ("rtl", "mapped"):
            (folder / f"phase_{label}").mkdir()
        (folder / "phase_tb.sv").write_text(phase_bench())
    elif args.phase == "prepare":
        folder, fixtures, generated, _, _ = setup()
        folder.mkdir()
        for name, text in generated.items():
            (folder / name).write_text(text)
        for name, path in fixtures.items():
            (folder / name).symlink_to(path)
        print(folder)
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
