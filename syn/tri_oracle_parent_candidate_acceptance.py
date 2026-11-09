"""Bind a guided candidate to accepted core data and every reset endpoint."""
import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
HEADER = ['endpoint','registered_depth','registered_sources','masters','clock_nets']


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def require_snapshot_binding(path, accepted_sha256):
    path = Path(path)
    expected = accepted_sha256.get(str(path))
    if not expected:
        raise ValueError('Missing accepted snapshot digest: '+str(path))
    actual = digest(path)
    if actual != expected:
        raise ValueError('Changed accepted snapshot digest: '+str(path))
    return actual


def read_topology(path):
    result = {}
    with Path(path).open() as stream:
        reader=csv.DictReader(stream,delimiter='\t')
        if reader.fieldnames != HEADER:
            raise ValueError('Malformed reset topology header')
        for row in reader:
            endpoint=row['endpoint']
            if not endpoint or endpoint in result:
                raise ValueError('Duplicate or empty reset endpoint: '+str(endpoint))
            depth=int(row['registered_depth'])
            chain=tuple(tuple(row[key].split(',')) for key in HEADER[2:])
            if depth<=0 or any(len(values)!=depth or any(not value for value in values) for values in chain):
                raise ValueError('Malformed reset chain: '+endpoint)
            result[endpoint]=(depth,*chain)
    return result


def require_reset_topology(baseline, candidate):
    before,after=read_topology(baseline),read_topology(candidate)
    cores={f'fabric/clusters[{cluster}].unit/cluster/implementation/cores[{core}]/rst_n'
           for cluster in range(5) for core in range(4)}
    actual_cores={name for name in before if not name.startswith('prediction/')}
    prediction={name for name in before if name.startswith('prediction/')}
    if actual_cores!=cores or len(prediction)!=961:
        raise ValueError('Accepted reset endpoint set is incomplete')
    for name in cores:
        depth,sources,_,clocks=before[name]
        if depth!=2 or sources!=('fabric/child_rst_n_reg','child_rst_n_reg') or clocks!=('clk','clk'):
            raise ValueError('Accepted core reset topology is unexpected: '+name)
    for name in prediction:
        depth,sources,_,clocks=before[name]
        if depth!=1 or sources!=('child_rst_n_reg',) or clocks!=('clk',):
            raise ValueError('Accepted prediction reset topology is unexpected: '+name)
    if set(before)!=set(after):
        raise ValueError('Reset endpoint set changed')
    for name,chain in before.items():
        if after[name]!=chain:
            raise ValueError('Reset topology changed: '+name)
    return dict(core_endpoints=len(cores),prediction_endpoints=len(prediction),
                all_endpoint_registers_masters_clocks_and_depths_preserved=True,
                baseline_sha256=digest(baseline),candidate_sha256=digest(candidate),
                scope='Exact per-endpoint registered ancestor topology. Does not establish recovery/removal timing or reset-wire inverter parity.')


