"""Synthetic host-only comparison of two three-sigma outlier policies.

Axes: raw[M=6,H=2048] signed32, gain[H] signed24 all one, epsilon[M]
unsigned64 all zero, gamma_exponent[M] signed8 all zero. The six caller-owned
rows are three declared constant-tail vectors and their exact sign mirrors.
No original trained values, tensor library, graphics processor or RTL runtime.
"""
from pathlib import Path
import ast
import hashlib
import json
import math
import os
import resource
import stat
import struct
import sys
import time
import types

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NORMALIZERS = ROOT / 'syn/tri_oracle_exact_c_normalizer'
API = NORMALIZERS / 'exact_normalizer_api_v1.py'
CPU = NORMALIZERS / 'cpu_fixedwords_v1.py'
RTL = ROOT / 'verilog/tri_oracle_fused_input_normalizer_wide_v1.sv'
HISTORICAL = ROOT / 'syn/tri_oracle_integer_reference.py'
CPU_SHA = 'e9e4a1eb776e4283d321ad89d81bc48d0c288c97f2ff4616fb57ca6cf643f29e'
H = 2048


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def identity(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid, s.st_size,
            s.st_mtime_ns, s.st_ctime_ns]


def closed(path):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and path.resolve() == path, 'regular canonical source')
    with path.open('rb') as stream:
        require(identity(os.fstat(stream.fileno())) == identity(before), 'opening source identity')
        raw = stream.read()
        after_fd = identity(os.fstat(stream.fileno()))
    after_path = identity(path.lstat())
    require(identity(before) == after_fd == after_path, 'stable source identity')
    return raw, dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                     identity_before=identity(before), identity_after_fd=after_fd,
                     identity_after_path=after_path, complete_EOF=True)


