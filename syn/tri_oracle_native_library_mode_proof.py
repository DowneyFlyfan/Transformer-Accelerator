"""Compare actual library models in native zero-delay Icarus simulation.

The structural audit is recomputed first. An intentionally inverted buffer
must fail the same checker before the unmodified models can qualify. This is
a small cell-model experiment, never a chip functionality or timing proof.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import resource
import subprocess
import tempfile
import time

from tri_oracle_library_mode import _graph, _library, audit_library_modes


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument("proof", type=Path)
    args = parser.parse_args()
    audit = json.loads(args.audit.read_text())
    library = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140.v")
    validator = Path("syn/tri_oracle_library_mode.py")
    netlist = Path(audit["netlist"])
    log_path = args.proof.with_suffix(".log")
    input_paths = (args.audit, library, validator, netlist, Path(__file__))
    outputs = {args.proof.resolve(), log_path.resolve()}
    if len(outputs) != 2 or outputs & {path.resolve() for path in input_paths}:
        raise ValueError("Proof output paths must be distinct from one another and every input")
    if any(path.exists() or path.is_symlink() for path in (args.proof, log_path)):
        raise ValueError("Proof output or log already exists; refusing to overwrite evidence")
    available = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                         if line.startswith("MemAvailable:"))) * 1024
    anonymous = int(dict(line.split() for line in Path("/sys/fs/cgroup/memory.stat").read_text().splitlines())["anon"])
    if available < 6 * 1024**3 or anonymous + 1024**3 >= 18 * 1024**3:
        raise ValueError("Insufficient headroom for the bounded cell-model proof")
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    started = time.monotonic()
    pinned = {str(path): digest(path) for path in input_paths}
    if audit["library_sha256"] != digest(library) or audit["validator_sha256"] != digest(validator) or audit["netlist_sha256"] != digest(netlist):
        raise ValueError("The structural audit does not bind the current sources")
    counts = {name: item["instances"] for name, item in audit["cells"].items()}
    log = []
    with tempfile.TemporaryDirectory(prefix="native_library_mode_", dir=".cache") as directory:
        root = Path(directory)
        sources = []
        for name, flags in (("default", []), ("functional", ["-DTETRAMAX"])):
            path = root / (name + ".v")
            subprocess.run(["iverilog", "-g2012", "-E", *flags, "-o", str(path), str(library)], check=True)
            sources.append(path.read_text())
        calculated = audit_library_modes(*sources, counts)
        if calculated != {key: audit[key] for key in calculated}:
            raise ValueError("Recomputed structural obligations differ from the supplied audit")
        gold, primitives, _ = _library(sources[0])
        functional, _, _ = _library(sources[1])
        # Bind coverage to the actual scalar native-export declarations, not
        # merely to cell names asserted by an otherwise hash-matching audit.
        # Consume complete supported scalar statements regardless of line or
        # attribute placement. Strings/comments/escaped identifiers are lexer
        # tokens, so text inside them cannot masquerade as an instantiation.
        lexer = re.compile(
            r'(?P<comment>/\*.*?\*/|//[^\n]*)|(?P<string>"(?:\\.|[^"\\])*")|'
            r'\\[^\s]+|[A-Za-z_][A-Za-z_0-9$]*|[^\s]', re.S)
        tokens = (match[0] for match in lexer.finditer(netlist.read_text())
                  if match.lastgroup not in {"comment", "string"})
        actual_counts = collections.Counter()
        for kind in tokens:
            if kind.startswith("\\"):
                kind = kind[1:]
            if kind not in gold:
                continue
            instance = next(tokens, "")
            if not re.fullmatch(r"\\\S+|[A-Za-z_][A-Za-z_0-9$]*", instance) or next(tokens, "") != "(":
                raise ValueError("Unsupported used-model inventory declaration for " + kind)
            depth = 1
            while depth:
                token = next(tokens, None)
                if token is None:
                    raise ValueError("Truncated used-model inventory declaration")
                if token == "(": depth += 1
                elif token == ")": depth -= 1
            if next(tokens, "") != ";":
                raise ValueError("Unsupported used-model inventory statement suffix")
            actual_counts[kind] += 1
        if actual_counts != counts:
            raise ValueError("Actual used-model inventory differs from the supplied structural audit")
        inputs, outputs = {}, {}
        for name in counts:
            ports, body = functional[name]
            interface = _graph(functional[name], primitives)["signature"][0]
            input_names = {pin for pin, kinds in interface if "input" in kinds}
            output_names = {pin for pin, kinds in interface if "output" in kinds}
            if input_names | output_names != set(ports):
                raise ValueError("Unsupported model port declarations: " + name)
            inputs[name] = [pin for pin in ports if pin in input_names]
            outputs[name] = [pin for pin in ports if pin in output_names]
        maximum_inputs = max(map(len, inputs.values()))
        if not 1 <= maximum_inputs <= 8:
            raise ValueError("Four-state enumeration exceeds the bounded experiment")
        symbols = set(counts) | primitives.keys()
        tokens = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in sorted(symbols, key=len, reverse=True)) + r")\b")

        def renamed(text, prefix):
            return tokens.sub(lambda match: prefix + match[0], text)

        def models(mutant):
            chunks = ["`timescale 1ns/1ps\n"]
            for prefix, definitions in (("GOLD_", gold), ("FUNC_", functional)):
                chunks.extend(renamed(item[0], prefix) + "\n" for item in primitives.values())
                for name in sorted(counts):
                    ports, body = definitions[name]
                    if mutant and prefix == "FUNC_" and name == "CKBD1BWP12T40P140":
                        body, changed = re.subn(r"\bbuf\b", "not", body, count=1)
                        if changed != 1:
                            raise ValueError("The negative control did not change the actual buffer primitive")
                    chunks.append(renamed("module " + name + "(" + ",".join(ports) + ");" + body + "endmodule\n", prefix))
            return "".join(chunks)

        compared = [name for name in sorted(counts) if outputs[name]]
        if "CKBD1BWP12T40P140" not in compared:
            raise ValueError("The used-model set lacks the required negative-control buffer")
        bench = ["`timescale 1ns/1ps", "module library_mode_tb;",
                 f"reg [{maximum_inputs - 1}:0] stimulus;",
                 "integer pattern, pin, base; integer comparisons=0; integer samples=0;"]
        for index, name in enumerate(compared):
            width = len(outputs[name])
            bench += [f"wire [{width - 1}:0] gold_{index}, func_{index};", f"reg known_{index}=0;"]
            for prefix, output_prefix in (("GOLD_", "gold"), ("FUNC_", "func")):
                connections = [f".{pin}(stimulus[{i}])" for i, pin in enumerate(inputs[name])]
                connections += [f".{pin}({output_prefix}_{index}[{i}])" for i, pin in enumerate(outputs[name])]
                bench.append(f"{prefix}{name} {output_prefix}_model_{index}(" + ",".join(connections) + ");")
        bench += ["task compare; begin", "samples=samples+1;"]
        for index, name in enumerate(compared):
            bench += [f'if(gold_{index} !== func_{index}) $fatal(1,"NATIVE_MODE_MISMATCH {name}");',
                      f"if((^gold_{index}) !== 1'bx) known_{index}=1;", "comparisons=comparisons+1;"]
        bench += ["end endtask", "initial begin",
                  "for(base=0;base<2;base=base+1) begin",
                  "stimulus=base ? '1 : '0; #1; compare;",
                  f"for(pin=0;pin<{maximum_inputs};pin=pin+1) begin",
                  "stimulus=base ? '1 : '0; stimulus[pin]=0; #1; compare;",
                  "stimulus[pin]=1; #1; compare; stimulus[pin]=0; #1; compare; end end",
                  f"for(pattern=0;pattern<{4**maximum_inputs};pattern=pattern+1) begin",
                  f"for(pin=0;pin<{maximum_inputs};pin=pin+1) begin",
                  "case((pattern>>(2*pin))&3) 0:stimulus[pin]=0; 1:stimulus[pin]=1; 2:stimulus[pin]=1'bx; 3:stimulus[pin]=1'bz; endcase end",
                  "#1; compare; end"]
        for index, name in enumerate(compared):
            bench.append(f'if(!known_{index}) $fatal(1,"NO_KNOWN_OUTPUT {name}");')
        bench += [f'$display("NATIVE_MODE_PASS models={len(compared)} samples=%0d comparisons=%0d",samples,comparisons);', "$finish; end endmodule"]
        bench_path = root / "bench.sv"
        bench_path.write_text("\n".join(bench) + "\n")
        samples = comparisons = None
        for mutant in (True, False):
            model_path = root / ("mutant.v" if mutant else "models.v")
            model_path.write_text(models(mutant))
            binary = root / "proof.vvp"
            compile_result = subprocess.run(["iverilog", "-g2012", "-gno-specify", "-s", "library_mode_tb", "-o", str(binary), str(model_path), str(bench_path)], text=True, capture_output=True)
            log += ["MUTANT" if mutant else "UNMODIFIED", compile_result.stdout, compile_result.stderr]
            if compile_result.returncode:
                raise ValueError("Native model compilation failed: " + compile_result.stderr)
            run = subprocess.run(["vvp", str(binary)], text=True, capture_output=True)
            log += [run.stdout, run.stderr]
            if mutant:
                if run.returncode == 0 or "NATIVE_MODE_MISMATCH CKBD1BWP12T40P140" not in run.stdout:
                    raise ValueError("Native negative control was not rejected by the functional comparator")
            else:
                marker = re.search(r"^NATIVE_MODE_PASS models=(\d+) samples=(\d+) comparisons=(\d+)$", run.stdout, re.M)
                if run.returncode or not marker or int(marker[1]) != len(compared):
                    raise ValueError("Unmodified native model comparison/known-output coverage failed: " + run.stdout + run.stderr)
                samples, comparisons = int(marker[2]), int(marker[3])
                if comparisons != samples * len(compared):
                    raise ValueError("Native comparison accounting differs from the model inventory")
        bench_sha256 = digest(bench_path)
    for name, expected in pinned.items():
        if digest(name) != expected:
            raise ValueError("Proof input changed during execution: " + name)
    with log_path.open("x") as file:
        file.write("\n".join(log))
    result = {
        "scope": "All used scalar cell models compared in native zero-delay Icarus. Not a chip functional or delay-annotated timing proof.",
        "comparison_passed": True, "cell_types": len(counts), "cell_types_with_outputs": len(compared),
        "maximum_input_pins": maximum_inputs, "four_state_input_patterns": 4**maximum_inputs,
        "settled_edge_warmup_samples": samples - 4**maximum_inputs, "output_vector_comparisons": comparisons,
        "every_output_model_produced_known_outputs": True, "wrong_functional_primitive_mutant_rejected": True,
        "structural_audit_sha256": pinned[str(args.audit)], "library_sha256": pinned[str(library)],
        "validator_sha256": pinned[str(validator)], "generator_sha256": pinned[str(Path(__file__))],
        "bench_sha256": bench_sha256, "elapsed_seconds": time.monotonic() - started,
        "peak_self_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "peak_children_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        "temporary_directory_removed": True, "full_core_simulation_passed": False,
    }
    with args.proof.open("x") as file:
        file.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
