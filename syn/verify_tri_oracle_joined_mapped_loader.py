"""Replay the joined decoder with its exact mapped weight loader in Xcelium."""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from prepare_tri_oracle_joined_decoder_candidate import INCLUDE, ROOT, WIDE, read
from prepare_tri_oracle_packed_sign_predictor import rewrite
from prepare_tri_oracle_parallel_chip_synthesis import LOADER, LOADER_CUT, declarations, pin, verify
from replay_tri_oracle_parallel_chip import XRUN
from run_tri_oracle_parallel_chip_synthesis import GIB, memory
from tri_oracle_process_guard import terminate_process_group


JOINED = WIDE / "dual_lane_joined_chip"
MAPPING = WIDE / "burst_handoff/matched_block_mapping"
ADAPTER = WIDE / "parallel_loader/mapped_adapter"
MASTER = LOADER + "_mapped"
TOP = "tri_oracle_batched406_learned_tb"
CELLS = ROOT / ".cache/physical/library/tcbn28hpcplusbwp12t40p140.v"
MARKERS = {"outputs": "BATCH408_PASS", "signs": "DUAL_LANE_PACKED_SIGN_PASS", "transport": "PACKED_DECODER_PASS"}
CASES = {"positive": (0, 0), "sign_fault": (4, 0), "weight_fault_lane0": (2, 0), "weight_fault_lane1": (2, 1)}


def recorded(pins, evidence, path):
    pin(pins, path, evidence[str(path.relative_to(ROOT))])


def prepare(output, pins, baseline):
    source = JOINED / "prepared.json"
    recorded(pins, baseline["evidence_sha256"], source)
    setup = read(source)
    assert setup["state"] == "prefetched_packed_sign_and_weight_handoff_decoder_prepared"
    for name, digest in setup["input_sha256"].items():
        pin(pins, ROOT / name, digest)

    mapped_record = ROOT / "records/wac_weight_handoff_mapped_result.json"
    pin(pins, mapped_record)
    mapped = read(mapped_record)
    assert mapped["state"] == "mapped_dual_lane_weight_handoff_verified"
    receipt, independent = MAPPING / "receipt.json", MAPPING / "independent_verification.json"
    netlist = MAPPING / "candidate/netlist.v"
    for path in (receipt, independent, netlist):
        recorded(pins, mapped["evidence_sha256"], path)
    mapping = read(receipt)["evidence_sha256"]
    adapter = ADAPTER / "adapter.sv"
    for path in (adapter, CELLS):
        recorded(pins, read(independent)["evidence_sha256"], path)
    native = MAPPING / "candidate/native_receipt.json"
    recorded(pins, mapping, native)
    assert read(native)["native_exit_status"] == 0

    bundle = (JOINED / "bundle.sv").read_text()
    includes = [Path(path) for path in INCLUDE.findall(bundle)]
    sources = {}
    for stem in (LOADER, "tri_oracle_paired_weight_schedule", "tri_oracle_packed_weight_schedule",
                 "tri_oracle_wide_weight_loader"):
        name = stem + ".sv"
        path, = (item for item in includes if item.name == name)
        compiled = MAPPING / "rtl" / name
        recorded(pins, mapping, compiled)
        assert pins[str(path.relative_to(ROOT))] == pins[str(compiled.relative_to(ROOT))], name
        sources[stem] = path

    text = netlist.read_text()
    ports, _ = declarations(text)
    previous_ports, _ = declarations((ADAPTER / "mapped.v").read_text())
    assert ports == previous_ports
    pin(pins, ADAPTER / "mapped.v")
    mapped_hdl = output / "mapped.v"
    mapped_hdl.write_text(rewrite(text, ((f"module {LOADER}(", f"module {MASTER}("),)))
    witness = output / "witness.sv"
    witness.write_text('module tri_oracle_mapped_loader_witness;\n'
                       '  initial $display("JOINED_MAPPED_LOADER %m");\nendmodule\n'
                       f'bind {MASTER} tri_oracle_mapped_loader_witness binding_witness ();\n')
    patched = output / "bundle.sv"
    patched.write_text(rewrite(bundle, ((f'`include "{sources[LOADER]}"',
                                        '\n'.join(f'`include "{path}"' for path in (adapter, mapped_hdl, witness))),)))
    for path in (mapped_hdl, witness, patched):
        pin(pins, path)
    return patched, len(ports)


