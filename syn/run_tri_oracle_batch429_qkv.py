"""Replay all trained query, key and value heads on the shared native tensor engine."""

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
from run_tri_oracle_batch426_attention import CORE_SOURCES
from tri_oracle_process_guard import terminate_process_group


ROOT=Path(__file__).resolve().parents[1]
TOP="tri_oracle_qkv429_tb"
FEATURES=2048
TOKENS=4
HEADS=40
HEAD_WIDTH=64
GROUPS=[(head,2) for head in range(0,30,2)]+[(30,3),(33,4),(37,3)]


def write_words(path,data,size):
    assert len(data)%size==0
    with path.open("x") as stream:
        stream.writelines(data[offset:offset+size][::-1].hex()+"\n" for offset in range(0,len(data),size))


def packed_shifts(values,count):
    assert len(values)<=count and all(0<=value<64 for value in values)
    word=sum(value<<(6*index) for index,value in enumerate(values))
    return f"{word:0{count*6//4}x}\n"


def main():
    check_memory(15*GIB)
    records=ROOT/"records"
    capture=ROOT/".cache/model_reference/batch429"
    manifest=capture/"reference.json"
    fixture=json.loads(manifest.read_text())
    assert fixture["heads"]==HEADS and fixture["tokens"]==TOKENS
    assert sorted(fixture["positions"])==fixture["positions"]
    assert fixture["positions"][0]==0 and fixture["positions"][-1]==fixture["positions"][-2]+1
    assert [head for first,count in GROUPS for head in range(first,first+count)]==list(range(HEADS))
    prior_path=records/"batch428_attention_context_result.json"
    prior=json.loads(prior_path.read_text())
    assert fixture["question"]==prior["question"] and prior["cores"]==20 and prior["compute_memory_models"]==600
    source=ROOT/"verilog/tri_oracle_qkv429.sv"
    bench=ROOT/"verilog"/f"{TOP}.sv"
    cores=[ROOT/"verilog"/f"tri_oracle_{name}.sv" for name in CORE_SOURCES]
    models=[Path(path) for path in prior["inputs_sha256"] if "/VERILOG/" in path and path.endswith(".v")]
    assert len(models)==3
    digests=fixture["source_sha256"]|{str(path):prior["inputs_sha256"][str(path)] for path in (*cores,*models)}
    digests.update({str(capture/name):digest for name,digest in fixture["fixture_sha256"].items()})
    for path in (source,bench,manifest,prior_path,Path(__file__),ROOT/"syn/tri_oracle_process_guard.py"):
        digests[str(path)]=sha256(path)
    assert all(sha256(Path(path))==digest for path,digest in digests.items())
    output=records/"batch429_qkv_result.json"
    archive=records/"batch429_qkv_logs.json.gz"
    assert not output.exists() and not archive.exists()
    weights=(capture/"weights.bin").read_bytes()
    expected=(capture/"expected.bin").read_bytes()
    dots=(capture/"dots.bin").read_bytes()
    assert len(weights)==HEADS*HEAD_WIDTH*FEATURES
    assert len(expected)==HEADS*HEAD_WIDTH*TOKENS and len(dots)==4*len(expected)
    run_cases=[(f"trained_{head:02}",head,count,False,False) for head,count in GROUPS]
    run_cases += [("fault_recovery",0,1,True,False),("wrong_rotary_sign",0,1,False,True)]
    cpus=sorted(os.sched_getaffinity(0))
    assert cpus

    def run(work,case,cpu):
        name,first,count,faults,mutant=case
        check_memory(10*GIB)
        folder=work/name
        folder.mkdir()
        selected=source
        if mutant:
            selected=folder/source.name
            before="upper_rotated = 49'(upper_cos)+49'(lower_sin)"
            text=source.read_text()
            assert text.count(before)==1
            selected.write_text(text.replace(before,before.replace("+","-")))
        write_words(folder/"weights.hex",weights[first*HEAD_WIDTH*FEATURES:(first+count)*HEAD_WIDTH*FEATURES],8)
        write_words(folder/"expected.hex",expected[first*HEAD_WIDTH*TOKENS:(first+count)*HEAD_WIDTH*TOKENS],64)
        write_words(folder/"dots.hex",dots[first*HEAD_WIDTH*TOKENS*4:(first+count)*HEAD_WIDTH*TOKENS*4],4)
        for shared in ("activation.hex","cos.hex","sin.hex","shifts.hex","shift_biases.hex"):
            (folder/shared).symlink_to(work/shared)
        bundle=folder/"bundle.sv"
        bundle.write_text('`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'+
                          "".join(f'`include "{path}"\n' for path in (*cores,*models,selected,bench)))
        command=["taskset","-c",str(cpu),"/opt/cadence/bin/xrun","-64bit","-sv","-xmerror","RECOME","-notimingchecks",
                 "-top",TOP,"-top","tri_oracle_batch357_hierarchy","-defparam",f"{TOP}.FIRST_HEAD={first}",
                 "-defparam",f"{TOP}.HEAD_COUNT={count}","-defparam",f"{TOP}.TEST_ERRORS={int(faults)}",
                 str(bundle),f"+FIXTURE={folder}"]
        native_log=folder/"console.log"
        start=time.monotonic()
        with native_log.open("x") as stream:
            worker=subprocess.Popen(command,cwd=folder,stdout=stream,stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL,start_new_session=True)
            print(f"BATCH429_STARTED case={name} pid={worker.pid} cpu={cpu}",flush=True)
            try:
                while worker.poll() is None:
                    check_memory(8*GIB)
                    assert time.monotonic()-start<900,name
                    time.sleep(1)
            finally:
                terminate_process_group(worker)
        log=native_log.read_text()
        assert log.splitlines().count("BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600")==1,log[-4000:]
        if mutant:
            marker="QKV429_VECTOR head=0 token=1"
            assert worker.returncode!=0 and log.splitlines().count(marker)==1 and "QKV429_PASS" not in log,log[-4000:]
        else:
            marker=(f"QKV429_PASS first={first} heads={count} vectors={count*TOKENS} "
                    f"faults={4 if faults else 0} stalls={2*count*TOKENS}")
            assert worker.returncode==0 and log.splitlines().count(marker)==1 and not re.search(r"\*(?:E|F),",log),log[-4000:]
        print(f"BATCH429_CHECKED {name} {marker}",flush=True)
        return name,dict(status=worker.returncode,first_head=first,head_count=count,marker=marker,
                         elapsed_seconds=time.monotonic()-start,log_sha256=sha256(native_log)),log

    lint=subprocess.run(["verilator","--lint-only","-Wall","--top-module",source.stem,str(source)],
                        cwd=ROOT,capture_output=True,text=True,timeout=30,check=True)
    with tempfile.TemporaryDirectory(dir=ROOT/".cache",prefix="batch429_native_") as folder:
        work=Path(folder)
        for name,size in (("activation",8),("cos",64),("sin",64)):
            write_words(work/f"{name}.hex",(capture/f"{name}.bin").read_bytes(),size)
        (work/"shifts.hex").write_text(packed_shifts(fixture["shifts"],40))
        (work/"shift_biases.hex").write_text(packed_shifts(fixture["shift_biases"],16))
        with ThreadPoolExecutor(max_workers=min(len(cpus),len(run_cases))) as pool:
            jobs=[pool.submit(run,work,case,cpus[index%len(cpus)]) for index,case in enumerate(run_cases)]
            completed=[job.result() for job in jobs]
    assert not work.exists() and all(sha256(Path(path))==digest for path,digest in digests.items())
    logs={name:log for name,_,log in completed}|{"lint":lint.stdout+lint.stderr}
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs,sort_keys=True).encode(),mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes()))==logs
    report=dict(state="trained_qkv_projection_and_rotation_verified",question=fixture["question"],
                original_positions=fixture["positions"],prompt_rows=3,decode_rows=1,
                query_heads=32,key_heads=4,value_heads=4,head_features=64,projection_input_features=FEATURES,
                raw_dot_comparisons=HEADS*HEAD_WIDTH*TOKENS,operand_byte_comparisons=HEADS*HEAD_WIDTH*TOKENS,
                hardware_cores_per_run=20,compute_memory_models_per_run=600,
                relative_error_by_head=fixture["relative_error_by_head"],value_error_sources=fixture["value_error_sources"],
                activation_exponents=fixture["activation_exponents"],output_exponents=fixture["output_exponents"],
                normalized_input_and_angles_supplied=True,attention_consumed_generated_vectors=False,
                paper_results_matched=False,inputs_sha256=digests,native_logs_sha256=sha256(archive),
                runs={name:entry for name,entry,_ in completed})
    with output.open("x") as stream:
        stream.write(json.dumps(report,indent=2)+"\n")
    print("BATCH429_VERIFIED heads=40 rows=4 raw_dots=10240 operand_bytes=10240")


if __name__=="__main__":
    main()
