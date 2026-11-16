"""Measure pin and read-bandwidth limits of the current cold Innovus export."""

import argparse
from fractions import Fraction
import json
from math import ceil
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import CHILD, TOP
from audit_tri_oracle_pad_ring_clearance import PAD_DEPTH_UM, dimensions, get_units, screen
from audit_tri_oracle_physical_io_budget import boundary, fixed_memory, indexed_weight_beats, macro_boxes, pressure, slots
from audit_tri_oracle_placed_chip_boundary import PAD_ARCHIVE, digest, pad_views
from check_tri_oracle_paper300_gate import PAPER_SHA256
from link_tri_oracle_indexed_whole_chip import module_at, pins, signature, spans


RECORDS = Path("records")
TRANSPORT = Path(".cache/model_reference/lossless_weight_burst_probe/transport_receipt.json")
LANES = ("rsp_data", "aux_rsp_data")


def read_ports(netlist):
    with netlist.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        index = spans(data)
        module = TOP
        body = module_at(data, index, module)
        external = signature(body)
        grouped = pins(body, "tri_oracle_grouped_read_fabric_cells", "grouped_reads")
        projection, = (match[1].decode() for match in CHILD.finditer(body) if match[2] == b"direct_projection")
        direct = pins(body, projection, "direct_projection")
        assert direct["rsp_data"] == b"proj_rsp_data"
        instance_path = ("layer", "layer", "feedforward", "compute", "compute", "tensor", "packed_loader")
        for instance in instance_path:
            child, = (match[1].decode() for match in CHILD.finditer(body) if match[2].decode() == instance)
            connections = pins(body, child, instance)
            body = module_at(data, index, child)
            module = child
        children = {match[2].decode() for match in CHILD.finditer(body)}
        assert {"raw_loader", r"\indexed_lane[0].loader", r"\indexed_lane[1].loader"} <= children
        loader = signature(body)
        for lane, (port, net) in enumerate(zip(LANES, (b"wide_rsp_data", b"aux_rsp_data"), strict=True)):
            assert grouped[f"mem_rsp_data[{lane}]"] == port.encode()
            assert connections[f"rsp_data[{lane}]"] == net
            assert loader[f"rsp_data[{lane}]"] == external[port]
        assert external["proj_rsp_data"] == (b"input", b"[63:0]")
        assert all(external[port] == (b"input", b"[511:0]") for port in LANES)
    return {"packed_weight_loader_path": ".".join(instance_path), "packed_weight_loader_master": module,
            "grouped_external_read_widths_bits": dict.fromkeys(LANES, 512),
            "direct_projection_read_width_bits": 64}


def narrow_host_budget(directory, read, pin, netlist_sha256, clear_sites, clock_reset_bits):
    prior = read(RECORDS / "tri_oracle_narrow_host_command_link.json")
    wrapper = read(directory / "wrapper.json")
    assert wrapper["cold_netlist_sha256"] == netlist_sha256
    for name, expected in wrapper["evidence_sha256"].items():
        pin(Path(name), expected)
    old_inputs = prior["evidence_sha256"]
    adapter = ".cache/host_command_link/genus/netlist.v"
    assert wrapper["evidence_sha256"][adapter] == old_inputs[adapter]
    cut = directory / "indexed_dispatch.v"
    pin(cut, old_inputs[".cache/host_command_link/indexed_dispatch.v"])
    for name in ("verilog/tri_oracle_host_command_link_tb.sv",
                 ".cache/physical/library/tcbn28hpcplusbwp12t40p140.v"):
        pin(Path(name), old_inputs[name])
    log = pin(directory / "console.log").read_text()
    assert all(f"file: {Path(name).resolve()}" in log for name in (
        cut, adapter, "verilog/tri_oracle_host_command_link_tb.sv",
        ".cache/physical/library/tcbn28hpcplusbwp12t40p140.v",
    ))
    result, = re.findall(r"(?m)^TRI_ORACLE_HOST_COMMAND_LINK_PASS (.+)$", log)
    observed = {name: int(value) for name, value in (item.split("=") for item in result.split())}
    assert observed == {"valid": 12, "malformed": 3, "rx": 579, "tx": 45}
    assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
    host_bits = wrapper["host_signals_after"]
    assert host_bits == prior["host_port_bits_after"]
    return {
        "validated_host_bits": host_bits,
        "host_bits_saved": wrapper["host_signals_before"] - host_bits,
        "wrapped_signal_bits": wrapper["wrapped_signal_bits"],
        "isolated_mapped_dispatcher_xcelium": observed,
        "sites_after_host_clock_reset_and_448_receive_pads": clear_sites - host_bits - clock_reset_bits - 448,
        "sites_after_host_clock_reset_and_512_receive_pads": clear_sites - host_bits - clock_reset_bits - 512,
        "scope": "Mapped host link replay with the extracted current dispatcher and a generated wrapper. "
                 "The pad allocation assumes two payload bits per pad per clock. The wrapper, memory "
                 "request and write packaging, physical capture, and complete chip replay remain unqualified.",
    }


