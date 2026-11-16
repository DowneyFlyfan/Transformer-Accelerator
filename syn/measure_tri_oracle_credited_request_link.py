"""Prepare and verify the mapped outbound credit link on the trained fixture."""
import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import tarfile

from audit_tri_oracle_bonded_pad_timing import PAD_CORNERS, read_arcs
from audit_tri_oracle_packed_weight_path import pins
from compare_tri_oracle_serial_memory_boundary import ADAPTER, FIXTURES, PAD_CONTROL, PEER, ROOT
from link_tri_oracle_chip_packet_io import instance, ports as mapped_ports
from link_tri_oracle_indexed_whole_chip import module_at, spans
from link_tri_oracle_narrow_host import declarations, width
from measure_tri_oracle_serial_memory_requests import digest, read, replace
from verify_tri_oracle_host_control import outer_ports
from verify_tri_oracle_host_status import arguments


WORK = Path(".cache/physical/whole_chip_xcelium_speed/credit_request_link")
PREVIOUS = Path(".cache/physical/whole_chip_xcelium_speed/combined_serial_memory")
BASELINE = Path("records/tri_oracle_combined_serial_memory.json")
METADATA = Path("records/tri_oracle_shared_edge_metadata.json")
PAD_TIMING = Path("records/tri_oracle_bonded_pad_timing.json")
METADATA_BINDING = Path(".cache/physical/whole_chip_xcelium_speed/shared_edge_metadata")
TX = Path("verilog/tri_oracle_memory_tx_credit.sv")
TB = Path("verilog/tri_oracle_memory_tx_credit_tb.sv")
SYNTHESIS = Path("syn/tri_oracle_synthesize_memory_tx_credit.tcl")
TIMING = Path("syn/tri_oracle_check_memory_tx_credit_timing.tcl")
FIFO = Path("verilog/tri_oracle_credit_bypass_fifo.sv")


LINK = """  // The full replay uses integer-cycle propagation in the surrounding
  // same-clock memory model. The separate transport test checks edge phase.
  localparam int Request_Transit = 2;
  localparam int Credit_Transit = 6;
  logic pad_request_valid, pad_request_credit, pad_request_clock, request_fault;
  logic [7:0] pad_request_data;
  logic flit_valid, flit_ready;
  logic [21:0] flit_data;
  tri_oracle_memory_tx_credit boundary_control (
    .clk, .rst_n, .in_valid(wire_valid), .in_ready(wire_ready), .in_word(wire_data),
    .pad_valid(pad_request_valid), .pad_data(pad_request_data), .pad_clock(pad_request_clock),
    .pad_credit(pad_request_credit), .protocol_error(request_fault)
  );
  logic [7:0] flight_data [Request_Transit];
  logic [Request_Transit-1:0] flight_valid;
  logic [Credit_Transit-1:0] flight_credit;
  logic full, empty, head_valid, head_ready;
  logic [7:0] head;
  wire tail_valid = flight_valid[Request_Transit-1];
  wire reload_head = !head_valid || head_ready;
  wire grant_credit = reload_head && (!empty || tail_valid);
  assign pad_request_credit = flight_credit[Credit_Transit-1];
  tri_oracle_credit_bypass_fifo #(.WIDTH(8), .DEPTH(16)) request_queue (
    .clk, .rst_n, .read_enable(reload_head), .write_enable(tail_valid),
    .write_data(flight_data[Request_Transit-1]), .read_data(head), .full, .empty
  );
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      flight_valid <= '0;
      flight_credit <= '0;
      head_valid <= 0;
    end else begin
      flight_valid <= {flight_valid[Request_Transit-2:0], pad_request_valid};
      flight_credit <= {flight_credit[Credit_Transit-2:0], grant_credit};
      if (reload_head) head_valid <= grant_credit;
    end
  end
  always_ff @(posedge clk) begin
    flight_data[0] <= pad_request_data;
    for (int i=1; i<Request_Transit; i++) flight_data[i] <= flight_data[i-1];
  end
  tri_oracle_flit_from_pads #(.WORD_BITS(22), .PAD_BITS(8)) memory_peer (
    .clk, .rst_n, .pad_valid(head_valid), .pad_ready(head_ready), .pad_data(head),
    .out_valid(flit_valid), .out_ready(flit_ready), .out_word(flit_data)
  );
  int physical_flits = 0, serialized_words = 0, pad_stalls = 0;
  logic [21:0] expected_flits[$];
  always @(posedge clk) if (rst_n) begin
    logic [21:0] expected;
    if (request_fault || (full && tail_valid)) $fatal(1, "FORWARD_CREDIT_PROTOCOL");
    if (pad_request_valid) physical_flits++;
    if (wire_valid && wire_ready) expected_flits.push_back(wire_data);
    if (wire_valid && !pad_request_valid) pad_stalls++;
    if (flit_valid && flit_ready) begin
      if (!expected_flits.size()) $fatal(1, "FORWARD_CREDIT_UNEXPECTED_FLIT");
      expected = expected_flits.pop_front();
      if (flit_data !== expected) $fatal(1, "FORWARD_CREDIT_FLIT_CHANGED");
      serialized_words++;
    end
  end
"""


