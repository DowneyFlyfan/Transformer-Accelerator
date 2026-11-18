"""Prove local valid progression and clear behavior in the mapped arrays."""
from hashlib import file_digest, sha256
from itertools import product
import json
from mmap import mmap, ACCESS_READ
from pathlib import Path
import re
import resource
import sys
import time

from prove_tri_oracle_packaged_products import (
    BRACES, CANDIDATE, CELL, MappedProducts, ROOT, WORK, bindings,
    liberty_group, memory_guard, parse_function, product_flip_flop, structural_cells,
)
from prove_tri_oracle_packaged_reductions import DecisionGraph

VALID_NAMES = ('valid[0]', 'valid[1]', 'valid[2]', 'out_valid')
RESET_NAMES = {'rst_n', 'p1', 'p2'}
VALID_REGISTER = re.compile(r'valid_reg\[([0-3])\]')


def valid_flip_flop(description):
    """Read the primary state group; nested test cells are not functional state."""
    starts = {m.end() - 1: m for m in re.finditer(r'\bff\s*\(([^)]*)\)\s*\{', description)}
    direct, depth = [], 0
    for token in BRACES.finditer(description):
        if token[0] == '{':
            if depth == 0 and token.start() in starts:
                direct.append(starts[token.start()])
            depth += 1
        elif token[0] == '}':
            depth -= 1
    if depth != 0 or len(direct) != 1:
        raise ValueError('Valid cell must have one direct flip-flop')
    match, = direct
    if [name.strip() for name in match[1].split(',')] != ['IQ', 'IQN']:
        raise ValueError('Valid flip-flop state variables differ')
    state = liberty_group(description, match.end())
    attribute = re.compile(r'\b(\w+)\s*:\s*"([^"]*)"\s*;')
    entries = attribute.findall(state)
    result = dict(entries)
    if (len(result) != len(entries) or attribute.sub('', state).strip()
            or set(result) != {'clear', 'clocked_on', 'next_state'}
            or result['clocked_on'] != 'CP'):
        raise ValueError('Unsupported valid flip-flop transition')
    for key in ('clear', 'next_state'):
        parse_function(result[key])
    return result


def prove_control_functions(graph, ready, data, clears, aliases):
    """Compare arbitrary states, including independent physical clear inputs.

    The reference is the four-bit shift with a common ready condition. A
    separate exhaustive integer check uses the original Boolean expressions.
    Physical reset aliases are intentionally NOT assumed equal here.
    """
    assert len(data) == len(clears) == len(aliases) == 4
    assert set(aliases) <= RESET_NAMES and 'rst_n' in aliases, 'Reset alias differs'
    controls = {*VALID_NAMES, 'in_valid', 'out_ready'}
    all_names = [*VALID_NAMES, 'in_valid', 'out_ready', *sorted(set(aliases))]
    for root in [ready, *data]:
        assert graph.dependencies(root) <= controls, 'Foreign control state or data input'
    for root in clears:
        assert graph.dependencies(root) <= set(aliases), 'Foreign control reset input'
    decision = DecisionGraph(all_names)
    actual = decision.convert(graph, [ready, *data, *clears])
    state = [decision.variable(name) for name in VALID_NAMES]
    expected_ready = decision.operation('|', decision.operation('!', state[3]),
                                        decision.variable('out_ready'))
    assert actual[0] == expected_ready, 'Ready differs from available output condition'
    incoming = [decision.variable('in_valid'), *state[:3]]
    for bit in range(4):
        expected_data = decision.operation('|',
            decision.operation('&', expected_ready, incoming[bit]),
            decision.operation('&', decision.operation('!', expected_ready), state[bit]))
        assert actual[1 + bit] == expected_data, ('Valid transition differs', bit)
        expected_clear = decision.operation('!', decision.variable(aliases[bit]))
        assert actual[5 + bit] == expected_clear, ('Asynchronous clear differs', bit)
    cases = common_reset_cases = 0
    for values in product(range(2), repeat=len(all_names)):
        assignment = dict(zip(all_names, values, strict=True))
        observed = graph.evaluate([ready, *data, *clears], assignment, 1)
        current = [assignment[name] for name in VALID_NAMES]
        available = int(not current[3] or assignment['out_ready'])
        shifted = [assignment['in_valid'], *current[:3]] if available else current
        expected_clears = [1 - assignment[alias] for alias in aliases]
        assert observed == [available, *shifted, *expected_clears], 'Integer control cross-check differs'
        next_state = [0 if clear else value for clear, value in zip(observed[5:], observed[1:5], strict=True)]
        expected_next = [value if assignment[alias] else 0
                         for alias, value in zip(aliases, shifted, strict=True)]
        assert next_state == expected_next, 'Clear-dominant next state differs'
        cases += 1
        common_reset_cases += len({assignment[name] for name in set(aliases)}) == 1
    return {'valid_registers': 4, 'reset_alias_by_stage': aliases,
            'independent_integer_cases': cases, 'common_reset_integer_cases': common_reset_cases,
            'maximum_decision_nodes': len(decision.nodes),
            'stall_and_advance_verified': True, 'asynchronous_clear_verified': True,
            'physical_reset_alias_equivalence_assumed': False}


