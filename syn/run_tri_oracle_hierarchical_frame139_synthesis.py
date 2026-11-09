"""Synthesize the fully staged prepared-frame parent, retaining all twenty core macros."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_checked_controller_adapters138 import checked_controller_adapter


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/frame139_synthesis_result.json'
    output=root/'.cache/physical/synthesis/tri_oracle_predicted_feedforward_hierarchical139'
    assert not result.exists() and not output.exists()
    started=time.monotonic();child=None;pause=None;lock=None;stop_requested=False
    entry=root/'syn/tri_oracle_synthesize_hierarchical_frame139.tcl'
    positive=root/'records/staged119_fullshape_result.json'
    record=dict(state='waiting_for_current_full_frame_simulation',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                supervisor_pid=os.getpid(),requested_maximum_cpu_workers=18,
                optimization_and_reported_period_ns=1.72414,full_paper_results_matched=False,
                native_anonymous_limit_bytes=16*1024**3,host_reserve_bytes=5*1024**3,retry_of='records/frame134_synthesis_result.json',explicit_adapter_ports=True,generic_optimization_effort='low',technology_mapping_effort='medium',final_optimization_effort='medium',reuse_mapped_controllers=True,
                scope='Provisional parent synthesis of the prepared prediction/FFN frame with staged projection and down controllers. Twenty extracted core80 timing-model cells,40 compiled aggregate memories,20 preserved mapped down controllers and5 preserved mapped projection controllers. Full core68 model restoration is required before final timing. No whole-chip route or paper metric claim.')
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        temp=result.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2)+'\n');temp.replace(result)
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
            assert not stop_requested and time.monotonic()-started<7200,'Prerequisite simulation wait expired'
            if positive.exists():
                passed=json.loads(positive.read_text())
                if passed['state']=='passed':break
                assert passed['state'] not in ['failed','yielded_to_physical_memory_reserve'],'Prerequisite simulation failed'
            time.sleep(2)
        assert passed['cases_seen']==12 and passed['returned_hidden_outputs_checked']==4420
        assert passed['actual_staged_down_adapter_instances']==20 and passed['actual_staged_projection_adapter_instances']==5
        assert all(sha(p)==h for p,h in passed['source_sha256'].items())
        mapping=root/'records/down120_mapped_functional_qualification.json'
        mapped=json.loads(mapping.read_text());assert mapped['state']=='staged_down_mapped_functional_qualified'
        assert all(sha(p)==h for p,h in mapped['current_source_sha256'].items())
        dma_qpath=root/'records/pipeline107_mapped_functional_qualification.json'
        dma_q=json.loads(dma_qpath.read_text());assert dma_q['state']=='mapped_staged_address_generator_functional_qualified'
        assert all(sha(p)==h for p,h in dma_q['current_source_sha256'].items())
        down_netlist=root/'.cache/physical/synthesis/tri_oracle_down_executor_staged116/netlist.v'
        dma_netlist=root/'.cache/physical/synthesis/tri_oracle_sparse_weight_dma_pipelined107/netlist.v'
        assert sha(down_netlist)==mapped['current_source_sha256'][str(down_netlist)]
        assert sha(dma_netlist)==dma_q['mapped_netlist_sha256']
        prior_path=root/'.cache/physical/synthesis/tri_oracle_predicted_fabric_registered_reset30/input_revision.json'
        prior=json.loads(prior_path.read_text())
        for p,h in prior['candidate_rtl_inventory'].items():assert sha(root/p)==h,'Original frozen source changed '+p
        libraries=[Path(p) for p in prior['library_list'].split()]
        libraries=[p if p.is_absolute() else root/p for p in libraries]
        bundle=passed['compiled_bundle']
        # Source-level core macros become extracted library cells; vendor memory
        # behavior and testbench are replaced by their matched timing libraries.
        kept=[];compiled_sources=[];removed=[]
        for line in bundle.splitlines():
            if line.startswith('`define ') and line!='`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC':
                removed.append(line);continue
            if line.strip().startswith('initial $display("JOINED_STAGED_'):
                removed.append(line);continue
            match=re.fullmatch(r'`include "([^"]+)"',line)
            if match:
                p=Path(match.group(1))
                if p.parent!=root/'verilog' or p.name in ['tri_oracle_pe_array.sv','tri_oracle_sram_memory_compute.sv','tri_oracle_predicted_feedforward_frame_tb.sv','tri_oracle_down_executor_staged.sv','tri_oracle_sparse_weight_dma_pipelined.sv']:
                    removed.append(line);continue
                compiled_sources.append(p)
            kept.append(line)
        assert len(compiled_sources)==15 and len(compiled_sources)==len(set(compiled_sources))
        assert root/'verilog/tri_oracle_down_executor_staged.sv' not in compiled_sources
        assert root/'verilog/tri_oracle_sparse_weight_dma_pipelined.sv' not in compiled_sources
        assert root/'verilog/tri_oracle_down_executor.sv' not in compiled_sources
        assert root/'verilog/tri_oracle_sparse_weight_dma.sv' not in compiled_sources
        compiled_bundle='\n'.join(kept)+'\n'
        adapter_qpath=root/'records/adapter138_binding_validation.json'
        adapter_q=json.loads(adapter_qpath.read_text());assert adapter_q['state']=='guarded_explicit_named_gate_import_adapters_qualified'
        assert all(sha(p)==h for p,h in adapter_q['source_sha256'].items())
        explicit_interfaces={}
        for unit,legacy,imported,netlist,field in [
            ('down','tri_oracle_down_executor','tri_oracle_down_executor_staged',down_netlist,'down_interface_adapter'),
            ('dma','tri_oracle_sparse_weight_dma','tri_oracle_sparse_weight_dma_pipelined',dma_netlist,'legacy_interface_adapter')]:
            named,interface=checked_controller_adapter(root/'verilog'/(legacy+'.sv'),netlist,imported)
            assert hashlib.sha256(named.encode()).hexdigest()==adapter_q['steps'][unit+'_named']['adapter_sha256']
            implicit='\n'.join(line for line in passed[field].splitlines() if not line.strip().startswith('initial $display("JOINED_STAGED_'))+'\n'
            assert compiled_bundle.count(implicit)==1
            compiled_bundle=compiled_bundle.replace(implicit,named)
            explicit_interfaces[imported]=interface
        assert ' implementation (.*);' not in compiled_bundle

        assert compiled_bundle.count('module tri_oracle_down_executor (')==1
        assert compiled_bundle.count('module tri_oracle_sparse_weight_dma (')==1
        identities={str(p):sha(p) for p in [Path(__file__).resolve(),entry,positive,mapping,dma_qpath,adapter_qpath,root/'syn/tri_oracle_named_controller_adapters137.py',root/'syn/tri_oracle_checked_controller_adapters138.py',down_netlist,dma_netlist,prior_path,*compiled_sources,*libraries,
            root/'verilog/tri_oracle_down_executor.sv',root/'verilog/tri_oracle_sparse_weight_dma.sv',
            root/'records/sram_core_timing_model80_export_validation.json',root/'records/sram_core_timing_model81_comparison.json',
            root/'syn/tri_oracle_memory_pressure_guard.py',root/'syn/tri_oracle_process_guard.py',
            Path('/opt/cadence/GENUS251/doc/genus_attref/syn_generic_effort.html'),Path('/opt/cadence/GENUS251/doc/genus_user/Setting_Effort_Levels.html')]}
        while True:
            available,anonymous=memory()
            if available>14*1024**3 and anonymous<3*1024**3:break
            assert not stop_requested and time.monotonic()-started<10800,'Initial synthesis headroom wait expired'
            save(state='waiting_for_initial_memory_headroom');time.sleep(2)
        output.mkdir()
        lock=(output/'guard.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        (output/'compiled_cluster_sources.sv').write_text(compiled_bundle)
        (output/'input_revision.json').write_text(json.dumps(dict(source_sha256=identities,
            compiled_bundle=compiled_bundle,explicit_controller_interfaces=explicit_interfaces,removed_simulation_only_lines=removed,
            simulated_bundle_sha256=passed['compiled_bundle_sha256'],library_list=[str(p) for p in libraries],
            extracted_core_model_is_provisional=True),indent=2)+'\n')
        log_argument=str(output/'native');console=output/'console.log'
        command=['genus','-no_gui','-batch','-log',log_argument,'-files',str(entry)]
        native_started=time.monotonic()
        with console.open('w') as stream:
            child=subprocess.Popen(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
                start_new_session=True,env=dict(os.environ,TRI_ORACLE_SYNTH_OUTPUT=str(output),
                TRI_ORACLE_REUSE_DOWN_NETLIST=str(down_netlist),TRI_ORACLE_REUSE_DMA_NETLIST=str(dma_netlist),TRI_ORACLE_TOP='tri_oracle_predicted_feedforward_frame',TRI_ORACLE_LIBS=' '.join(str(p) for p in libraries)))
            pause=OwnedProcessPause(child,log_argument)
            policy=MemoryPressurePolicy(host_reserve_bytes=5*1024**3,resume_bytes=6*1024**3,anonymous_limit_bytes=16*1024**3)
            save(state='native_parent_synthesis_running',source_sha256=identities,native_process_group=child.pid,command=command,output_directory=str(output),
                initial_memory_available_bytes=available,compiled_bundle_sha256=sha(output/'compiled_cluster_sources.sv'))
            last_save=0
            while child.poll() is None:
                assert not stop_requested,'External stop requested'
                assert time.monotonic()-native_started<7200,'Full-parent synthesis wall budget'
                available,anonymous=memory();action=policy.observe(available,anonymous,time.monotonic())
                if action in ('pause','resume'):
                    groups=pause.pause() if action=='pause' else pause.resume()
                    save(memory_pressure_events=record.get('memory_pressure_events',[])+[dict(action=action,groups=groups,available_bytes=available,anonymous_bytes=anonymous)])
                record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                if time.monotonic()-last_save>5:
                    save(native_elapsed_seconds=time.monotonic()-native_started,current_host_available_bytes=available,current_combined_anonymous_bytes=anonymous);last_save=time.monotonic()
                time.sleep(.2)
            pause.resume();terminate_process_group(child,log_argument=log_argument)
        text=console.read_text(errors='replace')
        assert child.returncode==0 and '\nTRI_ORACLE_FRAME139_SYNTHESIS_PASS tri_oracle_predicted_feedforward_frame\n' in text,console
        assert all(sha(p)==h for p,h in identities.items()),'Changed synthesis input'
        save(state='native_parent_mapping_completed_pending_report_review',native_exit_status=0,
             console_sha256=sha(console),native_elapsed_seconds=time.monotonic()-native_started,
             output_netlist_sha256=sha(output/'netlist.v'),routed_timing_qualified=False)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=str(output/'native'))
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child else None);raise
    finally:
        if lock is not None:lock.close()


if __name__=='__main__':main()
