"""Verify live token merging and head prediction through trained attention rows."""

from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import re
import subprocess
import tempfile

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from run_tri_oracle_batch426_attention import CORE_SOURCES, packed
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_attention427_layer_tb"
LAYER = "tri_oracle_attention_layer427"
PEERS = ("cumulative_token_merger423", "attention_head_predictor415", "attention_tile_batch413",
         "attention_head_classifier410", "attention_row426", "causal_token_size", "proportional_softmax")


def prepare_vectors(folder, heads, rows):
    with (folder/"heads.txt").open("x") as stream:
        for head in heads:
            stream.write(f"{head['head']} {len(head['keys'])} {head['alpha']} {head['inner']} "
                         f"{head['recent']} {int(head['streaming'])}\n")
            stream.writelines(vector+"\n" for vector in (*head["queries"], *head["keys"]))
    with (folder/"rows.txt").open("x") as stream:
        for index,row in rows:
            stream.write(f"{index} {row['head']} {len(row['keys_hex'])} {row['query_position']} "
                         f"{row['shift']} {len(row['selected'])}\n")
            stream.write(f"{row['query_hex']} {packed(row['result'],32)}\n")
            for key,value in zip(row["keys_hex"], row["values_hex"], strict=True):
                stream.write(f"{key} {value}\n")
            for rank,dot in zip(row["selected"], row["dots"], strict=True):
                stream.write(f"{rank:03x} {dot & 0xffffffff:08x}\n")


