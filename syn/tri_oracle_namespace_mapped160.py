"""Privately name every module in a Genus mapped netlist; retain cell masters."""
import re


IDENTIFIER = r'[A-Za-z_][A-Za-z_0-9$]*'


def masked_code(text):
    ignored = r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"'
    return re.sub(ignored, lambda match: ''.join('\n' if char == '\n' else ' ' for char in match[0]), text, flags=re.S)


def namespace_mapped_netlist(text, original_top, imported_top, prefix):
    assert all(re.fullmatch(IDENTIFIER, value) for value in [original_top, imported_top, prefix])
    code = masked_code(text)
    headers = list(re.finditer(r'^\s*module\s+('+IDENTIFIER+r')\s*\(', code, re.M))
    ends = list(re.finditer(r'^\s*endmodule\b', code, re.M))
    assert headers and len(headers) == len(ends), 'Incomplete or unsupported mapped module declaration'
    assert len(re.findall(r'^\s*module\b', code, re.M)) == len(headers)
    names = [match[1] for match in headers]
    assert len(set(names)) == len(names) and original_top in names
    assert not any(name.endswith('BWP12T40P140') for name in names), 'Embedded library-cell definitions are unsupported'
    for index, (header, end) in enumerate(zip(headers, ends)):
        assert header.end() < end.start()
        if index+1 < len(headers):
            assert end.end() <= headers[index+1].start(), 'Nested mapped module declaration'
    aliases = {name: imported_top if name == original_top else prefix+name for name in names}
    assert len(set(aliases.values())) == len(aliases), 'Imported module aliases collide'
    assert not set(aliases.values()) & set(names), 'Imported aliases overlap original module names'
    replacements = [(match.start(1), match.end(1), aliases[match[1]]) for match in headers]
    instance = r'^[ \t]*('+IDENTIFIER+r')\s+(?:\\[^\s]+|'+IDENTIFIER+r')\s*\('
    for match in re.finditer(instance, code, re.M):
        if match[1] in aliases:
            replacements.append((match.start(1), match.end(1), aliases[match[1]]))
    output = text
    for first, last, value in sorted(replacements, reverse=True):
        output = output[:first]+value+output[last:]
    original_identifiers = r'(?<![A-Za-z_0-9$])(?:'+'|'.join(re.escape(name) for name in names)+r')(?![A-Za-z_0-9$])'
    assert not re.search(original_identifiers, masked_code(output)), 'Unclassified original module identifier remains'
    return output, aliases
