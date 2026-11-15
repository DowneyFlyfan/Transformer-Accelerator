"""Verify constraints and library views for the prepared Innovus placement."""

import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import re

from audit_tri_oracle_placed_fanout import GIB, memory, sha
from verify_tri_oracle_joined_placed_constraints import parse_sdc


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_chip_command_layer_parallel_chip"
SEED = ROOT / "records/tri_oracle_bounded_decoder_probability_buffer_seed.json"
BASE_PLACEMENT = ROOT / "records/tri_oracle_bounded_decoder_reset_native_placement.json"
TARGETS = ROOT / "records/paper_result_targets.json"
CONTROL = ROOT / "records/tri_oracle_bounded_seed_native_timing_preflight.json"
VIEWS = {"setup_slow": "slow", "setup_typ": "typ", "hold_fast": "fast"}
LIBRARY_SUFFIX = {"slow": "ssg0p9v125c", "typ": "tt1v25c", "fast": "ffg1p05vm40c"}
MMMC_FILE = r"\$\{::IMEX::libVar\}/mmmc/([^\s\]{}]+)"


def read(path):
    return json.loads(path.read_text())


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical_sdc(file):
    text = file.read_text()
    text = re.sub(r"-name\s+core(?=\s)", "-name core_clock", text)
    return parse_sdc(re.sub(r"\[get_clocks\s+\{?core\}?\]", "[get_clocks {core_clock}]", text))


def view_inputs(file, database=None):
    text = re.sub(r"\\\r?\n", " ", file.read_text())
    commands = [" ".join(line.split()) for line in text.splitlines()]
    def command(prefix):
        matches = [line for line in commands if line.startswith(prefix)]
        require(len(matches) == 1, f"{file}: expected one {prefix}")
        return matches[0]

    require(command("set ::IMEX::libVar ") == "set ::IMEX::libVar ${::IMEX::dataVar}/libs",
            f"{file}: unexpected timing library root")
    parent = command("set ::IMEX::dataVar ").removeprefix("set ::IMEX::dataVar ").strip("{}")
    library_root = (database if database else Path(parent)) / "libs/mmmc"
    libraries, extraction = {}, {}
    for view, label in VIEWS.items():
        require(command(f"create_analysis_view -name {view} ") ==
                f"create_analysis_view -name {view} -constraint_mode functional -delay_corner dc_{label}",
                f"{view}: wrong timing corner")
        require(command(f"create_delay_corner -name dc_{label} ") ==
                f"create_delay_corner -name dc_{label} -timing_condition {{tc_{label}}} -rc_corner rc_{label}",
                f"{view}: resistance and capacitance corner miswired")
        require(command(f"create_timing_condition -name tc_{label} ") ==
                f"create_timing_condition -name tc_{label} -library_sets [list ls_{label}]",
                f"{view}: wrong library set")
        names = re.findall(MMMC_FILE, command(f"create_library_set -name ls_{label} "))
        require(len(names) == len(set(names)) == 7 and all(name.endswith(LIBRARY_SUFFIX[label] + ".lib")
                                                          for name in names), f"{view}: wrong library inventory")
        libraries[view] = [library_root / name for name in names]
        (kit,) = re.findall(MMMC_FILE, command(f"create_rc_corner -name rc_{label} "))
        require(kit.startswith(f"rc_{label}/"), f"{view}: wrong extraction technology")
        extraction[view] = library_root / kit
    require(command("set_analysis_view ") == "set_analysis_view -setup [list setup_slow setup_typ] -hold [list hold_fast]",
            "Unexpected active analysis views")
    constraints = command("create_constraint_mode -name functional ")
    managed = re.fullmatch(r"create_constraint_mode -name functional -sdc_files \[list \{([^}]+)\}\]", constraints)
    if managed:
        sdc = Path(managed[1])
    else:
        (name,) = re.findall(MMMC_FILE, constraints)
        sdc = library_root / name
    return libraries, extraction, sdc


