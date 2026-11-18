"""Prove the local ratio epoch under stable configuration, not full prediction.

The classifier inputs must hold the numerator/denominator through the epoch.
This verifier checks actual local register updates and reset functions, not
parent configuration stability, score accumulation or physical timing.
"""
from hashlib import file_digest, sha256
import json
from mmap import mmap, ACCESS_READ
from pathlib import Path
import re
import resource
import time

from prove_tri_oracle_head_ratio import ClassifierCone, prove_module, PREFIX
from prove_tri_oracle_packaged_products import BRACES, CANDIDATE, ROOT, liberty_group, memory_guard, parse_function
from prove_tri_oracle_packaged_reductions import DecisionGraph
from prove_tri_oracle_parent_reset import Module
from prove_tri_oracle_parent_clock import read_clock_library


def primary_state(description):
    starts = {m.end()-1: m for m in re.finditer(r'\bff\s*\(([^)]*)\)\s*\{', description)}
    direct, depth = [], 0
    for token in BRACES.finditer(description):
        if token[0] == '{':
            if depth == 0 and token.start() in starts:
                direct.append(starts[token.start()])
            depth += 1
        elif token[0] == '}':
            depth -= 1
    assert depth == 0 and len(direct) == 1, 'Expected one primary flip-flop'
    match, = direct
    assert [x.strip() for x in match[1].split(',')] == ['IQ', 'IQN'], 'Unsupported state variables'
    text = liberty_group(description, match.end())
    attribute = re.compile(r'\b(\w+)\s*:\s*"([^"]*)"\s*;')
    entries = attribute.findall(text)
    model = dict(entries)
    assert len(model) == len(entries) and not attribute.sub('', text).strip(), 'Unknown state statement'
    assert set(model) in ({'clocked_on', 'next_state', 'clear'}, {'clocked_on', 'next_state', 'preset'}), 'Unsupported state attributes'
    for expression in model.values():
        parse_function(expression)
    return model


class SequentialClassifier(ClassifierCone):
    def __init__(self, body, library, states):
        super().__init__(body, library, states)
        for name in ('clk', 'rst_n'):
            assert self.module.directions.get(name) == 'input' and self.module.declared[name] is None, 'Clock/reset port is not a scalar input'

    def transition(self, instance, expected_output):
        master, raw = self.module.cells[instance]
        assert self.states[master] == {'ff': 1}, 'Register state kind differs'
        pins = {name: self.module.expression(value) for name, value in raw.items()}
        model = self.library[master, '__sequence_ff__']
        assert parse_function(model['clocked_on']) == 'CP' and pins['CP'] == ('clk',), 'Register clock differs'
        assert pins['Q'] == (expected_output,) and self.library[master, 'Q']['function'] == 'IQ', 'Register output polarity or binding differs'
        state = self.graph.variable(expected_output)

        def function(expression):
            values = {'IQ': state, 'IQN': self.graph.operation('!', state)}
            for name in set(re.findall(r'[A-Za-z_]\w*', expression)) - values.keys():
                assert self.library[master, name]['direction'] == 'input' and len(pins[name]) == 1, 'Invalid state input'
                values[name] = self.cone(pins[name][0])
            return self.graph.function(expression, values)

        reset = 'clear' if 'clear' in model else 'preset'
        return function(model['next_state']), function(model[reset]), int(reset == 'preset')


def register_specification():
    result = []
    for instance, word, width, reset in [
        ('serial_ratio.difference_reg', 'serial_ratio.difference', 26, 0),
        ('serial_ratio.ratio_bit_reg', 'serial_ratio.ratio_bit', 3, 1),
        ('state_reg', 'state', 3, 0),
        ('total_inner_reg', 'total_inner', 18, 0),
        ('total_outer_reg', 'total_outer', 18, 0),
    ]:
        result.extend((f'{instance}[{bit}]', f'{word}[{bit}]', reset) for bit in range(width))
    result.extend([('streaming_reg', 'streaming', 0), ('out_error_reg', 'out_error', 0)])
    return result


