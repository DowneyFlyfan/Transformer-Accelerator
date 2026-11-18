"""Prove candidate-local modular head-ratio update cones, without chip changes.

The disclosed method compares inner and recent attention intensity. The ratio
and serial implementation are local reconstruction choices. This component
proof does not qualify complete prediction, finite-state control, parent
connectivity, trained execution, accuracy or physical timing.
"""
from hashlib import file_digest, sha256
import json
from mmap import mmap, ACCESS_READ
from pathlib import Path
import random
import re
import resource
import sys
import time

from prove_tri_oracle_packaged_products import BooleanGraph, CANDIDATE, ROOT, memory_guard, parse_function
from prove_tri_oracle_packaged_reductions import DecisionGraph
from prove_tri_oracle_parent_reset import Module
from prove_tri_oracle_parent_clock import read_clock_library

PREFIX = 'tri_oracle_attention_head_classifier410_SERIAL_RATIO1_SHARED_CONFIG1'


def add_bits(graph, left, right, carry=0):
    assert len(left) == len(right)
    result = []
    for a, b in zip(left, right, strict=True):
        parity = graph.operation('^', a, b)
        result.append(graph.operation('^', parity, carry))
        carry = graph.operation('|', graph.operation('&', a, b), graph.operation('&', parity, carry))
    return result


def update_bits(graph, difference, outer, inner, den, num):
    """Independent low-bit arithmetic: 2*difference + den*outer - num*inner.

    Lists contain least-significant bit first. Selected intensity operands are
    unsigned; the result is modular, so this covers either interpretation of
    the stored difference bit pattern. No signed/full-width result is claimed.
    """
    width = len(difference)
    if not width or not outer or len(outer) != len(inner) or len(outer) > width:
        raise ValueError('Invalid modular ratio operand widths')
    positive = [graph.operation('&', bit, den) for bit in outer] + [0] * (width - len(outer))
    negative = [graph.operation('&', bit, num) for bit in inner] + [0] * (width - len(inner))
    shifted = [0, *difference[:-1]]
    partial = add_bits(graph, shifted, positive)
    return add_bits(graph, partial, [graph.operation('!', bit) for bit in negative], carry=1)


def positive_bits(graph, word):
    """Strict signed comparison with zero, including an explicit zero test."""
    if not word:
        raise ValueError('Empty signed word')
    nonzero = 0
    for bit in word[:-1]:
        nonzero = graph.operation('|', nonzero, bit)
    return graph.operation('&', graph.operation('!', word[-1]), nonzero)


def require_capture_ff(model):
    assert (set(model) == {'clocked_on', 'next_state', 'clear'}
            and parse_function(model['clocked_on']) == 'CP'
            and parse_function(model['next_state']) == 'D'
            and parse_function(model['clear']) == ('!', 'CDN')), 'Capture register state model differs'


class ClassifierCone:
    """Read actual mapped gate functions; undriven internal nets are errors."""
    def __init__(self, body, library, states):
        self.module = Module(body)
        self.body_sha256 = self.module.sha256
        self.library, self.states = library, states
        self.graph = BooleanGraph()
        self.inputs = {bit for name, direction in self.module.directions.items() if direction == 'input'
                       for bit in self.module.net_bits(name)}
        self.drivers = {}
        self.cones, self.visiting, self.used_pins = {}, set(), set()
        for net, source in self.module.assignments.items():
            self.drivers[net] = ('assign', source)
        for instance, (master, raw) in self.module.cells.items():
            pins = {}
            for pin, expression in raw.items():
                bits = self.module.expression(expression)
                assert len(bits) <= 1, 'Non-scalar primitive connection'
                pins[pin] = bits[0] if bits else ''
                assert (master, pin) in library, ('Unknown library pin', master, pin)
            for pin, net in pins.items():
                direction = library[master, pin]['direction']
                assert direction in ('input', 'output'), 'Unsupported primitive direction'
                if direction != 'output' or not net:
                    continue
                assert not net.startswith("1'"), 'Constant primitive output driver'
                assert net not in self.drivers, 'Multiple mapped drivers'
                assert net not in self.inputs, 'Input has an internal driver'
                self.drivers[net] = ('cell', master, pin, pins)

    def cone(self, net):
        if net in self.cones:
            return self.cones[net]
        assert net not in self.visiting, 'Combinational cycle'
        self.visiting.add(net)
        if net in ("1'b0", "1'b1"):
            result = int(net[-1])
        elif net in self.inputs:
            assert net not in self.drivers, 'Input has an internal driver'
            result = self.graph.variable(net)
        else:
            assert net in self.drivers, ('Missing mapped driver', net)
            source = self.drivers[net]
            if source[0] == 'assign':
                result = self.cone(source[1])
            else:
                _, master, pin, pins = source
                self.used_pins.add((master, pin))
                function = self.library[master, pin].get('function')
                assert function, ('Missing gate function', master, pin)
                if self.states.get(master):
                    assert self.states[master] == {'ff': 1}, 'Unsupported sequential cut'
                    assert function in ('IQ', 'IQN'), 'Unsupported sequential polarity'
                    if function == 'IQN' and pins.get('Q'):
                        assert self.library[master, 'Q']['function'] == 'IQ', 'Unknown companion polarity'
                        result = self.graph.operation('!', self.graph.variable(pins['Q']))
                    else:
                        result = self.graph.variable(net)
                else:
                    symbols = set(re.findall(r'[A-Za-z_]\w*', function))
                    for symbol in symbols:
                        assert self.library[master, symbol]['direction'] == 'input', 'Function references non-input'
                        self.used_pins.add((master, symbol))
                    result = self.graph.function(function, {name: self.cone(pins[name]) for name in symbols})
        self.visiting.remove(net)
        self.cones[net] = result
        return result


