"""Qualify retained topology and constraints after a native mapped cold restore."""
import json
import csv
from collections import Counter
import os
from pathlib import Path
import sys

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_row_guard173_variants import sha
from tri_oracle_row_guard175_checkpoint import commands


def constraints_equivalent(original, restored):
    # Genus cold restore reorders this independent preservation subset. Keep
    # every other command in its original order and every preservation count.
    preserved = lambda lines: Counter(line for line in lines if line.startswith('set_dont_touch '))
    ordered = lambda lines: [line for line in lines if not line.startswith('set_dont_touch ')]
    return ordered(original) == ordered(restored) and preserved(original) == preserved(restored)


def require_boundary_pin_set(observed, anchored):
    assert len(observed) == len(set(observed)) == len(anchored) == len(set(anchored))
    assert set(observed) == set(anchored), 'Original boundary pin identities changed'


def main():
    previous, output = map(Path, sys.argv[1:3])
    phase = sys.argv[3] if len(sys.argv) == 4 else 'before'
    assert phase in ['before','after']
    postfix = '_after' if phase == 'after' else ''
    revision_path = output / 'input_revision.json'
    assert sha(revision_path) == os.environ['TRI_ORACLE_RESUME199_REVISION_SHA256']
    revision = json.loads(revision_path.read_text())
    assert all(sha(p) == h for p, h in revision['source_sha256'].items())
    assert artifact_fingerprint(previous / 'mapped.db') == revision['mapped_checkpoint_fingerprint']
    for template in ['reused_controls_{}.tsv.sorted', 'preserved_banks_{}.tsv']:
        assert sorted((previous / template.format('before')).read_text().splitlines()) == sorted((output / template.format(phase)).read_text().splitlines()), template
    constraint_file = 'postopt_constraints.sdc' if phase == 'after' else 'restored_constraints.sdc'
    assert constraints_equivalent(commands(previous / 'elaborated_constraints.sdc'), commands(output / constraint_file)), 'Original clock/IO/preservation constraints changed'
    gate = (output / ('gate_cells_'+phase+'.tsv')).read_text().splitlines()
    assert len(gate) == 151275
    assert sorted(gate) == sorted((previous / 'gate_cells_before.tsv').read_text().splitlines())
    assert (output / ('gate_preservation_'+phase+'.tsv')).read_text().strip() == 'numeric/engine/gated/implementation\ttri_oracle_fabric_gated_executor_mapped153\ttrue'
    gate_bits = (output / ('gate_boundary_'+phase+'.tsv')).read_text().splitlines()
    assert len(gate_bits) == len(set(gate_bits)) == 21012
    assert all(len(line.split('\t')) == 2 and all(line.split('\t')) for line in gate_bits)
    controls = (output / ('mapped_controller_boundaries'+postfix+'.tsv')).read_text().splitlines()
    assert controls[0] == 'instance\thpin\thnet'
    assert len(controls) - 1 == 135700
    assert len({line.split('\t')[1] for line in controls[1:]}) == 135700
    assert all(len(line.split('\t')) == 3 and all(line.split('\t')) for line in controls[1:])
    original_controls = (previous / 'mapped_controller_boundaries.tsv').read_text().splitlines()[1:]
    require_boundary_pin_set([line.split('\t')[1] for line in controls[1:]], [line.split('\t')[1] for line in original_controls])
    require_boundary_pin_set([line.split('\t')[0] for line in gate_bits], [line.split('\t')[0] for line in (previous/'gate_boundary_before.tsv').read_text().splitlines()])
    connection_file = 'boundary_connections_'+phase+'.tsv'
    with (output/connection_file).open() as stream:
        connections = list(csv.DictReader(stream, delimiter='\t'))
    assert len(connections) == len({row['pin'] for row in connections}) == 156712
    assert all(row['kind'] in ['hierarchical','constant_input','constant_output','flat_output','feedthrough_output'] for row in connections)
    for row in connections:
        if row['kind'].startswith('constant_'):
            assert row['constant'] in ['0','1']
        if row['kind'] in ['flat_output','feedthrough_output']:
            assert row['direction']=='out' and row['flat_net'] and row['source'] and int(row['external_loads'])>0
    require_boundary_pin_set([row['pin'] for row in connections],
        [line.split('\t')[1] for line in original_controls] + [line.split('\t')[0] for line in (previous/'gate_boundary_before.tsv').read_text().splitlines()])
    names = ['reused_controls_'+phase+'.tsv.sorted', 'preserved_banks_'+phase+'.tsv',
             'gate_cells_'+phase+'.tsv', 'gate_boundary_'+phase+'.tsv', 'gate_preservation_'+phase+'.tsv',
             'mapped_controller_boundaries'+postfix+'.tsv', constraint_file, connection_file]
    names += ['restored_check.rpt','restored_wiring.rpt','mapped_restore.v','mapped_restore.sdc'] if phase=='before' else ['postopt_check.rpt','postopt_wiring.rpt']
    record = dict(state='source_bound_full_parent_mapped_cold_restore_qualified' if phase=='before' else 'source_bound_full_parent_optimized_topology_qualified',
        source_sha256=revision['source_sha256'], input_revision_sha256=sha(revision_path),
        native_evidence_sha256={str(output / name): sha(output / name) for name in names},
        mapped_checkpoint_fingerprint=revision['mapped_checkpoint_fingerprint'],
        preserved_mapped_controllers=26, independently_preserved_gate_cells=151275,
        original_controls_boundary_bits=135700, mapped_gate_boundary_bits=21012,
        mapped_boundary_connection_kinds=dict(Counter(row['kind'] for row in connections)),
        original_clock_io_and_preservation_constraints_unchanged=True,
        full_mapped_function_qualified=False, optimization_completed=phase=='after',
        routed_timing_qualified=False, full_paper_results_matched=False,
        scope=('Cold-restored whole prepared20-core/40-bank parent after technology mapping. ' if phase=='before' else
               'Whole prepared20-core/40-bank parent after native final optimization returned. ')+
              'Independent native cell inventories, mapped connections, exact original pin sets and preservation constraints verified. '
              'Native function, physical placement, routed timing and paper results remain separate gates.')
    path = output / ('mapped_cold_restore_qualification.json' if phase=='before' else 'optimized_topology_qualification.json')
    assert not path.exists()
    path.write_text(json.dumps(record, indent=2) + '\n')
    print('TRI_ORACLE_FRAME199_BOUNDARY_TOPOLOGY_QUALIFIED phase='+phase, flush=True)


if __name__ == '__main__':
    main()