def process_identity(pid):
    try:
        raw=(Path('/proc')/str(pid)/'stat').read_text()
        values=raw[raw.rfind(')')+2:].split()
        return (values[0],int(values[19]))
    except (FileNotFoundError,ProcessLookupError):
        return None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait',action='store_true')
    args=parser.parse_args()
    sys.path.insert(0,str(ROOT/'syn'))
    from tri_oracle_artifact_fingerprint import artifact_fingerprint
    from tri_oracle_core_preservation import verify_core_snapshots
    from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
    started=time.monotonic()
    result_path=ROOT/'records/parent_candidate87_result.json'
    assert not result_path.exists()
    result=dict(state='checking',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                routed_timing_closure_qualified=False,full_paper_results_matched=False)
    def save(**updates):
        result.update(updates,elapsed_seconds=time.monotonic()-started)
        temporary=result_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(result,indent=2)+'\n');temporary.replace(result_path)
    save()
    try:
        producer_path=ROOT/'records/guided_parent85_result.json'
        producer=json.loads(producer_path.read_text())
        owner=producer['supervisor_pid']
        identity=process_identity(owner)
        while producer['state']!='restored_full_model_diagnostics_completed':
            assert args.wait, 'Guided candidate has not completed'
            assert producer['state']!='failed', producer.get('exception','Guided candidate failed')
            current=process_identity(owner)
            assert identity and current and current[1]==identity[1] and current[0] not in ('Z','X'), 'Guided candidate owner disappeared'
            assert time.monotonic()-started<10800, 'Guided candidate wait budget'
            save(state='waiting_for_verified_live_guided85',producer_pid=owner,
                 producer_start_ticks=identity[1],producer_state=producer['state'])
            time.sleep(2)
            producer=json.loads(producer_path.read_text())
        assert producer['native_exit_status']==0 and producer['all3_original_corners_diagnosed']
        placement_path=ROOT/'records/predicted_fabric_placement79_result.json'
        placement=json.loads(placement_path.read_text())
        parent=ROOT/'.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30'
        baseline=parent/'placement79/core_after.tsv'
        accepted=placement['core_preservation']['input_sha256']
        baseline_digest=require_snapshot_binding(baseline,accepted)
        reset_baseline=parent/'placement79/registered_reset_roots.tsv'
        assert digest(reset_baseline)==placement['native_registered_reset_report_sha256']
        identities={str(path):digest(path) for path in [Path(__file__).resolve(),producer_path,placement_path,
            ROOT/'syn/test_tri_oracle_parent_candidate_acceptance.py',ROOT/'records/parent_candidate87_green.log',baseline,reset_baseline]}
        green=(ROOT/'records/parent_candidate87_green.log').read_text()
        assert re.search(r'Ran 10 tests\b',green) and '\nOK\n' in green
        for path,expected in producer['source_sha256'].items():
            assert digest(path)==expected,'Changed candidate source '+path
            identities[path]=expected
        resets={}
        for stage in ['guided85','restored86']:
            resets[stage]=require_reset_topology(reset_baseline,parent/stage/'registered_reset_roots.tsv')
            identities[str(parent/stage/'registered_reset_roots.tsv')]=resets[stage]['candidate_sha256']
        complete=verify_core_snapshots(baseline,parent/'restored86/full_after.tsv',
                    (parent/'restored86/core_prefixes.txt').read_text().splitlines())
        assert complete['total_original_cells']==1889420
        dependencies={}
        base=ROOT/'.cache/physical/pnr/tri_oracle_sram_memory_compute'
        for dirname,filename in [('hierarchy_full_control_68','sram_core_hierarchy68_full_control_validation.json'),
                                 ('hierarchy_export_58','sram_core_hierarchy58_export_validation.json')]:
            expected=json.loads((ROOT/'records'/filename).read_text())['output_artifact_fingerprint']
            assert artifact_fingerprint(base/dirname)==expected
            dependencies[base/dirname/'ilm']={'type':'directory','files':{
                k[4:]:v for k,v in expected['files'].items() if k.startswith('ilm/')}}
        checkpoint=Path(producer['output_database'])
        assert hierarchy_fingerprint(checkpoint,directory_dependencies=dependencies)==producer['output_database_fingerprint']
        corners=producer['separate_corner_diagnostics']
        assert set(corners)=={'setup_slow','setup_typ','hold_fast'}
        for view,corner in corners.items():
            out=Path(corner['output_directory'])
            assert corner['native_exit_status']==0 and digest(out/'console.log')==corner['console_sha256']
            with (out/'slack_properties.tsv').open() as stream: rows=list(csv.DictReader(stream,delimiter='\t'))
            assert len(rows)==1 and rows[0]['view']==view and float(rows[0]['slack_ns'])==corner['slack_ns']
            for name in ['console.log','slack_properties.tsv','core_counts.tsv']:
                identities[str(out/name)]=digest(out/name)
        assert require_snapshot_binding(baseline,accepted)==baseline_digest
        for path,expected in identities.items(): assert digest(path)==expected,'Changed acceptance input '+path
        save(state='structure_and_original_corner_diagnostics_verified',source_and_evidence_sha256=identities,
             accepted_core_snapshot_sha256=baseline_digest,complete_core_preservation=complete,
             exact_registered_reset_topology=resets,original_corner_slacks_ns={k:v['slack_ns'] for k,v in corners.items()},
             all_original_corner_slacks_nonnegative=all(v['slack_ns']>=0 for v in corners.values()),
             scope='Complete original core preservation and exact registered-reset ancestor topology for this candidate. Three original pre-clock timing diagnostics, not final routed timing or complete processor/paper qualification.')
        print('PARENT_CANDIDATE87_ACCEPTANCE_GAPS_CLOSED',flush=True)
    except BaseException as error:
        save(state='failed',exception=repr(error));raise


if __name__=='__main__': main()
