"""Replay the widened chip's five-client read arbiter in Xcelium."""

import argparse
from hashlib import sha256
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import TOP as COMPUTE
from link_tri_oracle_indexed_whole_chip import module_at, pins, signature, spans
from prepare_tri_oracle_booth_packet_replay import replace_once
from verify_tri_oracle_booth_memory_interconnect import check_clusters
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, digest, read
from verify_tri_oracle_wide_seed_resources import ACCELERATOR, SEED


TOP = "tri_oracle_grouped_read_fabric_tb"
FABRIC = "tri_oracle_grouped_read_fabric_cells"
WIDE_PROOF = Path("records/tri_oracle_wide_seed_paper_resources.json")
REFERENCE = Path("records/tri_oracle_corrected_booth_request_response_overlap.json")
RTL = Path("verilog/tri_oracle_grouped_read_fabric.sv")
BENCH = Path(f"verilog/{TOP}.sv")
LIB = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140.v")
CASES = ("rtl", "mapped", "swapped_bits")
DATA_CALL = "data_word(client, sequence_no, lane_beat[lane])"


def replay_bench(mapped_ports, case):
    text = BENCH.read_text()
    text = replace_once(text, "    int lane_owner", "    int routed[5][2] = '{default:'{default:0}};\n    int lane_owner")
    text = replace_once(text, "        return (64'(client)", """        return ((64'h9c7d3fe24b180000 ^ (64'(sequence_no) * 64'h9e3779b9 << 20))
                & 64'hfffffffffff80000) | (64'(client)""")
    text = replace_once(text, "data_word(input int client, sequence_no, beat);",
                        "data_word(input int client, sequence_no, beat, lane, ordinal);")
    text = replace_once(text, "        for (int word = 0; word < 8; word++)", """        if (ordinal == 0) return '0;
        if (ordinal == 1) return '1;
        // Binary codes give every data bit a unique signature on every route.
        if (ordinal < 11) begin
            for (int bit_index = 0; bit_index < 512; bit_index++)
                value[bit_index] = 1'((bit_index >> (ordinal - 2)) & 1);
            return value;
        end
        for (int word = 0; word < 8; word++)""")
    text = replace_once(text, "(64'(word) << 32) |", "(64'(lane) << 46) | (64'(word) << 32) |")
    assert text.count(DATA_CALL) == 2
    text = text.replace(DATA_CALL, "data_word(client, sequence_no, lane_beat[lane], lane, routed[client][lane])")
    text = replace_once(text, "                    transfers++;",
                        "                    transfers++;\n                    routed[lane_owner[lane]][lane]++;")
    text = replace_once(text, "        if (offered[0] >= 0", """        $display("WIDE_READ_CYCLE %0d owners=%0d,%0d offers=%0d,%0d req=%b/%b rsp=%b/%b clients=%b/%b",
                 cycles, lane_owner[0], lane_owner[1], offered[0], offered[1],
                 mem_req_valid, mem_req_ready, mem_rsp_valid, mem_rsp_ready, client_req_ready, client_rsp_valid);
        if (offered[0] >= 0""")
    end = text.index('        $display("GROUPED_READ_PASS')
    text = text[:end] + """        for (int client = 0; client < 5; client++) begin
            for (int lane = 0; lane < 2; lane++) begin
                if (routed[client][lane] < 11)
                    $fatal(1, "GROUPED_READ_UNTESTED_ROUTE client=%0d lane=%0d beats=%0d", client, lane, routed[client][lane]);
                $display("WIDE_MAPPED_ROUTE client=%0d lane=%0d beats=%0d", client, lane, routed[client][lane]);
            end
        end
""" + text[end:]
    if case == "rtl":
        return text

    connections = []
    for port in mapped_ports:
        escaped = f"\\{port} " if "[" in port else port
        signal = port
        if case == "swapped_bits" and port == "mem_rsp_data[1]":
            signal = "{mem_rsp_data[1][511:8], mem_rsp_data[1][6], mem_rsp_data[1][7], mem_rsp_data[1][5:0]}"
        connections.append(f"        .{escaped}({signal})")
    return replace_once(text, "    tri_oracle_grouped_read_fabric dut (.*);",
                        f"    {FABRIC} dut (\n" + ",\n".join(connections) + "\n    );")


