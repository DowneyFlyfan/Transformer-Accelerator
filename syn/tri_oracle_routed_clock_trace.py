"""Read-only primitive tracing of scalar clocks in a native flat core export.

This is a diagnostic, not permission to rewrite clocks. It does not prove
clock-only fanout or state/data equivalence. Vendor models are preprocessed
with the same default definitions as the failing functional simulation.
"""
from pathlib import Path
import collections
import hashlib
import json
import subprocess
import tempfile

from tri_oracle_ideal_clock import _INSTANCE, _MODULE, _connections, _mask
from tri_oracle_library_mode import _library, _graph

MEMORY_CLOCKS = {
    'TS5N28HPCPSVTA32X128M2FW': ('CLK',),
    'TS5N28HPCPSVTA512X64M4F': ('CLK',),
    'TS6N28HPCPSVTA16X128M2F': ('CLKW', 'CLKR'),
}


def trace_clocks(netlist, library):
    source = Path(netlist).read_text()
    definitions = list(_MODULE.finditer(_mask(source)))
    if len(definitions) != 1:
        raise ValueError('Expected exactly one native flat module')
    module = definitions[0]
    with tempfile.TemporaryDirectory(prefix='sram_clock_library_', dir='.cache') as directory:
        preprocessed = Path(directory)/'library.v'
        subprocess.run(['iverilog', '-E', '-o', str(preprocessed), str(library)],
                       check=True, timeout=30)
        models, primitives, _ = _library(preprocessed.read_text())
    instances = []
    counts = collections.Counter()
    for instance in _INSTANCE.finditer(module[2]):
        connections = _connections(instance, module.start(2))
        instances.append((instance[1], instance[2].lstrip('\\'), connections))
        counts[instance[1]] += 1
    transparent = {}
    sequential = set()
    for kind in counts:
        if kind in MEMORY_CLOCKS:
            continue
        if kind not in models:
            raise ValueError('Unknown native leaf model: ' + kind)
        graph = _graph(models[kind], primitives)
        if graph['state_count']:
            sequential.add(kind)
        interface = dict(graph['signature'][0])
        inputs = {n for n, directions in interface.items() if 'input' in directions}
        outputs = {n for n, directions in interface.items() if 'output' in directions}
        if len(inputs) == len(outputs) == 1 and len(graph['components']) == 1:
            operation, _, ports = graph['components'][0]
            if operation in {'buf', 'not'} and ports == (next(iter(outputs)), next(iter(inputs))):
                transparent[kind] = (operation, ports[0], ports[1])
    drivers = {}
    clock_pins = []
    for kind, name, connections in instances:
        if kind in transparent:
            operation, output, input_pin = transparent[kind]
            net = connections[output][0].strip()
            if net in drivers:
                raise ValueError('Multiple transparent drivers: ' + net)
            drivers[net] = (operation, connections[input_pin][0].strip(), kind, name)
        if kind in sequential:
            if 'CP' not in connections:
                raise ValueError('Unclassified sequential clock: ' + kind)
            clock_pins.append((name, 'CP', connections['CP'][0].strip()))
        for pin in MEMORY_CLOCKS.get(kind, ()):
            clock_pins.append((name, pin, connections[pin][0].strip()))

    def trace(net):
        seen = set()
        path = []
        while net != 'clk':
            if net in seen:
                return {'error': 'cycle', 'net': net}
            seen.add(net)
            if net not in drivers:
                return {'error': 'nontransparent_clock_driver', 'net': net}
            operation, parent, kind, name = drivers[net]
            path.append((operation, kind, name, net))
            net = parent
        return {'depth': len(path), 'inversions': sum(x[0] == 'not' for x in path), 'path': path}

    paths = [{'instance': name, 'port': pin, 'net': net, **trace(net)}
             for name, pin, net in clock_pins]
    return {
        'netlist_sha256': hashlib.sha256(source.encode()).hexdigest(),
        'library_sha256': hashlib.sha256(Path(library).read_bytes()).hexdigest(),
        'instance_count': len(instances), 'clock_pin_count': len(paths), 'paths': paths,
        'depth_counts': dict(collections.Counter(x.get('depth', 'error') for x in paths)),
        'inversion_counts': dict(collections.Counter(x.get('inversions', 'error') for x in paths)),
        'scope': __doc__,
    }


if __name__ == '__main__':
    result = trace_clocks(
        '.cache/physical/pnr/tri_oracle_sram_memory_compute/qualification_si_opt_06/routed_netlist.v',
        '.cache/physical/library/tcbn28hpcplusbwp12t40p140.v')
    output = Path('.cache/physical/sram_core_raw_clock_tree_diagnosis.json')
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'paths'}, indent=2))
    for item in result['paths']:
        if item['instance'].startswith('outputs') or 'error' in item:
            print({k: v for k, v in item.items() if k != 'path'})
