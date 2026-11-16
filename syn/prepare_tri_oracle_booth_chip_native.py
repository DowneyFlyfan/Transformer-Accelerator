"""Prepare the verified Booth placement for the existing native import flow."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import re

from prepare_tri_oracle_booth_chip_terminals import read_ports
from verify_tri_oracle_booth_chip_link import TOP, WORK
from verify_tri_oracle_gated_compute_array import ROOT, digest, read

TERMINALS = Path("records/tri_oracle_booth_chip_terminals.json")
STRUCTURE = Path("records/tri_oracle_linked_booth_chip.json")
GEOMETRY = Path("records/tri_oracle_booth_chip_geometry.json")
RELOAD = Path("records/tri_oracle_repacked_whole_chip_cold_reload.json")
IMPORT = Path("syn/tri_oracle_import_exact_seed.tcl")
PLACEMENT = Path("syn/tri_oracle_require_clean_placement.tcl")
TX = Path("records/tri_oracle_credited_request_link.json")
RX = Path("records/tri_oracle_gated_receive_storage.json")
NATIVE = WORK / "native_reload"

PORT_END = re.compile(r" \[get_ports (?:\{([^{}]+)\}|(\w+))\]\s*$")
COMMANDS = (
    "set_load ",
    "set_input_delay ",
    "set_output_delay ",
    "set_input_transition ",
)


def expanded(ports):
    return {
        bit: direction
        for name, (direction, width) in ports.items()
        for bit in ([name] if width is None else (f"{name}[{i}]" for i in range(width)))
    }


def port_constraints(path):
    by_port = defaultdict(list)
    for line in path.read_text().splitlines():
        if line.startswith(COMMANDS):
            match = PORT_END.search(line)
            assert match, line
            by_port[match[1] or match[2]].append(line[: match.start()])
    return by_port


def constraints(ports, incoming, outgoing):
    clocks = (
        "create_clock -name core_clock -period 1.72414 -waveform {0.0 0.86207} [get_ports clk]",
        "create_generated_clock -name pad_sample_clock -edges {2 3 4} -source [get_ports clk] [get_ports memory_tx_clock]",
    )
    rx_names = {
        "memory_mem_rsp_data": "pad_data",
        "memory_mem_rsp_metadata": "pad_metadata",
        "memory_mem_rsp_credit": "pad_credit",
        "memory_mem_rsp_protocol_error": "protocol_error",
    }
    tx_names = {
        "memory_tx_clock": "pad_clock",
        "memory_tx_data": "pad_data",
        "memory_tx_valid": "pad_valid",
        "memory_tx_credit": "pad_credit",
    }
    rendered = [
        f"current_design {TOP}",
        "set_units -time 1ns -capacitance 1pf",
        *clocks,
        "set_false_path -from [get_ports rst_n]",
        "set_clock_gating_check -setup 0.0",
        "set_clock_uncertainty 0.05 [get_clocks core_clock]",
        "set_clock_uncertainty 0.05 [get_clocks pad_sample_clock]",
    ]
    coverage = Counter()
    for bit, direction in expanded(ports).items():
        if bit in {"clk", "rst_n"}:
            continue
        name, bracket, number = bit.partition("[")
        tail = bracket + number
        if name in rx_names:
            commands = incoming[rx_names[name] + tail]
            if direction == "INPUT":
                edges = [cmd for cmd in commands if cmd.startswith("set_input_delay ")]
                assert (
                    len(edges) == 2 and sum("-clock_fall" in cmd for cmd in edges) == 1
                )
            coverage["receive_ports"] += 1
        elif name in tx_names:
            commands = outgoing[tx_names[name] + tail]
            coverage["transmit_ports"] += 1
        else:
            assert name.startswith(("host_rx_", "host_tx_")), name
            if direction == "INPUT":
                commands = [
                    "set_input_transition 0.05",
                    "set_input_delay -clock [get_clocks core_clock] 0.2",
                ]
            else:
                commands = [
                    "set_load -pin_load 0.005",
                    "set_output_delay -clock [get_clocks core_clock] 0.2",
                ]
            coverage["host_ports"] += 1
        delay = "set_input_delay " if direction == "INPUT" else "set_output_delay "
        assert commands and (
            bit == "memory_tx_clock" or any(cmd.startswith(delay) for cmd in commands)
        ), bit
        rendered.extend(f"{cmd} [get_ports {{{bit}}}]" for cmd in commands)
    return "\n".join(rendered) + "\n", coverage


def prepare():
    evidence = {}

    def pin(path, receipt=None):
        checksum = digest(path)
        if receipt is not None:
            assert checksum == receipt["evidence_sha256"][str(path)], path
        evidence[str(path)] = checksum
        return path

    geometry, structure, terminals, predecessor = (
        read(pin(path)) for path in (GEOMETRY, STRUCTURE, TERMINALS, RELOAD)
    )
    linked = pin(WORK / "linked.v", structure)
    seed = pin(WORK / "placement_with_terminal_seed.def", terminals)
    assert structure["boundary_signal_pins"] == terminals["signal_terminals"] == 484
    ports = read_ports(linked)
    assert len(expanded(ports)) == 484
    templates = {}
    for receipt in (RX, TX):
        proof = read(pin(receipt))
        (path,) = (
            Path(key)
            for key in proof["evidence_sha256"]
            if key.endswith("/constraints.sdc")
            and ("gated_receive_storage/" in key or "credit_request_link/" in key)
        )
        templates[receipt] = port_constraints(pin(path, proof))
    rendered, coverage = constraints(ports, templates[RX], templates[TX])
    assert coverage == {"receive_ports": 459, "transmit_ports": 11, "host_ports": 12}

    (view,) = (
        Path(key)
        for key in predecessor["evidence_sha256"]
        if key.endswith("/viewDefinition.tcl")
    )
    template = pin(view, predecessor).read_text()
    bindings_path = view.parents[2] / "verified_bindings.json"
    bindings = read(pin(bindings_path, predecessor))
    libs = view.parent / "libs"
    (technology,) = (libs / "lef").glob("*.tlef")
    lef = [technology, *sorted((libs / "lef").glob("*.lef"))]
    assert len(lef) == 8
    for file in lef:
        pin(file, bindings if str(file) in bindings["evidence_sha256"] else None)
    library_refs = re.findall(r"\$\{::IMEX::libVar\}/(mmmc/[^\s\\\]]+)", template)
    sdc = "mmmc/setup_typ.sdc"
    assert len(library_refs) == len(set(library_refs)) == 25 and sdc in library_refs
    for name in library_refs:
        if name != sdc:
            file = libs / name
            pin(file, bindings if str(file) in bindings["evidence_sha256"] else None)

    NATIVE.mkdir(exist_ok=True)
    constraints_path = NATIVE / "boundary.sdc"
    constraints_path.write_text(rendered)
    views = NATIVE / "views.tcl"
    old_base = "set ::IMEX::dataVar [file dirname [file normalize [info script]]]"
    assert (
        template.count(old_base) == 1
        and template.count("${::IMEX::libVar}/" + sdc) == 1
    )
    views.write_text(
        template.replace(
            old_base, "set ::IMEX::dataVar {%s}" % view.parent.resolve()
        ).replace("${::IMEX::libVar}/" + sdc, "{%s}" % constraints_path.resolve())
    )

    plan = NATIVE / "plan.tcl"
    settings = {
        "top": TOP,
        "views": views.resolve(),
        "netlist": linked.resolve(),
        "seed": seed.resolve(),
        "database": (NATIVE / "import/placed.db").resolve(),
        "placement_checker": pin(PLACEMENT).resolve(),
        "memories": geometry["fixed_memories_verified"],
        "ports": terminals["signal_terminals"],
        "blockages": geometry["reservation_rectangles_verified"],
        "components": structure["reachable_leaves_including_memories"],
    }
    assert (
        sum(geometry[k] for k in ("standard_cells_verified", "fixed_memories_verified"))
        == settings["components"]
    )
    prefix = "return [dict create " + " ".join(
        f"{key} {{{value}}}" for key, value in settings.items()
    )
    plan.write_text(
        prefix
        + " abstracts [list "
        + " ".join("{%s}" % path.absolute() for path in lef)
        + "]]\n"
    )
    for path in (
        IMPORT,
        constraints_path,
        views,
        plan,
        Path(__file__).resolve().relative_to(ROOT),
    ):
        pin(path)
    return {
        "state": "linked_booth_chip_native_placement_inputs_prepared",
        "physical_components": settings["components"],
        "ports": settings["ports"],
        "placement_blockages": settings["blockages"],
        "port_timing_coverage": dict(coverage),
        "clock_period_ns": 1.72414,
        "analysis_views": ["setup_slow", "setup_typ", "hold_fast"],
        "scope": "Placement reload input. The receive and transmit timing constraints are transferred from earlier tested link wrappers. Host ports use the previous 0.2 ns boundary allowance. The abstractions exclude bond pad, board, and power-delivery effects.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(prepare(), indent=2, sort_keys=True))
