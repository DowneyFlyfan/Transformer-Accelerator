"""Strict physical-instance census for a mapped structural Verilog candidate.

The caller supplies all recognized library leaves and the memory subset.
This counts instantiated storage, not behavior, connectivity or access timing.
Only non-ANSI mapped headers and named pin associations are supported.
Unsupported structural statements fail in the existing mapped-module reader.
"""
from collections import Counter
from functools import cache
import re

from tri_oracle_mapped_module import IDENTIFIER, pin_fields, read_module


BOUNDARY = re.compile(
    rb'//[^\n]*|/\*[\s\S]*?\*/|(?m:^[ \t]*(?:module[ \t]+(?P<name>[\w$]+)[ \t]*\(|(?P<end>endmodule)\b))')
COMMENT = re.compile(rb'//[^\n]*|/\*[\s\S]*?\*/')


def census(source, top, allowed_leaves, memory_masters, guard=lambda: None):
    """Return leaf multiplicities and every reachable memory instance path."""
    allowed_leaves, memory_masters = set(allowed_leaves), set(memory_masters)
    if not memory_masters <= allowed_leaves:
        raise ValueError('Memory masters must be recognized library leaves')
    definitions, cursor, opening = {}, 0, None
    for match in BOUNDARY.finditer(source):
        if match['name'] is None and match['end'] is None:
            continue
        if match['name'] is not None:
            if opening is not None or COMMENT.sub(b'', source[cursor:match.start()]).strip():
                raise ValueError('Outside or overlapping module statements')
            name = match['name'].decode('ascii')
            if name in definitions:
                raise ValueError('Duplicate module: ' + name)
            opening = name, match.start()
            continue
        if opening is None:
            raise ValueError('Outside module end')
        guard()
        name, start = opening
        # The strict reader checks the complete module body, not only instances.
        header, ports, _, instances, _ = read_module(source[start:match.end()])
        if header[:3] != ('module', name, '(') or header[-1:] != (')',):
            raise ValueError('Unsupported mapped module header: ' + name)
        tokens = header[3:-1]
        if (tokens and len(tokens) % 2 == 0
                or any(token != ',' for token in tokens[1::2])
                or any(re.fullmatch(IDENTIFIER, token) is None for token in tokens[::2])):
            raise ValueError('Expected non-ANSI mapped module header: ' + name)
        port_names = [token.removeprefix('\\') for token in tokens[::2]]
        if len(set(port_names)) != len(port_names) or set(port_names) != set(ports):
            raise ValueError('Header and declared ports differ: ' + name)
        names, rows = set(), []
        for raw_name, (master, fields) in instances.items():
            pins = [pin.removeprefix('\\') for pin in pin_fields(fields)]
            if len(set(pins)) != len(pins):
                raise ValueError('Duplicate canonical pin name: ' + raw_name)
            instance = raw_name.removeprefix('\\')
            if '/' in instance or instance in names:
                raise ValueError('Ambiguous instance path: ' + instance)
            names.add(instance)
            rows.append((instance, master))
        definitions[name] = rows
        cursor = match.end()
        opening = None
    if opening is not None:
        raise ValueError('Unterminated module: ' + opening[0])
    if COMMENT.sub(b'', source[cursor:]).strip():
        raise ValueError('Outside module statements')
    if top not in definitions:
        raise ValueError('Missing top module: ' + top)
    if set(definitions) & allowed_leaves:
        raise ValueError('Module shadows a library leaf')
    active, visited = set(), set()

    @cache
    def leaves(module):
        if module in active:
            raise ValueError('Hierarchy cycle: ' + module)
        active.add(module)
        visited.add(module)
        result = Counter()
        for _, master in definitions[module]:
            if master in definitions:
                result.update(leaves(master))
            elif master in allowed_leaves:
                result[master] += 1
            else:
                raise ValueError('Unknown leaf: ' + master)
        active.remove(module)
        return result

    total = leaves(top)
    memories = {}

    def walk(module, prefix):
        for instance, master in definitions[module]:
            path = prefix + instance
            if master in memory_masters:
                if path in memories:
                    raise ValueError('Duplicate memory path: ' + path)
                memories[path] = master
            elif master in definitions and memory_masters.intersection(leaves(master)):
                walk(master, path + '/')

    walk(top, '')
    if Counter(memories.values()) != {master: count for master, count in total.items() if master in memory_masters}:
        raise ValueError('Memory hierarchy and leaf census disagree')
    return {'leaves': dict(total), 'memory': memories, 'module_count': len(definitions),
            'reachable_module_count': len(visited),
            'unreachable_modules': sorted(set(definitions) - visited)}


def compare_physical(logical, leaf_counts, fixed_memories):
    """Require all fixed memory identities and complete leaf counts to agree."""
    if logical['memory'] != fixed_memories:
        raise ValueError('Physical memory identities or masters differ')
    if logical['leaves'] != dict(leaf_counts):
        raise ValueError('Physical leaf multiplicities differ')
