"""Audit accepted-to-imported hierarchy protection before circuit edits."""
import datetime
import hashlib
import json
from pathlib import Path


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/hierarchy277_initial_import_validation.json'
    assert not result.exists()
    identities={str(Path(__file__).resolve()):sha(__file__)};pairs=[]
    for parent_number,child_number in [(260,266),(266,273)]:
        paths=[root/'records'/f'controller{n}_tree_result.json' for n in [parent_number,child_number]]
        parent,child=[json.loads(path.read_text()) for path in paths]
        assert all(record['state'] in ['noninverting_controller_tree_cold_preserved_and_three_corners_completed','noninverting_controller_batch_cold_preserved_and_three_corners_completed'] for record in [parent,child])
        for path in paths:identities[str(path)]=sha(path)
        before=Path(parent['output_directory'])/'cold/cold_hierarchy.tsv'
        imported=Path(child['output_directory'])/'warm/before_hierarchy.tsv'
        rows=[]
        for path,record in [(before,parent),(imported,child)]:
            digest=sha(path);assert digest==record['native_evidence_sha256'][str(path)]
            identities[str(path)]=digest
            lines=sorted(path.read_text().splitlines());fields=[line.split('\t') for line in lines]
            assert fields and all(len(row)==6 for row in fields) and len({row[0] for row in fields})==len(fields)
            rows.append(lines)
        assert rows[0]==rows[1]
        pairs.append(dict(accepted=parent_number,imported=child_number,hierarchy_rows=len(rows[0]),all_six_fields_identical=True))
    assert all(sha(path)==digest for path,digest in identities.items())
    result.write_text(json.dumps(dict(state='accepted_to_initial_import_hierarchy_policies_verified',verified_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=identities,comparisons=pairs,scope='Exact physical-view hierarchy/module binding,dont_touch andbothdont_touch_hports values match across260to266and266to273 initialimports. This fills an earlier comparison omission using original native ledgers; no saved source or receipt is changed. No new timing,functional or routing result.'),indent=2)+'\n')
    print('HIERARCHY277_IMPORT_POLICIES_PASS pairs=2')


if __name__=='__main__':main()
