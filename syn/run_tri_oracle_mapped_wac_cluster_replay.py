"""Replay the archived attention through mapped cluster controllers and compute cores."""

import argparse
from collections import Counter
from io import StringIO
import json
from pathlib import Path
import re
import shutil
import sys

from audit_tri_oracle_wac_memory_capacity import memory_inventory
from prepare_mapped_cluster_fixture import module_text
from prepare_tri_oracle_mapped_wac_layer import CORE, read, sha, verify
from run_separate_cores_fixture_export_at_reserve import genus_ports
from run_tri_oracle_head_offload_layer import check_replay, expected, replay, routes
from run_tri_oracle_mapped_wac_layer import LEAF
from run_tri_oracle_core_local_scores import CLUSTER_ISSUE

PORT = re.compile(r"(?m)^\s*(input|output)\s+(wire|logic|\w+::\w+)\s+(?:\[(\d+):(\d+)\]\s+)?(\w+)\s*,?$")
FIELDS = {
    "softmax_request": dict(owner=5, score_tile=1, score_core=1, cfg_valid=1, cfg_length=11,
                            in_valid=1, score=16, size=10, out_ready=1, outlier_valid=1, normalized=128),
    "softmax_response": dict(cfg_ready=1, cfg_error=1, in_ready=1, out_valid=1, out_last=1,
                             probability=16, outlier_valid=1, outliers=8, negative=8),
}
CENSUS = replay.CENSUS
BASE_TARGETS = replay.expected_types
BASE_CENSUS = replay.census


def check_core_bindings(source, ledger, ports):
    instance = source.read_text().split(f"{CORE} compute (", 1)[1].split("    );", 1)[0]
    connections = re.findall(r"\.(\w+)\(([^()]*)\)", instance)
    signals = dict(connections)
    assert len(connections) == len(signals) and signals.keys() == ports.keys()
    assert {port for port, signal in signals.items() if not signal} == {"activation_reload_required"}
    direct = re.compile(r"source_cluster/implementation/cores\[[0-3]\]/compute/[^/]+")
    actual = {}
    for row in ledger.read_text().splitlines():
        pin, net = row.split("\t")
        if direct.fullmatch(pin):
            assert pin not in actual, pin
            actual[pin] = net

    expected = {}
    for core in range(4):
        parent = f"source_cluster/implementation/cores[{core}]"
        for port, signal in connections:
            if not signal:
                continue
            name, _, field = signal.partition(".")
            net = f"{name}[{field}]" if field else name
            _, span = ports[port]
            bits = ("",) if span is None else (f"[{bit}]" for bit in range(min(span), max(span) + 1))
            for bit in bits:
                expected[f"{parent}/compute/{port}{bit}"] = f"{parent}/{net}{bit}"
    assert actual.keys() == expected.keys(), "Mapped compute port inventory differs from the declared interface"
    for pin, net in expected.items():
        assert actual[pin] == net, (pin, net, actual[pin])
    return len(expected)


def bridge(wrapper, mapped_top, mapped_text):
    header, _, _ = wrapper.partition("\n);")
    assert len(header) < len(wrapper)
    ports = {}
    connections = []
    mapped_module = module_text(mapped_text)[mapped_top][0]
    for direction, _, msb, lsb, name in PORT.findall(header):
        if name in FIELDS:
            for field, width in FIELDS[name].items():
                escaped = rf"\{name}[{field}]"
                canonical = f"{name}__{field}"
                mapped_module = mapped_module.replace(escaped, canonical)
                ports[canonical] = direction, (width - 1, 0) if width > 1 else None
                connections.append(f".{escaped} ({name}.{field})")
        else:
            ports[name] = direction, (int(msb), int(lsb)) if msb else None
            connections.append(f".{name}({name})")
    observed = genus_ports(StringIO(mapped_module), mapped_top)
    assert ports == observed, [(key, ports.get(key), observed.get(key)) for key in sorted(ports.keys() | observed.keys())
                               if ports.get(key) != observed.get(key)]
    prefix = "mapped_native.source_cluster.implementation."
    vectors = {}
    for pin in ("cmd_valid", "activation_reloaded"):
        vectors[pin] = ", ".join(rf"{prefix}\cores[{core}] .compute.{pin}" for core in range(3, -1, -1))
    linked_ports = ",\n    ".join(connections)
    return header + f"""
);
  {mapped_top} mapped_native (
    {linked_ports}
  );
  tri_oracle_score_core_issue_probe score_issue_probe (
    .clk, .rst_n, .issue(cmd_valid && cmd_ready), .activation_reloaded, .core_score_select,
    .core_issue({{{vectors['cmd_valid']}}}), .core_activation_reloaded({{{vectors['activation_reloaded']}}})
  );
endmodule"""