def check_ports(ports):
    expected = dict.fromkeys(("clk", "rst_n"), (b"input", b""))
    vectors = (
        (b"input", b"[4:0]", ("client_req_valid", "client_rsp_ready")),
        (b"output", b"[4:0]", ("client_req_ready", "client_rsp_valid", "client_rsp_last", "client_rsp_error")),
        (b"input", b"[1:0]", ("mem_req_ready", "mem_rsp_valid", "mem_rsp_last", "mem_rsp_error")),
        (b"output", b"[1:0]", ("mem_req_valid", "mem_rsp_ready")),
    )
    for direction, width, names in vectors:
        expected.update(dict.fromkeys(names, (direction, width)))
    for interface, channels, request, response in (("client", 5, b"input", b"output"), ("mem", 2, b"output", b"input")):
        for lane in range(channels):
            expected[f"{interface}_req_address[{lane}]"] = request, b"[63:0]"
            expected[f"{interface}_req_length[{lane}]"] = request, b"[5:0]"
            expected[f"{interface}_rsp_data[{lane}]"] = response, b"[511:0]"
    assert ports == expected


def setup():
    placement, proof, overlap = map(read, (SEED, WIDE_PROOF, REFERENCE))
    sources = {SEED: digest(SEED), WIDE_PROOF: digest(WIDE_PROOF), REFERENCE: digest(REFERENCE),
               RTL: digest(RTL), BENCH: digest(BENCH), LIB: digest(LIB)}
    assert overlap["evidence_sha256"][str(LIB)] == sources[LIB]
    candidate, = [Path(path) for path in placement["evidence_sha256"] if path.endswith("/placement_seed/candidate.v")]
    checksum = digest(candidate)
    assert checksum == placement["candidate_sha256"] == proof["candidate_sha256"]
    sources[candidate] = checksum
    with candidate.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        index = spans(data)
        instance = "tri_oracle_chip_credited_request"
        # Follow the same registered accelerator path whose SRAM owners were verified.
        for child in ACCELERATOR.decode().strip("/").split("/"):
            body = module_at(data, index, instance)
            matches = re.findall(rb"(?m)^\s*([\w$]+)\s+" + child.encode() + rb"\s*\(\s*\.", body)
            instance, = [name.decode() for name in matches]
        assert instance == COMPUTE
        parent = module_at(data, index, instance)
        clients = []
        for client in range(5):
            name = f"grouped_{client}"
            master, = re.findall(rf"(?m)^\s*([\w$]+)\s+{name}\s*\(\s*\.", parent.decode())
            clients.append(pins(parent, master, name))
        check_clusters(clients, pins(parent, FABRIC, "grouped_reads"))
        mapped = module_at(data, index, FABRIC)
        ports = signature(mapped)
        check_ports(ports)
        library_cells = set(re.findall(rb"(?m)^module\s+([\w$]+)\b", LIB.read_bytes()))
        used_cells = set(re.findall(rb"(?m)^\s*([\w$]+)\s+(?:\\\S+|[\w$]+)\s*\(\s*\.", mapped))
        assert used_cells and used_cells <= library_cells
    files = {case: {f"{TOP}.sv": replay_bench(ports, case),
                    "fabric.v": RTL.read_text() if case == "rtl" else mapped.decode() + "\n"}
             for case in CASES}
    return candidate.parents[1] / "mapped_grouped_read_cycle_replay", files, sources


