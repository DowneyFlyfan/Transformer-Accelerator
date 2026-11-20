"""Host-only exhaustive shift-domain check of the frozen 22-layer reference.

This checks format representability. It does not execute a model, change a
policy, prove mapped arithmetic, or qualify accuracy or physical implementation.
"""
if not __debug__:
    raise RuntimeError('Verification requires assertions')

from fractions import Fraction
from hashlib import file_digest
from pathlib import Path
from types import SimpleNamespace
import argparse,ast,json,math,shutil,time

ROOT=Path.cwd().resolve()
WORK=ROOT/'.cache/channel_scale_integration_20261120'
DATA=ROOT/'.cache/model_reference'
MODEL=DATA/'tiny_llava_v1'

def sha(path):
    with path.open('rb') as f:return file_digest(f,'sha256').hexdigest()

def available():
    return next(int(s.split()[1])*1024 for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:'))

def exponent_for_maximum(value):
    if value==0:return 0
    mantissa,exponent=math.frexp(value)
    return exponent-7+int(mantissa>127/128)

def case(gate_exponent,up_exponent,down_exponents,activation_exponent,gain_cap,offset):
    gate_shift=-(activation_exponent+gate_exponent+8)
    original_up=-(activation_exponent+up_exponent+8)
    gain=min(original_up,gain_cap)
    up_shift=original_up-gain
    down_shift=max(0,gain+offset)
    if not all(0<=s<=63 for s in (gate_shift,up_shift,down_shift)):return None
    base=max(down_exponents)+18+down_shift-gain
    deltas=[max(down_exponents)-e for e in down_exponents]
    return dict(gate_shift=gate_shift,up_shift=up_shift,down_shift=down_shift,gain=gain,
        base_shift=base,decrements=deltas,lane_shifts=[base-d for d in deltas],
        representable=0<=base<=31 and max(deltas)<=7 and min(base-d for d in deltas)>=0)

def source_exponent_expression():
    tree=ast.parse((ROOT/'syn/tri_oracle_integer_reference.py').read_text())
    klass,=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='IntegerFeedForwardReference']
    function,=[n for n in klass.body if isinstance(n,ast.FunctionDef) and n.name=='evaluate']
    assignment,=[n for n in function.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='values' for t in n.targets)]
    call=assignment.value
    assert isinstance(call,ast.Call) and ast.unparse(call.func)=='torch.ldexp' and len(call.args)==2
    return compile(ast.Expression(call.args[1]),'<frozen source exponent>','eval')

def read_headers(index):
    result={}
    for shard in set(index.values()):
        with (MODEL/shard).open('rb') as f:
            length=int.from_bytes(f.read(8),'little');header=json.loads(f.read(length))
        result[shard]=(8+length,header)
    return result

def checkpoint_row_exponents(key,index,headers):
    # The source tensor has shape [R,C], R output rows, C incoming features.
    # Read at most 128 rows; every temporary is [B,C], B<=128, or [B].
    import numpy as np
    shard=index[key];start,header=headers[shard];item=header[key]
    assert item['dtype']=='F32' and len(item['shape'])==2
    rows,columns=item['shape'];begin,end=item['data_offsets']
    assert end-begin==4*rows*columns
    maxima=[]  # [R], exact per-row float32 maxima; initialized from checkpoint.
    with (MODEL/shard).open('rb') as f:
        f.seek(start+begin)
        for first in range(0,rows,128):
            assert available()>=8.5*2**30,'Yield to the native job before allocating a weight chunk'
            count=min(128,rows-first)
            payload=f.read(count*columns*4)
            assert len(payload)==count*columns*4
            values=np.frombuffer(payload,dtype='<f4').reshape(count,columns)  # [B,C], zero-copy checkpoint view.
            assert np.isfinite(values).all()
            maxima.extend(np.abs(values).max(axis=1).tolist())  # [B] per-read, concatenated to [R].
    return [exponent_for_maximum(v) for v in maxima],exponent_for_maximum(max(maxima))

