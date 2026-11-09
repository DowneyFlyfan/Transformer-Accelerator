"""Reject same-size data changes even if a new runner would freshly hash them."""
import json
from pathlib import Path
import tempfile

from tri_oracle_fixture190_integrity import sha, validate_fixture_hashes


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/fixture190_integrity_controls.json'
    assert not result.exists()
    controls=[]
    with tempfile.TemporaryDirectory(prefix='fixture190_controls_',dir=root/'.cache/physical') as folder:
        directory=Path(folder)
        data={'gate.hex':'01\n02\n','expected.hex':'00000003\n','prediction_source.json':'{"a":1}\n'}
        for name,text in data.items():(directory/name).write_text(text)
        manifest={'files':{name:sha(directory/name) for name in data}}
        path=directory/'manifest.json';path.write_text(json.dumps(manifest))
        digest=sha(path)
        validate_fixture_hashes(directory,manifest,digest,list(data));controls.append('matching_archive_accepted')
        def rejected(label, metadata=manifest, required=None):
            try:validate_fixture_hashes(directory,metadata,digest,required or list(data))
            except AssertionError:controls.append(label)
            else:raise AssertionError('Incorrectly accepted '+label)
        for name in data:
            original=(directory/name).read_bytes()
            changed=original.replace(b'1',b'2',1) if b'1' in original else original.replace(b'3',b'4',1)
            assert changed!=original and len(changed)==len(original)
            (directory/name).write_bytes(changed)
            rejected('same_size_'+name+'_change_rejected')
            (directory/name).write_bytes(original)
        rebased={'files':dict(manifest['files'])}
        rebased['files']['gate.hex']='0'*64
        path.write_text(json.dumps(rebased));rejected('rebased_manifest_rejected',metadata=rebased)
        path.write_text(json.dumps(manifest))
        rejected('unanchored_consumed_file_rejected',required=['other.hex'])
        validate_fixture_hashes(directory,manifest,digest,list(data));controls.append('restored_archive_accepted')
    assert len(controls)==7
    result.write_text(json.dumps(dict(state='anchored_fixture_integrity_controls_passed',controls=controls,
        source_sha256={str(p):sha(p) for p in [Path(__file__).resolve(),root/'syn/tri_oracle_fixture190_integrity.py']},
        temporary_build_removed=True,scope='Synthetic verifier regression controls; not hardware-functional evidence.'),indent=2)+'\n')
    print(result.read_text())


if __name__=='__main__':main()
