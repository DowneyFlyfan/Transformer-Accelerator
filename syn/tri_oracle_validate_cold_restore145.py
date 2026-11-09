"""Verify a cold-restored parent against its native prepared checkpoint."""
import hashlib
import json
from pathlib import Path
import sys

from tri_oracle_artifact_fingerprint import artifact_fingerprint


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def commands(path):
    return [line.strip() for line in Path(path).read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]


def main():
    source,output=map(Path,sys.argv[1:])
    manifest=source/'elaborated_checkpoint_manifest.json';data=json.loads(manifest.read_text())
    assert all(sha(p)==h for p,h in data['source_sha256'].items())
    assert all(sha(p)==h for p,h in data['native_evidence_sha256'].items())
    assert artifact_fingerprint(source/'elaborated.db')==data['checkpoint_fingerprint']
    assert commands(source/'elaborated_constraints.sdc')==commands(output/'restored_constraints.sdc'),'Restored clock or IO constraints changed'
    for filename in ['reused_controls_before.tsv.sorted','preserved_banks_before.tsv','mapped_controller_boundaries.tsv']:
        assert sorted((source/filename).read_text().splitlines())==sorted((output/filename).read_text().splitlines()),'Restored inventory/wiring changed '+filename
    record={'state':'full_parent_cold_restore_wiring_cells_and_constraints_verified',
      'producer_manifest_sha256':sha(manifest),'producer_checkpoint_fingerprint':data['checkpoint_fingerprint'],
      'source_and_restored_sdc_commands_equal':True,'source_and_restored_controller_wiring_and_cell_inventories_equal':True,
      'native_evidence_sha256':{str(output/n):sha(output/n) for n in ['restored_constraints.sdc','reused_controls_before.tsv.sorted','preserved_banks_before.tsv','mapped_controller_boundaries.tsv','elaboration_wiring.rpt']},
      'scope':'Cold native restore before generic optimization. No mapped functionality, routed timing or paper metric claim.', 'full_paper_results_matched':False}
    result=output/'cold_restore_validation.json';assert not result.exists();result.write_text(json.dumps(record,indent=2)+'\n')
    print('TRI_ORACLE_FRAME145_COLD_RESTORE_VERIFIED',flush=True)


if __name__=='__main__':main()