def equal_functions(graph, actual, expected):
    assert len(actual) == len(expected)
    if actual == expected:
        return 0
    observed, required = [], []
    for left, right in zip(actual, expected, strict=True):
        if left == right:
            continue
        node = graph.nodes[right]
        if node[0] == 'v':
            # Exhaust both values of the retained register bit. This is exact
            # Shannon expansion, not an assumption that the register is zero.
            # It also removes irrelevant score logic before diagram conversion.
            for value in (0, 1):
                cofactor, = graph.substitute([left], {node[1]: value})
                observed.append(cofactor)
                required.append(value)
        else:
            observed.append(left)
            required.append(right)
    actual, expected = observed, required
    if actual == expected:
        return 0
    leaves = set().union(*(graph.dependencies(x) for x in [*actual, *expected]))
    order = [f'cfg_ratio_{kind}[{bit}]' for bit in range(8) for kind in ('den', 'num')]
    order += [f'{word}[{bit}]' for bit in range(26)
              for word in ('serial_ratio.difference', 'total_outer', 'total_inner')]
    order = [name for name in order if name in leaves]
    order += sorted(leaves - set(order))
    decision = DecisionGraph(order, maximum_nodes=250000)
    split = len(actual)
    values = decision.convert(graph, [*actual, *expected])
    assert values[:split] == values[split:], 'Mapped sequence transition differs'
    return len(decision.nodes)


def prove_sequence(model):
    graph = model.graph
    specification = register_specification()
    data, asynchronous, resets = {}, [], []
    for instance, output, reset in specification:
        value, active, actual_reset = model.transition(instance, output)
        assert actual_reset == reset, ('Register reset value differs', instance)
        data[output] = value
        asynchronous.append(active)
        resets.append(reset)
    reset_graph = DecisionGraph(['rst_n'])
    reset_values = reset_graph.convert(graph, asynchronous)
    assert reset_values == [reset_graph.operation('!', reset_graph.variable('rst_n'))] * 70, 'Asynchronous reset binding differs'
    difference = [graph.variable(f'serial_ratio.difference[{bit}]') for bit in range(26)]
    next_difference = [model.cone(f'serial_ratio.next_difference[{bit}]') for bit in range(26)]
    difference_data = [data[f'serial_ratio.difference[{bit}]'] for bit in range(26)]
    counter_data = [data[f'serial_ratio.ratio_bit[{bit}]'] for bit in range(3)]
    state_data = [data[f'state[{bit}]'] for bit in range(3)]
    held_names = [f'{word}[{bit}]' for word in ('total_inner', 'total_outer') for bit in range(18)] + ['out_error']
    held_data = [data[name] for name in held_names]
    held_values = [graph.variable(name) for name in held_names]
    streaming_data = data['streaming']
    master, stream_pins = model.module.cells['streaming_reg']
    captured_data = model.cone(model.module.expression(stream_pins['D'])[0])
    peaks, cases = [], 0
    for state in range(8):
        for selected in range(8):
            memory_guard(8.5)
            control = {'rst_n': 1}
            control.update({f'state[{bit}]': (state >> bit) & 1 for bit in range(3)})
            control.update({f'serial_ratio.ratio_bit[{bit}]': (selected >> bit) & 1 for bit in range(3)})
            actual = model.graph.substitute([*difference_data, *counter_data], control)
            expected_difference = (next_difference if selected else difference) if state == 4 else [0] * 26
            expected_counter = max(selected - 1, 0) if state == 4 else 7
            expected = model.graph.substitute(expected_difference + [(expected_counter >> bit) & 1 for bit in range(3)], control)
            peaks.append(equal_functions(graph, actual, expected))
            out_valid, = graph.substitute([model.cone('out_valid')], control)
            peaks.append(equal_functions(graph, [out_valid], [int(state == 6)]))
            if state in (4, 6):
                peaks.append(equal_functions(graph, graph.substitute(held_data, control), held_values))
                if state == 4:
                    expected_state = 4 if selected else 6
                    peaks.append(equal_functions(graph, graph.substitute(state_data, control), [(expected_state >> bit) & 1 for bit in range(3)]))
                    expected_stream = captured_data if selected == 0 else graph.variable('streaming')
                    peaks.append(equal_functions(graph, graph.substitute([streaming_data], control), graph.substitute([expected_stream], control)))
                else:
                    peaks.append(equal_functions(graph, graph.substitute([streaming_data], control), [graph.variable('streaming')]))
                    for ready in (0, 1):
                        expected_state = 0 if ready else 6
                        peaks.append(equal_functions(graph, graph.substitute(state_data, control | {'out_ready': ready}), [(expected_state >> bit) & 1 for bit in range(3)]))
            cases += 1
    return dict(registers=70,reset_zero_registers=resets.count(0),reset_one_registers=resets.count(1),
        encoded_state_counter_cases=cases,maximum_decision_nodes=max(peaks),
        entry_counter=7,entry_difference=0,classification_capture_counter=0,
        classification_cycles=8,classification_state=4,result_state=6,
        count_and_error_stability_during_classification=True,
        local_decision_count_error_retention_until_ready=True,local_clock_and_async_reset_bindings_verified=True,
        parent_configuration_stability_verified=False)