def namespace(raw, bank):
    modules = module_text(raw)
    suffix = f"_verified_bank{bank}"
    assert not any(name.endswith(suffix) for name in modules)
    pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, sorted(modules))) + r")\b")
    renamed = pattern.sub(lambda match: match[0] + suffix, raw)
    assert set(module_text(renamed)) == {name + suffix for name in modules}
    return renamed, suffix


def prepare(source, mappings, output):
    proof_path = source / "xcelium/mapped_wac_qualification.json"
    prior = read(proof_path)
    assert prior["state"] == "twenty_mapped_compute_cores_replayed_archived_attention"
    inputs = prior["input_sha256"].copy()
    verify(inputs)
    setup_path = source / "receipt.json"
    setup = read(setup_path)
    assert inputs[str(setup_path)] == sha(setup_path)
    core_netlist = Path(setup["mapped_core_netlist"])
    assert inputs[str(core_netlist)] == sha(core_netlist)
    with core_netlist.open() as stream:
        core_ports = genus_ports(stream, CORE)
    body = (source / "bundle.sv").read_text()
    wrappers_path, = (Path(name) for name in re.findall(r'(?m)^`include "([^"]+)"$', body) if Path(name).name == "wrappers.sv")
    assert inputs[str(wrappers_path)] == sha(wrappers_path)
    wrappers = wrappers_path.read_text()
    output.mkdir()
    variants = {}
    generated = []
    for mapping in mappings:
        receipt = mapping / "receipt.json"
        mapped = read(receipt)
        bank, top = mapped["bank"], mapped["top"]
        assert bank in range(5) and str(bank) not in variants and top == f"tri_oracle_native_cluster{bank}"
        assert mapped["state"] == "cluster_mapped_around_four_verified_cores"
        ledger = mapping / "core_boundary.tsv"
        assert sha(ledger) == mapped["output_sha256"][ledger.name]
        adapter = mapping / "tri_oracle_sram_compute_cluster.sv"
        assert sha(adapter) == mapped["input_sha256"][str(adapter)]
        connected_bits = check_core_bindings(adapter, ledger, core_ports)
        assert mapped["native"]["native_exit_status"] == 0 and mapped["native"]["log_sha256"] == sha(mapping / "console.log")
        for name, digest in (mapped["input_sha256"] | {str(mapping / name): digest for name, digest in mapped["output_sha256"].items()}).items():
            assert inputs.get(name, digest) == digest, name
            inputs[name] = digest
        inputs[str(receipt)] = sha(receipt)
        inputs[str(mapping / "console.log")] = sha(mapping / "console.log")
        mapped_text, suffix = namespace((mapping / "netlist.v").read_text(), bank)
        mapped_top = top + suffix
        wrapped = module_text(wrappers)[top]
        wrappers = wrappers[:wrapped.start()] + bridge(wrapped[0], mapped_top, mapped_text) + wrappers[wrapped.end():]
        linked = output / f"cluster{bank}.v"
        linked.write_text(mapped_text)
        generated.append(linked)
        variants[str(bank)] = dict(top=mapped_top, core=CORE + suffix, simd="tri_oracle_wac_softmax" + suffix,
                                   connected_compute_bits=connected_bits)
    assert variants
    patched = output / "wrappers.sv"
    patched.write_text(wrappers)
    witnesses = output / "mapped_cluster_witness.sv"
    witnesses.write_text("\n".join(
        f"bind {item['core']} tri_oracle_mapped_wac_witness mapped_wac_witness ();\n"
        f"bind {item['simd']} tri_oracle_wac_softmax_route_probe row_route_probe (.*);"
        for item in variants.values()) + "\n")
    bundle = output / "bundle.sv"
    body = body.replace(f'`include "{wrappers_path}"', f'`include "{patched}"')
    bundle.write_text(body + "".join(f'`include "{path}"\n' for path in [*generated, witnesses]))
    inputs.update({str(path): sha(path) for path in (Path(__file__), proof_path, patched, witnesses, bundle, *generated)})
    verify(inputs)
    setup.update(bundle=str(bundle), input_sha256=inputs, full_mapped_cluster_banks=variants)
    (output / "receipt.json").write_text(json.dumps(setup, indent=2) + "\n")


