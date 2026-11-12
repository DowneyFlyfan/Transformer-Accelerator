"""Prepare and check the preserved cuts of the joined Tri-Oracle decoder."""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from prepare_tri_oracle_joined_decoder_candidate import ROOT, WIDE, read
from prepare_tri_oracle_packed_sign_predictor import rewrite
from prepare_tri_oracle_parallel_chip_synthesis import LOADER_CUT, TOP, includes, pin, verify
from prepare_tri_oracle_unified_chip_synthesis import PROBE_TOP, stub_from_source
from replay_tri_oracle_parallel_chip import XRUN
from run_tri_oracle_parallel_chip_synthesis import GIB, memory
from tri_oracle_process_guard import terminate_process_group
from verify_tri_oracle_joined_mapped_loader import JOINED


BASELINE = WIDE / "parallel_synthesis"
PREDICTOR = "tri_oracle_packed_outlier_replay"
PREDICTOR_CUT = "layer.layer.feedforward.packed_signs.predictor.replay_table"


def predictor_ports(stub):
    header = stub.partition(") (")[2].partition("\n);")[0].strip()
    ports = {}
    for line in header.splitlines():
        match = re.fullmatch(r"\s*(input|output) logic\s+((?:\[\d+:0\]\s*)*)([\w ,]+)", line)
        assert match, line
        direction, bounds, names = match.groups()
        shape = [int(msb) + 1 for msb in re.findall(r"\[(\d+):0\]", bounds)]
        for name in names.rstrip(",").split(","):
            name = name.strip()
            assert name and name not in ports, name
            ports[name] = {"direction": direction, "packed_widths": shape}
    assert ports["rsp_data"] == {"direction": "input", "packed_widths": [2, 512]}
    return ports


