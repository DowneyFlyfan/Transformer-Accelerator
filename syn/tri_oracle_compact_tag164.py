"""Remove only the synthesized-away upper eight bits of the private row tag."""
import hashlib
import re

from tri_oracle_hierarchical_controller_adapter155 import module_body


def cell_signature(text):
    pattern = r'^[ \t]*[A-Za-z_]\w*BWP12T40P140\s+(?:\\[^\s]+|[A-Za-z_][A-Za-z_0-9$]*)\s*\(.*?\);'
    digest = hashlib.sha256()
    count = 0
    for match in re.finditer(pattern, text, re.M | re.S):
        digest.update(match[0].encode())
        count += 1
    assert count >= 1000
    return count, digest.hexdigest()


def without_declarations(body):
    body, count = re.subn(r'^\s*module\b.*?\);', '', body, count=1, flags=re.M | re.S)
    assert count == 1
    return re.sub(r'^\s*(?:input|output|inout|wire)\b[^;]*;', '', body, flags=re.M)


def low_scalar_uses_only(body, name):
    body = without_declarations(body)
    pattern = r'\b'+re.escape(name)+r'\s*\[\s*(\d+)\s*\]'
    indices = {int(match[1]) for match in re.finditer(pattern, body)}
    assert indices == set(range(8)), 'Tag bits outside the implemented eight-bit cone'
    remainder = re.sub(pattern, '', body)
    assert not re.search(r'\b'+re.escape(name)+r'\b', remainder), 'Unsupported aggregate/dynamic tag use'


def shrink_declaration(body, kind, name):
    pattern = r'(^[ \t]*'+kind+r'\s+)\[15:0\]\s+([^;]+);'
    found = 0

    def replace(match):
        nonlocal found
        names = [part.strip() for part in match[2].split(',')]
        if name not in names:
            return match[0]
        assert names.count(name) == 1 and all(re.fullmatch(r'[A-Za-z_]\w*', item) for item in names)
        found += 1
        others = [item for item in names if item != name]
        return (match[1]+'[15:0] '+', '.join(others)+';\n' if others else '')+match[1]+'[7:0] '+name+';'

    body = re.sub(pattern, replace, body, flags=re.M)
    assert found == 1, 'Expected exactly one tag declaration: '+kind+' '+name
    return body


def compact_unused_activation_tags(text, parent_name, child_name):
    parent, child = module_body(text, parent_name), module_body(text, child_name)
    low_scalar_uses_only(child, 'in_tag')
    low_scalar_uses_only(child, 'out_tag')
    instances = list(re.finditer(r'\b'+re.escape(child_name)+r'\s+activation_unit\s*\((.*?)\);', parent, re.S))
    assert len(instances) == 1
    instance = instances[0]
    low_scalar_uses_only(parent[:instance.start()]+parent[instance.end():], 'activation_tag')
    tags = list(re.finditer(r'\.in_tag\s*\(\s*\{(.*?)\}\s*\)', instance[0], re.S))
    assert len(tags) == 1
    terms = [part.strip() for part in tags[0][1].split(',')]
    floating = ['UNCONNECTED_HIER_Z']+['UNCONNECTED_HIER_Z'+str(index) for index in range(7)]
    assert len(terms) > 8 and len(set(terms[:8])) == 8 and set(terms[:8]) == set(floating)
    assert all(len(re.findall(r'\b'+re.escape(name)+r'\b', parent)) == 2 for name in floating), 'Floating tag bit has another consumer'
    width = 0
    for term in terms[8:]:
        match = re.fullmatch(r'[A-Za-z_]\w*(?:\[(\d+)(?::(\d+))?\])?', term)
        assert match, 'Unsupported low tag expression'
        width += abs(int(match[1])-int(match[2]))+1 if match[2] is not None else 1
    assert width == 8
    port = tags[0]
    replacement = instance[0][:port.start()]+'.in_tag ({'+', '.join(terms[8:])+'})'+instance[0][port.end():]
    updated_parent = parent[:instance.start()]+replacement+parent[instance.end():]
    declarations = list(re.finditer(r'^[ \t]*wire\s+([^;]+);', updated_parent, re.M))
    groups = [match for match in declarations if set(part.strip() for part in match[1].split(',')) == set(floating)]
    assert len(groups) == 1
    group = groups[0]
    updated_parent = updated_parent[:group.start()]+updated_parent[group.end():]
    assert not any(re.search(r'\b'+re.escape(name)+r'\b', updated_parent) for name in floating)
    updated_parent = shrink_declaration(updated_parent, 'wire', 'activation_tag')
    updated_child = child
    for kind, name in [('input', 'in_tag'), ('wire', 'in_tag'), ('output', 'out_tag'), ('wire', 'out_tag')]:
        updated_child = shrink_declaration(updated_child, kind, name)
    assert text.count(parent) == text.count(child) == 1
    result = text.replace(parent, updated_parent, 1).replace(child, updated_child, 1)
    before, after = cell_signature(text), cell_signature(result)
    assert before == after, 'Tag compaction changed a mapped cell statement'
    return result, dict(mode='remove_only_unimplemented_upper_tag_interface_bits',
        original_tag_width_bits=16, implemented_tag_width_bits=8, removed_floating_tag_nets=floating,
        mapped_cell_statements=before[0], mapped_cell_statements_sha256=before[1],
        all_mapped_cell_statements_unchanged=True,
        child_input_output_and_parent_tag_uses_exactly_low_eight_bits=True)
