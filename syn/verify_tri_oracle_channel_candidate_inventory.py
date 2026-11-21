"""Host-only structural preservation, checked against native tool inventories."""
from collections import Counter
from hashlib import file_digest, sha256
from pathlib import Path
import importlib.util
import json
import mmap
import re
import time

ROOT = Path.cwd().resolve()
WORK = ROOT / '.cache/channel_scale_integration_20261120'
OUT = WORK / 'linked_v1'
BASE = ROOT / '.cache/wide_packaged_host_link/drive_repair/branch_repair/native_trial_runtime_guarded/native'
MODULE = re.compile(rb'(?m)^module\s+(\w+)\s*\(')
END = re.compile(rb'(?m)^endmodule\b')
CONTROL_ROOT = 'chip/chip/normalization/chip/chip/chip/accelerator/'
REMOVED = (CONTROL_ROOT + 'dispatch/', CONTROL_ROOT + 'bank_writeback/')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def spans(path):
    result = {}
    with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as contents:
        for match in MODULE.finditer(contents):
            end_match = END.search(contents, match.end())
            require(end_match is not None, 'Unterminated module')
            end, name = end_match.end(), match[1].decode()
            require(name not in result, 'Duplicate module')
            digest = sha256()
            for offset in range(match.start(), end, 4 * 1024**2):
                digest.update(contents[offset:min(offset + 4 * 1024**2, end)])
            result[name] = digest.hexdigest()
    return result


def def_counts(path):
    all_cells, removed = Counter(), Counter()
    active = False
    declared = None
    complete = False
    with path.open() as stream:
        for line in stream:
            header = re.match(r'^COMPONENTS (\d+)\s*;', line)
            if header:
                require(declared is None, 'Duplicate component section')
                declared, active = int(header[1]), True
            elif line.strip() == 'END COMPONENTS':
                require(active, 'Unexpected component section end')
                active, complete = False, True
            elif active and line.startswith('- '):
                words = line.split()
                require(len(words) >= 3, 'Truncated component')
                name, master = words[1:3]
                all_cells[master] += 1
                if name.startswith(REMOVED):
                    removed[master] += 1
    require(complete and not active and declared == sum(all_cells.values()), 'Incomplete physical component inventory')
    return all_cells, removed


def main():
    require(__debug__, 'Optimized Python is not supported')
    require(not Path('/.dockerenv').exists(), 'Run software verification on the host')
    started = time.monotonic()
    link = json.loads((OUT / 'linkage.json').read_text())
    source, candidate = BASE / 'cold.v', OUT / 'candidate.v'
    require(sha(source) == link['source_sha256'], 'Original netlist changed')
    require(sha(candidate) == link['candidate_sha256'], 'Candidate changed')
    old, new = spans(source), spans(candidate)
    require(len(old) == 771 and set(new) == set(old) | set(link['added_module_renames'].values()), 'Module closure changed')
    changed = [name for name in old if old[name] != new[name]]
    require(changed == [link['changed_parent']], 'Unexpected old module changes')
    library = ROOT / '.cache/physical/library/tcbn28hpcplusbwp12t40p140.v'
    cells = set()
    with library.open() as stream:
        for line in stream:
            match = re.match(r'^\s*module\s+(\S+)\s*\(', line)
            if match:
                cells.add(match[1])
    parser = ROOT / 'syn/tri_oracle_streaming_netlist_inventory.py'
    spec = importlib.util.spec_from_file_location('stream_inventory_v3', parser)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actual = module.inspect(lambda: candidate.open(), 'tri_oracle_chip_credited_request', cells)
    prior_path = ROOT / '.cache/wide_packaged_host_link/owner_score_proof/current_memory_inventory_20261120/verified_inventory.json'
    prior = json.loads(prior_path.read_text())
    require(actual['memory_macro_count'] == 631 and actual['compiled_memory_bytes'] == 414928, 'Compiled memory capacity changed')
    require(actual['memories'] == prior['memories'], 'Compiled memory owner paths changed')
    physical, removed = def_counts(BASE / 'layout.def')
    require(physical == Counter(prior['leaf_instances']), 'Original native placement and verified baseline inventory disagree')
    require(sum(physical.values()) == 3900126 and sum(removed.values()) == 10709, 'Unexpected baseline component count')
    added = Counter()
    blocks = {}
    pins = {str(p.relative_to(ROOT)): sha(p) for p in [source, candidate, library, parser, prior_path, BASE / 'layout.def', OUT / 'linkage.json', Path(__file__)]}
    configurations = [
        ('dispatcher', 'tri_oracle_channel_indexed_dispatch', 2289),
        ('writer', 'tri_oracle_selectable_bank_writeback', 18934),
        ('arbiter', 'tri_oracle_narrow_read_arbiter', 99),
    ]
    for name, top, expected in configurations:
        netlist, report = WORK / 'mapping_v2' / name / 'netlist.v', WORK / 'mapping_v2' / name / 'area.rpt'
        require(sha(netlist) == link['mapping_inputs'][name], 'Mapped block changed')
        count = module.inspect(lambda: netlist.open(), top, cells)
        native = re.findall(r'^\s*' + re.escape(top) + r'\s+NA\s+(\d+)\b', report.read_text(), re.MULTILINE)
        require(native == [str(expected)], 'Unexpected native synthesis count')
        require(sum(count['leaf_instances'].values()) == expected, 'Parser differs from native synthesis count')
        require(count['memory_macro_count'] == 0, 'Unexpected control-block memory')
        added.update(count['leaf_instances'])
        blocks[name] = expected
        pins[str(netlist.relative_to(ROOT))], pins[str(report.relative_to(ROOT))] = sha(netlist), sha(report)
    predicted = physical.copy()
    predicted.subtract(removed)
    require(all(value >= 0 for value in predicted.values()), 'Removed master exceeds baseline count')
    predicted.update(added)
    predicted = +predicted
    require(predicted == Counter(actual['leaf_instances']), 'Candidate per-master composition does not match independent native inventories')
    require(sum(predicted.values()) == 3910739, 'Unexpected candidate count')
    for path, digest in pins.items():
        require(sha(ROOT / path) == digest, 'Evidence changed during verification: ' + path)
    result = dict(
        state='linked_candidate_preservation_and_native_inventory_composition_verified',
        candidate_sha256=sha(candidate), original_modules_byte_identical=770,
        only_changed_old_module=changed[0], added_modules=len(new) - len(old),
        memory_macros=631, compiled_memory_bytes=414928, all_memory_owner_paths_identical=True,
        original_leaf_instances=sum(physical.values()), removed_old_control_instances=sum(removed.values()),
        added_mapped_blocks=blocks, leaf_instances=sum(predicted.values()),
        per_master_composition_verified=True, candidate_leaf_instances_by_master=dict(sorted(predicted.items())),
        prior_incorrect_leaf_instances=3891185,
        correction_reason='Prior wrapper required whitespace before opening parenthesis and skipped compact and line-wrapped Genus instance headers.',
        parser_sha256=sha(parser), source_sha256=sha(Path(__file__)),
        elapsed_seconds=time.monotonic() - started, placed_or_routed=False,
        evidence_sha256=pins)
    with (OUT / 'preservation_v4.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({key: value for key, value in result.items() if key not in {'candidate_leaf_instances_by_master', 'evidence_sha256'}}, indent=2), flush=True)


if __name__ == '__main__':
    main()