def prove_module(model):
    """Compare every low update bit for all eight selected ratio-bit indexes."""
    required = {'serial_ratio.difference': (26, 0), 'serial_ratio.ratio_bit': (2, 0),
                'serial_ratio.next_difference': (26, 0), 'total_inner': (17, 0), 'total_outer': (17, 0)}
    assert all(model.module.declared.get(name) == bounds for name, bounds in required.items()), 'Ratio word dimensions differ'
    roots = [model.cone(f'serial_ratio.next_difference[{bit}]') for bit in range(26)]
    original_leaves = set().union(*(model.graph.dependencies(root) for root in roots))
    permitted = {f'{word}[{bit}]' for word, width in [('serial_ratio.difference', 26),
        ('serial_ratio.ratio_bit', 3), ('total_inner', 18), ('total_outer', 18),
        ('cfg_ratio_num', 8), ('cfg_ratio_den', 8)] for bit in range(width)}
    assert original_leaves <= permitted, ('Foreign ratio dependency', original_leaves - permitted)
    peaks = []
    for selected in range(8):
        memory_guard(8.5)
        current = model.graph.substitute(roots, {f'serial_ratio.ratio_bit[{bit}]': (selected >> bit) & 1 for bit in range(3)})
        names = [f'cfg_ratio_den[{selected}]', f'cfg_ratio_num[{selected}]']
        for bit in range(26):
            if bit:
                names.append(f'serial_ratio.difference[{bit - 1}]')
            if bit < 18:
                names.extend([f'total_outer[{bit}]', f'total_inner[{bit}]'])
        decision = DecisionGraph(names, maximum_nodes=250000)
        actual = decision.convert(model.graph, current)
        difference = [decision.variable(f'serial_ratio.difference[{bit}]') for bit in range(25)] + [0]
        outer = [decision.variable(f'total_outer[{bit}]') for bit in range(18)]
        inner = [decision.variable(f'total_inner[{bit}]') for bit in range(18)]
        expected = update_bits(decision, difference, outer, inner,
            decision.variable(f'cfg_ratio_den[{selected}]'), decision.variable(f'cfg_ratio_num[{selected}]'))
        assert actual == expected, ('Mapped modular ratio update differs', selected)
        peaks.append(len(decision.nodes))
    generator = random.Random(410)
    boundary = [0, 1, 131071, 131072, 262142, 262143]
    cases = [(d, outer, inner, ratio, ratio ^ 255, bit) for bit in range(8)
             for ratio in (0, 1, 8, 127, 128, 255) for d in (0, 1, (1 << 25) - 1, 1 << 25, (1 << 26) - 1)
             for outer, inner in [(boundary[i], boundary[-1-i]) for i in range(6)]]
    cases.extend((generator.randrange(1 << 26), generator.randrange(1 << 18), generator.randrange(1 << 18),
                  generator.randrange(256), generator.randrange(256), generator.randrange(8)) for _ in range(128))
    for difference, outer, inner, numerator, denominator, selected in cases:
        assignment = {f'{name}[{bit}]': (value >> bit) & 1 for name, width, value in [
            ('serial_ratio.difference', 26, difference), ('serial_ratio.ratio_bit', 3, selected),
            ('total_outer', 18, outer), ('total_inner', 18, inner),
            ('cfg_ratio_num', 8, numerator), ('cfg_ratio_den', 8, denominator)] for bit in range(width)}
        actual = sum(value << bit for bit, value in enumerate(model.graph.evaluate(roots, assignment)))
        expected = ((difference << 1) + outer * ((denominator >> selected) & 1)
                    - inner * ((numerator >> selected) & 1)) & ((1 << 26) - 1)
        assert actual == expected, 'Independent integer ratio check differs'
    sign = prove_sign_capture(model)
    return dict(module_sha256=model.body_sha256, update_bits=26, ratio_bit_indexes=8,
        symbolic_bits_checked=26 * 8, integer_cases=len(cases), maximum_decision_nodes=max(peaks),
        used_library_pins=len(model.used_pins), cone_nets=len(model.cones), sign_capture=sign)


