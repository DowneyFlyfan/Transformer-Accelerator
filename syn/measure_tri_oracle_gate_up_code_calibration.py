"""Test bounded offline gate/up code calibration in the existing formats.

M=240 ordinary archived rows, F=120 calibration rows, E=120 reused diagnostic
rows, H=O=2048 hidden/output features, K=5632 intermediate channels. The
checkpoint is frozen; candidate signed8 codes differ by at most one step.
No baseline files, runtime formats, mapped design or simulator inputs change.
"""
if not __debug__:raise RuntimeError('Code calibration requires assertions')
from copy import copy
from hashlib import file_digest
import importlib.util,json,resource,time
from pathlib import Path
import torch
import torch.nn.functional as functional
from safetensors import safe_open
from tri_oracle_integer_reference import IntegerFeedForwardReference,_quantize
from measure_tri_oracle_reciprocal_weight_equalization import evaluate_pair,metrics


def fit_projection_codes(activation,weight,codes,exponent):
    """Caller A[F,H], trained W[K,H], signed8 C[K,H], scalar exponent e.

    A and W are finite floating tensors on C's device. X[F,H] is the actual
    quantized/dequantized activation, Y[F,K]=A W^T the floating projection,
    B[K,H]=C*2^e the current physical weights. Normalize X and projection
    residual R[F,K] by each Y row's norm[F,1]. The discrete objective is
    ||Rn||_F^2 with each new code in original-1..original+1 and signed8 range.
    For16 iterations, independently per output k, choose coordinate h and
    physical step s in{-2^e,+2^e} maximizing
    2*s*dot(Xn[:,h],Rn[:,k])-s*s*||Xn[:,h]||^2. Apply only positive gains.
    This identity is the exact reduction in squared error for that step;
    different output columns have independent residuals. Signed16 updates
    cannot wrap. It is greedy discrete calibration, not a global optimum.
    """
    if activation.ndim!=2 or weight.ndim!=2 or codes.shape!=weight.shape or activation.shape[1]!=weight.shape[1]:
        raise ValueError('Projection dimensions differ')
    if min(*activation.shape,*weight.shape)==0 or not activation.is_floating_point() or not weight.is_floating_point():
        raise ValueError('Nonempty floating projection operands required')
    if codes.dtype!=torch.int8 or activation.device!=weight.device or codes.device!=weight.device:
        raise ValueError('Signed8 codes and floating operands on one device required')
    if type(exponent) is not int or not -126<=exponent<=126:
        raise ValueError('Finite scalar weight exponent required')
    if not bool(torch.isfinite(activation).all()&torch.isfinite(weight).all()):
        raise ValueError('Projection operands must be finite')
    input_codes,input_exponents=_quantize(activation,per_row=True)  # [F,H], [F,1], runtime encoding.
    x=torch.ldexp(input_codes.double(),input_exponents)  # [F,H], physical input rows.
    target=functional.linear(activation.double(),weight.double())  # [F,K], checkpoint target.
    physical=codes.double()*2.**exponent  # [K,H], frozen original physical weights.
    norm=target.norm(dim=1,keepdim=True).clamp_min(1e-20)  # [F,1], output-row scale.
    design=x/norm  # [F,H], row-normalized runtime inputs.
    residual=(target-functional.linear(x,physical))/norm  # [F,K], normalized projection error.
    curvature=design.square().sum(dim=0)  # [H], per-coordinate squared input norm.
    if not bool(torch.isfinite(design).all()&torch.isfinite(residual).all()&torch.isfinite(curvature).all()):
        raise ValueError('Nonfinite projection system')
    changed=codes.to(torch.int16)  # [K,H], independent mutable candidate.
    lower=(changed-1).clamp_min(-128);upper=(changed+1).clamp_max(127)  # [K,H], original-code bounds.
    outputs=torch.arange(weight.shape[0],device=codes.device)  # [K], unique output-row indices.
    scale=2.**exponent  # scalar physical size of one integer code.
    for _ in range(16):
        correlation=(design.T@residual).T  # [K,H], each coordinate's error correlation.
        if not bool(torch.isfinite(correlation).all()):raise ValueError('Nonfinite projection correlation')
        direction=torch.where(correlation>=0,1,-1).to(torch.int16)  # [K,H], best unconstrained step sign.
        proposed=changed+direction  # [K,H], signed16 legal-range candidate check.
        allowed=(proposed>=lower)&(proposed<=upper)  # [K,H], original step/range limits.
        gains=(2*scale*correlation.abs()-scale*scale*curvature[None,:]).masked_fill(~allowed,-torch.inf)  # [K,H].
        best,indices=gains.max(dim=1)  # [K], largest exact reduction and selected input coordinate.
        active=best>0  # [K], only strict improvements are allowed.
        if not bool(active.any()):break
        steps=torch.where(active,direction[outputs,indices],0)  # [K], zero for inactive outputs.
        old_loss=residual.square().sum()  # scalar normalized calibration objective.
        changed[outputs,indices]+=steps
        residual-=design[:,indices]*(steps.double()*scale)[None,:]  # [F,K], exact selected-column residual update.
        assert float(residual.square().sum())<=float(old_loss)*(1+1e-12)+1e-24,'Discrete calibration increased fit loss'
    changed=changed.to(torch.int8)  # [K,H], legal signed8 export representation.
    assert bool(((changed.to(torch.int16)-codes.to(torch.int16)).abs()<=1).all())
    return changed.contiguous()


