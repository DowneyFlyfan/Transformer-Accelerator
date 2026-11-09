"""Generate two narrowly changed controllers without modifying frozen sources."""
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, 'Expected exactly one original source block'
    return text.replace(old, new)


def build_variants(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    frozen = root/'.cache/physical/synthesis/tri_oracle_predicted_fabric_registered_reset30/input_revision.json'
    inventory = json.loads(frozen.read_text())['candidate_rtl_inventory']
    assert all(sha(root/p) == digest for p, digest in inventory.items()), 'Frozen source changed'
    assert not output.exists()
    originals = [root/'verilog'/('tri_oracle_'+unit+'.sv')
                 for unit in ['shared_fabric', 'cluster_projection_executor']]
    sources = {str(p): sha(p) for p in [Path(__file__).resolve(), frozen, *originals,
                                       root/'verilog/tri_oracle_row_address_guard.sv']}
    generated = {}
    for original in originals:
        text = original.read_text()
        instance = ('  logic projection_weight_overflow;\n'
                    '  tri_oracle_row_address_guard #(.ROWS(Rows)) weight_range_guard (\n'
                    '      .in_count(in_count), .in_channels(in_channels), .in_features(in_features),\n'
                    '      .in_weight_base(in_weight_base), .out_overflow(projection_weight_overflow));\n')
        if original.stem == 'tri_oracle_shared_fabric':
            text = once(text, '  logic [64:0] input_bytes,activation_end,weight_end;\n',
                        '  logic [64:0] input_bytes,activation_end;\n'+instance)
            text = once(text, '    weight_end=0;\n', '')
            text = once(text,
                "      for(int row=0;row<Rows;row++) begin\n"
                "        weight_end={1'b0,in_weight_base}+(65'(in_channels[row*16+:16])+1)*input_bytes-1;\n"
                "        if(row<int'(in_count) && weight_end>LastAddress) invalid_shape=1;\n"
                "      end\n", '      if(projection_weight_overflow) invalid_shape=1;\n')
        else:
            assert '  localparam int Lanes = 8;' in text and '  localparam int IdBits = 16;' in text
            text = once(text, '  logic [64:0] activation_end, weight_end, input_bytes;\n',
                        '  logic [64:0] activation_end, input_bytes;\n'+instance)
            text = once(text,
                "    weight_end = 0;\n"
                "    for (int row = 0; row < Rows; row++) begin\n"
                "      weight_end = {1'b0, in_weight_base} +\n"
                "                   (65'(in_channels[row*IdBits+:IdBits]) + 1) * input_bytes - 1;\n"
                "      if (row < int'(in_count) && weight_end > LastAddress) invalid_shape = 1;\n"
                "    end\n", '    if (projection_weight_overflow) invalid_shape = 1;\n')
        assert 'weight_end' not in text
        generated[original] = text
    output.mkdir(parents=True)
    replacements = {}
    for original, text in generated.items():
        path = output/original.name
        path.write_text(text)
        replacements[str(original)] = str(path)
    manifest = dict(state='frozen_controller_row_guard_variants_generated', source_sha256=sources,
                    replacements=replacements, generated_sha256={p: sha(p) for p in replacements.values()},
                    behavior_boundary='Only input weight-row overflow validation; packet interfaces, state machines, '
                                      'memory requests, arithmetic precision and latency unchanged.',
                    frozen_original_files_unchanged=True)
    (output/'variants.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest
