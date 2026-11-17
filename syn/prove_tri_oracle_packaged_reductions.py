"""Prove exact signed reduction arithmetic in the current mapped arrays."""
from functools import cache
from hashlib import file_digest, sha256
from itertools import product
import json
from pathlib import Path
import re
import random
import resource
import sys
import time

from prove_tri_oracle_packaged_products import (
    BRACES, CANDIDATE, CELL, PIN, MappedProducts, ROOT, WORK, bindings,
    inputs as product_inputs, liberty_group, memory_guard, parse_function,
    structural_cells,
)


class DecisionGraph:
    """Reduced ordered binary decision diagrams with explicit node bounds.

    Each node denotes (not variable and low) or (variable and high).
    Equal children remove a decision; unique triples share identical nodes.
    Applying an operation splits its operands at their first variable, so
    induction on the remaining variable order gives the exact truth function.
    """
    def __init__(self, variables, maximum_nodes=10000):
        self.names = tuple(variables)
        if len(set(self.names)) != len(self.names):
            raise ValueError('Repeated decision variable')
        self.order = {name: i for i, name in enumerate(self.names)}
        self.nodes = [(len(self.names), 0, 0), (len(self.names), 1, 1)]
        self.unique = {}
        self.operations = {}
        self.maximum_nodes = maximum_nodes

    def node(self, variable, low, high):
        if low == high:
            return low
        assert self.nodes[low][0] > variable and self.nodes[high][0] > variable
        key = variable, low, high
        if key not in self.unique:
            if len(self.nodes) >= self.maximum_nodes:
                raise ValueError('Decision graph node reserve reached')
            self.unique[key] = len(self.nodes)
            self.nodes.append(key)
        return self.unique[key]

    def variable(self, name):
        return self.node(self.order[name], 0, 1)

    def operation(self, operator, left, right=None):
        if operator == '!':
            return self.operation('^', left, 1)
        if operator not in ('&', '|', '^') or right is None:
            raise ValueError('Unsupported decision operation')
        if left > right:
            left, right = right, left
        if left < 2 and right < 2:
            return {'&': left & right, '|': left | right, '^': left ^ right}[operator]
        if left == right:
            return 0 if operator == '^' else left
        if left == 0:
            return 0 if operator == '&' else right
        if left == 1 and operator in ('&', '|'):
            return right if operator == '&' else 1
        key = operator, left, right
        if key not in self.operations:
            variable = min(self.nodes[left][0], self.nodes[right][0])
            a = self.nodes[left][1:] if self.nodes[left][0] == variable else (left, left)
            b = self.nodes[right][1:] if self.nodes[right][0] == variable else (right, right)
            low = self.operation(operator, a[0], b[0])
            high = self.operation(operator, a[1], b[1])
            self.operations[key] = self.node(variable, low, high)
        return self.operations[key]

    def evaluate(self, root, values):
        while root > 1:
            variable, low, high = self.nodes[root]
            value = values[self.names[variable]]
            if value not in (0, 1):
                raise ValueError('Decision variables must be binary')
            root = high if value else low
        return root

    def signed_sum(self, left, right):
        assert len(left) == len(right) and left
        carry = 0
        result = []
        for a, b in zip([*left, left[-1]], [*right, right[-1]], strict=True):
            parity = self.operation('^', a, b)
            result.append(self.operation('^', parity, carry))
            carry = self.operation('|', self.operation('&', a, b), self.operation('&', parity, carry))
        return result

    def convert(self, graph, roots):
        @cache
        def visit(root):
            operator, *arguments = graph.nodes[root]
            if operator == 'c':
                return arguments[0]
            if operator == 'v':
                return self.variable(arguments[0])
            return self.operation(operator, *(visit(child) for child in arguments))
        result = [visit(root) for root in roots]
        visit.cache_clear()
        return result


def sum_flip_flop(description):
    starts = {match.end() - 1: match for match in re.finditer(r'\bff\s*\(([^)]*)\)\s*\{', description)}
    direct = []
    depth = 0
    for token in BRACES.finditer(description):
        if token[0] == '{':
            if depth == 0 and token.start() in starts:
                direct.append(starts[token.start()])
            depth += 1
        elif token[0] == '}':
            depth -= 1
    if depth != 0 or len(direct) != 1:
        raise ValueError('Reduction cell must have one direct flip-flop')
    match, = direct
    if [name.strip() for name in match[1].split(',')] != ['IQ', 'IQN']:
        raise ValueError('Reduction flip-flop state variables differ')
    state = liberty_group(description, match.end())
    attribute = re.compile(r'\b(\w+)\s*:\s*"([^"]*)"\s*;')
    entries = attribute.findall(state)
    result = dict(entries)
    if (len(result) != len(entries) or attribute.sub('', state).strip()
            or set(result) != {'clocked_on', 'next_state'} or result['clocked_on'] != 'CP'):
        raise ValueError('Unsupported reduction flip-flop transition')
    parse_function(result['next_state'])
    return result


