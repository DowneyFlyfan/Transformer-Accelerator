"""Prove mapped product-register next states using original Liberty functions."""
from functools import cache
from hashlib import file_digest, sha256
from itertools import product
import json
from mmap import ACCESS_READ, mmap
from pathlib import Path
import re
import resource
import sys
import time


@cache
def parse_function(expression):
    tokens = re.findall(r"[A-Za-z_]\w*|[01]|[()!+^&*|']", expression)
    if ''.join(tokens) != re.sub(r'\s+', '', expression):
        raise ValueError(f'Unsupported Liberty Boolean syntax: {expression}')
    cursor = 0

    def unary():
        nonlocal cursor
        if cursor == len(tokens):
            raise ValueError('Missing Boolean operand')
        token = tokens[cursor]
        cursor += 1
        if token == '!':
            node = ('!', unary())
        elif token == '(':
            node = disjunction()
            if cursor == len(tokens) or tokens[cursor] != ')':
                raise ValueError('Unclosed Boolean group')
            cursor += 1
        elif re.fullmatch(r'[A-Za-z_]\w*|[01]', token):
            node = token
        else:
            raise ValueError(f'Unexpected Boolean token: {token}')
        while cursor < len(tokens) and tokens[cursor] == "'":
            cursor += 1
            node = ('!', node)
        return node

    def conjunction():
        nonlocal cursor
        node = unary()
        while cursor < len(tokens) and tokens[cursor] not in (')', '+', '|', '^'):
            if tokens[cursor] in ('&', '*'):
                cursor += 1
            node = ('&', node, unary())
        return node

    def exclusive_or():
        nonlocal cursor
        node = conjunction()
        while cursor < len(tokens) and tokens[cursor] == '^':
            cursor += 1
            node = ('^', node, conjunction())
        return node

    def disjunction():
        nonlocal cursor
        node = exclusive_or()
        while cursor < len(tokens) and tokens[cursor] in ('+', '|'):
            cursor += 1
            node = ('|', node, exclusive_or())
        return node

    result = disjunction()
    if cursor != len(tokens):
        raise ValueError('Trailing Boolean tokens')
    return result


class BooleanGraph:
    """A shared expression graph with exact two-state simplification."""
    def __init__(self):
        self.nodes = [('c', 0), ('c', 1)]
        self.index = {node: i for i, node in enumerate(self.nodes)}
        self._dependencies = {}

    def intern(self, node):
        if node not in self.index:
            self.index[node] = len(self.nodes)
            self.nodes.append(node)
        return self.index[node]

    def variable(self, name):
        return self.intern(('v', name))

    def operation(self, operator, left, right=None):
        if operator == '!':
            if left < 2:
                return 1 - left
            if self.nodes[left][0] == '!':
                return self.nodes[left][1]
            return self.intern(('!', left))
        if operator not in ('&', '|', '^') or right is None:
            raise ValueError('Unknown Boolean operator')
        if left > right:
            left, right = right, left
        if operator == '&':
            if left == 0:
                return 0
            if left == 1 or left == right:
                return right
        if operator == '|':
            if left == 0 or left == right:
                return right
            if left == 1:
                return 1
        if operator == '^':
            if left == right:
                return 0
            if left == 0:
                return right
            if left == 1:
                return self.operation('!', right)
        if self.nodes[right] == ('!', left) or self.nodes[left] == ('!', right):
            return 0 if operator == '&' else 1
        return self.intern((operator, left, right))

    def function(self, expression, pins):
        def instantiate(node):
            if isinstance(node, str):
                return int(node) if node in ('0', '1') else pins[node]
            return self.operation(node[0], *(instantiate(child) for child in node[1:]))
        return instantiate(parse_function(expression))

    def dependencies(self, root):
        if root not in self._dependencies:
            node = self.nodes[root]
            if node[0] == 'c':
                result = frozenset()
            elif node[0] == 'v':
                result = frozenset([node[1]])
            else:
                result = frozenset().union(*(self.dependencies(x) for x in node[1:]))
            self._dependencies[root] = result
        return self._dependencies[root]

    def substitute(self, roots, values):
        assert all(value in (0, 1) for value in values.values())
        @cache
        def visit(root):
            node = self.nodes[root]
            if node[0] == 'c':
                return root
            if node[0] == 'v':
                return int(values[node[1]]) if node[1] in values else root
            return self.operation(node[0], *(visit(child) for child in node[1:]))
        result = [visit(root) for root in roots]
        visit.cache_clear()
        return result


    def evaluate(self, roots, values, mask=1):
        assert mask > 0 and all(isinstance(x, int) and 0 <= x <= mask for x in values.values())
        @cache
        def visit(root):
            operator, *args = self.nodes[root]
            if operator == 'c':
                return mask if args[0] else 0
            if operator == 'v':
                return values[args[0]]
            left = visit(args[0])
            if operator == '!':
                return left ^ mask
            right = visit(args[1])
            if operator == '&':
                return left & right
            if operator == '|':
                return left | right
            return left ^ right
        result = [visit(root) for root in roots]
        visit.cache_clear()
        return result