def rounded_q8(raw_lane, energy):
    """Independent exact nearest/half-away Q8 code for one signed raw scalar.

    Its nonnegative square is raw_lane^2*H*256^2/energy. Integer floor sqrt
    followed by the exact squared midpoint comparison reproduces half-away
    rounding without floating square root or the production limb helpers.
    """
    numerator = raw_lane * raw_lane * H * 256**2
    floor = math.isqrt(numerator // energy)
    magnitude = floor + int(4*numerator >= (2*floor+1)**2 * energy)
    code = -magnitude if raw_lane < 0 else magnitude
    return max(-32768, min(32767, code))


def main():
    require(__debug__ and sys.dont_write_bytecode and
            (len(sys.argv) == 1 or (len(sys.argv) == 3 and sys.argv[1] == '--output')),
            'unoptimized Python-B with optional --output required')
    # Bound the process before source imports, synthetic normalization or math.
    resource.setrlimit(resource.RLIMIT_AS, (128 << 20, 128 << 20))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    started = time.monotonic()
    source_paths = [Path(__file__).resolve(), API, CPU, RTL, HISTORICAL]
    sources = {str(p): closed(p) for p in source_paths}
    expected = {
        API: '35b45a906d0f637fcd0f821e7b7056b8b2f0a4f87f2d3fe33b3664d618e4f5f4',
        CPU: CPU_SHA,
        RTL: 'c77050304eb235a0dd13f5c7a20a94266531680f46576b5fe5356087c0e62bed',
        HISTORICAL: '8a61793403dacf6439e6e326e9b572cdc1ffd794aea3b41173e06787d1778d8a',
    }
    for path, checksum in expected.items():
        require(sources[str(path)][1]['sha256'] == checksum, 'frozen compared method source')
    rtl = sources[str(RTL)][0].decode()
    require("denominator_total=(DENOMINATOR_WIDTH'(stats_total)<<16)" in rtl
            and "+DENOMINATOR_WIDTH'(features)*DENOMINATOR_WIDTH'(epsilon_q16);" in rtl
            and "saved_outliers[lane]<=((COMPARE_WIDTH'(square32($signed(replay_data[lane*32+:32])))*COMPARE_WIDTH'(features))<<16)>COMPARE_WIDTH'(denominator)*160'd9;" in rtl,
            'current RTL exact denominator and pre-round mask expressions')
    historical = ast.parse(sources[str(HISTORICAL)][0])
    outliers = [n for n in ast.walk(historical) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'outliers' for t in n.targets)]
    require(len(outliers) == 1 and ast.unparse(outliers[0].value) == 'norm_codes.abs() > 768',
            'historical policy tests rounded Q8 codes')
    module = types.ModuleType('synthetic_exact_current_C_cpu')
    module.__file__ = str(API)
    exec(compile(sources[str(API)][0], str(API), 'exec'), module.__dict__)
    # M rows are initialized solely from this declared fixture, never a file.
    cases = [('boundary', 3000000, 998000), ('below', 3000000, 1000000),
             ('above', 3000000, 997000)]
    raw = []
    labels = []
    for name, leading, background in cases:
        for sign in (1, -1):
            raw.append([sign*leading] + [sign*background]*(H-1))
            labels.append((name, sign))
    require(all(len(row) == H and all(-(1 << 31) <= v < (1 << 31) for v in row)
                for row in raw), 'feasible signed32[6,2048] vectors')
    gains = [1]*H
    actual = module.normalize24_cpu(raw, gains, [0]*len(raw), [0]*len(raw))
    require(actual['error_codes'] == [0]*len(raw), 'actual fixed-word CPU path accepts all six')
    records = []
    for index, (row, (name, sign)) in enumerate(zip(raw, labels)):
        energy = sum(v*v for v in row)
        require(energy > 0, 'positive mean-square denominator')
        q8 = [rounded_q8(v, energy) for v in row]
        exact_mask = [v*v*H > 9*energy for v in row]
        rounded_mask = [abs(v) > 768 for v in q8]
        # This is the literal RTL formula including its Q16 denominator scale.
        denominator_q16 = energy << 16
        rtl_mask = [(v*v*H << 16) > 9*denominator_q16 for v in row]
        require(actual['outlier_mask'][index] == rtl_mask == exact_mask,
                'all2048 current CPU masks equal literal RTL and independent integers')
        expected_code = {'boundary': 768, 'below': 767, 'above': 769}[name]*sign
        require(q8[0] == expected_code, 'independent exact rounded-Q8 first lane')
        require(sum(exact_mask) == int(name != 'below'), 'pre-round outlier count')
        require(sum(rounded_mask) == int(name == 'above'), 'post-round outlier count')
        require([i for i, (a, b) in enumerate(zip(exact_mask, rounded_mask)) if a != b]
                == ([0] if name == 'boundary' else []), 'exact mismatch lane set')
        squared_numerator = row[0]**2 * H
        lower_margin = squared_numerator - 9*energy
        upper_margin = 1537**2*energy - 512**2*squared_numerator
        if name == 'boundary':
            require(lower_margin > 0 and upper_margin > 0,
                    'integer squared proof:3 < |normalized first lane| <3+1/512')
            require(4*squared_numerator*256**2 < 1537**2*energy,
                    'strictly below Q8 code768/769 halfway boundary')
        records.append(dict(name=name, sign=sign, raw_first=row[0], raw_background=row[1],
            hidden_features=H, energy=energy, epsilon_q16=0, gain=1, gamma_exponent=0,
            squared_normalized_numerator=squared_numerator,
            squared_normalized_denominator=energy,
            above_three_squared_positive_margin=lower_margin,
            below_three_plus_one_over512_squared_positive_margin=upper_margin,
            independent_Q8_first=q8[0], independent_Q8_background=q8[1],
            current_CPU_activation_first=actual['codes'][index][0],
            current_CPU_activation_exponent=actual['activation_exponent'][index],
            current_pre_round_outlier_count=sum(exact_mask),
            historical_rounded_Q8_outlier_count=sum(rounded_mask),
            mismatch_lanes=[i for i,(a,b) in enumerate(zip(exact_mask,rounded_mask)) if a!=b],
            raw_sha256=hashlib.sha256(struct.pack('<2048i', *row)).hexdigest(),
            current_mask_sha256=hashlib.sha256(bytes(exact_mask)).hexdigest(),
            rounded_Q8_mask_sha256=hashlib.sha256(bytes(rounded_mask)).hexdigest()))
    for positive in (0, 2, 4):
        negative = positive+1
        require(actual['outlier_mask'][positive] == actual['outlier_mask'][negative], 'sign-symmetric mask')
        require(actual['codes'][negative] == [-v for v in actual['codes'][positive]], 'sign-symmetric activation codes')
        require(actual['outlier_negative'][positive] == [False]*H
                and actual['outlier_negative'][negative] == actual['outlier_mask'][negative],
                'actual negative-plane symmetry')
    require(not ({'torch', 'numpy'} & set(sys.modules)), 'stdlib-only execution')
    for path, (_, before) in sources.items():
        require(closed(Path(path))[1] == before, 'source unchanged after synthetic execution')
    result = dict(schema='synthetic_feasible_integer_three_sigma_policy_boundary_probe_v1',
        source_records={p: row for p, (_, row) in sources.items()},
        resource_limits=dict(address_space_bytes=128 << 20, CPU_seconds=30),
        synthetic_cases=records, signed32_lane_values_checked=H*len(raw),
        current_fixedword_CPU_rows_executed=len(raw), current_fixedword_CPU_calls=1,
        independent_integer_squared_proofs=True, all_sign_and_below_above_controls_passed=True,
        current_pre_round_vs_historical_post_round_policy_difference_proved=True,
        historical_torch_reference_executed=False, actual_RTL_executed=False,
        original_trained_data_reads=0, GPU_or_model_or_native_calls=0,
        trained_incidence_verified=False, task_accuracy_effect_verified=False,
        original_failure_cause_verified=False, full_model_equivalence_verified=False,
        paper300_release_allowed=False, elapsed_seconds=time.monotonic()-started)
    out = (ROOT / '.cache/tri_oracle_three_sigma_boundary_v1.json' if len(sys.argv) == 1
           else Path(sys.argv[2]).resolve())
    require(out.is_relative_to(ROOT / '.cache') and out.parent.is_dir(),
            'fresh result under this project cache required')
    encoded = (json.dumps(result, indent=2, sort_keys=True)+'\n').encode()
    with out.open('xb') as stream:
        stream.write(encoded)
    print(json.dumps(dict(result_path=str(out), result_sha256=hashlib.sha256(encoded).hexdigest(),
                          rows=len(raw), synthetic_exit=0)))


if __name__ == '__main__':
    main()
