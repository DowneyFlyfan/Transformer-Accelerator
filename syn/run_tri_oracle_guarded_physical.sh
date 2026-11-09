#!/usr/bin/env bash
# Run in tri-oracle-eda from a Cadence login environment.
set -euo pipefail
command -v innovus >/dev/null || { echo 'Innovus is not on PATH; use the Cadence login shell.' >&2; exit 127; }
exec python3 - <<'PY_GUARD'
import fcntl,hashlib,json,os,re,signal,subprocess,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,"syn")
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_artifact_fingerprint import artifact_fingerprint

def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):
            value.update(chunk)
    return value.hexdigest()
top=os.environ['TRI_ORACLE_TOP'];stage=os.environ['TRI_ORACLE_PHYSICAL_STAGE']
entry=os.environ['TRI_ORACLE_PHYSICAL_ENTRY'];marker=os.environ['TRI_ORACLE_PHYSICAL_MARKER']
if not re.fullmatch(r'tri_oracle_[a-z_]+',top) or not re.fullmatch(r'[a-z_0-9]+',stage):
    raise ValueError('Invalid top or stage')
if not Path(entry).is_file() or not marker.startswith('TRI_ORACLE_'):
    raise ValueError('Invalid entry or required marker')
out=Path('.cache/physical/pnr')/top;out.mkdir(parents=True,exist_ok=True)
lock=(out/'physical.guard.lock').open('a')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
start=time.monotonic()
# Invalidate old success while the stage lock is held, before any preparation.
result_path=out/(stage+'_guard_result.json')
result_path.write_text(json.dumps({
 'exit_status':None,'state':'preparing','supervisor_pid':os.getpid()
},indent=2)+'\n')
requested_stop=False
def stop(signum,frame):
    global requested_stop
    requested_stop=True
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
peak=0;minimum_available=None;reason=None;failure=None
output_artifacts={};started_wall=time.time()
child=None;console=None;code=1
try:
    limit=int(float(os.environ.get('TRI_ORACLE_PHYSICAL_ANON_GIB','14'))*1024**3)
    seconds=int(os.environ.get('TRI_ORACLE_PHYSICAL_SECONDS','7200'))
    if limit<=0 or seconds<=0:
        raise ValueError('Physical guard limits must be positive')
    netlist=Path('.cache/physical/synthesis')/top/'netlist.v'
    sdc=netlist.with_name('constraints.sdc')
    inputs={str(path):digest(path) for path in [netlist,sdc,*Path('syn').glob('tri_oracle_*.tcl')]}
    (out/(stage+'_guard_inputs.json')).write_text(json.dumps({
     'top':top,'stage':stage,'entry':entry,'required_marker':marker,'sha256':inputs,
     'supervisor_sha256':digest('syn/run_tri_oracle_guarded_physical.sh'),
     'process_guard_sha256':digest('syn/tri_oracle_process_guard.py'),
     'artifact_fingerprint_sha256':digest('syn/tri_oracle_artifact_fingerprint.py'),
     'scope':'tool execution and inputs; timing/geometry/connectivity reports require separate inspection'
    },indent=2)+'\n')
    if requested_stop:
        reason='external stop request'
        raise InterruptedError('Stop requested before native physical launch')
    console=(out/(stage+'_console.log')).open('w')
    child=subprocess.Popen(['/usr/bin/time','-v','innovus','-stylus','-no_gui','-batch',
     '-log',str(out/stage),'-files',entry],stdin=subprocess.DEVNULL,stdout=console,
     stderr=subprocess.STDOUT,start_new_session=True)
    (out/(stage+'_guard_child.pid')).write_text(str(child.pid)+'\n')
    result_path.write_text(json.dumps({
     'exit_status':None,'state':'running','supervisor_pid':os.getpid(),
     'native_process_group':child.pid
    },indent=2)+'\n')
    print(f'Started {top} {stage}, process group {child.pid}',flush=True)
    while child.poll() is None:
        stats=dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())
        anonymous=int(stats['anon']);peak=max(peak,anonymous)
        mem=dict((line.split(':',1)[0],line.split(':',1)[1].split()[0]) for line in Path('/proc/meminfo').read_text().splitlines())
        available=int(mem['MemAvailable'])*1024
        minimum_available=available if minimum_available is None else min(minimum_available,available)
        if requested_stop:reason='external stop request'
        elif anonymous>limit:reason='combined anonymous-memory guard'
        elif available<4*1024**3:reason='host available-memory guard'
        elif time.monotonic()-start>=seconds:reason='runtime guard'
        if reason:
            print('Stopping this physical job only: '+reason,flush=True)
            terminate_process_group(child,log_argument=str(out/stage))
            break
        time.sleep(1)
    code=child.wait()
    if reason:code=143 if reason=='external stop request' else (124 if reason=='runtime guard' else 75)
except BaseException as exception:
    failure=repr(exception)
    code=143 if reason=='external stop request' else 1
finally:
    # Retain the stage and inherited global execution locks until every owned
    # worker is gone, even when the initial launcher exits or monitoring fails.
    try:
        if child is not None:
            terminate_process_group(child,log_argument=str(out/stage))
    finally:
        if console is not None:console.close()
if code==0 and not re.search(r'^'+re.escape(marker)+r'$',(out/(stage+'_console.log')).read_text(),re.M):
    code=1
# Optional producer output binding: later stages must match this exact content.
# Stage markers alone never qualify a missing, stale, or replaced checkpoint.
if code==0 and os.environ.get('TRI_ORACLE_PHYSICAL_OUTPUT'):
    try:
        artifact=Path(os.environ['TRI_ORACLE_PHYSICAL_OUTPUT'])
        artifact.relative_to(out)
        content=artifact_fingerprint(artifact)
        files=[artifact] if artifact.is_file() else [p for p in artifact.rglob('*') if p.is_file()]
        if not any(p.stat().st_mtime>=started_wall for p in files):
            raise ValueError('Physical output was not refreshed by this stage: '+str(artifact))
        output_artifacts[str(artifact)]=content
    except BaseException as exception:
        failure=repr(exception);code=1
result_path.write_text(json.dumps({
 'exit_status':code,'state':'finished' if code==0 else 'failed',
 'stop_reason':reason,'elapsed_seconds':time.monotonic()-start,
 'peak_combined_anonymous_bytes':peak,'minimum_host_available_bytes':minimum_available,
 'supervisor_exception':failure,'output_artifacts':output_artifacts,
 'scope':'process/marker completion only, not physical signoff'
},indent=2)+'\n')
print(f'Finished {top} {stage}: exit {code}',flush=True)
sys.exit(code)
PY_GUARD