def main(output):
    output=output.resolve()
    assert output.is_relative_to(ROOT/'.cache')
    assert not Path('/.dockerenv').exists() and not output.exists()
    assert available()>=10*2**30 and shutil.disk_usage(WORK).free>=20*2**30
    started=time.monotonic();inputs={}
    receipt_path=DATA/'gqa_testdev/full_calibrated_clip/receipt.json'
    full_path=DATA/'gqa_testdev/full_calibrated_clip/inputs.json'
    receipt=json.loads(receipt_path.read_text());assert sha(full_path)==receipt['inputs_sha256']=='a332fd6e1403b202b8080b08138de61b8585e9afa95a71cccaccaad405e8b3f9'
    full=json.loads(full_path.read_text());anchors=full['input_sha256']
    def pin(path,expected=None):
        key=str(path.relative_to(ROOT));value=sha(path)
        if expected is not None:assert value==expected,('Input changed',key)
        if str(path) in anchors:assert anchors[str(path)]==value,('Frozen accuracy input changed',key)
        inputs[key]=value;return path
    pin(full_path);pin(receipt_path)
    sources=['syn/tri_oracle_integer_reference.py','syn/tri_oracle_format335_policy.py','syn/tri_oracle_format345_first_token.py',
             'syn/evaluate_tri_oracle_batch424_joint_pilot.py','.cache/model_reference/gqa_testdev/calibrated_clip_workflow/combined.py']
    for name in sources:assert str(ROOT/name) in anchors;pin(ROOT/name)
    first_path=pin(DATA/'format322/layer_policy.json');ordinary_path=pin(DATA/'format335/layer_policy.json')
    first=json.loads(first_path.read_text())['layers'];ordinary=json.loads(ordinary_path.read_text())['layers']
    assert len(first)==len(ordinary)==22
    pairs_path=pin(DATA/'packed_gate_up_export/v1/manifest.json');down_path=pin(DATA/'packed_down_export/v1/manifest.json')
    pairs={(r['layer'],r['branch']):r for r in json.loads(pairs_path.read_text())['matrices']}
    downs={r['layer']:r for r in json.loads(down_path.read_text())['layers']}
    index_path=pin(MODEL/'model.safetensors.index.json');index=json.loads(index_path.read_text())['weight_map']
    for shard in set(index.values()):
        expected=anchors.get(str(MODEL/shard),json.loads(pairs_path.read_text())['evidence_sha256'].get(str((MODEL/shard).relative_to(ROOT))))
        assert expected is not None;pin(MODEL/shard,expected)
    headers=read_headers(index);expression=source_exponent_expression()
    # Loading codebook metadata uses mapped CPU storage only. No GPU context or
