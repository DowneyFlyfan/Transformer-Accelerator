"""Allow only measured runtime metadata changes; bind every compiled file."""
import hashlib
import json
from pathlib import Path

from run_tri_oracle_xcelium303_runtime_control import library_files

ADMINISTRATIVE = frozenset(['run.lnx8664.25.03.d/mcebuild.args', 'xcelium_bin_paths.log'])


def runtime_template(control):
    if (control.get('state') != 'snapshot_reuse_and_runtime_reference_control_passed'
            or control.get('compiled_payload_unchanged') is not True
            or control.get('administrative_files_captured') is not True
            or control.get('temporary_build_removed') is not True):
        raise ValueError('Runtime control is not qualified')
    command = control['native_runs']['elaborate']['command']
    library = command[command.index('-xmlibdirname')+1]
    negative = control['administrative_snapshots']['wrong_reference']
    positive = control['administrative_snapshots']['positive']
    if set(negative) != ADMINISTRATIVE or negative != positive:
        raise ValueError('Runtime administrative templates differ')
    return {name: text.replace(library, '{LIBRARY}') for name, text in positive.items()}


def require_runtime_snapshot(folder, initial, template):
    folder = Path(folder)
    current = library_files(folder)
    if set(current) != set(initial) or not ADMINISTRATIVE <= set(initial):
        raise ValueError('Snapshot file inventory changed')
    if set(template) != ADMINISTRATIVE:
        raise ValueError('Unqualified administrative template set')
    payload = {name: digest for name, digest in initial.items() if name not in ADMINISTRATIVE}
    if not payload or any(current[name] != digest for name, digest in payload.items()):
        raise ValueError('Compiled payload changed')
    for name in ADMINISTRATIVE:
        path = folder/name
        if path.stat().st_size >= 65536 or path.read_text(encoding='utf-8') != template[name].replace('{LIBRARY}', str(folder)):
            raise ValueError('Unexpected runtime metadata '+name)
    return dict(compiled_payload_files=len(payload),
                compiled_payload_inventory_sha256=hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                administrative_sha256={name: current[name] for name in sorted(ADMINISTRATIVE)})