def prove_sign_capture(model):
    """Prove the actual streaming-register data cone under its arithmetic capture.

    Enumerate every encoded state/counter combination to identify which data
    cone depends on ratio arithmetic. That encoded-state predicate is reported
    explicitly; mapping it to the reachable control sequence is a separate proof.
    """
    master, raw = model.module.cells['streaming_reg']
    pins = {name: model.module.expression(value) for name, value in raw.items()}
    require_capture_ff(model.library[master, '__capture_ff__'])
    assert pins['CP'] == ('clk',) and pins['CDN'] == ('rst_n',) and pins['Q'] == ('streaming',), 'Capture register binding differs'
    data = model.cone(pins['D'][0])
    arithmetic_prefixes = ('serial_ratio.difference[', 'total_inner[', 'total_outer[', 'cfg_ratio_num[', 'cfg_ratio_den[')
    captures = []
    for state in range(8):
        for selected in range(8):
            control = {f'state[{bit}]': (state >> bit) & 1 for bit in range(3)}
            control.update({f'serial_ratio.ratio_bit[{bit}]': (selected >> bit) & 1 for bit in range(3)})
            root, = model.graph.substitute([data], control)
            if any(name.startswith(arithmetic_prefixes) for name in model.graph.dependencies(root)):
                captures.append((state, selected, root))
    assert len(captures) == 1 and captures[0][1] == 0, 'Arithmetic capture predicate differs'
    encoded_state, _, captured = captures[0]
    names = ['cfg_ratio_den[0]', 'cfg_ratio_num[0]']
    for bit in range(27):
        if bit:
            names.append(f'serial_ratio.difference[{bit - 1}]')
        if bit < 18:
            names.extend([f'total_outer[{bit}]', f'total_inner[{bit}]'])
    decision = DecisionGraph(names, maximum_nodes=250000)
    actual, = decision.convert(model.graph, [captured])
    difference = [decision.variable(f'serial_ratio.difference[{bit}]') for bit in range(26)]
    outer = [decision.variable(f'total_outer[{bit}]') for bit in range(18)]
    inner = [decision.variable(f'total_inner[{bit}]') for bit in range(18)]
    next_word = update_bits(decision, [*difference, difference[-1]], outer, inner,
                            decision.variable('cfg_ratio_den[0]'), decision.variable('cfg_ratio_num[0]'))
    assert actual == positive_bits(decision, next_word), 'Mapped signed positive decision differs'
    gate = DecisionGraph(['out_error', 'streaming'])
    observed, = gate.convert(model.graph, [model.cone('out_streaming')])
    assert observed == gate.operation('&', gate.operation('!', gate.variable('out_error')), gate.variable('streaming')), 'Output error suppression differs'
    checks = 0
    boundaries = [0, 1, 131071, 131072, 262142, 262143]
    for count in boundaries:
        for difference_value in (0, 1, -1, (1 << 25) - 1, -(1 << 25)):
            assignment = {name: 0 for name in names}
            for name, width, value in [('serial_ratio.difference', 26, difference_value), ('total_outer', 18, count), ('total_inner', 18, count)]:
                assignment.update({f'{name}[{bit}]': (value >> bit) & 1 for bit in range(width)})
            assignment.update({'cfg_ratio_den[0]': 1, 'cfg_ratio_num[0]': 1})
            assert model.graph.evaluate([captured], assignment) == [int(difference_value > 0)], 'Signed/tie integer decision differs'
            checks += 1
    return dict(encoded_capture_state=encoded_state, ratio_bit_at_capture=0,
        positive_decision_width=27, signed_difference_cut_width=26,
        maximum_decision_nodes=len(decision.nodes), integer_boundary_cases=checks,
        strict_zero_and_error_suppression_verified=True,
        reachable_state_sequence_verified=False)


