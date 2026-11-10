"""Qualify full-width streamed down projection from bound native evidence.

Prepared canonical down inputs, selected160 original outputs. Not complete
feedforward integration, mapped execution, model accuracy or paper performance.
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
    output=root/'records/batch388_stream_qualification.json';archive=root/'records/batch388_native_logs.json.gz'
    assert not output.exists() and not archive.exists()
    identities={};logs={};groups=set();inventories=[]
    def bind(path,digest=None):
        p=Path(path)
        if not p.is_absolute():p=root/p
        actual=sha(p);key=str(p)
        assert digest is None or digest==actual,'Changed input '+key
        assert key not in identities or identities[key]==actual
        identities[key]=actual
    fixture_path=root/'records/batch386_fixture_preparation.json';fixture=json.loads(fixture_path.read_text());bind(fixture_path)
    assert fixture['state']=='full_width_trained_down_fixture_scalar_cuda_equal'
    assert (fixture['token_rows'],fixture['input_features'],fixture['full_trained_output_rows'])==(16,5632,2048)
    assert fixture['selected_output_rows']==[i*2047//159 for i in range(160)]
    for key in ['full_weight_quantization_before_selection','complete_canonical_output_reconstruction_equal',
                'prior379_gated_and_down_subsets_equal','independent_scalar_dot_outputs_equal']:
        assert fixture[key] is True
    for key in ['source_sha256','files_sha256']:
        for p,h in fixture[key].items():bind(p,h)
    guard_path=root/'records/batch386_gpu_guard_result.json';guard=json.loads(guard_path.read_text());bind(guard_path)
    assert guard['state']=='completed' and guard['native_exit_status']==0 and guard['input_drift']==[]
    assert guard['summary_sha256']==sha(fixture_path)
    for p,h in guard['source_sha256'].items():bind(p,h)
    gpu_log=root/'.cache/batch386_gpu_native.log';bind(gpu_log,guard['native_log_sha256']);logs[str(gpu_log)]=gpu_log.read_text()
    assert 'BATCH386_FULL_WIDTH_DOWN_FIXTURE_READY' in logs[str(gpu_log)]
    architecture_path=root/'records/batch386_architecture_validation.json';a=json.loads(architecture_path.read_text());bind(architecture_path)
    assert a['source_audits_completed']==3 and a['render_visually_verified'] is True and a['inherited_model_page_pixel_identical'] is True
    bind(a['pdf'],a['pdf_sha256'])
    for p,h in a['source_sha256'].items():bind(p,h)
    values=[int(v,16) for v in (Path(fixture['fixture'])/'activation.hex').read_text().split()]
    assert len(values)==16*5632 and all(0<=v<=255 for v in values)
    path=root/'records/batch385_green_result.json';d=json.loads(path.read_text());bind(path)
    assert d['state']=='full_width_trained_streamed_down_projection_passed' and d['temporary_builds_removed'] is True
    assert all(d[k] is False for k in ['current_mapped_candidate_verified','complete_feedforward_verified','whole_model_verified','full_paper_results_matched'])
    assert sorted((r['tokens'],r['fault']) for r in d['runs'])==[(1,0),(3,6),(3,7),(8,0),(16,0)]
    for p,h in d['source_sha256'].items():bind(p,h)
    groups.add(d['supervisor_pid'])
    for run in d['runs']:
        assert run['state']=='streamed_down_projection_and_transfers_passed' and run['native_exit_status']==0
        p=Path(run['log']);bind(p,run['log_sha256']);content=p.read_text();logs[str(p)]=content
        assert content.count('BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600')==1
        match=re.search(r'BATCH385_PASS tokens=(\d+) hidden=5632 rows=160 exact_outputs=(\d+) requests=(\d+) activation_beats=(\d+) weight_beats=(\d+) stalls=(\d+) fault=(\d+)',content)
        tiles=re.search(r'BATCH385_STREAMED_INVENTORY tiles=(\d+) active_words=(\d+) weight_bursts_per_row=(\d+)',content)
        assert match and tiles
        actual=dict(zip(['tokens','exact_outputs','requests','activation_beats','weight_beats','stalls','fault'],map(int,match.groups())))
        tile_actual=dict(zip(['tiles','active_words','weight_bursts_per_row'],map(int,tiles.groups())))
        assert actual==run['inventory'] and tile_actual==run['tile_inventory']
        n=run['tokens'];fault=run['fault']
        active=[fault!=6 and any(values[t*5632+word*8+lane]!=0 for t in range(n) for lane in range(8)) for word in range(704)]
        bursts=0
        for part in range(4):
            for tile in range(0,176,32):
                cursor=tile;end=min(tile+32,176)
                while cursor<end:
                    if not active[part*176+cursor]:cursor+=1
                    else:
                        length=1
                        while length<16 and cursor+length<end and active[part*176+cursor+length]:length+=1
                        bursts+=1;cursor+=length
        assert tile_actual==dict(tiles=6,active_words=sum(active),weight_bursts_per_row=bursts)
        assert actual['tokens']==n and actual['fault']==fault and actual['exact_outputs']==n*160
        assert actual['activation_beats']==n*704 and actual['weight_beats']==160*sum(active)
        assert actual['requests']==n*44+160*bursts and actual['stalls']>=4
        if fault==7:
            assert 'BATCH385_PARTIAL_TILES_BEFORE_ERROR completed=2' in content and 'BATCH385_FAULT_DRAINED fault=7 ' in content
        if fault==6:assert actual['weight_beats']==0 and actual['requests']==132
        assert not re.search(r'\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal',content)
        assert not Path(run['command'][run['command'].index('-xmlibdirname')+1]).parent.exists()
        groups.add(run['process_group']);inventories.append(actual)
    path=root/'records/batch385_red_result.json';red=json.loads(path.read_text());bind(path)
    assert red['state']=='resident_full_width_batch_limit_reproduced' and red['temporary_builds_removed'] is True
    for p,h in red['source_sha256'].items():bind(p,h)
    groups.add(red['supervisor_pid']);assert len(red['runs'])==1
    run=red['runs'][0];assert run['native_exit_status']==2 and run['state']=='resident_capacity_limit_verified'
    p=Path(run['log']);bind(p,run['log_sha256']);content=p.read_text();logs[str(p)]=content
    assert content.count('xmsim: *F,FATSEV')==1 and 'BATCH385_DONE_METADATA' in content and 'BATCH385_PASS tokens=' not in content
    assert 'BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in content
    assert not Path(run['command'][run['command'].index('-xmlibdirname')+1]).parent.exists();groups.add(run['process_group'])
    path=root/'records/batch387_clear_control.json';clear=json.loads(path.read_text());bind(path)
    assert clear['state']=='missing_local_clear_rejected_on_native_unknown_data' and clear['native_exit_status']==2
    assert clear['temporary_build_removed'] is True
    for p,h in clear['source_sha256'].items():bind(p,h)
    original=(root/'verilog/tri_oracle_batched_stream385.sv').read_text();old=clear['one_replacement']['before'];new=clear['one_replacement']['after']
    assert original.count(old)==1 and hashlib.sha256(original.replace(old,new).encode()).hexdigest()==clear['compile_overlay_sha256']
    p=Path(clear['log']);bind(p,clear['log_sha256']);content=p.read_text();logs[str(p)]=content
    assert content.count('xmsim: *F,FATSEV')==1 and 'BATCH385_INTEGER_OUTPUT token=0 row=159 got=x' in content and 'BATCH385_PASS tokens=' not in content
    assert 'BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in content
    assert not Path(clear['command'][clear['command'].index('-xmlibdirname')+1]).parent.exists()
    groups.update([clear['supervisor_pid'],clear['process_group']])
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            fields=(p/'stat').read_text().rsplit(')',1)[1].split()
            assert not(fields[0]!='Z' and int(fields[2]) in groups),'Owned native group remains live'
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue
    assert len(logs)==8 and sum(x['exact_outputs'] for x in inventories)==4960
    full=next(x for x in inventories if x['tokens']==16 and x['fault']==0)
    assert (full['activation_beats']+full['weight_beats'])*8==991232
    payload=json.dumps(logs,sort_keys=True,separators=(',',':')).encode();archive.write_bytes(gzip.compress(payload,mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes()))==logs
    report=dict(state='full_width_trained_streamed_down_source_qualified',
        verified_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),qualifier_sha256=sha(__file__),
        source_and_evidence_sha256=identities,native_logs=len(logs),logs_archive_sha256=sha(archive),logs_archive_lossless_verified=True,
        actual_cores=20,actual_clusters=5,actual_vendor_memory_models=600,token_counts=[1,3,8,16],
        full_input_features=5632,selected_original_output_rows=fixture['selected_output_rows'],
        exact_output_comparisons=4960,trained_output_comparisons=4480,zero_input_output_comparisons=480,
        feature_tiles=6,maximum_resident_input_words_per_core=512,added_memory_macros=0,
        activation_words_read_once=True,active_weight_words_read_once=True,zero_word_weight_fetch_suppression_verified=True,
        late_error_after_two_partial_tiles_and_recovery_verified=True,native_missing_local_clear_counterfactual_rejected=True,
        resident_width_limit_counterfactual_verified=True,successful_full_batch_read_bytes=991232,
        successful_full_batch_read_requests=7744,all_local_native_groups_terminal=True,temporary_builds_removed=True,
        prepared_down_inputs=True,current_mapped_candidate_verified=False,complete_feedforward_hardware_verified=False,
        whole_model_execution_verified=False,routed_timing_qualified=False,paper300_release_authorized=False,
        full_paper_results_matched=False,scope=__doc__)
    output.write_text(json.dumps(report,indent=2)+'\n')
    print('BATCH388_QUALIFIED exact_outputs=4960 input_features=5632 feature_tiles=6 native_logs=8',flush=True)


if __name__=='__main__':main()
