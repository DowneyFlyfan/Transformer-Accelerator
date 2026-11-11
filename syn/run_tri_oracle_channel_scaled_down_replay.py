"""Replay the complete trained frame through five qualified mapped clusters."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil

from prepare_tri_oracle_wac_outlier_layer import ROOT, read, sha, verify
from replay_mapped_cluster_fixture import CENSUS, STAGE, shared_memory_stage, wait_for_shared_memory, write_monitor

BENCH = "tri_oracle_batched393_tb"
CORE = "tri_oracle_sram_memory_compute"
SELECTED_CLUSTER = re.compile(r"\.fabric\.clusters\[([0-4])\]\.unit\.selected_bank\1\.block_instance\.")


def change_once(source, old, new):
    assert source.count(old) == 1, old
    return source.replace(old, new, 1)


def build_bundle(source_bundle, bench_source, output):
    text = source_bundle.read_text()
    includes = [Path(name) for name in re.findall(r'(?m)^`include "([^"]+)"$', text)]
    frame, = (path for path in includes if path.name == "tri_oracle_batched_frame393.sv")
    attention_bench, = (path for path in includes if path.name == "attention_tb.sv")
    selected = output / frame.name
    # Select the same five native clusters as the verified attention replay.
    selected.write_text(change_once(frame.read_text(), "tri_oracle_batched_frame437 implementation (",
        "tri_oracle_batched_frame437 #(\n"
        "    .AGGREGATOR_SIGN_BANK(1), .AGGREGATOR_MERGE_TABLE(1), .LOCAL_TOKEN_SIZES(1),\n"
        "    .LOCAL_TOKEN_MERGE(1), .CORE_STRIP_PREDICTOR(1), .CORE_HEAD_PREDICTOR(1)\n"
        "  ) implementation ("))
    bench = output / "trained_frame_tb.sv"
    # Weight and activation arrays are fixed. The unchanged scoreboard requires
    # all scratch bytes to be committed before the down phase can read them.
    bench.write_text(change_once(bench_source.read_text(), "always_comb begin: read_word",
                                  "always @(read_address or read_beat or read_active) begin: read_word"))
    text = change_once(text, f'`include "{frame}"', f'`include "{selected}"')
    text = change_once(text, f'`include "{attention_bench}"', "")
    bundle = output / "bundle.sv"
    bundle.write_text(text + f'\n`include "{bench}"\n')
    return bundle, selected, bench


def expected_instances(inventory, variants):
    targets = {}
    for bank in range(5):
        item = variants[str(bank)]
        assert item["top"] == f"tri_oracle_native_cluster{bank}_verified_bank{bank}"
        assert item["core"] == f"{CORE}_verified_bank{bank}"
        targets[item["top"]] = ("cluster", 1)
        targets[item["core"]] = ("core", 4)
    memories = Counter()
    for bank in range(5):
        memories.update(inventory[str(bank)]["macros"])
    assert sum(memories.values()) == 621
    targets.update({master: ("memory", count) for master, count in memories.items()})
    return targets


def check_run(log, targets, inventory, variants, fixture):
    lines = log.read_text().splitlines()
    assert not any(re.search(r"\*[EF],|Simulation terminated via \$fatal", line) for line in lines)
    markers = [line.split(maxsplit=2)[1:] for line in lines if line.startswith(CENSUS + " ")]
    assert len({path for _, path in markers}) == len(markers)
    assert Counter(master for master, _ in markers) == {master: count for master, (_, count) in targets.items()}
    banks = [Counter() for _ in range(5)]
    for master, path in markers:
        assert path.startswith(f"{BENCH}.dut.implementation.compute.tensor.fabric."), path
        bank = SELECTED_CLUSTER.search(path)
        assert bank is not None, path
        banks[int(bank[1])][master] += 1
    for bank, observed in enumerate(banks):
        item = variants[str(bank)]
        assert observed == inventory[str(bank)]["macros"] | {item["top"]: 1, item["core"]: 4}
    raw, = (line.removeprefix("BATCH393_PASS ") for line in lines if line.startswith("BATCH393_PASS "))
    counters = {key: int(value) for key, value in (part.split("=") for part in raw.split())}
    tokens, hidden, intermediate = (fixture[key] for key in ("tokens", "hidden", "intermediate"))
    tile_count = (hidden + 159) // 160
    expected = dict(tokens=tokens, hidden=hidden, intermediate=intermediate, outputs=hidden, trained=1, fault=0,
                    exact_outputs=fixture["exact_integer_outputs"], intermediate_bytes=tokens * intermediate,
                    output_packets=tokens * tile_count)
    assert all(counters[key] == value for key, value in expected.items()), counters
    tiles = [line for line in lines if line.startswith("BATCH393_OUTPUT_TILE ")]
    assert tiles == [f"BATCH393_OUTPUT_TILE start={start} count={min(160, hidden - start)}"
                     for start in range(0, hidden, 160)]
    assert counters["read_requests"] > 0 and counters["read_bytes"] > 0
    return counters


def run(case, fixture_path, output):
    qualification = case / "xcelium/mapped_cluster_qualification.json"
    setup_path = case / "receipt.json"
    proof, setup, fixture = (read(path) for path in (qualification, setup_path, fixture_path))
    assert proof["state"] == "mapped_clusters_replayed_archived_attention_on_twenty_mapped_cores"
    assert proof["mapped_banks"] == list(range(5)) and proof["mapped_compute_cores"] == 20 and proof["compiled_memories"] == 623
    variants = setup["full_mapped_cluster_banks"]
    assert proof["connected_compute_bits"] == dict.fromkeys(variants, 13468)
    assert fixture["state"] == "trained_channel_scaled_down_fixture_cpu_and_gpu_equal"
    assert (fixture["tokens"], fixture["hidden"], fixture["intermediate"], fixture["exact_integer_outputs"]) == (15, 2048, 5632, 30720)
    source = Path(fixture["fixture"])
    assert source == fixture_path.parent
    assert setup["bundle"] == str(case / "bundle.sv")
    assert proof["input_sha256"][str(setup_path)] == sha(setup_path)
    assert proof["input_sha256"][setup["bundle"]] == sha(setup["bundle"])
    pins = proof["input_sha256"].copy()
    for name, digest in fixture["input_sha256"].items():
        assert pins.get(name, digest) == digest, name
        pins[name] = digest
    pins.update({str(source / name): digest for name, digest in fixture["files_sha256"].items()})
    verify(pins)
    inventory_path = STAGE / "inventory.json"
    assert pins[str(inventory_path)] == sha(inventory_path)
    inventory = read(inventory_path)
    targets = expected_instances(inventory, variants)
    bench_source = ROOT / "verilog/tri_oracle_batched393_tb.sv"
    output.mkdir()
    bundle, frame, bench = build_bundle(case / "bundle.sv", bench_source, output)
    monitor = output / "hierarchy.sv"
    write_monitor(monitor, targets)
    pins.update({str(path): sha(path) for path in (Path(__file__), qualification, fixture_path, bench_source,
                                                   bundle, frame, bench, monitor)})
    verify(pins)
    (output / "inputs.json").write_text(json.dumps(pins, indent=2) + "\n")
    snapshot = output / "xcelium.d"
    command = ["/opt/cadence/bin/xrun", "-64bit", "-sv", "-sequdp_nba_delay", "-xmerror", "RECOME",
               "-nospecify", "-notimingchecks", "-mce", "-mce_sim_thread_count", "4", "-mce_build_thread_count", "4",
               "-top", BENCH, "-xmlibdirname", str(snapshot)]
    parameters = dict(TRAINED=1, TOKENS=fixture["tokens"], HIDDEN=fixture["hidden"],
                      INTERMEDIATE=fixture["intermediate"], OUTPUTS=fixture["hidden"])
    for key, value in parameters.items():
        command.extend(("-defparam", f"{BENCH}.{key}={value}"))
    command.extend((str(bundle), str(monitor), f"+FIXTURE={source}"))
    wait_for_shared_memory("trained mapped feed-forward replay", 17)
    try:
        native = shared_memory_stage("trained mapped feed-forward replay", output, command, 21600, 0)
        assert native["log_sha256"] == sha(output / "console.log")
        counters = check_run(output / "console.log", targets, inventory, variants, fixture)
        verify(pins)
    finally:
        if snapshot.is_dir():
            shutil.rmtree(snapshot)
    result = dict(state="trained_channel_scaled_down_frame_replayed_on_five_mapped_clusters", native=native,
                  mapped_clusters=5, mapped_compute_cores=20, compiled_cluster_memories=621, counters=counters,
                  input_sha256=pins, scope="Prepared activations and skip masks with raw signed32 feed-forward outputs.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], counters["exact_outputs"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("case", "fixture", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    run(args.case, args.fixture, args.output)
