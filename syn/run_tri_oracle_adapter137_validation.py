"""Native gate-import adapter A/B checks and exported-wrapper functional simulation."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from tri_oracle_named_controller_adapters137 import controller_adapter
from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/adapter137_binding_validation.json';assert not result.exists()
    library=root/'.cache/physical/library/tcbn28hpcplusbwp12t40p140tt1v25c.lib'
    standard=root/'.cache/physical/library/tcbn28hpcplusbwp12t40p140.v'
    units=[('down','tri_oracle_down_executor','tri_oracle_down_executor_staged','tri_oracle_down_executor_staged116','STAGED_DOWN_PASS cases=34'),
           ('dma','tri_oracle_sparse_weight_dma','tri_oracle_sparse_weight_dma_pipelined','tri_oracle_sparse_weight_dma_pipelined107','PIPELINED_DMA_PASS cases=18 reset_stages=7')]
    inputs=[Path(__file__).resolve(),root/'syn/tri_oracle_named_controller_adapters137.py',root/'syn/tri_oracle_process_guard.py',library,standard]
    for unit,legacy,mapped,dirname,marker in units:
        inputs += [root/'verilog'/(legacy+'.sv'),root/'verilog'/(mapped+'_tb.sv'),root/'.cache/physical/synthesis'/dirname/'netlist.v']
    inputs += [root/'verilog'/('tri_oracle_'+name+'.sv') for name in ['word_bank','pe_array','memory_compute']]
    identities={str(p):sha(p) for p in inputs}
    started=time.monotonic();record=dict(state='prepared',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        supervisor_pid=os.getpid(),source_sha256=identities,steps={},full_paper_results_matched=False,
        scope='Genus read_hdl-netlist mixed with a legacy SystemVerilog adapter, then Xcelium simulates the Genus-exported wrapper against the unchanged34/18-case controller scoreboards. Individual inferred-memory compute references; no full-system or physical-timing acceptance.')
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        temp=result.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2)+'\n');temp.replace(result)
    def run(command,cwd,log,log_argument):
        child=None;begin=time.monotonic()
        with log.open('w') as stream:
            child=subprocess.Popen(command,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
            try:
                while child.poll() is None:
                    available=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024
                    assert available>5*1024**3 and time.monotonic()-begin<180,'Adapter native preflight resource/time budget'
                    time.sleep(.1)
            finally:terminate_process_group(child,log_argument=log_argument)
        return child.returncode,log.read_text(errors='replace')
    save()
    try:
        with tempfile.TemporaryDirectory(prefix='adapter137_',dir=root/'.cache/physical') as directory:
            build=Path(directory)
            for unit,legacy,mapped,dirname,marker in units:
                netlist=root/'.cache/physical/synthesis'/dirname/'netlist.v'
                for mode in ['wildcard','named']:
                    label=unit+'_'+mode;folder=build/label;folder.mkdir()
                    adapter,ports=controller_adapter(root/'verilog'/(legacy+'.sv'),netlist,mapped,explicit=mode=='named')
                    adapter_path=folder/'adapter.sv';adapter_path.write_text(adapter)
                    exported=folder/'exported.v';entry=folder/'import.tcl'
                    entry.write_text('set_db max_cpus_per_server 8\nread_libs {'+str(library)+'}\nread_hdl -netlist {'+str(netlist)+'}\nread_hdl -sv {'+str(adapter_path)+'}\nelaborate '+legacy+'\nset units [get_db hinsts -if {.module.name == '+mapped+'}]\nif {[llength $units]!=1} {error BAD_ADAPTER_IMPORT}\nset_db $units .preserve true\ncheck_design -unresolved > {'+str(folder/'unresolved.rpt')+'}\nwrite_hdl > {'+str(exported)+'}\nputs ADAPTER137_EXPORT_FINISHED\nexit\n')
                    genus_log=root/'records'/('adapter137_'+label+'_genus.log')
                    command=['genus','-no_gui','-batch','-log',str(folder/'genus'),'-files',str(entry)]
                    code,text=run(command,folder,genus_log,str(folder/'genus'))
                    assert code==0 and '\nADAPTER137_EXPORT_FINISHED\n' in text and exported.is_file(),text[-3000:]
                    disconnected='Unconnected input port' in text or 'Undriven module output port' in text
                    assert disconnected==(mode=='wildcard'),(label,text[-3000:])
                    original_bench=root/'verilog'/(mapped+'_tb.sv');stimulus=original_bench.read_text()
                    pattern=r'\b'+re.escape(mapped)+r'(?=\s+dut\s*\()'
                    stimulus,changed=re.subn(pattern,legacy,stimulus);assert changed==1
                    bench=folder/'bench.sv';bench.write_text(stimulus)
                    sources=[root/'verilog'/('tri_oracle_'+name+'.sv') for name in ['word_bank','pe_array','memory_compute']]+[standard,exported,bench]
                    xrun_log=root/'records'/('adapter137_'+label+'_xcelium.log')
                    command=['/opt/cadence/bin/xrun','-64bit','-sv','-sequdp_nba_delay','-xmerror','RECOME','-top',mapped+'_tb',
                        '-xmlibdirname',str(folder/'xcelium.d'),'-l',str(folder/'xrun.log'),'-history_file',str(folder/'history'),*[str(p) for p in sources]]
                    xcode,xtext=run(command,folder,xrun_log,str(folder/'xrun.log'))
                    assert 'xcelium> run' in xtext,xtext[-3000:]
                    if mode=='named':assert xcode==0 and marker in xtext,xtext[-3000:]
                    else:assert xcode!=0 and marker not in xtext,xtext[-3000:]
                    record['steps'][label]=dict(native_genus_exit_status=code,exported_netlist_sha256=sha(exported),adapter_sha256=sha(adapter_path),
                        formal_port_names=ports,generated_adapter=adapter,generated_bench_sha256=sha(bench),genus_log_sha256=sha(genus_log),
                        expected_disconnected_diagnostic=disconnected,native_simulation_exit_status=xcode,native_simulation_log_sha256=sha(xrun_log),
                        state='explicit_exported_wrapper_functionally_passed' if mode=='named' else 'wildcard_disconnect_reproduced_and_functionally_rejected')
                    save(state='native_adapter_cases_running')
            assert all(sha(p)==h for p,h in identities.items())
            save(state='explicit_named_gate_import_adapters_qualified',native_export_and_functional_positive_cases=52,wildcard_negatives_rejected=2)
        save(temporary_build_removed=not Path(directory).exists())
    except BaseException as error:
        save(state='failed',exception=repr(error));raise


if __name__=='__main__':main()
