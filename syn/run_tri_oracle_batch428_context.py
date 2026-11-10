"""Verify macro-backed layer restoration in chronological trained attention."""

from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import re
import subprocess
import tempfile

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from run_tri_oracle_batch426_attention import CORE_SOURCES
from run_tri_oracle_batch427_attention import LAYER, PEERS, ROOT, TOP, prepare_vectors
from tri_oracle_process_guard import terminate_process_group


CONTEXT = "tri_oracle_attention_context428"
UNIT = f"{CONTEXT}_tb"
LEGACY_HIERARCHY = "BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600"
PERSISTENT_HIERARCHY = "CTX428_ACTUAL_HIERARCHY cores=20 clusters=5 compute_memories=600 context_memories=4"


def main():
    check_memory(15*GIB)
    records = ROOT/"records"
    prior_path = records/"batch427_attention_layer_result.json"
    prior = json.loads(prior_path.read_text())
    assert prior["state"]=="live_merge_and_head_prediction_through_trained_attention_rows"
    operand_path = ROOT/".cache/model_reference/batch426/operands.json"
    head_path = ROOT/".cache/model_reference/batch427/heads.json"
    operands = json.loads(operand_path.read_text())
    heads = json.loads(head_path.read_text())
    assert operands["question"]==heads["question"]==prior["question"]
    assert len(operands["maps"])==22 and len(operands["cases"])==25 and len(heads["heads"])==5
    compact = json.loads((records/"batch422_compact_decoder_result.json").read_text())
    mode = compact["native_fixture_modes"].index("compact_and_streaming")
    native_fixture = Path(compact["native_fixture"])
    inputs = {name:native_fixture/f"{name}_{mode}.hex" for name in ("map","signs")}
    source, bench, unit = [ROOT/"verilog"/f"{name}.sv" for name in (LAYER,TOP,UNIT)]
    peers = [ROOT/"verilog"/f"tri_oracle_{name}.sv" for name in PEERS]
    context = ROOT/"verilog"/f"{CONTEXT}.sv"
    cores = [ROOT/"verilog"/f"tri_oracle_{name}.sv" for name in CORE_SOURCES]
    models = [Path(path) for path in prior["inputs_sha256"] if "/VERILOG/" in path and path.endswith(".v")]
    assert len(models)==3
    context_model = next(path for path in models if "512x64" in path.name)
    replaced = {str(source),str(bench),str(ROOT/"syn/run_tri_oracle_batch427_attention.py")}
    digests = {path:digest for path,digest in prior["inputs_sha256"].items() if path not in replaced}
    for path in (prior_path,source,bench,context,unit,Path(__file__),ROOT/"syn/run_tri_oracle_batch427_attention.py"):
        digests[str(path)] = sha256(path)
    assert all(sha256(Path(path))==digest for path,digest in digests.items())
    report_path = records/"batch428_attention_context_result.json"
    archive_path = records/"batch428_attention_context_logs.json.gz"
    assert not report_path.exists() and not archive_path.exists()

    prefill_rows = sum(row["prefill"] for row in operands["cases"])
    decode_rows = len(operands["cases"])-prefill_rows
    signs = 576+sum(origin==index for mapping in operands["maps"][:-1] for index,origin in enumerate(mapping))
    scores = sum(len(row["selected"]) for row in operands["cases"])
    marker = (f"CTX428_ATTENTION_PASS frames=22 maps=12672 signs={signs} restores=26 heads=5 streaming=2 "
              f"rows=25 scores={scores} frame_errors=2 restore_errors=3 head_errors=1 row_errors=3")
    wrong_origin = next(index for index,(left,right) in
                        enumerate(zip(operands["maps"][0],operands["maps"][10],strict=True)) if left!=right)
    cases = {
        "memory": ("CTX428_PASS saved=12707 restored=12672 writes=1985 reads=1980 stalls=1320",None),
        "persistent": (marker,None),
        "legacy": (prior["runs"]["layer_00"]["marker"],None),
        "wrong_layer_address": (f"CTX428_RESTORED_MAP layer=0 index={wrong_origin}",
                                (".layer(restore_start ? restore_layer : frame_layer)",
                                 ".layer(restore_start ? next_merge_layer-5'd1 : frame_layer)")),
        "drop_restored_heads": ("LAYER427_ROW_INVENTORY row=20",
                                ("known_heads <= stored_known[resident_layer];","known_heads <= 0;")),
    }

    def simulate(work, name, expected, mutant, fixture):
        check_memory(10*GIB)
        folder = work/name
        folder.mkdir()
        rtl = source
        if mutant is not None:
            rtl = folder/source.name
            before,after = mutant
            original = source.read_text()
            assert original.count(before)==1
            rtl.write_text(original.replace(before,after))
        bundle = folder/"bundle.sv"
        if name=="memory":
            paths, top = (context,unit,context_model), UNIT
            options = []
        else:
            observer = cores[-1]
            if name!="legacy":
                original = observer.read_text()
                assert original.count("activations!=40")==original.count(LEGACY_HIERARCHY)==1
                observer = folder/observer.name
                observer.write_text(original.replace("activations!=40","activations!=44")
                                    .replace(LEGACY_HIERARCHY,PERSISTENT_HIERARCHY))
            paths, top = (*cores[:-1],observer,*models,*peers,rtl,bench), TOP
            options = ["-top","tri_oracle_batch357_hierarchy",
                       "-defparam",f"{TOP}.PERSIST_LAYER_CONTEXT={int(name!='legacy')}",f"+FIXTURE={fixture}"]
        bundle.write_text('`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n' +
                          "".join(f'`include "{path}"\n' for path in paths))
        command = ["/opt/cadence/bin/xrun","-64bit","-sv","-xmerror","RECOME","-notimingchecks","-top",top,
                   *options,str(bundle)]
        native_log = folder/"console.log"
        with native_log.open("x") as stream:
            worker = subprocess.Popen(command,cwd=folder,stdout=stream,stderr=subprocess.STDOUT,
                                      stdin=subprocess.DEVNULL,start_new_session=True)
            print(f"BATCH428_STARTED case={name} pid={worker.pid}",flush=True)
            try:
                status = worker.wait(timeout=540)
            finally:
                terminate_process_group(worker)
        log = native_log.read_text()
        assert log.splitlines().count(expected)==1, log[-4000:]
        if name!="memory":
            hierarchy = LEGACY_HIERARCHY if name=="legacy" else PERSISTENT_HIERARCHY
            assert log.splitlines().count(hierarchy)==1
        if mutant is None:
            assert status==0 and not re.search(r"\*(?:E|F),",log), log[-4000:]
        else:
            assert status!=0 and "CTX428_ATTENTION_PASS" not in log, log[-4000:]
        print(f"BATCH428_CHECKED case={name} {expected}",flush=True)
        return name,dict(status=status,marker=expected,log_sha256=sha256(native_log)),log

    with tempfile.TemporaryDirectory(dir=ROOT/".cache",prefix="batch428_native_") as folder:
        work = Path(folder)
        fixture = work/"fixture"
        fixture.mkdir()
        for name,path in inputs.items():
            (fixture/f"{name}.hex").symlink_to(path)
        for layer in range(22):
            group_heads = [head for head in heads["heads"] if head["layer"]==layer]
            group_rows = [(i,row) for i,row in enumerate(operands["cases"]) if row["layer"]==layer]
            for stage in ("prefill","decode"):
                staged = fixture/f"{stage}_{layer}"
                staged.mkdir()
                prepare_vectors(staged, group_heads if stage=="prefill" else [],
                                [(i,row) for i,row in group_rows if row["prefill"]==(stage=="prefill")])
                if stage=="prefill":
                    (staged/"heads.txt").rename(fixture/f"heads_{layer}.txt")
                (staged/"rows.txt").rename(fixture/f"{stage}_{layer}.txt")
        prepare_vectors(fixture,[head for head in heads["heads"] if head["layer"]==0],
                        [(i,row) for i,row in enumerate(operands["cases"]) if row["layer"]==0])
        vector_digests = {str(path.relative_to(fixture)):sha256(path) for path in fixture.glob("*.txt")}
        with ThreadPoolExecutor(max_workers=len(cases)) as pool:
            jobs = [pool.submit(simulate,work,name,expected,mutant,fixture) for name,(expected,mutant) in cases.items()]
            runs = [job.result() for job in jobs]
        assert all(sha256(fixture/name)==digest for name,digest in vector_digests.items())
    assert not work.exists() and all(sha256(Path(path))==digest for path,digest in digests.items())
    logs = {name:log for name,_,log in runs}
    with archive_path.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs,sort_keys=True).encode(),mtime=0))
    assert json.loads(gzip.decompress(archive_path.read_bytes()))==logs
    report = dict(state="macro_backed_layer_restore_through_trained_attention",question=prior["question"],
                  layer_maps=22,map_entries=12672,restore_transactions=26,restored_entries=26*576,
                  prompt_rows=prefill_rows,decode_rows=decode_rows,heads=5,attention_scores=scores,
                  attention_value_components=25*64,map_words_used=1980,map_payload_bytes=126720//8,
                  installed_context_macros=4,context_macro_capacity_bytes=4*512*64//8,
                  per_layer_head_flags_and_frame_geometry_bits=22*85,
                  cores=20,compute_memory_models=600,compact_operands_supplied=True,
                  full_paper_results_matched=False,inputs_sha256=digests,fixture_sha256=vector_digests,
                  native_logs_sha256=sha256(archive_path),runs={name:details for name,details,_ in runs})
    with report_path.open("x") as stream:
        stream.write(json.dumps(report,indent=2)+"\n")
    print("BATCH428_VERIFIED layers=22 restores=26 prompt=20 decode=5 components=1600")


if __name__=="__main__":
    main()
