"""Validate only the imported controller interface in a hierarchical netlist."""
import re
from pathlib import Path

from tri_oracle_checked_controller_adapters138 import declarations
from tri_oracle_named_controller_adapters137 import controller_adapter


def module_body(text, name):
    assert re.fullmatch(r'[A-Za-z_][A-Za-z_0-9$]*', name)
    starts = list(re.finditer(r'^\s*module\s+'+re.escape(name)+r'\s*\(', text, re.M))
    assert len(starts) == 1, 'Expected exactly one controller module'
    rest = text[starts[0].start():]
    end = re.search(r'^\s*endmodule\b', rest, re.M)
    assert end, 'Controller module is incomplete'
    body = rest[:end.end()]
    assert len(re.findall(r'^\s*module\b', body, re.M)) == 1
    return body


def renamed_controller_netlist(path, original_module, imported_module):
    assert original_module != imported_module, 'Adapter would recursively instantiate itself'
    assert re.fullmatch(r'[A-Za-z_][A-Za-z_0-9$]*', imported_module)
    text = Path(path).read_text()
    module_body(text, original_module)
    assert not re.search(r'^\s*module\s+'+re.escape(imported_module)+r'\b', text, re.M)
    pattern = r'(^\s*module\s+)'+re.escape(original_module)+r'(\s*\()'
    renamed, count = re.subn(pattern, lambda match: match[1]+imported_module+match[2], text, flags=re.M)
    assert count == 1
    return renamed


def checked_hierarchical_controller_adapter(original_path, imported_netlist, imported_module):
    assert Path(original_path).stem != imported_module, 'Adapter would recursively instantiate itself'
    adapter, ports = controller_adapter(original_path, imported_netlist, imported_module)
    first = adapter.index('(')
    last = adapter.index('\n);', first)
    expected = declarations(adapter[first+1:last])
    body = module_body(Path(imported_netlist).read_text(), imported_module)
    actual = {}
    for match in re.finditer(r'^\s*(input|output|inout)\s+([^;]+);', body, re.M):
        for name, shape in declarations(match[1]+' '+match[2]).items():
            assert name not in actual, 'Duplicate imported controller port'
            actual[name] = shape
    assert actual == expected, 'Controller interface direction/width mismatch'
    assert set(ports) == set(expected)
    return adapter, expected
