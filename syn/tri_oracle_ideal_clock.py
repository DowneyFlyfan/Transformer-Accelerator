"""Idealize a proven single clock domain in a native scalar gate export.

This creates a simulation copy: only verified sequential CP connections change.
All clock buffers, data/reset/enable pins and state-cell models remain intact.
The result adds a binary-clock assertion; it makes no physical timing claim.
"""
import collections
import hashlib
import json
import re

from tri_oracle_library_mode import IDENT, _graph, _library


_NAME = rf"(?:\\[^\s]+|{IDENT})"
_MODULE = re.compile(rf"\bmodule\s+({IDENT})\s*\([^;]*\)\s*;(.*?)\bendmodule\b", re.S)
_INSTANCE = re.compile(rf"(?<![\w$\\])({IDENT})\s+({_NAME})\s*\(([^;]*)\)\s*;", re.S)
_PORT = re.compile(rf"\s*\.({_NAME})\s*\(\s*([^()]*)\)\s*(?:,|$)", re.S)
_DECL = re.compile(r"\b(input|output|inout|wire|tri|tri0|tri1|wand|wor|reg|logic)\s+([^;]+);", re.S)
_MULTIPLE = object()


def _mask(source):
    return re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"',
                  lambda m: re.sub(r"[^\n]", " ", m[0]), source, flags=re.S)


def _net(expression):
    """Keep escaped identifiers distinct from ordinary packed-bit selections."""
    match = re.fullmatch(rf"\s*({_NAME})(?:\s*\[\s*(\d+)\s*\])?\s*", expression)
    if not match:
        return None
    return match[1].lstrip("\\"), int(match[2]) if match[2] is not None else None


def _connections(match, offset):
    result = {}
    position = 0
    while position < len(match[3]):
        port = _PORT.match(match[3], position)
        if not port or port[1].lstrip("\\") in result:
            raise ValueError("Unsupported or duplicate native instance port")
        result[port[1].lstrip("\\")] = (
            port[2], offset+match.start(3)+port.start(2), offset+match.start(3)+port.end(2))
        position = port.end()
    return result


