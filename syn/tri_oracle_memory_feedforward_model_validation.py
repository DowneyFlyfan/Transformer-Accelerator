"""Independent scalar and memory-only hardware checks for two checkpoint slices.

H=2048 input features, K=64 selected original intermediate rows, O=35 outputs;
D=5632 is the original intermediate stride. All lists below originate in pinned
checkpoint archives; no expected output calls hardware implementation helpers.
"""
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import tempfile
import time


from tri_oracle_cached_feedforward_model_validation import read_signed, scalar_outputs


def main():
    """Verify pinned scalar baselines, memory-fed sums/traffic, and real fault controls.

    Paths/configurations/logs are scalar metadata, initialized from local files or
    empty containers. Numerical arrays below state their source and dimensions.
    """
    result_path = Path('records/memory_feedforward_model_validation.json')
    result_path.write_text(json.dumps({'passed': False, 'state': 'running'})+'\n')
    available = int(next(line.split()[1] for line in
                         Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:')))*1024  # scalar host headroom
    assert available >= 6*1024**3
    activation_proof = json.loads(Path('records/rms_activation_model_validation.json').read_text())
    assert activation_proof['passed']  # scalar prior4096-word native arithmetic qualification
    for path, digest in activation_proof['input_sha256'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path
    names = ('activation_loader', 'activation_cache', 'rms_activation', 'affine_quantizer', 'rmsnorm',
             'sign_fetch', 'prediction_feedforward_core', 'feedforward_core',
             'strip_predictor', 'channel_compactor', 'predicted_dispatch', 'silu_gate',
             'gated_executor', 'tile_executor', 'sparse_weight_dma', 'down_executor',
             'memory_compute', 'pe_array', 'word_bank')  # source dependency names
    sources = ['verilog/tri_oracle_memory_feedforward_core.sv',
               'verilog/tri_oracle_cached_feedforward_core.sv']+[
        f'verilog/tri_oracle_{name}.sv' for name in names]+['verilog/tri_oracle_memory_model_tb.sv']
    fingerprints = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                    for path in sources+[__file__, 'syn/tri_oracle_cached_feedforward_model_validation.py',
                                  'records/rms_activation_model_validation.json']}
    tools = ['.cache/tools/iverilog', '.cache/tools/vvp', '.cache/tools/ivl/ivl',
             '.cache/tools/ivl/ivlpp', '.cache/tools/ivl/vvp.tgt',
             '.cache/tools/ivl/system.vpi']  # scalar executable/dependency paths
    fingerprints.update({path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                         for path in tools})
    results, log, controls = [], [], []  # empty per-token evidence/log/control lists
    observations = {'peak_container_anonymous_bytes': 0,
                    'minimum_host_available_bytes': available}  # scalar resource observations

    def bounded():
        resource.setrlimit(resource.RLIMIT_AS, (512*1024**2, 512*1024**2))

    def run(arguments, timeout):
        """Execute scalar command metadata; monitor the real child and host reserve."""
        started = time.monotonic()  # scalar monotonic start
        child = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, preexec_fn=bounded, start_new_session=True)
        try:
            while True:
                host_available = int(next(line.split()[1] for line in
                    Path('/proc/meminfo').read_text().splitlines()
                    if line.startswith('MemAvailable:')))*1024  # scalar host availability
                anonymous = int(next(line.split()[1] for line in
                    Path('/sys/fs/cgroup/memory.stat').read_text().splitlines()
                    if line.startswith('anon ')))  # scalar container resident anonymous bytes
                observations['minimum_host_available_bytes'] = min(
                    observations['minimum_host_available_bytes'], host_available)
                observations['peak_container_anonymous_bytes'] = max(
                    observations['peak_container_anonymous_bytes'], anonymous)
                if host_available < 6*1024**3:
                    raise RuntimeError('test stopped first to protect placement host reserve')
                if time.monotonic()-started > timeout:
                    raise TimeoutError(f'native command exceeded {timeout} seconds')
                try:
                    stdout, _ = child.communicate(timeout=.25)  # scalar captured native text
                    return subprocess.CompletedProcess(arguments, child.returncode, stdout, '')
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.communicate()

    def compile_native(binary, inputs):
        """Compile actual source paths to one owned temporary simulation binary."""
        compiled = run(['.cache/tools/iverilog', '-B', '.cache/tools/ivl', '-g2012',
                        '-s', 'tri_oracle_memory_model_tb', '-o', str(binary), *inputs], 90)
        assert compiled.returncode == 0, compiled.stdout

    with tempfile.TemporaryDirectory(prefix='memory_ff_model_', dir='.cache') as directory:
        temporary = Path(directory)  # owned temporary fixture/binary directory
        binary = temporary/'model.vvp'
        compile_native(binary, sources)
        for name in ('feedforward_fixture', 'feedforward_pruning_fixture'):
            root = Path('.cache/model_reference')/name  # pinned source fixture directory
            manifest = json.loads((root/'manifest.json').read_text())  # checkpoint/shape provenance
            source = json.loads((root/'prediction_source.json').read_text())  # residual/gamma[H]
            assert manifest['repository'] == 'bczhou/tiny-llava-v1-hf'
            assert manifest['revision'] == '70f28eb22f0265a8a41858f6aebc1928cedd53eb'
            assert (manifest['hidden_features'], manifest['dense_intermediate_stride'],
                    manifest['output_count']) == (2048, 5632, 35)
            fingerprints[str(root/'manifest.json')] = hashlib.sha256(
                (root/'manifest.json').read_bytes()).hexdigest()
            fixture = temporary/name
            fixture.mkdir()
            for filename, digest in manifest['files'].items():
                path = root/filename
                assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, str(path)
                fingerprints[str(path)] = digest
                # Memory validation never receives a precomputed activation array.
                if filename not in ('activation.hex', 'expected.hex', 'norm.hex'):
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
            assert len(raw) == len(gamma) == len(normalized) == len(activation) == 2048
            assert all(-32768 <= value <= 32767 for value in raw+gamma+normalized)
            assert len(set(gamma)) > 1 and sum(value < 0 for value in gamma) == 3
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
            for filename, values, width in (('norm.hex', normalized, 16), ('raw_residual.hex', raw, 16), ('gamma.hex', gamma, 16),
                                           ('expected.hex', expected, 32)):
                (fixture/filename).write_text(''.join(f'{value & ((1 << width)-1):0{width//4}x}\n'
                                                     for value in values))
            (fixture/'epsilon_q16.hex').write_text(f"{chosen['epsilon_q16']:08x}\n")
            (fixture/'activation_shift.hex').write_text(f"{chosen['shift']:08x}\n")
            generated = {filename: hashlib.sha256((fixture/filename).read_bytes()).hexdigest()
                         for filename in ('norm.hex', 'raw_residual.hex', 'gamma.hex',
                                          'expected.hex', 'epsilon_q16.hex',
                                          'activation_shift.hex')}  # represented-array identities
            assert not (fixture/'activation.hex').exists()
            native = run(['.cache/tools/vvp', '-M', '.cache/tools/ivl',
                          str(binary), f'+FIXTURE_DIR={fixture}'], 180)
            log.extend([json.dumps({'fixture': name}), native.stdout+native.stderr])
            Path('records/memory_feedforward_model_validation.log').write_text('\n'.join(log))
            assert native.returncode == 0, native.stdout+native.stderr
            assert native.stdout.count('PASS: pinned TinyLLaVA-v1') == 1
            traffic = re.search(r'WEIGHT_TRAFFIC: gate_bytes=(\d+) up_bytes=(\d+) '
                                r'dense_bytes_per_matrix=131072 skipped_channels=(\d+) '
                                r'activation_bytes=(\d+) down_bytes=(\d+)', native.stdout)
            signs = re.search(r'HARDWARE_PREDICTION_TRAFFIC: sign_bytes=(\d+)', native.stdout)
            assert traffic and signs
            gate_bytes, up_bytes, skipped_count, activation_bytes, down_bytes = map(int, traffic.groups())
            assert activation_bytes == 0
            source_traffic = re.search(r'SOURCE_TRAFFIC: raw_bytes=(\d+) gamma_bytes=(\d+)', native.stdout)
            assert source_traffic and tuple(map(int, source_traffic.groups())) == (8192, 4096)
            stalled = re.search(r'STALL_COVERAGE: request_cycles=(\d+) output_cycles=(\d+)', native.stdout)
            assert stalled and all(int(value) > 0 for value in stalled.groups())
            assert (gate_bytes, up_bytes, skipped_count, int(signs.group(1)), down_bytes) == (
                (131072, 131072, 0, 288, 2240) if name == 'feedforward_fixture'
                else (86016, 86016, 22, 64, 3640))
            differences = [a-b for a, b in zip(expected, old_expected)]  # [O] arithmetic delta from new codes
            results.append({'fixture': name, 'scalar_baseline_matches_archived_outputs': 35,
                            'native_memory_driven_output_sums_matched': 35,
                            'raw_source_bytes': 8192, 'coefficient_source_bytes': 4096, 'external_activation_bytes': activation_bytes,
                            'represented_input_and_golden_sha256': generated,
                            'request_stall_cycles': int(stalled.group(1)),
                            'output_stall_cycles': int(stalled.group(2)),
                            'gate_bytes': gate_bytes, 'up_bytes': up_bytes, 'sign_bytes': int(signs.group(1)),
                            'down_bytes': down_bytes, 'skipped_channels': skipped_count,
                            'changed_output_sums_vs_archived_activation_codes': sum(value != 0 for value in differences),
                            'maximum_output_accumulator_delta_vs_archived': max(abs(value) for value in differences)})
            if name == 'feedforward_fixture':
                original = (fixture/'expected.hex').read_text()  # [O] independent golden hex
                corrupted = original.splitlines()  # [O] owned copied golden words
                corrupted[0] = f'{int(corrupted[0], 16) ^ 1:08x}'
                (fixture/'expected.hex').write_text('\n'.join(corrupted)+'\n')
                wrong_golden = run(['.cache/tools/vvp', '-M', '.cache/tools/ivl',
                                    str(binary), f'+FIXTURE_DIR={fixture}'], 180)
                (fixture/'expected.hex').write_text(original)
                assert wrong_golden.returncode != 0 and 'model reference mismatch' in wrong_golden.stdout
                log.extend(['NEGATIVE_CONTROL: corrupt first expected output', wrong_golden.stdout])
                controls.append({'fault': 'first independent golden output XOR1',
                                 'rejected': True, 'reason': 'model reference mismatch'})
                loader = Path('verilog/tri_oracle_activation_loader.sv').read_text()
                before = ('if (second_beat) gamma_word[WordWidth+:WordWidth] <= rsp_data;\n'
                          '              else gamma_word[0+:WordWidth] <= rsp_data;')
                after = ('if (second_beat) gamma_word[0+:WordWidth] <= rsp_data;\n'
                         '              else gamma_word[WordWidth+:WordWidth] <= rsp_data;')
                assert loader.count(before) == 1
                mutant = temporary/'swapped_gamma_loader.sv'
                mutant.write_text(loader.replace(before, after))
                mutant_binary = temporary/'swapped_gamma.vvp'
                compile_native(mutant_binary, [str(mutant) if path ==
                    'verilog/tri_oracle_activation_loader.sv' else path for path in sources])
                wrong_packing = run(['.cache/tools/vvp', '-M', '.cache/tools/ivl',
                                     str(mutant_binary), f'+FIXTURE_DIR={fixture}'], 180)
                assert wrong_packing.returncode != 0 and 'model reference mismatch' in wrong_packing.stdout
                log.extend(['NEGATIVE_CONTROL: swap actual loader coefficient beat packing',
                            wrong_packing.stdout])
                controls.append({'fault': 'actual loader swaps two64-bit coefficient halves',
                                 'source_before': before, 'source_after': after,
                                 'mutant_sha256': hashlib.sha256(mutant.read_bytes()).hexdigest(),
                                 'rejected': True, 'reason': 'model reference mismatch'})
                top = Path('verilog/tri_oracle_memory_feedforward_core.sv').read_text()
                before_valid = 'out_valid = state == Error || (state == Run && core_out_valid);'
                after_valid = ('out_valid = (state == Error || (state == Run && core_out_valid))\n'
                               '            & (out_ready ? 1\'b1 : 1\'bx);')
                assert top.count(before_valid) == 1
                mutant_top = temporary/'unknown_valid_top.sv'
                mutant_top.write_text(top.replace(before_valid, after_valid))
                compile_native(mutant_binary, [str(mutant_top) if path ==
                    'verilog/tri_oracle_memory_feedforward_core.sv' else path for path in sources])
                unknown_valid = run(['.cache/tools/vvp', '-M', '.cache/tools/ivl',
                                    str(mutant_binary), f'+FIXTURE_DIR={fixture}'], 180)
                log.extend(['NEGATIVE_CONTROL: actual output-valid unknown while blocked',
                            unknown_valid.stdout])
                Path('records/memory_feedforward_model_validation.log').write_text('\n'.join(log))
                assert unknown_valid.returncode != 0 and 'unknown output-valid' in unknown_valid.stdout
                controls.append({'fault': 'actual memory top drives unknown valid when output blocked',
                                 'source_before': before_valid, 'source_after': after_valid,
                                 'mutant_sha256': hashlib.sha256(mutant_top.read_bytes()).hexdigest(),
                                 'rejected': True, 'reason': 'unknown output-valid'})
                before_stall = '+ (WordWidth\'(strip_index) << StripBytesLog2);'
                after_stall = ('+ (WordWidth\'(strip_index) << StripBytesLog2)\n'
                               '            + (req_ready ? WordWidth\'(0) : WordWidth\'(8));')
                assert loader.count(before_stall) == 1
                mutant.write_text(loader.replace(before_stall, after_stall))
                compile_native(mutant_binary, [str(mutant) if path ==
                    'verilog/tri_oracle_activation_loader.sv' else path for path in sources])
                wrong_stall = run(['.cache/tools/vvp', '-M', '.cache/tools/ivl',
                                  str(mutant_binary), f'+FIXTURE_DIR={fixture}'], 180)
                log.extend(['NEGATIVE_CONTROL: actual request address changes while blocked',
                            wrong_stall.stdout])
                Path('records/memory_feedforward_model_validation.log').write_text('\n'.join(log))
                assert wrong_stall.returncode != 0 and 'request changed under backpressure' in wrong_stall.stdout
                controls.append({'fault': 'actual loader changes address only while ready is low',
                                 'source_before': before_stall, 'source_after': after_stall,
                                 'mutant_sha256': hashlib.sha256(mutant.read_bytes()).hexdigest(),
                                 'rejected': True, 'reason': 'request changed under backpressure'})
                Path('records/memory_feedforward_model_validation.log').write_text('\n'.join(log))
            for filename, digest in generated.items():
                assert hashlib.sha256((fixture/filename).read_bytes()).hexdigest() == digest
    assert not temporary.exists()
    assert len(controls) == 4
    for path, digest in fingerprints.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path
    result = {'scope': 'Memory-only raw residual/coefficient fetch, normalization, prediction and gate/up/down source hardware; two real checkpoint slices.',
              'passed': True, 'state': 'finished', 'input_sha256': fingerprints, 'cases': results,
              'negative_controls': controls, 'resources': observations,
              'log_sha256': hashlib.sha256(
                  Path('records/memory_feedforward_model_validation.log').read_bytes()).hexdigest(),
              'temporary_fixtures_and_binaries_removed': True,
              'limitations': ['Local precision causes13 activation-code changes versus archived floating source',
                              'Only64 intermediate rows and35 outputs per token',
                              'Only the new source interface is checked; mapped/routed implementation remains separate',
                              'No full-model accuracy, compiled memory mapping, physical or paper metric matching']}
    Path('records/memory_feedforward_model_validation.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'passed': True, 'cases': results}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        Path('records/memory_feedforward_model_validation.json').write_text(json.dumps({
            'passed': False, 'state': 'failed', 'error': repr(error),
            'log': 'records/memory_feedforward_model_validation.log'}, indent=2)+'\n')
        raise