class MappedValid(MappedProducts):
    def __init__(self, body, library, states):
        super().__init__(body, library, states)
        self.valid = {}
        cells, _ = structural_cells(body)
        for master, name, fields in cells:
            match = VALID_REGISTER.fullmatch(name.decode().removeprefix('\\'))
            if match is None:
                continue
            bit = int(match[1])
            pins = bindings(fields, self.declared)
            master = master.decode()
            assert bit not in self.valid, 'Repeated valid register'
            assert states[master] == {'ff': 1}, 'Valid register is not a single flip-flop'
            assert pins['CP'] == 'clk', 'Valid register clock differs'
            assert pins['Q'] == VALID_NAMES[bit], 'Valid register bit mapping differs'
            assert library[master, 'Q']['function'] == 'IQ', 'Valid output polarity differs'
            assert pins['CDN'] in RESET_NAMES, 'Reset alias differs'
            self.valid[bit] = master, pins
        assert set(self.valid) == set(range(4)), 'Valid register inventory differs'
        from link_tri_oracle_indexed_whole_chip import signature
        self.ports = signature(body)
        for direction, names in [(b'input', ('clk', 'rst_n', 'in_valid', 'out_ready')),
                                 (b'output', ('in_ready', 'out_valid'))]:
            for name in names:
                assert self.ports.get(name) == (direction, b''), ('Control port direction or width differs', name)
        for name, (direction, _) in self.ports.items():
            if direction != b'input':
                continue
            bounds = self.declared[name]
            nets = [name] if bounds is None else (f'{name}[{bit}]' for bit in range(min(bounds), max(bounds) + 1))
            assert not any(net in self.drivers for net in nets), ('Input port has an internal driver', name)

    def prove(self):
        data, clears, aliases = [], [], []
        for bit in range(4):
            master, pins = self.valid[bit]
            model = self.library[master, '__valid_ff__']
            assert model['clocked_on'] == 'CP'
            alias = pins['CDN']
            assert self.declared[alias] is None and self.ports.get(alias) == (b'input', b''), \
                'Reset alias is not a scalar input port'
            assert alias not in self.drivers, 'Reset input has an internal driver'
            symbols = set(re.findall(r'[A-Za-z_]\w*', model['next_state'] + ' ' + model['clear']))
            values = {'IQ': self.graph.variable(pins['Q']),
                      'IQN': self.graph.operation('!', self.graph.variable(pins['Q']))}
            for symbol in symbols - values.keys():
                assert self.library[master, symbol]['direction'] == 'input', 'State function uses a non-input pin'
                values[symbol] = self.cone(pins[symbol])
            data.append(self.graph.function(model['next_state'], values))
            clears.append(self.graph.function(model['clear'], values))
            aliases.append(alias)
        result = prove_control_functions(self.graph, self.cone('in_ready'), data, clears, aliases)
        result.update(array_module_sha256=self.body_sha256)
        return result


