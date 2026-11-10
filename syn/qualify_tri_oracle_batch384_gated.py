"""Bind paired projection, nonlinear, precision and queue-error source evidence.

Prepared masks, local fixed-point formats and captured first-layer inputs.
No down projection, complete feedforward, model accuracy, timing or paper claim.
"""
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/batch384_gated_qualification.json'
    archive=root/'records/batch384_native_logs.json.gz'
    assert not result.exists() and not archive.exists()
    identities={};logs={};groups=set();inventories=[]
    def bind(path,digest=None):
        p=Path(path)
        if not p.is_absolute():p=root/p
        key=str(p);actual=sha(p)
        assert digest is None or digest==actual,'Changed bound input '+key
        assert key not in identities or identities[key]==actual
        identities[key]=actual
    fixture_path=root/'records/batch379_fixture_preparation.json';fixture=json.loads(fixture_path.read_text());bind(fixture_path)
    assert fixture['state']=='trained_paired_gated_fixture_scalar_cuda_equal'
    assert (fixture['token_rows'],fixture['hidden_features'],fixture['full_trained_channels'])==(16,2048,5632)
    assert fixture['selected_channels']==[i*71 for i in range(80)]
    assert fixture['full_weight_quantization_before_selection'] and fixture['independent_scalar_masks_projection_and_nonlinear_equal']
    assert fixture['activation_codes_equal_prior358'] and fixture['predicted_skipped_pairs']==76
    for key in ['source_sha256','files_sha256']:
        for p,h in fixture[key].items():bind(p,h)
    guard_path=root/'records/batch379_gpu_guard_result.json';guard=json.loads(guard_path.read_text());bind(guard_path)
    assert guard['state']=='completed' and guard['native_exit_status']==0 and guard['input_drift']==[]
    assert guard['summary_sha256']==sha(fixture_path)
    for p,h in guard['source_sha256'].items():bind(p,h)
    gpu_log=root/'.cache/batch379_gpu_native.log';bind(gpu_log,guard['native_log_sha256']);logs[str(gpu_log)]=gpu_log.read_text()
    assert 'BATCH379_TRAINED_PAIRED_FIXTURE_READY 76 skipped' in logs[str(gpu_log)]
    groups.update([guard['supervisor_pid'],guard['child_pid']])
    architecture_path=root/'records/batch379_architecture_validation.json'
    architecture=json.loads(architecture_path.read_text());bind(architecture_path)
    assert architecture['source_audits_completed']==3 and architecture['render_visually_verified'] is True
    assert architecture['inherited_model_page_pixel_identical'] is True
    bind(architecture['pdf'],architecture['pdf_sha256'])
    for p,h in architecture['source_sha256'].items():bind(p,h)
    masks=[int(v,16) for v in (Path(fixture['fixture'])/'keep.hex').read_text().split()]
    assert len(masks)==1280 and set(masks)<={0,1}
    specs=[('batch380','trained_batched_paired_projection_and_nonlinear_source_passed',
            [(1,0),(16,0),(3,1),(3,2),(3,3)],'BATCH380'),
           ('batch381','queued_raw_and_activation_fault_drain_and_recovery_passed',
            [(3,4),(3,5)],'BATCH381')]
    for name,state,cases,prefix in specs:
        path=root/'records'/(name+'_source_result.json');d=json.loads(path.read_text());bind(path)
        assert d['state']==state and d['temporary_builds_removed'] is True
        assert all(d[k] is False for k in ['current_mapped_candidate_verified','complete_feedforward_verified','whole_model_verified','full_paper_results_matched'])
        for p,h in d['source_sha256'].items():bind(p,h)
        assert sorted((r['tokens'],r['case']) for r in d['runs'])==sorted(cases)
        groups.add(d['supervisor_pid'])
        for run in d['runs']:
            assert run['state']=='paired_projection_nonlinear_and_transfers_passed' and run['native_exit_status']==0
            p=Path(run['log']);bind(p,run['log_sha256']);content=p.read_text();logs[str(p)]=content
            assert content.count('BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600')==1
            match=re.search(prefix+r'_PASS tokens=(\d+) hidden=2048 rows=80 gated_words=(\d+) down_words=(\d+) requests=(\d+) activation_beats=(\d+) gate_beats=(\d+) up_beats=(\d+) stalls=(\d+) case=(\d+)',content)
            assert match
            actual=dict(zip(['tokens','gated_words','down_words','requests','activation_beats','gate_beats','up_beats','stalls','case'],map(int,match.groups())))
            assert actual==run['inventory'] and actual['tokens']==run['tokens'] and actual['case']==run['case']
            n=run['tokens'];kind=run['case'];union=0 if kind==3 else sum(any(masks[t*80+row] for t in range(n)) for row in range(80))
            assert actual['gated_words']==actual['down_words']==n*80
            assert actual['activation_beats']==n*256 and actual['gate_beats']==actual['up_beats']==union*256
            assert actual['requests']==n*16+union*32 and actual['stalls']>=4
            if kind in [1,2,4,5]:assert f'{prefix}_FAULT_DRAINED case={kind} ' in content
            if kind in [4,5]:assert f'{prefix}_RAW_OWNER_DRAINED packets=3 case={kind}' in content
            if kind==1:assert re.search(prefix+r'_FAULT_DRAINED case=1 requests=\d+ up_beats=16',content)
            if kind==2:assert prefix+'_FAULT_DRAINED case=2 requests=0 up_beats=0' in content
            assert not re.search(r'\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal',content)
            assert not Path(run['command'][run['command'].index('-xmlibdirname')+1]).parent.exists()
            groups.add(run['process_group']);inventories.append(actual)
    path=root/'records/batch383_controls_result.json';d=json.loads(path.read_text());bind(path)
    assert d['state']=='all_shift_boundaries_and_omitted_wrapper_checks_verified' and d['temporary_builds_removed'] is True
    assert {r['label'] for r in d['runs']}=={'quantization','raw_count','activation_tag'}
    for p,h in d['source_sha256'].items():bind(p,h)
    groups.add(d['supervisor_pid'])
    production=(root/'verilog/tri_oracle_batched_gated380.sv').read_text()
    for run in d['runs']:
        p=Path(run['log']);bind(p,run['log_sha256']);content=p.read_text();logs[str(p)]=content
        assert content.count('BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600')==1
        if run['label']=='quantization':
            assert run['native_exit_status']==0 and run['state']=='passed'
            assert 'BATCH382_QUANT_PASS shifts=64 exact_comparisons=2324 signed_minima_rounding_ties_saturation=1' in content
            assert not re.search(r'\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal',content)
        else:
            assert run['native_exit_status']==2 and run['state']=='omitted_fault_check_rejected'
            assert content.count('xmsim: *F,FATSEV')==1 and 'BATCH381_OUTPUT_METADATA' in content and 'BATCH381_PASS tokens=' not in content
            old=run['one_replacement']['before'];new=run['one_replacement']['after']
            assert production.count(old)==1
            assert hashlib.sha256(production.replace(old,new).encode()).hexdigest()==run['compile_overlay_sha256']
        assert not Path(run['command'][run['command'].index('-xmlibdirname')+1]).parent.exists()
        groups.add(run['process_group'])
    # Auxiliary GPU PIDs belong to another PID namespace. Check that container
    # separately in the publication check; native simulation groups are local.
    local_groups=groups-{guard['supervisor_pid'],guard['child_pid']}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            fields=(p/'stat').read_text().rsplit(')',1)[1].split()
            assert not(fields[0]!='Z' and int(fields[2]) in local_groups),'Owned native group remains live'
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue
    payload=json.dumps(logs,sort_keys=True,separators=(',',':')).encode();archive.write_bytes(gzip.compress(payload,mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes()))==logs
    assert len(logs)==11 and sum(x['gated_words'] for x in inventories)==2560
    full=next(x for x in inventories if x['tokens']==16 and x['case']==0)
    assert (full['activation_beats']+full['gate_beats']+full['up_beats'])*8==360448
    report=dict(state='trained_batched_paired_projection_and_gating_source_qualified',
        verified_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),qualifier_sha256=sha(__file__),
        source_and_evidence_sha256=identities,logs_archive_sha256=sha(archive),logs_archive_lossless_verified=True,native_logs=len(logs),
        actual_cores=20,actual_clusters=5,actual_vendor_memory_models=600,hidden_features=2048,
        selected_original_channels=fixture['selected_channels'],full_trained_channels=5632,
        raw_projection_comparisons=5120,gated16_comparisons=2560,down_input8_comparisons=2560,
        total_data_comparisons=10240,quantization_comparisons=2324,all64_nonnegative_shifts_checked=True,
        native_omitted_fault_check_counterfactuals=2,queued_raw_packets_drained_each_error=3,
        successful_full_batch_read_bytes=360448,successful_full_batch_read_requests=2816,
        all_local_native_workers_terminal=True,temporary_builds_removed=True,
        prepared_prediction_masks=True,numerical_formats_are_local_reconstruction=True,
        down_projection_verified=False,complete_feedforward_verified=False,whole_model_execution_verified=False,
        current_mapped_candidate_verified=False,routed_timing_qualified=False,paper300_release_authorized=False,
        full_paper_results_matched=False,scope=__doc__)
    result.write_text(json.dumps(report,indent=2)+'\n')
    print('BATCH384_QUALIFIED data_comparisons=10240 quantization_comparisons=2324 native_logs=11',flush=True)


if __name__=='__main__':main()
