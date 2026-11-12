"""Prepare source-level timing constraints for the second packed-weight lane."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from audit_tri_oracle_wac_parent_hdl_export import declarations
from prepare_physical_inputs import IO, IO_COMMANDS, PROTECT, port_bits
from prepare_tri_oracle_parallel_chip_synthesis import AUX_PORTS, BASE, TOP, pin, read, verify
from verify_tri_oracle_packed_down_weights import ROOT


REFERENCE = ROOT / ".cache/physical/context_external/shared_decoder"
PORT = re.compile(r"(input|output) logic (?:\[(\d+):0\] )?(\w+)")
WIDE_PRIMARY = {"req_length": ("output", (5, 0)), "rsp_data": ("input", (511, 0)),
                "req_wide": ("output", None)}


def source_ports(text):
    header, = re.findall(rf"(?s)\bmodule {TOP}\s*#\s*\([^)]*\)\s*\((.*?)\);", text)
    ports = {}
    for raw in header.split(","):
        direction, msb, name = PORT.fullmatch(raw.strip()).groups()
        assert name not in ports, name
        ports[name] = direction, (int(msb), 0) if msb else None
    return ports


def pin_constraints(source, ports):
    commands = {name: {} for name in IO_COMMANDS}
    for line in source.splitlines():
        match = IO.fullmatch(line)
        if match:
            name, _, expression = match.groups()
            bit = expression.strip("{}")
            assert bit not in commands[name], (name, bit)
            commands[name][bit] = line, expression
        else:
            assert not line.startswith(tuple(commands)), line
    for name, direction in IO_COMMANDS.items():
        assert commands[name].keys() == port_bits(ports, direction), name
    return commands


def extend_constraints(source, previous_ports, candidate_ports):
    auxiliary = {name: (direction, (width - 1, 0) if width > 1 else None)
                 for name, (direction, width) in AUX_PORTS.items()}
    assert not auxiliary.keys() & previous_ports.keys()
    assert previous_ports["req_length"] == ("output", (4, 0))
    assert previous_ports["rsp_data"] == ("input", (63, 0)) and "req_wide" not in previous_ports
    primary = previous_ports | WIDE_PRIMARY
    assert candidate_ports == primary | auxiliary
    assert all(primary[name.removeprefix("aux_")] == shape for name, shape in auxiliary.items())
    assert source.splitlines().count(f"current_design {TOP}") == 1
    assert source.count('create_clock -name "core_clock" -period 1.72414 ') == 1
    assert source.count("set_false_path -from [get_ports rst_n]") == 1
    baseline = pin_constraints(source, previous_ports)
    additions = []
    for name, direction in IO_COMMANDS.items():
        reference = {bit: line.removesuffix(f"[get_ports {expression}]")
                     for bit, (line, expression) in baseline[name].items()}
        for bit in sorted(port_bits(primary, direction) - reference.keys()):
            example = "req_valid" if bit == "req_wide" else bit.split("[", 1)[0] + "[0]"
            reference[bit] = reference[example]
            additions.append(reference[bit] + f"[get_ports {{{bit}}}]")
        for bit in sorted(port_bits(auxiliary, direction)):
            additions.append(reference[bit.removeprefix("aux_")] + f"[get_ports {{{bit}}}]")
    result = source.rstrip("\n") + "\n\n" + "\n".join(additions) + "\n"
    counts = {name: len(bits) for name, bits in pin_constraints(result, candidate_ports).items()}
    assert len(additions) == sum(counts[name] - len(bits) for name, bits in baseline.items())
    return result, counts


def protection_counts(source, cuts):
    total = Counter()
    by_cut = Counter()
    targets = set()
    for line in source.splitlines():
        match = PROTECT.fullmatch(line)
        if match is None:
            assert not line.startswith("set_dont_touch"), line
            continue
        command, expression = match.groups()
        path = expression.strip("{}")
        assert (command, path) not in targets, (command, path)
        targets.add((command, path))
        scope = path if command == "get_cells" else path.rpartition("/")[0]
        scope = scope.replace("/", ".")
        covering = [cut for cut in cuts if scope == cut or scope.startswith(cut + ".")]
        assert len(covering) <= 1, (scope, covering)
        total[command] += 1
        if covering:
            by_cut[command] += 1
    return total, by_cut, total - by_cut


def run(synthesis, output):
    baseline = ROOT / "records/wac_chip_top_physical_preflight_result.json"
    known = read(baseline)
    pins = {}
    pin(pins, baseline)
    source = REFERENCE / "chip_physical_input_preflight/candidate.sdc"
    wrapper = REFERENCE / "chip_structural_interface_preflight/chip_wrapper.v"
    for file in (source, wrapper):
        pin(pins, file, known["evidence_sha256"][str(file.relative_to(ROOT))])
    prepared = synthesis / "prepared.json"
    preflight = ROOT / "records/wac_parallel_chip_synthesis_preflight_result.json"
    pin(pins, preflight)
    pin(pins, prepared, read(preflight)["evidence_sha256"][str(prepared.relative_to(ROOT))])
    setup = read(prepared)
    assert setup["state"] == "parallel_chip_synthesis_partition_prepared" and setup["top"] == TOP
    candidate = synthesis / f"{TOP}.sv"
    pin(pins, candidate, setup["input_sha256"][str(candidate.relative_to(ROOT))])
    for file in (Path(__file__).resolve(), Path(port_bits.__code__.co_filename).resolve(),
                 Path(declarations.__code__.co_filename).resolve()):
        pin(pins, file)

    old_ports, _ = declarations(wrapper.read_text())
    new_ports = source_ports(candidate.read_text())
    text = source.read_text()
    constraints, counts = extend_constraints(text, old_ports, new_ports)
    total, preserved, outside = protection_counts(text, setup["preserved"])
    assert dict(total) == known["protected_targets"]
    assert sum(known["external_constraint_counts"].values()) // 2 + 2 == known["external_port_bits_including_clock_and_reset"]
    assert new_ports["clk"] == new_ports["rst_n"] == ("input", None)
    verify(pins)

    output.mkdir()
    sdc = output / "candidate.sdc"
    sdc.write_text(constraints)
    result = {
        "state": "parallel_chip_source_pin_constraints_preflight",
        "clock_period_ns": 1.72414,
        "external_port_bits_including_clock_and_reset": sum(counts.values()) // 2 + 2,
        "external_constraint_counts": counts,
        "auxiliary_port_bits": {direction: sum(width for mode, width in AUX_PORTS.values() if mode == direction)
                                for direction in ("input", "output")},
        "primary_port_bits_added": {direction: len(port_bits(old_ports | WIDE_PRIMARY, direction) -
                                                  port_bits(old_ports, direction))
                                    for direction in ("input", "output")},
        "inherited_protections_under_preserved_cuts": dict(preserved),
        "inherited_protections_outside_preserved_cuts": dict(outside),
        "scope": "Source port and constraint coverage. The linked netlist still needs exact port and protection-target checks.",
        "input_sha256": pins,
    }
    output_pins = {}
    pin(output_pins, sdc)
    result["output_sha256"] = output_pins
    (output / "receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], result["external_port_bits_including_clock_and_reset"], counts,
          "protections outside preserved cuts:", dict(outside), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    parser.add_argument("--synthesis", type=lambda value: Path(value).resolve(), default=BASE / "parallel_synthesis")
    args = parser.parse_args()
    run(args.synthesis, args.output)