def inputs():
    from link_tri_oracle_indexed_whole_chip import spans
    from plan_tri_oracle_grouped_reset import read_library
    # This proof does not allocate the multiplier's large packed truth tables.
    memory_guard(10)
    evidence = {}

    def pin(path, wanted=None):
        with path.open('rb') as stream:
            value = file_digest(stream, 'sha256').hexdigest()
        assert wanted is None or value == wanted, path
        evidence[str(path.relative_to(ROOT))] = value
        return path

    structure = json.loads(pin(ROOT / 'records/tri_oracle_packaged_compute_structure.json').read_text())
    assert structure['state'] == 'packaged_register_geometry_and_reachable_prediction_ownership_verified'
    for name, checksum in structure['evidence_sha256'].items():
        pin(ROOT / name, checksum)
    pin(CANDIDATE, structure['candidate_sha256'])
    names = set(structure['array_register_inventory'])
    masters, valid_masters, product_masters = set(), set(), set()
    with CANDIDATE.open('rb') as stream, mmap(stream.fileno(), 0, access=ACCESS_READ) as source:
        modules = spans(source)
        assert {name for name in modules if name.startswith('tri_oracle_pe_array_verified_bank')} == names
        ranges = {name: modules[name] for name in sorted(names)}
        for low, high in ranges.values():
            for match in CELL.finditer(source, low, high):
                master, instance = match[1].decode(), match[2].decode().removeprefix('\\')
                masters.add(master)
                if VALID_REGISTER.fullmatch(instance):
                    valid_masters.add(master)
                if re.fullmatch(r'product\[\d+\]\.value_reg\[\d+\]', instance):
                    product_masters.add(master)
    assert len(ranges) == 20
    storage = json.loads(pin(ROOT / 'records/tri_oracle_packaged_storage_accounting.json').read_text())
    detail_name, = storage['full_detail_cache']
    detail = json.loads(pin(ROOT / detail_name, storage['full_detail_cache'][detail_name]).read_text())
    states = {name: row['state_kinds'] for name, row in detail['standard_cell_state_by_master'].items()}
    corners = []
    for suffix in ('ssg0p9v125c', 'tt1v25c', 'ffg1p05vm40c'):
        basename = f'tcbn28hpcplusbwp12t40p140{suffix}.lib'
        (name, checksum), = ((name, checksum) for name, checksum in structure['evidence_sha256'].items()
                           if Path(name).name == basename)
        path = pin(ROOT / name, checksum)
        pins = read_library(path, masters)
        corner = {key: {k: v for k, v in row.items() if k in ('direction', 'function')}
                  for key, row in pins.items()}
        text = path.read_text()
        for master in valid_masters | product_masters:
            match, = re.finditer(r'(?m)^cell\s*\(' + re.escape(master) + r'\)\s*\{', text)
            description = liberty_group(text, match.end())
            if master in valid_masters:
                corner[master, '__valid_ff__'] = valid_flip_flop(description)
            if master in product_masters:
                corner[master, '__product_ff__'] = product_flip_flop(description)
        corners.append(corner)
    assert corners[0] == corners[1] == corners[2], 'Array Boolean and valid state functions differ across corners'
    library = corners[0]
    qualified_arrays = None
    for record, state in [
        ('tri_oracle_packaged_product_next_states.json', 'packaged_signed_product_next_states_exhaustively_verified'),
        ('tri_oracle_packaged_reduction_next_states.json', 'packaged_signed_reduction_next_states_symbolically_verified'),
    ]:
        result = json.loads(pin(ROOT / 'records' / record).read_text())
        assert result['state'] == state and result['candidate_sha256'] == structure['candidate_sha256']
        assert set(result['arrays']) == set(ranges)
        identities = {name: row['array_module_sha256'] for name, row in result['arrays'].items()}
        if qualified_arrays is None:
            qualified_arrays = identities
        assert qualified_arrays == identities, 'Arithmetic proof array identities differ'
        for name, checksum in result['evidence_sha256'].items():
            pin(ROOT / name, checksum)
        for name, (low, high) in ranges.items():
            with CANDIDATE.open('rb') as stream:
                stream.seek(low)
                assert sha256(stream.read(high - low)).hexdigest() == result['arrays'][name]['array_module_sha256']
    for path in [Path(__file__).resolve(), ROOT / 'syn/test_tri_oracle_packaged_valid_logic.py',
                 ROOT / 'syn/prove_tri_oracle_packaged_products.py',
                 ROOT / 'syn/prove_tri_oracle_packaged_reductions.py',
                 ROOT / 'syn/link_tri_oracle_indexed_whole_chip.py',
                 ROOT / 'syn/plan_tri_oracle_grouped_reset.py']:
        pin(path)
    return ranges, library, states, evidence, structure, qualified_arrays


def inspect_range(task):
    name, (low, high), library, states, expected_module_sha256 = task
    started = time.monotonic()
    memory_guard()
    with CANDIDATE.open('rb') as stream:
        stream.seek(low)
        body = stream.read(high - low)
    assert sha256(body).hexdigest() == expected_module_sha256, ('Changed mapped array', name)
    result = MappedValid(body, library, states).prove()
    result.update(wall_seconds=time.monotonic() - started,
                  peak_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
    print('PACKAGED_VALID_ARRAY_PROVED', name, flush=True)
    return name, result


def controls(ranges, library, states, evidence, structure, qualified_arrays):
    name = 'tri_oracle_pe_array_verified_bank0'
    low, high = ranges[name]
    with CANDIDATE.open('rb') as stream:
        stream.seek(low)
        body = stream.read(high - low)
    assert sha256(body).hexdigest() == qualified_arrays[name], ('Changed mapped array', name)
    reg = next(m for m in CELL.finditer(body) if m[2].removeprefix(b'\\') == b'valid_reg[0]')
    buffer_master, buffer_output = next((master, pin) for (master, pin), row in library.items()
        if row.get('direction') == 'output' and parse_function(row.get('function', '0')) in ('I', ('!', 'I'))
        and library.get((master, 'I'), {}).get('direction') == 'input' and not states.get(master))

    def driven_input(name):
        cell = f'   {buffer_master} proof_control_driver (.I(out_ready), .{buffer_output}({name}));\n'
        return body.replace(b'endmodule', cell.encode() + b'endmodule')

    def reversed_port(name, direction, replacement):
        changed, count = re.subn(rb'\b' + direction.encode() + rb'\s+' + name.encode() + rb'\s*;',
                                replacement.encode() + b' ' + name.encode() + b';', body)
        assert count == 1
        return changed

    def replace_register(old, new):
        changed = reg[0].replace(old, new)
        assert changed != reg[0]
        return body[:reg.start()] + changed + body[reg.end():]

    mutations = [
        ('wrong_valid_source', replace_register(b'.D(in_valid)', b'.D(out_valid)'), library, 'Valid transition'),
        ('wrong_stall_enable', replace_register(b'.E(in_ready)', b'.E(out_ready)'), library, 'Valid transition'),
        ('wrong_clock', replace_register(b'.CP(clk)', b'.CP(out_ready)'), library, 'Valid register clock'),
        ('missing_reset', replace_register(b'.CDN(p1)', b".CDN(1'b1)"), library, 'Reset alias'),
        ('wrong_valid_output', replace_register(b'.Q(valid[0])', b'.Q(in_valid)'), library,
         'Valid register bit mapping'),
        ('missing_valid_register', body[:reg.start()] + body[reg.end():], library, 'Valid register inventory'),
        ('clock_is_output', reversed_port('clk', 'input', 'output'), library, 'Control port'),
        ('internally_driven_clock', driven_input('clk'), library, 'Input port has an internal driver'),
    ]
    for port in ('in_valid', 'out_ready'):
        mutations.append((port + '_is_output', reversed_port(port, 'input', 'output'), library, 'Control port'))
        mutations.append(('internally_driven_' + port, driven_input(port), library,
                          'Input port has an internal driver'))
    for port in ('in_ready', 'out_valid'):
        mutations.append((port + '_is_input', reversed_port(port, 'output', 'input'), library, 'Control port'))
    key = reg[1].decode(), '__valid_ff__'
    mutations.extend([
        ('active_high_clear', body, library | {key: library[key] | {'clear': 'CDN'}}, 'Asynchronous clear'),
        ('removed_hold', body, library | {key: library[key] | {'next_state': 'D'}}, 'Valid transition'),
    ])
    rejected = []
    for label, changed, models, message in mutations:
        try:
            MappedValid(changed, models, states).prove()
        except (AssertionError, ValueError) as error:
            assert message in str(error), (label, 'Unexpected rejection', str(error))
            rejected.append(label)
            print('PACKAGED_VALID_MUTATION_REJECTED', label, flush=True)
        else:
            raise AssertionError(('Valid checker accepted corruption', label))
    result = {'state': 'packaged_valid_negative_controls_verified', 'array_module': name,
              'candidate_sha256': structure['candidate_sha256'], 'rejected_mutations': rejected,
              'evidence_sha256': evidence}
    (WORK / 'valid_controls.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    return result


def verify(negative_controls=False):
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context
    assert __debug__ and Path.cwd() == ROOT and not Path('/.dockerenv').exists()
    started = time.monotonic()
    ranges, library, states, evidence, structure, qualified_arrays = inputs()
    if negative_controls:
        return controls(ranges, library, states, evidence, structure, qualified_arrays)
    control_path = WORK / 'valid_controls.json'
    control_result = json.loads(control_path.read_text())
    assert control_result['state'] == 'packaged_valid_negative_controls_verified'
    assert control_result['candidate_sha256'] == structure['candidate_sha256']
    assert control_result['evidence_sha256'] == evidence, 'Negative controls have stale inputs'
    assert set(control_result['rejected_mutations']) == {
        'wrong_valid_source', 'wrong_stall_enable', 'wrong_clock', 'missing_reset',
        'wrong_valid_output', 'missing_valid_register', 'clock_is_output', 'internally_driven_clock',
        'in_valid_is_output', 'internally_driven_in_valid', 'out_ready_is_output',
        'internally_driven_out_ready', 'in_ready_is_input', 'out_valid_is_input',
        'active_high_clear', 'removed_hold'}
    tasks = [(name, bounds, library, states, qualified_arrays[name]) for name, bounds in ranges.items()]
    with ProcessPoolExecutor(max_workers=4, mp_context=get_context('spawn')) as pool:
        arrays = dict(pool.map(inspect_range, tasks))
    assert {name: row['array_module_sha256'] for name, row in arrays.items()} == qualified_arrays
    memory_guard()
    for name, wanted in evidence.items():
        with (ROOT / name).open('rb') as stream:
            assert file_digest(stream, 'sha256').hexdigest() == wanted, ('Changed proof input', name)
    with control_path.open('rb') as stream:
        evidence[str(control_path.relative_to(ROOT))] = file_digest(stream, 'sha256').hexdigest()
    result = {'state': 'packaged_local_valid_transitions_and_clears_verified',
              'candidate_sha256': structure['candidate_sha256'], 'arrays': arrays,
              'array_instances': len(arrays), 'valid_registers': 4 * len(arrays),
              'independent_integer_cases': sum(row['independent_integer_cases'] for row in arrays.values()),
              'wall_seconds': time.monotonic() - started, 'evidence_sha256': evidence,
              'complete_paper_architecture_verified': False,
              'advance_to_clock_distribution_or_routing_allowed': False,
              'scope': 'Exact two-state local ready/valid transition and clear proof for all twenty '
                       'reachable mapped arrays. All arbitrary valid states, ready/valid inputs and '
                       'independent physical reset inputs are checked against the four-stage globally '
                       'stalled pipeline. Primary flip-flop clock, clear and enable/feedback functions '
                       'are read from the original three-corner Liberty models. This is a local '
                       'pipeline choice of the reproduction, not a paper-specified latency. The proof '
                       'does not qualify parent reset equivalence, reset release or propagation timing, '
                       'four-state simulation, complete chip control, full-model execution, accuracy '
                       'or physical timing and routing.'}
    (WORK / 'verified_valid.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print('PACKAGED_LOCAL_VALID_VERIFIED', result['valid_registers'], result['independent_integer_cases'], flush=True)
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controls', action='store_true')
    verify(parser.parse_args().controls)
