"""Exact-code attention/context continuation reference.

T1..1024 cache slots, M1..1024 selected queries, H2048 hidden features, Q32
query heads, G4 grouped key/value heads, D64 features/head, B32 output blocks.
Inputs are actual signed-code tensors with explicit physical units and original
positions. No Float activation/context decode or activation/weight quantizer,
model, cache mirror, residual join, CPU fallback, compiler or fitted unit exists.
Double matrix products below are only the unchanged bounded integer dot sums.
All operations follow the input device's current CUDA stream. No inference-mode
wrapper forces special output restrictions. No loss or optimizer is introduced.

Four helpers are plain byte-exact source extractions from the canonical sources;
only expected metadata is read on host. Common-context units use integer lower-
bound search, with the ACTIVE signed-transfer zero-row precedence, never FLOAT
reconstruction. Real cache/frame/trained-table ownership remains caller-owned.
"""
import math
from fractions import Fraction
import torch
import torch.nn.functional as functional

if not __debug__:
    raise RuntimeError('Canonical score/softmax assertions require normal Python mode')

def _dot(left,right):
    """left[M,R] signed8 input, right[N,R] signed8 weights from reference.
    padded[P,R], P=max(32,ceil(M/16)*16), meets native alignment and M>16.
    Returns exact signed32[M,N] sums; caller bounds dot lengths to avoid overflow.
    """
    rows=left.shape[0]
    padded_rows=max(32,((rows+15)//16)*16)
    padded=functional.pad(left.contiguous(),(0,0,0,padded_rows-rows))
    return torch._int_mm(padded,right.t())[:rows]

def _requantize(values,shift,bits):
    """values[M,K] signed integer sums/products; shift[M,1] from configuration.
    magnitude/rounded preserve[M,K]; half[M,1] supplies ties-away rounding.
    Returns signed64 integer codes, saturated to the scalar bits width.
    """
    magnitude=values.to(torch.int64).abs()
    half=torch.where(shift>0,torch.bitwise_left_shift(torch.ones_like(shift,dtype=torch.int64),(shift-1).clamp_min(0)),0)
    rounded=torch.bitwise_right_shift(magnitude+half,shift)
    rounded=torch.where(values<0,-rounded,rounded)
    return rounded.clamp(-(1<<(bits-1)),(1<<(bits-1))-1)

def score_codes(dots,shifts):
    """dots[...]: signed32 integer dot products from caller; shifts broadcast
    to the same shape, signed integer in[-31,31]. Magnitude/amount/rounded have
    the broadcast output shape. Output signed64 values encode signed16 scores.
    Negative shifts use nearest/ties-even, as actual score_scale hardware.
    """
    assert bool(((shifts>=-31)&(shifts<=31)).all())
    assert bool(((dots>=-(1<<31))&(dots<(1<<31))).all())
    magnitude=dots.to(torch.int64).abs()
    amount=(-shifts).clamp_min(1)
    halfway=torch.ones_like(amount,dtype=torch.int64)<<(amount-1)
    right=(magnitude+halfway-1+((magnitude>>amount)&1))>>amount
    left=magnitude<<shifts.clamp_min(0)
    rounded=torch.where(shifts<0,right,left)
    return torch.where(dots<0,-rounded,rounded).clamp(-32768,32767)

def probabilities(scores,sizes):
    """scores/sizes[...,K] are caller integer code and multiplicity arrays.
    maximum[...,1] ignores zero sizes. All remaining arrays preserve[...,K]
    except sums/reciprocal[...,1] and table[65] initialized from exp2 constants.
    Output[...,K] is exact unsigned16 probability codes, returned signed64.
    Zero-mass rows return zeros. Split the48-bit product to avoid overflow.
    """
    assert scores.shape==sizes.shape and 0<scores.shape[-1]<=1024
    assert bool(((scores>=-32768)&(scores<=32767)).all())
    assert bool(((sizes>=0)&(sizes<=1023)).all())
    maximum=scores.masked_fill(sizes==0,-32768).amax(-1,keepdim=True)
    delta=torch.where(sizes>0,maximum-scores,0)
    power=(delta*5909+2048)>>12
    fraction=power&255;index=fraction>>2;remainder=fraction&3
    table=torch.tensor([round((1<<20)*math.exp2(-i/64)) for i in range(65)],dtype=torch.int64,device=scores.device)
    interpolated=(table[index]*(4-remainder)+table[index+1]*remainder+1)>>2
    weights=(sizes*interpolated)>>(power>>8).clamp_max(63)
    sums=weights.sum(-1,keepdim=True)
    reciprocal=torch.where(sums>0,(1<<48)//sums.clamp_min(1),0)
    mass=weights*reciprocal
    low=(mass&0xffffffff)*65535+(1<<47)
    high=(mass>>32)*65535
    return (high+(low>>32))>>16

# Exact floor(B*2**r), B=127*65535, r=-22..9; all admitted signed32 peaks fit.
_HEAD_THRESHOLDS = (1, 3, 7, 15, 31, 63, 126, 253, 507, 1015, 2031, 4063, 8127, 16255, 32511, 65023, 130046, 260092, 520184, 1040368, 2080736, 4161472, 8322945, 16645890, 33291780, 66583560, 133167120, 266334240, 532668480, 1065336960, 2130673920, 4261347840)


def _check_tensors(specifications, device):
    """Caller (tensor,dtype,shape) tuples and scalar device -> validation only.

    No allocations or tensor mutation. value is each caller tensor; dtype/shape
    are immutable metadata. All shapes are full geometry stated by callers.
    """
    for value,dtype,shape in specifications:
        if (not isinstance(value,torch.Tensor) or value.dtype!=dtype or
                tuple(value.shape)!=shape or value.device!=device or
                device.type!='cuda' or value.layout!=torch.strided or
                not value.is_contiguous()):
            raise ValueError('Same-device contiguous CUDA tensor dtype/geometry required')


def _check_units(*vectors):
    """Caller int64 unit vectors[40]/[32] -> no new tensor results or choice."""
    for value in vectors:
        if not bool(((value>=-256)&(value<=255)).all()):
            raise ValueError('Physical unit vectors must fit signed9')


def _ratio(value):
    """Caller two scalar integers -> checked immutable policy pair."""
    if (type(value)not in(tuple,list) or len(value)!=2 or
            any(type(v)is not int for v in value) or value[0]<0 or value[1]<=0):
        raise ValueError('Nonnegative integer numerator and positive integer denominator required')
    return tuple(value)


def _ratio_proxy(ratio, count_bound):
    """Unbounded Python policy pair and scalar U=T*T -> exact small comparator.

    A=recent,B=inner are each0..U. For B>0, A/B has denominator at mostU.
    A nearest bounded-denominator Fraction cannot skip an attainable A/B.
    Equality is included exactly when its representative lies ABOVE the actual
    ratio. B==0 is handled by ordinary positive comparison, never equality.
    No tensor values, GPU count copies, Float or expanded lookup enter here.
    The two GPU products are <=U**3<=2**60; the ratio>U branch uses <=U*(U+1).
    """
    numerator,denominator=ratio
    if numerator>count_bound*denominator:
        return count_bound+1,1,False
    original=Fraction(numerator,denominator)
    nearest=original.limit_denominator(count_bound)
    return nearest.numerator,nearest.denominator,nearest>original


def _cache_inputs(vectors,exponents):
    """Caller vectors[40,T,64]/int64 units[40] -> scalar T, same CUDA device."""
    if not isinstance(vectors,torch.Tensor) or vectors.ndim!=3:
        raise ValueError('Full40-head cache tensor required')
    count=vectors.shape[1]
    if not 0<count<=1024:
        raise ValueError('Physical cache count must be1..1024')
    device=vectors.device
    _check_tensors(((vectors,torch.int8,(40,count,64)),(exponents,torch.int64,(40,))),device)
    _check_units(exponents)
    return count,device


def classify_heads_codes(vectors,projection_exponents,*,prompt,ratio=(8,1)):
    """Caller actual signed8 cache[40,T,64], int64 signed9 units[40], scalar
    prompt/ratio -> fresh original-prefill classifier state. No cache is owned.

    count/device are input metadata, exponents aliases caller units. Canonical
    group[Q] maps query head to grouped key, shifts[Q] derives fixed units,
    alpha[Q] is the exact unsigned32 threshold represented in float64 before
    integer conversion. For prompt>96, query[Q,P,D],key[Q,T,D] are integer
    code values represented exactly in double, P=prompt-96; dots[Q,P,T] are
    integer dot sums. rows[P,1]/keys[1,T]/block[P,1] initialize cache-rank bands,
    above[Q,P,T] is strict comparison, inner/recent[Q] integer counts. flags[Q]
    are bool; records32 scalar dictionaries, copied exponents tuple40, prompt
    and policy pair preserve the original frozen-prefill contract. No unit or
    decision is refitted from decoded physical activations.
    """
    count,device=_cache_inputs(vectors,projection_exponents)
    if type(prompt)is not int or not 0<prompt<=count:
        raise ValueError('Original prefill prompt must fit current cache')
    ratio=_ratio(ratio)
    exponents=projection_exponents
    group=torch.arange(32,device=device)//8
    shifts=exponents[:32]+exponents[32+group]+5
    alpha=torch.ldexp(torch.full((32,),4.,device=device,dtype=torch.float64),8-shifts)
    if not bool(((alpha>0)&(alpha<(1<<32))&(alpha==alpha.floor())).all()):raise ValueError('Classifier threshold cannot fit native words')
    if prompt>96:
        query=vectors[:32,96:prompt].double();key=vectors[32+group].double()
        dots=(query@key.transpose(1,2)).to(torch.int64)
        rows=torch.arange(96,prompt,device=device)[:,None];keys=torch.arange(count,device=device)[None,:];block=rows//32*32
        above=dots>(dots[:,:,:32].amax(-1,keepdim=True)-alpha.to(torch.int64)[:,None,None])
        inner=(above&((keys>=block-64)&(keys<block-32))[None]).sum((1,2))
        recent=(above&((keys>=block)&(keys<=rows))[None]).sum((1,2))
    else:inner=recent=torch.zeros(32,device=device,dtype=torch.int64)
    numerator,denominator,include_equal=_ratio_proxy(ratio,count*count)
    lhs=recent*denominator;rhs=inner*numerator
    flags=lhs>rhs
    if include_equal:flags=flags|((lhs==rhs)&(inner>0))
    records=[dict(head=h,alpha=int(alpha[h]),score_shift=int(shifts[h]),inner=int(inner[h]),recent=int(recent[h]),streaming=bool(flags[h])) for h in range(32)]
    return dict(prompt=prompt,ratio=tuple(ratio),exponents=tuple(exponents.tolist()),flags=flags.contiguous(),shifts=shifts.contiguous(),records=records)


def _check_state(state,exponents,count,device):
    """Caller original-prefill state -> validation, not head reclassification.

    flags[Q] bool/shifts[Q] int64 stay on input device; expected[Q] derives only
    from fixed unit metadata. rows/flags/shifts below are host metadata lists,
    record is a scalar dictionary. No cache-vector value crosses to host, no
    current decode data is used to regenerate an original-prefill decision.
    This consistency check does not create a real cache/frame owner identity.
    """
    if type(state)is not dict or set(state)!={'prompt','ratio','exponents','flags','shifts','records'}:
        raise ValueError('Exact original-prefill state schema required')
    if type(state['prompt'])is not int or not 0<state['prompt']<=count:
        raise ValueError('Original-prefill prompt differs from cache domain')
    ratio=_ratio(state['ratio'])
    if (type(state['exponents'])is not tuple or len(state['exponents'])!=40 or
            any(type(v)is not int or not-256<=v<=255 for v in state['exponents'])or
            state['exponents']!=tuple(exponents.tolist())):
        raise ValueError('Original-prefill physical units differ')
    _check_tensors(((state['flags'],torch.bool,(32,)),(state['shifts'],torch.int64,(32,))),device)
    group=torch.arange(32,device=device)//8
    expected=exponents[:32]+exponents[32+group]+5
    if not bool(((expected>=-21)&(expected<=10)).all()) or not torch.equal(state['shifts'],expected):
        raise ValueError('Original-prefill score units differ')
    rows=state['records'];flags=state['flags'].tolist();shifts=state['shifts'].tolist()
    if type(rows)is not list or len(rows)!=32:
        raise ValueError('Exactly32 original-prefill classifier records required')
    for head,record in enumerate(rows):
        if (type(record)is not dict or set(record)!={'head','alpha','score_shift','inner','recent','streaming'} or
                any(type(record[key])is not int for key in('head','alpha','score_shift','inner','recent'))or
                type(record['streaming'])is not bool or record['head']!=head or
                record['score_shift']!=shifts[head] or record['alpha']!=1<<(10-shifts[head])or
                not 0<=record['inner']<=state['prompt']*32 or not 0<=record['recent']<=state['prompt']*32 or
                record['streaming']!=flags[head] or
                record['streaming']!=(record['recent']*ratio[1]>record['inner']*ratio[0])):
            raise ValueError('Original-prefill classifier record differs')


def attend_codes(vectors,projection_exponents,positions,origins,*,image_start,query_ranks,state):
    """Caller signed8 cache[40,T,64], fixed units[40], actual ordered original
    positions[T], canonical origins[576], scalar image start and query rank list
    -> owned probabilities int64[Q,M,T],accumulators int64[Q,M,D] carrying S32.

    count/device are metadata; exponents aliases units. identity[576]/roots[K]
    derive canonical current frame roots; image[T] selects actual image keys.
    selected[M]/rank[T]/group[Q] are fresh rank/physical-head indices. query
    [Q,M,D]/key[Q,T,D] and values[Q,T,D] are signed-code integers exactly carried
    in double; dots[Q,M,T] are bounded exact sums. allowed[Q,M,T] joins causal,
    original prefilling head flags, first32 sinks and recent32 cache ranks.
    root_rank[576],prefix[577,K],cutoffs[M] compute original-position partial
    multiplicities[M,T]; sizes[Q,M,T] has zeros for masked keys. scores/probs
    retain[Q,M,T]. No decoded physical Float cache or cache mutation exists.
    """
    count,device=_cache_inputs(vectors,projection_exponents)
    _check_tensors(((positions,torch.int64,(count,)),(origins,torch.int64,(576,))),device)
    if (type(image_start)is not int or not 0<=image_start<=(1<<63)-1 or
            type(query_ranks)is not list or not query_ranks or
            any(type(v)is not int or not 0<=v<count for v in query_ranks)or
            query_ranks!=sorted(set(query_ranks))):
        raise ValueError('Original image position and ordered query ranks required')
    if not bool((positions>=0).all())or not bool((positions[1:]>positions[:-1]).all()):
        raise ValueError('Actual cache positions must be ordered unique nonnegative originals')
    exponents=projection_exponents
    _check_state(state,exponents,count,device)
    identity=torch.arange(576,device=device);roots=(origins==identity).nonzero().flatten()
    if not roots.numel() or not bool(((origins>=0)&(origins<=identity)).all()) or not torch.equal(origins[origins],origins):raise ValueError('Noncanonical cumulative origins')
    # Nonnegative original positions/image_start make subtraction fit signed64.
    relative_positions=positions-image_start
    image=(relative_positions>=0)&(relative_positions<576)
    if not torch.equal(relative_positions[image],roots):raise ValueError('Image keys do not match surviving roots')
    selected=torch.tensor(query_ranks,device=device,dtype=torch.int64);rank=torch.arange(count,device=device)
    group=torch.arange(32,device=device)//8
    query=vectors[:32,selected].double();key=vectors[32+group].double()
    dots=(query@key.transpose(1,2)).to(torch.int64)
    allowed=(rank[None,:]<=selected[:,None])[None]&(~state['flags'][:,None,None]|((rank[None,:]<32)|(rank[None,:]>=selected[:,None]+1-32))[None])
    root_rank=torch.searchsorted(roots,origins)
    prefix=torch.nn.functional.pad(torch.nn.functional.one_hot(root_rank,num_classes=roots.numel()).cumsum(0),(0,0,1,0))
    multiplicities=torch.ones((len(query_ranks),count),device=device,dtype=torch.int64)
    # Equivalent mathematical clamp(diff+1,0,576), without INT64_MAX+1 wrap.
    cutoffs=(positions[selected]-image_start).clamp(-1,575)+1
    multiplicities[:,image]=prefix[cutoffs]
    sizes=multiplicities[None].expand(32,len(query_ranks),count).masked_fill(~allowed,0)
    scores=score_codes(dots,state['shifts'][:,None,None]);probs=probabilities(scores,sizes)
    values=vectors[36+group].double();accumulators=(probs.double()@values).to(torch.int64)
    if not bool(((accumulators>=-(1<<31))&(accumulators<(1<<31))).all()):raise ValueError('Native attention accumulation overflow')
    return dict(probabilities=probs.contiguous(),accumulators=accumulators.contiguous(),value_requests=int((sizes>0).sum()))


def _context_units(accumulators,value_exp,output_exponents,weight_exponents):
    """Caller signed32-valued int64 sums[Q,M,D], grouped value units[Q] and
    output-block units[B] -> fresh int64 common p[M], full range[-287,286].

    peaks[Q,M] is exact abs maximum; thresholds[32] are immutable integer
    positive-limit values for relative powers-22..9. Lower-bound indices[Q,M]
    select the MINIMAL unrounded fitting unit. candidate[Q,M] ignores zero heads
    using sentinel-4096 (below every admitted unit), then row p[M] is max.
    zero_rows[M] triggers the ACTIVE lower/legacy/expanded scalar unit interval;
    all lower/upper temporaries are scalar int64 tensors. No FLOAT context or
    CPU-dependent code values are constructed; no new units are clipped.
    """
    peaks=accumulators.abs().amax(dim=2)
    thresholds=torch.tensor(_HEAD_THRESHOLDS,device=accumulators.device,dtype=torch.int64)
    indices=torch.searchsorted(thresholds,peaks.contiguous(),right=False)
    candidate=value_exp[:,None]+indices-22
    pe=candidate.masked_fill(peaks==0,-4096).amax(dim=0)
    zero_rows=~peaks.ne(0).any(dim=0)
    if bool(zero_rows.any()):
        lower=torch.maximum(value_exp.max()-31,(output_exponents-weight_exponents-48).max())
        output_upper=(output_exponents-weight_exponents-1).min()
        legacy_upper=torch.minimum(value_exp.min(),output_upper)
        expanded_upper=torch.minimum(value_exp.min()+31,output_upper)
        if bool(lower>expanded_upper):raise ValueError('No bidirectional common unit even for zero context')
        upper=torch.where(lower<=legacy_upper,legacy_upper,expanded_upper)
        pe=torch.where(zero_rows,upper,pe)
    return pe


def project_output_codes(accumulators,projection_exponents,weights,weight_exponents,output_exponents,*,global_positions):
    """Caller int64 signed32 sums[Q,M,D], QKV units[40], signed8 weights[B,D,H],
    signed9 int64 weight/output-block units[B], original positions[M] -> seven
    fresh contiguous code/physical-sidecar tensors. Q32,B32,D64,H2048,M1..1024.

    count/device are metadata. value_exp[Q] selects the ACTUAL grouped V unit;
    pe[M] is exact integer common input unit, independent of output block axes.
    zero-row source precedence is in _context_units. transfer[Q,M] ranges-31..31;
    shifts[M,B] ranges1..48. magnitude[Q,M,D]/denominator[Q,M,1] represent exact
    dyadic transfer divided by65535, single-round ties-away then signed8 clamp.
    context_codes[M,H] concatenates32query heads in original feature order.
    raw[M,B,D] is canonical exact signed32 dot promoted to contiguous signed64;
    codes[M,B,D] is canonical requantization in caller fixed output units.
    p,output_exponents and global_positions clones own separate backing storage.
    Full software p is[-287,286], nonzero-only[-278,264]; no hardware-width clamp.
    """
    if not isinstance(accumulators,torch.Tensor)or accumulators.ndim!=3:
        raise ValueError('Full signed32-valued context tensor required')
    count=accumulators.shape[1];device=accumulators.device
    if not 0<count<=1024:
        raise ValueError('Selected-query count must be1..1024')
    _check_tensors(((accumulators,torch.int64,(32,count,64)),(projection_exponents,torch.int64,(40,)),
        (weights,torch.int8,(32,64,2048)),(weight_exponents,torch.int64,(32,)),
        (output_exponents,torch.int64,(32,)),(global_positions,torch.int64,(count,))),device)
    _check_units(projection_exponents,weight_exponents,output_exponents)
    if not bool(((accumulators>=-(1<<31))&(accumulators<(1<<31))).all()):
        raise ValueError('Context accumulators must fit signed32')
    if not bool((global_positions>=0).all())or global_positions.unique().numel()!=count:
        raise ValueError('Actual original positions must be unique and nonnegative')
    value_exp=projection_exponents[36+torch.arange(32,device=device)//8]
    pe=_context_units(accumulators,value_exp,output_exponents,weight_exponents)
    transfer=value_exp[:,None]-pe[None,:]
    if not bool(((transfer>=-31)&(transfer<=31)).all()):raise ValueError('Context units cannot fit bidirectional transfer primitive')
    shifts=output_exponents[None,:]-pe[:,None]-weight_exponents[None,:]
    if not bool(((shifts>0)&(shifts<49)).all()):raise ValueError('Output units cannot fit projection primitive')
    magnitude=accumulators.abs().to(torch.int64)<<transfer.clamp_min(0)[:,:,None]
    denominator=torch.full_like(transfer,65535)<<(-transfer).clamp_min(0)
    denominator=denominator[:,:,None]
    context_codes=(((magnitude+denominator//2)//denominator)*torch.where(accumulators<0,-1,1)).clamp(-128,127).to(torch.int8).permute(1,0,2).reshape(count,2048).contiguous()
    raw=_dot(context_codes,weights.reshape(2048,2048)).to(torch.int64).reshape(count,32,64).contiguous()
    codes=_requantize(raw,shifts[:,:,None],8).to(torch.int8).contiguous()
    return dict(context_codes=context_codes,context_exponents=pe.clone().contiguous(),raw=raw,codes=codes,
                shifts=shifts.contiguous(),output_exponents=output_exponents.clone(),global_positions=global_positions.clone())