def prepare(out):
    proof = read(BASELINE)
    for name in ("trained_tb.sv", "bundle.sv"):
        path = PREVIOUS / name
        assert digest(path) == proof["evidence_sha256"][str(path)], path
    source = replace((PREVIOUS / "trained_tb.sv").read_text(), ADAPTER, LINK)
    source = replace(source, "      $display(\"SERIAL_MEMORY_PAD_TRAFFIC",
                     "      if (expected_flits.size()) $fatal(1, \"FORWARD_CREDIT_UNDRAINED_FLITS\");\n"
                     "      $display(\"SERIAL_MEMORY_PAD_TRAFFIC")
    source = replace(source, 'SERIAL_MEMORY_PAD_TRAFFIC narrow=%0d wide=%0d stalled=%0d',
                     'SERIAL_MEMORY_PAD_TRAFFIC narrow=%0d wide=%0d source_cycles_without_pad_valid=%0d')
    bundle = (PREVIOUS / "bundle.sv").read_text()
    bundle = replace(bundle, str(PAD_CONTROL.resolve()), str(out / "genus/netlist.v"))
    bundle = replace(bundle, str((PREVIOUS / "trained_tb.sv").resolve()), str(out / "trained_tb.sv"))
    bundle = replace(bundle, str(PEER.resolve()), str(out / "peer_assembler.sv"))
    bundle = f'`include "{FIFO.resolve()}"\n' + bundle
    source_peer = PEER.read_text()
    receiver = source_peer.index("module tri_oracle_flit_from_pads")
    (out / "peer_assembler.sv").write_text("`timescale 1ns/1ps\n" + source_peer[receiver:])
    (out / "trained_tb.sv").write_text(source)
    (out / "bundle.sv").write_text(bundle)
    mapped = TB.read_text().replace("tri_oracle_memory_tx_credit #(.CREDITS(Credits)) sender",
                                   "tri_oracle_memory_tx_credit sender")
    (out / "mapped_tb.sv").write_text(mapped)
    for folder in ("directed", "trained"):
        target = out / folder
        target.mkdir(exist_ok=True)
        for name in FIXTURES:
            source_file = (PREVIOUS / "full" / name).resolve(strict=True)
            link = target / name
            if link.is_symlink():
                assert link.resolve(strict=True) == source_file
            else:
                link.symlink_to(source_file)


def terminal(log):
    assert not re.search(r"\*[EF],", log)
    assert log.count("Simulation complete via $finish(1)") == 1


