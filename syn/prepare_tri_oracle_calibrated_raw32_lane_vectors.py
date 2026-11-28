"""Regenerate the standalone calibrated raw32 lane's exact synthetic vectors.

Run from the project: python3 -B syn/prepare_tri_oracle_calibrated_raw32_lane_vectors.py
Optional: --output PATH, restricted to a fresh file under this project's .cache.
The matching testbench top is scaled_lane_tb_v1; pass +vectors=ABSOLUTE_HEX_PATH.
This standard-library generator uses no implementation, trained values, model,
graphics processor or simulator. It covers only an isolated arithmetic lane.
"""
from pathlib import Path
import hashlib
import json
import resource
import struct
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
H = 2048
INT_MAX = 2147483647
A1 = 5632*128*128
DOWN_MAX = A1
BASES = (-19,-17,-16,-15,-14,-13,-12,-11,-8,-6)
BASE_UNITS = BASES
EXPECTED_COUNT = 93376
EXPECTED_BYTES = 11298496
EXPECTED_SHA256 = 'b9f237077a8ca729d1bf93a93c35aa514bf022c0bbc0079e30ffe4672b3c4b82'
EXPECTED_ROW_CODES_SHA = {'all_delta0_scalar_equivalence_-15': '173f20b1252fc9332c177bc4a7970272f37fe92d6bd886a4892ecb9aabe3f269', 'all_delta0_scalar_equivalence_-32': '5349966dabc68a68e803522ee9a8ba2201584c860725a99295da4cd50bee8d55', 'all_delta0_scalar_equivalence_0': 'cdd0cbd636bbd03a30f51ec325d297091efb67c5fb1b118b3311d09db8bcd4e5', 'all_delta0_scalar_equivalence_97': 'ab8cdb2fca88844e808f37b49a1ed95e1f6e4a5f83c93fffb3e5c5a622932b69', 'allones_peak_plus_nonzero_sticky_tail': '2b14a5684d411c8871b04b30a028b363bcb26ee7873cc6eee3e2ad006594d975', 'full_domain_width_delta0': '13c53066e1a8e49cc96a74fc71cd624339b33e4d25e2a60444c7e8f0c32510f2', 'full_domain_width_delta5': '13c53066e1a8e49cc96a74fc71cd624339b33e4d25e2a60444c7e8f0c32510f2', 'full_domain_width_delta7': '13c53066e1a8e49cc96a74fc71cd624339b33e4d25e2a60444c7e8f0c32510f2', 'physical_peak_not_largest_native_code': '0787ef9493bb585f45b77d71c043438d61a401e513bf59c147565783d9d0ce95', 'same_table_token_A_small_peak': 'c279bc901b73690396cecfc329a6a711e7ba042e2b91b1b24a39a89e682144ab', 'same_table_token_B_large_peak': '2f5e00bd25bd8226dd60fd115ab4a0f0bc9f7cb4539cd7f699070ebfd661c49f', 'sign_cancellation_halfway_boundary_positions': '45f646da884b5e89b8e6140254ea6506b416235981f8c0d3e157b72c0f7b8e35', 'zero_residual_and_DOWN_force_unit0': '9f1dcbc35c350d6027f98be0f5c8b43b42ca52b7604459c0c42be3aa88913d47'}


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def half_away_integer(numerator, denominator):
    """Signed exact rational scalar -> nearest integer, midpoint away from zero."""
    need(type(numerator) is int and type(denominator) is int and denominator > 0, 'integer ratio')
    magnitude, remainder = divmod(abs(numerator), denominator)
    magnitude += int(2*remainder >= denominator)
    return -magnitude if numerator < 0 else magnitude


def epsilon_for(unit):
    return half_away_integer(1 << (16-2*unit), 100000) if unit <= 0 else 0


