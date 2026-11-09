"""Independent scalar and native cached-compute checks for two checkpoint slices.

H=2048 input features, K=64 selected original intermediate rows, O=35 outputs;
D=5632 is the original intermediate stride. All lists below originate in pinned
checkpoint archives; no expected output calls hardware implementation helpers.
"""
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
import math
from pathlib import Path
import re
import resource
import subprocess
import tempfile


def read_signed(path, bits):
    """path/bits: scalar archive filename/code width; result[L] signed stored codes."""
    words = [int(value, 16) for value in path.read_text().split()]  # [L] hex source
    return [value-(1 << bits) if value >= 1 << (bits-1) else value for value in words]


def round_code(value, shift, bits):
    """Scalar integer value, right shift and signed width -> one saturated code."""
    magnitude = abs(value)  # scalar absolute input product/accumulator
    quotient, remainder = divmod(magnitude, 1 << shift)  # scalar exact division
    if shift and remainder*2 >= 1 << shift:
        quotient += 1
    signed = -quotient if value < 0 else quotient  # scalar ties-away result
    return max(-(1 << (bits-1)), min((1 << (bits-1))-1, signed))


def scalar_outputs(activation, gate, up, down, selected, skipped, shifts):
    """activation[H], gate/up[K*H], down[O*D], selected[K], skipped[K], shifts[3].

    Inputs are signed archive codes or independently generated activation codes;
    selected contains original channel IDs. Gate/up stages use signed16 codes
    with8 fractional bits; output[O] is the exact signed32 down accumulator.
    No loss/optimizer: this is inference arithmetic, not model training.
    """
    hidden = len(activation)  # H, scalar feature count from activation[H]
    channels = len(selected)  # K, scalar selected original-row count
    dense = 5632  # D, scalar archived down-row stride
    outputs = len(down)//dense  # O, scalar number of archived output rows
    assert hidden == 2048 and channels == 64 and outputs == 35
    assert len(gate) == len(up) == channels*hidden
    table = []  # [257] independently computed SiLU samples at x=-8+i/16
    for index in range(257):
        position = -8+index/16  # scalar sample coordinate
        value = 256*position/(1+math.exp(-position))  # scalar sampled nonlinear code
        table.append((-1 if value < 0 else 1)*math.floor(abs(value)+.5))
    down_input = []  # [K] derived signed8 gated activations
    for row in range(channels):
        first = row*hidden  # scalar source offset into row-major matrices
        gate_sum = sum(activation[feature]*gate[first+feature]
                       for feature in range(hidden))  # scalar exact dot sum
        up_sum = sum(activation[feature]*up[first+feature]
                     for feature in range(hidden))  # scalar exact dot sum
        gate_code = round_code(gate_sum, shifts[0], 16)  # scalar signed16 Q8
        up_code = round_code(up_sum, shifts[1], 16)  # scalar signed16 Q8
        if gate_code <= -2048:
            nonlinear = 0  # scalar negative SiLU tail
        elif gate_code >= 2048:
            nonlinear = gate_code  # scalar positive linear tail
        else:
            lower, fraction = divmod(gate_code+2048, 16)  # scalar sample/fraction
            blend = table[lower]*(16-fraction)+table[lower+1]*fraction  # scalar Q12 blend
            nonlinear = round_code(blend, 4, 16)  # scalar interpolated signed16 Q8
        product = round_code(nonlinear*up_code, 8, 16)  # scalar signed16 Q8
        down_input.append(0 if skipped[row] else round_code(product, shifts[2], 8))
    result = [sum(down[row*dense+selected[channel]]*down_input[channel]
                  for channel in range(channels)) for row in range(outputs)]  # [O] exact
    assert all(-(1 << 31) <= value < 1 << 31 for value in result)
    return result


