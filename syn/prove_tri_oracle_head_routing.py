"""Trace actual mapped head buses with explicit compositional port cutpoints."""
from collections import defaultdict
import re

from prove_tri_oracle_parent_reset import ResetHierarchy
from prove_tri_oracle_head_ratio_sequence import equal_functions
from link_tri_oracle_indexed_whole_chip import signature
from prove_tri_oracle_parent_clock import read_clock_library

REQUEST_FIELDS = {'cfg_ratio_num': (307, 8), 'cfg_ratio_den': (299, 8), 'cfg_alpha': (328, 32)}
RESPONSE_FIELDS = [('cfg_ready', None, 72), ('in_ready', None, 71), ('out_valid', None, 70),
                   ('out_error', None, 69), ('out_streaming', None, 68)]
RESPONSE_FIELDS += [(name, bit, start+bit) for name, start in [('out_inner',18), ('out_outer',0)] for bit in range(18)]


def routing_libraries(sources, masters):
    """Load the standard cells and all six compiled memories at three corners."""
    assert len(sources)==3,'Expected three route library corners'
    tables={}
    for corner,paths in sources.items():
        assert len(paths)==len(set(paths))==7,'Expected seven distinct library views per corner'
        table={};declared=set()
        for path in paths:
            names={name.strip() for name in re.findall(r'(?m)^cell\s*\(([^)]+)\)\s*\{',path.read_text())}
            assert not declared & names,'Duplicate declared route library cell'
            declared.update(names)
            rows=read_clock_library(path,masters)
            assert not table.keys() & rows.keys(),'Duplicate route library pin'
            table.update({key:{name:value for name,value in properties.items() if name in ('direction','function')}
                          for key,properties in rows.items()})
        # Fillers, boundary and decoupling cells legitimately have no signal
        # pins. Require their declarations, rather than inventing pin entries.
        assert masters<=declared,'Missing route library master declaration'
        tables[corner]=table
    first=next(iter(tables.values()))
    assert all(table==first for table in tables.values()),'Route Boolean functions differ across corners'
    return tables


class HeadRoutes(ResetHierarchy):
    """Cut only declared scheduler outputs and independently qualified head outputs.

    The caller separately qualifies those component contracts on the exact same
    module bodies. Every connection between the cutpoints is traced normally.
    """
    def __init__(self, body, masters, library, states, top, scheduler, heads, *, guard=lambda: None):
        super().__init__(body, masters, library, states, guard=guard)
        self.contexts[''] = top, None, None
        self.driver_indexes = {}
        self.port_signatures = {}

        def context(path):
            current = ''
            for instance in path.split('/'):
                if instance:
                    current = self.child(current, instance)
            return current

        self.scheduler = context(scheduler)
        self.heads = {owner: context(path) for owner, path in heads.items()}
        assert len(set(self.heads.values())) == len(heads), 'Repeated head route'
        self.owners = {path: owner for owner, path in self.heads.items()}
        scheduler_module = self.module(self.contexts[self.scheduler][0])
        assert scheduler_module.directions.get('head_request') == 'output', 'Scheduler request cut is not an output'
        assert scheduler_module.directions.get('head_response') == 'input', 'Scheduler response is not an input'
        self.request_bits = set(scheduler_module.net_bits('head_request'))
        self.response_outputs = {name for name, _, _ in RESPONSE_FIELDS}
        for path in self.heads.values():
            module = self.module(self.contexts[path][0])
            for name in self.response_outputs & module.directions.keys():
                assert module.directions[name] == 'output', 'Head response cut is not an output'

    def direction(self, master, pin):
        if master in self.masters and master not in self.modules:
            # Only port declarations are needed to distinguish an unrelated
            # consumer from a driver. If tracing enters an output, the normal
            # trace path still parses and validates that child's complete body.
            if master not in self.port_signatures:
                self.port_signatures[master] = signature(self.body(master))
            return self.port_signatures[master][pin][0].decode()
        return super().direction(master,pin)

    def drivers(self, context, net):
        module = self.module(self.contexts[context][0])
        stem = net if net in module.declared else net.rsplit('[',1)[0]
        assert stem in module.declared, 'Undeclared route net'
        key = context, stem
        if key not in self.driver_indexes:
            wanted = set(module.net_bits(stem))
            indexed = defaultdict(list)
            for left, right in module.assignments.items():
                if left in wanted:
                    indexed[left].append(('assign', right))
            for instance, (master, pins) in module.cells.items():
                for pin, value in pins.items():
                    if stem not in value:
                        continue
                    bits = module.expression(value)
                    selected = [(offset, bit) for offset, bit in enumerate(bits) if bit in wanted]
                    if not selected:
                        continue
                    direction = self.direction(master, pin)
                    if direction == 'output':
                        for offset, bit in selected:
                            indexed[bit].append(('cell', instance, master, pin, offset, len(bits), pins))
                    else:
                        assert direction == 'input', 'Unsupported route pin direction'
            self.driver_indexes[key] = indexed
        return self.driver_indexes[key].get(net, [])

    def trace(self, context, net):
        if context == self.scheduler and net in self.request_bits:
            return self.graph.variable('scheduler.'+net)
        if context in self.owners:
            module = self.module(self.contexts[context][0])
            for name in self.response_outputs & module.directions.keys():
                if net in module.net_bits(name):
                    return self.graph.variable(f'head{self.owners[context]}.{net}')
        return super().trace(context, net)