def range_invariant():
    """Induction: prefix difference = outer*den_prefix - inner*num_prefix.

    Appending one coefficient bit doubles the prefix and adds that bit.
    For nonnegative intensities bounded by C, each prefix product is between
    zero and C*prefix_max, so their difference lies in the corresponding
    symmetric interval (not twice that interval). Thus every stored prefix
    fits signed26; the final signed27 word is the exact integer difference.
    This composition requires fixed coefficients and held intensity registers.
    """
    checks = 0
    for coefficient in range(256):
        prefix = 0
        for bit in range(7, -1, -1):
            prefix = 2 * prefix + ((coefficient >> bit) & 1)
            assert prefix == coefficient >> bit
            checks += 1
    maximum_count = (1 << 18) - 1
    bounds = [maximum_count * ((1 << bits) - 1) for bits in range(1, 9)]
    assert all(bound < (1 << 25) for bound in bounds[:7])
    assert bounds[7] < (1 << 26)
    return dict(coefficient_identity_cases=checks,maximum_intensity=maximum_count,
        absolute_prefix_bounds=bounds,maximum_stored_prefix=bounds[6],maximum_final_difference=bounds[7],
        required_assumption='Numerator and denominator remain stable at the local classifier ports for all8 classification cycles.',
        parent_assumption_discharged=False)


def rejection_controls(body, library, states):
    from prove_tri_oracle_parent_reset import INSTANCE, identifier
    from prove_tri_oracle_packaged_products import PIN
    digest = sha256(body).hexdigest()
    library_before = [(key, dict(value)) for key, value in sorted(library.items())]

    def replace_pin(instance, pin, replacement):
        match, = (m for m in INSTANCE.finditer(body) if identifier(m[2].decode()) == instance)
        binding, = (m for m in PIN.finditer(match[3]) if identifier(m[1].decode()) == pin)
        changed = match[3][:binding.start(2)] + replacement + match[3][binding.end(2):]
        result = body[:match.start(3)] + changed + body[match.end(3):]
        assert result != body, 'Ineffective sequence mutation'
        return result

    controls = [
        ('wrong_local_clock', replace_pin('serial_ratio.difference_reg[0]', 'CP', b'cfg_valid'), 'Register clock differs'),
        ('disconnected_counter_preset', replace_pin('serial_ratio.ratio_bit_reg[0]', 'SDN', b"1'b1"), 'Asynchronous reset binding differs'),
        ('stalled_bit_counter', replace_pin('serial_ratio.ratio_bit_reg[0]', 'D', b'\\serial_ratio.ratio_bit [0]'), 'Mapped sequence transition differs'),
        ('count_update_during_classification', replace_pin('total_inner_reg[0]', 'D', b"1'b1"), 'Mapped sequence transition differs'),
        ('premature_classification_exit', replace_pin('state_reg[0]', 'D', b"1'b1"), 'Mapped sequence transition differs'),
    ]
    rejected = []
    for label, altered, expected in controls:
        try:
            prove_sequence(SequentialClassifier(altered, library, states))
        except (AssertionError, ValueError, KeyError) as error:
            assert expected in str(error), ('Unrelated sequence rejection', label, str(error))
            rejected.append(dict(control=label, rejection=str(error)))
        else:
            raise AssertionError(('Corrupted sequence accepted', label))
    assert sha256(body).hexdigest() == digest, 'Original classifier bytes changed'
    assert [(key, dict(value)) for key, value in sorted(library.items())] == library_before, 'Original sequence library changed'
    return rejected


