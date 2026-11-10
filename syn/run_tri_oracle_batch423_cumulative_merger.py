"""Verify cumulative native token merging on both compact-decoder traces."""

from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import re
import subprocess
import tempfile

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_cumulative423_tb"
MODULE = "tri_oracle_cumulative_token_merger423"
TOKENS, LAYERS, FEATURES = 576, 22, 2048


def main():
    check_memory(14*GIB)
    records = ROOT / "records"
    receipt = records / "batch422_compact_decoder_result.json"
    prior = json.loads(receipt.read_text())
    assert prior["state"] == "cumulative_compact_decoder_pilot_scored" and prior["decode_replay_checks"] == 3
    assert prior["native_fixture_modes"] == ["compact", "compact_and_streaming"]
    fixture = Path(prior["native_fixture"])
    consumed = {str(fixture / f"{name}_{mode}.hex") for name in ("map", "signs") for mode in range(2)}
    assert consumed == set(prior["native_fixture_sha256"])
    module, causal, bench = [ROOT / "verilog" / f"{name}.sv" for name in
                            (MODULE, "tri_oracle_causal_token_size", TOP)]
    digests = prior["native_fixture_sha256"].copy()
    for path in (receipt, module, causal, bench, Path(__file__), ROOT / "syn/tri_oracle_process_guard.py",
                 ROOT / "syn/run_tri_oracle_batch396_masks.py"):
        digest = sha256(path)
        assert prior["source_sha256"].get(str(path),digest)==digest
        digests[str(path)] = digest
    assert all(sha256(Path(path))==digest for path,digest in digests.items())

    expected = dict(modes=2,layers=2*LAYERS,maps=2*LAYERS*TOKENS,signs=0,rows=2*LAYERS*(TOKENS+2),sizes=0,cfg_errors=3)
    control = None
    for mode in range(2):
        mapping = [int(line,16) for line in (fixture/f"map_{mode}.hex").read_text().splitlines()]
        signs = [int(line,16) for line in (fixture/f"signs_{mode}.hex").read_text().splitlines()]
        assert len(mapping)==len(signs)==LAYERS*TOKENS
        previous = list(range(TOKENS))
        roots_by_layer = []
        for layer in range(LAYERS):
            current = mapping[layer*TOKENS:(layer+1)*TOKENS]
            previous_roots = [i for i,value in enumerate(previous) if i==value]
            roots = [i for i,value in enumerate(current) if i==value]
            assert set(roots)<=set(previous_roots)
            assert all(current[i]<=i and current[current[i]]==current[i] and current[previous[i]]==current[i] for i in range(TOKENS))
            assert all(value.bit_length()<=FEATURES and (previous[i]==i or value==0)
                       for i,value in enumerate(signs[layer*TOKENS:(layer+1)*TOKENS]))
            expected["signs"] += len(previous_roots)
            expected["sizes"] += sum(TOKENS-root for root in roots)+bisect_right(roots,23)+len(roots)
            if mode==0 and control is None:
                for i,old in enumerate(previous):
                    if old!=i and current[i]!=old:
                        control=(layer,i)
                        break
            previous=current
            roots_by_layer.append(len(roots))
        first_question=prior["cases"][prior["native_fixture_modes"][mode]][0]
        assert roots_by_layer==first_question["layer_roots"]
    assert control is not None and expected["signs"]<expected["maps"]
    result = records / "batch423_cumulative_merger_result.json"
    archive = records / "batch423_native_logs.json.gz"
    assert not result.exists() and not archive.exists()

    def run(work, name, corrupt, cpu):
        folder = work/name
        folder.mkdir()
        selected = module
        if corrupt:
            selected = folder/module.name
            text = module.read_text()
            old = "inherited_root = origins[previous_root]"
            assert text.count(old)==1
            selected.write_text(text.replace(old,"inherited_root = previous_root"))
        command=["taskset","-c",str(cpu),"/opt/cadence/bin/xrun","-64bit","-sv","-xmerror","RECOME","-top",TOP,
                 str(selected),str(causal),str(bench),f"+FIXTURE={fixture}"]
        log=folder/"console.log"
        with log.open("x") as stream:
            process=subprocess.Popen(command,cwd=folder,stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
                                     start_new_session=True)
            print(f"BATCH423_STARTED case={name} group={process.pid}",flush=True)
            try:
                status=process.wait(timeout=180)
            finally:
                terminate_process_group(process)
        content=log.read_text()
        if corrupt:
            layer, position=control
            marker=f"BATCH423_UNEXPECTED_DONE mode=0 layer={layer} maps={position}"
            assert status!=0 and content.splitlines().count(marker)==1 and "BATCH423_PASS" not in content,content[-4000:]
            inventory={"layer":layer,"position":position}
        else:
            markers=re.findall(r"^BATCH423_PASS (.+)$",content,re.M)
            assert status==0 and len(markers)==1 and not re.search(r"\*(?:E|F),",content),content[-4000:]
            inventory={k:int(v) for k,v in (word.split("=") for word in markers[0].split())}
            assert all(inventory[key]==value for key,value in expected.items()),(inventory,expected)
            assert inventory["map_stalls"]>=3*expected["layers"] and inventory["done_stalls"]==5*(expected["layers"]+expected["cfg_errors"])
        return name,{"status":status,"inventory":inventory,"log_sha256":sha256(log)},content

    with tempfile.TemporaryDirectory(dir=ROOT/".cache",prefix="batch423_build_") as name:
        work=Path(name)
        lint=subprocess.run(["verilator","--lint-only","-Wall","--top-module",MODULE,str(module)],cwd=work,
                            capture_output=True,text=True,timeout=30)
        assert lint.returncode==0,lint.stdout+lint.stderr
        with ThreadPoolExecutor(max_workers=2) as pool:
            good=pool.submit(run,work,"trained_traces",False,4)
            bad=pool.submit(run,work,"stale_inheritance_control",True,5)
            runs=[good.result(),bad.result()]
    assert not work.exists() and all(sha256(Path(path))==digest for path,digest in digests.items())
    logs={name:content for name,_,content in runs}|{"verilator":lint.stdout+lint.stderr}
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs,sort_keys=True).encode(),mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes()))==logs
    report={"state":"cumulative_merger_and_causal_prefixes_verified_on_compact_traces","scope":__doc__,
            "sign_bank_slots":24,"sign_features":FEATURES,"inventory":runs[0][1]["inventory"],
            "source_and_fixture_sha256":digests,"runs":{name:entry for name,entry,_ in runs},
            "native_logs_sha256":sha256(archive),"full_paper_results_matched":False}
    with result.open("x") as stream:
        stream.write(json.dumps(report,indent=2)+"\n")
    print("BATCH423_VERIFIED "+json.dumps(report["inventory"],separators=(",",":")),flush=True)


if __name__=="__main__":
    main()
