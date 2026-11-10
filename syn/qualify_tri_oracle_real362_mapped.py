"""Independently qualify the complete trained layer on the preserved candidate.

Bind the actual placed-parent netlist/database, frozen fixture and unchanged
observer scoreboard to native negative/positive logs. Prepared normalization
and sign inputs, local integer formats and ideal functional clocking remain
explicit. This does not qualify complete architecture, model accuracy, delay
annotation, physical timing, system performance or release the paper300 hold.
"""
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re

from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_process_guard import _processes


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def require_current_bundle(prepared,compiled,current_parent):
    includes=re.findall(r'^`include "([^"]+)"$',prepared,re.M)
    if len(includes)<3:raise ValueError('Missing prepared parent include')
    old='`include "'+includes[2]+'"';new='`include "'+str(current_parent)+'"'
    if prepared.count(old)!=1 or compiled!=prepared.replace(old,new):
        raise ValueError('Compiled bundle is not the exact current-parent substitution')


def parse_pair(negative,positive,negative_status,positive_status,expected_word):
    def signed(word):return word-(1<<32) if word&(1<<31) else word
    hierarchy='REAL_FRAME_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600'
    wrong=re.findall(r'REAL_FRAME_INTEGER_OUTPUT row=0 got=(-?\d+) expected=(-?\d+)',negative)
    if (negative_status!=2 or len(wrong)!=1 or tuple(map(int,wrong[0]))!=(signed(expected_word),signed(expected_word^1))
            or hierarchy not in negative or 'REAL_FRAME_PASS outputs=' in negative):
        raise ValueError('Missing exact first-word negative control')
    matches=re.findall(r'REAL_FRAME_PASS outputs=2048 packets=13 groups=176 strips=45056 channels=5632 prediction_packets=36 stalls=(\d+) requests=(\d+)',positive)
    if positive_status!=0 or len(matches)!=1 or hierarchy not in positive or 'REAL_FRAME_INTEGER_OUTPUT' in positive:
        raise ValueError('Missing complete positive trained-layer result')
    stalls,requests=map(int,matches[0])
    if stalls<=0 or requests!=1580544:raise ValueError('Unexpected workload or missing backpressure coverage')
    return dict(exact_integer_outputs=2048,groups=176,strips=45056,channels=5632,output_packets=13,
                prediction_packets=36,stalls=stalls,memory_requests=requests)


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'records/real362_mapped_functional_qualification.json';assert not output.exists()
    producer_path=root/'records/real310_mapped_pair_result.json';producer=json.loads(producer_path.read_text())
    assert producer['state']=='current_mapped_trained_layer_and_wrong_sum_pair_passed'
    assert producer['temporary_build_removed'] and producer['native_exit_status']==0
    identities=dict(producer['source_sha256'])
    for path in [Path(__file__).resolve(),root/'syn/test_tri_oracle_real362_qualification.py',producer_path]:identities[str(path)]=sha(path)
    assert all(sha(path)==digest for path,digest in identities.items()),'Frozen mapped input drift'
    prep=json.loads((root/'records/real299_mapped_preparation.json').read_text())
    restored=json.loads((root/'records/restore295_full_result.json').read_text())
    qualification=json.loads((root/'records/restore304_preservation_qualification.json').read_text())
    parent=Path(restored['output_directory'])/'full/restored_parent.v'
    assert producer['physical_parent']==str(parent)
    assert sha(parent)==producer['physical_parent_sha256']==restored['native_evidence_sha256'][str(parent)]
    require_current_bundle(prep['compiled_bundle'],producer['compiled_bundle'],parent)
    assert len(producer['generated_sha256'])==1
    assert next(iter(producer['generated_sha256'].values()))==hashlib.sha256(producer['compiled_bundle'].encode()).hexdigest()
    assert sha(root/'.cache/physical/rtl/real299_mapped/trained_mapped_observer_bench.sv')==producer['compiled_bench_sha256']==prep['compiled_bench_sha256']
    assert qualification['recovered_saved_checkpoint']==restored['output_database']
    fingerprint=restored['output_database_fingerprint']
    dependencies={Path(name):value for name,value in fingerprint.get('directory_dependencies',{}).items()}
    assert hierarchy_fingerprint(restored['output_database'],directory_dependencies=dependencies)==fingerprint
    assert hashlib.sha256(json.dumps(fingerprint,sort_keys=True,separators=(',',':')).encode()).hexdigest()==qualification['recovered_checkpoint_fingerprint_sha256']
    assert producer['timing_checks_disabled'] and set(producer['native_runs'])=={'elaborate','wrong_sum','full'}
    folder=Path(producer['output_directory']);logs={}
    libraries=[]
    for phase,native in producer['native_runs'].items():
        path=folder/(phase+'_native.log');assert sha(path)==native['console_sha256'];identities[str(path)]=sha(path)
        text=path.read_text();logs[phase]=dict(path=str(path),sha256=sha(path),text=text)
        command=native['command'];libraries.append(command[command.index('-xmlibdirname')+1])
        assert '-notimingchecks' in command and command[command.index('-mce_sim_thread_count')+1]=='8'
        if phase=='elaborate':
            assert native['native_exit_status']==0 and 'Writing initial simulation snapshot:' in text and '*E,' not in text
            assert '-elaborate' in command and '-sequdp_nba_delay' in command
        else:
            assert '-R' in command and ('+CORRUPT_REAL_REFERENCE' in command)==(phase=='wrong_sum')
    assert len(set(libraries))==1 and not Path(libraries[0]).exists()
    checks=producer['runtime_snapshot_checks'];assert set(checks)=={'wrong_sum','full'}
    assert checks['wrong_sum']==checks['full']
    assert checks['full']['compiled_payload_files']==656 and producer['compiled_snapshot_files']==658
    fixture=Path(prep['fixture']);manifest=json.loads((fixture/'manifest.json').read_text())
    assert sha(fixture/'manifest.json')==prep['fixture_manifest_sha256']
    assert (manifest['hidden_features'],manifest['dense_intermediate_stride'],manifest['output_start'],manifest['output_count'])==(2048,5632,0,2048)
    assert manifest['selected_channels']==list(range(5632)) and manifest['skipped_channels']==0
    word=int((fixture/'expected.hex').read_text().splitlines()[0],16)
    metrics=parse_pair(logs['wrong_sum']['text'],logs['full']['text'],producer['native_runs']['wrong_sum']['native_exit_status'],producer['native_runs']['full']['native_exit_status'],word)
    progress=folder/'full_progress.log';rows=re.findall(r'REAL_FRAME_OUTPUT time=[^\n]* outputs=(\d+) packets=(\d+) requests=(\d+)',progress.read_text())
    assert len(rows)==13 and tuple(map(int,rows[-1]))==(2048,13,1580544)
    for index,row in enumerate(rows):assert int(row[0])==min((index+1)*160,2048) and int(row[1])==index+1
    identities[str(progress)]=sha(progress)
    ps=_processes();assert producer['supervisor_pid'] not in ps and producer['native_process_group'] not in ps
    prefix=os.fsencode(str(folder)) + b'/'
    assert not [pid for pid,(_,_,args) in ps.items() if args and Path(os.fsdecode(args[0])).name in {'xrun','xmsim','xmelab','xmvlog'} and any(arg.startswith(prefix) for arg in args)]
    assert all(sha(path)==digest for path,digest in identities.items()),'Mapped qualification inputs changed'
    archive=root/'records/real362_native_logs.json.gz';assert not archive.exists()
    raw=json.dumps(logs,sort_keys=True).encode();archive.write_bytes(gzip.compress(raw,mtime=0));assert gzip.decompress(archive.read_bytes())==raw
    report=dict(state='current_placed_candidate_complete_trained_layer_functional_qualified',
        verified_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=identities,
        current_parent=str(parent),current_parent_sha256=sha(parent),
        preserved_checkpoint=restored['output_database'],preserved_checkpoint_fingerprint_sha256=qualification['recovered_checkpoint_fingerprint_sha256'],
        current_parent_substitution_verified=True,actual_cores=20,actual_clusters=5,actual_vendor_memory_models=600,
        input_features=2048,metrics=metrics,same_compiled_payload_receipts_verified=True,compiled_payload_files=656,
        exact_first_word_negative_rejected=True,all13_positive_output_packets_observed=True,all_native_workers_terminal=True,
        removed_build_verified=True,logs_archive_sha256=sha(archive),logs_archive_lossless_verified=True,
        source_and_current_mapped_integer_fixture_equal=True,prepared_normalization_and_sign_inputs=True,
        fixture_predicted_skips=0,pruning_benefit_verified=False,whole_model_accuracy_qualified=False,
        complete_paper_architecture_verified=False,memory_capacity_reconciled=False,routed_timing_qualified=False,
        delay_annotated_simulation_qualified=False,paper300_release_authorized=False,full_paper_results_matched=False,
        scope=__doc__)
    output.write_text(json.dumps(report,indent=2)+'\n')
    print('REAL362_CURRENT_MAPPED_FUNCTION_QUALIFIED',len(identities),'bound files',metrics,flush=True)


if __name__=='__main__':main()