SUM_REGISTER = re.compile(r'reduction\[(\d+)\]\.row\[(\d+)\]\.sum\[(\d+)\]\.value_reg\[(\d+)\]')


def sample_pairs(width):
    limit = 1 << width
    boundary = [0, 1, limit - 1, (limit >> 1) - 1, limit >> 1]
    pairs = list(product(boundary, repeat=2))
    generator = random.Random(width)
    return pairs + [(generator.randrange(limit), generator.randrange(limit)) for _ in range(39)]


class MappedReductions(MappedProducts):
    def __init__(self, body, library, states):
        super().__init__(body, library, states)
        self.sums = {}
        cells, _ = structural_cells(body)
        for master, name, fields in cells:
            match = SUM_REGISTER.fullmatch(name.decode().removeprefix('\\'))
            if match is None:
                continue
            key = tuple(map(int, match.groups()))
            level, row, pair, bit = key
            master = master.decode()
            pins = bindings(fields, self.declared)
            assert key not in self.sums
            assert states[master] == {'ff': 1}, 'Reduction register state differs'
            assert pins['CP'] == 'clk', 'Reduction register clock differs'
            assert library[master, 'Q']['function'] == 'IQ', 'Reduction output polarity differs'
            wanted = (f'out_sums[{row * 19 + bit}]' if level == 2 else
                      f'reduction[{level}].row[{row}].sum[{pair}].value[{bit}]')
            assert pins['Q'] == wanted, 'Reduction register bit mapping differs'
            self.sums[key] = master, pins
        expected = {(level, row, pair, bit) for level in range(3) for row in range(32)
                    for pair in range(4 >> level) for bit in range(17 + level)}
        assert self.sums.keys() == expected, 'Reduction register inventory differs'

    def inputs_for(self, word):
        level, row, pair = word
        width = 16 + level
        if level == 0:
            return [[self.products[row * 8 + 2 * pair + side, bit]['Q']
                     for bit in range(width)] for side in range(2)]
        return [[self.sums[level - 1, row, 2 * pair + side, bit][1]['Q']
                 for bit in range(width)] for side in range(2)]

    def next_state(self, key):
        master, pins = self.sums[key]
        model = self.library[master, '__sum_ff__']
        assert model['clocked_on'] == 'CP'
        symbols = set(re.findall(r'[A-Za-z_]\w*', model['next_state']))
        assert all(self.library[master, symbol]['direction'] == 'input' for symbol in symbols)
        return self.graph.function(model['next_state'], {name: self.cone(pins[name]) for name in symbols})

    def integer_crosscheck(self, data, words):
        """Evaluate original gate functions without using decision diagrams."""
        assignments = {}
        expected = {}
        for word in words:
            left, right = self.inputs_for(word)
            width = len(left)
            limit = 1 << width
            pairs = sample_pairs(width)
            assert len(pairs) == 64
            for labels, side in [(left, 0), (right, 1)]:
                for bit, name in enumerate(labels):
                    value = sum(((pair[side] >> bit) & 1) << index for index, pair in enumerate(pairs))
                    assert name not in assignments
                    assignments[name] = value
            sums = []
            for a, b in pairs:
                signed_a = a - limit if a >= limit // 2 else a
                signed_b = b - limit if b >= limit // 2 else b
                sums.append((signed_a + signed_b) & ((limit << 1) - 1))
            for bit in range(width + 1):
                expected[*word, bit] = sum(((value >> bit) & 1) << index for index, value in enumerate(sums))
        keys = sorted(data)
        actual = self.graph.evaluate([data[key] for key in keys], assignments, mask=(1 << 64) - 1)
        assert actual == [expected[key] for key in keys], 'Integer cross-check differs from mapped addition'
        return len(words) * 64

    def prove(self):
        memory_guard()
        graph = self.graph
        keys = sorted(self.sums)
        roots = [self.next_state(key) for key in keys]
        for key, root in zip(keys, roots, strict=True):
            level, row, pair, bit = key
            left, right = self.inputs_for((level, row, pair))
            allowed = set(left + right) | {f'valid[{level}]', 'out_ready', 'out_valid', self.sums[key][1]['Q']}
            assert graph.dependencies(root) <= allowed, ('Foreign reduction input', key,
                                                         graph.dependencies(root) - allowed)
        writing = None
        holds = writes = 0
        for valid, ready, occupied in product(range(2), repeat=3):
            control = {f'valid[{level}]': valid for level in range(3)}
            control.update(out_ready=ready, out_valid=occupied)
            current = graph.substitute(roots, control)
            if valid and (ready or not occupied):
                if writing is None:
                    writing = current
                else:
                    assert current == writing, 'Reduction write depends on handshake case'
                writes += 1
            else:
                assert all(node == graph.variable(self.sums[key][1]['Q'])
                           for key, node in zip(keys, current, strict=True)), 'Stalled reduction does not hold'
                holds += 1
        assert writes == 3 and holds == 5 and writing is not None
        data = dict(zip(keys, writing, strict=True))
        words = sorted({key[:3] for key in keys})
        crosschecked = self.integer_crosscheck(data, words)
        node_counts = []
        for index, word in enumerate(words):
            if index % 32 == 0:
                memory_guard()
            left, right = self.inputs_for(word)
            order = [name for pair in zip(left, right, strict=True) for name in pair]
            decision = DecisionGraph(order)
            expected = decision.signed_sum([decision.variable(name) for name in left],
                                           [decision.variable(name) for name in right])
            actual = decision.convert(graph, [data[*word, bit] for bit in range(len(left) + 1)])
            assert actual == expected, ('Signed reduction differs from exact addition', word)
            node_counts.append(len(decision.nodes))
        memory_guard()
        return {'array_module_sha256': self.body_sha256, 'registered_sum_bits': len(keys),
                'registered_word_adders': len(words), 'word_adders_per_stage': [128, 64, 32],
                'signed_input_widths': [16, 17, 18], 'signed_output_widths': [17, 18, 19],
                'hold_cases': holds, 'write_cases': writes, 'control_cases': 8,
                'maximum_decision_nodes_per_word': max(node_counts),
                'decision_nodes_total': sum(node_counts),
                'independent_integer_word_cases': crosschecked,
                'operand_and_feedback_dependencies_isolated': True}