@cache
def product_truth_tables():
    """Bit i of each integer is the result for unsigned pair (i >> 8, i & 255)."""
    packed = [bytearray(8192) for _ in range(16)]
    for index in range(65536):
        left, right = index >> 8, index & 255
        left -= 256 if left >= 128 else 0
        right -= 256 if right >= 128 else 0
        value = (left * right) & 65535
        byte, offset = index >> 3, index & 7
        for bit in range(16):
            if value & (1 << bit):
                packed[bit][byte] |= 1 << offset
    return tuple(int.from_bytes(value, 'little') for value in packed)


def input_truth_tables():
    result = []
    for bit in range(16):
        if bit < 3:
            data = bytes([sum(((i >> bit) & 1) << i for i in range(8))]) * 8192
        else:
            length = 1 << (bit - 3)
            data = (bytes(length) + b'\xff' * length) * (8192 // (2 * length))
        assert len(data) == 8192
        result.append(int.from_bytes(data, 'little'))
    return tuple(result)


CELL = re.compile(rb'(?m)^[ \t]+([\w$]+)\s+(\\\S+|[\w$]+)\s*\(\s*(\.[^;]*)\);')
PIN = re.compile(rb'\.([\\\w\[\]]+)\s*\(([^()]*)\)')
PRODUCT_REGISTER = re.compile(r'product\[(\d+)\]\.value_reg\[(\d+)\]')
IDENTIFIER = rb'(?:\\[A-Za-z0-9_$.\[\]]+\s+|[A-Za-z_$][\w$]*)'
DECLARATION = re.compile(rb'\b(input|output|wire)\s+(?:wire\s+)?(?:signed\s+)?'
                         rb'(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s+)?('
                         + IDENTIFIER + rb'(?:\s*,\s*' + IDENTIFIER + rb')*)\s*;')


def structural_cells(body):
    comments = re.compile(rb'\\[^\s]+|/\*[\s\S]*?\*/|//[^\n]*')
    clean = comments.sub(lambda m: m[0] if m[0].startswith(b'\\') else b'', body)
    header = re.match(rb'\s*module\s+[\w$]+\s*\(([^;]*)\)\s*;', clean)
    if header is None:
        raise ValueError('Unsupported mapped module text: header')
    ports = [name.strip().decode() for name in header[1].split(b',')]
    if len(set(ports)) != len(ports) or not all(re.fullmatch(r'[A-Za-z_$][\w$]*', name) for name in ports):
        raise ValueError('Unsupported mapped module text: old-style port list required')
    rest = clean[header.end():].strip()
    if not rest.endswith(b'endmodule'):
        raise ValueError('Unsupported mapped module text: material outside module')
    rest = rest[:-len(b'endmodule')]
    rows = CELL.findall(rest)
    rest = CELL.sub(b'', rest)
    declared = {}
    directions = {}
    canonical = set()
    for match in DECLARATION.finditer(rest):
        bounds = (int(match[2]), int(match[3])) if match[2] is not None else None
        for raw in match[4].split(b','):
            name = raw.strip().decode().removeprefix('\\')
            if name in declared:
                raise ValueError('Repeated declared net: ' + name)
            declared[name] = bounds
            if match[1] in (b'input', b'output'):
                directions[name] = match[1]
            labels = {name} if bounds is None else {f'{name}[{b}]' for b in range(min(bounds), max(bounds) + 1)}
            if canonical & labels:
                raise ValueError('Ambiguous declared net: ' + name)
            canonical.update(labels)
    rest = DECLARATION.sub(b'', rest).strip()
    if rest or set(directions) != set(ports):
        raise ValueError('Unsupported mapped module text: ' + repr(rest[:100]))
    return rows, declared


def bindings(fields, declared):
    matches = PIN.findall(fields)
    result = {}
    for pin, raw in matches:
        value = raw.decode().lstrip()
        if not value.strip() or re.fullmatch(r"1'[bB][01]", value.strip()):
            label = value.strip()
        else:
            if value.startswith('\\'):
                match = re.fullmatch(r'\\([A-Za-z0-9_$.\[\]]+)(?:\s+\[\s*(\d+)\s*\]\s*|\s+)', value)
            else:
                match = re.fullmatch(r'([A-Za-z_$][\w$]*)(?:\s*\[\s*(\d+)\s*\])?\s*', value)
            if match is None:
                raise ValueError('Unsupported mapped net reference: ' + value)
            name, bit = match.groups()
            if name not in declared:
                raise ValueError('Undeclared mapped net: ' + name)
            bounds = declared[name]
            if (bounds is None) != (bit is None):
                raise ValueError('Mapped net selection width differs: ' + value)
            if bit is not None and not min(bounds) <= int(bit) <= max(bounds):
                raise ValueError('Mapped net index is out of bounds: ' + value)
            label = name if bit is None else f'{name}[{int(bit)}]'
        result[pin.decode().removeprefix('\\')] = label
    assert len(result) == len(matches)
    assert not PIN.sub(b'', fields).strip(b' \t\r\n,')
    return result


class MappedProducts:
    def __init__(self, body, library, states):
        self.body_sha256 = sha256(body).hexdigest()
        self.graph = BooleanGraph()
        self.library = library
        self.states = states
        self.drivers = {}
        self.products = {}
        self.cones = {}
        self.visiting = set()
        cells, self.declared = structural_cells(body)
        for master, name, fields in cells:
            master, name = master.decode(), name.decode().removeprefix('\\')
            pins = bindings(fields, self.declared)
            for pin, net in pins.items():
                properties = library[master, pin]
                if properties['direction'] == 'output' and net:
                    assert not net.startswith("1'"), 'Cell output is connected to a constant'
                    assert net not in self.drivers, ('Multiple drivers', net)
                    self.drivers[net] = (master, pin, pins)
            if match := PRODUCT_REGISTER.fullmatch(name):
                key = tuple(map(int, match.groups()))
                assert key not in self.products
                assert states[master] == {'ff': 1}, 'Product register is not a single flip-flop'
                assert pins['CP'] == 'clk', 'Product register clock differs'
                assert library[master, '__product_ff__'] == {'clocked_on': 'CP', 'next_state': 'D'}, \
                    'Product register sequential semantics differ'
                assert library[master, 'Q']['function'] == 'IQ'
                lane, bit = key
                assert pins['Q'] == f'product[{lane}].value[{bit}]'
                self.products[key] = pins
        assert self.products.keys() == {(lane, bit) for lane in range(256) for bit in range(16)}

    def cone(self, net):
        if net in self.cones:
            return self.cones[net]
        assert net not in self.visiting, ('Combinational cycle', net)
        self.visiting.add(net)
        if re.fullmatch(r"1'[bB][01]", net):
            result = int(net[-1])
        elif net not in self.drivers:
            result = self.graph.variable(net)
        else:
            master, pin, pins = self.drivers[net]
            function = self.library[master, pin]['function']
            if self.states.get(master):
                assert self.states[master] == {'ff': 1}, (master, self.states[master])
                assert function in ('IQ', 'IQN'), (master, function)
                if function == 'IQN' and 'Q' in pins:
                    result = self.graph.operation('!', self.graph.variable(pins['Q']))
                else:
                    result = self.graph.variable(net)
            else:
                symbols = set(re.findall(r'[A-Za-z_]\w*', function))
                operands = {symbol: self.cone(pins[symbol]) for symbol in symbols}
                result = self.graph.function(function, operands)
        self.visiting.remove(net)
        self.cones[net] = result
        return result

    def prove(self):
        memory_guard()
        graph = self.graph
        keys = sorted(self.products)
        roots = [self.cone(self.products[key]['D']) for key in keys]
        for (lane, bit), root in zip(keys, roots, strict=True):
            allowed = {'in_valid', 'out_ready', 'out_valid', f'lane_enable[{lane}]',
                       self.products[lane, bit]['Q']}
            allowed.update(f'operand_{operand}[{lane * 8 + b}]'
                           for operand in ('a', 'b') for b in range(8))
            assert graph.dependencies(root) <= allowed, ('Foreign lane or state input', lane, bit,
                                                         graph.dependencies(root) - allowed)
        writing = None
        held_cases = written_cases = 0
        for valid, ready, occupied in product(range(2), repeat=3):
            memory_guard()
            control = {'in_valid': valid, 'out_ready': ready, 'out_valid': occupied}
            if valid and (ready or not occupied):
                enabled = control | {f'lane_enable[{lane}]': 1 for lane in range(256)}
                disabled = control | {f'lane_enable[{lane}]': 0 for lane in range(256)}
                current = graph.substitute(roots, enabled)
                assert all(node == 0 for node in graph.substitute(roots, disabled)), 'Disabled product is not zero'
                if writing is None:
                    writing = current
                else:
                    assert current == writing, 'Write arithmetic depends on handshake case'
                written_cases += 1
            else:
                current = graph.substitute(roots, control)
                assert all(node == graph.variable(self.products[key]['Q'])
                           for key, node in zip(keys, current, strict=True)), 'Stalled product does not hold'
                held_cases += 1
        assert held_cases == 5 and written_cases == 3 and writing is not None
        patterns = input_truth_tables()
        assignments = {f'operand_{operand}[{lane * 8 + bit}]': patterns[bit + offset]
                       for operand, offset in [('a', 8), ('b', 0)]
                       for lane in range(256) for bit in range(8)}
        actual = graph.evaluate(writing, assignments, mask=(1 << 65536) - 1)
        expected = product_truth_tables()
        assert all(value == expected[bit] for (lane, bit), value in zip(keys, actual, strict=True)), \
            'Signed product truth vector differs from integer multiplication'
        memory_guard()
        return {'registered_products': 256, 'product_bits': 4096,
                'operand_pairs_per_lane': 65536, 'handshake_cases': 8,
                'hold_cases': held_cases, 'write_cases': written_cases,
                'disabled_write_value': 0, 'lane_and_feedback_dependencies_isolated': True,
                'mapped_product_cone_nets': len(self.cones), 'expression_nodes': len(graph.nodes),
                'array_module_sha256': self.body_sha256}


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.cache/wide_packaged_host_link/architecture_check'
CANDIDATE = ROOT / '.cache/wide_packaged_host_link/drive_repair/host_legalized/candidate.v'


def memory_guard(reserve_gib=6):
    available, = re.findall(r'(?m)^MemAvailable:\s+(\d+) kB$', Path('/proc/meminfo').read_text())
    assert int(available) * 1024 >= reserve_gib * 1024**3, 'Host memory reserve reached'


BRACES = re.compile(r'"(?:\\.|[^"\\])*"|/\*[\s\S]*?\*/|//[^\n]*|[{}]')


def liberty_group(text, opening):
    depth = 1
    for token in BRACES.finditer(text, opening):
        if token[0] == '{':
            depth += 1
        elif token[0] == '}':
            depth -= 1
        if depth == 0:
            return text[opening:token.start()]
    raise ValueError('Unclosed Liberty group')


def product_flip_flop(description):
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
        raise ValueError('Product cell must have exactly one direct flip-flop')
    match, = direct
    if [name.strip() for name in match[1].split(',')] != ['IQ', 'IQN']:
        raise ValueError('Product flip-flop state variables differ')
    state = liberty_group(description, match.end())
    attribute = re.compile(r'\b(\w+)\s*:\s*"([^"]*)"\s*;')
    values = attribute.findall(state)
    result = dict(values)
    if len(result) != len(values) or attribute.sub('', state).strip() or result != {'clocked_on': 'CP', 'next_state': 'D'}:
        raise ValueError('Product flip-flop transition semantics differ')
    return result


def inputs():
    sys.path.insert(0, str(ROOT / 'syn'))
    from link_tri_oracle_indexed_whole_chip import spans
    from plan_tri_oracle_grouped_reset import read_library
    memory_guard(12)
    evidence = {}

    def pin(path, expected=None):
        with path.open('rb') as stream:
            value = file_digest(stream, 'sha256').hexdigest()
        assert expected is None or value == expected, path
        evidence[str(path.relative_to(ROOT))] = value
        return path

    structure = json.loads(pin(ROOT / 'records/tri_oracle_packaged_compute_structure.json').read_text())
    assert structure['state'] == 'packaged_register_geometry_and_reachable_prediction_ownership_verified'
    for name, checksum in structure['evidence_sha256'].items():
        pin(ROOT / name, checksum)
    pin(CANDIDATE, structure['candidate_sha256'])
    names = set(structure['array_register_inventory'])
    with CANDIDATE.open('rb') as stream, mmap(stream.fileno(), 0, access=ACCESS_READ) as source:
        modules = spans(source)
        assert {name for name in modules if name.startswith('tri_oracle_pe_array_verified_bank')} == names
        ranges = {name: modules[name] for name in sorted(names)}
        masters = {match[1].decode() for low, high in ranges.values()
                   for match in CELL.finditer(source, low, high)}
        product_masters = {match[1].decode() for low, high in ranges.values()
                           for match in CELL.finditer(source, low, high)
                           if PRODUCT_REGISTER.fullmatch(match[2].decode().removeprefix('\\'))}
    assert len(ranges) == 20
    libraries = []
    for suffix in ('ssg0p9v125c', 'tt1v25c', 'ffg1p05vm40c'):
        basename = f'tcbn28hpcplusbwp12t40p140{suffix}.lib'
        (name, wanted), = ((name, checksum) for name, checksum in structure['evidence_sha256'].items()
                           if Path(name).name == basename)
        path = ROOT / name
        rows = read_library(pin(path, wanted), masters)
        models = {key: {k: v for k, v in row.items() if k in ('direction', 'function')}
                  for key, row in rows.items()}
        text = path.read_text()
        for master in product_masters:
            match, = re.finditer(r'(?m)^cell\s*\(' + re.escape(master) + r'\)\s*\{', text)
            models[master, '__product_ff__'] = product_flip_flop(liberty_group(text, match.end()))
        libraries.append(models)
    assert libraries[0] == libraries[1] == libraries[2], 'Corner Boolean models differ'
    storage = json.loads(pin(ROOT / 'records/tri_oracle_packaged_storage_accounting.json').read_text())
    detail_name, = storage['full_detail_cache']
    detail = json.loads(pin(ROOT / detail_name, storage['full_detail_cache'][detail_name]).read_text())
    states = {name: row['state_kinds'] for name, row in detail['standard_cell_state_by_master'].items()}
    pin(Path(__file__).resolve())
    pin(ROOT / 'syn/test_tri_oracle_packaged_product_logic.py')
    pin(ROOT / 'syn/plan_tri_oracle_grouped_reset.py')
    pin(ROOT / 'syn/link_tri_oracle_indexed_whole_chip.py')
    return ranges, libraries[0], states, evidence, structure


def inspect_range(task):
    name, bounds, library, states = task
    started = time.monotonic()
    memory_guard()
    with CANDIDATE.open('rb') as stream:
        stream.seek(bounds[0])
        body = stream.read(bounds[1] - bounds[0])
    result = MappedProducts(body, library, states).prove()
    result.update(wall_seconds=time.monotonic() - started,
                  peak_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
    print('PACKAGED_PRODUCT_ARRAY_PROVED', name, result['registered_products'], flush=True)
    return name, result


def controls(ranges, library, states, evidence, structure):
    name = 'tri_oracle_pe_array_verified_bank0'
    low, high = ranges[name]
    with CANDIDATE.open('rb') as stream:
        stream.seek(low)
        body = stream.read(high - low)
    base = MappedProducts(body, library, states)
    mutations = [
        ('operand_bit_swap', body.replace(b'operand_a[0]', b'operand_a[1]'), library,
         'Signed product truth vector differs'),
        ('foreign_lane_input', body.replace(b'operand_a[0]', b'operand_a[8]'), library,
         'Foreign lane or state input'),
    ]
    carry = ('FA1D1BWP12T40P140', 'CO')
    assert carry in library
    wrong_library = library | {carry: library[carry] | {'function': '0'}}
    mutations.append(('full_adder_carry_corruption', body, wrong_library, 'Signed product truth vector differs'))
    reg = next(match for match in CELL.finditer(body)
               if match[2].removeprefix(b'\\') == b'product[0].value_reg[0]')
    fragment = reg[0].replace(b'.CP(clk)', b'.CP(p1)')
    assert fragment != reg[0]
    mutations.append(('product_clock_swap', body[:reg.start()] + fragment + body[reg.end():],
                      library, 'Product register clock differs'))
    data = base.products[0, 0]['D']
    driver = next(match for match in CELL.finditer(body) if bindings(match[3], base.declared).get('Z') == data)
    feedback = next(pin for pin in PIN.finditer(driver[3]) if pin[1] == b'B2')
    assert bindings(driver[3], base.declared)['B2'] == base.products[0, 0]['Q']
    first, last = driver.start(3) + feedback.start(2), driver.start(3) + feedback.end(2)
    mutations.append(('removed_stall_feedback', body[:first] + b"1'b0" + body[last:],
                      library, 'Stalled product does not hold'))
    mutations.extend([
        ('unparsed_assignment', body.replace(b'endmodule', b'assign operand_a[0]=operand_a[1];\nendmodule'),
         library, 'Unsupported mapped module text'),
        ('escaped_operand_alias', body.replace(b'operand_a[0]', b'\\operand_a[0] '),
         library, 'Undeclared mapped net'),
        ('escaped_product_alias', body.replace(b'\\product[0].value [0]', b'\\product[0].value[0] '),
         library, 'Undeclared mapped net'),
        ('declared_alias_collision', body.replace(b'endmodule', b'wire \\operand_a[0] ;\nendmodule'),
         library, 'Ambiguous declared net'),
    ])
    ff = ('DFQD2BWP12T40P140', '__product_ff__')
    wrong_state = library | {ff: library[ff] | {'next_state': '!D'}}
    mutations.append(('changed_flip_flop_transition', body, wrong_state,
                      'Product register sequential semantics differ'))
    rejected = []
    for label, changed, models, message in mutations:
        try:
            MappedProducts(changed, models, states).prove()
        except (AssertionError, ValueError) as error:
            assert message in str(error), (label, 'Unexpected rejection', str(error))
            rejected.append(label)
            print('PACKAGED_PRODUCT_MUTATION_REJECTED', label, flush=True)
        else:
            raise AssertionError(('Arithmetic checker accepted corruption', label))
    result = {'state': 'packaged_product_negative_controls_verified', 'array_module': name,
              'candidate_sha256': structure['candidate_sha256'], 'rejected_mutations': rejected,
              'evidence_sha256': evidence}
    (WORK / 'product_controls.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    return result


def verify(negative_controls=False):
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context
    assert __debug__ and Path.cwd() == ROOT and not Path('/.dockerenv').exists()
    started = time.monotonic()
    ranges, library, states, evidence, structure = inputs()
    if negative_controls:
        return controls(ranges, library, states, evidence, structure)
    control_path = WORK / 'product_controls.json'
    control_result = json.loads(control_path.read_text())
    assert control_result['state'] == 'packaged_product_negative_controls_verified'
    assert control_result['candidate_sha256'] == structure['candidate_sha256']
    assert control_result['evidence_sha256'] == evidence, 'Negative controls have stale inputs'
    assert set(control_result['rejected_mutations']) == {
        'operand_bit_swap', 'foreign_lane_input', 'full_adder_carry_corruption',
        'product_clock_swap', 'removed_stall_feedback', 'unparsed_assignment',
        'escaped_operand_alias', 'escaped_product_alias', 'declared_alias_collision',
        'changed_flip_flop_transition'}
    tasks = [(name, bounds, library, states) for name, bounds in ranges.items()]
    with ProcessPoolExecutor(max_workers=4, mp_context=get_context('spawn')) as pool:
        arrays = dict(pool.map(inspect_range, tasks))
    memory_guard()
    with CANDIDATE.open('rb') as stream:
        assert file_digest(stream, 'sha256').hexdigest() == structure['candidate_sha256']
    with control_path.open('rb') as stream:
        evidence[str(control_path.relative_to(ROOT))] = file_digest(stream, 'sha256').hexdigest()
    result = {'state': 'packaged_signed_product_next_states_exhaustively_verified',
              'candidate_sha256': structure['candidate_sha256'], 'arrays': arrays,
              'array_instances': len(arrays), 'registered_products': 20 * 256,
              'operand_pairs_per_lane': 65536, 'control_cases_per_product_bit': 8,
              'operand_pair_lane_checks': 20 * 256 * 65536,
              'wall_seconds': time.monotonic() - started, 'evidence_sha256': evidence,
              'complete_paper_architecture_verified': False,
              'advance_to_clock_distribution_or_routing_allowed': False,
              'scope': 'Exact two-state product-register next-state proof for all twenty reachable '
                       'mapped arrays in the candidate. Every product cone is isolated from foreign '
                       'lanes and state bits. All 65536 signed eight-bit operand pairs match integer '
                       'multiplication. The three accepting handshake cases write identical arithmetic, '
                       'disabled lanes write zero, and all five non-accepting cases preserve arbitrary '
                       'prior register bits. Original Liberty Boolean functions agree across all three '
                       'corners. This proof abstracts clock transitions and known Boolean state; it does '
                       'not prove four-state behavior, the reduction tree, valid-pipeline progression, '
                       'whole-model execution, accuracy, electrical timing, placement or routing.'}
    (WORK / 'verified_products.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print('PACKAGED_PRODUCT_NEXT_STATES_VERIFIED', result['registered_products'],
          result['operand_pair_lane_checks'], flush=True)
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controls', action='store_true')
    verify(parser.parse_args().controls)