def main():
    """Verify archive shapes/identity, scalar baseline, cached native sums and traffic."""
    available = int(next(line.split()[1] for line in
                         Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:')))*1024  # scalar host headroom
    assert available >= 8*1024**3
    activation_proof = json.loads(Path('records/rms_activation_model_validation.json').read_text())
    assert activation_proof['passed']  # scalar prior4096-word native arithmetic qualification
    for path, digest in activation_proof['input_sha256'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path
    names = ('activation_cache', 'rms_activation', 'affine_quantizer', 'rmsnorm',
             'sign_fetch', 'prediction_feedforward_core', 'feedforward_core',
             'strip_predictor', 'channel_compactor', 'predicted_dispatch', 'silu_gate',
             'gated_executor', 'tile_executor', 'sparse_weight_dma', 'down_executor',
             'memory_compute', 'pe_array', 'word_bank')  # source dependency names
    sources = ['verilog/tri_oracle_cached_feedforward_core.sv']+[
        f'verilog/tri_oracle_{name}.sv' for name in names]+['verilog/tri_oracle_model_feedforward_tb.sv']
    fingerprints = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                    for path in sources+[__file__, 'records/rms_activation_model_validation.json']}
    results, log = [], []  # per-token scalar/native evidence records and console log

    def bounded():
        resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))

    with tempfile.TemporaryDirectory(prefix='cached_ff_model_', dir='.cache') as directory:
        temporary = Path(directory)  # owned temporary fixture/binary directory
        binary = temporary/'model.vvp'
        compiled = subprocess.run([
            'iverilog', '-g2012', '-s', 'tri_oracle_model_feedforward_tb', '-P',
            'tri_oracle_model_feedforward_tb.HARDWARE_PREDICTION=2', '-o', str(binary),
            *sources], capture_output=True, text=True, timeout=90, preexec_fn=bounded)
        assert compiled.returncode == 0, compiled.stderr
        for name in ('feedforward_fixture', 'feedforward_pruning_fixture'):
            root = Path('.cache/model_reference')/name  # pinned source fixture directory
            manifest = json.loads((root/'manifest.json').read_text())  # checkpoint/shape provenance
            source = json.loads((root/'prediction_source.json').read_text())  # residual/gamma[H]
            fixture = temporary/name
            fixture.mkdir()
            for filename, digest in manifest['files'].items():
                path = root/filename
                assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, str(path)
                fingerprints[str(path)] = digest
                # Native mode2 never receives a precomputed activation array.
                if filename not in ('activation.hex', 'expected.hex'):
                    (fixture/filename).symlink_to(path.resolve())
            chosen = next(case for case in activation_proof['cases'] if case['fixture'] == name)
            with localcontext() as context:
                context.prec = 100
                scale = Decimal(2)**chosen['raw_scale_power_of_two']  # scalar residual scale
                gamma_scale = Decimal(2)**chosen['gamma_scale_power_of_two']  # scalar coefficient scale
                raw = [int((Decimal.from_float(value)/scale).to_integral_value(rounding=ROUND_HALF_UP))
                       for value in source['residual_before_rms']]  # [H] represented residual
                gamma = [int((Decimal.from_float(value)/gamma_scale).to_integral_value(rounding=ROUND_HALF_UP))
                         for value in source['learned_normalization_scale']]  # [H] represented coefficients
                denominator = (sum(Decimal(value*value) for value in raw)/2048+
                               Decimal(chosen['epsilon_q16'])/65536).sqrt()  # scalar RMS divisor
                normalized = [int((Decimal(value)*256/denominator).to_integral_value(rounding=ROUND_HALF_UP))
                              for value in raw]  # [H] independent pre-scale signed16 Q8
                activation = [max(-128, min(127, int((Decimal(n)*g/(1 << chosen['shift']))
                              .to_integral_value(rounding=ROUND_HALF_UP))))
                              for n, g in zip(normalized, gamma)]  # [H] independent signed8 codes
            gate = read_signed(root/'gate.hex', 8)  # [K*H] frozen row-major weights
            up = read_signed(root/'up.hex', 8)  # [K*H] frozen row-major weights
            down = read_signed(root/'down.hex', 8)  # [O*D] frozen full-stride weights
            skipped = [bool(value) for value in read_signed(root/'skip.hex', 8)]  # [K] archived decisions
            selected = manifest['selected_channels']  # [K] original row identities
            shifts = read_signed(root/'configuration.hex', 32)[:3]  # [3] gate/up/down shifts
            old_activation = read_signed(root/'activation.hex', 8)  # [H] archived float-derived codes
            old_expected = read_signed(root/'expected.hex', 32)  # [O] independent archived golden
            assert scalar_outputs(old_activation, gate, up, down, selected, skipped, shifts) == old_expected
            expected = scalar_outputs(activation, gate, up, down, selected, skipped, shifts)  # [O]
            for filename, values, width in (('raw_residual.hex', raw, 16), ('gamma.hex', gamma, 16),
                                           ('expected.hex', expected, 32)):
                (fixture/filename).write_text(''.join(f'{value & ((1 << width)-1):0{width//4}x}\n'
                                                     for value in values))
            (fixture/'epsilon_q16.hex').write_text(f"{chosen['epsilon_q16']:08x}\n")
            (fixture/'activation_shift.hex').write_text(f"{chosen['shift']:08x}\n")
            assert not (fixture/'activation.hex').exists()
            native = subprocess.run(['vvp', str(binary), f'+FIXTURE_DIR={fixture}'],
                                    capture_output=True, text=True, timeout=180, preexec_fn=bounded)
            log.extend([json.dumps({'fixture': name}), native.stdout+native.stderr])
            Path('records/cached_feedforward_model_validation.log').write_text('\n'.join(log))
            assert native.returncode == 0, native.stdout+native.stderr
            assert native.stdout.count('PASS: pinned TinyLLaVA-v1') == 1
            traffic = re.search(r'WEIGHT_TRAFFIC: gate_bytes=(\d+) up_bytes=(\d+) '
                                r'dense_bytes_per_matrix=131072 skipped_channels=(\d+) '
                                r'activation_bytes=(\d+) down_bytes=(\d+)', native.stdout)
            signs = re.search(r'HARDWARE_PREDICTION_TRAFFIC: sign_bytes=(\d+)', native.stdout)
            assert traffic and signs
            gate_bytes, up_bytes, skipped_count, activation_bytes, down_bytes = map(int, traffic.groups())
            assert activation_bytes == 0
            differences = [a-b for a, b in zip(expected, old_expected)]  # [O] arithmetic delta from new codes
            results.append({'fixture': name, 'scalar_baseline_matches_archived_outputs': 35,
                            'native_cached_output_sums_matched': 35, 'external_activation_bytes': activation_bytes,
                            'gate_bytes': gate_bytes, 'up_bytes': up_bytes, 'sign_bytes': int(signs.group(1)),
                            'down_bytes': down_bytes, 'skipped_channels': skipped_count,
                            'changed_output_sums_vs_archived_activation_codes': sum(value != 0 for value in differences),
                            'maximum_output_accumulator_delta_vs_archived': max(abs(value) for value in differences)})
    assert not temporary.exists()
    for path, digest in fingerprints.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path
    result = {'scope': 'Cached source hardware from raw residual/learned-scale streams through local activation reads, prediction and final gate/up/down sums; two real checkpoint slices.',
              'passed': True, 'input_sha256': fingerprints, 'cases': results,
              'temporary_fixtures_and_binaries_removed': True,
              'limitations': ['Local precision causes13 activation-code changes versus archived floating source',
                              'Only64 intermediate rows and35 outputs per token',
                              'Learned coefficients still stream from caller; no coefficient memory-fetch controller',
                              'No full-model accuracy, compiled memory mapping, physical or paper metric matching']}
    Path('records/cached_feedforward_model_validation.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'passed': True, 'cases': results}, indent=2))


if __name__ == '__main__':
    main()
