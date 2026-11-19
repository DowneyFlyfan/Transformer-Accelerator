"""Strict raw groups for scalar-cell comparison, including escaped newlines."""
import re

def resize_direct_groups(text):
    """Find real direct groups while consuming comments and quoted strings."""
    quoted = '"(?:\\\\.|[^"\\\\])*"'
    pattern = re.compile(quoted + '|/\\*[\\s\\S]*?\\*/|//[^\\n]*|/\\*|"|(?P<kind>\\b[A-Za-z_]\\w*)\\s*\\((?P<arguments>(?:' + quoted + '|[^()"])*?)\\)\\s*\\{|[{}]', flags=re.DOTALL)
    groups = []
    depth = 0
    current = None
    for token in pattern.finditer(text):
        raw = token[0]
        assert raw != '/*', 'Unclosed Liberty comment'
        assert raw != '"', 'Unclosed Liberty quoted string'
        if raw.startswith(('"', '/*', '//')):
            continue
        if token['kind'] is not None:
            if depth == 0:
                arguments = token['arguments'].strip()
                if re.fullmatch(quoted, arguments):
                    arguments = arguments[1:-1]
                current = (token['kind'], arguments, token.end())
            depth += 1
        elif raw == '{':
            assert depth > 0, 'Input memory declaration group header differs'
            depth += 1
        elif raw == '}':
            depth -= 1
            assert depth >= 0, 'Invalid Liberty group nesting'
            if depth == 0:
                assert current is not None, 'Input memory declaration group differs'
                kind, arguments, opening = current
                groups.append((kind, arguments, text[opening:token.start()]))
                current = None
    assert depth == 0, 'Unclosed Liberty declaration group'
    return groups



def resize_group(text,opening):
    assert opening>0 and text[opening-1]=='{','Expected actual Liberty group opening'
    tokens=re.compile(r'"(?:\\[\s\S]|[^"\\])*"|/\*[\s\S]*?\*/|//[^\n]*|/\*|"|[{}]')
    depth=1
    for token in tokens.finditer(text,opening):
        raw=token[0]
        assert raw not in ('"','/*'),'Unclosed Liberty quoted string or comment'
        if raw=='{':depth+=1
        elif raw=='}':depth-=1
        if depth==0:return text[opening:token.start()]
    raise ValueError('Unclosed Liberty group')