def verify(candidate):
    require(__debug__ and Path("/.dockerenv").is_file(), "Use the Cadence container with assertions enabled")
    prepared = read(SEED)
    native_seed_path = candidate / "native_seed_verified.json"
    require(sha(native_seed_path) == prepared["evidence_sha256"][str(native_seed_path.relative_to(ROOT))],
            "Buffered placement seed receipt changed")
    native_seed = read(native_seed_path)
    plan = candidate / "plan.tcl"
    require(sha(plan) == native_seed["evidence_sha256"][str(plan.relative_to(ROOT))], "Buffered import plan changed")
    (view_path,) = re.findall(r" views \{([^}]+)\}", plan.read_text())
    config = Path(view_path)
    control = read(CONTROL)
    (target_name,) = (name for name in control["evidence_sha256"] if name.endswith("/native_timing_target_preflight.json"))
    previous_timing = ROOT / target_name
    require(sha(previous_timing) == control["evidence_sha256"][target_name], "Earlier timing preflight changed")
    require(sha(config) == read(previous_timing)["evidence_sha256"][str(config.relative_to(ROOT))],
            "The imported timing views differ from the preflight input")

    base = candidate.parent / "native_reset_eco_relinked_native"
    predecessor = base / "native_receipt.json"
    earlier = read(BASE_PLACEMENT)
    require(sha(predecessor) == earlier["evidence_sha256"][str(predecessor.relative_to(ROOT))],
            "Native predecessor receipt changed")
    previous = read(predecessor)
    require(previous["exported_cold_netlist_sha256"] == prepared["source_cold_netlist_sha256"],
            "Native predecessor and buffered netlist differ")
    database = base / "import/placed.db"
    actual_config = database / "viewDefinition.tcl"
    files, kits, constraints = view_inputs(config)
    actual_files, actual_kits, actual_sdc = view_inputs(actual_config, database)
    require(canonical_sdc(constraints) == canonical_sdc(actual_sdc), "Native constraint mode differs from import")

    parsed = canonical_sdc(constraints)
    core_clock = parsed[0]["create_clock"]
    require(parsed[0]["current_design"] == TOP and
            core_clock == ("clk", Decimal("1.72414"), (Decimal(0), Decimal("0.86207"))),
            "Unexpected chip clock or period")
    external = Counter(command for command, _, _ in parsed[1])
    require(sum(external.values()) == 31772, "Unexpected external delay and load inventory")
    source_paths = [SEED, native_seed_path, plan, BASE_PLACEMENT, predecessor, config, actual_config,
                    CONTROL, previous_timing, constraints, actual_sdc, TARGETS, Path(__file__).resolve()]
    results = {}
    for view in VIEWS:
        sdc = base / "cold" / f"{view}.sdc"
        require(sha(sdc) == previous["evidence_sha256"][str(sdc.relative_to(ROOT))], f"{view}: changed cold constraints")
        require(canonical_sdc(sdc) == parsed, f"{view}: cold constraint mismatch")
        for lhs, rhs in zip(files[view], actual_files[view], strict=True):
            require(lhs.name == rhs.name and sha(lhs) == sha(rhs), f"{view}: changed library {lhs.name}")
        require(sha(kits[view]) == sha(actual_kits[view]), f"{view}: changed extraction technology")
        source_paths.extend([sdc, *actual_files[view], actual_kits[view]])
        standard, = (path for path in actual_files[view] if path.name.startswith("tcbn28"))
        with standard.open() as stream:
            header = stream.read(32768)
        (voltage,) = re.findall(r"nom_voltage\s*:\s*([\d.]+)\s*;", header)
        results[view] = dict(libraries=len(files[view]), nominal_supply_volts=float(voltage),
                             extraction_model=actual_kits[view].name, external_constraints=sum(external.values()))
    budget = read(TARGETS)
    capacity = int(Path("/sys/fs/cgroup/memory.max").read_text())
    host_capacity = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                         if line.startswith("MemTotal:"))
    available, used_anonymous = memory()
    required = control["reference_policy_container_headroom_bytes"]
    return dict(
        state="buffered_seed_three_corner_timing_inputs_verified",
        buffered_netlist_sha256=prepared["buffered_netlist_sha256"],
        clock_period_ns=float(core_clock[1]),
        views=results,
        process=budget["local_qualification"]["process"],
        reference_peak_supply_volts=budget["peak"]["supply_volts"],
        reference_energy_supply_volts=budget["energy_point"]["supply_volts"],
        host_total_gib=round(host_capacity/GIB, 3), host_available_gib=round(available/GIB, 3),
        container_limit_gib=round(capacity/GIB, 3),
        container_approximate_anonymous_headroom_gib=round((capacity-used_anonymous)/GIB, 3),
        full_diagnostic_reference_headroom_gib=round(required/GIB, 3),
        native_buffered_timing_measured=False,
        evidence_sha256={str(path.relative_to(ROOT)): sha(path) for path in dict.fromkeys(source_paths)},
        scope="Verified the buffered placement import configuration against the native predecessor. "
              "Clock frequency, extracted timing, and energy are separate measurements.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    print(json.dumps(verify(parser.parse_args().candidate.resolve()), indent=2, sort_keys=True))