def replay(output, bundle, name, fault, lane, pins, baseline):
    old_progress = JOINED / name / "progress.log"
    recorded(pins, baseline["evidence_sha256"], old_progress)
    folder = output / name
    folder.mkdir()
    log, progress = folder / "xrun.log", folder / "progress.log"
    command = ["/usr/bin/prlimit", f"--as={5 * GIB}", "--", *XRUN, "-top", TOP, "-log", str(log)]
    for parameter, value in (("INTERMEDIATE", 256), ("FAULT", fault), ("FAULT_LANE", lane)):
        command.extend(("-defparam", f"{TOP}.{parameter}={value}"))
    command.extend((str(bundle), str(JOINED / "trained_tb.sv"), f"+PROGRESS={progress}"))
    invocation = folder / "invocation.json"
    invocation.write_text(json.dumps(command, indent=2) + "\n")
    deadline = time.monotonic() + 1800
    while True:
        available, anonymous = memory()
        if available >= 14.5 * GIB and anonymous <= 6 * GIB:
            break
        assert time.monotonic() < deadline, (name, available, anonymous)
        time.sleep(3)
    assert shutil.disk_usage(output).free >= 12 * GIB
    console = folder / "console.log"
    started = time.monotonic()
    try:
        with console.open("x") as stream:
            process = subprocess.Popen(command, cwd=folder, stdout=stream, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, start_new_session=True)
            try:
                while process.poll() is None:
                    available, anonymous = memory()
                    assert available >= 13.5 * GIB and anonymous <= 7 * GIB, (name, available, anonymous)
                    assert time.monotonic() - started < 180, name
                    time.sleep(0.3)
            finally:
                if process.poll() is None:
                    terminate_process_group(process, log_argument=str(log))
    finally:
        snapshot = folder / "xcelium.d"
        if snapshot.is_dir():
            shutil.rmtree(snapshot)
    assert process.returncode == 0, (name, process.returncode, console.read_text()[-2000:])
    content = log.read_text()
    assert not re.search(r"\*[EF],", content) and content.count("Simulation complete via $finish(1)") == 1
    instance, = re.findall(r"(?m)^JOINED_MAPPED_LOADER (.+)$", content)
    assert re.sub(r"[\\\s]", "", instance) == f"{TOP}.dut.{LOADER_CUT}.binding_witness", instance
    counters = {}
    for key, marker in MARKERS.items():
        fields, = re.findall(rf"(?m)^{marker} (.+)$", content)
        counters[key] = {name: int(value) for name, value in (field.split("=") for field in fields.split())}
    assert counters == baseline["cases"][name], (name, counters)
    assert progress.read_bytes() == old_progress.read_bytes(), name
    if fault:
        assert content.splitlines().count(f"BATCH408_FAULT_DRAINED fault={fault} output_prefix_packets=0") == 1
    for path in (invocation, console, log, progress):
        pin(pins, path)
    print("JOINED_MAPPED_LOADER_PASS", name, counters["outputs"]["exact_outputs"],
          counters["transport"]["cycles"], flush=True)
    return {**counters, "native_exit_status": process.returncode,
            "native_elapsed_seconds": round(time.monotonic() - started, 3)}


def run(output):
    assert Path("/opt/cadence/bin/xrun").is_file() and Path("/.dockerenv").is_file()
    output.mkdir()
    baseline_path = ROOT / "records/wac_joined_packed_sign_decoder_directed_result.json"
    baseline = read(baseline_path)
    assert baseline["state"] == "prefetched_packed_sign_and_weight_handoff_decoder_directed_verified"
    pins = {}
    for path in (baseline_path, Path(__file__).resolve()):
        pin(pins, path)
    bundle, ports = prepare(output, pins, baseline)
    cases = {name: replay(output, bundle, name, *config, pins, baseline) for name, config in CASES.items()}
    verify(pins)
    result = {"state": "joined_decoder_mapped_weight_loader_directed_verified", "cases": cases,
              "mapped_cut": LOADER_CUT, "mapped_ports": ports, "evidence_sha256": pins,
              "scope": "Mapped weight loader in the joined decoder with the source predictor."}
    (output / "receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
