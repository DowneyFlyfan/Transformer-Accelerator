"""Test reciprocal Up/Down weight balancing in the current integer formats.

M=240 archived ordinary rows, F=120 fit rows, E=120 reused diagnostic rows;
H=O=2048 hidden features, K=5632 intermediate channels. No answer labels,
gradient training, optimizer, new runtime scale fields or mapped-execution claim.
"""
if not __debug__:raise RuntimeError('Equalization verification requires assertions')
from copy import copy
from hashlib import file_digest
import importlib.util,json,resource,time
from pathlib import Path
import torch
import torch.nn.functional as functional
from safetensors import safe_open
from tri_oracle_integer_reference import IntegerFeedForwardReference,_quantize,_dot,_requantize
from tri_oracle_format335_policy import evaluate_policy


def channel_powers(up,down):
    """Caller finite floating Up[K,H], effective calibrated Down[O,K].
    a/b[K] are absolute row/column maxima; valid[K] marks contributing channels.
    balance[K] is the centered half log-range difference. Return powers[K]
    signed32, rounded and clamped to -2..2; weights alone select these powers.
    """
    if up.ndim!=2 or down.ndim!=2 or down.shape[1]!=up.shape[0]:raise ValueError('Weight shapes differ')
    if not up.is_floating_point() or not down.is_floating_point() or up.device!=down.device:
        raise ValueError('Finite floating weights on one device required')
    if not bool(torch.isfinite(up).all()&torch.isfinite(down).all()):raise ValueError('Weights must be finite')
    a=up.abs().amax(1);b=down.abs().amax(0);valid=(a>0)&(b>0)
    powers=torch.zeros_like(a,dtype=torch.int32)
    if bool(valid.any()):
        balance=.5*(torch.log2(b[valid])-torch.log2(a[valid]))
        powers[valid]=(balance-balance.mean()).round().clamp(-2,2).to(torch.int32)
    return powers


def reciprocal_weights(up,down,powers):
    """Caller Up[K,H], Down[O,K], integer powers[K] produce same-shape floats.
    Positive S=diag(2**powers) gives Up'=S*Up and Down'=Down*S^-1.
    Gate and input are unchanged, so floating SwiGLU output is preserved.
    """
    if up.ndim!=2 or down.ndim!=2 or down.shape[1]!=up.shape[0] or powers.shape!=(up.shape[0],):
        raise ValueError('Reciprocal weight shapes differ')
    if powers.dtype!=torch.int32 or powers.device!=up.device or down.device!=up.device or not bool(((powers>=-2)&(powers<=2)).all()):
        raise ValueError('Bounded integer channel powers required')
    return torch.ldexp(up,powers[:,None]),torch.ldexp(down,-powers[None,:])


def metrics(values,target):
    """Caller outputs/targets[N,O], N=F or E; double error[N,O], norm[N].
    Return scalar mean row-relative error, used on F for binary selection only.
    Original captured floating targets are never supplied to channel_powers.
    """
    error=values.double()-target.double();norm=target.double().norm(dim=1).clamp_min(1e-20)
    result=float((error.norm(dim=1)/norm).mean())
    assert result>=0 and bool(torch.isfinite(error).all())
    return result


def evaluate_pair(reference,activation,residual,policy,late):
    """Caller reference codes Gate/Up[K,H],Down[O,K], exponents scalar/[1,O].
    activation/residual[M,H] and frozen scalar policy give raw/values[M,O],
    stats norm_codes[M,H] and remaining stats[M]. All recreated integer gate,
    up,gated,wide,coarse,delta/skip tensors have[M,K]; signs/codes[M,H],
    exponent/shift/gain[M,1]. Both physical outputs[M,O] share exact current
    formats. Three 2-by-8 integer-dot subsets are independently checked in double.
    """
    raw,values,stats=evaluate_policy(reference,activation,residual,policy,prune=False)
    codes,exponent=_quantize(activation,per_row=True)
    gate_dot=_dot(codes,reference.gate);up_dot=_dot(codes,reference.up)
    for actual,weight in ((gate_dot,reference.gate),(up_dot,reference.up)):
        assert torch.equal(actual[:2,:8].long(),(codes[:2].double()@weight[:8].double().T).long())
    gate=_requantize(gate_dot,stats['gate_shift'][:,None],16)
    up=_requantize(up_dot,stats['up_shift'][:,None],16)
    gated=_requantize(reference.silu_response[gate+32768]*up,torch.full_like(exponent,8),16)
    shift=stats['down_shift'][:,None];gain=stats['up_gain_bits'][:,None]
    wide=_requantize(gated,shift,16);coarse=wide.clamp(-128,127).to(torch.int8)
    delta=(wide-coarse.to(torch.int64)).clamp(-128,127).to(torch.int8) if late else torch.zeros_like(coarse)
    signs=(torch.where(stats['norm_codes']<0,-1,1)*(stats['norm_codes'].abs()>768)).to(torch.int8)
    skip=(stats['outlier_count'][:,None]>0)&(_dot(signs,reference.gate_sign)<=0)&(_dot(signs,reference.up_sign)==0)
    assert torch.equal(skip.sum(1,dtype=torch.int32),stats['skip_count'])
    base=_dot(coarse,reference.down);assert torch.equal(base,raw)
    assert torch.equal(base[:2,:8].long(),(coarse[:2].double()@reference.down[:8].double().T).long())
    assert reference.channels*2*128*128<2**31
    dense=base+_dot(delta,reference.down)
    pruned=_dot(coarse.masked_fill(skip,0),reference.down)+_dot(delta.masked_fill(skip,0),reference.down)
    scale=reference.down_exponent+shift-8-gain
    dense_values=torch.ldexp(dense.float(),scale);pruned_values=torch.ldexp(pruned.float(),scale)
    if not late:assert torch.equal(dense_values,values)
    return dict(dense=dense_values,pruned=pruned_values,skip=skip,
        shift_range={name:[int(stats[name].min()),int(stats[name].max())] for name in ('gate_shift','up_shift','down_shift')})


