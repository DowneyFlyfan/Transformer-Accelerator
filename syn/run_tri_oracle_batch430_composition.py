"""Feed complete natively projected head caches into the shared attention engine."""

from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from run_tri_oracle_batch426_attention import CORE_SOURCES, packed
from run_tri_oracle_batch427_attention import LAYER, PEERS
from run_tri_oracle_batch429_qkv import packed_shifts, write_words
from tri_oracle_process_guard import terminate_process_group


ROOT=Path(__file__).resolve().parents[1]
TOP="tri_oracle_attention430_tb"
HEADS=(0,32,36)
SLOTS=409
SEED_SLOTS=400
SHARDS=25


def main():
    check_memory(15*GIB)
    records=ROOT/"records"
    capture=ROOT/".cache/model_reference/batch430"
    input_path=capture/"reference.json"
    reference=json.loads(input_path.read_text())
    assert tuple(reference["head_ids"])==HEADS and len(reference["original_positions"])==SLOTS
    assert reference["prompt_slots"]==408 and reference["rows"][-1]["rank"]==408
    compact_path=records/"batch422_compact_decoder_result.json"
    compact=json.loads(compact_path.read_text())
    native_dir=Path(compact["native_fixture"])
    mode=compact["native_fixture_modes"].index("compact_and_streaming")
    prior=records/"batch429_qkv_result.json"
    previous=json.loads(prior.read_text())
    context_path=records/"batch428_attention_context_result.json"
    context=json.loads(context_path.read_text())
    assert reference["question"]==previous["question"]==context["question"]
    sources=[ROOT/"verilog"/f"{name}.sv" for name in (
        LAYER,*[f"tri_oracle_{peer}" for peer in PEERS],"tri_oracle_qkv429","tri_oracle_qkv_store430",
        "tri_oracle_attention_pipeline430",TOP)]
    cores=[ROOT/"verilog"/f"tri_oracle_{name}.sv" for name in CORE_SOURCES]
    models=[Path(path) for path in previous["inputs_sha256"] if "/VERILOG/" in path and path.endswith(".v")]
    assert len(models)==3
    digests=reference["source_sha256"].copy()
    for path in (*cores,*models,*sources):
        digest=sha256(path)
        for record in (previous,context):
            assert record["inputs_sha256"].get(str(path),digest)==digest
        digests[str(path)]=digest
    for path in (input_path,prior,context_path,Path(__file__),ROOT/"syn/tri_oracle_process_guard.py"):
        digests[str(path)]=sha256(path)
    digests.update({str(capture/name):digest for name,digest in reference["fixture_sha256"].items()})
    assert all(sha256(Path(path))==digest for path,digest in digests.items())
    output=records/"batch430_attention_composition_result.json"
    archive=records/"batch430_attention_composition_logs.json.gz"
    assert not output.exists() and not archive.exists()
    cpus=sorted(os.sched_getaffinity(0))
    assert cpus

    def run(work,fixture,name,shard,integrated,cpu,corrupt=False):
        check_memory(9*GIB)
        folder=work/name
        folder.mkdir()
        selected=list(sources)
        if corrupt:
            index=next(i for i,path in enumerate(selected) if path.stem=="tri_oracle_qkv_store430")
            source=selected[index]
            text=source.read_text()
            expression="base+64'({expected_head,slot,6'b0})"
            assert text.count(expression)==1
            selected[index]=folder/source.name
            selected[index].write_text(text.replace(expression,expression+"+64'd64"))
        bundle=folder/"bundle.sv"
        bundle.write_text('`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'+
                          "".join(f'`include "{path}"\n' for path in (*cores,*models,*selected)))
        dump=folder/"dump.hex"
        command=["taskset","-c",str(cpu),"/opt/cadence/bin/xrun","-64bit","-sv","-xmerror","RECOME","-notimingchecks",
                 "-top",TOP,"-top","tri_oracle_batch357_hierarchy","-defparam",f"{TOP}.SHARD={shard}",
                 "-defparam",f"{TOP}.INTEGRATE={int(integrated)}",str(bundle),f"+FIXTURE={fixture}",f"+DUMP={dump}"]
        native_log=folder/"console.log"
        start=time.monotonic()
        with native_log.open("x") as stream:
            worker=subprocess.Popen(command,cwd=folder,stdout=stream,stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL,start_new_session=True)
            print(f"BATCH430_STARTED {name} pid={worker.pid} cpu={cpu}",flush=True)
            try:
                while worker.poll() is None:
                    check_memory(8*GIB)
                    assert time.monotonic()-start<900,name
                    time.sleep(1)
            finally:
                terminate_process_group(worker)
        log=native_log.read_text()
        assert log.splitlines().count("BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600")==1,log[-4000:]
        if corrupt:
            marker="COMPOSE430_WRITE group=0 slot=0"
            assert worker.returncode!=0 and log.splitlines().count(marker)==1 and not dump.exists(),log[-4000:]
        else:
            assert worker.returncode==0 and not re.search(r"\*(?:E|F),",log),log[-4000:]
            pattern=(r"^COMPOSE430_PASS maps=576 writes=27 failed_writes=2 rows=4 values=1023 "
                     r"attention_reads=([1-9][0-9]*) stalls=([1-9][0-9]*)$" if integrated else
                     rf"^COMPOSE430_SHARD_PASS shard={shard} writes=48 stalls=([1-9][0-9]*)$")
            match=re.search(pattern,log,re.M)
            assert match,log[-4000:]
            marker=match.group(0)
        print(f"BATCH430_CHECKED {name} {marker}",flush=True)
        evidence=dict(status=worker.returncode,marker=marker,log_sha256=sha256(native_log),
                      elapsed_seconds=time.monotonic()-start)
        if dump.exists():
            evidence["dump_sha256"]=sha256(dump)
        return name,evidence,log,dump

    with tempfile.TemporaryDirectory(dir=ROOT/".cache",prefix="batch430_native_") as folder:
        work=Path(folder)
        fixture=work/"fixture"
        fixture.mkdir()
        for name,size in (("activation",8),("cos",64),("sin",64),("expected",64)):
            write_words(fixture/f"{name}.hex",(capture/f"{name}.bin").read_bytes(),size)
        weights=(ROOT/".cache/model_reference/batch429/weights.bin").read_bytes()
        stride=64*2048
        write_words(fixture/"weights.hex",b"".join(weights[head*stride:(head+1)*stride] for head in HEADS),8)
        (fixture/"shifts.hex").write_text(packed_shifts(reference["shifts"],40))
        with (fixture/"biases.hex").open("x") as stream:
            assert all(0<=bias<64 for bias in reference["shift_biases"])
            stream.writelines(f"{bias:02x}\n" for bias in reference["shift_biases"])
        for name in ("map","signs"):
            text=(native_dir/f"{name}_{mode}.hex").read_text().splitlines()[:576]
            (fixture/f"{name}.hex").write_text("\n".join(text)+"\n")
        with (fixture/"rows.txt").open("x") as stream:
            stream.write(f"{reference['image_start']} {reference['alpha']} {reference['score_shift']} "
                         f"{reference['head_inner']} {reference['head_recent']} {int(reference['head_streaming'])}\n")
            for row in reference["rows"]:
                stream.write(f"{row['rank']} {row['position']} {row['visible']} {packed(row['output'],32)}\n")
        fixture_digests={path.name:sha256(path) for path in fixture.iterdir()}

        with ThreadPoolExecutor(max_workers=min(len(cpus),SHARDS+1)) as pool:
            pending=[pool.submit(run,work,fixture,f"shard_{shard:02}",shard,False,cpus[shard%len(cpus)])
                     for shard in range(SHARDS)]
            mutation=pool.submit(run,work,fixture,"wrong_write_slot",0,False,cpus[SHARDS%len(cpus)],True)
            completed=[future.result() for future in pending]
            completed.append(mutation.result())

        expected=(fixture/"expected.hex").read_text().splitlines()
        exported=[[] for _ in HEADS]
        for shard,(name,evidence,_,dump) in enumerate(completed[:SHARDS]):
            assert name==f"shard_{shard:02}" and sha256(dump)==evidence["dump_sha256"]
            lines=dump.read_text().splitlines()
            assert len(lines)==3*16
            for group in range(3):
                start=group*SLOTS+shard*16
                segment=lines[group*16:(group+1)*16]
                assert segment==expected[start:start+16]
                exported[group].extend(segment)
        seed_digests={}
        for group,lines in enumerate(exported):
            assert len(lines)==SEED_SLOTS
            path=fixture/f"seed_{group}.hex"
            path.write_text("\n".join(lines)+"\n")
            seed_digests[path.name]=sha256(path)
        completed.append(run(work,fixture,"projection_to_attention",0,True,cpus[0]))
        assert all(sha256(fixture/name)==digest for name,digest in (fixture_digests|seed_digests).items())

    assert not work.exists() and all(sha256(Path(path))==digest for path,digest in digests.items())
    logs={name:log for name,_,log,_ in completed}
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs,sort_keys=True).encode(),mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes()))==logs
    result=dict(state="trained_projection_cache_consumed_by_native_attention",question=reference["question"],
                trained_layer=0,query_head=0,key_value_group=0,prompt_slots=408,decode_slots=1,
                native_shard_cache_vectors=3*SEED_SLOTS,live_projection_vectors=27,
                projected_operand_bytes=3*SLOTS*64,attention_output_components=4*64,
                attention_value_reads=1023,head_prediction_inner=reference["head_inner"],
                head_prediction_recent=reference["head_recent"],head_streaming=reference["head_streaming"],
                rows=[{"original_position":row["position"],"visible_keys":row["visible"]} for row in reference["rows"]],
                projection_and_attention_share_tensor_owner=True,failed_write_retry_verified=True,
                normalized_activations_and_rotary_angles_supplied=True,paper_results_matched=False,
                inputs_sha256=digests,fixture_sha256=fixture_digests,native_seed_sha256=seed_digests,
                native_logs_sha256=sha256(archive),runs={name:entry for name,entry,_,_ in completed})
    with output.open("x") as stream:
        stream.write(json.dumps(result,indent=2)+"\n")
    print("BATCH430_VERIFIED projection_vectors=1227 prompt=408 decode=1 attention_outputs=256")


if __name__=="__main__":
    main()
