"""Audit the hardware frontend with existing pinned-checkpoint residual/sign data.

Shapes: H=2048 raw residual features; two32-channel groups per token;
gate/up signs[2,32,H]. No model/weight tensor is loaded onto the graphics device.
"""
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
import math
from pathlib import Path

from test_tri_oracle_rmsnorm import normalized_codes
from test_tri_oracle_rms_sign_predictor import RmsSignPredictorTest


def main():
    fixtures = ('feedforward_fixture', 'feedforward_pruning_fixture')
    extra_cases, metadata, input_hashes = [], [], {}
    with localcontext() as context:
        context.prec = 100
        for name in fixtures:
            root = Path('.cache/model_reference')/name
            manifest = json.loads((root/'manifest.json').read_text())
            assert manifest['revision'] == '70f28eb22f0265a8a41858f6aebc1928cedd53eb'
            source = json.loads((root/'prediction_source.json').read_text())
            for filename in ('prediction_source.json', 'gate.hex', 'up.hex',
                             'norm.hex', 'skip.hex', 'groups.hex'):
                path = root/filename
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                assert digest == manifest['files'][filename], str(path)
                input_hashes[str(path)] = digest
            input_hashes[str(root/'manifest.json')] = hashlib.sha256(
                (root/'manifest.json').read_bytes()).hexdigest()
            residual = source['residual_before_rms']  # [H] floating pre-gamma residual
            assert len(residual) == manifest['hidden_features'] == 2048
            maximum = max(abs(value) for value in residual)
            exponent = math.ceil(math.log2(maximum/32767))
            epsilon = Decimal.from_float(source['rms_epsilon'])
            # The squared epsilon must fit32 bits as well as the signed16 data.
            # Small real residuals otherwise suggest an excessively fine scale.
            while epsilon/(Decimal(2)**(2*exponent))*65536 > 4294967295:
                exponent += 1
            scale = Decimal(2)**exponent
            raw = [int((Decimal.from_float(value)/scale).to_integral_value(
                rounding=ROUND_HALF_UP)) for value in residual]  # [H] signed16 codes
            epsilon_q16 = int((epsilon/(scale*scale)*65536).to_integral_value(
                rounding=ROUND_HALF_UP))
            assert max(raw) <= 32767 and min(raw) >= -32768
            assert 0 <= epsilon_q16 <= 4294967295
            normalized = normalized_codes(raw, epsilon_q16)  # [H] independent quotient
            archived = [int(line, 16) for line in (root/'norm.hex').read_text().split()]
            archived = [value-65536 if value >= 32768 else value for value in archived]
            assert len(archived) == len(raw)
            matrices = [[int(word, 16) for word in (root/f'{matrix}.hex').read_text().split()]
                        for matrix in ('gate', 'up')]  # [2,64*H] signed8 bit patterns
            groups = manifest['selected_groups']
            skips = [bool(int(word, 16)) for word in (root/'skip.hex').read_text().split()]
            assert len(groups) == 2 and len(skips) == 64
            assert all(len(matrix) == 64*len(raw) for matrix in matrices)
            differences = [abs(a-b) for a, b in zip(normalized, archived)]
            for offset, group in enumerate(groups):
                signs = [[[int(matrix[(offset*32+row)*len(raw)+feature] >= 128)
                           for feature in range(len(raw))] for row in range(32)]
                         for matrix in matrices]  # [2,32,H] original quantized-weight signs
                extra_cases.append(dict(values=raw, epsilon=epsilon_q16, group=group,
                                        matrix_signs=signs))
                old_mask = sum(int(skips[offset*32+row]) << row for row in range(32))
                metadata.append({
                    'fixture': name, 'prompt_token_position': manifest['token_position'],
                    'group': group, 'hidden_features': len(raw),
                    'raw_scale_power_of_two': exponent, 'epsilon_q16': epsilon_q16,
                    'changed_normalized_codes_vs_float_source': sum(bool(x) for x in differences),
                    'maximum_code_difference_vs_float_source': max(differences),
                    'changed_outlier_positions_vs_float_source': sum(
                        (abs(a) > 768) != (abs(b) > 768) for a, b in zip(normalized, archived)),
                    'archived_skip_mask': old_mask,
                })
    native = RmsSignPredictorTest('test_native_raw_residual_sign_reads_late_faults_and_recovery')
    native.extra_model_cases = extra_cases
    native.test_native_raw_residual_sign_reads_late_faults_and_recovery()
    assert len(native.extra_case_evidence) == len(metadata) == 4
    for record, observed in zip(metadata, native.extra_case_evidence):
        assert not observed['error']
        gate, up = observed['masks']
        skip = gate & up
        record.update({
            'native_mask_comparison_passed': True,
            'gate_mask': gate, 'up_mask': up, 'skip_mask': skip,
            'outliers': observed['count'], 'skipped_channels': skip.bit_count(),
            'sign_word_reads': observed['request_count'],
            'sign_memory_bytes': observed['request_count']*8,
            'skip_mask_changes_vs_archived_float_normalization':
                (skip ^ record['archived_skip_mask']).bit_count(),
        })
    for path in ('verilog/tri_oracle_rmsnorm.sv', 'verilog/tri_oracle_sign_fetch.sv',
                 'verilog/tri_oracle_rms_sign_predictor.sv',
                 'verilog/tri_oracle_strip_predictor.sv',
                 'syn/test_tri_oracle_rmsnorm.py', 'syn/test_tri_oracle_sign_fetch.py',
                 'syn/test_tri_oracle_rms_sign_predictor.py', __file__):
        input_hashes[path] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    result = {
        'scope': 'Two archived real prompt-token residuals, two32-output groups each; source-only native Icarus normalization/sign-memory/prediction frontend.',
        'checkpoint_revision': '70f28eb22f0265a8a41858f6aebc1928cedd53eb',
        'input_sha256': input_hashes, 'cases': metadata,
        'native_stdout': native.native_stdout,
        'passed': True,
        'limitations': ['Local signed16 residual and squared-epsilon quantization',
                       'Packed sign memory layout is a local choice',
                       'Groups renormalize the same input; no cross-group reuse yet',
                       'No connection to routed compute top or learned-gamma datapath',
                       'No full-model/dataset accuracy, physical timing or paper energy claim'],
    }
    Path('records/rms_sign_model_validation.json').write_text(json.dumps(result, indent=2)+'\n')
    print(native.native_stdout, end='')
    print(json.dumps({'passed': True, 'real_cases': metadata}, indent=2))


if __name__ == '__main__':
    main()
