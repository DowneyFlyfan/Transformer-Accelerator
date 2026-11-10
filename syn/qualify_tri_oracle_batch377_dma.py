"""Independently bind batched operand-transfer proof to native source evidence.

This qualifies a raw affine operator with prepared masks. It does not qualify
complete feedforward, hardware prediction, mapped timing or paper performance.
"""
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'records/batch377_dma_qualification.json'
    archive=root/'records/batch377_native_logs.json.gz'
    assert not output.exists() and not archive.exists()
    identities={};evidence={};logs={};groups=set();inventories=[]
    def bind(path,digest=None):
        path=str(path);actual=sha(path)
        assert digest is None or actual==digest,'Changed consumed input '+path
        assert path not in identities or identities[path]==actual
        identities[path]=actual
    fixture_path=root/'records/batch358_fixture_preparation.json'
    fixture=json.loads(fixture_path.read_text());bind(fixture_path)
    assert fixture['state']=='trained_batched_affine_fixture_scalar_cuda_equal'
    assert fixture['hidden_features']==2048 and fixture['full_trained_weight_rows']==5632
    assert fixture['full_weight_quantization_before_slice'] is True
    for p,h in fixture['files_sha256'].items():bind(p,h)
    masks=[int(word,16) for word in (Path(fixture['fixture'])/'keep.hex').read_text().split()]
    assert len(masks)==2560 and set(masks)<={0,1} and masks.count(0)==145
    specs=[
        ('batch372_green','trained_batched_operand_transfers_and_internal_fault_recovery_passed',
         [(1,0),(16,0),*[(3,f) for f in range(1,7)]],'BATCH372'),
        ('batch376_green','stalled_request_and_post_last_load_error_recovery_passed',
         [(3,7),(3,8)],'BATCH373')]
    for name,state,cases,marker_prefix in specs:
        path=root/'records'/(name+'_result.json');d=json.loads(path.read_text());bind(path)
        assert d['state']==state and d['temporary_builds_removed'] is True
        assert all(d[k] is False for k in ['current_mapped_candidate_verified','full_model_verified','full_paper_results_matched'])
        assert sorted((run['tokens'],run['fault']) for run in d['runs'])==sorted(cases)
        for p,h in d['source_sha256'].items():bind(p,h)
        groups.add(d['supervisor_pid'])
        for run in d['runs']:
            assert run['state']=='transfer_and_arithmetic_passed' and run['native_exit_status']==0
            tokens=run['tokens'];fault=run['fault'];p=Path(run['log']);bind(p,run['log_sha256'])
            content=p.read_text();logs[str(p)]=content;evidence[str(p)]=sha(p)
            assert content.count('BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600')==1
            match=re.search(marker_prefix+r'_PASS tokens=(\d+) hidden=2048 rows=160 exact_outputs=(\d+) requests=(\d+) activation_beats=(\d+) weight_beats=(\d+) stalls=(\d+) fault=(\d+)',content)
            assert match
            actual=dict(zip(['tokens','exact_outputs','requests','activation_beats','weight_beats','stalls','fault'],map(int,match.groups())))
            assert actual==run['inventory']
            union=sum(any(masks[t*160+row] for t in range(tokens)) for row in range(160))
            assert actual['tokens']==tokens and actual['fault']==fault and actual['exact_outputs']==tokens*160
            assert actual['activation_beats']==tokens*256 and actual['weight_beats']==union*256
            assert actual['requests']==16*(tokens+union) and actual['stalls']>=4
            if fault:
                drain_beats=1 if fault==2 else 17 if fault==3 else 0 if fault in [4,5] else 16
                drain_requests=0 if fault in [4,5] else 1
                assert f'{marker_prefix}_FAULT_DRAINED fault={fault} requests={drain_requests} beats={drain_beats}' in content
            assert not re.search(r'\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal',content)
            assert not Path(run['command'][run['command'].index('-xmlibdirname')+1]).parent.exists()
            groups.add(run['process_group']);inventories.append(actual)
    path=root/'records/batch375_full_result.json';d=json.loads(path.read_text());bind(path)
    assert d['state']=='short_burst_partial_rows_and_address_boundaries_passed'
    assert d['exact_output_comparisons']==525 and d['temporary_builds_removed'] is True
    assert sorted(run['fault'] for run in d['runs'])==[0,7,8,9,10]
    for p,h in d['source_sha256'].items():bind(p,h)
    groups.add(d['supervisor_pid'])
    for run in d['runs']:
        assert run['state']=='passed' and run['native_exit_status']==0 and run['owned_process_group_cleaned'] is True
        p=Path(run['log']);bind(p,run['log_sha256']);content=p.read_text();logs[str(p)]=content;evidence[str(p)]=sha(p)
        assert content.count('BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600')==1
        assert re.search(r'BATCH371_PASS tokens=3 hidden=160 rows=35 exact_outputs=105 requests=148 activation_beats=60 weight_beats=680 stalls=\d+ fault='+str(run['fault']),content)
        if run['fault']:assert f'BATCH371_FAULT_DRAINED fault={run["fault"]} requests=0 beats=0' in content
        assert not re.search(r'\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal',content)
        assert not Path(run['command'][run['command'].index('-xmlibdirname')+1]).parent.exists()
        groups.add(run['process_group'])
    for name,state,needle in [
        ('batch372_red','internal_load_error_undrained_burst_reproduced',
         'BATCH372_FAULT_NOT_DRAINED active=1 rsp_valid=1 accepted_beats=1'),
        ('batch376_red','stalled_request_cancellation_reproduced',
         'BATCH373_REQUEST_CHANGED_UNDER_STALL')]:
        path=root/'records'/(name+'_result.json');d=json.loads(path.read_text());bind(path)
        assert d['state']==state and d['temporary_builds_removed'] is True and len(d['runs'])==1
        for p,h in d['source_sha256'].items():bind(p,h)
        groups.add(d['supervisor_pid']);run=d['runs'][0];assert run['native_exit_status']==2
        p=Path(run['log']);bind(p,run['log_sha256']);content=p.read_text();logs[str(p)]=content;evidence[str(p)]=sha(p)
        assert needle in content and content.count('xmsim: *F,FATSEV')==1 and not re.search(r'BATCH37[23]_PASS tokens=',content)
        assert not Path(run['command'][run['command'].index('-xmlibdirname')+1]).parent.exists()
        groups.add(run['process_group'])
    termination_path=root/'records/batch375_termination_control.json'
    stop_path=root/'records/batch375_stop_control_result.json'
    termination=json.loads(termination_path.read_text());bind(termination_path);bind(stop_path,termination['terminal_receipt_sha256'])
    bind(root/'syn/run_tri_oracle_batch375_boundary.py',termination['runner_sha256'])
    assert termination['state']=='native_supervisor_termination_cleans_owned_groups'
    assert termination['all_owned_groups_terminal'] is True and termination['temporary_builds_removed'] is True
    assert termination['observed_live_native_groups']
    stop=json.loads(stop_path.read_text());assert stop['state']=='failed' and 'requested-stop guard' in stop['exception']
    assert all(run['owned_process_group_cleaned'] is True for run in stop['runs'])
    groups.update(termination['all_owned_groups']);groups.add(termination['supervisor_pid'])
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            fields=(p/'stat').read_text().rsplit(')',1)[1].split()
            assert not(fields[0]!='Z' and int(fields[2]) in groups),'Owned native group remains live'
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue
    payload=json.dumps(logs,sort_keys=True,separators=(',',':')).encode()
    archive.write_bytes(gzip.compress(payload,mtime=0));assert json.loads(gzip.decompress(archive.read_bytes()))==logs
    full=next(x for x in inventories if x['tokens']==16 and x['fault']==0)
    assert (full['activation_beats']+full['weight_beats'])*8==360448
    result=dict(state='trained_batched_operand_transfer_source_qualified',
        verified_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),qualifier_sha256=sha(__file__),
        source_and_evidence_sha256=identities,native_logs=len(logs),logs_archive_sha256=sha(archive),
        logs_archive_lossless_verified=True,actual_cores=20,actual_clusters=5,actual_vendor_memory_models=600,
        trained_hidden_features=2048,trained_original_output_rows=160,
        trained_output_comparisons=6560,literal_boundary_output_comparisons=525,
        total_output_comparisons=7085,exact_old_fault_counterfactuals=2,
        trained_fault_recovery_cases=8,literal_invalid_descriptor_recovery_cases=4,
        native_supervisor_termination_verified=True,all_owned_groups_terminal=True,temporary_builds_removed=True,
        activations_read_once_per_descriptor=True,each_union_retained_weight_read_once_per_descriptor=True,
        full_batch_native_bus_bytes=360448,full_batch_native_read_requests=2816,
        original_channel_id_extremes_verified_on_literal_boundary=[0,65535],
        architecture_scope='Batched raw affine projection, prepared token-specific masks, native memories and local bus/controller choices.',
        complete_gated_feedforward_verified=False,hardware_prediction_integrated=False,
        current_mapped_candidate_verified=False,whole_model_execution_verified=False,
        routed_timing_qualified=False,paper300_release_authorized=False,full_paper_results_matched=False,
        scope=__doc__)
    output.write_text(json.dumps(result,indent=2)+'\n')
    print('BATCH377_QUALIFIED comparisons=7085 native_logs=17 full_batch_bus_bytes=360448',flush=True)


if __name__=='__main__':main()