def run(pad_archive, narrow_host_run=None):
    evidence = {}

    def pin(path, expected=None, *, label=None):
        name = label or str(path)
        if name not in evidence:
            evidence[name] = digest(path)
        assert expected is None or evidence[name] == expected, name
        return path

    def read(path, expected=None):
        return json.loads(pin(path, expected).read_bytes())

    cold = read(RECORDS / "tri_oracle_repacked_whole_chip_cold_reload.json")
    cold_inputs = cold["evidence_sha256"]
    netlist, = (Path(path) for path in cold_inputs if path.endswith("/cold/cold.v"))
    pin(netlist, cold["cold_netlist_sha256"])
    native = read(netlist.parents[1] / "verified.json", cold_inputs[str(netlist.parents[1] / "verified.json")])
    bindings_path = netlist.parents[1] / "verified_bindings.json"
    bindings = read(bindings_path, cold_inputs[str(bindings_path)])["evidence_sha256"]
    assert native["cold_netlist_sha256"] == cold["cold_netlist_sha256"]
    layout = netlist.with_name("layout.def")
    pin(layout, native["evidence_sha256"][str(layout)])
    assert evidence[str(layout)] == bindings[str(layout)]
    libraries = [pin(Path(path), checksum) for path, checksum in bindings.items() if path.endswith(".lef")]
    assert len(libraries) == cold["compiled_physical_abstracts_verified"]
    with layout.open() as stream:
        units = get_units(stream)
        outline, = (tuple(map(int, line)) for line in re.findall(
            r"(?m)^DIEAREA \( (\d+) (\d+) \) \( (\d+) (\d+) \) ;$", stream.read(4096)))
    width, height = cold["die_mm"]
    assert outline == (0, 0, int(width * 1000 * units), int(height * 1000 * units))
    fixed = fixed_memory(layout, cold["physical_components"])
    assert len(fixed) == cold["fixed_compiled_memory_macros"]
    _, halos = macro_boxes(fixed, dimensions(libraries, units))
    prior = read(RECORDS / "tri_oracle_physical_io_budget.json")["evidence_sha256"]
    _, _, pad_width, corner, _ = pad_views(pin(pad_archive, prior[str(PAD_ARCHIVE)], label=str(PAD_ARCHIVE)))
    edges = screen(units, outline, halos, pad_width, corner, PAD_DEPTH_UM)
    clear_sites = slots(edges)

    groups = boundary(netlist)
    signal_bits = sum(sum(role.values()) for role in groups.values())
    roles = ("command_and_response", "clock_and_reset")
    dedicated_control = sum(sum(groups[role].values()) for role in roles)
    available_receive = clear_sites - dedicated_control
    assert available_receive > 0
    target = read(RECORDS / "paper_result_targets.json")
    pin(Path(target["source"]), PAPER_SHA256)
    latency = target["system_latency"]
    cycles = latency["milliseconds"] * latency["clock_megahertz"] * 1000
    assert latency["external_memory_access_included"]
    traffic = read(RECORDS / "tri_oracle_ranked_sign_workload_bounds.json")
    assert (latency["prefill_tokens"], latency["decode_tokens"]) == (traffic["prompt_tokens"], traffic["decode_steps"])
    assert cycles == traffic["paper_latency_cycle_budget"]
    transport = read(TRANSPORT, prior[str(TRANSPORT)])
    lanes = transport["fixed_lane_traffic"]
    assert len(lanes) == 2
    raw = sum(lane["original_weight_beats"] for lane in lanes)
    encoding_path = TRANSPORT.with_name("receipt.json")
    encoding = read(encoding_path, transport["input_sha256"][str(encoding_path)])
    indexed = indexed_weight_beats(transport, encoding)
    assert raw == transport["original_weight_beats"]
    sign = traffic["modeled_sign_line_reads"]
    payloads = {"raw_weights_and_signs": 64 * (raw + sign),
                "indexed_weights_one_index_response_per_block_and_signs": 64 * (indexed + sign)}
    assert payloads["raw_weights_and_signs"] == traffic["modeled_weight_plus_sign_read_bytes"]
    scenarios = {}
    cycles_per_ms = latency["clock_megahertz"] * 1000
    for mode, byte_count in payloads.items():
        scenario = pressure(byte_count, cycles, clear_sites)
        receive = scenario["two_bits_per_cycle_input_pads"]
        scenario["sites_left_after_receive_and_dedicated_control"] = available_receive - receive
        scenario["ideal_payload_latency_ms_with_both_512_bit_read_ports"] = float(
            Fraction(ceil(Fraction(byte_count, 128)), cycles_per_ms))
        pad_cycles = ceil(Fraction(byte_count * 8, 2 * available_receive))
        scenario["ideal_payload_latency_ms_after_dedicated_control_pads"] = float(Fraction(pad_cycles, cycles_per_ms))
        scenario["fraction_of_ideal_receive_capacity_after_dedicated_control_pads"] = float(
            Fraction(byte_count * 8, 2 * available_receive * cycles))
        scenarios[mode] = scenario
    for source in ("audit_tri_oracle_physical_io_budget.py", "audit_tri_oracle_pad_ring_clearance.py",
                   "audit_tri_oracle_placed_chip_boundary.py", "link_tri_oracle_indexed_whole_chip.py",
                   Path(__file__).name):
        pin(Path("syn") / source)
    result = {
        "state": "cold_netlist_read_boundary_and_fixed_macro_pad_budget_verified",
        "cold_netlist_sha256": cold["cold_netlist_sha256"],
        "physical_revision_sha256": cold["candidate_sha256"],
        "read_boundary": read_ports(netlist),
        "top_level_signal_bits": signal_bits,
        "direct_signal_pad_deficit": signal_bits - clear_sites,
        "clear_pad_sites_by_edge": {name: slots({name: edge}) for name, edge in edges.items()},
        "clear_pad_sites": clear_sites,
        "dedicated_command_response_clock_reset_bits": dedicated_control,
        "paper_latency_cycles": cycles,
        "archived_local_workload_payload_floors": scenarios,
        "scope": "One-row pad geometry with fixed memory halos and smallest installed signal pad. "
                 "The analytical traffic floor uses the archived local trajectory, ideal joint port utilization, "
                 "and excludes compute, attention and other traffic. The two-bit-per-clock scenario grants "
                 "ideal signaling on both clock edges. It excludes package, power, control beyond the "
                 "dedicated subset, and pad timing, and does not establish interface feasibility.",
        "evidence_sha256": evidence,
    }
    if narrow_host_run is not None:
        result["narrow_host_candidate"] = narrow_host_budget(
            narrow_host_run, read, pin, cold["cold_netlist_sha256"], clear_sites, sum(groups["clock_and_reset"].values())
        )
    return result


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pad_archive", type=Path)
    parser.add_argument("--narrow-host-run", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.pad_archive, args.narrow_host_run), indent=2, sort_keys=True))