def projection_error(activation,weight,codes,exponent):
    """Caller A[N,H], trained W[K,H], signed8 C[K,H], scalar e; N=F/E.
    Dequantized inputs[N,H], physical weights[K,H], output/target[N,K]
    share the exact runtime activation encoding. Return scalar row-relative error.
    """
    inputs,powers=_quantize(activation,per_row=True)  # [N,H], [N,1], input-derived.
    values=functional.linear(torch.ldexp(inputs.double(),powers),codes.double()*2.**exponent)  # [N,K].
    target=functional.linear(activation.double(),weight.double())  # [N,K], frozen checkpoint.
    return metrics(values,target)


@torch.inference_mode()
def run(output,diagram):
    """Paths, pins, policies and counts are scalar metadata. Captures contain
    CPU-mapped activation/residual/target[256,H] for22 layers. Per layer,
    weights are Gate/Up[K,H],Down[O,K] float32 on the graphics processor;
    selected activation/residual/target[M,H] omit token0 from every image.
    The calibrated Down record stores codes[O,K],scale[O,1]. Baseline and
    candidate expose dense/pruned[M,O] and skip[M,K]. Fit and diagnostic
    metrics are scalar dictionaries. No generated answers or label fitting.
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
        assert wanted is None or digest==wanted,('Changed calibration input',path)
        assert pins.setdefault(str(path),digest)==digest
        return path
    seal=read(pin(cache/'ff_gate_up_channel_scale/inputs.json'))
    for name,digest in seal['input_sha256'].items():pin(Path(name),digest)
    calibration_record=read(pin(root/'records/tri_oracle_down_code_calibration.json'))
    calibration=cache/'gqa_testdev/down_code_calibration_export/receipt.json'
    cal=read(pin(calibration,calibration_record['evidence_sha256'][str(calibration.relative_to(root))]))
    earlier_record=read(pin(root/'records/tri_oracle_reciprocal_weight_balance_diagnostic.json'))
    earlier_path=cache/'ff_reciprocal_weight_equalization_final/receipt.json'
    earlier=read(pin(earlier_path,earlier_record['evidence_sha256'][str(earlier_path.relative_to(root))]))
    assert cal['checkpoint_revision']==seal['checkpoint_revision']==earlier['checkpoint_revision']
    baseline_source=pin(cache/'ff_systematic_offset_audit/audit.py')
    for path in (Path(__file__).resolve(),root/'syn/test_tri_oracle_gate_up_code_calibration.py',
        Path(evaluate_pair.__code__.co_filename).resolve(),diagram,stage/'architecture.dot',stage/'guard.py',
        root/'syn/tri_oracle_process_guard.py',root/'syn/audit_tri_oracle_calibrated_weight_transport.py'):
        pin(path)
    spec=importlib.util.spec_from_file_location('calibration_current_control',baseline_source)
    baseline_helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline_helper)
    model=cache/'tiny_llava_v1';mapping=read(model/'model.safetensors.index.json')['weight_map']
    epsilon=read(model/'config.json')['text_config']['rms_norm_eps']
    archived=torch.load(cache/'format320/captured_rows.pt',map_location='cpu',weights_only=True,mmap=True)
    policies=read(cache/'format335/layer_policy.json')['layers']
    metadata=read(root/'records/format320_multi_image_range_audit.json')
    assert metadata['labels_used'] is False and [x['split'] for x in metadata['inputs']]==['calibration']*8+['held']*8
    assert len({x['image_pixel_sha256'] for x in metadata['inputs']})==16
    assert len(archived)==len(policies)==len(cal['layers'])==len(earlier['layers'])==22
    selected=[row for row in range(256) if row%16];assert len(selected)==240
    results=[]
    for layer,(data,policy,cal_row,old_row) in enumerate(zip(archived,policies,cal['layers'],earlier['layers'],strict=True)):
        assert policy['layer']==cal_row['layer']==old_row['layer']==layer
        weights=[]  # Gate/Up[K,H],Down[O,K], one layer read from pinned checkpoint shards.
        for kind in ('gate','up','down'):
            key,=(name for name in mapping if name.endswith(f'.layers.{layer}.mlp.{kind}_proj.weight'))
            with safe_open(model/mapping[key],framework='pt',device='cpu') as shard:
                weights.append(shard.get_tensor(key).to(device='cuda',dtype=torch.float32))
        activation,residual,target=[data[name][selected].to('cuda') for name in ('activation','residual','target')]  # [M,H].
        assert activation.shape==residual.shape==target.shape==(240,2048)
        assert weights[0].shape==weights[1].shape==(5632,2048) and weights[2].shape==(2048,5632)
        rebuilt=functional.linear(functional.silu(functional.linear(activation,weights[0]))*
                                  functional.linear(activation,weights[1]),weights[2])  # [M,O], source-check target.
        assert metrics(rebuilt,target)<1e-5
        baseline=IntegerFeedForwardReference(*weights,epsilon)
        record=torch.load(pin(calibration.parent/f'codes/down_{layer:02d}.pt',cal_row['codebook_sha256']),
                          map_location='cpu',weights_only=True)
        original,scales=_quantize(weights[2],per_row=True)  # [O,K], [O,1], original Down representation.
        baseline.down=record['codes'].to('cuda');baseline.down_exponent=record['scale'].to('cuda').T
        assert torch.equal(baseline.down_exponent,scales.T) and baseline.down.dtype==torch.int8
        assert bool(((baseline.down.to(torch.int16)-original.to(torch.int16)).abs()<=1).all())
        before=evaluate_pair(baseline,activation,residual,policy,layer>=17)
        control,_=baseline_helper.current_output(baseline,activation,residual,policy,layer>=17)  # [M,O], independent current control.
        assert torch.equal(control,before['pruned']),('Current calibrated baseline differs',layer)
        for mode in ('dense','pruned'):
            assert abs(metrics(before[mode][120:],target[120:])-old_row['diagnostic'][mode]['baseline'])<1e-12
        candidate=copy(baseline)
        candidate.gate=fit_projection_codes(activation[:120],weights[0],baseline.gate,baseline.gate_exponent)
        candidate.up=fit_projection_codes(activation[:120],weights[1],baseline.up,baseline.up_exponent)
        candidate.gate_sign=torch.where(candidate.gate<0,-1,1).to(torch.int8)  # [K,H], actual new code signs.
        candidate.up_sign=torch.where(candidate.up<0,-1,1).to(torch.int8)  # [K,H], zero maps to+1 as in current runtime.
        after=evaluate_pair(candidate,activation,residual,policy,layer>=17)
        assert before['shift_range']==after['shift_range']
        projections={}
        for role,weight in zip(('gate','up'),weights[:2],strict=True):
            exponent=getattr(baseline,role+'_exponent')
            projections[role]={split:{name:projection_error(activation[rows],weight,getattr(reference,role),exponent)
                for name,reference in (('baseline',baseline),('calibrated',candidate))}
                for split,rows in (('fit',slice(0,120)),('diagnostic',slice(120,None)))}
        fit={mode:{name:metrics(value[mode][:120],target[:120]) for name,value in (('baseline',before),('calibrated',after))}
             for mode in ('dense','pruned')}
        choice='calibrated' if fit['pruned']['calibrated']<fit['pruned']['baseline'] else 'baseline'
        diagnostic={mode:{name:metrics(value[mode][120:],target[120:]) for name,value in (('baseline',before),('calibrated',after))}
                    for mode in ('dense','pruned')}
        row=dict(layer=layer,choice=choice,fit=fit,diagnostic=diagnostic,projections=projections,
            changed_codes={role:int(getattr(candidate,role).ne(getattr(baseline,role)).sum()) for role in ('gate','up')},
            changed_signs={role:int(getattr(candidate,role+'_sign').ne(getattr(baseline,role+'_sign')).sum()) for role in ('gate','up')},
            diagnostic_mask_changes=int((before['skip'][120:]^after['skip'][120:]).sum()),
            scalar_weight_exponents={role:getattr(baseline,role+'_exponent') for role in ('gate','up')},shift_ranges=after['shift_range'])
        results.append(row);print('GATE_UP_CODE_LAYER',layer,choice,diagnostic['pruned'],flush=True)
        del weights,activation,residual,target,rebuilt,baseline,candidate,record,original,scales,before,after,control,weight
    for name,wanted in pins.items():
        with Path(name).open('rb') as f:assert file_digest(f,'sha256').hexdigest()==wanted,('Changed final calibration input',name)
    summary={mode:{name:sum(row['diagnostic'][mode][name if name!='selected' else row['choice']] for row in results)/22
        for name in ('baseline','calibrated','selected')} for mode in ('dense','pruned')}
    report=dict(state='bounded_gate_up_code_calibration_current_format_diagnostic_completed',checkpoint_revision=seal['checkpoint_revision'],
        layers=results,diagnostic_summary=summary,fit_images=8,reused_diagnostic_images=8,rows_per_split_per_layer=120,
        maximum_coordinate_iterations=16,maximum_code_step=1,current_calibrated_baselines_exactly_reproduced=22,
        device=torch.cuda.get_device_name(),torch_version=str(torch.__version__),
        independent_exact_dot_cells=22*2*3*2*8,input_sha256=pins,elapsed_seconds=time.monotonic()-started,
        peak_device_bytes=torch.cuda.max_memory_allocated(),peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        hardware_format_extensions_used=False,new_weight_transport_verified=False,task_accuracy_verified=False,
        mapped_execution_verified=False,paper_results_matched=False,untouched_holdout=False,weights_exported_or_promoted=False,
        scope='At most16 greedy discrete projection-residual fit steps on120 calibration rows per layer; Gate/Up codes change by at most1, '
              'scalar exponents and calibrated Down/policies/late correction retained, actual prediction signs recomputed. '
              'Fit pruned layer error chooses baseline or candidate; reused image-disjoint diagnostic rows are separate. '
              'No answer labels, gradient optimizer, task generation, weight export or mapped execution.')
    with output.open('x') as f:f.write(json.dumps(report,indent=2)+'\n')
    print('GATE_UP_CODE_COMPLETE',summary,flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);parser.add_argument('diagram',type=Path)
    args=parser.parse_args();run(args.output,args.diagram)
