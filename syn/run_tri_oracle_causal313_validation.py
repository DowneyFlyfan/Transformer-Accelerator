"""Validate the paper's causal-prefix size method independently of chip PPA.

Preserve the large mapped run. Each small native test is limited to120seconds,
combined anonymous memory below14GiB and host available memory above8GiB.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

from tri_oracle_process_guard import terminate_process_group
from run_tri_oracle_row_guard175_synthesis import memory


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/causal313_functional_validation.json'
    assert not result.exists()
    baseline_path=root/'records/causal313_baseline_regression.json'
    baseline=json.loads(baseline_path.read_text())
    assert baseline['state']=='existing_global_size_stream_fails_causal_prefix_regression'
    assert baseline['temporary_build_removed'] is True
    assert baseline['native_exit_status']!=0
    baseline_log=root/'records/causal313_baseline_native.log'
    assert sha(baseline_log)==baseline['native_log_sha256']
    assert 'CAUSAL_PREFIX_REQUIRED query=1 got=000055aa expected=00008080' in baseline_log.read_text()
    sources={str(p):sha(p) for p in [Path(__file__).resolve(),baseline_path,baseline_log,
        root/'records/paper312_causal_size_gap.json',root/'syn/tri_oracle_process_guard.py',
        root/'syn/run_tri_oracle_row_guard175_synthesis.py',Path('/opt/cadence/bin/xrun'),
        *[root/'verilog'/name for name in ['tri_oracle_token_merger.sv','tri_oracle_token_merger_random_tb.sv',
        'tri_oracle_proportional_normalizer.sv','tri_oracle_proportional_normalizer_tb.sv',
        'tri_oracle_causal_token_size.sv','tri_oracle_causal_token_size_tb.sv',
        'tri_oracle_causal_token_integration_tb.sv']]]}
    assert all(sha(path)==digest for path,digest in baseline['source_sha256'].items())
    started=time.monotonic();stopped=False
    def stop(number, frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    record=dict(state='running',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                supervisor_pid=os.getpid(),source_sha256=sources,native_runs={},scope=__doc__,
                peak_combined_anonymous_bytes=0,minimum_host_available_bytes=memory()[0],
                parent_placement_candidate_changed=False,parent_timing_qualified=False,
                full_chip_integrated=False,full_paper_results_matched=False)
    def save(**changes):
        record.update(changes,elapsed_seconds=time.monotonic()-started)
        temporary=result.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(result)
    save()
    temporary_paths=[]
    try:
        def native(phase,top,names,extra=(),mutant=None):
            available,anonymous=memory()
            assert available>8*1024**3 and anonymous<14*1024**3,'Small-test resource admission'
            with tempfile.TemporaryDirectory(prefix='causal313_',dir=root/'.cache/physical') as directory:
                folder=Path(directory);temporary_paths.append(folder)
                paths=[root/'verilog'/name for name in names]
                if mutant is not None:
                    replacement=folder/'mutant.sv';replacement.write_text(mutant)
                    assert paths[0].name=='tri_oracle_causal_token_size.sv'
                    paths[0]=replacement
                log=root/'records'/('causal313_'+phase+'_native.log');assert not log.exists()
                token=str(folder/'xrun.log')
                command=['/opt/cadence/bin/xrun','-64bit','-sv','-top',top,*extra,
                         '-xmlibdirname',str(folder/'xcelium.d'),'-l',token,
                         '-history_file',str(folder/'history'),*[str(p) for p in paths]]
                begin=time.monotonic()
                with log.open('w') as stream:
                    child=subprocess.Popen(command,cwd=folder,stdin=subprocess.DEVNULL,
                        stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
                    try:
                        while child.poll() is None:
                            available,anonymous=memory()
                            record['peak_combined_anonymous_bytes']=max(record['peak_combined_anonymous_bytes'],anonymous)
                            record['minimum_host_available_bytes']=min(record['minimum_host_available_bytes'],available)
                            assert not stopped and time.monotonic()-begin<120,'Small-test wall/stop guard'
                            assert available>8*1024**3 and anonymous<14*1024**3,'Small-test memory guard'
                            time.sleep(.1)
                    finally:
                        terminate_process_group(child,log_argument=token)
                content=log.read_text(errors='replace')
                assert not re.search(r'\*[EF],',content),content[-2400:]
                assert not re.search(r'\*W,',content),content[-2400:]
                record['native_runs'][phase]=dict(command=command,native_exit_status=child.returncode,
                    elapsed_seconds=time.monotonic()-begin,native_log_sha256=sha(log))
                save()
                return child.returncode,content
        sizes={}
        for size in [1,2,3,4,17,32,33,576]:
            code,text=native('size_'+str(size),'tri_oracle_causal_token_size_tb',
                ['tri_oracle_causal_token_size.sv','tri_oracle_causal_token_size_tb.sv'],
                ['-defparam','tri_oracle_causal_token_size_tb.MAX_TOKENS='+str(size)])
            match=re.search(r'CAUSAL_SIZE_PASS max_tokens=(\d+) rows=(\d+) words=(\d+) stalled_cycles=(\d+)',text)
            assert code==0 and match and int(match[1])==size
            assert all(int(match[i])>0 for i in [2,3,4])
            sizes[str(size)]={key:int(match[i]) for i,key in enumerate(['max_tokens','rows','words','stalled_cycles'],1)}
        code,text=native('integration','tri_oracle_causal_token_integration_tb',
            ['tri_oracle_token_merger.sv','tri_oracle_proportional_normalizer.sv',
             'tri_oracle_causal_token_size.sv','tri_oracle_causal_token_integration_tb.sv'])
        assert code==0 and 'CAUSAL_INTEGRATION_PASS mappings=4 rows=5 backward_queries=2' in text
        for phase,top,names,marker in [
            ('legacy_merger','tri_oracle_token_merger_random_tb',
             ['tri_oracle_token_merger.sv','tri_oracle_token_merger_random_tb.sv'],'PASS: 30 token decisions'),
            ('legacy_normalizer','tri_oracle_proportional_normalizer_tb',
             ['tri_oracle_proportional_normalizer.sv','tri_oracle_proportional_normalizer_tb.sv'],
             'PASS: token-size weighting, causal mask, zero denominator, backpressure')]:
            code,text=native(phase,top,names);assert code==0 and marker in text
        source=(root/'verilog/tri_oracle_causal_token_size.sv').read_text()
        target="location_count[cursor_location]<=location_count[cursor_location]-1'b1;"
        assert source.count(target)==1
        mutant=source.replace(target,'// Deliberate test-only mutation: omit the backward decrement.')
        code,text=native('missing_decrement_mutant','tri_oracle_causal_token_size_tb',
            ['tri_oracle_causal_token_size.sv','tri_oracle_causal_token_size_tb.sv'],
            ['-defparam','tri_oracle_causal_token_size_tb.MAX_TOKENS=4'],mutant=mutant)
        assert code!=0 and 'CAUSAL_SIZE_WORD' in text and 'CAUSAL_SIZE_PASS' not in text
        assert all(sha(path)==digest for path,digest in sources.items())
        assert all(not path.exists() for path in temporary_paths)
        save(state='causal_prefix_method_and_stalled_output_functionally_verified',
             parameter_cases=sizes,independent_prefix_rows_checked=sum(v['rows'] for v in sizes.values()),
             independent_origin_count_words_checked=sum(v['words'] for v in sizes.values()),
             real_merger_normalizer_integration_rows=5,existing_related_tests_passed=True,
             baseline_global_count_counterexample_verified=True,missing_decrement_mutation_rejected=True,
             temporary_builds_removed=True,
             scope='Standalone causal-prefix token-size method from Figure31.6.3 verified in native Xcelium, plus real merger/normalizer integration test. Local interfaces, backward-query extension and table realization are reconstruction choices. No compiled SRAM mapping, full-chip integration, timing, accuracy, power or paper headline match claim.')
        print('CAUSAL313_FUNCTIONAL_METHOD_VERIFIED',record['independent_prefix_rows_checked'],record['independent_origin_count_words_checked'])
    except BaseException as error:
        save(state='failed',exception=repr(error),temporary_builds_removed=all(not path.exists() for path in temporary_paths))
        raise


if __name__=='__main__':
    main()
