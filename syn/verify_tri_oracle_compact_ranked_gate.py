"""Compare compiled-memory traffic on the exact source and mapped predictors."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess

from verify_tri_oracle_ranked_sign_gate import (
    BENCH, CELLS, ROOT, RTL_ONLY, TOP, adapter_text, require, sha,
)


RECORD = ROOT / "records/wac_compact_ranked_metadata_result.json"
WITNESS = ROOT / "verilog/tri_oracle_compact_bank_traffic.sv"
EXPECTED_BANKS = {"TS5N28HPCPSVTA32X128M2FW": 9, "TS5N28HPCPSVTA512X64M4F": 1}
BANK = re.compile(r"COMPACT_BANK (\w+) (.+) (\d+) (\d+) ([0-9a-f]{16})")
SOURCE_ONLY = RTL_ONLY | {
    "tri_oracle_outlier_word_codec.sv", "tri_oracle_compact_outlier_words.sv", "memory_witness.sv",
}


def memory_traffic(lines, prefix):
    ledger = {}
    for line in lines:
        if not line.startswith("COMPACT_BANK "):
            continue
        entry = BANK.fullmatch(line)
        require(entry is not None, f"Malformed compiled memory traffic: {line}")
        master, raw_path, reads, writes, signature = entry.groups()
        instance = re.sub(r"[\\\s]", "", raw_path).removesuffix(".traffic")
        require(instance.startswith(f"{prefix}."), f"Unexpected memory instance: {instance}")
        require(instance not in ledger, f"Duplicate memory instance: {instance}")
        ledger[instance] = master, int(reads), int(writes), signature
    require(Counter(entry[0] for entry in ledger.values()) == EXPECTED_BANKS,
            "Unexpected compiled memory inventory")
    return ledger


def compare_traffic(source, mapped):
    source_signatures = Counter(tuple(entry) for entry in source.values())
    mapped_signatures = Counter(tuple(entry) for entry in mapped.values())
    require(source_signatures == mapped_signatures, "Memory traffic changed between source and mapped gates")


def metadata_traffic(ledger, record):
    metadata = [entry for name, entry in ledger.items() if name.startswith(f"{BENCH}.dut.metadata_memory.")]
    require(len(metadata) == 6, "Unexpected source metadata bank count")
    reads = sum(entry[1] for entry in metadata)
    writes = sum(entry[2] for entry in metadata)
    require(reads == record["metadata_native_reads"] and writes == record["metadata_native_writes"],
            "Physical metadata traffic differs from the source interface counts")
    return {"reads": reads, "writes": writes}


def read(path):
    return json.loads(path.read_text())


def run(integrated, output, mapping=None, reference=None):
    source_record = read(RECORD)
    require(source_record["state"] == "compact_ranked_predictor_replayed_trained_masks_with_compiled_memory",
            "The compact source predictor has no verified trained replay")
    pins = source_record["input_sha256"].copy()

    def pin(path, expected=None):
        name, digest = str(path.relative_to(ROOT)), sha(path)
        require((expected is None or expected == digest) and pins.setdefault(name, digest) == digest,
                f"Changed input: {path}")

    def verify_pins():
        require(all(sha(ROOT / name) == digest for name, digest in pins.items()), "Evidence changed during replay")

    for path in (RECORD, WITNESS, Path(__file__).resolve()):
        pin(path)
    source = integrated / f"{TOP}.sv"
    bench = integrated / f"{BENCH}.sv"
    prior = integrated / "trained/invocation.json"
    args = read(prior)["argv"]
    require(all(args.count(str(path)) == 1 for path in (source, bench, integrated / "memory_witness.sv")),
            "The prior replay did not bind the expected source and testbench")
    for path in (source, bench, prior):
        require(str(path.relative_to(ROOT)) in pins, f"Unbound source replay input: {path}")
        pin(path)
    fixture, = (Path(arg.split("=", 1)[1]) for arg in args if arg.startswith("+FIXTURE="))
    for name in ("branch_masks.hex", "outlier_counts.hex"):
        pin(fixture / name)
    for arg in args:
        if arg.startswith("+") and not arg.startswith("+FIXTURE="):
            pin(Path(arg.split("=", 1)[1]))
        if arg.startswith("/") and Path(arg).suffix in (".v", ".sv"):
            pin(Path(arg))

    wrapper = mapped_bench = gate = None
    output.mkdir()
    if mapping:
        source_proof = read(reference)
        require(source_proof["state"] == "compact_predictor_source_bank_traffic_verified", "Missing source traffic proof")
        for name, digest in source_proof["input_sha256"].items():
            pin(ROOT / name, digest)
        source_console = reference.with_name("console.log")
        require(str(source_console.relative_to(ROOT)) in source_proof["input_sha256"],
                "Source bank census did not bind the native transcript")
        source_traffic = memory_traffic(source_console.read_text().splitlines(), f"{BENCH}.dut")
        require(source_proof["bank_traffic"] == {name: list(entry) for name, entry in source_traffic.items()},
                "Source receipt differs from the compiled memory transcript")
        pin(reference)
        mapped = read(mapping / "native_receipt.json")
        require(mapped["native_exit_status"] == 0 and mapped["stop"] is None,
                "The compact predictor mapping did not pass")
        require(mapped["input_sha256"][str(RECORD.relative_to(ROOT))] == sha(RECORD),
                "The mapping did not use the verified compact source")
        for name, digest in mapped["input_sha256"].items():
            pin(ROOT / name, digest)
        for name, digest in mapped["outputs"].items():
            pin(mapping / name, digest)
        pin(mapping / "native_receipt.json")
        cell_proof = ROOT / "records/wac_response_address_mapped_result.json"
        pin(cell_proof)
        pin(CELLS, read(cell_proof)["evidence_sha256"][str(CELLS.relative_to(ROOT))])
        pin(Path(adapter_text.__code__.co_filename).resolve())
        gate = mapping / "netlist.v"
        wrapper = output / "mapped_predictor.sv"
        wrapper.write_text(adapter_text(source.read_text(), gate.read_text()))
        mapped_bench = output / bench.name
        request = "dut.cache_req_valid && dut.cache_req_ready"
        text = bench.read_text()
        require(text.count(request) == 1, "The predictor request monitor changed")
        mapped_bench.write_text(text.replace(request, "dut.observed_cache_accept"))
        pin(wrapper)
        pin(mapped_bench)

    argv = []
    for arg in args:
        if arg == str(integrated / "memory_witness.sv"):
            argv.append(str(WITNESS))
        elif gate and arg == str(source):
            argv.extend(map(str, (CELLS, gate, wrapper)))
        elif gate and arg == str(bench):
            argv.append(str(mapped_bench))
        elif not (gate and arg.startswith("/") and Path(arg).name in SOURCE_ONLY):
            argv.append(arg)
    invocation = output / "invocation.json"
    invocation.write_text(json.dumps({"argv": argv}, indent=2) + "\n")
    pin(invocation)
    verify_pins()
    available = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                     if line.startswith("MemAvailable:"))
    require(available >= 15 * 1024**2, "Insufficient host memory for the replay")
    console = output / "console.log"
    try:
        with console.open("x") as stream:
            status = subprocess.run(argv, cwd=output, stdout=stream, stderr=subprocess.STDOUT, timeout=180).returncode
    finally:
        snapshot = output / "xcelium.d"
        if snapshot.is_dir():
            shutil.rmtree(snapshot)
    exit_status = output / "exit_status"
    exit_status.write_text(f"{status}\n")
    log = console.read_text()
    require(status == 0 and not re.search(r"\*[EF],|\$fatal", log), f"Xcelium replay failed: {console}")
    metrics, = re.findall(r"(?m)^PACKED_SIGN_PREDICTOR_PASS (.+)$", log)
    observed = {name: int(value) for name, value in (field.split("=") for field in metrics.split())}
    require(observed == source_record["trained_replay"], "Trained mask or request counters changed")
    prefix = f"{BENCH}.dut" + (".mapped" if gate else "")
    traffic = memory_traffic(log.splitlines(), prefix)
    native_log = output / "xrun.log"
    require(memory_traffic(native_log.read_text().splitlines(), prefix) == traffic,
            "The native simulator log and console disagree")
    if gate:
        compare_traffic(source_traffic, traffic)
    metadata = metadata_traffic(source_traffic if gate else traffic, source_record)
    for path in (console, exit_status, native_log):
        pin(path)
    verify_pins()
    state = ("compact_predictor_mapped_bank_traffic_verified" if gate else
             "compact_predictor_source_bank_traffic_verified")
    result = {"state": state, "bank_traffic": traffic, "metadata_traffic": metadata,
              "trained_replay": observed, "input_sha256": pins}
    (output / "receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(state, metrics, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integrated", "output", "--mapping", "--reference"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    if bool(args.mapping) != bool(args.reference):
        parser.error("--mapping and --reference are required together")
    run(args.integrated, args.output, args.mapping, args.reference)
