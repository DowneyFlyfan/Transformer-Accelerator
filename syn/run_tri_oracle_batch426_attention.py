"""Verify native compact attention from dot products through signed weighted values."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import re
import subprocess
import tempfile

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from run_tri_oracle_batch425_softmax import fixed_probabilities
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_attention426_row_tb"
ROW = "tri_oracle_attention_row426"
CORE_SOURCES = ("pe_array", "sram_memory_compute", "sram_compute_cluster", "compute_fabric",
                "batched_projection356", "batched_tensor390", "batch357_hierarchy")


def packed(values, bits):
    return "".join(f"{value & ((1 << bits) - 1):0{bits//4}x}" for value in reversed(values))


def boundary(image_start, origins, position, streaming, shift):
    """Stress the maximum compact and original sequence lengths and score scaling."""
    query = [1, -1, 3] + [0]*61
    keys = [[rank % 255-127, rank % 3-1, rank % 9-4] + [0]*61 for rank in range(1024)]
    values = [[(rank*5+feature*7) % 256-128 for feature in range(64)] for rank in range(1024)]
    image_prefix = origins[:max(0, position-image_start+1)]
    root_sizes = Counter(image_prefix)
    roots = sorted(set(origins))
    visible = min(image_start, position+1) + len(root_sizes) + max(0, position-image_start-575)
    selected = [*range(32), *range(visible-32, visible)] if streaming and visible > 64 else list(range(visible))
    dots = [sum(a*b for a,b in zip(query, keys[rank], strict=True)) for rank in selected]
    scores = [min(32767, max(-32768, round(dot * 2.0**shift))) for dot in dots]
    sizes = [root_sizes[roots[rank-image_start]] if image_start <= rank < image_start+len(roots) else 1
             for rank in selected]
    assert all(size > 0 for size in sizes)
    probabilities = fixed_probabilities(scores, sizes)
    result = [sum(prob*values[rank][feature] for rank,prob in zip(selected,probabilities,strict=True))
              for feature in range(64)]
    return dict(image_start=image_start, query_position=position, streaming=streaming, shift=shift,
                query_hex=packed(query,8), keys_hex=[packed(key,8) for key in keys],
                values_hex=[packed(vector,8) for vector in values], selected=selected, dots=dots,
                result=result, origins=origins)


def write_vectors(path, cases):
    with path.open("x") as stream:
        for row_id, case in cases:
            keys, values = case["keys_hex"], case["values_hex"]
            selected, dots = case["selected"], case["dots"]
            assert len(keys) == len(values) and len(selected) == len(dots)
            stream.write(f"{row_id} {case['image_start']} {len(keys)} {case['query_position']} "
                         f"{int(case['streaming'])} {case['shift']} {len(selected)}\n")
            stream.write(f"{case['query_hex']} {packed(case['result'],32)}\n")
            for origin in case["origins"]:
                stream.write(f"{origin:03x}\n")
            for key, vector in zip(keys, values, strict=True):
                stream.write(f"{key} {vector}\n")
            for rank, dot in zip(selected, dots, strict=True):
                stream.write(f"{rank:03x} {dot & 0xffffffff:08x}\n")


def main():
    check_memory(15*GIB)
    records = ROOT / "records"
    operand_path = ROOT / ".cache/model_reference/batch426/operands.json"
    captured = json.loads(operand_path.read_text())
    source = ROOT / "verilog" / f"{ROW}.sv"
    bench = ROOT / "verilog" / f"{TOP}.sv"
    sizes = ROOT / "verilog/tri_oracle_causal_token_size.sv"
    softmax = ROOT / "verilog/tri_oracle_proportional_softmax.sv"
    backend_path = records / "batch393_literal_result.json"
    backend = json.loads(backend_path.read_text())
    cores = [ROOT / "verilog" / f"tri_oracle_{name}.sv" for name in CORE_SOURCES]
    models = [Path(path) for path in backend["source_sha256"] if "/VERILOG/" in path and path.endswith(".v")]
    assert len(models) == 3
    digests = captured["source_sha256"].copy()
    digests.update({str(path): backend["source_sha256"][str(path)] for path in cores+models})
    for path in (operand_path, source, bench, sizes, softmax, backend_path, Path(__file__),
                 ROOT/"syn/tri_oracle_process_guard.py"):
        digests[str(path)] = sha256(path)
    assert all(sha256(Path(path)) == digest for path,digest in digests.items())
    report_path = records / "batch426_attention_row_result.json"
    logs_path = records / "batch426_attention_row_logs.json.gz"
    assert not report_path.exists() and not logs_path.exists()

    trained = [(index, case | {"origins": captured["maps"][case["layer"]]})
               for index,case in enumerate(captured["cases"])]
    assert len(trained) == 25
    groups = {f"layer_{layer:02}": [(i, case) for i,case in trained if case["layer"] == layer]
              for layer in (0,10,21)}
    groups["bounds"] = [(25, boundary(0, list(range(576)), 1023, False, 31)),
                        (26, boundary(1, [0]*576, 1598, True, -2)),
                        (27, boundary(3, [index-index%2 for index in range(576)], 283, True, -31))]
    wrong_index, wrong_case = next((index,case) for index,case in groups["layer_00"]
                                   if case["result"] != case["unit_size_result"])
    first_wrong_feature = next(index for index,(a,b) in enumerate(zip(wrong_case["result"],wrong_case["unit_size_result"]))
                               if a != b)
    multiplicity_failure = (f"ROW426_RESULT row={wrong_index} feature={first_wrong_feature} "
                            f"expected={wrong_case['result'][first_wrong_feature]} "
                            f"got={wrong_case['unit_size_result'][first_wrong_feature]}")
    streaming_index, streaming_case = next((index,case) for index,case in groups["layer_10"]
                                            if case["streaming"] and len(case["selected"]) == 64 and 32 not in case["selected"])
    assert len(streaming_case["selected"]) == 64
    streaming_failure = f"ROW426_SKIPPED_KEY_READ row={streaming_index} address={0x2000+32*64:016x}"
    mutants = {
        "ignore_multiplicity": ("layer_00", "? image_sizes[10'(send_rank-image_start)] : 10'd1;",
                                "? 10'd1 : 10'd1;", multiplicity_failure),
        "include_middle_key": ("layer_10", "selected_index >= WINDOW", "selected_index > WINDOW", streaming_failure),
        "abandon_bad_frame": ("layer_00", "(sizes_map_ready || sizes_error)", "sizes_map_ready", "ROW426_MAP index=1"),
    }

    def simulate(work, name, group, fixture, mutant=None):
        check_memory(10*GIB)
        run = work/name
        run.mkdir()
        selected = source
        if mutant is not None:
            before, after, _ = mutant
            text = source.read_text()
            assert text.count(before) == 1
            selected = run/source.name
            selected.write_text(text.replace(before, after))
        bundle = run/"bundle.sv"
        bundle.write_text('`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n' +
                          "".join(f'`include "{path}"\n' for path in (*cores,*models,sizes,softmax,selected,bench)))
        command = ["/opt/cadence/bin/xrun", "-64bit", "-sv", "-xmerror", "RECOME", "-notimingchecks",
                   "-top", TOP, "-top", "tri_oracle_batch357_hierarchy", str(bundle), f"+FIXTURE={fixture}"]
        log_path = run/"console.log"
        with log_path.open("x") as stream:
            process = subprocess.Popen(command, cwd=run, stdin=subprocess.DEVNULL, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            print(f"BATCH426_STARTED {name} pid={process.pid}", flush=True)
            try:
                status = process.wait(timeout=240)
            finally:
                terminate_process_group(process)
        log = log_path.read_text()
        hierarchy = "BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600"
        assert log.splitlines().count(hierarchy) == 1, log[-3500:]
        if mutant is None:
            count = sum(len(case["selected"]) for _,case in group)
            errors = 5 if group[0][0] == 0 else 0
            marker = f"ROW426_PASS rows={len(group)} scores={count} values={count} errors={errors} stalls={3*(len(group)+errors)}"
            assert status == 0 and log.splitlines().count(marker) == 1, log[-3500:]
            assert not re.search(r"\*(?:E|F),",log), log[-3500:]
        else:
            marker = mutant[2]
            assert status != 0 and log.count(marker) == 1 and "ROW426_PASS" not in log, log[-3500:]
        print(f"BATCH426_CHECKED {name} {marker}", flush=True)
        return name, dict(status=status, marker=marker, fixture_sha256=sha256(fixture), log_sha256=sha256(log_path)), log

    with tempfile.TemporaryDirectory(dir=ROOT/".cache", prefix="batch426_native_") as folder:
        work = Path(folder)
        lint = subprocess.run(["verilator", "--lint-only", "-Wall", "-Wno-fatal", "-Wno-PINCONNECTEMPTY",
                               "--top-module", ROW, str(source), str(sizes), str(softmax)],
                              cwd=work, capture_output=True, text=True, timeout=30, check=True)
        assert not re.search(r"^%Warning.*tri_oracle_attention_row426\.sv", lint.stderr, re.M), lint.stderr
        fixtures = {}
        for name, group in groups.items():
            fixtures[name] = work/f"{name}.txt"
            write_vectors(fixtures[name], group)
        with ThreadPoolExecutor(max_workers=6) as pool:
            jobs = [pool.submit(simulate, work,name,group,fixtures[name]) for name,group in groups.items()]
            jobs.extend(pool.submit(simulate, work,name,groups[group],fixtures[group],(before,after,marker))
                        for name,(group,before,after,marker) in mutants.items())
            runs = [job.result() for job in jobs]
    assert not work.exists() and all(sha256(Path(path)) == digest for path,digest in digests.items())
    logs = {name: log for name,_,log in runs} | {"lint":lint.stdout+lint.stderr}
    with logs_path.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs,sort_keys=True).encode(),mtime=0))
    assert json.loads(gzip.decompress(logs_path.read_bytes())) == logs
    report = dict(state="trained_compact_attention_rows_functionally_verified",
                  question=captured["question"], trained_rows=len(trained), boundary_rows=len(groups["bounds"]),
                  trained_scores=sum(len(case["selected"]) for _,case in trained),
                  trained_value_components=64*len(trained),
                  max_absolute_value_code_error=max(case["max_absolute_value_code_error"] for _,case in trained),
                  trained_row_inventory=[dict(row=i, layer=case["layer"], head=case["head"], prefill=case["prefill"],
                       original_query_position=case["query_position"], keys=len(case["keys_hex"]),
                       selected_keys=len(case["selected"]), streaming=case["streaming"],
                       value_exponent=case["value_exponent"]) for i,case in trained],
                  actual_cores=20, actual_compiled_memory_models=600, live_causal_sizes=True,
                  head_type_provided_by_caller=True, merge_map_provided_by_caller=True,
                  whole_model_mapped=False, paper_results_matched=False,
                  inputs_sha256=digests, native_logs_sha256=sha256(logs_path),
                  runs={name:details for name,details,_ in runs})
    with report_path.open("x") as stream:
        stream.write(json.dumps(report,indent=2)+"\n")
    print("BATCH426_VERIFIED", report["trained_rows"], report["trained_scores"], report["trained_value_components"])


if __name__ == "__main__":
    main()