def normalize(line):
    line = re.sub(r"\\(\S+)\s+(?=\.)", r"\1", line)
    if line.startswith("SCORE_CORE_ISSUE "):
        line = line.replace(".block_instance.score_issue_probe", ".block_instance.source_cluster.implementation.score_issue_probe")
    return line.replace(".block_instance.mapped_native.", ".block_instance.")


def run(source, mappings, output):
    prepare(source, mappings, output)
    setup, baseline, baseline_path = expected(output)
    variants = setup["full_mapped_cluster_banks"]
    targets = BASE_TARGETS(output, setup)
    original = targets.copy()
    if len(variants) == 5:
        del targets[CORE]
    else:
        targets[CORE] = ("source_core", 20 - 4 * len(variants))
    for item in variants.values():
        targets[item["core"]] = ("mapped_core", 4)

    def check_census(lines, *_):
        counts = Counter(line.split()[1] for line in lines if line.startswith(CENSUS + " "))
        assert counts == {name: count for name, (_, count) in targets.items()}, counts
        aliases = {item["core"]: CORE for item in variants.values()}
        normalized = []
        for line in lines:
            if line.startswith(CENSUS + " "):
                marker, master, path = line.split(maxsplit=2)
                normalized.append(f"{marker} {aliases.get(master, master)} {normalize(path)}")
        BASE_CENSUS(normalized, original, [])
        return {"cluster": 5, "source_core": 20 - 4 * len(variants), "mapped_core": 4 * len(variants), "memory": 623}, counts

    replay.expected_types = lambda *_: targets
    replay.census = check_census
    replay.check_markers = lambda lines, markers: check_replay(lines, markers, baseline)
    sys.argv = [replay.__file__, str(output), "--shared-memory"]
    try:
        replay.main()
    finally:
        snapshot = output / "xcelium/xcelium.d"
        if snapshot.is_dir():
            shutil.rmtree(snapshot)
    native = output / "xcelium"
    receipt_path = native / "receipt.json"
    result = read(receipt_path)
    console = native / "positive/console.log"
    assert sha(console) == result["replay"]["log_sha256"]
    log = console.read_text()
    assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
    lines = [normalize(line) for line in log.splitlines()]
    prior = read(source / "xcelium/mapped_wac_qualification.json")
    assert result["measured"] == prior["compared"]
    routes(lines, (2, 0), prior["compared"]["rows"], prior["compared"]["values"])
    issues = [CLUSTER_ISSUE.fullmatch(line) for line in lines if line.startswith("SCORE_CORE_ISSUE ")]
    assert len(issues) == 5 and all(issues)
    assert sorted(tuple(map(int, item.groups())) for item in issues) == [(bank, bank, 8 if bank == 2 else 0) for bank in range(5)]
    leaves = [LEAF.fullmatch(line) for line in lines if line.startswith("WAC_MAPPED_COMPUTE_LEAF ")]
    assert len(leaves) == 20 and all(leaves)
    assert sorted(tuple(map(int, item.groups())) for item in leaves) == [(bank, bank, core) for bank in range(5) for core in range(4)]
    expected_memory = {name: count for name, (role, count) in original.items() if role == "memory"}
    prior_console = source / "xcelium/positive/console.log"
    assert prior["input_sha256"][str(prior_console)] == sha(prior_console)
    assert memory_inventory(lines, expected_memory) == memory_inventory(prior_console.read_text().splitlines(), expected_memory)
    pins = result["input_sha256"].copy()
    pins.update({str(path): sha(path) for path in (receipt_path, console, baseline_path)})
    verify(pins)
    record = dict(state="mapped_clusters_replayed_archived_attention_on_twenty_mapped_cores",
                  mapped_banks=sorted(map(int, variants)), mapped_compute_cores=20, compiled_memories=623,
                  connected_compute_bits={bank: item["connected_compute_bits"] for bank, item in variants.items()},
                  measured=result["measured"], replay_seconds=result["replay"]["elapsed_seconds"], input_sha256=pins)
    (native / "mapped_cluster_qualification.json").write_text(json.dumps(record, indent=2) + "\n")
    print(record["state"], record["mapped_banks"], record["measured"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=lambda value: Path(value).resolve())
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    parser.add_argument("mappings", nargs="+", type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    run(args.source, args.mappings, args.output)
