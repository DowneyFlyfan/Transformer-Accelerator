"""Verify completed native receipts and publish small lossless metadata evidence."""
import csv
import datetime
import filecmp
import gzip
import hashlib
import json
from pathlib import Path

from tri_oracle_native_diagnostics import require_clean_native
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    source=root/'records/controller266_tree_result.json'
    output=root/'records/controller268_physical_qualification.json'
    receipt=root/'records/controller266_tree_result.json.gz'
    assert not output.exists() and not receipt.exists()
    raw=source.read_bytes();record=json.loads(raw)
    assert record['state']=='noninverting_controller_batch_cold_preserved_and_three_corners_completed' and record['native_exit_status']==0
    for key in ['all_original_parent_cells_geometry_flags_and_other_connections_preserved','original600_memory_models_preserved','all3_original_corner_constraints_preserved','original86_protected_targets_preserved','hierarchy_and_module_hport_policies_preserved']:
        assert record[key] is True
    assert record['added_noninverting_buffers']==1989
    assert set(record['original_core_preservation'])=={'warm','cold'}
    assert all(v['total_original_cells']==1889420 for v in record['original_core_preservation'].values())
    for key in ['source_sha256','native_evidence_sha256']:
        assert all(sha(name)==digest for name,digest in record[key].items()),key
    fp=record['output_database_fingerprint']
    assert hierarchy_fingerprint(record['output_database'],directory_dependencies={Path(n):v for n,v in fp.get('directory_dependencies',{}).items()})==fp
    out=Path(record['output_directory'])
    def equal(first,second):
        for path in [first,second]:assert str(path) in record['native_evidence_sha256']
        assert filecmp.cmp(first,second,shallow=False),(str(first),str(second))
    for before,after in [('before_cells','after_original_cells'),('before_other_nets','after_other_nets')]+[(f'before_{k}',f'after_{k}') for k in ['ports','pins','design','hierarchy','preservation','halos','core_pins','port_poses']]:
        equal(out/'warm'/(before+'.tsv.sorted'),out/'warm'/(after+'.tsv.sorted'))
    for kind in ['cells','ports','nets','pins','design','hierarchy','preservation','halos','core_pins','port_poses']:
        equal(out/'warm'/('after_'+kind+'.tsv.sorted'),out/'cold'/('cold_'+kind+'.tsv.sorted'))
    runs={}
    for phase,run in record['native_runs'].items():
        path=out/phase/'console.log';text=path.read_text(errors='replace')
        assert run['native_exit_status']==0 and sha(path)==run['console_sha256'];require_clean_native(text)
        marker='TRI_ORACLE_CONTROLLER266_TREE_PLACED_AND_ORIGINAL_CORES_EXPORTED' if phase=='warm' else 'TRI_ORACLE_CONTROLLER266_COLD_TREE_AND_ORIGINAL_CORES_EXPORTED' if phase=='cold' else 'TRI_ORACLE_FRAME267_CORNER_DIAGNOSTIC_FINISHED '+phase.removeprefix('corner_')
        assert '\n'+marker+'\n' in text
        runs[phase]=run
    assert set(runs)=={'warm','cold','corner_setup_slow','corner_setup_typ','corner_hold_fast'}
    for view in ['setup_slow','setup_typ','hold_fast']:
        with (out/('corner_'+view)/'slack_properties.tsv').open() as stream:rows=list(csv.DictReader(stream,delimiter='\t'))
        assert len(rows)==1 and rows[0]['view']==view
        actual=dict(slack_ns=float(rows[0]['slack_ns']),startpoint=rows[0]['startpoint'],endpoint=rows[0]['endpoint'])
        assert actual==record['corner_diagnostics'][view]['worst']
    compressed=gzip.compress(raw,mtime=0)
    assert len(compressed)<256*1024 and gzip.decompress(compressed)==raw
    assert source.read_bytes()==raw
    receipt.write_bytes(compressed)
    result=dict(state='control_enable_batch_physical_preservation_and_three_corners_qualified',
        verified_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        verification_source_sha256={str(Path(__file__).resolve()):sha(__file__)},
        original_native_record_sha256=sha(source),published_lossless_record=str(receipt.relative_to(root)),
        published_lossless_record_sha256=sha(receipt),decompressed_bytes_identical=True,
        source_and_native_evidence_hashes_checked=sum(len(record[k]) for k in ['source_sha256','native_evidence_sha256']),
        native_runs=runs,actual_cores=20,actual_compiled_memories=600,original_core_cells=1889420,
        added_noninverting_buffers=1989,original_enable_loads_buffered=47503,
        parent_geometry_connections_flags_and_constraints_preserved=True,cold_reload_verified=True,
        corner_diagnostics=record['corner_diagnostics'],post_change_mapped_functional_simulation_qualified=False,
        parent_timing_closed=False,parent_routing_completed=False,full_paper_results_matched=False,
        scope='Completed266buffer-tree experiment. Original physical parent, fullcore models, memory catalog and3timingconstraints retained. All3corners stillfail. The latest mapped12casepass remains260/261 ancestor; no new functional simulation is claimed. The compressed metadata receipt reproduces every original native JSON byte, includes no libraries or checkpoints, and leaves the original local receipt unchanged.')
    output.write_text(json.dumps(result,indent=2)+'\n')
    print('PHYSICAL268_QUALIFIED receipt_bytes='+str(len(compressed)))


if __name__=='__main__':main()
