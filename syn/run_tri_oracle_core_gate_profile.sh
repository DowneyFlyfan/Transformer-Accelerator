#!/usr/bin/env bash
# Serialize large Icarus elaboration with the core's native physical tools.
set -euo pipefail
command -v iverilog >/dev/null
command -v vvp >/dev/null
exec python3 - <<'PY_GUARD'
import fcntl,hashlib,json,os,re,signal,subprocess,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,'syn')
from tri_oracle_process_guard import terminate_process_group

def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()

def qualify_library_functional_mode(netlist,models,bench,proof_directory=Path('records')):
    audit_path=proof_directory/'library_functional_mode_structural_audit.json'
    proof_path=proof_directory/'library_functional_mode_dynamic_proof.json'
    validator=Path('syn/tri_oracle_library_mode.py')
    audit=json.loads(audit_path.read_text());proof=json.loads(proof_path.read_text())
    if (audit.get('netlist_sha256')!=digest(netlist)
        or audit.get('library_sha256')!=digest(models)
        or audit.get('validator_sha256')!=digest(validator)
        or proof.get('validator_sha256')!=digest(validator)
        or proof.get('library_sha256')!=digest(models)
        or proof.get('structural_audit_sha256')!=digest(audit_path)
        or proof.get('cell_types')!=audit.get('audited_cell_types')
        or not audit.get('audited_cell_types')
        or any(proof.get(name) is not True for name in
               ['comparison_passed','wrong_functional_primitive_mutant_rejected',
                'every_output_model_produced_known_outputs'])):
        raise ValueError('Library functional mode lacks current matching structural/native proof')
    for path in [netlist,bench]:
        with Path(path).open('rb') as source:
            if any(b'TETRAMAX' in line or b'$sdf_annotate' in line for line in source):
                raise ValueError('Functional mode is unsupported for these compilation inputs')
    return [audit_path,proof_path,validator]

out=Path('.cache/physical/pnr/tri_oracle_memory_compute')
stage=os.environ['TRI_ORACLE_GATE_STAGE']
if not re.fullmatch(r'[a-z_0-9]+',stage):raise ValueError('Invalid gate stage')
bench=os.environ.get('TRI_ORACLE_CORE_BENCH','tri_oracle_memory_compute_tb')
markers={
 'tri_oracle_memory_compute_tb':'PASS: full-size core memory loading, independent low/high addresses, 40 compute commands, consecutive accumulation, 512 output sums, bounds, reset',
 'tri_oracle_partial_weight_tb':'PASS: sparse weight row writes, disabled-row poison, word isolation, signed extrema, zero enables, independent activation/mask loads',
 'tri_oracle_feedforward_core_tb':'PASS: prediction-to-gate/up-to-sparse-down on one shared core, dense reference sums, all15 partial-sum slots, multiple input batches/output tiles, empty tensor, faults in all matrices, late failure withholding outputs, stalls, reset',
 'tri_oracle_memory_feedforward_core_tb':'MEMORY_FEEDFORWARD_PASS cases=34'
}
if bench not in markers:raise ValueError('Unsupported core bench')
lock=(out/'physical.guard.lock').open('a')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
result_path=out/(stage+'_guard_result.json')
if result_path.exists():raise ValueError('Refusing to overwrite an existing stage result')
netlist=Path(os.environ.get('TRI_ORACLE_CORE_NETLIST',str(out/'routed_netlist.v')))
os.environ['TRI_ORACLE_CORE_NETLIST']=str(netlist)
inputs=[netlist,Path('.cache/physical/library/tcbn28hpcplusbwp12t40p140.v'),
 Path('verilog')/(bench+'.sv'),Path('syn/run_tri_oracle_core_gate_simulation.sh'),
 Path('syn/run_tri_oracle_core_gate_profile.sh'),Path('syn/tri_oracle_process_guard.py')]
functional_mode=os.environ.get('TRI_ORACLE_FUNCTIONAL_LIBRARY_MODE','0')
if functional_mode not in ('0','1'):raise ValueError('Unsupported functional-library mode')
if functional_mode=='1':
    proof_directory=Path(os.environ.get('TRI_ORACLE_FUNCTIONAL_PROOF_DIRECTORY','records'))
    inputs+=qualify_library_functional_mode(netlist,inputs[1],Path('verilog')/(bench+'.sv'),proof_directory)
hashes={str(path):digest(path) for path in inputs}
(out/(stage+'_guard_inputs.json')).write_text(json.dumps({
 'bench':bench,'netlist':str(netlist),'sha256':hashes,
 'functional_library_mode':functional_mode=='1',
 'scope':'zero-delay routed/mapped functional test, not delay-annotated timing or paper matching'
},indent=2)+'\n')
limit=int(float(os.environ.get('TRI_ORACLE_GATE_ANON_GIB','17'))*1024**3)
seconds=int(os.environ.get('TRI_ORACLE_GATE_SECONDS','3600'))
requested_stop=False
def stop(signum,frame):
    global requested_stop
    requested_stop=True
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
log=out/(stage+'_console.log');console=log.open('w')
start=time.monotonic();peak=0;minimum_available=None;reason=None
binary=Path('.cache')/(bench+'_gate_simulation.vvp')
child=None;code=1;unchanged=None;failure=None
try:
    child=subprocess.Popen(['/usr/bin/time','-v','bash','syn/run_tri_oracle_core_gate_simulation.sh'],
     stdin=subprocess.DEVNULL,stdout=console,stderr=subprocess.STDOUT,start_new_session=True)
    (out/(stage+'_guard_child.pid')).write_text(str(child.pid)+'\n')
    print(f'Started {stage}: {bench}, process group {child.pid}',flush=True)
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
            print('Stopping this gate simulation only: '+reason,flush=True)
            terminate_process_group(child)
            break
        time.sleep(1)
    code=child.wait()
    if reason:code=143 if reason=='external stop request' else (124 if reason=='runtime guard' else 75)
    console.flush()
    text=log.read_text()
    if code==0 and (text.count(markers[bench])!=1 or re.search(r'FATAL:|ERROR:|Command terminated by signal',text)):code=1
    unchanged=all(digest(path)==value for path,value in hashes.items())
    if not unchanged:code=1
except BaseException as exception:
    failure=repr(exception);code=1
finally:
    # A completed launcher does not prove that its compiler descendants exited.
    # Retain the execution lock through unconditional owned-group cleanup, also
    # when monitor/hash reads raise. No unrelated native processes are touched.
    try:
        if child is not None:terminate_process_group(child)
    finally:
        console.close()
        binary.unlink(missing_ok=True)
result_path.write_text(json.dumps({
 'exit_status':code,'stop_reason':reason,'elapsed_seconds':time.monotonic()-start,
 'peak_combined_anonymous_bytes':peak,'minimum_host_available_bytes':minimum_available,
 'inputs_unchanged':unchanged,'positive_marker':markers[bench],
 'supervisor_exception':failure,
 'log_sha256':digest(log),'delay_annotation':False,
 'functional_library_mode':functional_mode=='1',
 'scope':'specified core functional cases only; not full-chip timing/accuracy or paper PPA matching'
},indent=2)+'\n')
print(f'Finished {stage}: exit {code}',flush=True)
sys.exit(code)
PY_GUARD
