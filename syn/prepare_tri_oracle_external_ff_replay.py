"""Prepare the frozen shared-array source replay using local memory models.

Run on the host. This writes a bundle under .cache and never starts a simulator.
The six memory model files remain external; none of their contents is copied.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / 'syn/tri_oracle_external_ff_sources.json'
# Independently derived from the original native bundle's two definitions and
# all 69 ordered payload hashes. A manifest cannot authorize its own replacement.
FROZEN_SOURCE_SEQUENCE_SHA256 = 'af7a44686bc7ca2ee1193bcbe0187351da200f3b76c9cfc279534dfa525b0ed4'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(manifest, memory_files, output_directory):
    """Validate every input before creating bundle.sv and receipt.json."""
    if Path('/.dockerenv').exists():
        raise ValueError('Prepare the source replay on the host')
    output = Path(output_directory).resolve()
    cache = (ROOT / '.cache').resolve()
    if output == cache or not output.is_relative_to(cache):
        raise ValueError('output must be under the project .cache directory')
    if output.exists():
        raise ValueError('output already exists; do not overwrite prior results')
    manifest = Path(manifest).resolve()
    config = json.loads(manifest.read_text())
    if config.get('version') != 1:
        raise ValueError('Unsupported source manifest version')
    definitions = config['defines']
    if not all(isinstance(x, str) and re.fullmatch(r'[A-Za-z_]\w*', x)
               for x in definitions):
        raise ValueError('Invalid preprocessor definition')
    supplied = {}
    for path in memory_files:
        path = Path(path).resolve(strict=True)
        if path.name in supplied and supplied[path.name] != path:
            raise ValueError('Duplicate memory model filename: ' + path.name)
        supplied[path.name] = path
    inputs = []
    source_count = memory_count = 0
    for item in config['includes']:
        if item['kind'] == 'source':
            relative = Path(item['path'])
            path = (ROOT / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(ROOT / 'verilog'):
                raise ValueError('source path must name repository Verilog: ' + str(relative))
            if sha(path) != item['sha256']:
                raise ValueError('source digest differs: ' + str(relative))
            source_count += 1
        elif item['kind'] == 'memory':
            filename = item['filename']
            if filename not in supplied:
                raise ValueError('missing memory model: ' + filename)
            path = supplied[filename]
            if sha(path) != item['sha256']:
                raise ValueError('memory model digest differs: ' + filename)
            memory_count += 1
        else:
            raise ValueError('Unsupported include kind')
        inputs.append(path)
    sequence = {'defines': definitions,
                'ordered_sha256': [item['sha256'] for item in config['includes']]}
    fingerprint = hashlib.sha256(json.dumps(
        sequence, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if fingerprint != config['source_sequence_sha256']:
        raise ValueError('source sequence differs from the frozen native bundle')
    if fingerprint != FROZEN_SOURCE_SEQUENCE_SHA256:
        raise ValueError('frozen source sequence differs from the tested native design')
    if source_count != 63 or memory_count != 6:
        raise ValueError('frozen source sequence requires 63 sources and six external memory models')
    bundle = ''.join('`define ' + name + '\n' for name in definitions)
    bundle += ''.join('`include ' + json.dumps(str(path)) + '\n' for path in inputs)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'bundle.sv').write_text(bundle)
    receipt = {
        'state': 'ordered_source_replay_prepared_not_native_execution_proof',
        'manifest_sha256': sha(manifest),
        'bundle_sha256': sha(output / 'bundle.sv'),
        'source_sequence_sha256': fingerprint,
        'ordered_inputs': len(inputs),
        'repository_sources': source_count,
        'external_memory_models': memory_count,
        'input_sha256': {str(path): item['sha256']
                         for path, item in zip(inputs, config['includes'])},
        'vendor_memory_contents_copied': False,
        'native_execution_verified': False,
        'paper_matching': False,
    }
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--memory-file', type=Path, action='append', default=[])
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = prepare(args.manifest, args.memory_file, args.output_directory)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('error: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps({key: receipt[key] for key in (
        'state', 'ordered_inputs', 'repository_sources', 'external_memory_models')}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