def bind(out):
    proof = read(METADATA)["evidence_sha256"]
    original_top = (METADATA_BINDING / "top_wrapper.v").resolve()
    original_bundle = (METADATA_BINDING / "chip_bundle.sv").resolve()
    for path in (original_top, original_bundle):
        assert digest(path) == proof[str(path)]
    previous = PAD_CONTROL.read_bytes()
    index = spans(previous)
    parent = module_at(previous, index, "tri_oracle_serial_control_pads")
    host_ports = {name: value for name, value in mapped_ports(parent).items() if "memory_tx_" not in name}
    host_modules = ("tri_oracle_flit_from_pads_WORD_BITS18_PAD_BITS4",
                    "tri_oracle_flit_to_pads_WORD_BITS17_PAD_BITS4")
    # Keep the verified port hookups and the explicit last-beat flag assignments.
    body = parent.decode().split("  wire UNCONNECTED, UNCONNECTED0;", 1)[1]
    body = body.split("  tri_oracle_flit_to_pads_WORD_BITS22_PAD_BITS8 memory_tx(", 1)[0]
    host_cut = f"module tri_oracle_host_serial_pads (\n" + ",\n".join(declarations(host_ports)) + "\n);\n"
    host_cut += "  wire UNCONNECTED, UNCONNECTED0;" + body + "endmodule\n"
    host_cut += "\n".join(module_at(previous, index, name).decode() for name in host_modules)
    host_path = out / "host_pad_cut.v"
    host_path.write_text(host_cut)

    source = original_top.read_text()
    physical = outer_ports(source)
    assert physical.pop("memory_tx_ready") == ("INPUT", None)
    physical["memory_tx_credit"] = ("INPUT", None)
    physical["memory_tx_clock"] = ("OUTPUT", None)
    mapped = (out / "genus/netlist.v").read_bytes()
    request_ports = mapped_ports(module_at(mapped, spans(mapped), "tri_oracle_memory_tx_credit"))
    body = source.split("\n);\n", 1)[1]
    body = body.split("  tri_oracle_serial_control_pads serial_pads (", 1)[0]
    body += "  wire request_protocol_error;\n"
    body += instance("tri_oracle_host_serial_pads", "serial_pads", {name: name for name in host_ports})
    wiring = {
        "clk": "clk", "rst_n": "rst_n", "in_valid": "wide_memory_tx_valid", "in_ready": "wide_memory_tx_ready",
        "in_word": "wide_memory_tx_data", "pad_valid": "memory_tx_valid", "pad_data": "memory_tx_data",
        "pad_clock": "memory_tx_clock", "pad_credit": "memory_tx_credit", "protocol_error": "request_protocol_error",
    }
    assert request_ports.keys() == wiring.keys()
    body += instance("tri_oracle_memory_tx_credit", "request_link", wiring)
    top = "module tri_oracle_chip_credited_request (\n" + ",\n".join(declarations(physical)) + "\n);\n"
    top += body + "endmodule\n"
    assert width(outer_ports(top)) == 484
    chip = "tri_oracle_chip_credited_metadata"
    assert pins(top.encode(), chip, "chip") == pins(source.encode(), chip, "chip")
    top_path = out / "top_wrapper.v"
    top_path.write_text(top)
    bundle = replace(original_bundle.read_text(), str(PAD_CONTROL.resolve()), str(host_path))
    bundle = replace(bundle, str(original_top), str(top_path))
    bundle += f'`include "{out / "genus/netlist.v"}"\n'
    (out / "chip_bundle.sv").write_text(bundle)


def pad_envelope(setup, hold):
    proof = read(PAD_TIMING)
    archive, = [Path(name) for name in proof["evidence_sha256"] if name.endswith("_nldm.tar.gz")]
    assert digest(archive) == proof["evidence_sha256"][str(archive)]
    delays = {}
    with tarfile.open(archive, "r:gz") as bundle:
        for corner in PAD_CORNERS[:2]:
            member, = (name for name in proof["pad_library_member_sha256"] if name.endswith(corner + ".lib"))
            with bundle.extractfile(member) as stream:
                raw = stream.read()
            assert sha256(raw).hexdigest() == proof["pad_library_member_sha256"][member]
            points = []
            for side in ("H", "V"):
                arcs = read_arcs(raw.decode(), f"PDDW16DGZ_{side}_G", output=True)
                for metric in ("cell_rise", "cell_fall"):
                    slews, loads, rows = arcs[metric]
                    assert slews[0] == Decimal("0.1") and loads[:3] == (5, 10, 25)
                    points.extend(zip(loads[:3], rows[0][:3], strict=True))
            delays[corner] = points
    output = {}
    for limit in (10, 25):
        spread = []
        for corner in PAD_CORNERS[:2]:
            values = [delay for load, delay in delays[corner] if load <= limit]
            spread.append(1000 * (max(values) - min(values)))
        output[str(limit)] = {
            "pad_setup_skew_allowance_ps": float(spread[0]), "pad_hold_skew_allowance_ps": float(spread[1]),
            "remaining_setup_ps_before_package_and_board": float(setup - spread[0]),
            "remaining_hold_ps_before_package_and_board": float(hold - spread[1]),
        }
    return output


def check_bundle(out):
    paths = re.findall(r'(?m)^`include "([^"]+)"$', (out / "chip_bundle.sv").read_text())
    assert len(paths) == len(set(paths))
    modules = set()
    declaration = re.compile(rb"^[ \t]*module\s+([^\s#(]+)")
    for name in paths:
        with Path(name).open("rb") as stream:
            for line in stream:
                if match := declaration.match(line):
                    assert match[1] not in modules, (name, match[1])
                    modules.add(match[1])
    assert {b"tri_oracle_chip_credited_request", b"tri_oracle_host_serial_pads",
            b"tri_oracle_memory_tx_credit"} <= modules
    return len(paths), len(modules)


