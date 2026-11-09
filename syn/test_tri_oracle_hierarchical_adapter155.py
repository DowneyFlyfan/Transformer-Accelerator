"""Check that nested declarations neither alter nor hide controller port errors."""
import hashlib
import json
from pathlib import Path
import re
import tempfile

from tri_oracle_hierarchical_controller_adapter155 import (
    checked_hierarchical_controller_adapter, renamed_controller_netlist,
)


def main():
    root = Path(__file__).resolve().parents[1]
    original = root/'verilog/tri_oracle_down_executor_staged.sv'
    mapped = root/'.cache/physical/synthesis/tri_oracle_down_executor_staged116/netlist.v'
    imported = 'tri_oracle_down_executor_staged_mapped155'
    renamed = renamed_controller_netlist(mapped, original.stem, imported)
    child = '\nmodule adapter155_child(clk);\n  input wire [2:0] clk;\nendmodule\n'
    cases = {}
    with tempfile.TemporaryDirectory(prefix='adapter155_validation_', dir=root/'.cache/physical') as folder:
        fixture = Path(folder)/'mapped.v'

        def check(label, text, accepted):
            fixture.write_text(text)
            try:
                adapter, interface = checked_hierarchical_controller_adapter(original, fixture, imported)
            except AssertionError:
                assert not accepted, label+' rejected a valid interface'
                cases[label] = 'rejected'
            else:
                assert accepted, label+' accepted an invalid interface'
                assert interface['in_channels'] == {'direction': 'input', 'width_bits': 512}
                assert '.clk(clk)' in adapter and '.*' not in adapter
                cases[label] = 'accepted'

        check('flat', renamed, True)
        check('child_after_top', renamed+child, True)
        check('child_before_top', child+renamed, True)
        width, count = re.subn(r'(input\s+)\[511:0\](\s+in_channels\s*;)', r'\g<1>[510:0]\2', renamed, count=1)
        assert count == 1
        check('wrong_width_with_valid_child', width+child, False)
        direction, count = re.subn(r'output\s+in_ready\s*,', 'input in_ready;\n  output ', renamed, count=1)
        assert count == 1
        check('wrong_direction_with_valid_child', child+direction, False)
        check('duplicate_controller_module', renamed+renamed, False)
        check('missing_controller_module', child, False)
        check('truncated_controller_module', renamed.rsplit('endmodule', 1)[0], False)
        try:
            renamed_controller_netlist(mapped, original.stem, original.stem)
        except AssertionError:
            cases['recursive_import_name'] = 'rejected'
        else:
            raise AssertionError('Recursive import name was accepted')
    result = root/'records/adapter155_interface_validation.json'
    assert not result.exists()
    inputs = [Path(__file__).resolve(), root/'syn/tri_oracle_hierarchical_controller_adapter155.py',
              root/'syn/tri_oracle_checked_controller_adapters138.py',
              root/'syn/tri_oracle_named_controller_adapters137.py', original, mapped]
    result.write_text(json.dumps(dict(state='hierarchical_controller_interface_parser_qualified', cases=cases,
        source_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
        temporary_build_removed=not Path(folder).exists(),
        scope='Interface parsing and explicit adapter generation only. Native hierarchical gate import and functionality still required.',
        full_paper_results_matched=False), indent=2)+'\n')
    print(json.dumps(cases, indent=2))


if __name__ == '__main__':
    main()
