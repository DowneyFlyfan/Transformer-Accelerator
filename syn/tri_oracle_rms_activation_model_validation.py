"""Native learned-scale activation words against independent Decimal arithmetic.

Two real checkpoint tokens have H=2048 residual/learned-scale/activation values.
Integer residual and coefficient encoding are local precision choices. This is
activation generation only; cache serving and joint compute integration remain open.
"""
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
import math
from pathlib import Path

from test_tri_oracle_rms_activation import RmsActivationTest


def main():
    prior = json.loads(Path('records/rms_sign_model_validation.json').read_text())
    assert prior['passed']
    for path, digest in prior['input_sha256'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path
    cases, metadata, independent, input_hashes = [], [], [], {}
    with localcontext() as context:
        context.prec = 100
        for name in ('feedforward_fixture', 'feedforward_pruning_fixture'):
            root = Path('.cache/model_reference')/name
            source = json.loads((root/'prediction_source.json').read_text())
            manifest = json.loads((root/'manifest.json').read_text())
            for filename in ('prediction_source.json', 'activation.hex', 'norm.hex'):
                path = root/filename;digest = hashlib.sha256(path.read_bytes()).hexdigest()
                assert digest == manifest['files'][filename], str(path)
                input_hashes[str(path)] = digest
            input_hashes[str(root/'manifest.json')] = hashlib.sha256(
                (root/'manifest.json').read_bytes()).hexdigest()
            chosen = next(case for case in prior['cases'] if case['fixture'] == name)
            raw_scale = Decimal(2)**chosen['raw_scale_power_of_two']
            raw = [int((Decimal.from_float(value)/raw_scale).to_integral_value(
                rounding=ROUND_HALF_UP)) for value in source['residual_before_rms']]
            gamma_exponent = -15
            gamma = [int((Decimal.from_float(value)/(Decimal(2)**gamma_exponent)).to_integral_value(
                rounding=ROUND_HALF_UP)) for value in source['learned_normalization_scale']]
            assert len(raw) == len(gamma) == 2048
            assert min(raw) >= -32768 and max(raw) <= 32767
            assert min(gamma) >= -32768 and max(gamma) <= 32767
            epsilon = chosen['epsilon_q16']
            denominator = (sum(Decimal(value*value) for value in raw)/2048+
                           Decimal(epsilon)/65536).sqrt()
            normalized = [int((Decimal(value)*256/denominator).to_integral_value(
                rounding=ROUND_HALF_UP)) for value in raw]
            shift = 8-gamma_exponent+manifest['activation_exponent']
            assert 0 <= shift <= 63
            activation = [max(-128, min(127, int((Decimal(n)*Decimal(g)/(1 << shift))
                          .to_integral_value(rounding=ROUND_HALF_UP)))) for n, g in zip(normalized, gamma)]
            cases.append(dict(values=raw, gamma=gamma, shift=shift, epsilon=epsilon))
            independent.append((normalized, activation))
            archived = [int(value, 16) for value in (root/'activation.hex').read_text().split()]
            archived = [value-256 if value >= 128 else value for value in archived]
            norm_archived = [int(value, 16) for value in (root/'norm.hex').read_text().split()]
            norm_archived = [value-65536 if value >= 32768 else value for value in norm_archived]
            changes = [a-b for a, b in zip(activation, archived)]
            scale = 2.0**manifest['activation_exponent']
            actual = source['ffn_activation']
            squared_actual = math.fsum(value*value for value in actual)
            assert squared_actual > 0
            baseline_error = math.sqrt(math.fsum((a*scale-b)**2 for a, b in zip(archived, actual))/squared_actual)
            hardware_error = math.sqrt(math.fsum((a*scale-b)**2 for a, b in zip(activation, actual))/squared_actual)
            metadata.append({
                'fixture': name, 'prompt_token_position': manifest['token_position'],
                'raw_scale_power_of_two': chosen['raw_scale_power_of_two'],
                'gamma_scale_power_of_two': gamma_exponent,
                'activation_scale_power_of_two': manifest['activation_exponent'],
                'shift': shift, 'epsilon_q16': epsilon,
                'negative_encoded_gamma_values': sum(value < 0 for value in gamma),
                'hardware_codes_compared': len(activation),
                'changed_codes_vs_archived_float_normalization': sum(value != 0 for value in changes),
                'maximum_code_difference_vs_archived': max(abs(value) for value in changes),
                'maximum_physical_difference_vs_archived': max(abs(value) for value in changes)*scale,
                'signed_code_differences': {str(value): changes.count(value) for value in sorted(set(changes))},
                'archived_activation_relative_l2_error_vs_float': baseline_error,
                'hardware_activation_relative_l2_error_vs_float': hardware_error,
                'changed_prediction_outlier_positions': sum((abs(a) > 768) != (abs(b) > 768)
                                                           for a, b in zip(normalized, norm_archived)),
            })
    native = RmsActivationTest('test_native_raw_residual_gamma_capture_errors_and_reset')
    native.extra_model_cases = cases
    native.test_native_raw_residual_gamma_capture_errors_and_reset()
    assert len(native.extra_case_evidence) == 2
    for observed, (normalized, activation) in zip(native.extra_case_evidence, independent):
        assert observed['normalized_codes'] == normalized
        assert observed['activation_codes'] == activation
    for record in metadata:
        record['native_all_words_match_independent_decimal'] = True
    paths = ['verilog/tri_oracle_rmsnorm.sv', 'verilog/tri_oracle_affine_quantizer.sv',
             'verilog/tri_oracle_rms_activation.sv', 'syn/test_tri_oracle_rmsnorm.py',
             'syn/test_tri_oracle_affine_quantizer.py', 'syn/test_tri_oracle_rms_activation.py',
             'records/rms_sign_model_validation.json', __file__]
    input_hashes.update({path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths})
    result = {
        'scope': 'Native generation of4096 real-checkpoint learned-scale/quantized activation codes and pre-scale prediction metadata; not connected to compute activation-cache serving.',
        'passed': True, 'input_sha256': input_hashes, 'cases': metadata,
        'total_real_activation_codes_matched': 4096, 'native_stdout': native.native_stdout,
        'limitations': ['Raw residual/coefficient/output precision and thresholds are local choices',
                       '13 of4096 codes differ by one from archived floating-input activation quantization',
                       'Downstream sums with the new activation codes are not qualified in this experiment',
                       'No learned-scale coefficient memory fetch or activation-cache serving yet',
                       'No full-model accuracy, new-top physical qualification or paper metric matching'],
    }
    Path('records/rms_activation_model_validation.json').write_text(json.dumps(result, indent=2)+'\n')
    print(native.native_stdout, end='')
    print(json.dumps({'passed': True, 'cases': metadata}, indent=2))


if __name__ == '__main__':
    main()
