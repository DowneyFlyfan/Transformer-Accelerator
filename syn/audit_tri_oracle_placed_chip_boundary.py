"""Audit placed signal terminals against a TSMC 28 nm single-row pad-ring bound."""

import argparse
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from hashlib import file_digest, sha256
import json
from pathlib import Path
import re
import tarfile


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_chip_command_layer_parallel_chip"
PAD_ARCHIVE = Path("/pdks/tsmc28hpc/IO/tphn28hpcpgv18_170a/AN61001_20180125/"
                   "tphn28hpcpgv18_110a_sefu10lm.tar.gz")
GROUPS = {
    "clock_and_reset": "clk rst_n",
    "command_and_response": ("command_valid command_ready command_opcode command_tag payload_valid payload_ready "
                             "payload_data payload_last response_valid response_ready response_error response_opcode response_tag"),
    "memory_primary_read": "req_valid req_ready req_address req_length req_wide rsp_valid rsp_ready rsp_data rsp_last rsp_error",
    "memory_auxiliary_read": ("aux_req_valid aux_req_ready aux_req_address aux_req_length aux_rsp_valid aux_rsp_ready "
                              "aux_rsp_data aux_rsp_last aux_rsp_error"),
    "memory_write": ("wr_req_valid wr_req_ready wr_address wr_length wr_data_valid wr_data_ready wr_data wr_data_last "
                     "wr_strobe wr_rsp_valid wr_rsp_ready wr_rsp_error"),
    "memory_base_addresses": "value_read_base context_base",
    "normalization_stream": "stats_valid stats_last stats_data stats_ready replay_valid replay_last replay_data replay_gamma replay_ready residual_token",
    "rotary_angles": "angle_valid angle_last angle_ready angle_cos angle_sin",
    "token_signs_and_origins": "sign_valid sign_ready sign_data map_valid map_last map_ready map_index map_origin",
    "head_prediction_result": "head_done_streaming head_done_id head_done_inner head_done_recent",
    "feedforward_result": "out_valid out_ready out_last out_token out_tag out_start out_count out_data",
    "attention_result": "result_values",
}
PORT = re.compile(r"\s+(input|output)(?: \[(\d+):0\])? (\w+);")
DEF_PIN = re.compile(r"- (\S+) \+ NET (\S+) \+ DIRECTION (INPUT|OUTPUT) \+ USE SIGNAL")
DEF_POSITION = re.compile(r"  \+ (PLACED|FIXED) \( (\d+) (\d+) \) ([NEWS]) ;")


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def verilog_ports(path):
    with path.open() as stream:
        target = f"module {TOP} (\n"
        assert any(line == target for line in stream), path
        header = []
        for line in stream:
            line = line.strip()
            if line.endswith(");"):
                header.extend(line[:-2].split())
                break
            header.extend(line.rstrip(",").split())
        ports = {}
        for line in stream:
            if line.startswith("   // Internal wires") or line.startswith("   wire "):
                break
            if not line.strip():
                continue
            match = PORT.fullmatch(line.rstrip())
            assert match, line
            direction, msb, name = match.groups()
            assert name not in ports, name
            ports[name] = (direction.upper(), None if msb is None else int(msb) + 1)
        assert len(header) == len(set(header)) and set(header) == ports.keys()
    return ports


def check_ports(ports, terminals):
    expected = {
        bit: direction
        for name, (direction, width) in ports.items()
        for bit in ([name] if width is None else (f"{name}[{index}]" for index in range(width)))
    }
    assert terminals == expected, "Placed terminals disagree with mapped ports"