def digest(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def inputs():
    ranges, library, states, evidence, structure = product_inputs()
    product_record = ROOT / 'records/tri_oracle_packaged_product_next_states.json'
    products = json.loads(product_record.read_text())
    assert products['state'] == 'packaged_signed_product_next_states_exhaustively_verified'
    assert products['candidate_sha256'] == structure['candidate_sha256']
    qualified_arrays = {name: row['array_module_sha256'] for name, row in products['arrays'].items()}
    assert set(qualified_arrays) == set(ranges) and len(qualified_arrays) == 20
    for name, wanted in products['evidence_sha256'].items():
        assert digest(ROOT / name) == wanted, name
        evidence[name] = wanted
    evidence[str(product_record.relative_to(ROOT))] = digest(product_record)
    masters = set()
    with CANDIDATE.open('rb') as stream:
        for low, high in ranges.values():
            stream.seek(low)
            body = stream.read(high - low)
            masters.update(match[1].decode() for match in CELL.finditer(body)
                           if SUM_REGISTER.fullmatch(match[2].decode().removeprefix('\\')))
    models = []
    for suffix in ('ssg0p9v125c', 'tt1v25c', 'ffg1p05vm40c'):
        basename = f'tcbn28hpcplusbwp12t40p140{suffix}.lib'
        path, = (ROOT / name for name in evidence if Path(name).name == basename)
        text = path.read_text()
        corner = {}
        for master in sorted(masters):
            match, = re.finditer(r'(?m)^cell\s*\(' + re.escape(master) + r'\)\s*\{', text)
            corner[master] = sum_flip_flop(liberty_group(text, match.end()))
        models.append(corner)
    assert models[0] == models[1] == models[2], 'Reduction transition models differ across corners'
    library = library | {(master, '__sum_ff__'): model for master, model in models[0].items()}
    for path in (Path(__file__).resolve(), ROOT / 'syn/test_tri_oracle_packaged_reduction_logic.py'):
        evidence[str(path.relative_to(ROOT))] = digest(path)
    return ranges, library, states, evidence, structure, qualified_arrays


def inspect_range(task):
    name, bounds, library, states, expected_module_sha256 = task
    started = time.monotonic()
    memory_guard()
    with CANDIDATE.open('rb') as stream:
        stream.seek(bounds[0])
        body = stream.read(bounds[1] - bounds[0])
    assert sha256(body).hexdigest() == expected_module_sha256, ('Changed mapped array', name)
    result = MappedReductions(body, library, states).prove()
    result.update(wall_seconds=time.monotonic() - started,
                  peak_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
    print('PACKAGED_REDUCTION_ARRAY_PROVED', name, result['registered_word_adders'], flush=True)
    return name, result


def change_pin(body, instance, pin, replacement):
    match, = (match for match in CELL.finditer(body)
               if match[2].decode().removeprefix('\\') == instance)
    terminal, = (item for item in PIN.finditer(match[3]) if item[1].decode() == pin)
    low, high = match.start(3) + terminal.start(2), match.start(3) + terminal.end(2)
    return body[:low] + replacement + body[high:]


def rare_sum_fault(body, base):
    """Flip one sum bit only for a reachable product pair absent from sampling."""
    chosen = (100 * 101, 99 * 97)
    assert chosen not in sample_pairs(16)
    assert not any(name.startswith('proof_fault_') for name in base.declared)
    left, right = base.inputs_for((0, 0, 0))
    wires = []
    cells = []

    def wire():
        name = f'proof_fault_{len(wires)}'
        wires.append(name)
        return name

    def reference(name):
        leading, _, last = name.rpartition('[')
        assert leading.startswith('product[') and last.endswith(']')
        return '\\' + leading + ' [' + last

    terms = []
    for labels, value in zip((left, right), chosen, strict=True):
        for bit, label in enumerate(labels):
            terminal = reference(label)
            if not ((value >> bit) & 1):
                inverted = wire()
                cells.append(f'   INVD0BWP12T40P140 {inverted}_inst (.I({terminal}),.ZN({inverted}));')
                terminal = inverted
            terms.append(terminal)
    match = terms[0]
    for terminal in terms[1:]:
        combined = wire()
        cells.append(f'   AN2D1BWP12T40P140 {combined}_inst (.A1({match}),.A2({terminal}),.Z({combined}));')
        match = combined
    pins = base.sums[0, 0, 0, 0][1]
    data_pin = 'D' if 'D' in pins else 'DB'
    inverted, corrected = wire(), wire()
    cells.append(f'   XNR2D1BWP12T40P140 {inverted}_inst (.A1({pins[data_pin]}),.A2({match}),.ZN({inverted}));')
    cells.append(f'   INVD0BWP12T40P140 {corrected}_inst (.I({inverted}),.ZN({corrected}));')
    changed = change_pin(body, 'reduction[0].row[0].sum[0].value_reg[0]', data_pin, corrected.encode())
    added = '\n'.join('   wire ' + name + ';' for name in wires) + '\n' + '\n'.join(cells) + '\n'
    assert changed.count(b'endmodule') == 1
    return changed.replace(b'endmodule', added.encode() + b'endmodule')


def controls(ranges, library, states, evidence, structure, qualified_arrays):
    name = 'tri_oracle_pe_array_verified_bank0'
    low, high = ranges[name]
    with CANDIDATE.open('rb') as stream:
        stream.seek(low)
        body = stream.read(high - low)
    assert sha256(body).hexdigest() == qualified_arrays[name], 'Control array changed after qualification'
    base = MappedReductions(body, library, states)

    def instance(key):
        level, row, pair, bit = key
        return f'reduction[{level}].row[{row}].sum[{pair}].value_reg[{bit}]'

    mutations = []
    for label, key in [('first_stage_data', (0, 0, 0, 0)), ('second_stage_data', (1, 0, 0, 5)),
                       ('final_sign_bit', (2, 0, 0, 18))]:
        pins = base.sums[key][1]
        pin = 'D' if 'D' in pins else 'DB'
        mutations.append((label, change_pin(body, instance(key), pin, b"1'b0"),
                          'Integer cross-check differs from mapped addition'))
    first = 0, 0, 0, 0
    pins = base.sums[first][1]
    feedback = 'SI' if 'SI' in pins else 'DA'
    mutations.append(('removed_sum_feedback', change_pin(body, instance(first), feedback, b"1'b0"),
                      'Stalled reduction does not hold'))
    mutations.append(('sum_clock_swap', change_pin(body, instance(first), 'CP', b'p1'),
                      'Reduction register clock differs'))
    other = base.sums[0, 1, 0, 0][1]
    other_data = other['D'] if 'D' in other else other['DB']
    target = 'D' if 'D' in pins else 'DB'
    mutations.append(('foreign_row_data', change_pin(body, instance(first), target, other_data.encode()),
                      'Foreign reduction input'))
    match, = (match for match in CELL.finditer(body)
               if match[2].decode().removeprefix('\\') == instance(first))
    mutations.append(('missing_sum_register', body[:match.start()] + body[match.end():],
                      'Reduction register inventory differs'))
    mutations.append(('unsampled_reachable_word_fault', rare_sum_fault(body, base),
                      'Signed reduction differs from exact addition'))
    rejected = []
    for label, changed, expected in mutations:
        try:
            MappedReductions(changed, library, states).prove()
        except (AssertionError, ValueError) as error:
            assert expected in str(error), (label, 'Unexpected rejection', str(error))
            rejected.append(label)
            print('PACKAGED_REDUCTION_MUTATION_REJECTED', label, flush=True)
        else:
            raise AssertionError(('Reduction checker accepted corruption', label))
    result = {'state': 'packaged_reduction_negative_controls_verified', 'array_module': name,
              'candidate_sha256': structure['candidate_sha256'], 'rejected_mutations': rejected,
              'evidence_sha256': evidence}
    (WORK / 'reduction_controls.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    return result


def verify(negative_controls=False):
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context
    assert __debug__ and Path.cwd() == ROOT and not Path('/.dockerenv').exists()
    started = time.monotonic()
    ranges, library, states, evidence, structure, qualified_arrays = inputs()
    if negative_controls:
        return controls(ranges, library, states, evidence, structure, qualified_arrays)
    receipt = WORK / 'reduction_controls.json'
    control = json.loads(receipt.read_text())
    assert control['state'] == 'packaged_reduction_negative_controls_verified'
    assert control['candidate_sha256'] == structure['candidate_sha256']
    assert control['evidence_sha256'] == evidence, 'Reduction controls have stale inputs'
    assert set(control['rejected_mutations']) == {'first_stage_data', 'second_stage_data', 'final_sign_bit',
                                                'removed_sum_feedback', 'sum_clock_swap',
                                                'foreign_row_data', 'missing_sum_register',
                                                'unsampled_reachable_word_fault'}
    tasks = [(name, bounds, library, states, qualified_arrays[name]) for name, bounds in ranges.items()]
    with ProcessPoolExecutor(max_workers=4, mp_context=get_context('spawn')) as pool:
        arrays = dict(pool.map(inspect_range, tasks))
    assert set(arrays) == set(qualified_arrays) and len(arrays) == 20
    assert digest(CANDIDATE) == structure['candidate_sha256'], 'Candidate changed during reduction proof'
    for name, wanted in evidence.items():
        assert digest(ROOT / name) == wanted, ('Reduction proof input changed', name)
    memory_guard()
    evidence[str(receipt.relative_to(ROOT))] = digest(receipt)
    result = {'state': 'packaged_signed_reduction_next_states_symbolically_verified',
              'candidate_sha256': structure['candidate_sha256'], 'array_instances': len(arrays),
              'registered_word_adders': sum(row['registered_word_adders'] for row in arrays.values()),
              'registered_sum_bits': sum(row['registered_sum_bits'] for row in arrays.values()),
              'independent_integer_word_cases': sum(row['independent_integer_word_cases'] for row in arrays.values()),
              'signed_input_widths': [16, 17, 18], 'signed_output_widths': [17, 18, 19],
              'control_cases_per_sum_bit': 8, 'arrays': arrays,
              'wall_seconds': time.monotonic() - started, 'evidence_sha256': evidence,
              'complete_paper_architecture_verified': False,
              'advance_to_clock_distribution_or_routing_allowed': False,
              'scope': 'Exact two-state equivalence of all mapped registered reduction additions '
                       'to full-precision signed addition in the current candidate. Each operand '
                       'pair is represented symbolically over every input bit, with word and '
                       'feedback isolation and all eight local valid/ready cases checked. '
                       'Original three-corner flip-flop transition functions, including scan '
                       'and data-multiplexing holds, are modeled explicitly. A separate packed '
                       'integer boundary/random check evaluates the mapped Boolean functions '
                       'without decision diagrams. Reset distribution, valid propagation, '
                       'complete prediction behavior, chip control, trained full-model accuracy, '
                       'physical timing and routing remain unqualified.'}
    (WORK / 'verified_reductions.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print('PACKAGED_REDUCTION_NEXT_STATES_VERIFIED', result['registered_word_adders'],
          result['registered_sum_bits'], flush=True)
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controls', action='store_true')
    verify(parser.parse_args().controls)
