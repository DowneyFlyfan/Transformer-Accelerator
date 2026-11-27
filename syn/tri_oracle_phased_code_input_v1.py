"""Phase dispatch over the existing immutable scalar-weight code-input family.

M caller token rows,H input features,K intermediate channels,O output features.
Complete trained shape is H=O2048,K5632; existing constructor also admits
aligned small matrices. No weights, model, floating activation or oracle is
loaded. All arithmetic uses existing tensor primitives and reference tables.
"""
import torch
from tri_oracle_code_input_reference_v1 import (
    CodeInputFeedForwardReference, _dot_codes, _policy_table, _requantize, _signed9,
)


def _first_pair(first_policy, layer):
    """Caller frozen scalar dictionary/layer -> existing checked signed pair.

    required is a local key set. fallback is a new dictionary initialized from
    the two caller scalar fields; checked is a new scalar-policy dictionary.
    table/setting come from existing _policy_table; no tensor or answer selects
    them and the caller dictionaries are never modified.
    """
    required={'layer','maximum_up_gain_bits','down_shift_offset'}
    if (type(first_policy) is not dict or set(first_policy)!=required
            or type(first_policy['layer']) is not int or first_policy['layer']!=layer):
        raise ValueError('Protected policy must have matching layer and signed scalar pair')
    fallback={key:first_policy[key] for key in ('maximum_up_gain_bits','down_shift_offset')}
    checked=dict(layer=layer,fallback=fallback,buckets=[])
    table,setting=_policy_table(checked,layer)
    return setting


def _validate_reference(reference, layer):
    """Caller existing reference/layer -> validated unchanged object metadata.

    tensors are the constructor-owned signed8 gate/up[K,H],down[O,K]. expected
    contains shapes from constructor scalar dimensions. Signs[K,H] and the
    signed64 nonlinear response[65536] were initialized by that constructor.
    matrix/shape/sign are loop views of those stored tensors; none is written.
    Units/layer/revision are scalar metadata, never reselected from values.
    """
    if not isinstance(reference,CodeInputFeedForwardReference):
        raise ValueError('Existing CodeInputFeedForwardReference required')
    if (type(layer) is not int or not 0<=layer<22
            or type(reference.layer) is not int or reference.layer!=layer):
        raise ValueError('Caller and immutable reference layers must match')
    if (type(reference.checkpoint_revision) is not str or not reference.checkpoint_revision.strip()):
        raise ValueError('Existing reference revision metadata required')
    for name in ('gate_exponent','up_exponent','down_exponent'):
        _signed9(getattr(reference,name),name)
    tensors=(reference._gate,reference._up,reference._down)
    expected=((reference.channels,reference.hidden),(reference.channels,reference.hidden),
              (reference.outputs,reference.channels))
    for matrix,shape in zip(tensors,expected):
        if (not isinstance(matrix,torch.Tensor) or matrix.dtype!=torch.int8
                or tuple(matrix.shape)!=shape or matrix.device!=reference.device):
            raise ValueError('Existing immutable weight geometry/device changed')
    for sign in (reference._gate_sign,reference._up_sign):
        if (not isinstance(sign,torch.Tensor) or sign.dtype!=torch.int8
                or tuple(sign.shape)!=expected[0] or sign.device!=reference.device):
            raise ValueError('Existing immutable weight sign geometry/device changed')
    if (not isinstance(reference._silu_response,torch.Tensor)
            or reference._silu_response.dtype!=torch.int64
            or reference._silu_response.shape!=(65536,)
            or reference._silu_response.device!=reference.device):
        raise ValueError('Existing immutable nonlinear table geometry/device changed')


def _compute_group(reference, codes, outlier_mask, outlier_negative, positions,
                   gate_shift, up_shift, down_shift, gain, prune):
    """Unchanged existing tensor primitive sequence for B selected actual rows.

    Caller codes/planes[M,H] and positions[B] select original rows, initialized
    by phase+eA metadata only. reference owns gate/up[K,H],down[O,K],signs[K,H]
    and nonlinear lookup[65536]. Scalar shifts/gain/prune are already checked.
    active/negative[B,H] use index_select; signals[B,H] initialize from actual
    pre-gamma Boolean planes. count[B] is signed32 actual outlier population.
    gate_margin/up_margin,gate_dot/up_dot[B,K] initialize from existing exact
    _dot_codes. skip/keep[B,K] are predictor flags; row_codes[B,H] copy actual
    input codes without floating decode. shift_tensor[B,1] starts filled from
    gate_shift and is reused locally. gate_q8/up_q8/products/gated[B,K] are
    signed64; down_input[B,K] is signed8. group contains raw[B,O] signed32 and
    the existing17 traces. name/value are scalar trace keys/unit metadata;
    torch.full creates fresh signed64 scalar-stat vectors[B]. No input writes.
    """
    active=outlier_mask.index_select(0,positions)
    negative=outlier_negative.index_select(0,positions)
    signals=(torch.where(negative,-1,1)*active).to(torch.int8)
    count=active.sum(dim=-1,dtype=torch.int32)
    gate_margin=_dot_codes(signals,reference._gate_sign)
    up_margin=_dot_codes(signals,reference._up_sign)
    skip=(count[:,None]>0)&(gate_margin<=0)&(up_margin==0)
    row_codes=codes.index_select(0,positions)
    gate_dot=_dot_codes(row_codes,reference._gate)
    up_dot=_dot_codes(row_codes,reference._up)
    shift_tensor=torch.full((positions.numel(),1),gate_shift,dtype=torch.int64,device=reference.device)
    gate_q8=_requantize(gate_dot,shift_tensor,16)
    shift_tensor.fill_(up_shift)
    up_q8=_requantize(up_dot,shift_tensor,16)
    products=reference._silu_response[gate_q8+32768]*up_q8
    shift_tensor.fill_(8)
    gated=_requantize(products,shift_tensor,16)
    shift_tensor.fill_(down_shift)
    down_input=_requantize(gated,shift_tensor,8).to(torch.int8)
    if prune:
        down_input=down_input.masked_fill(skip,0)
    group=dict(raw=_dot_codes(down_input,reference._down),gate_margin=gate_margin,
               up_margin=up_margin,skip=skip,keep=~skip,gate_dot=gate_dot,up_dot=up_dot,
               gate_q8=gate_q8,up_q8=up_q8,gated=gated,down_input=down_input,outlier_count=count)
    for name,value in (('output_exponents',reference.down_exponent+down_shift-8-gain),
                       ('gate_shift',gate_shift),('up_shift',up_shift),
                       ('down_shift',down_shift),('up_gain_bits',gain)):
        group[name]=torch.full((positions.numel(),),value,dtype=torch.int64,device=reference.device)
    return group


