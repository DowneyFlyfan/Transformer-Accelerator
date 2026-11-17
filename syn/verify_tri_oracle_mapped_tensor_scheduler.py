"""Verify the recovered mapped tensor scheduler against the timed chip replay."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

from audit_tri_oracle_packed_weight_path import pins
from link_tri_oracle_indexed_whole_chip import module_at, signature, spans
from verify_tri_oracle_mapped_weight_prefetch import BUNDLE, ROOT, RUN, WORK as LOADER, invocation
from verify_tri_oracle_phase_chip import summary, verify_case


WORK = RUN / "mapped_tensor_scheduler"
TOP = "tri_oracle_batched_tensor390"
GATE = TOP + "_gate"
FABRIC = "tri_oracle_compute_fabric"
LOADER_MODULE = "tri_oracle_backpressured_raw_weight_loader"
SEQUENCER = "tri_oracle_batched_projection356"
FLAGS = ("AGGREGATOR_SIGN_BANK", "AGGREGATOR_MERGE_TABLE", "LOCAL_TOKEN_SIZES", "LOCAL_TOKEN_MERGE",
         "CORE_STRIP_PREDICTOR", "CORE_HEAD_PREDICTOR")
SUFFIX = "_" + "_".join(flag + "1" for flag in FLAGS)
CASES = ("early_gate", "weight_stall", "weight_prefetch_fault_lane0", "weight_prefetch_fault_lane1",
         "weight_guard_disabled", "scalar")


def linked_inputs():
    contents = {}
    status = (WORK / "exit_status").read_text().strip()
    log = (WORK / "console.log").read_text().splitlines()
    assert all(log.count(f"TENSOR_SCHEDULER_CUT {name}") == 1 for name in ("packed_loader", "sequencer", "fabric"))
    assert status == "124" and any("Done mapping '" + TOP in line for line in log)
    archive, = (WORK / "fv").glob("*/fv_map.v.gz")
    assert any("Wrote 'fv/" in line and "fv_map.v.gz" in line for line in log)
    with gzip.open(archive, "rb") as stream:
        native = stream.read()
    spans_by_name = spans(native)
    native_name, = (name for name in spans_by_name if name in (TOP, TOP + SUFFIX))
    fabric_name, = (name for name in spans_by_name if name.startswith(FABRIC))
    parent = module_at(native, spans_by_name, native_name)
    fabric = module_at(native, spans_by_name, fabric_name)
    support = spans_by_name.keys() - {native_name, fabric_name, LOADER_MODULE, SEQUENCER}
    aliases = {name.encode(): f"scheduler_{name}".encode() for name in support}
    inst = re.compile(rb"(?m)^([ \t]*)(\w+)([ \t]+\\?[^\s]+[ \t]*\()")
    def namespaced(block):
        return inst.sub(lambda item: item[1] + aliases.get(item[2], item[2]) + item[3], block)
    fabric_bindings = pins(parent, fabric_name, "fabric")
    assert fabric_bindings and pins(parent, LOADER_MODULE, "packed_loader")
    sequencer = pins(parent, SEQUENCER, "sequencer")

    source = (RUN / "source" / f"{TOP}.sv").read_text()
    parent = parent.replace(f"module {native_name}(".encode(), f"module {GATE}(".encode(), 1)
    assert parent.startswith(f"module {GATE}(".encode())
    names = signature(module_at(native, spans_by_name, native_name))
    assert {"clk", "rst_n", "weight_memory_clk", "cfg_channels", "cfg_keep", "softmax_request[score_tile]"} <= names.keys()
    top = WORK / "scheduler.v"
    blocks = []
    for name in spans_by_name:
        if name in support:
            block = module_at(native, spans_by_name, name)
            block = block.replace(b"module " + name.encode() + b"(", b"module " + aliases[name.encode()] + b"(", 1)
            blocks.append(namespaced(block))
    contents[top] = b"\n".join((*blocks, namespaced(parent))) + b"\n"
    wrapper = WORK / "scheduler_adapter.sv"
    original_header = source.split("\n);\n", 1)[0] + "\n);\n"
    connections = [f".\\{name} ({name.replace('[', '.').rstrip(']')})"
                   for name in names if "[" in name]
    assert connections and all(re.fullmatch(r"\w+\[\w+\]", name) for name in names if "[" in name)
    contents[wrapper] = (original_header + f"  {GATE} implementation (\n    "
                         + ",\n    ".join((*connections, ".*")) + "\n  );\nendmodule\n").encode()

    ports = signature(fabric)
    grouped = {}
    struct_pins = {}
    for port in ports:
        if match := re.fullmatch(r"(\w+)\[(\d+)\]", port):
            grouped.setdefault(match[1], []).append((int(match[2]), port))
        elif match := re.fullmatch(r"(\w+)\[(\w+)\]", port):
            struct_pins[port] = (match[1], match[2])
    assert grouped.keys() == {"wide_load_core", "wide_load_addr", "wide_load_group", "wide_load_enable", "wide_load_payload"}
    connections = [f".{name}({{{', '.join(chr(92) + port + ' ' for _, port in sorted(group, reverse=True))}}})"
                   for name,group in grouped.items()]
    actual = (RUN / "source" / f"{FABRIC}.sv").read_text().split("\n);\n", 1)[0]
    structs = {name: type_name for type_name, name in
               re.findall(r"(tri_oracle_\w+::(?:request_t|response_t)) (\w+)", actual)}
    assert {name for name, _ in struct_pins.values()} == structs.keys()
    structure_wires = "".join(f"  {type_name} {name};\n" for name,type_name in structs.items())
    for port, (name, field) in struct_pins.items():
        field_path, wire = f"{name}.{field}", f"\\{port} "
        assigned, value = (field_path, wire) if ports[port][0] == b"input" else (wire, field_path)
        structure_wires += f"  assign {assigned} = {value};\n"
    parameters = ", ".join(f".{flag}(1'b1)" for flag in FLAGS)
    adapter = WORK / "fabric_adapter.sv"
    contents[adapter] = fabric.rsplit(b"endmodule", 1)[0] + (
        structure_wires + f"  {FABRIC} #({parameters}) implementation (\n    "
        + ",\n    ".join((*connections, ".*")) + "\n  );\nendmodule\n"
    ).encode()

    loader_gate = (LOADER / "gates.v").read_bytes()
    loader = WORK / "weight_loader.v"
    loader_definition = loader_gate.replace(f"module {LOADER_MODULE}_mapped(".encode(),
                                           f"module {LOADER_MODULE}(".encode(), 1)
    assert signature(loader_definition) == signature(module_at(native, spans_by_name, LOADER_MODULE))
    contents[loader] = loader_definition

    original = ROOT / "verilog/tri_oracle_activation_tile_prefetch_probe.sv"
    probe = WORK / "activation_prefetch_probe.sv"
    done = sequencer["done_ready"].decode()
    assert re.fullmatch(r"\w+", done), done
    text = original.read_text()
    assert text.count("state==WAIT_PREFETCH") == 1
    text = text.replace("state==WAIT_PREFETCH", done).replace(f"bind {TOP} ", f"bind {GATE} ")
    for pin in ("load_valid", "load_kind"):
        text = text.replace(f".{pin},", f".{pin}({fabric_bindings[pin].decode()}),")
    contents[probe] = text.encode()
    old_weight_probe = ROOT / "verilog/tri_oracle_weight_tile_prefetch_probe.sv"
    new_weight_probe = WORK / old_weight_probe.name
    contents[new_weight_probe] = old_weight_probe.read_text().replace(f"bind {TOP} ", f"bind {GATE} ").encode()
    base = (RUN / "mapped_ingress/mapped/bundle.sv").read_text()
    replacements = {
        RUN / "source" / f"{TOP}.sv": [top, wrapper, adapter],
        LOADER / "gates.v": [loader],
        LOADER / "adapter.sv": [],
        original: [probe],
        old_weight_probe: [new_weight_probe],
    }
    for old, paths in replacements.items():
        entry = f'`include "{old}"\n'
        assert base.count(entry) == 1, old
        base = base.replace(entry, "".join(f'`include "{path}"\n' for path in paths))
    bundle = WORK / "bundle.sv"
    contents[bundle] = base.encode()
    return contents


def fixture(name, bundle):
    case = WORK / name
    baseline = (RUN / name / "xrun.log").read_text().replace(str(BUNDLE), str(bundle))
    if name != "weight_guard_disabled" and name != "weight_stall" and "fault" not in name:
        return baseline, None, None
    original = RUN / "source/weight_prefetch_stress_bench.sv"
    bench = case / original.name
    source = original.read_text()
    assert source.count(".tensor.fabric.weight_ingress.allowed") == 1
    source = source.replace(".tensor.fabric.weight_ingress.allowed",
                            ".tensor.fabric.implementation.weight_ingress.allowed")
    for member in ("prefetch_inflight", "sequence_done_valid", "fabric"):
        source = source.replace(f".tensor.{member}", f".tensor.implementation.{member}")
    return baseline.replace(str(original), str(bench)), bench, source


def replay(bundle, name):
    case = WORK / name
    case.mkdir()
    baseline, path, source = fixture(name, bundle)
    if path is not None:
        path.write_text(source)
    args = [arg for line in invocation(baseline) for arg in line.split()]
    command = ["docker", "exec", "-w", str(case), "tri-oracle-eda", "timeout", "-k", "5", "300",
               "prlimit", "--as=5368709120", "--", "/opt/cadence/bin/xrun", *args]
    with (case / "console.log").open("w") as console:
        status = subprocess.run(command, stdout=console, stderr=subprocess.STDOUT, check=False).returncode
    (case / "exit_status").write_text(f"{status}\n")
    assert status == (2 if name == "weight_guard_disabled" else 0), (name, status)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify():
    manifest = WORK / "synthesis_inputs.json"
    source_pins = {ROOT / name: value for name, value in json.loads(manifest.read_text()).items()}
    assert all(digest(path) == value for path, value in source_pins.items())
    files = linked_inputs()
    assert all(path.read_bytes() == expected for path, expected in files.items())
    inputs = [*files, *source_pins, manifest, Path(__file__).resolve(), WORK / "console.log", WORK / "exit_status",
              LOADER / "gates.v", RUN / "mapped_ingress/mapped/bundle.sv"]
    inputs.extend((WORK / "fv").glob("*/fv_map.v.gz"))
    bundle = WORK / "bundle.sv"
    cases = {}
    for name in CASES:
        case = WORK / name
        baseline, bench, contents = fixture(name, bundle)
        if bench is not None:
            assert bench.read_text() == contents
            inputs.append(bench)
        path = case / "xrun.log"
        text = path.read_text()
        assert invocation(text) == invocation(baseline), name
        inputs.extend((path, case / "exit_status", RUN / name / "xrun.log"))
        if name == "weight_guard_disabled":
            assert (case / "exit_status").read_text().strip() == "2"
            assert "CHIP_WEIGHT_PREFETCH_OVERWRITE cluster=0 word=0" in text
            assert "Simulation terminated via $fatal(1)" in text and "BATCH408_PASS" not in text
            cases[name] = {"rejected_unread_word": 0}
            continue
        original, reference = verify_case(RUN, name)
        _, physical = verify_case(WORK, name)
        assert physical == reference, name
        result = {}
        markers = ("BATCH408_PASS", "PACKED_DECODER_PASS", "CHIP_WEIGHT_PREFETCH",
                   "CHIP_ACTIVATION_PREFETCH", "CHIP_WEIGHT_GUARD")
        if "fault" in name:
            markers += ("BATCH408_FAULT_DRAINED",)
        for marker in markers:
            result[marker] = summary(text, marker)
            assert result[marker] == summary(original, marker), (name, marker)
        assert result["BATCH408_PASS"]["exact_outputs"] == 504
        trace, control = case / "progress.log", RUN / name / "progress.log"
        assert trace.read_bytes() == control.read_bytes(), name
        inputs.extend((trace, control))
        cases[name] = result
    return {
        "state": "mapped_tensor_scheduler_matches_source_cycles",
        "genus_exit_status": int((WORK / "exit_status").read_text()),
        "cases": cases,
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in sorted(set(inputs))},
        "scope": "The mapped scheduler comes from the saved technology-mapping checkpoint. "
                 "The final Genus export timed out. The chip replay uses the mapped weight loader "
                 "and ingress, the source projection sequencer, and timed compiler memory models.",
    }


if __name__ == "__main__":
    assert __debug__, "run verification with assertions enabled"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    if args.replay:
        for path, contents in linked_inputs().items():
            path.write_bytes(contents)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda case: replay(WORK / "bundle.sv", case), CASES))
    result = verify()
    if args.record:
        args.record.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("Verified the recovered mapped scheduler against all six timed-memory test cases.")