def main():
    check_memory(15*GIB)
    records = ROOT/"records"
    head_path = ROOT/".cache/model_reference/batch427/heads.json"
    row_path = ROOT/".cache/model_reference/batch426/operands.json"
    compact_path = records/"batch422_compact_decoder_result.json"
    backend_path = records/"batch393_literal_result.json"
    row_result_path = records/"batch426_attention_row_result.json"
    capture, operands, compact, backend, row_result = [json.loads(path.read_text()) for path in
        (head_path,row_path,compact_path,backend_path,row_result_path)]
    assert capture["question"]==operands["question"]==row_result["question"]
    assert sha256(row_path)==row_result["inputs_sha256"][str(row_path)]
    assert compact["local_ratio"]==[8,1] and compact["minimum_matching_signs"]==1536
    assert {row["image_start"] for row in operands["cases"]}=={5}
    trace = Path(compact["native_fixture"])
    mode = compact["native_fixture_modes"].index("compact_and_streaming")
    fixtures = {name: trace/f"{name}_{mode}.hex" for name in ("map","signs")}
    for path in fixtures.values():
        assert sha256(path)==compact["native_fixture_sha256"][str(path)]
    source, bench, *peers = [ROOT/"verilog"/f"{name}.sv" for name in
        (LAYER,TOP,*(f"tri_oracle_{peer}" for peer in PEERS))]
    cores = [ROOT/"verilog"/f"tri_oracle_{name}.sv" for name in CORE_SOURCES]
    models = [Path(path) for path in backend["source_sha256"] if "/VERILOG/" in path and path.endswith(".v")]
    assert len(models)==3
    digests = capture["source_sha256"].copy()
    digests.update({str(path):backend["source_sha256"][str(path)] for path in (*cores,*models)})
    for path in (head_path,row_path,compact_path,backend_path,row_result_path,source,bench,*peers,*fixtures.values(),
                 Path(__file__),ROOT/"syn/tri_oracle_process_guard.py",ROOT/"syn/run_tri_oracle_batch426_attention.py"):
        digest=sha256(path)
        assert digests.get(str(path),digest)==digest
        assert row_result["inputs_sha256"].get(str(path),digest)==digest
        digests[str(path)]=digest
    assert all(sha256(Path(path))==digest for path,digest in digests.items())
    report_path=records/"batch427_attention_layer_result.json"
    archive_path=records/"batch427_attention_layer_logs.json.gz"
    assert not report_path.exists() and not archive_path.exists()
    groups = {layer:([head for head in capture["heads"] if head["layer"]==layer],
                      [(i,row) for i,row in enumerate(operands["cases"]) if row["layer"]==layer])
              for layer in (0,10,21)}
    assert sum(len(rows) for _,rows in groups.values())==25
    assert sum(len(heads) for heads,_ in groups.values())==5
    for heads,rows in groups.values():
        for _,row in rows:
            head=next(head for head in heads if head["head"]==row["head"])
            assert head["streaming"]==row["streaming"]
    signs_needed=[576]+[sum(origin==i for i,origin in enumerate(mapping)) for mapping in operands["maps"][:-1]]
    assert len(signs_needed)==22
    mutants={
        "ignore_head_type": (10, ".row_streaming(head_types[row_head])",
                             ".row_streaming(1'b0)", "LAYER427_KEY_READ row=10 address=0000000000020800"),
        "stale_head_cache": (0, "frame_failed <= 0;\n                    known_heads <= 0;",
                             "frame_failed <= 0;", "LAYER427_UNEXPECTED_READ"),
        "stale_image_map": (0, "frame_new_image || merge_sequence_valid ? frame_minimum_matches : 12'hfff",
                            "frame_minimum_matches", "LAYER427_REJECTED_FRAME_REQUESTED_SIGN layer=1"),
    }

    def simulate(work, name, layer, fixture, mutant=None):
        check_memory(10*GIB)
        directory=work/name
        directory.mkdir()
        selected=source
        if mutant is not None:
            before,after,_=mutant
            selected=directory/source.name
            original=source.read_text()
            assert original.count(before)==1
            selected.write_text(original.replace(before,after))
        bundle=directory/"bundle.sv"
        bundle.write_text('`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n' +
                         "".join(f'`include "{path}"\n' for path in (*cores,*models,*peers,selected,bench)))
        command=["/opt/cadence/bin/xrun","-64bit","-sv","-xmerror","RECOME","-notimingchecks",
                 "-top",TOP,"-top","tri_oracle_batch357_hierarchy","-defparam",f"{TOP}.TARGET_LAYER={layer}",
                 str(bundle),f"+FIXTURE={fixture}"]
        native_log=directory/"console.log"
        with native_log.open("x") as stream:
            worker=subprocess.Popen(command,cwd=directory,stdout=stream,stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL,start_new_session=True)
            print(f"BATCH427_STARTED case={name} pid={worker.pid}",flush=True)
            try:
                status=worker.wait(timeout=420)
            finally:
                terminate_process_group(worker)
        log=native_log.read_text()
        assert log.splitlines().count("BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600")==1, log[-4000:]
        if mutant is None:
            heads,rows=groups[layer]
            frames=layer+1+int(layer==0)
            scores=sum(len(row["selected"]) for _,row in rows)
            faults=int(layer==0)
            marker=(f"LAYER427_PASS frames={frames} maps={frames*576} signs={sum(signs_needed[:frames])} "
                    f"heads={len(heads)} streaming={sum(h['streaming'] for h in heads)} rows={len(rows)} scores={scores} "
                    f"frame_errors={4*faults} head_errors={faults} row_errors={faults}")
            assert status==0 and log.splitlines().count(marker)==1 and not re.search(r"\*(?:E|F),",log), log[-4000:]
        else:
            marker=mutant[2]
            assert status!=0 and log.splitlines().count(marker)==1 and "LAYER427_PASS" not in log, log[-4000:]
        print(f"BATCH427_CHECKED case={name} {marker}",flush=True)
        return name,dict(status=status,marker=marker,log_sha256=sha256(native_log)),log

    with tempfile.TemporaryDirectory(dir=ROOT/".cache",prefix="batch427_native_") as folder:
        work=Path(folder)
        lint=subprocess.run(["verilator","--lint-only","-Wall","-Wno-fatal","-Wno-PINCONNECTEMPTY",
                             "--top-module",LAYER,str(source),*map(str,peers)],cwd=work,
                            capture_output=True,text=True,timeout=30,check=True)
        assert not re.search(r"^%Warning.*tri_oracle_attention_layer427\.sv",lint.stderr,re.M),lint.stderr
        inputs={}
        for layer,(heads,rows) in groups.items():
            fixture=work/f"fixture_{layer}"
            fixture.mkdir()
            for name,path in fixtures.items():
                (fixture/f"{name}.hex").symlink_to(path)
            prepare_vectors(fixture,heads,rows)
            inputs[layer]=fixture
        vector_digests={str(layer):{name:sha256(fixture/name) for name in ("heads.txt","rows.txt")}
                        for layer,fixture in inputs.items()}
        with ThreadPoolExecutor(max_workers=6) as pool:
            jobs=[pool.submit(simulate,work,f"layer_{layer:02}",layer,fixture) for layer,fixture in inputs.items()]
            jobs.extend(pool.submit(simulate,work,name,layer,inputs[layer],(before,after,marker))
                        for name,(layer,before,after,marker) in mutants.items())
            runs=[job.result() for job in jobs]
        assert all(sha256(inputs[int(layer)]/name)==digest
                   for layer,entries in vector_digests.items() for name,digest in entries.items())
    assert not work.exists() and all(sha256(Path(path))==digest for path,digest in digests.items())
    logs={name:log for name,_,log in runs}|{"lint":lint.stdout+lint.stderr}
    with archive_path.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs,sort_keys=True).encode(),mtime=0))
    assert json.loads(gzip.decompress(archive_path.read_bytes()))==logs
    report=dict(state="live_merge_and_head_prediction_through_trained_attention_rows", question=capture["question"],
                unique_merge_frames=22, unique_map_entries=22*576, trained_heads=5,
                streaming_heads=sum(head["streaming"] for head in capture["heads"]), trained_attention_rows=25,
                trained_attention_scores=row_result["trained_scores"],
                trained_attention_value_components=row_result["trained_value_components"],
                head_decisions=[{key:head[key] for key in ("layer","head","alpha","inner","recent","streaming")}
                                for head in capture["heads"]],
                cores=20, compiled_memory_models=600, source_sign_vectors_from_caller=True,
                compact_operands_from_caller=True, resident_layer_only=True, full_paper_results_matched=False,
                inputs_sha256=digests, generated_vector_sha256=vector_digests, native_logs_sha256=sha256(archive_path),
                runs={name:details for name,details,_ in runs})
    with report_path.open("x") as stream:
        stream.write(json.dumps(report,indent=2)+"\n")
    print("BATCH427_VERIFIED maps=12672 heads=5 rows=25 outputs=1600")


if __name__=="__main__":
    main()
