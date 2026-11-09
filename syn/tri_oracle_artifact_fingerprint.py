"""Content identity for nonempty tool files and native database directories."""
import hashlib
import os
from pathlib import Path


def artifact_fingerprint(path):
    path=Path(path)
    if path.is_symlink():
        raise ValueError('Artifact must not be a symbolic link: '+str(path))
    if path.is_file():
        if path.stat().st_size==0:
            raise ValueError('Empty artifact: '+str(path))
        checksum=hashlib.sha256()
        with path.open('rb') as file:
            for chunk in iter(lambda:file.read(1024*1024),b''):
                checksum.update(chunk)
        return {'type':'file','size_bytes':path.stat().st_size,'sha256':checksum.hexdigest()}
    if path.is_dir():
        files={}
        for child in sorted(path.rglob('*')):
            link_target=None
            if child.is_symlink():
                if not child.is_file():
                    raise ValueError('Database library link must target a regular file: '+str(child))
                link_target=os.readlink(child)
            if child.is_file():
                # Native databases may include empty auxiliary files; bind them
                # too, while requiring positive total database content below.
                checksum=hashlib.sha256()
                with child.open('rb') as file:
                    for chunk in iter(lambda:file.read(1024*1024),b''):
                        checksum.update(chunk)
                entry={'size_bytes':child.stat().st_size,'sha256':checksum.hexdigest()}
                if link_target is not None:entry['symlink_target']=link_target
                files[str(child.relative_to(path))]=entry
        if not files or sum(item['size_bytes'] for item in files.values())==0:
            raise ValueError('Empty native database: '+str(path))
        return {'type':'directory','files':files}
    raise ValueError('Missing or unsupported artifact: '+str(path))