def rejection_controls(body, library, states):
    """Corrupt actual bindings or functions in memory; preserve source bytes."""
    from prove_tri_oracle_parent_reset import INSTANCE
    from prove_tri_oracle_packaged_products import PIN
    original = ClassifierCone(body, library, states)
    original_library_rows = [(key, dict(value)) for key, value in sorted(library.items())]
    mutations = []
    changed_cell = None
    for match in INSTANCE.finditer(body):
        for binding in PIN.finditer(match[3]):
            if binding[2].decode().strip() != 'cfg_ratio_num[0]':
                continue
            changed_cell = match, binding
            break
        if changed_cell:
            break
    assert changed_cell, 'Missing numerator binding for rejection control'
    match, binding = changed_cell
    for replacement, label in [(b"1'b0", 'stuck_numerator_bit'), (b'cfg_rows[0]', 'foreign_config_dependency')]:
        fields = match[3][:binding.start(2)] + replacement + match[3][binding.end(2):]
        altered = body[:match.start(3)] + fields + body[match.end(3):]
        assert altered != body
        mutations.append((label, altered, library))
    _, master, pin, _ = original.drivers['serial_ratio.next_difference[0]']
    gate, = (match for match in INSTANCE.finditer(body)
             if any(value.strip() == b'\\serial_ratio.next_difference [0]'
                    for key, value in PIN.findall(match[3]) if (match[1].decode(), key.decode()) == (master, pin)))
    mutations.append(('missing_update_driver', body[:gate.start()] + body[gate.end():], library))
    altered_library = library.copy()
    altered_library[master, pin] = library[master, pin] | {'function': '!(' + library[master, pin]['function'] + ')'}
    mutations.append(('inverted_original_gate_function', body, altered_library))
    stream_master = original.module.cells['streaming_reg'][0]
    altered_library = library.copy()
    altered_library[stream_master, '__capture_ff__'] = library[stream_master, '__capture_ff__'] | {'next_state': '!D'}
    mutations.append(('inverted_capture_data', body, altered_library))
    rejections = []
    for label, altered_body, altered_library in mutations:
        memory_guard(8.5)
        try:
            prove_module(ClassifierCone(altered_body, altered_library, states))
        except (AssertionError, KeyError, ValueError) as error:
            message = str(error)
            expected = ('Foreign ratio dependency' if label == 'foreign_config_dependency'
                        else 'Missing mapped driver' if label == 'missing_update_driver'
                        else 'Capture register state model' if label == 'inverted_capture_data'
                        else 'Mapped modular ratio update differs')
            assert expected in message, ('Unrelated rejection', label, message)
            rejections.append(dict(control=label, rejection=message))
        else:
            raise AssertionError(('Corrupted head-ratio logic accepted', label))
    assert sha256(body).hexdigest() == original.body_sha256, 'Original module changed during controls'
    assert [(key, dict(value)) for key, value in sorted(library.items())] == original_library_rows, 'Original library changed during controls'
    return rejections