def prove_routes(checker):
    assert set(checker.heads) == set(range(20)), 'Expected twenty owner routes'
    graph = checker.graph
    scheduler = checker.module(checker.contexts[checker.scheduler][0])
    assert scheduler.declared['head_request'] == (399,0) and scheduler.declared['head_response'] == (72,0), 'Scheduler bus dimensions differ'
    inputs, controls, responses = [], [], []
    controls_expected = []
    heads = []
    for owner, path in sorted(checker.heads.items()):
        checker.guard()
        module = checker.module(checker.contexts[path][0])
        numeric, expected = [], []
        for name, (start,width) in REQUEST_FIELDS.items():
            assert module.directions[name] == 'input' and module.declared[name] == (width-1,0), 'Numerical head input dimensions differ'
            for bit in range(width):
                numeric.append(checker.trace(path, f'{name}[{bit}]'))
                expected.append(graph.variable(f'scheduler.head_request[{start+bit}]'))
        equal_functions(graph, numeric, expected)
        inputs.extend(numeric)
        selected = 1
        for bit in range(5):
            value = graph.variable(f'scheduler.head_request[{395+bit}]')
            selected = graph.operation('&', selected, value if (owner>>bit)&1 else graph.operation('!',value))
        for name, request_bit in [('cfg_valid',394), ('in_valid',393), ('out_ready',392)]:
            assert module.directions[name] == 'input' and module.declared[name] is None, 'Head control input differs'
            controls.append(checker.trace(path,name))
            controls_expected.append(graph.operation('&', selected, graph.variable(f'scheduler.head_request[{request_bit}]')))
        heads.append(dict(owner=owner,path=path,module=checker.contexts[path][0],module_sha256=module.sha256))
    equal_functions(graph, controls, controls_expected)
    response_roots = [checker.trace(checker.scheduler,f'head_response[{bit}]') for _,_,bit in RESPONSE_FIELDS]
    for owner in range(20):
        assignment = {f'scheduler.head_request[{395+bit}]': (owner>>bit)&1 for bit in range(5)}
        actual = graph.substitute(response_roots, assignment)
        expected = [graph.variable(f'head{owner}.{name}' + (f'[{bit}]' if bit is not None else '')) for name,bit,_ in RESPONSE_FIELDS]
        equal_functions(graph, actual, expected)
        responses.extend(actual)
    integer_cases = 0
    for owner in range(32):
        for flags in range(8):
            assignment = {f'scheduler.head_request[{395+bit}]': (owner>>bit)&1 for bit in range(5)}
            assignment.update({f'scheduler.head_request[{request_bit}]': (flags>>index)&1 for index,request_bit in enumerate([394,393,392])})
            actual = graph.evaluate(controls, assignment)
            expected = [int(owner==head)*((flags>>index)&1) for head in range(20) for index in range(3)]
            assert actual == expected, 'Integer owner-gated control check differs'
            integer_cases += 1
    clock_roots, reset_roots = [], []
    for path in [checker.scheduler, *checker.heads.values()]:
        module = checker.module(checker.contexts[path][0])
        for name in ('clk','rst_n'):
            assert module.directions[name] == 'input' and module.declared[name] is None, 'Clock/reset route port differs'
        clock_roots.append(checker.trace(path,'clk'))
        reset_roots.append(checker.trace(path,'rst_n'))
    equal_functions(graph,clock_roots,[graph.variable('top.clk')]*21)
    equal_functions(graph,reset_roots,[graph.variable('top.rst_n')]*21)
    return dict(heads=heads,numerical_input_bits=len(inputs),owner_gated_control_bits=len(controls),
        selected_response_bits=len(responses),response_fields_per_owner=len(RESPONSE_FIELDS),integer_owner_control_cases=integer_cases,
        common_clock_and_reset_endpoints=21,
        parent_module_sha256={name:module.sha256 for name,module in checker.modules.items()},
        used_library_pins=len(checker.used_library_pins),route_cones=len(checker.cones),
        complete_tag_or_response_stability_verified=False)