def prepare(output):
    prior = ROOT / "records/wac_parallel_chip_synthesis_preflight_result.json"
    loader = ROOT / "records/wac_joined_mapped_loader_directed_result.json"
    pins = {}
    for path in (prior, loader, Path(__file__).resolve()):
        pin(pins, path)
    old, tested = read(prior), read(loader)
    assert old["state"] == "parallel_chip_preserved_synthesis_interfaces_verified"
    assert tested["state"] == "joined_decoder_mapped_weight_loader_directed_verified"
    assert tested["mapped_cut"] == LOADER_CUT and tested["mapped_ports"] == 34
    assert len(tested["cases"]) == 4 and all(case["native_exit_status"] == 0 for case in tested["cases"].values())

    old_prepared = BASELINE / "prepared.json"
    pin(pins, old_prepared, old["evidence_sha256"][str(old_prepared.relative_to(ROOT))])
    setup = read(old_prepared)
    assert setup["top"] == TOP and len(setup["preserved"]) == 11
    prior_bundle, prior_stubs, prior_probe, prior_recipe = (
        BASELINE / name for name in ("synthesis.sv", "preserved.sv", "cut_probe.sv", "map.tcl"))
    for path in (prior_bundle, prior_stubs, prior_probe, prior_recipe, *includes(prior_bundle)):
        pin(pins, path, setup["input_sha256"][str(path.relative_to(ROOT))])

    source_bundle = JOINED / "bundle.sv"
    joined = includes(source_bundle)
    for path in (source_bundle, *joined):
        pin(pins, path, tested["evidence_sha256"][str(path.relative_to(ROOT))])
    old_includes = includes(prior_bundle)
    replacements = {}
    for stem in ("tri_oracle_batched_learned406", "tri_oracle_batched_tensor390", "tri_oracle_shared_layer437"):
        name = stem + ".sv"
        before, = (path for path in old_includes if path.name == name)
        after, = (path for path in joined if path.name == name)
        assert before != after
        replacements[before] = after
    source_top, = (path for path in joined if path.name == TOP + ".sv")
    old_top, = (path for path in old_includes if path.name == source_top.name)
    assert old_top.read_text() == rewrite(source_top.read_text(), (
        ("  input logic aux_rsp_last,aux_rsp_error,\n", "  input logic aux_rsp_last,\n  input logic aux_rsp_error,\n"),))
    additional = tuple(next(path for path in joined if path.name == name + ".sv") for name in
                       ("tri_oracle_packed_normalize405", "tri_oracle_wide_read_arbiter"))
    source, = (path for path in joined if path.name == PREDICTOR + ".sv")
    predictor = stub_from_source(source.read_text(), PREDICTOR)
    ports = predictor_ports(predictor)

    output.mkdir()
    stubs, synthesis, monitor, recipe = (output / name for name in
                                       ("preserved.sv", "synthesis.sv", "cut_probe.sv", "map.tcl"))
    stubs.write_text(prior_stubs.read_text() + "\n" + predictor)
    parent_sources = tuple(replacements.get(path, path) for path in old_includes if path != prior_stubs)
    assert set(parent_sources) - set(joined) == {old_top, WIDE / "parallel_loader/mapped_adapter/adapter.sv"}
    synthesis.write_text("".join(f'`include "{path}"\n' for path in (*parent_sources, *additional, stubs)))
    checks = ["CORE_STRIP_PREDICTOR === 1'b1"]
    for name, info in ports.items():
        shape = info["packed_widths"]
        if shape:
            checks.append(f"$dimensions({name})=={len(shape)}")
            checks.extend(f"$size({name},{index})=={size}" for index, size in enumerate(shape, 1))
        else:
            checks.append(f"$bits({name})==1")
    monitor.write_text(prior_probe.read_text() +
                       f'\nbind {PREDICTOR} tri_oracle_cut_shape_probe #(.MASTER("{PREDICTOR}"),\n'
                       f'  .WIDTHS_MATCH({" && ".join(checks)})) cut_probe ();\n')
    recipe.write_text(rewrite(prior_recipe.read_text(), (
        (str(prior_bundle), str(synthesis)), ("[llength $cuts] != 11", "[llength $cuts] != 12"),)))
    for path in (stubs, synthesis, monitor, recipe):
        pin(pins, path)
    mapped = WIDE / "dual_lane_joined_mapped_loader/mapped.v"
    pin(pins, mapped, tested["evidence_sha256"][str(mapped.relative_to(ROOT))])
    preserved = setup["preserved"]
    preserved[LOADER_CUT]["netlist_sha256"] = pins[str(mapped.relative_to(ROOT))]
    result = {"state": "joined_chip_synthesis_cuts_prepared", "preserved": preserved,
              "top": TOP, "auxiliary_ports": setup["auxiliary_ports"],
              "predictor": {"cut": PREDICTOR_CUT, "source_module": PREDICTOR, "ports": ports,
                            "core_strip_predictor": 1}, "input_sha256": pins}
    (output / "prepared.json").write_text(json.dumps(result, indent=2) + "\n")
    return joined, result


