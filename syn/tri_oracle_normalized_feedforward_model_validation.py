"""Check connected hardware prediction and compute against archived model sums.

H=2048 features, K=64 selected original rows, O=35 down-projection outputs.
Raw residual[H] drives prediction; existing learned-scale activation[H] remains
the compute-memory input. No full-model or learned-gamma hardware claim follows.
"""
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
from pathlib import Path
import re
import resource
import subprocess
import tempfile


def main():
    available = int(next(line.split()[1] for line in
                         Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:')))*1024
    assert available >= 8*1024**3
    frontend = json.loads(Path('records/rms_sign_model_validation.json').read_text())
    assert frontend['passed']
    for path, digest in frontend['input_sha256'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path
    sources = ['verilog/tri_oracle_normalized_feedforward_core.sv']+[
        f'verilog/tri_oracle_{name}.sv' for name in (
            'rmsnorm', 'sign_fetch', 'prediction_feedforward_core', 'feedforward_core', 'strip_predictor',
            'channel_compactor', 'predicted_dispatch', 'silu_gate', 'gated_executor',
            'tile_executor', 'sparse_weight_dma', 'down_executor', 'memory_compute',
            'pe_array', 'word_bank')]+['verilog/tri_oracle_model_feedforward_tb.sv']
    input_hashes = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                    for path in sources+[__file__, 'records/rms_sign_model_validation.json']}
    results, log = [], []

    def bounded():
        resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))

    with tempfile.TemporaryDirectory(prefix='normalized_ff_model_', dir='.cache') as directory:
        temporary = Path(directory)
        for hardware_prediction in (0, 1):
            binary = temporary/f'model_{hardware_prediction}.vvp'
            compiled = subprocess.run([
                'iverilog', '-g2012', '-s', 'tri_oracle_model_feedforward_tb',
                '-P', f'tri_oracle_model_feedforward_tb.HARDWARE_PREDICTION={hardware_prediction}',
                '-o', str(binary), *sources], capture_output=True, text=True,
                timeout=90, preexec_fn=bounded)
            assert compiled.returncode == 0, compiled.stderr
            for name in ('feedforward_fixture', 'feedforward_pruning_fixture'):
                original = Path('.cache/model_reference')/name
                manifest = json.loads((original/'manifest.json').read_text())
                fixture = temporary/f'{name}_{hardware_prediction}'
                fixture.mkdir()
                for filename, digest in manifest['files'].items():
                    source = original/filename
                    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest, str(source)
                    input_hashes[str(source)] = digest
                    (fixture/filename).symlink_to(source.resolve())
                metadata = next(case for case in frontend['cases'] if case['fixture'] == name)
                with localcontext() as context:
                    context.prec = 100
                    residual = json.loads((original/'prediction_source.json').read_text())[
                        'residual_before_rms']  # [H] frozen real residual before learned scale
                    scale = Decimal(2)**metadata['raw_scale_power_of_two']
                    raw = [int((Decimal.from_float(value)/scale).to_integral_value(
                        rounding=ROUND_HALF_UP)) for value in residual]  # [H] signed16
                assert len(raw) == 2048 and min(raw) >= -32768 and max(raw) <= 32767
                (fixture/'raw_residual.hex').write_text(''.join(f'{value & 0xffff:04x}\n'
                                                               for value in raw))
                (fixture/'epsilon_q16.hex').write_text(f"{metadata['epsilon_q16']:08x}\n")
                native = subprocess.run(['vvp', str(binary), f'+FIXTURE_DIR={fixture}'],
                                        capture_output=True, text=True, timeout=180,
                                        preexec_fn=bounded)
                log.append(json.dumps({'fixture': name, 'hardware_prediction': hardware_prediction}))
                log.append(native.stdout+native.stderr)
                Path('records/normalized_feedforward_model_validation.log').write_text('\n'.join(log))
                assert native.returncode == 0, native.stdout+native.stderr
                assert native.stdout.count('PASS: pinned TinyLLaVA-v1') == 1
                traffic = re.search(r'WEIGHT_TRAFFIC: gate_bytes=(\d+) up_bytes=(\d+) '
                                    r'dense_bytes_per_matrix=131072 skipped_channels=(\d+) '
                                    r'activation_bytes=(\d+) down_bytes=(\d+)', native.stdout)
                assert traffic, native.stdout
                gate, up, skipped, activation, down = map(int, traffic.groups())
                sign = 0
                if hardware_prediction:
                    sign_match = re.search(r'HARDWARE_PREDICTION_TRAFFIC: sign_bytes=(\d+)', native.stdout)
                    assert sign_match
                    sign = int(sign_match.group(1))
                    assert sign == sum(case['sign_memory_bytes'] for case in frontend['cases']
                                       if case['fixture'] == name)
                results.append({
                    'fixture': name, 'hardware_prediction': bool(hardware_prediction),
                    'independent_output_sums_matched': 35,
                    'skipped_channels': skipped, 'gate_bytes': gate, 'up_bytes': up,
                    'sign_bytes': sign, 'activation_bytes': activation, 'down_bytes': down,
                    'raw_scale_power_of_two': metadata['raw_scale_power_of_two'],
                    'epsilon_q16': metadata['epsilon_q16'],
                })
    assert not temporary.exists()
    assert len(results) == 4
    for path, digest in input_hashes.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path
    for name in ('feedforward_fixture', 'feedforward_pruning_fixture'):
        before, after = [case for case in results if case['fixture'] == name]
        assert (before['gate_bytes'], before['up_bytes'], before['skipped_channels']) == (
            after['gate_bytes'], after['up_bytes'], after['skipped_channels'])
    result = {
        'scope': 'Connected source hardware prediction/sign reads and gate/up/down computation on two archived real checkpoint slices; original software-driven prediction mode also rechecked.',
        'passed': True, 'input_sha256': input_hashes, 'cases': results,
        'temporary_fixtures_and_binaries_removed': True,
        'limitations': ['Compute activation memory still contains software learned-scale/quantized inputs',
                       'Only64 selected intermediate channels and35 output rows per token',
                       'Local precision, thresholds, packed signs, replay and bus protocol',
                       'No physical implementation, model-wide accuracy or paper metric matching'],
    }
    Path('records/normalized_feedforward_model_validation.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'passed': True, 'cases': results}, indent=2))


if __name__ == '__main__':
    main()
