"""Native mapped staged down-projection arithmetic and protocol tests."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from tri_oracle_process_guard import terminate_process_group


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label',required=True)
    parser.add_argument('--expect-missing',action='store_true')
    parser.add_argument('--negative-reference',action='store_true')
    args=parser.parse_args()
    assert args.label and all(c.isalnum() or c in '_-' for c in args.label)
    root=Path(__file__).resolve().parents[1]
    result=root/'records'/(args.label+'_result.json');assert not result.exists()
    production=root/'.cache/physical/synthesis/tri_oracle_down_executor_staged116/netlist.v'
    bench=root/'verilog/tri_oracle_down_executor_staged_tb.sv'
    assert production.exists()!=args.expect_missing
    sources=[root/'verilog'/('tri_oracle_'+name+'.sv') for name in ['word_bank','pe_array','memory_compute']]+([production] if production.exists() else [])+[root/'.cache/physical/library/tcbn28hpcplusbwp12t40p140.v',bench]
    mapped_q=json.loads((root/'records/down116_synthesis_result.json').read_text())
    assert mapped_q['state']=='native_small_block_mapping_completed_pending_report_review'
    assert hashlib.sha256(production.read_bytes()).hexdigest()==mapped_q['output_netlist_sha256']
    executable=Path('/opt/cadence/bin/xrun')
    def sha(path):
        with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    identities={str(p):sha(p) for p in [Path(__file__).resolve(),executable,*sources,root/'syn/tri_oracle_process_guard.py']}
    started=time.monotonic();child=None;folder_path=None
    record=dict(state='preflight',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                supervisor_pid=os.getpid(),source_sha256=identities,staged_down_controller_only=True,mapped_standard_cell_netlist=True,
                actual_compiled_core_instances=0,actual_compiled_memory_instances=0,
                full_paper_results_matched=False,scope='Mapped standard-cell staged sparse down controller feeding the inferred-memory compute reference. Raw-clock functional simulation with sequential UDP nonblocking scheduling; no SDF or routed timing proof.')
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        temporary=result.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(result)
    def available():
        return int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024
    save()
    try:
        while available()<=7*1024**3:
            assert time.monotonic()-started<7200,'Prediction-test memory headroom wait expired'
            save(state='waiting_for_prediction_test_memory_headroom')
            time.sleep(2)
        with tempfile.TemporaryDirectory(prefix=args.label+'_',dir=root/'.cache/physical') as folder:
            folder_path=Path(folder);log=root/'records'/(args.label+'_native.log')
            command=[str(executable),'-64bit','-sv','-xmerror','RECOME','-sequdp_nba_delay','-top','tri_oracle_down_executor_staged_tb',
                     '-xmlibdirname',str(folder_path/'xcelium.d'),'-l',str(folder_path/'xrun.log'),
                     '-history_file',str(folder_path/'history'),*[str(p) for p in sources]]
            if args.negative_reference:command.append('+CORRUPT_DOWN_REFERENCE')
            with log.open('w') as output:
                native_started=time.monotonic()
                child=subprocess.Popen(command,cwd=folder_path,stdin=subprocess.DEVNULL,stdout=output,
                                       stderr=subprocess.STDOUT,start_new_session=True)
                save(state='native_mock_control_test_running',native_process_group=child.pid,command=command)
                try:
                    while child.poll() is None:
                        assert available()>5*1024**3,'Yielding control test to host memory reserve'
                        assert time.monotonic()-native_started<300,'Control-test wall budget'
                        time.sleep(.1)
                finally:terminate_process_group(child,log_argument=str(folder_path/'xrun.log'))
            text=log.read_text(errors='replace')
            for path,expected in identities.items():assert sha(path)==expected,'Changed source '+path
            if args.expect_missing:
                assert child.returncode!=0 and 'CUVMUR' in text and 'tri_oracle_down_executor_staged' in text
                save(state='expected_missing_production_module_rejected',native_exit_status=child.returncode,native_console_sha256=sha(log));return
            if args.negative_reference:
                marker='down reference matrix product mismatch'
                assert child.returncode!=0 and marker in text
                save(state='expected_wrong_control_reference_rejected',native_exit_status=child.returncode,native_console_sha256=sha(log));return
            assert child.returncode==0 and 'STAGED_DOWN_PASS cases=34' in text,text[-4000:]
            save(state='staged_down_mapped_functional_passed',cases_seen=34,native_exit_status=0,native_console_sha256=sha(log),
                 actual_compiled_memory_integration_and_timing_still_required=True)
    except BaseException as error:
        if child is not None:terminate_process_group(child,log_argument=str(folder_path/'xrun.log'))
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child else None);raise
    finally:
        if folder_path is not None:save(temporary_build_removed=not folder_path.exists())


if __name__=='__main__':main()
