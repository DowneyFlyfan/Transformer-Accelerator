"""Export a guidance-only checkpoint, exit, and prove its fresh-process reload."""
import datetime
import fcntl
import filecmp
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'syn'))
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy,OwnedProcessPause
from tri_oracle_parent_candidate_acceptance import require_reset_topology
from tri_oracle_process_guard import terminate_process_group

PARENT=ROOT/'.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30'
BASE=ROOT/'.cache/physical/pnr/tri_oracle_sram_memory_compute'
OUT=PARENT/'guidance96'
RESULT=ROOT/'records/guidance_parent96_result.json'
ENTRY=ROOT/'syn/tri_oracle_prepare_guidance_parent96.tcl'
started=time.monotonic();child=None;pause=None;log_argument=None;locks=[];requested_stop=False
record=dict(state='preflight',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),supervisor_pid=os.getpid(),
            optimization_executed=False,guidance_final_timing_qualified=False,full_paper_results_matched=False,
            scope='Prepare compact guidance mapping in an isolated native lifetime, then cold reload in a fresh native process. Parent and all fixed macros remain unchanged; no optimization or final timing acceptance.')

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def save(**updates):
    record.update(updates,elapsed_seconds=time.monotonic()-started)
    temporary=RESULT.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(RESULT)
def stop(signum,frame):
    global requested_stop
    requested_stop=True
def available():
    return int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024
