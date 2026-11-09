"""Check that unused tag-interface compaction never changes mapped cells."""
import hashlib
import json
from pathlib import Path

from tri_oracle_compact_tag164 import compact_unused_activation_tags
from tri_oracle_namespace_mapped160 import namespace_mapped_netlist


def main():
    root = Path(__file__).resolve().parents[1]
    netlist = root/'.cache/physical/synthesis/tri_oracle_fabric_gated_executor153/netlist.v'
    source = netlist.read_text()
    parent = 'tri_oracle_fabric_gated_executor_mapped153'
    source, aliases = namespace_mapped_netlist(source, 'tri_oracle_fabric_gated_executor', parent, 'tri_oracle_gated160_')
    child = aliases['tri_oracle_silu_gate']
    normalized, report = compact_unused_activation_tags(source, parent, child)
    assert report['mapped_cell_statements'] == 151275
    assert report['all_mapped_cell_statements_unchanged']
    assert '[7:0] in_tag;' in normalized and 'UNCONNECTED_HIER_Z' not in normalized
    results = dict(matching_qualified_netlist='accepted')
    changes = {
        'live_high_input_bit': lambda text: text.replace('in_tag[0]', 'in_tag[8]', 1),
        'live_high_output_bit': lambda text: text.replace('out_tag[0]', 'out_tag[8]', 1),
        'parent_uses_high_tag_bit': lambda text: text.replace('activation_tag[0]', 'activation_tag[8]', 1),
        'additional_floating_net_consumer': lambda text: text.replace('.in_tag\n', '.in_tag\n', 1).replace(
            '  tri_oracle_gated160_tri_oracle_silu_gate activation_unit',
            '  AND2D1BWP12T40P140 unexpected(.A1(UNCONNECTED_HIER_Z),.A2(clk),.Z(unexpected_net));\n  tri_oracle_gated160_tri_oracle_silu_gate activation_unit', 1),
    }
    for name, change in changes.items():
        mutated = change(source)
        assert mutated != source, 'Mutation did not apply: '+name
        try:
            compact_unused_activation_tags(mutated, parent, child)
        except AssertionError:
            results[name] = 'rejected'
        else:
            raise AssertionError(name+' was accepted')
    path = root/'records/compact164_tag_validation.json'
    assert not path.exists()
    files = [Path(__file__).resolve(), root/'syn/tri_oracle_compact_tag164.py',
             root/'syn/tri_oracle_namespace_mapped160.py', netlist]
    path.write_text(json.dumps(dict(state='unused_tag_interface_compaction_controls_passed', cases=results,
        report=report, source_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
        scope='Static cone and cell-statement checks on the real mapped gate; native reimport/function remain pending.'), indent=2)+'\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
