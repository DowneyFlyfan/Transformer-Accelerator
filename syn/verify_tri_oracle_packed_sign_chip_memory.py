"""Measure the packed predictor chip's compiled memory capacity in Xcelium."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess

from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256, sha
from verify_tri_oracle_shared_memory import CORNERS, ROOT, memory_shape, require


BENCH = "tri_oracle_batched406_learned_tb"
PREFIX = f"{BENCH}.dut."
PREDICTOR = "layer.layer.feedforward.packed_signs.predictor.replay_table."
INCLUDE = re.compile(r'(?m)^`include "([^"]+)"$')
MARKER = re.compile(r"TRI_ORACLE_SOURCE_SRAM (\w+) (\d+) (\d+) (.+)")


def census(lines, geometries):
    observed = {}
    for line in lines:
        if not line.startswith("TRI_ORACLE_SOURCE_SRAM "):
            continue
        match = MARKER.fullmatch(line)
        require(match is not None, f"Malformed memory census: {line}")
        master, depth, width, raw_path = match.groups()
        path = re.sub(r"[\\\s]", "", raw_path)
        require(path.startswith(PREFIX) and path.endswith(".source_sram_witness"), f"Unexpected SRAM path: {path}")
        relative = path.removeprefix(PREFIX).removesuffix(".source_sram_witness")
        require(relative not in observed, f"Duplicate SRAM instance: {relative}")
        require((int(depth), int(width)) == geometries[master], f"Elaborated geometry differs: {relative}")
        observed[relative] = master
    require(set(observed.values()) == set(geometries), "The source chip did not instantiate every compiled memory master")
    return observed


def run(candidate, output, verify_existing=False):
    evidence = {}

    def pin(path, expected=None):
        key, digest = str(path.relative_to(ROOT)), sha(path)
        require(expected is None or digest == expected, f"Evidence changed: {path}")
        require(evidence.setdefault(key, digest) == digest, f"Evidence changed during the census: {path}")

    def read(path):
        pin(path)
        return json.loads(path.read_text())

    prepared = candidate / "prepared.json"
    setup = read(prepared)
    require(setup["state"] == "dual_lane_packed_sign_chip_source_prepared", "Wrong source chip preparation")
    for name, digest in setup["input_sha256"].items():
        pin(ROOT / name, digest)
    prior = read(ROOT / "records/wac_response_address_linked_memory_result.json")
    require(prior["state"] == "linked_response_address_layer_memory_independently_verified",
            "Missing independently measured decoder memory baseline")
    targets = read(ROOT / "records/paper_result_targets.json")
    pin(ROOT / PAPER_RELATIVE, PAPER_SHA256)
    pin(Path(__file__).resolve())
    pin(Path(memory_shape.__code__.co_filename).resolve())

    geometries = {}
    bindings = []
    bundle = candidate / "bundle.sv"
    models = [Path(name) for name in INCLUDE.findall(bundle.read_text()) if Path(name).parent.name == "VERILOG"]
    require(len(models) == len(set(models)) == 6, "Unexpected compiled model list")
    for model in models:
        compiler = model.parent.parent
        master = compiler.name.removesuffix("_130a").upper()
        source = model.read_text()
        pin(model, prior["input_sha256"][str(model.relative_to(ROOT))])
        abstract = compiler / "LEF" / f"{compiler.name}.lef"
        pin(abstract, prior["input_sha256"][str(abstract.relative_to(ROOT))])
        require(re.findall(r"(?m)^\s*MACRO\s+(\w+)\s*$", abstract.read_text()) == [master],
                f"Wrong physical macro: {abstract}")
        shapes = set()
        for corner in CORNERS:
            library = compiler / "NLDM" / f"{compiler.name}_{corner}.lib"
            pin(library, prior["input_sha256"][str(library.relative_to(ROOT))])
            shapes.add(memory_shape(source, library.read_text(), master))
        require(len(shapes) == 1 and master not in geometries, f"Inconsistent memory geometry: {master}")
        geometries[master] = shapes.pop()
        depth, width = ("numWord", "numBit") if re.search(r"\bparameter\s+(?:integer\s+)?numWord\b", source) else ("W", "N")
        bindings.append(f'bind {master} source_sram_census #(.MASTER("{master}"), '
                        f'.WORDS({depth}), .WIDTH({width})) source_sram_witness ();\n')

    witness = output / "memory_census.sv"
    witness_source = """`timescale 1ns/1ps
module source_sram_census #(parameter string MASTER="", parameter int WORDS=0, WIDTH=0) ();
    initial $display("TRI_ORACLE_SOURCE_SRAM %s %0d %0d %m", MASTER, WORDS, WIDTH);
endmodule
""" + "".join(bindings)
    progress = output / "progress.log"
    argv = ["/usr/bin/prlimit", "--as=5368709120", "--", "/opt/cadence/bin/xrun", "-64bit", "-sv",
            "-nospecify", "-notimingchecks", "-sequdp_nba_delay", "-xmerror", "RECOME",
            "-top", BENCH, "-defparam", f"{BENCH}.INTERMEDIATE=256", str(bundle), str(candidate / "trained_tb.sv"),
            str(witness), f"+PROGRESS={progress}"]
    invocation = output / "invocation.json"
    console = output / "console.log"
    exit_status = output / "exit_status"
    if verify_existing:
        require(witness.read_text() == witness_source, "The existing capture used a different census witness")
        require(json.loads(invocation.read_text()) == {"argv": argv}, "The existing capture used a different invocation")
        status = int(exit_status.read_text())
    else:
        available = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                         if line.startswith("MemAvailable:"))
        require(available >= 17 * 1024**2, "Insufficient host memory for the source census")
        output.mkdir()
        witness.write_text(witness_source)
        invocation.write_text(json.dumps({"argv": argv}, indent=2) + "\n")
        try:
            with console.open("x") as stream:
                status = subprocess.run(argv, cwd=output, stdout=stream, stderr=subprocess.STDOUT, timeout=180).returncode
        finally:
            snapshot = output / "xcelium.d"
            if snapshot.is_dir():
                shutil.rmtree(snapshot)
        exit_status.write_text(f"{status}\n")
    log = output / "xrun.log"
    for path in (console, log, exit_status, progress, witness, invocation):
        pin(path)
    text = log.read_text()
    require(status == 0 and text.count("Simulation complete via $finish(1)") == 1
            and not re.search(r"\*[EF],", text), "The native source memory run failed")
    for path in (bundle, candidate / "trained_tb.sv", witness):
        require(text.splitlines().count(f"file: {path}") == 1, f"Native compile input differs: {path}")
    require(re.search(r"(?m)^BATCH408_PASS .* exact_outputs=504 .* fault=0 trained=0$", text),
            "The integrated predictor did not replay the source fixture")
    observed = census(text.splitlines(), geometries)
    # A driver diagnostic can interrupt a line in the shared stdout/stderr capture.
    captured = console.read_text().replace("dmesg: read kernel buffer failed: Operation not permitted\n", "")
    require(observed == census(captured.splitlines(), geometries),
            "Xcelium console and simulator memory counts disagree")
    counts = Counter(observed.values())
    sizes = {master: depth * width // 8 for master, (depth, width) in geometries.items()}
    predictor = {name: master for name, master in observed.items() if name.startswith(PREDICTOR)}
    roles = Counter()
    for name, master in predictor.items():
        role = name.removeprefix(PREDICTOR).split(".", 1)[0]
        roles[role] += sizes[master]
    require(len(predictor) == 10 and roles == {"metadata_memory": 6656, "sign_cache": 2048},
            "Unexpected packed predictor memory partition")
    expected = Counter({master: row["instances"] for master, row in prior["by_master"].items()})
    expected["TS5N28HPCPSVTA512X64M4F"] -= 2  # The scalar predictor used two of these metadata macros.
    expected.update(predictor.values())
    require(counts == expected, "Memory outside the packed predictor differs from the verified baseline")
    total = sum(sizes[master] * count for master, count in counts.items())
    label = targets["silicon"]["sram_published_KB"]
    require(all(sha(ROOT / name) == digest for name, digest in evidence.items()), "Census evidence changed")
    result = {
        "state": "packed_sign_source_chip_compiled_memory_census_verified",
        "instances": len(observed), "bytes": total, "kibibytes": total / 1024,
        "compiled_by_master": dict(sorted(counts.items())), "bytes_per_macro": sizes,
        "packed_predictor_bytes_by_role": dict(roles), "packed_predictor_instances": len(predictor),
        "prior_decoder_compiled_bytes": prior["compiled_bytes"],
        "published_label_kb": label, "delta_from_decimal_label_bytes": total - label * 1000,
        "delta_from_binary_label_bytes": total - label * 1024,
        "scope": "Reachable compiled memory instances in the full chip source simulation. "
                 "Capacity is independently checked against the physical abstracts and three timing library views. "
                 "The publication does not identify the unit convention, and the integrated mapped chip remains pending.",
        "evidence_sha256": evidence,
    }
    with (output / "receipt.json").open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], len(observed), total, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args()
    run(args.candidate, args.output, args.verify_existing)
