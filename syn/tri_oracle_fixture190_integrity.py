"""Bind every consumed fixture byte to the previously anchored archive manifest."""
import hashlib
import json
from pathlib import Path


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_fixture_hashes(fixture, manifest, expected_manifest_sha256, required_files):
    fixture = Path(fixture)
    path = fixture/'manifest.json'
    assert sha(path) == expected_manifest_sha256, 'Archived fixture manifest changed'
    assert json.loads(path.read_text()) == manifest, 'Parsed fixture metadata changed'
    assert required_files and len(required_files) == len(set(required_files))
    expected = {}
    for name in required_files:
        assert Path(name).name == name and name not in ['.', '..'], 'Invalid fixture filename'
        assert name in manifest['files'], 'Consumed fixture file is not anchored: '+name
        path = fixture/name
        digest = manifest['files'][name]
        assert sha(path) == digest, 'Archived fixture content changed: '+name
        expected[str(path)] = digest
    return expected
