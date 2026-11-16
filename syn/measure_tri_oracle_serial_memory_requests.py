"""Compare serialized memory requests with the archived mapped weight replay."""

import argparse
from hashlib import file_digest
import json
from math import ceil
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import CHILD, TOP
from link_tri_oracle_indexed_whole_chip import module_at, signature, spans


RECORDS = Path("records")
ORIGINAL = Path(".cache/compact_index_io/fixed")
SERVICES = (("parallel", 0), ("full_address", 1), ("aligned_address", 2))
INDEXED_FIXTURE = Path(".cache/model_reference/lossless_weight_burst_probe/streaming_probe/aligned/"
                       "partial_retention/indexed_down")

# Each mode uses the same memory responder. Serial mode keeps a request pending
# until the last transfer and round-robins the two lanes on one shared link.
SERIAL_REQUESTS = """  int request_mode, flits_remaining, packed_requests, full_requests;
  bit pending, lane_selected, next_lane;
  logic [1:0] request_open;
  initial begin
    if (!$value$plusargs("REQUEST_MODE=%d", request_mode)) $fatal(1,"REQUEST_MODE_REQUIRED");
    if (request_mode<0 || request_mode>2) $fatal(1,"INVALID_REQUEST_MODE");
  end
  for (genvar i=0; i<2; i++) begin : request_eligibility
    assign request_open[i]=req_valid[i] && !active[i] && cycle%5!=i;
  end
  always @(posedge clk) begin
    if (!rst_n) begin
      pending<=0;
      next_lane<=0;
      flits_remaining<=0;
    end else if (request_mode!=0) begin
      if (!pending && |request_open) begin
        bit selected, short_packet;
        selected=request_open[next_lane] ? next_lane : !next_lane;
        short_packet=request_mode==2 && req_address[selected][63:42]==0 &&
                     req_address[selected][5:0]==0;
        pending<=1;
        lane_selected<=selected;
        next_lane<=!selected;
        flits_remaining<=short_packet ? 1 : 3;
        if (short_packet) packed_requests++;
        else full_requests++;
      end else if (pending && flits_remaining>1) begin
        flits_remaining<=flits_remaining-1;
      end else if (pending && req_ready[lane_selected]) begin
        if (!req_valid[lane_selected]) $fatal(1,"REQUEST_DROPPED_IN_SERIALIZER");
        pending<=0;
      end
    end
  end
"""


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def replace(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def extract(path, old, output):
    old_bytes = old.read_bytes()
    old_index = spans(old_bytes)
    replacements = {}
    with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        index = spans(data)

        def modules(master):
            return {match[2].decode(): match[1].decode()
                    for match in CHILD.finditer(module_at(data, index, master))}

        master = TOP
        for instance in ("layer", "layer", "feedforward", "compute", "compute", "tensor"):
            master = modules(master)[instance]
        children = modules(master)
        for instance, previous in (
            ("packed_loader", "tri_oracle_dual_group_weight_transport"),
            ("packed_write_stage", "tri_oracle_packed_write_stage_mapped"),
        ):
            target = children[instance]
            original_ports = signature(module_at(old_bytes, old_index, previous))
            ports = signature(module_at(data, index, target))
            assert all(ports[pin] == value for pin, value in original_ports.items())
            resets = sorted(ports.keys() - original_ports.keys())
            assert all(pin.startswith("tri_reset_tree_") and ports[pin] == (b"input", b"") for pin in resets)
            replacements[previous] = target, resets
        pending = [target for target, _ in replacements.values()]
        reachable = set()
        while pending:
            master = pending.pop()
            if master not in reachable:
                reachable.add(master)
                pending.extend(child for child in modules(master).values() if child in index)
        with output.open("xb") as stream:
            for master in sorted(reachable, key=lambda name: index[name][0]):
                stream.write(module_at(data, index, master) + b"\n")
    return replacements


def prepare(output):
    output.mkdir(exist_ok=True)
    placed_path = RECORDS / "tri_oracle_repacked_whole_chip_cold_reload.json"
    placed = read(placed_path)
    netlist, = (Path(name) for name in placed["evidence_sha256"] if name.endswith("/cold.v"))
    assert digest(netlist) == placed["cold_netlist_sha256"]
    prior = read(RECORDS / "tri_oracle_compact_index_ingress.json")
    prepared = ORIGINAL / "prepared.json"
    assert digest(prepared) == prior["evidence_sha256"][str(prepared)]
    previous = read(prepared)["evidence_sha256"]
    cut = ORIGINAL / "current_weight_cut.v"
    bench = ORIGINAL / "compact_index_replay_tb.sv"
    assert all(digest(file) == previous[str(file)] for file in (cut, bench))
    mapped = output / "packed_weight_cut.v"
    replacements = extract(netlist, cut, mapped)
    text = bench.read_text()
    for (old, (name, resets)), instance in zip(replacements.items(), ("dut", "stage"), strict=True):
        reset_connections = "".join(f"\n      .{pin}(rst_n)," for pin in resets)
        text = replace(text, f"{old} {instance} (", f"{name} {instance} ({reset_connections}")
    text = replace(text, "  for (genvar lane=0;lane<2;lane++) begin : lanes",
                   SERIAL_REQUESTS + "  for (genvar lane=0;lane<2;lane++) begin : lanes")
    text = replace(text, "assign req_ready[lane]=!active[lane] && cycle%5!=lane;",
                   "assign req_ready[lane]=request_mode==0 ? !active[lane] && cycle%5!=lane :\n"
                   "        pending && lane_selected==lane && flits_remaining==1;")
    text = replace(text, '      $display("DUAL_GROUP_MATRIX_WRITES', '''      $display("MEMORY_REQUEST_FORMAT mode=%0d compact=%0d full=%0d",
               request_mode,packed_requests,full_requests);
      $display("DUAL_GROUP_MATRIX_WRITES''')
    output_bench = output / bench.name
    output_bench.write_text(text)
    print(json.dumps({
        "cold_netlist_sha256": placed["cold_netlist_sha256"],
        "extracted_masters": {old: [name, len(resets)] for old, (name, resets) in replacements.items()},
        "evidence_sha256": {str(path): digest(path) for path in
                            (placed_path, cut, bench, prepared, mapped, output_bench, Path(__file__))},
    }, indent=2, sort_keys=True))


def budget(receipts):
    fit = receipts["pads"]
    workload = receipts["workload"]
    ranked = receipts["signs"]
    prior = receipts["projection"]
    target = receipts["target"]["system_latency"]
    request_count = 2 * workload["gate_up"]["payload_bursts"] + workload["down_projection"]["payload_bursts"]
    assert request_count == workload["one_request_cycle_per_burst"]
    response_beats = (workload["gate_up"]["payload_beats"] + workload["down_projection"]["payload_beats"] +
                      workload["modeled_single_response_index_bursts"])
    assert workload["modeled_single_response_index_bursts"] == workload["gate_up"]["payload_bursts"]
    available = fit["narrow_host_candidate"]["sites_after_host_clock_reset_and_512_receive_pads"]
    # Keep one valid, ready, last and error signal per receive lane plus
    # two handshakes for the shared transmit link.
    width = available - 2 * 4 - 2
    assert width == 22 and fit["paper_latency_cycles"] == ranked["paper_latency_cycle_budget"]
    clock = target["clock_megahertz"] * 1000
    paper_cycles = target["milliseconds"] * clock
    assert paper_cycles == prior["target_cycles"] == fit["paper_latency_cycles"]
    line_reads = ranked["modeled_sign_line_reads"]
    estimates = {}
    for name, packet_bits in (("full_address", 64 + 6 + 2), ("aligned_address", 36 + 6 + 2)):
        flits = ceil(packet_bits / width)
        # Grant ideal balance on both read lanes and complete overlap of a
        # lane's outgoing request with the other lane's incoming response.
        lane_cycles = (response_beats + flits * request_count + line_reads + 1) // 2
        shared_cycles = flits * request_count
        with_projection = max(lane_cycles, shared_cycles) + prior["minimum_projection_issue_cycles"]
        estimates[name] = {
            "request_bits": packet_bits, "flits_per_request": flits,
            "optimistic_read_and_request_cycles": max(lane_cycles, shared_cycles),
            "with_serial_projection_ms": with_projection / clock,
            "cycles_left_for_other_work_in_serial_model": paper_cycles - with_projection,
        }
    return {
        "shared_single_edge_request_data_bits": width,
        "modeled_weight_requests": request_count,
        "modeled_weight_response_beats": response_beats,
        "modeled_sign_line_reads": line_reads,
        "paper_target_ms": target["milliseconds"],
        "estimates": estimates,
    }


def summarize(output):
    prepared_path = output / "prepared.json"
    receipt = read(prepared_path)
    evidence = receipt["evidence_sha256"]
    assert all(digest(Path(path)) == expected for path, expected in evidence.items())
    paths = {
        "pads": RECORDS / "tri_oracle_cold_memory_boundary.json",
        "workload": Path(".cache/memory_response_gearbox/workload_serial.json"),
        "signs": RECORDS / "tri_oracle_ranked_sign_workload_bounds.json",
        "projection": Path(".cache/physical/wide_weight_loader/joined_chip_partition/serial_projection_budget.json"),
        "target": RECORDS / "paper_result_targets.json",
    }
    prior = read(RECORDS / "tri_oracle_memory_response_gearbox.json")
    assert digest(paths["workload"]) == prior["evidence_sha256"][str(paths["workload"])]
    refs = {key: read(path) for key, path in paths.items()}
    assert refs["pads"]["cold_netlist_sha256"] == receipt["cold_netlist_sha256"]
    ingress_path = RECORDS / "tri_oracle_compact_index_ingress.json"
    ingress = read(ingress_path)["evidence_sha256"]
    mapped_ingress = Path(".cache/compact_index_io/genus/netlist.v")
    standard_cells = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140.v")
    weights = Path(".cache/model_reference/packed_down_export/v1/weights.bin")
    fixtures = (INDEXED_FIXTURE / "down_index.bin", INDEXED_FIXTURE / "down_payload.bin")
    for path in (mapped_ingress, weights, *fixtures):
        digest_value = digest(path)
        assert digest_value == ingress[str(path)]
        evidence[str(path)] = digest_value
    cells_path = RECORDS / "tri_oracle_narrow_host_command_link.json"
    cell_digest = digest(standard_cells)
    assert cell_digest == read(cells_path)["evidence_sha256"][str(standard_cells)]
    evidence[str(standard_cells)] = cell_digest
    results = {}
    for name, mode in SERVICES:
        path = output / name / "console.log"
        log = path.read_text()
        observed_paths = {(path.parent / source).resolve() for source in re.findall(r"(?m)^file: (.+)$", log)}
        expected_paths = (mapped_ingress, standard_cells, output / "packed_weight_cut.v",
                          output / "compact_index_replay_tb.sv")
        assert all(source.resolve() in observed_paths for source in expected_paths)
        assert all((path.parent / fixture.name).resolve() == fixture.resolve() for fixture in fixtures)
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        cols, = re.findall(r"(?m)^MEMORY_REQUEST_FORMAT mode=(\d+) compact=(\d+) full=(\d+)$", log)
        selected, compact, full = map(int, cols)
        assert selected == mode
        assert "STAGED_INDEXED_DOWN_MATRIX_PASS cases=78 exact_bytes=11534336" in log
        assert "INDEXED_WEIGHT_MODE_PASS switched_to_raw=1" in log
        cycles, = re.findall(r"(?m)^DUAL_GROUP_MATRIX_WRITES writes=90112 cycles=(\d+)$", log)
        results[name] = {"matrix_cycles": int(cycles), "compact_requests": compact, "full_requests": full}
        evidence[str(path)] = digest(path)
    assert results["aligned_address"]["compact_requests"] == results["full_address"]["full_requests"] > 0
    assert results["aligned_address"]["full_requests"] == 0
    assert results["parallel"]["matrix_cycles"] < results["aligned_address"]["matrix_cycles"] < (
        results["full_address"]["matrix_cycles"]
    )
    for path in (*paths.values(), prepared_path, ingress_path, cells_path, RECORDS / "tri_oracle_memory_response_gearbox.json"):
        evidence[str(path)] = digest(path)
    receipt.update(state="serial_memory_request_service_compared_on_mapped_weight_fixture",
                   down_projection_fixture=results, conditional_archived_workload=budget(refs),
                   scope="Xcelium fixture applies request serialization delays to the current extracted mapped "
                         "weight loader and write stage with functional reset pins tied together. The host "
                         "model grants ideal two-lane receive balance and adds archived projection issue "
                         "cycles serially. Packet encoding, physical timing, real memory, writes and whole-model "
                         "execution remain unverified.")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "summarize"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    (prepare if args.phase == "prepare" else summarize)(args.directory)
