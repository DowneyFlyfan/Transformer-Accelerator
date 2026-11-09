"""Qualify the physical control-tree experiment and its paired mapped simulation."""
import csv
import datetime
import filecmp
import hashlib
import json
from pathlib import Path
import re

from tri_oracle_core_preservation import verify_core_snapshots
from tri_oracle_frame202_preservation import CORES, require_reset_topology
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_mapped_restore199 import constraints_equivalent
from tri_oracle_row_guard175_checkpoint import commands
from tri_oracle_mapped208_prerequisite import require_wrong_reference
from tri_oracle_native_diagnostics import require_clean_native


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'records/controller261_physical_functional_qualification.json'
    assert not output.exists()
    physical_path=root/'records/controller260_tree_result.json'
    positive_path=root/'records/controller259_full_result.json'
    negative_path=root/'records/controller259_wrong_sum_result.json'
    physical=json.loads(physical_path.read_text())
    positive=json.loads(positive_path.read_text())
    negative=json.loads(negative_path.read_text())
    assert physical['state']=='noninverting_controller_tree_cold_preserved_and_three_corners_completed'
    assert positive['state']=='full_mapped_frame_functional_passed'
    assert negative['state']=='expected_wrong_mapped_reference_rejected'
    assert positive['native_exit_status']==0 and negative['native_exit_status']!=0
    assert positive['temporary_build_removed'] is True and negative['temporary_build_removed'] is True
    assert positive['cases_seen']==12 and positive['hidden_outputs_checked']==4420
    assert (positive['actual_cores'],positive['actual_clusters'],positive['actual_compiled_memories'])==(20,5,600)
    assert positive['required_negative_reference_label']=='controller259_wrong_sum'
    assert positive['requested_simulation_workers']==negative['requested_simulation_workers']==8
    assert positive['cluster_bind_targets']==negative['cluster_bind_targets']
    assert positive['compiled_bench_sha256']==negative['compiled_bench_sha256']
    require_wrong_reference(negative,positive['static_source_sha256'],8)
    shared=dict(negative['source_sha256'])
    assert all(positive['source_sha256'][name]==digest for name,digest in shared.items())
    assert positive['source_sha256'][str(negative_path)]==sha(negative_path)
    assert positive['source_sha256'][str(physical_path)]==sha(physical_path)
    identities={}
    for record,keys in [(physical,['source_sha256','native_evidence_sha256']),
                        (positive,['source_sha256','static_source_sha256']),
                        (negative,['source_sha256','static_source_sha256'])]:
        for key in keys:
            for name,digest in record[key].items():
                assert name not in identities or identities[name]==digest
                assert sha(name)==digest, 'Changed consumed evidence '+name
                identities[name]=digest
    for path in [physical_path,positive_path,negative_path,Path(__file__).resolve()]:
        identities[str(path)]=sha(path)
    logs={}
    for label,record in [('controller259_full',positive),('controller259_wrong_sum',negative)]:
        path=root/'records'/(label+'_native.log')
        assert sha(path)==record['native_console_sha256']
        text=path.read_text(errors='replace')
        assert 'JOINED_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in text
        identities[str(path)]=sha(path)
        logs[label]=text
    passed=re.findall(r'JOINED_CASE_PASS case=(\d+) outputs=(\d+) error=(\d+) requests=(\d+)',logs['controller259_full'])
    assert len(passed)==12 and [int(row[0]) for row in passed]==list(range(1,13))
    assert sum(int(row[1]) for row in passed)==4420
    match=re.search(r'JOINED_PASS cases=12 hidden_outputs=4420 success_stalls=(\d+) error_stalls=(\d+)',logs['controller259_full'])
    assert match and int(match[1])>0 and int(match[2])>=9
    assert 'JOINED_HIDDEN_SUM row=0 got=16256 expected=16257' in logs['controller259_wrong_sum']
    assert 'JOINED_PASS cases=' not in logs['controller259_wrong_sum']
    database=Path(physical['output_database'])
    fingerprint=physical['output_database_fingerprint']
    dependencies={Path(name):value for name,value in fingerprint.get('directory_dependencies',{}).items()}
    assert hierarchy_fingerprint(database,directory_dependencies=dependencies)==fingerprint
    out=Path(physical['output_directory'])
    baseline_path=root/'records/frame247_restore_result.json'
    baseline_record=json.loads(baseline_path.read_text())
    baseline=Path(baseline_record['output_directory'])/'cold'
    identities[str(baseline_path)]=sha(baseline_path)
    for flag in ['all3_original_corner_constraints_preserved',
                 'all_original_parent_cells_geometry_flags_and_other_connections_preserved',
                 'original600_memory_models_preserved','original86_protected_targets_preserved',
                 'hierarchy_and_module_hport_policies_preserved']:
        assert physical[flag] is True
    # Compare already bound sorted native inventories; no proxy based only on counts.
    def equal(first,second):
        first=Path(str(first)+'.sorted');second=Path(str(second)+'.sorted')
        assert str(first) in identities and str(second) in identities
        assert filecmp.cmp(first,second,shallow=False),str(second)
    for kind in ['cells','ports','nets','pins','design','preservation','halos','core_pins','port_poses']:
        equal(baseline/f'restored_{kind}.tsv',out/'warm'/f'before_{kind}.tsv')
    equal(out/'warm/before_cells.tsv',out/'warm/after_original_cells.tsv')
    equal(out/'warm/before_other_nets.tsv',out/'warm/after_other_nets.tsv')
    for kind in ['ports','pins','design','hierarchy','preservation','halos','core_pins','port_poses']:
        equal(out/'warm'/f'before_{kind}.tsv',out/'warm'/f'after_{kind}.tsv')
    for kind in ['cells','ports','nets','pins','design','hierarchy','preservation','halos','core_pins','port_poses']:
        equal(out/'warm'/f'after_{kind}.tsv',out/'cold'/f'cold_{kind}.tsv')
    for phase,tag in [('warm','after'),('cold','cold')]:
        require_reset_topology(baseline/'restored_reset_roots.tsv',out/phase/f'{tag}_reset_roots.tsv')
        core=verify_core_snapshots(baseline/'core_cells.tsv',out/phase/'core_cells.tsv',sorted(CORES))
        assert core['total_original_cells']==1889420
        for view in ['setup_slow','setup_typ','hold_fast']:
            assert constraints_equivalent(commands(baseline/f'{view}.sdc'),commands(out/phase/f'{view}.sdc'))
    with (out/'warm/placed_buffers.tsv').open() as stream:
        added=list(csv.DictReader(stream,delimiter='\t'))
    assert len(added)==len({row['instance'] for row in added})==43
    assert all(row['status']=='placed' for row in added)
    corners={}
    for phase,native in physical['native_runs'].items():
        log=out/phase/'console.log'
        assert native['native_exit_status']==0 and sha(log)==native['console_sha256']
        require_clean_native(log.read_text(errors='replace'))
    for view in ['setup_slow','setup_typ','hold_fast']:
        with (out/('corner_'+view)/'slack_properties.tsv').open() as stream:
            rows=list(csv.DictReader(stream,delimiter='\t'))
        assert len(rows)==1 and rows[0]['view']==view
        actual={**rows[0]};actual.pop('view');actual['slack_ns']=float(actual['slack_ns'])
        assert actual==physical['corner_diagnostics'][view]['worst']
        corners[view]=actual
    record=dict(state='control_tree_physical_preservation_and_mapped_functional_pair_qualified',
        verified_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        evidence_sha256=identities,actual_cores=20,actual_clusters=5,actual_compiled_memories=600,
        original_core_cells=1889420,original_parent_physical_leaves_including_macros=928808,
        added_noninverting_buffers=43,repaired_original_loads=998,
        cases_passed=12,exact_hidden_outputs_checked=4420,
        success_backpressure_stalls=int(match[1]),error_backpressure_stalls=int(match[2]),
        wrong_integer_sum_reference_rejected=True,positive_and_negative_consumed_same_hardware=True,
        requested_simulation_workers=8,positive_native_elapsed_seconds=positive['native_elapsed_seconds'],
        negative_native_elapsed_seconds=negative['native_elapsed_seconds'],corner_diagnostics=corners,
        physical_checkpoint_cold_preserved=True,original_constraints_preserved=True,
        fast_reset_removal_regressed_from_ns=baseline_record['corner_diagnostics']['hold_fast']['slack_ns'],
        parent_timing_closed=False,parent_routing_completed=False,signal_interference_analysis_qualified=False,
        trained_full_layer_execution_qualified=False,whole_model_accuracy_qualified=False,
        full_paper_results_matched=False,
        scope='43 transparent buffers on one998-load protected enable. Native placement and cold reload preserve original geometry, logic outside the verified tree, protection policies, full cores and memory models. Twelve analytic mapped cases without delay annotation. Three process corners still fail; fast reset removal worsens. No routed-parent, accuracy, power or paper-performance claim.')
    assert all(sha(name)==digest for name,digest in identities.items())
    output.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({key:value for key,value in record.items() if key!='evidence_sha256'},indent=2))


if __name__=='__main__':
    main()
