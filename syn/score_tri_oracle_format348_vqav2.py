"""Official scoring of the frozen five-mode,first-token-protected64-question pilot.

Reuse the exact qualified326 official evaluator and submission normalization.
Require complete successful346/347 inference and all three archived baseline
answers/per-question scores. This reused mixed-floating diagnostic is not the
paper's full benchmark, recovered protocol or hardware accuracy qualification.
"""
import datetime
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from score_tri_oracle_format326_vqav2 import load_official_sources,score_cases,sha


def main():
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    output=root/'records/format348_official_scoring.json';assert not output.exists()
    started=time.monotonic()
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                       if line.startswith('MemAvailable:')))*1024
    assert available>6*1024**3
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    qualification=root/'records/format327_qualification.json'
    assert sha(qualification)=='750d9451f8fe8c83a2c517bc91a41f1e30c17cfade13a41678bb92d7f0ab6a81'
    qualified=json.loads(qualification.read_text())
    prior_score_path=root/'records/format326_official_scoring.json'
    assert sha(prior_score_path)==qualified['scoring_sha256']
    old=json.loads(prior_score_path.read_text())
    inference_path=root/'records/format346_vqav2_inference.json'
    guard_path=root/'records/format347_gpu_guard_result.json'
    result=json.loads(inference_path.read_text());guard=json.loads(guard_path.read_text())
    assert guard['state']=='completed' and guard['native_exit_status']==0 and guard['input_drift']==[]
    assert sha(inference_path)==guard['summary_sha256']
    assert result['state']=='completed' and len(result['cases'])==320 and result['sample_count']==64
    evaluator,processor,inputs=load_official_sources(root)
    for source_map in [result['source_sha256'],guard['source_sha256']]:
        for path,digest in source_map.items():
            assert path not in inputs or inputs[path]==digest
            inputs[path]=digest
    paths=[Path(__file__),qualification,prior_score_path,inference_path,guard_path,
           root/'syn/score_tri_oracle_format326_vqav2.py',root/'syn/test_tri_oracle_format326_scoring.py']
    for path in paths:
        key=str(path.resolve());assert key not in inputs or inputs[key]==sha(path);inputs[key]=sha(path)
    log=root/'.cache/format347_gpu_native.log'
    assert sha(log)==guard['native_log_sha256'];inputs[str(log)]=guard['native_log_sha256']
    assert all(sha(path)==digest for path,digest in inputs.items())
    manifest_path=root/'.cache/model_reference/vqav2_pilot/manifest.json'
    manifest=json.loads(manifest_path.read_text())
    assert sha(manifest_path)==inputs[str(manifest_path)]
    samples=manifest['samples']
    assert len(samples)==len({item['question_id'] for item in samples})==len({item['image_id'] for item in samples})==64
    previous_path=root/'records/format324_vqav2_inference.json'
    assert sha(previous_path)==inputs[str(previous_path)]
    previous=json.loads(previous_path.read_text())
    previous_cases={(item['mode'],item['question_id']):item for item in previous['cases']}
    assert previous['state']=='completed' and len(previous_cases)==256
    modes=['floating','extended_integer_dense','extended_integer_predicted','integer_dense','integer_predicted']
    assert {item['mode'] for item in result['cases']}==set(modes)
    baseline={'floating':'floating','extended_integer_dense':'integer_dense','extended_integer_predicted':'integer_predicted'}
    tests=subprocess.run([sys.executable,'-B','-m','unittest','syn/test_tri_oracle_format326_scoring.py'],
                         cwd=root,capture_output=True,text=True,timeout=60,check=True)
    scored={}
    for mode in modes:
        cases=[item for item in result['cases'] if item['mode']==mode];assert len(cases)==64
        for item in cases:
            assert item['integer_layers']==(0 if mode=='floating' else 22)
            assert item['per_layer_calls']==([] if mode=='floating' else[len(item['answer_tokens'])+1]*22)
            expected_offsets=[0,0]+list(range(item['prefill_tokens'],item['prefill_tokens']+len(item['answer_tokens'])-1))
            expected_protected=[1,1]+[0]*(len(item['answer_tokens'])-1)
            assert item['per_layer_token_offsets']==([] if mode=='floating' else [expected_offsets]*22)
            assert item['per_layer_protected_rows']==([] if mode=='floating' else [expected_protected]*22)
            if mode in baseline:
                assert item['answer_tokens']==previous_cases[baseline[mode],item['question_id']]['answer_tokens']
        scored[mode]=score_cases(samples,cases,evaluator,processor)
        if mode in baseline:assert scored[mode]==old['results'][baseline[mode]],'Archived per-question score/answer mismatch'
        print('FORMAT348_OFFICIAL_SCORE',mode,scored[mode]['official_vqa_consensus_percent_on64'],flush=True)
    decode_calls={mode:sum(sum(max(0,count-2) for count in item['per_layer_calls'])
                          for item in result['cases'] if item['mode']==mode)
                  for mode in modes if mode!='floating'}
    assert decode_calls==result['generation_decode_calls_by_mode']
    assert result['incremental_decode_offsets_verified']==all(decode_calls[mode]>0 for mode in ['integer_dense','integer_predicted'])
    assert all(sha(path)==digest for path,digest in inputs.items())
    record=dict(state='official_protected_pilot_scoring_completed_baselines_reproduced',
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=inputs,
        sample_count=64,inference_cases=320,official_scoring_executed=True,
        official_evaluator_conversion_sha256=old['converted_evaluator_sha256'],
        controls_exit_status=tests.returncode,controls_stdout=tests.stdout,controls_stderr=tests.stderr,
        all192_archived_answer_sequences_reproduced=True,all192_archived_per_question_scores_reproduced=True,
        results=scored,whole_model_integer=False,hardware_configuration_mapping_verified=False,
        paper_accuracy_matched=False,full_paper_results_matched=False,
        input_exponent_policy_is_local_reconstruction_choice=True,first_token_protection_is_local_reconstruction_choice=True,
        generation_decode_calls_by_mode=result['generation_decode_calls_by_mode'],
        incremental_decode_offsets_verified=result['incremental_decode_offsets_verified'],
        full_validation_question_count=214354,elapsed_seconds=time.monotonic()-started,
        maximum_resident_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,scope=__doc__)
    with output.open('x') as stream:stream.write(json.dumps(record,indent=2)+'\n')
    print('FORMAT348_COMPLETED',sha(output),flush=True)


if __name__=='__main__':main()