def recode(values, common):
    """Exact aligned integer[H] and scalar common unit -> one row unit/codes."""
    peak = max(map(abs, values))
    if peak == 0:
        selected = 0
    else:
        selected = None
        for unit in range(-32, 98):
            shift = unit-common
            fits = peak <= INT_MAX << shift if shift >= 0 else peak << (-shift) <= INT_MAX
            if fits:
                selected = unit
                break
        if selected is None:
            raise OverflowError('no symmetric signed32 output unit in-32..97')
    shift = selected-common
    codes = [half_away_integer(v, 1 << shift) if shift >= 0 else v << (-shift) for v in values]
    need(all(abs(v) <= INT_MAX for v in codes), 'symmetric signed32 final codes; no saturation')
    return dict(common_unit=common, peak=peak, selected_unit=selected,
                epsilon_q16=epsilon_for(selected), codes=codes)


def align_row(raw, down, raw_unit, down_base_unit, deltas):
    """Independent common-unit integer reference; no rounding of either operand."""
    need(len(raw) == len(down) == len(deltas) == H, 'three full output vectors')
    need(type(raw_unit) is int and -32 <= raw_unit <= 97, 'raw unit domain')
    need(type(down_base_unit) is int and down_base_unit in BASE_UNITS, 'current base DOWN unit domain')
    need(all(type(v) is int and abs(v) <= INT_MAX for v in raw), 'symmetric signed32 raw')
    need(all(type(v) is int and abs(v) <= DOWN_MAX for v in down), 'signed native dot bound')
    need(all(type(v) is int and 0 <= v <= 7 for v in deltas), 'per-output delta0..7')
    common = min(raw_unit, down_base_unit-max(deltas))
    values = [(r << (raw_unit-common)) + (d << (down_base_unit-delta-common))
              for r, d, delta in zip(raw, down, deltas)]
    answer = recode(values, common)
    answer['aligned'] = values
    answer['minimum_signed_width'] = max(1, max((abs(v).bit_length()+1 if v >= 0 else (~v).bit_length()+1) for v in values))
    return answer


def lane_reference(raw, down, raw_unit, base, maximum, lane, correction):
    """Known scalar public inputs -> bad/common/lane/exact/magnitude integers.

    A maximum delta belongs to the authenticated full output table. It can
    exceed this lane's delta; no token/root/address can index the delta instead.
    """
    values = (raw,down,raw_unit,base,maximum,lane,correction)
    valid = all(type(v) is int for v in values)
    valid = valid and -INT_MAX <= raw <= INT_MAX and -32 <= raw_unit <= 97
    valid = valid and base in BASES and 0 <= lane <= maximum <= 7 and correction in (0,1)
    valid = valid and abs(down) <= A1*(1+correction)
    if not valid:
        return (1,0,0,0,0)
    common = min(raw_unit,base-maximum)
    unit = base-lane
    exact = raw*(2**(raw_unit-common)) + down*(2**(unit-common))
    need(-(1 << 154) <= exact < (1 << 154), 'declared signed155 domain')
    return (0,common,unit,exact,abs(exact))


def row_fixtures():
    """Reconstruct only the thirteen already accepted synthetic row recipes."""
    raw = [(j % 7)-3 for j in range(H)]
    down = [(j % 19)-9 for j in range(H)]
    for raw_unit, unit in [(-32,-19),(-15,-17),(0,-6),(97,-19)]:
        yield 'all_delta0_scalar_equivalence_'+str(raw_unit), [0]*H if raw_unit==97 else raw[:], down[:], raw_unit,unit,[0]*H
    r,d,ds = [0]*H,[0]*H,[0]*H
    r[0] = INT_MAX
    placements = [7,8,15,16,31,32,63,64,159,160,191,192,1999,2047]
    triples = [(1,-1,1),(1,-3,2),(1,-1,2),(-1,1,1),(-1,3,2),(-1,1,2),
               (1,-2,1),(-1,2,1),(1,-127,7),(-1,127,7),(1,-33,6),(-1,33,6),(0,1,7),(0,-1,7)]
    for j,(rv,dv,delta) in zip(placements,triples):
        r[j],d[j],ds[j] = rv,dv,delta
    yield 'sign_cancellation_halfway_boundary_positions',r,d,-19,-19,ds
    r,d,ds = [0]*H,[0]*H,[0]*H
    d[0],ds[0],d[1] = A1,7,1000000
    yield 'physical_peak_not_largest_native_code',r,d,-32,-19,ds
    r,d,ds = [0]*H,[0]*H,[0]*H
    r[15],d[15],ds[15] = INT_MAX,1,7
    yield 'allones_peak_plus_nonzero_sticky_tail',r,d,-19,-19,ds
    d = [0]*H
    d[0] = 1
    yield 'same_table_token_A_small_peak',[0]*H,d,-32,-17,[j%8 for j in range(H)]
    d = [0]*H
    d[0] = 1000000
    yield 'same_table_token_B_large_peak',[0]*H,d,-19,-17,[j%8 for j in range(H)]
    for maximum in (0,5,7):
        r,d,ds = [0]*H,[0]*H,[maximum]*H
        r[0],d[1],ds[1] = INT_MAX,A1,0
        yield 'full_domain_width_delta'+str(maximum),r,d,97,-19,ds
    ds = [7]*H
    ds[0] = 0
    yield 'zero_residual_and_DOWN_force_unit0',[0]*H,[0]*H,97,-19,ds