def def_boundary(path, library_cells):
    with path.open() as stream:
        die = units = None
        pad_instances = Counter()
        in_components = False
        for line in stream:
            if line.startswith("UNITS DISTANCE MICRONS "):
                units = int(line.split()[3])
            elif line.startswith("DIEAREA "):
                die = tuple(map(int, re.findall(r"-?\d+", line)))
            elif line.startswith("COMPONENTS "):
                in_components = True
            elif line == "END COMPONENTS\n":
                in_components = False
            elif in_components and line.startswith("- "):
                _, _, master, *_ = line.split(maxsplit=3)
                if master in library_cells:
                    pad_instances[master] += 1
            elif line.startswith("PINS "):
                count = int(line.split()[1])
                break
        assert die and units and not in_components, path
        left, bottom, right, top = die
        edges = {"E": ("left", 0, left, "M4"), "W": ("right", 0, right, "M4"),
                 "N": ("bottom", 1, bottom, "M5"), "S": ("top", 1, top, "M5")}
        terminals, positions = {}, set()
        sides = Counter()
        for line in stream:
            if line == "END PINS\n":
                break
            match = DEF_PIN.fullmatch(line.rstrip())
            assert match, line
            name, net, direction = match.groups()
            assert name == net and name not in terminals, line
            layer, = re.findall(r"^  \+ LAYER (M\d+) ", next(stream))
            match = DEF_POSITION.fullmatch(next(stream).rstrip())
            assert match, name
            _, x, y, orientation = match.groups()
            xy = int(x), int(y)
            edge, axis, coordinate, expected_layer = edges[orientation]
            assert layer == expected_layer and xy[axis] == coordinate, (name, xy)
            assert left <= xy[0] <= right and bottom <= xy[1] <= top, (name, xy)
            assert (xy, layer) not in positions, (name, xy)
            positions.add((xy, layer))
            terminals[name] = direction
            sides[edge] += 1
        else:
            raise AssertionError("Missing END PINS")
        assert len(terminals) == count
    return ((Decimal(right-left)/units, Decimal(top-bottom)/units), terminals, dict(sides), pad_instances)


def pad_views(archive):
    with tarfile.open(archive, "r:gz") as package:
        (member,) = (entry for entry in package if entry.isfile() and entry.name.endswith(".lef"))
        with package.extractfile(member) as stream:
            raw = stream.read()
    macros = {}
    for name, body in re.findall(r"(?ms)^MACRO (\w+)\n(.*?)^END \1\s*$", raw.decode()):
        cell_class, = re.findall(r"(?m)^    CLASS (.+?)\s*;", body)
        width, height = re.search(r"(?m)^    SIZE (\S+) BY (\S+) ;$", body).groups()
        pins = re.findall(r"(?m)^    PIN (\w+)\s*$", body)
        assert name not in macros and pins.count("PAD") <= 1
        macros[name] = (cell_class, Decimal(width), Decimal(height), "PAD" in pins)
    assert macros
    pads = [(width, height) for kind, width, height, signal in macros.values() if kind == "PAD" and signal]
    corners = [(width, height) for kind, width, height, _ in macros.values() if kind.startswith("ENDCAP")]
    assert pads and corners and all(width > 0 and height > 0 for width, height in (*pads, *corners))
    assert all(width == height for width, height in corners)
    return set(macros), len(pads), min(min(size) for size in pads), min(width for width, _ in corners), sha256(raw).hexdigest()


