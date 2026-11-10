"""Check held mask offers and tagged cancellation before frame reuse.

Native shared frame393 is unchanged. The producer offers its second mask while
the first tile is busy, holds it stable, and cancels it on tagged terminal error
before acknowledging done. Ignoring cancellation must reject the stale mask.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    result=root/'records/batch394_mask_control.json';directory=root/'.cache/physical/simulation/batch394'
    assert not result.exists() and not directory.exists()
    prior_path=root/'records/batch393_literal_result.json';prior=json.loads(prior_path.read_text())
    assert prior['state']=='literal_joined_feedforward_and_six_recoveries_passed'
    paths=[Path(p) for p in prior['source_sha256'] if Path(p).suffix in ['.sv','.v'] and Path(p).name!='tri_oracle_batched393_tb.sv']
    bench=root/'verilog/tri_oracle_batched394_mask_tb.sv';paths.append(bench)
    inputs={str(p):sha(p) for p in [Path(__file__).resolve(),prior_path,root/'syn/tri_oracle_process_guard.py',*paths]}
    for p in paths:
        if p!=bench:assert inputs[str(p)]==prior['source_sha256'][str(p)]
    bundle='`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'+''.join('`include "'+str(p)+'"\n' for p in paths)
    started=time.monotonic();stopped=False;lock=threading.RLock()
    record=dict(state='native_mask_controls_running',supervisor_pid=os.getpid(),source_sha256=inputs,
                runs=[],scope=__doc__,full_paper_results_matched=False)
    def save(**changes):
        with lock:
            record.update(changes,elapsed_seconds=time.monotonic()-started)
            p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    def stop(number,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def memory():
        available=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024
        anonymous=int(dict(l.split() for l in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        assert available>6*1024**3 and anonymous<18*1024**3 and not stopped
    memory();directory.mkdir();save()
    def run(case):
        fault,honor=case;label=f'f{fault}_c{honor}';work=directory/label;work.mkdir();(work/'bundle.sv').write_text(bundle)
        log=directory/(label+'.log');child=None;began=time.monotonic();entry=dict(fault=fault,honor_cancel=honor,state='starting')
        with lock:record['runs'].append(entry);save()
        try:
            top='tri_oracle_batched394_mask_tb'
            command=['/opt/cadence/bin/xrun','-64bit','-sv','-xmerror','RECOME','-notimingchecks',
                '-top',top,'-top','tri_oracle_batch357_hierarchy',
                '-defparam',top+f'.FAULT={fault}','-defparam',top+f'.HONOR_CANCEL={honor}',
                '-xmlibdirname',str(work/'xcelium.d'),'-l',str(work/'native.log'),
                '-history_file',str(work/'history'),str(work/'bundle.sv')]
            with log.open('x') as stream:
                child=subprocess.Popen(command,cwd=work,stdin=subprocess.DEVNULL,stdout=stream,
                    stderr=subprocess.STDOUT,start_new_session=True)
                with lock:entry.update(state='running',process_group=child.pid,command=command);save()
                while child.poll() is None:
                    memory();assert time.monotonic()-began<600;time.sleep(.5)
            content=log.read_text()
            with lock:entry.update(native_exit_status=child.returncode,log=str(log),log_sha256=sha(log),elapsed_seconds=time.monotonic()-began);save()
            assert content.count('BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600')==1
            if honor:
                assert child.returncode==0 and 'BATCH394_PASS tokens=3 hidden=64 intermediate=96 outputs=173 exact_outputs=519' in content
                flow=re.search(r'BATCH394_MASK_FLOW held_cycles=(\d+) cancelled=(\d+)',content)
                assert flow and int(flow[1])>0 and int(flow[2])==fault
                if fault:assert re.search(r'BATCH394_MASK_CANCELLED start=80 held_cycles=[1-9]\d*',content)
            else:
                assert child.returncode==2 and 'BATCH394_STALE_MASK_REJECTED_AFTER_IGNORED_CANCEL' in content
                assert 'BATCH394_PASS tokens=' not in content
            with lock:entry['state']='passed' if honor else 'stale_offer_rejected';save()
        finally:
            if child is not None:terminate_process_group(child)
            shutil.rmtree(work)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(run,[(0,1),(1,1),(1,0)]))
        assert all(sha(p)==h for p,h in inputs.items())
        save(state='held_mask_flow_cancel_recovery_and_stale_rejection_verified',
             exact_output_comparisons=1038,temporary_builds_removed=True)
        print('BATCH394_MASK_CANCELLATION_VERIFIED',flush=True)
    except BaseException as error:
        save(state='failed',exception=repr(error));raise


if __name__=='__main__':main()
