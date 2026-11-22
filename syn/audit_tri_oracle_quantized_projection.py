"""Check trained shared-array work through accepted signed eight-bit outputs."""
if not __debug__:
    raise RuntimeError('Verification requires Python assertions; run without -O.')

from pathlib import Path
import hashlib
import json
import re
import sys
import types

import audit_tri_oracle_shared_projection as raw_audit

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.cache/late_clipping_20261121/frame_integration/quantized_shared_projection_v1'
REFERENCE_SHA = 'e1a24f5299eb77ddee886494c79e7c80575ac58943a84a28b2e150257536a459'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_quantized(log):
    """Validate every accepted word, units, channel identity and release order."""
    assert not re.search(r'\*[EWF],', log), 'Native diagnostic present'
    assert sha(WORK / 'reference.json') == REFERENCE_SHA
    reference = json.loads((WORK / 'reference.json').read_text())
    for path, wanted in reference['evidence_sha256'].items():
        assert sha(path) == wanted, path
    expected = [int(word, 16) for word in (WORK / 'expected_output_words.hex').read_text().splitlines()]
    assert len(expected) == 256
    lines = log.splitlines()
    units = [(i, raw_audit.fields(line)) for i, line in enumerate(lines) if line.startswith('SHARED_PROJECTION_UNITS ')]
    assert len(units) == 1, 'Missing unique hardware unit witness'
    unit_index, actual_units = units[0]
    def packed(values):
        return int.from_bytes(bytes(x & 255 for x in values), 'little')
    assert set(actual_units) == {'context', 'weights', 'outputs'}
    assert int(actual_units['context']) == reference['context_exponent']
    assert int(actual_units['weights'], 16) == packed(reference['weight_exponents'])
    assert int(actual_units['outputs'], 16) == packed(reference['output_exponents'])
    rows = [(i, raw_audit.fields(line)) for i, line in enumerate(lines) if line.startswith('SHARED_QUANTIZED_WORD ')]
    assert len(rows) == 256, 'Missing or duplicate quantized word'
    for ordinal, (_, word) in enumerate(rows):
        assert set(word) == {'index', 'tag', 'token', 'source_last', 'packet_last', 'count', 'channels', 'data'}
        assert int(word['index']) == ordinal, 'Reordered or duplicated word'
        channel_start = ordinal * 8
        assert int(word['tag'], 16) == 0x80000000 + channel_start // 160
        assert int(word['token']) == 0 and int(word['source_last']) == 1
        assert int(word['count']) == 8
        assert int(word['packet_last']) == int(channel_start % 160 == 152 or channel_start == 2040)
        channels = int(word['channels'], 16)
        assert [channels >> (16 * lane) & 65535 for lane in range(8)] == list(range(channel_start, channel_start + 8))
        assert int(word['data'], 16) == expected[ordinal], ('Quantized trained word differs', ordinal)
    dots = {group: [] for group in range(13)}
    groups = {}
    for i, line in enumerate(lines):
        if line.startswith('SHARED_PROJECTION_DOT '):
            channel = int(raw_audit.fields(line)['channel'])
            assert 0 <= channel < 2048
            dots[channel // 160].append(i)
        elif line.startswith('SHARED_PROJECTION_GROUP_PASS '):
            group = int(raw_audit.fields(line)['group'])
            assert group not in groups
            groups[group] = i
    assert set(groups) == set(range(13))
    for group in range(13):
        count = 128 if group == 12 else 160
        assert len(dots[group]) == count
        words = rows[group * 20:group * 20 + count // 8]
        assert max(dots[group]) < words[0][0] <= words[-1][0] < groups[group], 'Packet ownership released before its words'
    def unique_index(text):
        found = [i for i, line in enumerate(lines) if line == text]
        assert len(found) == 1, ('Missing unique completion', text)
        return found[0]
    frame_indices = [i for i, line in enumerate(lines) if line.startswith('COMMIT_FRAME_READY ')]
    assert len(frame_indices) == 1
    finish = unique_index('COMMIT_FINISH_ACCEPTED')
    collector = unique_index('COMMIT_COLLECTOR_TERMINAL error=0')
    terminal = unique_index('SHARED_QUANTIZED_PROJECTION_PASS words=256 codes=2048')
    assert frame_indices[0] < unit_index < rows[0][0] < rows[-1][0] < finish < collector < terminal, 'Output ownership released early'
    return dict(exact_quantized_projection_codes=2048, accepted_quantized_words=256,
                context_exponent=reference['context_exponent'], per_output_groups=32,
                held_output_and_final_drain_verified=True)


def check(log):
    result = raw_audit.check(log, 'positive')
    result.update(check_quantized(log))
    result['quantized_projection_output_verified'] = True
    # This test uses captured Q/K/V, one trained layer/query, and source hardware.
    result.update(fresh_query_key_value_projection_verified=False,
                  full_decoder_integration_verified=False,
                  current_mapped_candidate_verified=False,
                  full_accuracy_verified=False, paper_matching=False)
    return result


def qualify():
    out = WORK / 'native_integration_v3'
    status = json.loads((out / 'status.json').read_text())
    invocation = json.loads((out / 'invocation.json').read_text())
    assert status['exit_status'] == 0 and status['owned_group_terminal']
    assert status['stop_reason'] is None and status['supervisor_error'] is None
    for path, wanted in invocation['source_sha256'].items():
        assert sha(path) == wanted, path
    argv = invocation['argv']
    xrun = argv.index('/opt/cadence/bin/xrun')
    assert '+define+QUANTIZED_PROJECTION' in argv
    assert argv[argv.index('-top') + 1] == 'tri_oracle_shared_attention_projection_tb'
    checker_path = next(Path(p) for p in invocation['source_sha256'] if p.endswith('/invocation_v2.py'))
    checker = types.ModuleType('quantized_invocation_check')
    checker.__file__ = str(checker_path)
    exec(compile(checker_path.read_bytes(), str(checker_path), 'exec'), checker.__dict__)
    log = (out / 'xrun.log').read_text()
    checker.verify_invocation(log, argv[xrun + 1:])
    unit = WORK / 'green_v1'
    unit_status = json.loads((unit / 'status.json').read_text())
    unit_invocation = json.loads((unit / 'invocation.json').read_text())
    assert unit_status['exit_status'] == 0 and unit_status['owned_group_terminal']
    assert unit_status['stop_reason'] is None and unit_status['supervisor_error'] is None
    for path, wanted in unit_invocation['source_sha256'].items():
        assert sha(path) == wanted, path
    assert '+define+QUANTIZER_ABSENT' not in unit_invocation['argv']
    unit_log = (unit / 'xrun.log').read_text()
    unit_argv = unit_invocation['argv']
    checker.verify_invocation(unit_log, unit_argv[unit_argv.index('/opt/cadence/bin/xrun') + 1:])
    assert not re.search(r'\*[EWF],', unit_log)
    assert len(re.findall(r'^PROJECTION_REQUANTIZER_PASS packets=39 values=2096 trained_codes=2048 rejected=8 stalls=\d+$', unit_log, re.M)) == 1
    result = check(log)
    error_out = WORK / 'native_error_v3'
    error_status = json.loads((error_out / 'status.json').read_text())
    error_invocation = json.loads((error_out / 'invocation.json').read_text())
    assert error_status['exit_status'] == 0 and error_status['owned_group_terminal']
    assert error_status['stop_reason'] is None and error_status['supervisor_error'] is None
    for path, wanted in error_invocation['source_sha256'].items():
        assert sha(path) == wanted, path
    error_argv = error_invocation['argv']
    assert '+PROJECTION_ERROR' in error_argv and '+define+PROJECTION_FAULT_PROBE' in error_argv
    error_log = (error_out / 'xrun.log').read_text()
    checker.verify_invocation(error_log, error_argv[error_argv.index('/opt/cadence/bin/xrun') + 1:])
    error_result = raw_audit.check(error_log, 'error')
    assert 'SHARED_QUANTIZED_WORD ' not in error_log
    assert error_result['accepted_weight_error_drain_verified'] and error_result['requested_weight_words'] == 16
    broad = json.loads((WORK / 'project_regression_review.json').read_text())
    assert broad['full_project_regression_passed'] is False
    result.update(state='shared_array_trained_quantized_projection_verified',
                  native_wall_seconds=status['wall_seconds'],
                  native_error_wall_seconds=error_status['wall_seconds'],
                  literal_boundary_cases=22, additional_unit_test_values=48, rejected_descriptors=8,
                  accepted_weight_error_drain_verified=True,
                  converter_payload_storage_bits=0, converter_control_state_bits=9,
                  full_project_regression_passed=False,
                  known_broad_regression_limit='25 simulation passes; 12 pre-existing unused-signal lint warnings in unchanged compute_cluster/fabric')
    evidence = [Path(__file__).resolve(), ROOT / 'verilog/tri_oracle_projection_requantizer.sv',
                ROOT / 'verilog/tri_oracle_projection_requantizer_tb.sv',
                ROOT / 'verilog/tri_oracle_shared_attention_projection_tb.sv', WORK / 'reference.json',
                WORK / 'integration_inputs_v3.json', WORK / 'project_regression_review.json']
    evidence += [p / name for p in [out, unit, error_out] for name in ['xrun.log', 'console.log', 'status.json', 'invocation.json']]
    result['evidence_sha256'] = {str(p): sha(p) for p in evidence}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    qualify()
