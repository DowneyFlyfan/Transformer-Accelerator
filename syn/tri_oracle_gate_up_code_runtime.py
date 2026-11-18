"""Route fit-selected ordinary-prefill integer codebooks without data dependencies.

The caller supplies its existing baseline configuration callback. First prompt
rows, generated rows, unselected layers and baseline mode delegate to that
callback. Only selected ordinary-prefill calls use alternative Gate/Up codes.
No checkpoint, dataset or archived source is read when this module is imported.
"""
if not __debug__:raise RuntimeError('Code routing requires assertions')
from copy import copy
from hashlib import file_digest
from pathlib import Path
import torch
from tri_oracle_integer_reference import _quantize,_dot,_requantize
from export_tri_oracle_gate_up_codes import validate_payload,tensor_sha


def _sha(path):
    with path.open('rb') as f:return file_digest(f,'sha256').hexdigest()


def _gated_codes(reference,activation,stats):
    """Caller input[M,H], fixed signed8 Gate/Up[K,H], and row stats[M].
    Runtime input codes[M,H], Gate/Up/product/gated[M,K] reproduce the
    original signed16 integer nonlinear conversion with scalar shifts[M,1].
    """
    codes,_=_quantize(activation,per_row=True)
    gate=_requantize(_dot(codes,reference.gate),stats['gate_shift'][:,None],16)
    up=_requantize(_dot(codes,reference.up),stats['up_shift'][:,None],16)
    product=reference.silu_response[gate+32768]*up
    return _requantize(product,torch.full_like(stats['down_shift'][:,None],8),16)


def install(item,projection,index,codebook,context,exported,*,configure,late_range=(17,22)):
    """item/projection: existing layer/reference and frozen checkpoint module.
    index/codebook/context/exported are scalar scheduling/file/hash metadata.
    Original Gate/Up[K,H], Down[O,K] signed8 tensors and scalar Gate/Up scales
    precede combined.configure's closure override. Selected candidate weights
    keep these dimensions and original scales, with current calibrated Down
    codes[O,K] and per-output exponent[1,O]. Candidate sign tables[K,H]
    derive from the actual exported codes. K=5632,H=O=2048.
    """
    candidate=None
    if exported is not None:
        assert exported['layer']==index and _sha(Path(exported['path']))==exported['sha256']
        payload=torch.load(exported['path'],map_location='cpu',weights_only=True)
        validate_payload(payload,item.reference.gate,item.reference.up,
                         item.reference.gate_exponent,item.reference.up_exponent)
        for role in ('gate','up'):
            assert tensor_sha(getattr(item.reference,role))==exported['original_numeric_sha256'][role]
            assert tensor_sha(payload[role])==exported['candidate_numeric_sha256'][role]
        candidate=copy(item.reference)  # Class evaluator retained before the baseline closure is installed.
        assert 'evaluate' not in candidate.__dict__
        candidate.gate=payload['gate'].to(candidate.device)
        candidate.up=payload['up'].to(candidate.device)
        candidate.gate_sign=torch.where(candidate.gate<0,-1,1).to(torch.int8)
        candidate.up_sign=torch.where(candidate.up<0,-1,1).to(torch.int8)
        record=torch.load(codebook,map_location='cpu',weights_only=True)
        ordinary_codes,down_scale=_quantize(projection.down_proj.weight,per_row=True)  # [O,K],[O,1].
        candidate.down=record['codes'].to(candidate.device)
        candidate.down_exponent=record['scale'].to(candidate.device).T
        assert candidate.down.dtype==torch.int8 and candidate.down.shape==ordinary_codes.shape
        assert torch.equal(candidate.down_exponent,down_scale.T)
        assert bool(((candidate.down.to(torch.int16)-ordinary_codes.to(torch.int16)).abs()<=1).all())
    configure(item,projection,index,codebook,context)
    original=item.reference.evaluate

    def evaluate(activation,residual,**settings):
        """Caller input/residual[M,H] and scalar settings come from unchanged
        policy buckets. raw/values[M,O],norm[M,H] and stats[M] come from the
        selected class evaluator. Outliers/signs[M,H],margins/skip[M,K],gated/
        wide/coarse/overflow/delta[M,K],active[M],selected[A,K] reconstruct
        the current late correction once. Total[M,O] and gain/shift[M,1]
        retain the original scalar number formats. Context counters update
        exactly once per call. First token, decode and other layers use the
        original closure with no candidate computation or counter changes.
        """
        first=item.decoder.prefill_active and context['calls'][index]==0
        if not(context['candidate'] and candidate is not None and item.decoder.prefill_active and not first):
            return original(activation,residual,**settings)
        assert context['calibrated'] and context['clipping'] and settings['prune']
        assert settings.get('gate_threshold',0)==settings.get('up_window',0)==0
        context['calls'][index]+=1
        context['weight_rows'][index]+=activation.shape[0]
        context['changed_rows'][index]+=activation.shape[0]
        raw,values,stats=candidate.evaluate(activation,residual,**settings)
        if not late_range[0]<=index<late_range[1]:return raw,values,stats
        norm=stats['norm_codes'];outliers=norm.abs()>768
        signs=(torch.where(norm<0,-1,1)*outliers).to(torch.int8)
        gate=_dot(signs,candidate.gate_sign);up=_dot(signs,candidate.up_sign)
        skip=(stats['outlier_count'][:,None]>0)&(gate<=0)&(up==0)
        assert torch.equal(skip.sum(dim=1,dtype=torch.int32),stats['skip_count'])
        gated=_gated_codes(candidate,activation,stats)
        shift=stats['down_shift'][:,None]
        wide=_requantize(gated,shift,16);coarse=wide.clamp(-128,127)
        overflow=wide-coarse
        delta=overflow.clamp(-128,127).masked_fill(skip,0).to(torch.int8)
        active=delta.ne(0).any(dim=1);selected=delta[active]
        base=_dot(coarse.masked_fill(skip,0).to(torch.int8),candidate.down)
        assert torch.equal(base,raw)
        context['clip_rows'][index]+=activation.shape[0]
        context['workload'].update(rows=gated.shape[0],codes=gated.numel(),active_rows=selected.shape[0],
            saturated_codes=int(overflow.ne(0).sum()),retained_corrections=int(selected.ne(0).sum()),
            skipped_saturated_codes=int((skip&overflow.ne(0)).sum()))
        if selected.shape[0]:
            total=raw.clone();total[active]+=_dot(selected,candidate.down)
            assert candidate.channels*2*128*128<2**31
            gain=stats['up_gain_bits'][:,None]
            values=torch.ldexp(total.float(),candidate.down_exponent+shift-8-gain)
            raw=total
        return raw,values,stats
    item.reference.evaluate=evaluate