def verify(output, limit=None):
    from audit_tri_oracle_mapped_redundancy import hierarchy
    from link_tri_oracle_indexed_whole_chip import spans

    assert __debug__ and not Path('/.dockerenv').exists()
    assert output.resolve().is_relative_to((ROOT / '.cache').resolve()) and not output.exists()
    memory_guard(10)
    started, evidence = time.monotonic(), {}

    def pin(path, wanted=None):
        with path.open('rb') as stream:
            actual = file_digest(stream, 'sha256').hexdigest()
        assert wanted is None or actual == wanted, ('Changed ratio proof input', path)
        assert evidence.setdefault(str(path.relative_to(ROOT)), actual) == actual
        return path

    structure = json.loads(pin(ROOT / 'records/tri_oracle_packaged_compute_structure.json').read_text())
    storage = json.loads(pin(ROOT / 'records/tri_oracle_packaged_storage_accounting.json').read_text())
    assert structure['state'] == 'packaged_register_geometry_and_reachable_prediction_ownership_verified'
    assert storage['state'] == 'exact_packaged_candidate_sram_and_standard_cell_state_accounted'
    assert storage['candidate_sha256'] == structure['candidate_sha256']
    pin(CANDIDATE, structure['candidate_sha256'])
    detail_name, = storage['full_detail_cache']
    detail = json.loads(pin(ROOT / detail_name, storage['full_detail_cache'][detail_name]).read_text())
    states = {name: item['state_kinds'] for name, item in detail['standard_cell_state_by_master'].items()}
    graph = hierarchy(CANDIDATE)
    reached = []

    def walk(master, path, parents):
        assert master not in parents, 'Recursive mapped hierarchy'
        if master.startswith(PREFIX):
            reached.append((path, master))
        for instance, child in graph[master].items():
            walk(child, path + '/' + instance.removeprefix('\\'), parents | {master})

    walk(structure['logical_top'], structure['logical_top'], set())
    assert len(reached) == len({name for _, name in reached}) == 20, 'Expected20 reachable classifier masters'
    bodies = {}
    with CANDIDATE.open('rb') as stream, mmap(stream.fileno(), 0, access=ACCESS_READ) as source:
        ranges = spans(source)
        assert {name for name in ranges if name.startswith(PREFIX)} == {name for _, name in reached}
        for _, name in reached:
            low, high = ranges[name]
            bodies[name] = source[low:high]
    masters = {kind for body in bodies.values() for kind, _ in Module(body).cells.values()}
    corners = []
    for suffix in ('ssg0p9v125c', 'tt1v25c', 'ffg1p05vm40c'):
        (name, checksum), = ((name, checksum) for name, checksum in structure['evidence_sha256'].items()
                            if Path(name).name == f'tcbn28hpcplusbwp12t40p140{suffix}.lib')
        raw = read_clock_library(pin(ROOT / name, checksum), masters)
        corner = {key: {k: v for k, v in values.items() if k in ('direction', 'function')} for key, values in raw.items()}
        from prove_tri_oracle_packaged_products import liberty_group
        from prove_tri_oracle_packaged_valid import valid_flip_flop
        description = (ROOT / name).read_text()
        capture_masters = {Module(body).cells['streaming_reg'][0] for body in bodies.values()}
        for capture_master in capture_masters:
            match, = re.finditer(r'(?m)^cell\s*\(' + re.escape(capture_master) + r'\)\s*\{', description)
            corner[capture_master, '__capture_ff__'] = valid_flip_flop(liberty_group(description, match.end()))
        corners.append(corner)
    assert corners[0] == corners[1] == corners[2], 'Classifier Boolean functions differ by corner'
    library = corners[0]
    for path in [Path(__file__).resolve(), ROOT / 'syn/test_tri_oracle_head_ratio_logic.py',
                 ROOT / 'syn/prove_tri_oracle_parent_reset.py', ROOT / 'syn/prove_tri_oracle_parent_clock.py',
                 ROOT / 'syn/prove_tri_oracle_packaged_products.py', ROOT / 'syn/prove_tri_oracle_packaged_reductions.py',
                 ROOT / 'syn/prove_tri_oracle_packaged_valid.py',
                 ROOT / 'syn/audit_tri_oracle_mapped_redundancy.py', ROOT / 'syn/link_tri_oracle_indexed_whole_chip.py',
                 ROOT / 'syn/plan_tri_oracle_grouped_reset.py', ROOT / 'verilog/tri_oracle_attention_head_classifier410.sv']:
        pin(path)
    results = {}
    for path, name in reached[:limit]:
        model = ClassifierCone(bodies[name], library, states)
        results[name] = prove_module(model) | dict(path=path)
        print('HEAD_RATIO_MODULE_PROVED', name, flush=True)
    rejected = rejection_controls(bodies[reached[0][1]], library, states)
    for name, checksum in evidence.items():
        pin(ROOT / name, checksum)
    report = dict(state='mapped_modular_head_ratio_update_cones_verified', candidate_sha256=structure['candidate_sha256'],
        classifiers=results, reachable_classifiers=len(reached), complete_classifier_inventory=(len(results) == len(reached)),
        rejected_controls=rejected,
        tested_corners=3, evidence_sha256=evidence, wall_seconds=time.monotonic() - started,
        peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        full_head_prediction_verified=False, complete_paper_architecture_verified=False,
        advance_to_clock_distribution_or_routing_allowed=False,
        scope='All26 low modular update bits compared to independent arithmetic for every ratio-bit index and all binary operand values. '
              'Actual gate functions and register-cut outputs from the current mapped candidate; three Liberty corners agree. '
              'The27-bit signed positive decision and final error suppression are checked under the reported encoded capture predicate. '
              'This does not prove reachable state sequences, sequential updates, count accumulation, scheduling, parent controls, '
              'trained workload execution, task accuracy, timing or complete paper matching.')
    with output.open('x') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--limit', type=int)
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.output, arguments.limit), indent=2))