def main():
    need(__debug__ and sys.dont_write_bytecode and
         (len(sys.argv)==1 or (len(sys.argv)==3 and sys.argv[1]=='--output')),
         'ordinary Python-B with optional --output')
    resource.setrlimit(resource.RLIMIT_AS,(128 << 20,128 << 20))
    resource.setrlimit(resource.RLIMIT_CPU,(30,30))
    started = time.monotonic()
    output = ((ROOT/'.cache/tri_oracle_calibrated_raw32_lane_vectors_v1/scaled_lane_vectors_v1.hex')
              if len(sys.argv)==1 else Path(sys.argv[2])).resolve()
    need(output.is_relative_to(ROOT/'.cache'), 'output must remain in project .cache')
    target = output.with_suffix('.manifest.json')
    need(not output.exists() and not target.exists(), 'fresh vector and manifest required')
    output.parent.mkdir(parents=True,exist_ok=True)
    count = valid = invalid = scalar_equal = wide148 = 0
    digest = hashlib.sha256()
    categories = {}
    examples = {}
    widths = (32,32,8,12,3,3,1,1,9,12,155,155)
    digits = (8,8,2,3,1,1,1,1,3,3,39,39)
    with output.open('xb') as stream:
        def emit(category, inputs, expectation=None):
            nonlocal count,valid,invalid,scalar_equal,wide148
            answer = lane_reference(*inputs)
            if expectation is not None:
                need(answer==expectation,'independent fullrow vs scalar lane')
            if answer[0]:
                invalid += 1
                need(answer==(1,0,0,0,0),'all rejected numeric outputs zero')
            else:
                valid += 1
                if inputs[4]==0:
                    common = min(inputs[2],inputs[3])
                    scalar = inputs[0]*(2**(inputs[2]-common))+inputs[1]*(2**(inputs[3]-common))
                    need(answer[1]==common and answer[2]==inputs[3] and answer[3]==scalar,'D0 old scalar equality')
                    scalar_equal += 1
                if not -(1 << 147) <= answer[3] < (1 << 147):
                    wide148 += 1
                    if len(examples)<8:
                        examples[str(count)] = dict(inputs=list(inputs),expected=list(answer))
            values = inputs+answer
            encoded = (' '.join(format(v&((1<<w)-1),'0'+str(d)+'x') for v,w,d in zip(values,widths,digits))+'\n').encode()
            stream.write(encoded)
            digest.update(encoded)
            count += 1
            categories[category] = categories.get(category,0)+1

        for name,raw,down,raw_unit,unit,deltas in row_fixtures():
            full = align_row(raw,down,raw_unit,unit,deltas)
            codes_hash = hashlib.sha256(struct.pack('<2048i',*full['codes'])).hexdigest()
            need(codes_hash==EXPECTED_ROW_CODES_SHA[name],'exact accepted thirteen-row fixture recipe '+name)
            maximum = max(deltas)
            for j in range(H):
                expect = (0,full['common_unit'],unit-deltas[j],full['aligned'][j],abs(full['aligned'][j]))
                emit('accepted_13rows_all2048lanes',(raw[j],down[j],raw_unit,unit,maximum,deltas[j],0),expect)
        # Full raw/base/max/correction endpoint envelopes, three signed tuples
        # per state. Include positive/negative raw and DOWN exact endpoints.
        for raw_unit in range(-32,98):
            for unit in BASES:
                for maximum in range(8):
                    for correction in (0,1):
                        bound = A1*(1+correction)
                        emit('all_unit_endpoint_envelopes',(INT_MAX,bound,raw_unit,unit,maximum,0,correction))
                        emit('all_unit_endpoint_envelopes',(-INT_MAX,-bound,raw_unit,unit,maximum,maximum,correction))
                        emit('all_unit_endpoint_envelopes',(INT_MAX,-bound,raw_unit,unit,maximum,maximum,correction))
        # Exercise every legal max/lane pair at the two raw-unit endpoints.
        for raw_unit in (-32,97):
            for unit in BASES:
                for maximum in range(8):
                    for lane in range(maximum+1):
                        for correction in (0,1):
                            emit('every_legal_max_lane_pair',(1,-1,raw_unit,unit,maximum,lane,correction))
        # Known invalid boundary values, always all-zero numeric rejection.
        for unit in BASES:
            for maximum in range(8):
                for correction in (0,1):
                    bound = A1*(1+correction)
                    for sign in (-1,1):
                        emit('DOWN_one_beyond_selected_A1_A2',(0,sign*(bound+1),-32,unit,maximum,maximum,correction))
                    for raw_unit in (-32,97):
                        for lane in (0,maximum):
                            emit('raw_INTMIN_rejected',(-(1<<31),0,raw_unit,unit,maximum,lane,correction))
                    for raw_unit in (-128,-33,98,127):
                        emit('raw_unit_outside_domain',(0,0,raw_unit,unit,maximum,0,correction))
        for unit in (-2048,-20,-18,-7,0,2047):
            for raw_unit in (-32,97):
                for maximum in range(8):
                    for correction in (0,1):
                        emit('base_unit_not_in_enum',(0,0,raw_unit,unit,maximum,0,correction))
        for unit in BASES:
            for maximum in range(8):
                for lane in range(maximum+1,8):
                    for correction in (0,1):
                        for raw_unit in (-32,97):
                            emit('lane_delta_exceeds_table_maximum',(0,0,raw_unit,unit,maximum,lane,correction))
    need(count==EXPECTED_COUNT and valid+invalid==count,'exact frozen vector census')
    need(scalar_equal>0 and wide148>0,'nonvacuous scalar equality and148overflow witnesses')
    need(not ({'torch','numpy'}&set(sys.modules)),'stdlib only')

    need(digest.hexdigest()==EXPECTED_SHA256 and output.stat().st_size==EXPECTED_BYTES,
         'exact qualified synthetic-vector bytes and digest')
    manifest = dict(schema='public_calibrated_raw32_lane_synthetic_vectors_v1',
        generator_sha256=hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest(),
        vector_path=str(output),vector_sha256=digest.hexdigest(),
        vector_bytes=output.stat().st_size,vector_count=count,valid_vectors=valid,
        invalid_vectors=invalid,categories=categories,known_scalar_D0_equalities=scalar_equal,
        exact_sum_outside_signed148_vectors=wide148,
        input_fields=['raw_value_s32','down_value_s32','raw_unit_s8','base_down_unit_s12',
                      'maximum_decrement_u3','lane_decrement_u3','correction_enable_u1'],
        expected_fields=['bad_u1','common_unit_s9','lane_unit_s12','exact_sum_s155','magnitude_u155'],
        hex_digits=list(digits),unknown_X_Z_tests_in_testbench=182,
        limits=dict(address_space_bytes=128 << 20,CPU_seconds=30),
        model_GPU_native_or_trained_payload_calls=0,full_consumer_qualified=False,
        trained_execution_qualified=False,paper300_release_allowed=False,
        elapsed_seconds=time.monotonic()-started)
    encoded=(json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode()
    with target.open('xb') as stream:
        stream.write(encoded)
    print(json.dumps(dict(manifest_path=str(target),vector_sha256=digest.hexdigest(),
                          vector_count=count,valid=valid,invalid=invalid,synthetic_exit=0)))


if __name__=='__main__':
    main()