def rewrite_clocks(source, library, counts, top, root_reference):
    if not re.fullmatch(rf"{IDENT}(?:\.{IDENT})+\.clk", root_reference):
        raise ValueError("Invalid hierarchical root clock reference")
    text = _mask(source)
    if re.search(r"\b(?:always|initial|force|release|generate|assign|tran|tranif0|tranif1)\b", text):
        raise ValueError("Unsupported behavioral or alternate-driver input")
    definitions = list(_MODULE.finditer(text))
    modules = {match[1]: match for match in definitions}
    if len(modules) != len(definitions) or top not in modules:
        raise ValueError("Missing or duplicate native module")
    if _MODULE.sub(" ", text).strip():
        raise ValueError("Unconsumed global statement or primitive")
    models, primitives, _ = _library(library)
    info = {}
    for kind in counts:
        graph = _graph(models[kind], primitives)
        interface = dict(graph["signature"][0])
        inputs = {name for name, directions in interface.items() if "input" in directions}
        outputs = {name for name, directions in interface.items() if "output" in directions}
        buffer = None
        if len(inputs) == len(outputs) == 1 and len(graph["components"]) == 1:
            component = graph["components"][0]
            if component[0] == "buf" and component[2] == (next(iter(outputs)), next(iter(inputs))):
                buffer = component[2]
        clock = None
        if graph["state_count"]:
            if "CP" not in inputs:
                raise ValueError("State cell lacks a verified CP clock pin: "+kind)
            for component in graph["components"]:
                positions = [i for i, name in enumerate(component[2]) if name == "CP"]
                if not positions:
                    continue
                primitive = primitives.get(component[0])
                header = re.match(r"primitive\s+\w+\s*\(([^)]*)\)", primitive[0]) if primitive else None
                ports = [p.strip().lower() for p in header[1].split(",")] if header else []
                if not primitive or not primitive[2] or ports.count("cp") != 1 or positions != [ports.index("cp")]:
                    raise ValueError("CP has an unverified non-clock use in model: "+kind)
            state = [c for c in graph["components"] if c[0] in primitives and primitives[c[0]][2]]
            if any("CP" not in c[2] for c in state):
                raise ValueError("State primitive is outside the root clock domain")
            clock = "CP"
        info[kind] = (inputs, outputs, buffer, clock, not graph["components"] and not outputs)

    declarations = {}
    scalar_ports = {}
    calls = {}
    observed = collections.Counter()
    parents = {}
    drivers = {}
    adjacency = collections.defaultdict(list)
    clock_pins = []

    def node(module, expression):
        value = _net(expression)
        if value is not None and value[1] == 0 and declarations.get(module, {}).get(value[0]) == ("wire", False):
            value = (value[0], None)
        return (module, *value) if value is not None else None

    def drive(destination, origin=None, buffer=False):
        if destination is None:
            return
        edge = (origin, buffer)
        drivers[destination] = _MULTIPLE if destination in drivers else edge
        if origin is not None:
            adjacency[origin].append((destination, edge))

    # Native module definitions are unique after the physical export. Resolve
    # their actual input/output port links, rather than trusting clock names.
    for name, module in modules.items():
        ports = {}
        declared = {}
        for declaration in _DECL.finditer(module[2]):
            kind, body = declaration.groups()
            vector = bool(re.match(r"\s*\[", body))
            body = re.sub(r"^\s*\[[^]]*\]\s*", "", body)
            for item in body.split(","):
                value = _net(item)
                if value is None or value[1] is not None:
                    raise ValueError("Unsupported native net declaration")
                net = value[0]
                if kind in {"input", "output", "inout"}:
                    if not vector:
                        ports[net] = kind
                    declared.setdefault(net, ("wire" if kind != "inout" else "inout", vector))
                else:
                    declared[net] = (kind, vector)
        declarations[name] = declared
        scalar_ports[name] = ports
        if _DECL.sub(" ", _INSTANCE.sub(" ", module[2])).strip():
            raise ValueError("Unconsumed native statement or unnamed primitive")
        calls[name] = []
        for instance in _INSTANCE.finditer(module[2]):
            kind, instance_name = instance[1], instance[2]
            connections = _connections(instance, module.start(2))
            if kind not in info and kind not in modules:
                raise ValueError("Unknown native instance type: "+kind)
            if kind in modules:
                calls[name].append((kind, instance_name, connections))
                if kind in parents:
                    raise ValueError("Native module definitions must have unique instances")
                parents[kind] = name
                continue
            observed[kind] += 1
            inputs, outputs, buffer, clock, passive = info[kind]
            if set(connections) != inputs | outputs:
                raise ValueError("Native cell connection inventory differs from its interface")
            for pin, (expression, start, end) in connections.items():
                if expression.strip() and _net(expression) is None:
                    if pin in outputs or not re.fullmatch(r"\s*1'[bB][01xXzZ]\s*", expression):
                        raise ValueError("Potential non-clock load or unsupported complex leaf connection")
            for output in outputs:
                destination = node(name, connections[output][0])
                origin = node(name, connections[buffer[1]][0]) if buffer else None
                drive(destination, origin, buffer is not None)
            if clock:
                clock_pins.append((name, instance_name, connections[clock]))
    if observed != counts:
        raise ValueError("Native cell inventory differs from the independent audit")
    if top in parents or set(parents) != set(modules)-{top}:
        raise ValueError("Native module hierarchy must be unique, reachable, and complete")
    for module in modules:
        seen = set()
        current = module
        while current != top:
            if current in seen or current not in parents:
                raise ValueError("Native hierarchy is not uniquely rooted")
            seen.add(current)
            current = parents[current]
    for parent, instances in calls.items():
        for kind, instance, connections in instances:
            if kind not in modules:
                continue
            for port, direction in scalar_ports[kind].items():
                if port not in connections:
                    # An omitted, unused port is unconnected, not an extra
                    # driver. Any sequential CP depending on it still fails
                    # root reachability below.
                    continue
                local = (kind, port, None)
                external = node(parent, connections[port][0])
                if direction == "input":
                    drive(local, external)
                elif direction == "output":
                    drive(external, local)

    root = (top, "clk", None)
    if scalar_ports[top].get("clk") != "input" or root in drivers:
        raise ValueError("The root clock must be one externally driven scalar input")
    rooted = {root: 0}
    queue = collections.deque([root])
    while queue:
        origin = queue.popleft()
        for destination, edge in adjacency.get(origin, ()):
            if drivers[destination] is _MULTIPLE:
                raise ValueError("Clock net has multiple drivers: "+str(destination))
            if destination not in rooted:
                rooted[destination] = rooted[origin]+int(edge[1])
                queue.append(destination)
    for module, name, bit in rooted:
        if bit is not None or declarations[module].get(name) != ("wire", False):
            raise ValueError("Clock cone must contain explicitly declared scalar wire nets")
    if any((top, name, None) in rooted for name in scalar_ports[top] if name != "clk"):
        raise ValueError("Clock cone reaches another top-level port/external driver")
    for parent, instances in calls.items():
        for kind, instance, connections in instances:
            for port, (expression, start, end) in connections.items():
                direction = scalar_ports[kind].get(port)
                if direction in {"input", "output"} and _net(expression) is not None:
                    continue
                # Unresolved/vector/inout/complex port links must not conceal
                # root-clock uses. Native data-bus connections remain intact.
                expression = re.sub(r"\b\d+'[bBoOdDhH][0-9a-fA-F_xXzZ]+", " ", expression)
                references = re.finditer(rf"({_NAME})(?:\s*\[[^]]*\])?", expression)
                if any(node(parent, reference[0]) in rooted or
                       node(parent, reference[1]) in rooted for reference in references):
                    raise ValueError("Clock cone has a non-clock load at unresolved hierarchical port: "+parent+"/"+instance+"/"+port)
    # Reparse leaf loads instead of retaining hundreds of thousands of port
    # dictionaries while building the clock graph.
    for module, definition in modules.items():
        for call in _INSTANCE.finditer(definition[2]):
            kind, instance = call[1], call[2]
            if kind not in info:
                continue
            connections = _connections(call, definition.start(2))
            inputs, outputs, buffer, clock, passive = info[kind]
            for pin in inputs:
                if node(module, connections[pin][0]) in rooted:
                    if pin == clock or (buffer and pin == buffer[1]) or passive:
                        continue
                    raise ValueError("Clock cone has a non-clock load: "+module+"/"+instance+"/"+pin)
    if any((top, name, None) in rooted for name, direction in scalar_ports[top].items() if direction != "input"):
        raise ValueError("Clock cone escapes through a top-level non-clock output")
    if not clock_pins:
        raise ValueError("No verified sequential root clock pins")
    edits = []
    per_module = collections.Counter()
    changes = hashlib.sha256()
    for module, instance, (expression, start, end) in clock_pins:
        if node(module, expression) not in rooted:
            raise ValueError("Sequential CP is outside the noninverting root clock tree")
        edits.append((start, end, root_reference))
        per_module[module] += 1
        changes.update(json.dumps([module, instance, expression, start, end]).encode())
    guard = '''
// Simulation-only clock-domain contract; original data and state logic retained.
initial begin
 #0;
 if (clk !== 1'b0 && clk !== 1'b1) $fatal(1,"IDEAL_CLOCK_NONBINARY");
end
always @(clk)
 if (clk !== 1'b0 && clk !== 1'b1) $fatal(1,"IDEAL_CLOCK_NONBINARY");
'''
    edits.append((modules[top].end(2), modules[top].end(2), guard))
    chunks = []
    cursor = 0
    for start, end, replacement in sorted(edits):
        if start < cursor:
            raise ValueError("Overlapping clock rewrite edits")
        chunks.extend((source[cursor:start], replacement))
        cursor = end
    chunks.append(source[cursor:])
    derived = "".join(chunks)
    return derived, {
        "scope": "Ideal-root-clock functional simulation copy; no physical timing or arbitrary four-state equivalence claim",
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "derived_sha256": hashlib.sha256(derived.encode()).hexdigest(),
        "rewritten_clock_pins": len(clock_pins), "rewritten_pins_by_module": dict(per_module),
        "clock_connection_map_sha256": changes.hexdigest(),
        "root_reference": root_reference, "maximum_clock_buffer_depth": max(rooted.values()),
        "verified_rooted_clock_nets": len(rooted), "cell_inventory_preserved": dict(observed),
        "single_driver_and_clock_only_fanout_proven": True,
        "all_data_reset_enable_connections_and_cell_models_preserved": True,
        "binary_clock_guard_added": True, "physical_database_changed": False,
    }
