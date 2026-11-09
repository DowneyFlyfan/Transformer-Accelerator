"""Verify the channel-conservation observer accepts full streams and rejects defects."""
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from tri_oracle_fixture190_integrity import sha
from tri_oracle_process_guard import terminate_process_group


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/channel190_monitor_validation.json';assert not result.exists()
    source=root/'verilog/tri_oracle_real_channel_sequence190_monitor.sv'
    bench=root/'verilog/tri_oracle_real_channel_sequence190_monitor_tb.sv'
    inputs=[Path(__file__).resolve(),source,bench,Path('/opt/cadence/bin/xrun'),
            root/'syn/tri_oracle_fixture190_integrity.py',root/'syn/tri_oracle_process_guard.py']
    identities={str(p):sha(p) for p in inputs}
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                       if line.startswith('MemAvailable:')))*1024
    assert available>8*1024**3
    def stop(signum,frame):raise InterruptedError('Monitor validation stop requested')
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    started=time.monotonic();steps=[]
    expected={1:'ID',2:'ID',3:'COUNT',4:'LAST',5:'METADATA',6:'STALLED_PACKET_CHANGED',7:'EXTRA',8:'UNKNOWN'}
    with tempfile.TemporaryDirectory(prefix='channel190_',dir=root/'.cache/physical') as folder:
        directory=Path(folder)
        for mode in range(9):
            assert all(sha(p)==h for p,h in identities.items())
            log=directory/('mode'+str(mode)+'.log')
            command=['/opt/cadence/bin/xrun','-64bit','-sv','-top','tri_oracle_real_channel_sequence190_monitor_tb',
                '-xmlibdirname',str(directory/'xcelium.d'),'-l',str(directory/'xrun.log'),
                '-history_file',str(directory/'history'),str(source),str(bench),'+MUTANT='+str(mode)]
            with log.open('w') as output:
                child=subprocess.Popen(command,cwd=directory,stdin=subprocess.DEVNULL,stdout=output,
                                       stderr=subprocess.STDOUT,start_new_session=True)
                try:child.wait(timeout=30)
                finally:terminate_process_group(child,log_argument=str(directory/'xrun.log'))
            text=log.read_text(errors='replace')
            if mode==0:
                assert child.returncode==0 and 'REAL_CHANNEL_MONITOR_PASS channels=5632 packets=36' in text,text[-3000:]
            else:
                assert child.returncode!=0 and 'REAL_CHANNEL_SEQUENCE_'+expected[mode] in text,text[-3000:]
                assert 'REAL_CHANNEL_MONITOR_PASS' not in text
            steps.append(dict(mode=mode,native_exit_status=child.returncode,console=text))
    assert all(sha(p)==h for p,h in identities.items())
    result.write_text(json.dumps(dict(state='channel_conservation_monitor_positive_and_eight_mutants_passed',
        source_sha256=identities,steps=steps,elapsed_seconds=time.monotonic()-started,temporary_build_removed=True,
        scope='Test-observer verification only: one5632-channel stream and eight protocol/identity mutants. '
              'Not full-layer arithmetic, chip functionality, timing or paper-result evidence.'),indent=2)+'\n')
    print('CHANNEL190_MONITOR_VALIDATION_PASS steps=9 channels=5632 packets=36')


if __name__=='__main__':main()
