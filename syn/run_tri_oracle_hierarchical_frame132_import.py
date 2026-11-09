"""Import the mapped staged frame for diagnostic macro floorplanning."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/frame132_import_result.json'
    output=root/'.cache/physical/pnr/tri_oracle_predicted_feedforward_hierarchical131'
    assert not result.exists() and not output.exists()
    started=time.monotonic();child=None;pause=None;lock=None;stop_requested=False
    qpath=root/'records/frame131_synthesis_result.json'
    entry=root/'syn/tri_oracle_initialize_hierarchical_frame132.tcl'
    record=dict(state='preflight',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                supervisor_pid=os.getpid(),requested_maximum_cpu_workers=8,reported_period_ns=1.72414,full_paper_results_matched=False,
                scope='Diagnostic native import and macro floorplan of the mapped staged20-core parent. Full core models, exact new parent reset topology, placement, routed timing and paper metrics remain unqualified.')
    def sha(path):
        with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        temporary=result.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(result)
    def memory():
        available=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024
        anonymous=int(dict(x.split() for x in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        return available,anonymous
    def stop(signum,frame):
        nonlocal stop_requested
        stop_requested=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    save()
    try:
        while True:
            assert not stop_requested and time.monotonic()-started<10800,'Parent mapping wait expired'
            if qpath.exists():
                prerequisite=json.loads(qpath.read_text())
                if prerequisite['state']=='native_parent_mapping_completed_pending_report_review':break
                assert prerequisite['state']!='failed','Parent mapping prerequisite failed'
            save(state='waiting_for_native_parent_mapping');time.sleep(2)
        assert prerequisite['native_exit_status']==0
        assert all(sha(p)==h for p,h in prerequisite['source_sha256'].items())
        mapped=Path(prerequisite['output_directory'])/'netlist.v';sdc=mapped.with_name('constraints.sdc')
        assert sha(mapped)==prerequisite['output_netlist_sha256']
        accepted_path=root/'records/predicted_fabric_placement79_result.json'
        accepted=json.loads(accepted_path.read_text())
        canonical=root/'.cache/physical/pnr/tri_oracle_sram_memory_compute/hierarchy_twenty_core_75_inputs/wrapper.v'
        assert sha(canonical)==accepted['source_sha256'][str(canonical)]
        import re
        mapped_text=mapped.read_text();canonical_text=canonical.read_text()
        assert len(re.findall(r'^\s*module\s+tri_oracle_predicted_feedforward_frame\s*\(',mapped_text,re.M))==1
        core=re.compile(r'^\s*module\s+tri_oracle_sram_memory_compute\s*\(',re.M)
        assert not core.search(mapped_text),'Unexpected embedded core implementation; review before import'
        starts=list(core.finditer(canonical_text));assert len(starts)==1
        end=re.search(r'^\s*endmodule\s*$',canonical_text[starts[0].start():],re.M);assert end
        declaration=canonical_text[starts[0].start():starts[0].start()+end.end()]+'\n'
        import_text=mapped_text+('' if mapped_text.endswith('\n') else '\n')+declaration
        assert import_text.startswith(mapped_text)
        physical=[root/'.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef',
          root/'.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef',
          root/'.cache/physical/sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/LEF/ts5n28hpcpsvta32x128m2fw_130a.lef',
          root/'.cache/physical/sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/LEF/ts6n28hpcpsvta16x128m2f_130a.lef',
          root/'.cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/LEF/ts5n28hpcpsvta512x64m4f_130a.lef',
          root/'.cache/physical/pnr/tri_oracle_sram_memory_compute/hierarchy_export_58/core.lef']
        libraries=[]
        for suffix in ['tt1v25c','ssg0p9v125c','ffg1p05vm40c']:
            libraries += [root/'.cache/physical/library'/('tcbn28hpcplusbwp12t40p140'+suffix+'.lib')]
            for base,name in [('core_weights_masks_01','ts5n28hpcpsvta32x128m2fw_130a'),('core_outputs_01','ts6n28hpcpsvta16x128m2f_130a'),('activation_cache_banks_01','ts5n28hpcpsvta512x64m4f_130a')]:
                libraries += [root/'.cache/physical/sram'/base/name/'NLDM'/(name+'_'+suffix+'.lib')]
        identities={str(p):sha(p) for p in [Path(__file__).resolve(),entry,qpath,mapped,sdc,canonical,accepted_path,*physical,*libraries,
            *[root/'.cache/physical/rc'/n for n in ['qrc_typical','qrc_rcworst','qrc_rcbest']],
            root/'syn/tri_oracle_hierarchical_frame132_mmmc.tcl',root/'syn/tri_oracle_staged_frame123_floorplan.tcl',
            root/'syn/tri_oracle_registered_reset_trace102.tcl',root/'syn/tri_oracle_check_registered_reset_fabric.tcl',
            root/'records/registered_reset34_sequential_masters.json',root/'records/sram_core_hierarchy58_export_validation.json',
            root/'syn/tri_oracle_memory_pressure_guard.py',root/'syn/tri_oracle_process_guard.py']}
        while True:
            available,anonymous=memory()
            if available>14*1024**3 and anonymous<3*1024**3:break
            assert not stop_requested and time.monotonic()-started<14400,'Physical import headroom wait expired'
            save(state='waiting_for_initial_memory_headroom');time.sleep(2)
        output.mkdir()
        (output/'parent_import.v').write_text(import_text)
        lock=(output/'guard.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        log_argument=str(output/'native');console=output/'console.log'
        command=['innovus','-stylus','-no_gui','-batch','-log',log_argument,'-files',str(entry)]
        native_started=time.monotonic()
        with console.open('w') as stream:
            child=subprocess.Popen(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
                start_new_session=True,env=dict(os.environ))
            pause=OwnedProcessPause(child,log_argument)
            policy=MemoryPressurePolicy(host_reserve_bytes=5*1024**3,resume_bytes=6*1024**3,anonymous_limit_bytes=10*1024**3)
            save(state='native_parent_import_running',source_sha256=identities,native_process_group=child.pid,command=command,output_directory=str(output))
            last_save=0
            while child.poll() is None:
                assert not stop_requested,'External stop requested'
                assert time.monotonic()-native_started<3600,'Physical import wall budget'
                available,anonymous=memory();action=policy.observe(available,anonymous,time.monotonic())
                if action in ('pause','resume'):
                    groups=pause.pause() if action=='pause' else pause.resume()
                    save(memory_pressure_events=record.get('memory_pressure_events',[])+[dict(action=action,groups=groups,available_bytes=available,anonymous_bytes=anonymous)])
                record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                if time.monotonic()-last_save>5:save(native_elapsed_seconds=time.monotonic()-native_started);last_save=time.monotonic()
                time.sleep(.1)
            pause.resume();terminate_process_group(child,log_argument=log_argument)
        text=console.read_text(errors='replace')
        assert child.returncode==0 and '\nTRI_ORACLE_HIERARCHICAL_FRAME132_MACRO_FLOORPLAN_FINISHED\n' in text,console
        assert all(sha(p)==h for p,h in identities.items()),'Changed synthesis input'
        save(state='native_parent_macro_import_completed_pending_report_review',native_exit_status=0,
             console_sha256=sha(console),native_elapsed_seconds=time.monotonic()-native_started,
             parent_import_sha256=sha(output/'parent_import.v'),output_database=str(output/'macro_floorplan.db'),routed_timing_qualified=False)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=str(output/'native'))
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child else None);raise
    finally:
        if lock is not None:lock.close()


if __name__=='__main__':main()
