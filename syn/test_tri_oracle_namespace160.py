"""Check private mapped-module names without changing cell masters or ports."""
import hashlib
import json
from pathlib import Path

from tri_oracle_namespace_mapped160 import namespace_mapped_netlist


SOURCE = '''// root_gate and child_gate in this comment remain untouched.
module root_gate(clk,x,z);
input clk,x;
output z;
child_gate lane(.clk(clk),.x(x),.z(z));
endmodule
module child_gate(clk,x,z);
input clk,x;
output z;
XOR2D1BWP12T40P140 cell0(.A1(x),.A2(clk),.Z(z));
endmodule
'''
EXPECTED = '''// root_gate and child_gate in this comment remain untouched.
module private_top(clk,x,z);
input clk,x;
output z;
private_child_gate lane(.clk(clk),.x(x),.z(z));
endmodule
module private_child_gate(clk,x,z);
input clk,x;
output z;
XOR2D1BWP12T40P140 cell0(.A1(x),.A2(clk),.Z(z));
endmodule
'''


def main():
    result = {}
    mapped, names = namespace_mapped_netlist(SOURCE, 'root_gate', 'private_top', 'private_')
    assert mapped == EXPECTED
    assert names == {'root_gate': 'private_top', 'child_gate': 'private_child_gate'}
    result['hierarchical_exact_output'] = 'accepted'
    variants = {
        'duplicate_module': SOURCE+SOURCE,
        'unsupported_parameter_instance': SOURCE.replace('child_gate lane(', 'child_gate #(.W(1)) lane('),
        'unclassified_module_identifier': SOURCE.replace('input clk,x;', 'input clk,x; wire child_gate;', 1),
        'truncated_module': SOURCE.rsplit('endmodule', 1)[0],
    }
    for name, source in variants.items():
        try:
            namespace_mapped_netlist(source, 'root_gate', 'private_top', 'private_')
        except AssertionError:
            result[name] = 'rejected'
        else:
            raise AssertionError(name+' was accepted')
    for name, top, imported, prefix in [('missing_top', 'absent', 'private_top', 'private_'),
                                         ('alias_collision', 'root_gate', 'private_child_gate', 'private_')]:
        try:
            namespace_mapped_netlist(SOURCE, top, imported, prefix)
        except AssertionError:
            result[name] = 'rejected'
        else:
            raise AssertionError(name+' was accepted')
    root = Path(__file__).resolve().parents[1]
    path = root/'records/namespace160_validation.json'
    assert not path.exists()
    files = [Path(__file__).resolve(), root/'syn/tri_oracle_namespace_mapped160.py']
    path.write_text(json.dumps(dict(state='mapped_module_namespace_controls_passed', cases=result,
        source_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
        scope='Module-declaration/type rewriting controls only; native mapped function and parent integration remain pending.'), indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
