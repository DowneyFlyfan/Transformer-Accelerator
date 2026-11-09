"""Native prediction/batching packet-stream tests without a compute datapath."""
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
    production=root/'verilog/tri_oracle_prediction_packet_stream.sv'
    bench=root/'verilog/tri_oracle_prediction_packet_stream_tb.sv'
    assert production.exists()!=args.expect_missing
    sources=[root/'verilog'/('tri_oracle_'+name+'.sv') for name in ['strip_predictor','channel_compactor','predicted_dispatch']]+([production] if production.exists() else [])+[bench]
    executable=Path('/opt/cadence/bin/xrun')
    def sha(path):
        with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    identities={str(p):sha(p) for p in [Path(__file__).resolve(),executable,*sources,root/'syn/tri_oracle_process_guard.py']}
    started=time.monotonic();child=None;folder_path=None
    record=dict(state='preflight',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                supervisor_pid=os.getpid(),source_sha256=identities,prediction_control_only=True,
                actual_compiled_core_instances=0,actual_compiled_memory_instances=0,
                full_paper_results_matched=False,scope='Actual strip predictor and compactor with production packet batching. No compute cores or memories; integrated numeric frame validation remains required.')
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
            command=[str(executable),'-64bit','-sv','-top','tri_oracle_prediction_packet_stream_tb',
                     '-xmlibdirname',str(folder_path/'xcelium.d'),'-l',str(folder_path/'xrun.log'),
                     '-history_file',str(folder_path/'history'),*[str(p) for p in sources]]
            if args.negative_reference:command.append('+CORRUPT_PACKET_REFERENCE')
            with log.open('w') as output:
                native_started=time.monotonic()
                child=subprocess.Popen(command,cwd=folder_path,stdin=subprocess.DEVNULL,stdout=output,
                                       stderr=subprocess.STDOUT,start_new_session=True)
                save(state='native_mock_control_test_running',native_process_group=child.pid,command=command)
                try:
                    while child.poll() is None:
                        assert available()>5*1024**3,'Yielding control test to host memory reserve'
                        assert time.monotonic()-native_started<120,'Control-test wall budget'
                        time.sleep(.1)
                finally:terminate_process_group(child,log_argument=str(folder_path/'xrun.log'))
            text=log.read_text(errors='replace')
            for path,expected in identities.items():assert sha(path)==expected,'Changed source '+path
            if args.expect_missing:
                assert child.returncode!=0 and 'CUVMUR' in text and 'tri_oracle_prediction_packet_stream' in text
                save(state='expected_missing_production_module_rejected',native_exit_status=child.returncode,native_console_sha256=sha(log));return
            if args.negative_reference:
                marker='PREDICTION_PACKET_ID'
                assert child.returncode!=0 and marker in text
                save(state='expected_wrong_control_reference_rejected',native_exit_status=child.returncode,native_console_sha256=sha(log));return
            assert child.returncode==0 and 'PREDICTION_PACKET_PASS cases=9' in text,text[-4000:]
            save(state='prediction_packet_stream_passed',cases_seen=9,native_exit_status=0,native_console_sha256=sha(log),
                 connected_prediction_numeric_frame_integration_still_required=True)
    except BaseException as error:
        if child is not None:terminate_process_group(child,log_argument=str(folder_path/'xrun.log'))
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child else None);raise
    finally:
        if folder_path is not None:save(temporary_build_removed=not folder_path.exists())


if __name__=='__main__':main()