def verify(out):
    rtl, mapped = [out / name / "console.log" for name in ("rtl", "mapped")]
    rtl_history, mapped_history = [path.with_name("xrun.history") for path in (rtl, mapped)]
    rtl_args = arguments(rtl_history)
    mapped_args = arguments(mapped_history)
    assert str(TX.resolve()) in rtl_args and str(TB.resolve()) in rtl_args
    assert str(out / "genus/netlist.v") in mapped_args and str(out / "mapped_tb.sv") in mapped_args
    logs = [path.read_text() for path in (rtl, mapped)]
    for log in logs:
        terminal(log)
    summary = r"(?m)^MEMORY_TX_[A-Z_]+_PASS(?: .*)?$"
    standalone, gate = [re.findall(summary, log) for log in logs]
    assert standalone == gate and len(standalone) == 7
    cases = {}
    for delay in (4, 8, 18):
        cases[str(delay)] = {}
        for tag in ("RATE", "STALL"):
            prefix = f"MEMORY_TX_CREDIT_{tag}_PASS delay={delay} words=96 bytes=288 bubbles="
            line, = [item for item in gate if item.startswith(prefix)]
            cases[str(delay)][tag.lower() + "_bubbles"] = int(line.removeprefix(prefix))
    assert all(cases[tag]["rate_bubbles"] == 0 for tag in ("4", "8"))
    assert cases["18"]["rate_bubbles"] > 0 and "MEMORY_TX_UNSOLICITED_CREDIT_PASS" in gate
    wrong_phase = out / "wrong_phase/console.log"
    assert "*F,FATSEV" in wrong_phase.read_text()
    assert "RECOVERED_WORD_MISMATCH ordinal=0" in wrong_phase.read_text()

    baseline_path = PREVIOUS / "full/console.log"
    assert digest(baseline_path) == read(BASELINE)["evidence_sha256"][str(baseline_path)]
    train = out / "trained/console.log"
    previous, current = baseline_path.read_text(), train.read_text()
    terminal(current)
    for pattern in (r"^INDEXED_DOWN_TILE .*$", r"^STAGED_INDEXED_DOWN_MATRIX_PASS .*$",
                    r"^MEMORY_REQUEST_HARDWARE_FIXTURE .*$", r"^EARLY_PAIR_SPARSE_ROWS_PASS .*$",
                    r"^INDEXED_WEIGHT_MODE_PASS .*$"):
        a, b = [re.findall(pattern, text, re.M) for text in (previous, current)]
        assert a and a == b, pattern
    assert re.search(r"(?m)^NATIVE_FORWARD_MIXED_PASS headers=16 words=128 reads_during_writes=[1-9]\d*$", current)
    assert re.search(r"(?m)^NATIVE_MEMORY_IO_PASS acks=16 faults=2 stalled=[1-9]\d*$", current)
    assert re.search(r"(?m)^STAGED_WRITES_PASS segments=180224 concurrent=[1-9]\d* directed_conflicts=[1-9]\d*$", current)
    cycles = [int(re.search(r"(?m)^DUAL_GROUP_MATRIX_WRITES writes=90112 cycles=(\d+)$", text)[1])
              for text in (previous, current)]
    traffic = re.search(r"(?m)^SERIAL_MEMORY_PAD_TRAFFIC narrow=(\d+) wide=(\d+) "
                        r"source_cycles_without_pad_valid=\d+$", current)
    assert tuple(map(int, traffic.groups())) == (27840, 9280)
    history = out / "trained/xrun.history"
    argv = arguments(history)
    assert str(out / "bundle.sv") in argv and "+FULL_MATRIX" in argv
    for name in FIXTURES:
        assert (out / "trained" / name).resolve(strict=True) == (PREVIOUS / "full" / name).resolve(strict=True)

    genus = out / "genus"
    assert "TRI_ORACLE_MEMORY_TX_CREDIT_GENUS_FINISHED" in (genus / "console.log").read_text()
    assert "No unresolved references" in (genus / "mapped_check.rpt").read_text()
    timing = (genus / "pad_setup.rpt").read_text()
    assert "pad_sample_clock" in timing
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", timing)))
    assert slack > 0
    assert "TRI_ORACLE_MEMORY_TX_CREDIT_TIMING_FINISHED" in (out / "sta/console.log").read_text()

    def native(name, view, check):
        text = (genus / name).read_text()
        assert re.search(rf"View:\s+{view}\b", text)
        assert check in text
        if name.startswith("native_pad_"):
            assert re.search(r"Endpoint:.*\n\s*Clock: \(F\) core_clock", text)
        return min(Decimal(value) * 1000 for value in re.findall(r"Slack:=\s+(-?\d+(?:\.\d+)?)", text))

    setup = min(slack, native("native_pad_setup.rpt", "setup_slow", "Late Output Delay Assertion"))
    hold = native("native_pad_hold.rpt", "hold_fast", "Early Output Delay Assertion")
    credit = native("native_return_hold.rpt", "hold_fast", "Hold")
    assert min(setup, hold, credit) > 0
    area, = re.findall(r"(?m)^tri_oracle_memory_tx_credit\s+NA\s+\d+\s+([0-9.]+)",
                       (genus / "area.rpt").read_text())
    pad_bound = read(METADATA)
    signals = pad_bound["chip_signal_bits"] + 1
    assert signals + pad_bound["supply_ground_placeholder_pads"] == 497
    ports = outer_ports((out / "top_wrapper.v").read_text())
    assert width(ports) == signals and ports["memory_tx_clock"] == ("OUTPUT", None)
    assert ports["memory_tx_credit"] == ("INPUT", None) and "memory_tx_ready" not in ports
    additional_sites = int((Decimal(area) / Decimal("0.168")).to_integral_value(rounding="ROUND_CEILING"))
    spare = pad_bound["independent_filler_geometric_site_margin_after_remapped_receiver"] - additional_sites
    assert spare > 0
    source_count, module_count = check_bundle(out)
    paths = (rtl, mapped, rtl_history, mapped_history, train, history, baseline_path,
             wrong_phase, out / "wrong_phase/tb.sv",
             BASELINE, METADATA, PAD_TIMING, TX, TB, SYNTHESIS, TIMING,
             FIFO, PEER, out / "host_pad_cut.v", out / "chip_bundle.sv", out / "top_wrapper.v", out / "sta/console.log",
             out / "trained_tb.sv", out / "bundle.sv", out / "mapped_tb.sv", out / "peer_assembler.sv",
             Path(__file__).resolve(),
             *(genus / name for name in ("console.log", "mapped_check.rpt", "pad_setup.rpt", "area.rpt",
                                         "constraints.sdc", "netlist.v", "peer_phase.sdc", "tx_credit_mmmc.tcl",
                                         "native_pad_setup.rpt", "native_pad_hold.rpt", "native_return_hold.rpt")))
    return {
        "state": "credited_request_link_mapped_and_replayed_with_delayed_peer",
        "standalone_clock_phase_test": cases,
        "trained_weight_tiles": 78, "verified_weight_bytes": 11534336,
        "direct_serial_matrix_cycles": cycles[0], "credited_request_matrix_cycles": cycles[1],
        "additional_matrix_cycles": cycles[1] - cycles[0],
        "modeled_forward_and_return_delay_pipeline_cycles": [2, 6],
        "credits": 16, "output_setup_margin_ps_at_slow_core_corner": float(setup),
        "output_hold_margin_ps_at_fast_core_corner": float(hold),
        "credit_input_hold_margin_ps_at_fast_core_corner": float(credit),
        "matched_16ma_clock_and_output_pad_envelope_by_load_limit_pf": pad_envelope(setup, hold),
        "mapped_area_square_micrometers": float(Decimal(area)),
        "candidate_signal_pins_if_link_replaces_ready_and_adds_clock": signals,
        "geometric_site_margin_even_charging_the_entire_new_module": spare,
        "structural_bundle_source_files": source_count,
        "structural_bundle_unique_modules": module_count,
        "scope": "The standalone transport test uses a delayed forwarded clock, registered output data and "
                 "delayed credit pulses. The trained fixture models propagation as whole-cycle pipelines. "
                 "The existing ready pin carries credits in the structural wrapper, and the sender fault remains "
                 "internal. Static timing uses ideal clocks and external delay budgets. The pad screen excludes "
                 "package and board parasitics.",
        "evidence_sha256": {str(path.relative_to(ROOT) if path.is_absolute() else path): digest(path) for path in paths},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "bind", "verify"))
    opts = parser.parse_args()
    assert Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    out = WORK.resolve()
    if opts.mode == "prepare":
        prepare(out)
    elif opts.mode == "bind":
        bind(out)
    else:
        print(json.dumps(verify(out), indent=2, sort_keys=True))
