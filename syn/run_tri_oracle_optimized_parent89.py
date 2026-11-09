"""Queue the canonical51-case mapped test on the actual optimized parent."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'syn'))
from tri_oracle_ideal_clock import _MODULE,_INSTANCE,_mask,_connections


def core_bindings(source):
    definitions=list(_MODULE.finditer(_mask(source)))
    modules={m[1]:m for m in definitions}
    if len(modules)!=len(definitions) or 'tri_oracle_predicted_fabric' not in modules:
        raise ValueError('Missing or duplicate native parent module')
    result={}
    def walk(kind,tokens,ancestors):
        if kind in ancestors: raise ValueError('Recursive native module hierarchy')
        for instance in _INSTANCE.finditer(modules[kind][2]):
            master,name=instance[1],instance[2]
            path=tokens+[name]
            if master=='tri_oracle_sram_memory_compute':
                logical='/'.join(token.lstrip('\\') for token in path)
                match=re.search(r'clusters\[([0-4])\]\.unit/cluster/implementation/cores\[([0-3])\]$',logical)
                if not match: raise ValueError('Unrecognized original core path: '+logical)
                bit=int(match[1])*4+int(match[2])
                if bit in result: raise ValueError('Duplicate logical core: '+logical)
                if not {'rst_n','cmd_valid','cmd_ready'}<=set(_connections(instance,0)):
                    raise ValueError('Missing native core observable ports')
                result[bit]='dut.'+'.'.join(token+' ' if token.startswith('\\') else token for token in path)
            elif master in modules:
                walk(master,path,ancestors|{kind})
    walk('tri_oracle_predicted_fabric',[],set())
    if set(result)!=set(range(20)): raise ValueError('Expected20 original cores')
    return sorted(result.items())


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def process_identity(pid):
    try:
        raw=(Path('/proc')/str(pid)/'stat').read_text()
        fields=raw[raw.rfind(')')+2:].split()
        return fields[0],int(fields[19])
    except (FileNotFoundError,ProcessLookupError): return None


def main():
    os.chdir(ROOT)
    started=time.monotonic()
    queue=ROOT/'records/optimized_parent89_queue.json'
    assert not queue.exists()
    status=dict(state='waiting_for_structural_acceptance87',supervisor_pid=os.getpid(),
                started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                scope='Queued test only; not simulation execution. The candidate must pass independent structural acceptance before native simulation.')
    def save(**updates):
        status.update(updates,elapsed_seconds=time.monotonic()-started)
        temporary=queue.with_suffix('.tmp');temporary.write_text(json.dumps(status,indent=2)+'\n');temporary.replace(queue)
    save()
    try:
        audit_pid=int(os.environ['TRI_ORACLE_OPTIMIZED89_AUDIT_PID'])
        audit_identity=process_identity(audit_pid)
        auditor_command=(Path('/proc')/str(audit_pid)/'cmdline').read_bytes().split(b'\0') if audit_identity else []
        assert any(token.endswith(b'/tri_oracle_parent_candidate_acceptance.py') for token in auditor_command)
        acceptance_path=ROOT/'records/parent_candidate87_result.json'
        while True:
            accepted=json.loads(acceptance_path.read_text())
            if accepted['state']=='structure_and_original_corner_diagnostics_verified': break
            assert accepted['state']!='failed',accepted.get('exception','Candidate rejected')
            current=process_identity(audit_pid)
            assert current and current[0] not in ('Z','X') and current[1]==audit_identity[1], 'Acceptance auditor disappeared'
            assert time.monotonic()-started<14400,'Acceptance wait budget'
            save(auditor_pid=audit_pid,auditor_start_ticks=audit_identity[1],auditor_verified_live=True)
            time.sleep(2)
        for path,expected in accepted['source_and_evidence_sha256'].items():
            assert digest(path)==expected,'Changed accepted candidate evidence '+path
        while True:
            available=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024
            anonymous=int(dict(l.split() for l in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
            if available>18*1024**3 and anonymous<3*1024**3: break
            assert time.monotonic()-started<14400,'Simulation memory wait budget'
            save(state='waiting_for_simulation_memory_reserve',host_available_bytes=available,combined_anonymous_bytes=anonymous)
            time.sleep(2)
        candidate=ROOT/'.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30/restored86/full_parent.v'
        bindings=core_bindings(candidate.read_text())
        original=ROOT/'.cache/physical/run_mapped_registered_reset31.py'
        previous=json.loads((ROOT/'records/xcelium_mapped_registered_reset31_result.json').read_text())
        assert previous['state']=='passed' and previous['cases_seen']==51
        assert digest(original)==previous['source_sha256'][str(original)]
        for path,expected in previous['source_sha256'].items():
            if path.endswith('.py'): assert digest(path)==expected,'Changed proven simulation helper '+path
        source=original.read_text()
        old="Path('.cache/physical/synthesis/tri_oracle_predicted_fabric_registered_reset30/netlist.v')"
        assert source.count(old)==1
        source=source.replace(old,'Path('+repr(str(candidate.relative_to(ROOT)))+')')
        anchor="    prelude = '''"
        assert source.count(anchor)==1
        source=source.replace(anchor,'    bindings = OPTIMIZED_BINDINGS\n'+anchor)
        anchor="producer_inputs += [canonical_bench, Path('syn/run_tri_oracle_xcelium.py'),"
        assert source.count(anchor)==1
        source=source.replace(anchor,"producer_inputs += [Path('records/parent_candidate87_result.json'), Path('records/guided_parent85_result.json'), Path('records/optimized_parent89_queue.json'), Path('.cache/physical/run_mapped_registered_reset31.py'), canonical_bench, Path('syn/run_tri_oracle_xcelium.py'),")
        reset_line=next(line for line in source.splitlines() if line.startswith('    reset_check = '))
        source=source.replace(reset_line,'    reset_check = OPTIMIZED_RESET_CHECK')
        anchor="'MAPPED_THREADS':settings.threads, 'MAPPED_BINDINGS':bindings})"
        assert source.count(anchor)==1
        source=source.replace(anchor,"'MAPPED_THREADS':settings.threads, 'MAPPED_BINDINGS':bindings, 'OPTIMIZED_RESET_CHECK':OPTIMIZED_RESET_CHECK})")
        resets=''.join('  always @(negedge '+path+'.rst_n)\n    if (rst_n && !cfg_valid && !expect_error)\n      $fatal(1,"OPTIMIZED_PARENT_UNEXPECTED_CORE_RESET core=%0d cycle=%0d seed=%0d", '+str(bit)+', cycle, seed);\n' for bit,path in bindings)
        compile(source,str(original),'exec')
        save(state='starting_optimized_parent_simulation',candidate_netlist=str(candidate),
             candidate_netlist_sha256=digest(candidate),observed_core_bindings=bindings,
             native_simulation_driver_sha256=digest(original),
             adapted_driver_sha256=hashlib.sha256(source.encode()).hexdigest(),
             adapted_driver_source=source,requested_simulation_threads=18,
             acceptance_record_sha256=digest(acceptance_path))
        # The proven driver records this immutable queue in its simulation
        # inputs. Leave it unchanged until that driver's checks finish.
        sys.argv=[str(Path(__file__).resolve()),'--threads','18','predicted','--label','xcelium_optimized_parent89','--seconds','1800']
        exec(compile(source,str(original),'exec'),{'__name__':'__main__','__file__':str(Path(__file__).resolve()),
             'OPTIMIZED_BINDINGS':bindings,'OPTIMIZED_RESET_CHECK':resets})
        print('OPTIMIZED_PARENT89_CANONICAL_FUNCTIONAL_SIMULATION_PASSED',flush=True)
    except BaseException as error:
        # A started simulation binds the queue's exact bytes. Keep its record
        # unchanged; native/preparation records carry failures after launch.
        if status['state']!='starting_optimized_parent_simulation': save(state='failed',exception=repr(error))
        raise


if __name__=='__main__': main()