@torch.inference_mode()
def evaluate_phased_codes(reference, codes, eA, outlier_mask, outlier_negative, *,
                          layer, global_positions, mode, ordinary_policy,
                          first_policy, prune):
    """Actual normalizer code/feature tensors -> existing17traces + row_phase.

    reference is caller's existing immutable scalar-weight object. codes[M,H]
    signed8, planes[M,H] Boolean and eA/positions[M] signed64 come unchanged
    from the caller. eA carries signed9; positions are genuine unique originals.
    mode/layer/prune/policies are caller scalar metadata; phase is never derived
    from row index, image rank, code values or an invented offset.

    value is a caller vector/plane used in validation only. table/fallback and
    protected are existing-helper scalar policy results. row_phase[M] starts
    fresh:0 genuine PREFILLglobal0,1 otherprefill,2 positive DECODE. schedule
    starts as an empty list of metadata groups. phase/exponent are scalar
    metadata, eligible[M] is a Boolean selection and positions[B] initialize
    from nonzero(eligible & eA==exponent). caps/offsets/gain/shifts are integers.
    All shifts are checked before any projection is computed.

    outputs is a new dictionary initialized with fresh row_phase[M]. Each
    group computes existing numeric traces[B,O]/[B,K]/[B], then fresh empty
    outputs[M,...] are filled only at original caller row indices. name/value
    are group keys/tensors. Inputs, policies and reference state are unchanged.
    """
    _validate_reference(reference,layer)
    if type(mode) is not str or mode not in ('PREFILL','DECODE') or type(prune) is not bool:
        raise ValueError('Exact PREFILL/DECODE mode and Boolean prune required')
    if (not isinstance(codes,torch.Tensor) or codes.dtype!=torch.int8 or codes.ndim!=2
            or codes.shape[0]==0 or codes.shape[1]!=reference.hidden or codes.device!=reference.device):
        raise ValueError('Nonempty signed8 code matrix on existing reference device required')
    for value in (eA,global_positions):
        if (not isinstance(value,torch.Tensor) or value.dtype!=torch.int64
                or value.shape!=(codes.shape[0],) or value.device!=reference.device):
            raise ValueError('Signed64 per-row units and actual positions required')
    for value in (outlier_mask,outlier_negative):
        if (not isinstance(value,torch.Tensor) or value.dtype!=torch.bool
                or value.shape!=codes.shape or value.device!=reference.device):
            raise ValueError('Boolean actual feature planes on existing reference device required')
    if (not bool(((eA>=-256)&(eA<=255)).all()) or not bool((global_positions>=0).all())
            or torch.unique(global_positions).numel()!=codes.shape[0]
            or bool((outlier_negative&~outlier_mask).any())):
        raise ValueError('Invalid signed9 units, original positions or outlier sign subset')
    if mode=='DECODE' and not bool((global_positions>0).all()):
        raise ValueError('DECODE requires genuine positive original positions')
    table,fallback=_policy_table(ordinary_policy,layer)
    protected=_first_pair(first_policy,layer)
    row_phase=(torch.full_like(global_positions,2) if mode=='DECODE' else
               torch.where(global_positions==0,torch.zeros_like(global_positions),torch.ones_like(global_positions)))
    schedule=[]
    for phase in (0,1,2):
        eligible=row_phase==phase
        for exponent in sorted(set(eA[eligible].tolist())):
            positions=torch.nonzero(eligible&(eA==exponent),as_tuple=True)[0]
            gain_cap,down_offset=protected if phase==0 else table.get(exponent,fallback)
            gate_shift=-(exponent+reference.gate_exponent+8)
            original_up_shift=-(exponent+reference.up_exponent+8)
            gain=min(original_up_shift,gain_cap)
            up_shift=original_up_shift-gain
            down_shift=max(0,gain+down_offset)
            if any(value<0 or value>63 for value in (gate_shift,up_shift,down_shift)):
                raise ValueError('Number format does not fit existing unsigned six-bit shifts')
            schedule.append((positions,gate_shift,up_shift,down_shift,gain))
    outputs=dict(row_phase=row_phase)
    for positions,gate_shift,up_shift,down_shift,gain in schedule:
        group=_compute_group(reference,codes,outlier_mask,outlier_negative,positions,
                             gate_shift,up_shift,down_shift,gain,prune)
        for name,value in group.items():
            if name not in outputs:
                outputs[name]=torch.empty((codes.shape[0],*value.shape[1:]),dtype=value.dtype,device=reference.device)
            outputs[name].index_copy_(0,positions,value)
    return outputs