def pad_limit(die, width, corner):
    assert width > 0 and all(side > 2*corner for side in die)
    return 2 * sum(int((side-2*corner)//width) for side in die)


def summarize_ports(ports):
    remaining = set(ports)
    result = {}
    for group, names in GROUPS.items():
        members = names.split()
        assert set(members) <= remaining
        remaining.difference_update(members)
        counts = Counter()
        for name in members:
            direction, width = ports[name]
            counts[direction.lower()] += width or 1
        result[group] = {"input": counts["input"], "output": counts["output"],
                         "total": counts.total()}
    assert not remaining, remaining
    return result


def memory_rate_bound(identity):
    traffic_path = ROOT / "records/tri_oracle_ranked_sign_workload_bounds.json"
    target_path = ROOT / "records/paper_result_targets.json"
    traffic = json.loads(traffic_path.read_text())
    targets = json.loads(target_path.read_text())
    paper = ROOT / targets["source"]
    paper_hash = digest(paper)
    assert paper_hash == "6d6b998c459ade605e082d723374462e1d14b53d6a6b13063ca0f8d1180b1d9f"
    latency = targets["system_latency"]
    assert traffic["state"] == "normalized_ranked_sign_cache_budget_reconciled"
    assert traffic["candidate_sha256"] == identity
    assert (latency["prefill_tokens"], latency["decode_tokens"]) == (traffic["prompt_tokens"], traffic["decode_steps"])
    cycles = latency["clock_megahertz"] * 1000 * latency["milliseconds"]
    assert cycles == traffic["paper_latency_cycle_budget"]
    bits = 8 * traffic["modeled_weight_plus_sign_read_bytes"]
    read_bits_per_cycle = Fraction(bits, cycles)
    return {
        "archived_workload_read_payload_bytes": bits // 8,
        "paper_latency_cycle_budget": cycles,
        "minimum_average_read_bits_per_cycle": round(float(read_bits_per_cycle), 3),
        "ideal_receive_pads_at_one_bit_per_cycle": -(-bits // cycles),
        "ideal_receive_pads_at_two_bits_per_cycle": -(-bits // (2 * cycles)),
        "traffic_record_sha256": digest(traffic_path),
        "paper_targets_sha256": digest(target_path),
        "paper_sha256": paper_hash,
        "scope": "Ideal receive-only lower bound from the modeled archived workload. Every bit time carries payload.",
    }


def audit(placement, archive):
    assert __debug__ and Path("/.dockerenv").is_file()
    public = ROOT / "records/tri_oracle_restored_chip_placement_and_memory.json"
    reference = json.loads(public.read_text())
    receipt = placement / "receipt.json"
    assert digest(receipt) == reference["local_placement_receipt_sha256"]
    native = json.loads(receipt.read_text())
    assert native["candidate_sha256"] == reference["candidate_sha256"]
    assert native["state"] == "registered_flush_incremental_placement_verified"
    assert all(native["native"][stage]["native_exit_status"] == 0 for stage in ("place", "cold"))

    cells, signal_cells, minimum_width, corner, abstract_hash = pad_views(archive)
    observed = {}
    for stage in ("place", "cold"):
        verilog, layout = (placement / stage / name for name in ("placed.v", "placed.def"))
        assert digest(verilog) == reference["placed_netlist_sha256"][stage]
        assert digest(layout) == reference["placed_def_sha256"][stage]
        ports = verilog_ports(verilog)
        die, terminals, sides, pad_instances = def_boundary(layout, cells)
        check_ports(ports, terminals)
        observed[stage] = die, ports, sides, pad_instances
    assert observed["place"] == observed["cold"]
    die, ports, sides, pad_instances = observed["place"]
    groups = summarize_ports(ports)
    total = sum(group["total"] for group in groups.values())
    assert total == sum(sides.values()) == reference["signal_pins"]
    assert list(die) == [Decimal(str(mm))*1000 for mm in reference["die_dimensions_mm"]]

    rejected = []
    for name, mismatch in (("missing_port_bit", {"data[0]": "INPUT"}),
                           ("wrong_port_direction", {"data[0]": "INPUT", "data[1]": "OUTPUT"})):
        try:
            check_ports({"data": ("INPUT", 2)}, mismatch)
        except AssertionError:
            rejected.append(name)
        else:
            raise AssertionError(f"Port verifier accepted {name}")
    assert pad_limit((Decimal(100), Decimal(100)), Decimal(20), Decimal(10)) == 16
    pads_with_corners = pad_limit(die, minimum_width, corner)
    memory = sum(group["total"] for name, group in groups.items() if name.startswith("memory_"))
    raw_data = sum(group["total"] for name, group in groups.items()
                   if name in {"memory_primary_read", "memory_auxiliary_read", "memory_write"})
    assert not pad_instances and raw_data > pads_with_corners
    rate = memory_rate_bound(reference["candidate_sha256"])
    assert rate["ideal_receive_pads_at_one_bit_per_cycle"] > pads_with_corners
    return dict(state="repaired_placement_signal_boundary_verified", candidate_sha256=reference["candidate_sha256"],
                placed_netlist_sha256=reference["placed_netlist_sha256"],
                placed_def_sha256=reference["placed_def_sha256"],
                placement_receipt_sha256=reference["local_placement_receipt_sha256"],
                signal_terminals=total, terminals_by_edge=sides, signals_by_function=groups,
                memory_interface_signal_bits=memory, raw_memory_channel_signal_bits=raw_data,
                pad_library_signal_masters=signal_cells, pad_instances_from_audited_library=sum(pad_instances.values()),
                pad_abstract_sha256=abstract_hash, die_um=list(map(str, die)),
                minimum_signal_pad_width_um=str(minimum_width), minimum_corner_width_um=str(corner),
                single_row_pad_capacity_without_corners=pad_limit(die, minimum_width, Decimal(0)),
                single_row_pad_capacity_with_corners=pads_with_corners,
                archived_workload_interface_rate=rate,
                negative_controls_rejected=rejected,
                scope="Placed Verilog and DEF boundary inventory. Pad capacity assumes one signal per pad on one perimeter row and excludes power, ground, spacing and packaging constraints.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placement", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pad-archive", type=Path, default=PAD_ARCHIVE)
    args = parser.parse_args()
    report = audit(args.placement, args.pad_archive)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(report["state"], report["signal_terminals"], report["raw_memory_channel_signal_bits"],
          report["single_row_pad_capacity_with_corners"], flush=True)