def anonymous():
    return int(dict(x.split() for x in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
def equal_inventories(before,after):
    with tempfile.TemporaryDirectory(prefix='inventory_compare_',dir=OUT) as folder:
        files=[]
        for index,path in enumerate([before,after]):
            target=Path(folder)/str(index)
            subprocess.run(['sort','-S','64M','-T',folder,'-o',str(target),str(path)],
                           env=dict(os.environ,LC_ALL='C'),check=True,timeout=600);files.append(target)
        assert filecmp.cmp(*files,shallow=False),'Native parent inventory changed'
        return sha(files[0])
def native(stage,checkpoint,cold=False):
    global child,pause,log_argument
    directory=OUT/stage;directory.mkdir(exist_ok=False)
    console=directory/'console.log';log_argument=str(directory/'native')
    command=['innovus','-stylus','-no_gui','-batch','-log',log_argument,'-files',str(ENTRY)]
    environment=dict(os.environ,TRI_ORACLE_GUIDANCE_PREPARATION_DIRECTORY=str(directory),
        TRI_ORACLE_GUIDANCE_PREPARATION_INPUT=str(checkpoint),TRI_ORACLE_GUIDANCE_PREPARATION_COLD='1' if cold else '0')
    policy=MemoryPressurePolicy(host_reserve_bytes=6*1024**3,resume_bytes=7*1024**3,anonymous_limit_bytes=12*1024**3)
    native_started=time.monotonic();peak=0;minimum=available()
    with console.open('w') as stream:
        child=subprocess.Popen(command,cwd=directory,env=environment,stdin=subprocess.DEVNULL,
            stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        pause=OwnedProcessPause(child,log_argument)
        save(state='fresh_compact_reload_running' if cold else 'native_guidance_preparation_running',native_process_group=child.pid)
        while child.poll() is None:
            memory,combined=available(),anonymous();peak=max(peak,combined);minimum=min(minimum,memory)
            assert not requested_stop and time.monotonic()-native_started<1800,'Native guidance preparation stopped or exceeded wall budget'
            action=policy.observe(memory,combined,time.monotonic())
            if action in ('pause','resume'):
                groups=pause.pause() if action=='pause' else pause.resume()
                save(memory_pressure_events=record.get('memory_pressure_events',[])+[dict(action=action,groups=groups,stage=stage)])
            if time.monotonic()-record.get('last_sample_monotonic',0)>10:
                save(last_sample_monotonic=time.monotonic(),current_stage=stage,current_stage_peak_anonymous_bytes=peak,current_stage_minimum_available_bytes=minimum)
            time.sleep(.2)
        terminate_process_group(child,log_argument=log_argument)
    marker='TRI_ORACLE_GUIDANCE96_FRESH_PROCESS_COMPACT_PARENT_VERIFIED' if cold else 'TRI_ORACLE_GUIDANCE96_CHECKPOINT_PREPARED_WITHOUT_OPTIMIZATION'
    assert child.returncode==0 and '\n'+marker+'\n' in console.read_text(errors='replace'),console
    return dict(native_exit_status=0,elapsed_seconds=time.monotonic()-native_started,
                peak_combined_anonymous_bytes=peak,minimum_host_available_bytes=minimum,console_sha256=sha(console),output_directory=str(directory))

signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
assert not RESULT.exists();save()
try:
    assert available()>16*1024**3 and anonymous()<3*1024**3,'Preparation initial memory reserve'
    assert shutil.disk_usage(PARENT).free>8*1024**3,'Disk reserve'
    placement_path=ROOT/'records/predicted_fabric_placement79_result.json'
    placement=json.loads(placement_path.read_text());assert placement['state']=='real_parent_full_model_geometric_placement_passed'
    identities=dict(placement['source_sha256'])
    for path in [Path(__file__).resolve(),ENTRY,placement_path,ROOT/'syn/tri_oracle_guided_parent_checks.tcl',
                 ROOT/'syn/tri_oracle_parent_candidate_acceptance.py',ROOT/'syn/tri_oracle_hierarchy_fingerprint.py',
                 ROOT/'syn/tri_oracle_memory_pressure_guard.py',ROOT/'syn/tri_oracle_process_guard.py']:
        identities[str(path)]=sha(path)
    for path,expected in placement['core_preservation']['input_sha256'].items():
        assert sha(path)==expected;identities[path]=expected
    reset_baseline=PARENT/'placement79/registered_reset_roots.tsv'
    assert sha(reset_baseline)==placement['native_registered_reset_report_sha256']
    identities[str(reset_baseline)]=placement['native_registered_reset_report_sha256']
    models={};dependencies={}
    for dirname,filename in [('hierarchy_full_control_68','sram_core_hierarchy68_full_control_validation.json'),('hierarchy_export_58','sram_core_hierarchy58_export_validation.json')]:
        path=ROOT/'records'/filename;identities[str(path)]=sha(path)
        expected=json.loads(path.read_text())['output_artifact_fingerprint'];assert artifact_fingerprint(BASE/dirname)==expected
        models[str(BASE/dirname)]=expected
        dependencies[BASE/dirname/'ilm']={'type':'directory','files':{k[4:]:v for k,v in expected['files'].items() if k.startswith('ilm/')}}
    checkpoint=PARENT/'placement79/placed.db'
    def immutable():
        for path,expected in identities.items():assert sha(path)==expected,'Changed source '+path
        for path,expected in models.items():assert artifact_fingerprint(path)==expected,'Changed model '+path
        assert hierarchy_fingerprint(checkpoint,directory_dependencies=dependencies)==placement['placed_checkpoint_fingerprint']
    immutable();save(source_sha256=identities,input_database_fingerprint=placement['placed_checkpoint_fingerprint'])
    for path in [ROOT/'.cache/physical/pnr/tri_oracle_memory_compute/physical.guard.lock',PARENT/'physical.guard.lock']:
        lock=path.open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(lock)
    OUT.mkdir(exist_ok=False)
    preparation=native('prepare',checkpoint)
    prepared=OUT/'prepare/prepared_guidance.db'
    guide_path=BASE/'hierarchy_export_58/ilm'
    fingerprint=hierarchy_fingerprint(prepared,directory_dependencies={guide_path:dependencies[guide_path]})
    assert set(fingerprint['directory_dependencies'])=={str(guide_path)},'Prepared checkpoint still references complete models'
    inventory=equal_inventories(OUT/'prepare/parent_before.tsv',OUT/'prepare/parent_after.tsv')
    resets={'prepare':require_reset_topology(reset_baseline,OUT/'prepare/registered_reset_roots.tsv')}
    save(state='prepared_requires_fresh_native_reload',preparation=preparation,output_database=str(prepared),output_database_fingerprint=fingerprint)
    cold=native('cold',prepared,True)
    assert equal_inventories(OUT/'prepare/parent_before.tsv',OUT/'cold/parent_after.tsv')==inventory
    assert (OUT/'prepare/macros.tsv').read_bytes()==(OUT/'cold/macros.tsv').read_bytes()
    equal_inventories(OUT/'prepare/guidance.tsv',OUT/'cold/guidance.tsv')
    resets['cold']=require_reset_topology(reset_baseline,OUT/'cold/registered_reset_roots.tsv')
    for directory in [OUT/'prepare',OUT/'cold']:
        text=(directory/'models.rpt').read_text();assert 'current ilm data is for si mode' in text.lower()
        assert len(re.findall(r'\bAll\s+ILM\s+post-cts\s+',text))==20
    immutable();assert hierarchy_fingerprint(prepared,directory_dependencies={guide_path:dependencies[guide_path]})==fingerprint
    save(state='guidance_only_checkpoint_and_fresh_reload_qualified',native_exit_status=0,cold_reload=cold,
         all337515_original_parent_cells_and_geometry_preserved=True,all60_fixed_macro_poses_interfaces_preserved=True,
         exact_registered_reset_topology=resets,canonical_parent_inventory_sha256=inventory,
         compact_core_instances=20,compact_cells_per_core=33818,actual_memory_macros=600,
         complete_model_directory_absent_from_prepared_dependencies=True,original_inputs_and_models_unchanged=True,
         fresh_optimizer_process_still_required=True)
    print('GUIDANCE_PARENT96_FRESH_PROCESS_PREPARATION_QUALIFIED',flush=True)
except BaseException as error:
    if child is not None:
        if pause is not None:pause.resume()
        terminate_process_group(child,log_argument=log_argument)
    save(state='failed',exception=repr(error),native_exit_status=child.returncode if child else None);raise
finally:
    for lock in reversed(locks):lock.close()
