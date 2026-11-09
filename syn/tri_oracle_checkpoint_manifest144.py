"""Bind a completed pre-optimization Genus checkpoint to its exact sources."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys

from tri_oracle_artifact_fingerprint import artifact_fingerprint


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    output=Path(sys.argv[1]);result=output/'elaborated_checkpoint_manifest.json'
    assert not result.exists()
    revision=output/'input_revision.json';data=json.loads(revision.read_text())
    assert all(sha(p)==h for p,h in data['source_sha256'].items())
    consumed=output/'compiled_cluster_sources.sv'
    assert consumed.read_bytes()==data['compiled_bundle'].encode(),'Consumed source bundle differs from saved revision'
    consumed_sha256=sha(consumed)
    assert consumed_sha256==os.environ['TRI_ORACLE_COMPILED_BUNDLE_SHA256'],'Consumed source bundle differs from pre-launch hash'
    evidence=[consumed]+[output/n for n in ['elaboration_wiring.rpt','mapped_controller_boundaries.tsv','reused_controls_before.tsv.sorted','preserved_banks_before.tsv','flow_settings.rpt','elaborated_constraints.sdc']]
    assert all(p.exists() for p in evidence)
    record={'state':'connected_full_parent_elaborated_checkpoint_saved','observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'input_revision_sha256':sha(revision),'source_sha256':data['source_sha256'],'consumed_bundle_sha256':consumed_sha256,
        'checkpoint_fingerprint':artifact_fingerprint(output/'elaborated.db'),
        'native_evidence_sha256':{str(p):sha(p) for p in evidence},
        'scope':'Complete connected parent before generic optimization. This checkpoint is for resuming the same circuit; it does not establish mapping, functional gate simulation, physical timing, routing or paper metrics.',
        'full_paper_results_matched':False}
    temp=result.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2)+'\n');temp.replace(result)
    print('TRI_ORACLE_PREOPTIMIZATION_CHECKPOINT_FINGERPRINTED',flush=True)


if __name__=='__main__':main()