# model is created. Codes remain [2048,5632]; scales are [2048,1].
    import torch
    torch.set_num_threads(1)
    fit_path=pin(WORK/'all22_scale_table_fit.json');fits=json.loads(fit_path.read_text())['layers']
    all_rows=[];valid=excluded=0;lane_min=100;base_max=-100;maximum_delta=0
    for layer in range(22):
        gate_key=pairs[layer,'gate']['checkpoint_key'];up_key=pairs[layer,'up']['checkpoint_key'];down_key=downs[layer]['checkpoint_key']
        _,eg=checkpoint_row_exponents(gate_key,index,headers)
        _,eu=checkpoint_row_exponents(up_key,index,headers)
        ed_rows,ed_global=checkpoint_row_exponents(down_key,index,headers)  # [2048] per-output exponents and one global exponent.
        assert eg==pairs[layer,'gate']['scale_exponent'] and eu==pairs[layer,'up']['scale_exponent'] and ed_global==downs[layer]['scale_exponent']
        book_path=pin(DATA/f'gqa_testdev/down_code_calibration_export/codes/down_{layer:02}.pt',fits[layer]['codebook_sha256'])
        assert str(book_path) in anchors
        book=torch.load(book_path,weights_only=True,map_location='cpu',mmap=True)
        assert book['codes'].dtype==torch.int8 and tuple(book['codes'].shape)==(2048,5632)
        assert book['scale'].dtype==torch.int32 and tuple(book['scale'].shape)==(2048,1)
        assert book['scale'][:,0].tolist()==ed_rows
        table_path=pin(WORK/f'tables/layer_{layer:02}.bin',fits[layer]['binary_sha256']);table=table_path.read_bytes();assert len(table)==1024
        deltas=[max(ed_rows)-e for e in ed_rows]
        for word in range(128):
            bits=int.from_bytes(table[8*word:8*word+8],'little');assert bits>>48==0
            assert [(bits>>(3*k))&7 for k in range(16)]==deltas[16*word:16*word+16]
        maximum_delta=max(maximum_delta,max(deltas))
        summary=dict(layer=layer,gate_exponent=eg,up_exponent=eu,global_down_exponent=ed_global,per_output_down_range=[min(ed_rows),max(ed_rows)],policies={})
        for kind,policy in [('first_global',first[layer]),('ordinary_per_output',ordinary[layer])]:
            assert policy['layer']==layer
            table_policy={r['activation_exponent']:r for r in policy.get('buckets',[])}
            assert len(table_policy)==len(policy.get('buckets',[]))
            domain=[]
            # gate_shift=-(activation_exponent+gate_exponent+8) in [0,63]
            # is equivalent to this exact finite set of 64 activation exponents.
            # All actual accepted reference states are a subset of this set.
            for gate_shift in range(64):
                activation_exponent=-eg-8-gate_shift
                setting=policy if kind=='first_global' else table_policy.get(activation_exponent,policy['fallback'])
                exponents=[ed_global] if kind=='first_global' else sorted(set(ed_rows))
                row=case(eg,eu,exponents,activation_exponent,setting['maximum_up_gain_bits'],setting['down_shift_offset'])
                if row is None:excluded+=1;continue
                assert row['representable'],(layer,kind,activation_exponent,row)
                for exponent,shift in zip(exponents,row['lane_shifts']):
                    software=eval(expression,{'__builtins__':{}},{'self':SimpleNamespace(down_exponent=exponent),'down_shift':row['down_shift'],'gain':row['gain']})
                    assert Fraction(2)**software==(Fraction(2)**shift)/2**26
                domain.append(dict(activation_exponent=activation_exponent,**row));valid+=1
                lane_min=min(lane_min,min(row['lane_shifts']));base_max=max(base_max,row['base_shift'])
            assert domain
            summary['policies'][kind]=dict(valid_states=len(domain),base_shift_range=[min(v['base_shift'] for v in domain),max(v['base_shift'] for v in domain)],
                lane_shift_range=[min(min(v['lane_shifts']) for v in domain),max(max(v['lane_shifts']) for v in domain)],negative_gain_states=sum(v['gain']<0 for v in domain),cases=domain)
        all_rows.append(summary)
        print('SCALE_DOMAIN_LAYER_VERIFIED',layer,flush=True)
    # Source accumulation length bounds cover primary+correction raw sums.
    assert 2*5632*128*128<2**31
    for name,wanted in inputs.items():assert sha(ROOT/name)==wanted,name
    output.parent.mkdir(parents=True,exist_ok=True)
    result=dict(state='frozen_22_layer_scale_domain_representable',valid_reference_format_states=valid,excluded_reference_invalid_shift_states=excluded,
        enumerated_gate_states=22*2*64,minimum_lane_shift=lane_min,maximum_base_shift=base_max,maximum_table_decrement=maximum_delta,
        full_reference_inputs_sha256=sha(full_path),elapsed_seconds=time.monotonic()-started,layers=all_rows,
        candidate_functional_execution=False,full_model_accuracy_qualification=False,paper_matching=False,routing_release=False,
        scope='All activation exponent states accepted by the current scalar/reference shift limits, under frozen first/ordinary policy selection. First/global and ordinary/per-output weight scales are independently recomputed from checkpoint weights. Not mapped execution or equivalence of rounding/saturation to the floating model.',
        source_sha256=sha(Path(__file__)),input_sha256=inputs)
    output.write_text(json.dumps(result,indent=2)+'\n')
    print('ALL22_SCALE_DOMAIN_PASS',valid,'lane_min',lane_min,'base_max',base_max,'elapsed',result['elapsed_seconds'],flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=WORK/'all22_scale_domain_verified.json')
    main(parser.parse_args().output)