@torch.inference_mode()
def run(output,diagram):
    """Scalar paths/pins/metadata select22 frozen layers and ordinary rows.
    Captures:22 CPU-mapped dictionaries of activation/residual/target[256,H].
    Per layer weights:Gate/Up[K,H],Down[O,K] float32 CUDA checkpoint matrices.
    record codes[O,K]/scale[O,1] are pinned calibrated weights. Inputs/targets
    [M,H] omit row0 per image. effective_down[O,K] preserves calibration, not
    the uncalibrated checkpoint. powers[K], changed_up[K,H]/down[O,K] are
    weight-only transforms; quantized candidate retains current scalar Up
    exponent and per-output Down exponents[1,O]. Probe input[4,H] and double
    outputs[4,O] check reciprocal floating identity before integer requantizing.
    Candidate selection uses only fit row error; all reports contain scalars.
    """
    root=Path.cwd();cache=root/'.cache/model_reference';stage=output.parent
    assert not Path('/.dockerenv').exists() and root==Path('/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator')
    assert output.resolve().is_relative_to(cache.resolve()) and not output.exists() and diagram.is_file()
    started=time.monotonic();torch.set_num_threads(1);torch.set_num_interop_threads(1)
    torch.set_float32_matmul_precision('highest');torch.cuda.set_per_process_memory_fraction(.15)
    torch.cuda.reset_peak_memory_stats();pins={}
    def read(path):return json.loads(path.read_text())
    def pin(path,wanted=None):
        with path.open('rb') as f:digest=file_digest(f,'sha256').hexdigest()
        assert wanted is None or digest==wanted,('Changed numerical input',path)
        assert pins.setdefault(str(path),digest)==digest
        return path
    old_inputs=cache/'ff_gate_up_channel_scale/inputs.json';seal=read(pin(old_inputs))
    for name,digest in seal['input_sha256'].items():pin(Path(name),digest)
    calibration_record=read(pin(root/'records/tri_oracle_down_code_calibration.json'))
    calibration=cache/'gqa_testdev/down_code_calibration_export/receipt.json'
    cal=read(pin(calibration,calibration_record['evidence_sha256'][str(calibration.relative_to(root))]))
    assert cal['checkpoint_revision']==seal['checkpoint_revision']
    baseline_source=pin(cache/'ff_systematic_offset_audit/audit.py')
    for path in (Path(__file__).resolve(),root/'syn/test_tri_oracle_reciprocal_weight_equalization.py',
                 diagram,stage/'guard.py',root/'syn/audit_tri_oracle_calibrated_weight_transport.py'):
        pin(path)
    spec=importlib.util.spec_from_file_location('current_offset_control',baseline_source)
    baseline_helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline_helper)
    model=cache/'tiny_llava_v1';mapping=read(model/'model.safetensors.index.json')['weight_map']
    epsilon=read(model/'config.json')['text_config']['rms_norm_eps']
    archived=torch.load(cache/'format320/captured_rows.pt',map_location='cpu',weights_only=True,mmap=True)
    policies=read(cache/'format335/layer_policy.json')['layers']
    metadata=read(root/'records/format320_multi_image_range_audit.json')
    assert metadata['labels_used'] is False and [x['split'] for x in metadata['inputs']]==['calibration']*8+['held']*8
    assert len({x['image_pixel_sha256'] for x in metadata['inputs']})==16
    assert len(archived)==len(policies)==len(cal['layers'])==22
    selected=[row for row in range(256) if row%16];assert len(selected)==240
    results=[]
    for layer,(data,policy,cal_row) in enumerate(zip(archived,policies,cal['layers'],strict=True)):
        assert policy['layer']==cal_row['layer']==layer
        weights=[]
        for kind in ('gate','up','down'):
            key,=(name for name in mapping if name.endswith(f'.layers.{layer}.mlp.{kind}_proj.weight'))
            with safe_open(model/mapping[key],framework='pt',device='cpu') as shard:
                weights.append(shard.get_tensor(key).to(device='cuda',dtype=torch.float32))
        activation,residual,target=[data[name][selected].to('cuda') for name in ('activation','residual','target')]
        assert activation.shape==residual.shape==target.shape==(240,2048)
        rebuilt=functional.linear(functional.silu(functional.linear(activation,weights[0]))*
                                  functional.linear(activation,weights[1]),weights[2])
        assert metrics(rebuilt,target)<1e-5
        baseline=IntegerFeedForwardReference(*weights,epsilon)
        record=torch.load(pin(calibration.parent/f'codes/down_{layer:02d}.pt',cal_row['codebook_sha256']),
                          map_location='cpu',weights_only=True)
        original_codes,scales=_quantize(weights[2],per_row=True)
        baseline.down=record['codes'].to('cuda');baseline.down_exponent=record['scale'].to('cuda').T
        assert torch.equal(baseline.down_exponent,scales.T) and baseline.down.dtype==torch.int8
        assert bool(((baseline.down.to(torch.int16)-original_codes).abs()<=1).all())
        effective_down=torch.ldexp(baseline.down.float(),baseline.down_exponent.T)
        powers=channel_powers(weights[1],effective_down)
        changed_up,changed_down=reciprocal_weights(weights[1],effective_down,powers)
        probe=activation[:4].double();gate=functional.silu(functional.linear(probe,weights[0].double()))
        old=functional.linear(gate*functional.linear(probe,weights[1].double()),effective_down.double())
        new=functional.linear(gate*functional.linear(probe,changed_up.double()),changed_down.double())
        torch.testing.assert_close(new,old,rtol=1e-11,atol=1e-11)
        candidate=copy(baseline);candidate.up,power=_quantize(changed_up);candidate.up_exponent=int(power)
        candidate.up_sign=torch.where(candidate.up<0,-1,1).to(torch.int8)
        candidate.down,power=_quantize(changed_down,per_row=True);candidate.down_exponent=power.T
        before=evaluate_pair(baseline,activation,residual,policy,layer>=17)
        control,_=baseline_helper.current_output(baseline,activation,residual,policy,layer>=17)
        assert torch.equal(control,before['pruned']),('Current calibrated baseline differs',layer)
        after=evaluate_pair(candidate,activation,residual,policy,layer>=17)
        fit={name:metrics(value['pruned'][:120],target[:120]) for name,value in (('baseline',before),('balanced',after))}
        dense_fit={name:metrics(value['dense'][:120],target[:120]) for name,value in (('baseline',before),('balanced',after))}
        choice='balanced' if fit['balanced']<fit['baseline'] else 'baseline'
        diagnostic={mode:{name:metrics(value[mode][120:],target[120:]) for name,value in
            (('baseline',before),('balanced',after))} for mode in ('dense','pruned')}
        row=dict(layer=layer,choice=choice,fit_pruned=fit,fit_dense=dense_fit,diagnostic=diagnostic,
            channel_power_counts={str(power):int((powers==power).sum()) for power in range(-2,3)},
            candidate_shift_ranges=after['shift_range'],up_weight_exponent_before=baseline.up_exponent,
            up_weight_exponent_after=candidate.up_exponent,
            diagnostic_mask_changes=int((before['skip'][120:]^after['skip'][120:]).sum()),
            diagnostic_baseline_skips=int(before['skip'][120:].sum()),diagnostic_balanced_skips=int(after['skip'][120:].sum()))
        results.append(row);print('RECIPROCAL_LAYER',layer,choice,diagnostic['pruned'],flush=True)
        del weights,activation,residual,target,rebuilt,baseline,candidate,record,original_codes,scales,effective_down,powers
        del changed_up,changed_down,probe,gate,old,new,before,after,control
    for name,wanted in pins.items():
        with Path(name).open('rb') as f:assert file_digest(f,'sha256').hexdigest()==wanted,('Changed final input',name)
    summary={mode:{name:sum(row['diagnostic'][mode][name if name!='selected' else row['choice']] for row in results)/22
        for name in ('baseline','balanced','selected')} for mode in ('dense','pruned')}
    report=dict(state='reciprocal_weight_balancing_current_format_diagnostic_completed',checkpoint_revision=seal['checkpoint_revision'],
        layers=results,diagnostic_summary=summary,fit_images=8,reused_diagnostic_images=8,rows_per_split_per_layer=120,
        current_calibrated_baselines_exactly_reproduced=22,float64_reciprocal_identity_layers=22,
        independent_exact_dot_cells=22*2*3*2*8,input_sha256=pins,elapsed_seconds=time.monotonic()-started,
        peak_device_bytes=torch.cuda.max_memory_allocated(),peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        hardware_format_extensions_used=False,new_weight_transport_verified=False,task_accuracy_verified=False,
        mapped_execution_verified=False,paper_results_matched=False,untouched_holdout=False,
        scope='Weight-only bounded reciprocal channel powers, original gate and current calibrated physical Down weights. '
              'The fit split chooses baseline or balanced per layer. Fixed current format policies and late correction remain; '
              'new signed8 weights require separate transport/task verification before promotion. No answer labels or training.')
    with output.open('x') as f:f.write(json.dumps(report,indent=2)+'\n')
    print('RECIPROCAL_COMPLETE',summary,flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path);parser.add_argument('diagram',type=Path)
    args=parser.parse_args();run(args.output,args.diagram)