def verify():
    output, definitions, sources = setup()
    positive = {}
    checked = re.compile(r"(?m)^GROUPED_READ_PASS clusters=5 bursts=(\d+) transfers=(\d+) errors=(\d+) "
                         r"request_stalls=(\d+) response_stalls=(\d+) overlapping_cycles=(\d+)\s*$")
    for case, files in definitions.items():
        work = output / case
        for name, content in files.items():
            assert (work / name).read_text() == content
            sources[work / name] = digest(work / name)
        log = work / "xrun.log"
        status = work / "exit_status"
        sources[log] = digest(log)
        sources[status] = digest(status)
        text = log.read_text()
        assert "xrun" in text and not re.search(r"\*E,", text)
        if case == "swapped_bits":
            assert int(status.read_text()) != 0
            assert re.search(r"(?m)^GROUPED_READ_BAD_RESPONSE lane=1 client=[0-4] beat=\d+$", text)
            assert "Simulation terminated via $fatal(1)" in text and checked.search(text) is None
            continue
        assert status.read_text().strip() == "0" and "GROUPED_READ_BAD_RESPONSE" not in text
        pass_line, = checked.findall(text)
        bursts, transfers, errors, request_stalls, response_stalls, overlap = map(int, pass_line)
        entries = re.findall(r"(?m)^WIDE_MAPPED_ROUTE client=(\d+) lane=(\d+) beats=(\d+)\s*$", text)
        assert len(entries) == 10
        routes = {(int(client), int(lane)): int(beats) for client, lane, beats in entries}
        assert set(routes) == {(client, lane) for client in range(5) for lane in range(2)}
        assert sum(routes.values()) == transfers and min(routes.values()) >= 11
        expected = [(63 if burst == 0 else 1 + (client * 5 + burst * 3) % 11, (client + burst) % 9 == 0)
                    for client in range(5) for burst in range(24)]
        assert (bursts, transfers, errors) == (len(expected), sum(beats for beats, _ in expected),
                                              sum(error for _, error in expected))
        assert request_stalls >= 15 and response_stalls >= 100 and overlap >= 100
        cycles = re.findall(r"(?m)^WIDE_READ_CYCLE \d+ .*\S$", text)
        assert len(cycles) >= overlap and all(line.split()[1] == str(i) for i, line in enumerate(cycles))
        positive[case] = {
            "bursts": bursts, "accepted_response_beats": transfers, "injected_terminal_errors": errors,
            "request_stall_observations": request_stalls, "response_stall_observations": response_stalls,
            "checked_cycles": len(cycles), "ownership_and_handshake_trace_sha256": sha256("\n".join(cycles).encode()).hexdigest(),
            "simultaneous_active_lane_cycles": overlap, "response_beats_by_client_and_lane": [
                [routes[client, lane] for lane in range(2)] for client in range(5)],
        }
    assert positive["rtl"] == positive["mapped"]
    sources[Path(__file__).resolve().relative_to(ROOT)] = digest(Path(__file__))
    return {
        "state": "wide_candidate_grouped_read_arbiter_rtl_and_mapped_replay_agree",
        "grouped_read_master": FABRIC, "candidate_sha256": read(WIDE_PROOF)["candidate_sha256"],
        "scope": "Xcelium burst replay through the arbiter extracted from the widened netlist. "
                 "The test exercises all client and lane combinations and distinguishes every bit in each data route. "
                 "Cluster engines, external memory and whole-chip performance require separate checks.",
        "response_width_bits": 512, "distinct_route_payload_patterns": 11,
        "negative_control": "Swapping response bits 7 and 6 at lane 1 triggered the mapped scoreboard.",
        **positive["mapped"], "evidence_sha256": {str(path): value for path, value in sources.items()},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    if args.phase == "prepare":
        folder, inputs, _ = setup()
        folder.mkdir()
        for case, files in inputs.items():
            work = folder / case
            work.mkdir()
            for name, contents in files.items():
                (work / name).write_text(contents)
        print(folder)
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