def xcelium(work, command):
    deadline = time.monotonic() + 4 * 3600
    print("JOINED_CHIP_CUT_PREFLIGHT_WAIT", work.name, flush=True)
    while True:
        available, anonymous = memory()
        if available >= 13.5 * GIB and anonymous <= 7 * GIB:
            break
        assert time.monotonic() < deadline, (available, anonymous)
        time.sleep(3)
    assert shutil.disk_usage(work).free >= 12 * GIB
    log = work / "xrun.log"
    console = work / "console.log"
    started = time.monotonic()
    try:
        with console.open("x") as stream:
            process = subprocess.Popen(["/usr/bin/prlimit", f"--as={3 * GIB}", "--", *command,
                                        "-log", str(log)], cwd=work, stdout=stream,
                                       stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
            print("JOINED_CHIP_CUT_PREFLIGHT_STARTED", work.name, process.pid, flush=True)
            try:
                while process.poll() is None:
                    available, anonymous = memory()
                    assert available >= 12.5 * GIB and anonymous <= 7.5 * GIB, (available, anonymous)
                    assert time.monotonic() - started < 60
                    time.sleep(0.2)
            finally:
                if process.poll() is None:
                    terminate_process_group(process, log_argument=str(log))
    finally:
        snapshot = work / "xcelium.d"
        if snapshot.is_dir():
            shutil.rmtree(snapshot)
    return process.returncode, log, console


def run(output):
    assert Path("/.dockerenv").is_file() and Path(XRUN[0]).is_file()
    joined, setup = prepare(output)
    models = tuple(path for path in joined if path.parent.name == "VERILOG")
    assert len(models) == 6
    pins = setup["input_sha256"]
    pin(pins, output / "prepared.json")
    includes_text = "".join(f'`include "{path}"\n' for path in
                            (*models, output / "synthesis.sv", output / "cut_probe.sv"))
    test = output / "elaborate.sv"
    test.write_text("`define UNIT_DELAY\n" + includes_text)
    bad_stubs, bad_synthesis, negative = (output / name for name in
                                        ("narrowed_predictor.sv", "narrowed_synthesis.sv", "narrowed_elaborate.sv"))
    bad_stubs.write_text(rewrite((output / "preserved.sv").read_text(), (
        ("[1:0][511:0] rsp_data", "[1:0][510:0] rsp_data"),)))
    bad_synthesis.write_text(rewrite((output / "synthesis.sv").read_text(), (
        (str(output / "preserved.sv"), str(bad_stubs)),)))
    negative.write_text(rewrite(test.read_text(), ((str(output / "synthesis.sv"), str(bad_synthesis)),)))

    positive, rejected = output / "positive", output / "negative"
    positive.mkdir()
    rejected.mkdir()
    status, log, console = xcelium(positive, [*XRUN, "-top", PROBE_TOP, str(test)])
    transcript = log.read_text()
    assert status == 0 and not re.search(r"\*[EF],", transcript), console
    assert transcript.splitlines().count("UNIFIED_CHIP_CUT_PREFLIGHT_PASS") == 1
    expected = {name: cut["source_module"] for name, cut in setup["preserved"].items()}
    expected[PREDICTOR_CUT] = PREDICTOR
    found = {}
    for module, raw in re.findall(r"(?m)^UNIFIED_CHIP_CUT (\S+) (.+)$", transcript):
        path = re.sub(r"[\\\s]", "", raw)
        assert path.startswith(f"{PROBE_TOP}.dut.") and path.endswith(".cut_probe")
        cut = path.removeprefix(f"{PROBE_TOP}.dut.").removesuffix(".cut_probe")
        assert cut not in found, cut
        found[cut] = module
    assert found == expected, found

    failed, bad_log, bad_console = xcelium(rejected, [*XRUN, "-top", PROBE_TOP, str(negative)])
    damaged = bad_log.read_text()
    assert failed != 0 and "UNIFIED_CHIP_CUT_PREFLIGHT_PASS" not in damaged
    assert f"UNIFIED_CHIP_CUT_PORT_WIDTH {PROBE_TOP}.dut.{PREDICTOR_CUT}.cut_probe" in damaged, bad_console
    for path in (test, bad_stubs, bad_synthesis, negative, log, console, bad_log, bad_console):
        pin(pins, path)
    verify(pins)
    proof = {"state": "joined_chip_synthesis_source_cuts_elaborated", "cuts": found,
             "checked_cut_ports": sum(len(cut["ports"]) for cut in setup["preserved"].values()) +
             len(setup["predictor"]["ports"]), "predictor": setup["predictor"],
             "narrowed_predictor_response_rejected": True, "input_sha256": pins,
             "scope": "Source hierarchy and preserved port shapes checked in Xcelium before Genus mapping."}
    (output / "preflight_receipt.json").write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
    print(proof["state"], len(found), proof["checked_cut_ports"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