def verify(output, limit=None):
    from audit_tri_oracle_mapped_redundancy import hierarchy
    from link_tri_oracle_indexed_whole_chip import spans
    assert __debug__ and not Path('/.dockerenv').exists()
    assert output.resolve().is_relative_to((ROOT / '.cache').resolve()) and not output.exists()
    memory_guard(10)
    started, evidence = time.monotonic(), {}

    def pin(path, expected=None):
        with path.open('rb') as stream:
            actual = file_digest(stream, 'sha256').hexdigest()
        assert expected is None or expected == actual, ('Changed sequence evidence', path)
        assert evidence.setdefault(str(path.relative_to(ROOT)), actual) == actual
        return path

    prior = json.loads(pin(ROOT / 'records/tri_oracle_packaged_head_ratio_arithmetic.json').read_text())
    for name, checksum in prior['evidence_sha256'].items():
        pin(ROOT / name, checksum)
    pin(CANDIDATE, prior['candidate_sha256'])
    storage = json.loads(pin(ROOT / 'records/tri_oracle_packaged_storage_accounting.json').read_text())
    detail_name, = storage['full_detail_cache']
    detail = json.loads(pin(ROOT / detail_name, storage['full_detail_cache'][detail_name]).read_text())
    states = {name: row['state_kinds'] for name, row in detail['standard_cell_state_by_master'].items()}
    topology = hierarchy(CANDIDATE)
    reached = []

    def walk(master, path, parents):
        assert master not in parents, 'Recursive classifier hierarchy'
        if master.startswith(PREFIX):
            reached.append((path, master))
        for instance, child in topology[master].items():
            walk(child, path + '/' + instance.removeprefix('\\'), parents | {master})

    walk('tri_oracle_chip_credited_request', 'tri_oracle_chip_credited_request', set())
    assert len(reached) == len({master for _, master in reached}) == 20
    assert {master for _, master in reached} == set(prior['module_sha256'])
    bodies = {}
    with CANDIDATE.open('rb') as stream, mmap(stream.fileno(), 0, access=ACCESS_READ) as source:
        spans_for = spans(source)
        for _, master in reached:
            lo, hi = spans_for[master]
            bodies[master] = source[lo:hi]
            assert sha256(bodies[master]).hexdigest() == prior['module_sha256'][master]
    modules = {master: Module(body) for master, body in bodies.items()}
    masters = {kind for module in modules.values() for kind, _ in module.cells.values()}
    sequential = {module.cells[instance][0] for module in modules.values() for instance, _, _ in register_specification()}
    libraries = []
    for suffix in ('ssg0p9v125c', 'tt1v25c', 'ffg1p05vm40c'):
        name, = (name for name in evidence if Path(name).name == f'tcbn28hpcplusbwp12t40p140{suffix}.lib')
        path = ROOT / name
        raw = read_clock_library(path, masters)
        library = {key: {k: v for k, v in value.items() if k in ('direction', 'function')} for key, value in raw.items()}
        text = path.read_text()
        for master in sequential:
            match, = re.finditer(r'(?m)^cell\s*\(' + re.escape(master) + r'\)\s*\{', text)
            library[master, '__sequence_ff__'] = primary_state(liberty_group(text, match.end()))
        for module in modules.values():
            master = module.cells['streaming_reg'][0]
            library[master, '__capture_ff__'] = library[master, '__sequence_ff__']
        libraries.append(library)
    assert libraries[0] == libraries[1] == libraries[2], 'Sequential or Boolean functions differ across corners'
    for path in [Path(__file__).resolve(), ROOT / 'syn/test_tri_oracle_head_ratio_sequence_logic.py']:
        pin(path)
    invariant = range_invariant()
    results = {}
    for path, master in reached[:limit]:
        model = SequentialClassifier(bodies[master], libraries[0], states)
        arithmetic = prove_module(model)
        sequence = prove_sequence(model)
        results[master] = dict(path=path, module_sha256=model.body_sha256, arithmetic=arithmetic, sequence=sequence)
        print('HEAD_RATIO_SEQUENCE_PROVED', master, flush=True)
    rejected = rejection_controls(bodies[reached[0][1]], libraries[0], states)
    for name, checksum in evidence.items():
        pin(ROOT / name, checksum)
    report = dict(state='local_mapped_ratio_epoch_verified_under_stable_configuration',
        candidate_sha256=prior['candidate_sha256'],classifiers=results,complete_classifier_inventory=(len(results) == 20),
        rejected_controls=rejected,
        conditional_range_invariant=invariant,evidence_sha256=evidence,wall_seconds=time.monotonic() - started,
        peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        parent_configuration_stability_verified=False,full_head_prediction_verified=False,
        assumptions=['Local numerator and denominator ports stay fixed for the complete epoch.',
                     'The epoch begins at a state4 entry following a non4 edge that initializes difference0/counter7; arbitrary initial state4 values are excluded.',
                     'Local reset remains deasserted during classification; binary state is sampled on settled positive clock edges.'],
        complete_paper_architecture_verified=False,advance_to_clock_distribution_or_routing_allowed=False,
        scope='Candidate-local classification epoch: actual sequential functions, reset values, entry initialization,8-step counter progression, count/error retention and result hold. '
              'From an initialized entry, composes with rerun arithmetic proofs and a signed-prefix bound to establish outer*denominator > inner*numerator under stable local numerator/denominator inputs. '
              'Eventual entry from valid traffic, parent input/tag stability, complete response stability, pre-classification intensity accumulation, full prediction, timing and paper-result matching remain unqualified.')
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
