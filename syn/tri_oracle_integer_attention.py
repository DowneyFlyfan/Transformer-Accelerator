"""Reusable physical-format attention equations for the 22-layer model driver.

T=1..1024 cached tokens; N selected queries; H=2048 hidden features;
A=40 projected heads (32query,4key,4value), Q=32 query heads,D=64features.
All weights/exponents/codes are caller-owned frozen inputs, never fitted here.
No loss, optimizer, floating-attention substitution or benchmark labels.
"""
import torch
from tri_oracle_integer_reference import _quantize,_dot,_requantize
from tri_oracle_attention_arithmetic import score_codes,probabilities

@torch.inference_mode()
def encode_head_weights(weights):
    """weights[A,R,H] frozen floating caller parameters. Codes preserve shape;
    exponents[A] derive only from each head's full trained matrix[R,H].
    """
    if weights.ndim!=3 or not bool(torch.isfinite(weights).all()):raise ValueError('Expected finite head matrices')
    codes,exponents=_quantize(weights.flatten(1),per_row=True)
    return codes.reshape_as(weights),exponents[:,0].to(torch.int64)

@torch.inference_mode()
def project_qkv(hidden,weights,weight_exponents,output_exponents,cosine,sine):
    """hidden[T,H] current normalized floating caller input; weights[A,D,H]
    signed8 encoded trained matrices, exponents[A] immutable physical units.
    cosine/sine[T,D/2] signed16 Q14 words from caller's current original positions.
    Activation[T,H]/exponent[T,1] come from input-only quantization. raw[A,T,D]
    is signed32 dot data promoted to64 before rotation; vectors same axes signed8.
    base[A],bias[T],effective[A,T] match existing projection descriptor fields.
    """
    count=hidden.shape[0]
    if hidden.shape!=(count,2048) or not 0<count<=1024 or weights.shape!=(40,64,2048) or weights.dtype!=torch.int8:raise ValueError('Invalid projection shape')
    if cosine.shape!=sine.shape or cosine.shape!=(count,32):raise ValueError('Invalid rotary words')
    if weight_exponents.shape!=(40,) or output_exponents.shape!=(40,):raise ValueError('Invalid projection units')
    activation,ae=_quantize(hidden,per_row=True)
    raw=_dot(activation,weights.reshape(2560,2048)).reshape(count,40,64).permute(1,0,2).to(torch.int64)
    rotated=raw.clone();low=raw[:36,:,:32];high=raw[:36,:,32:]
    cosine=cosine.to(torch.int64);sine=sine.to(torch.int64)
    rotated[:36,:,:32]=low*cosine-high*sine;rotated[:36,:,32:]=high*cosine+low*sine
    fractions=torch.tensor([14]*36+[0]*4,device=hidden.device,dtype=torch.int64)
    common=ae.max();bias=common-ae[:,0];base=output_exponents-common-weight_exponents+fractions
    effective=base[:,None]+bias[None,:]
    if not bool(((base>=0)&(base<=63)).all()&((bias>=0)&(bias<=63)).all()&((effective>0)&(effective<63)).all()):raise ValueError('Projection descriptor cannot represent these units')
    vectors=_requantize(rotated,effective[:,:,None],8).to(torch.int8)
    return dict(activation=activation,activation_exponents=ae[:,0],raw=raw,vectors=vectors,base_shifts=base,biases=bias)

@torch.inference_mode()
def classify_heads(vectors,exponents,prompt,ratio=(8,1)):
    """vectors[A,T,D] signed8 actual cache; exponents[A] fixed powers.
    prompt scalar prefill length and ratio are unchanged native policy inputs.
    dots[Q,P,T],P=max(0,prompt-96), use actual projected vectors. Band masks
    [P,T] and comparisons[Q,P,T] produce integer inner/recent counts[Q].
    Cached state owns copied units/flags[Q] and frozen scalar records; decode
    must reuse it, rather than refitting decisions on later query rows.
    """
    count=vectors.shape[1]
    if vectors.shape!=(40,count,64) or vectors.dtype!=torch.int8 or not 0<prompt<=count<=1024:raise ValueError('Invalid projected cache')
    if exponents.shape!=(40,) or len(ratio)!=2 or ratio[0]<0 or ratio[1]<=0:raise ValueError('Invalid classifier units/policy')
    device=vectors.device;group=torch.arange(32,device=device)//8
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
    flags=recent*ratio[1]>inner*ratio[0]
    records=[dict(head=h,alpha=int(alpha[h]),score_shift=int(shifts[h]),inner=int(inner[h]),recent=int(recent[h]),streaming=bool(flags[h])) for h in range(32)]
    return dict(prompt=prompt,ratio=tuple(ratio),exponents=tuple(exponents.tolist()),flags=flags,shifts=shifts,records=records)

@torch.inference_mode()
def attend(vectors,exponents,positions,origins,image_start,query_ranks,state):
    """vectors[A,T,D]/exponents[A] actual cache and fixed powers; positions[T]
    sorted original positions; origins[576] cumulative representatives, from
    current merger. query_ranks[N] ordered selected cache ranks. state is the
    original prefill classifier record. Actual scores/probabilities/sizes have
    [Q,N,T], accumulators[Q,N,D]. No query can use a future key or zero-sized
    image group. Appended decode rows reuse prefill flags and full image sizes.
    """
    count=vectors.shape[1];device=vectors.device
    positions=torch.as_tensor(positions,device=device,dtype=torch.int64);origins=torch.as_tensor(origins,device=device,dtype=torch.int64)
    if vectors.shape!=(40,count,64) or not 0<count<=1024 or vectors.dtype!=torch.int8:raise ValueError('Invalid projected cache')
    if tuple(exponents.tolist())!=state['exponents'] or not 0<state['prompt']<=count:raise ValueError('Cached classifier units/prompt differ')
    if not query_ranks or query_ranks!=sorted(set(query_ranks)) or query_ranks[0]<0 or query_ranks[-1]>=count:raise ValueError('Invalid query selection')
    if positions.shape!=(count,) or origins.shape!=(576,) or not bool((positions[1:]>positions[:-1]).all()):raise ValueError('Invalid current positions/origins')
    identity=torch.arange(576,device=device);roots=(origins==identity).nonzero().flatten()
    if not roots.numel() or not bool(((origins>=0)&(origins<=identity)).all()) or not torch.equal(origins[origins],origins):raise ValueError('Noncanonical cumulative origins')
    image=(positions>=image_start)&(positions<image_start+576)
    if not torch.equal(positions[image]-image_start,roots):raise ValueError('Image keys do not match surviving roots')
    selected=torch.tensor(query_ranks,device=device,dtype=torch.int64);rank=torch.arange(count,device=device)
    group=torch.arange(32,device=device)//8
    query=vectors[:32,selected].double();key=vectors[32+group].double()
    dots=(query@key.transpose(1,2)).to(torch.int64)
    allowed=(rank[None,:]<=selected[:,None])[None]&(~state['flags'][:,None,None]|((rank[None,:]<32)|(rank[None,:]>=selected[:,None]+1-32))[None])
    root_rank=torch.searchsorted(roots,origins)
    prefix=torch.nn.functional.pad(torch.nn.functional.one_hot(root_rank,num_classes=roots.numel()).cumsum(0),(0,0,1,0))
    multiplicities=torch.ones((len(query_ranks),count),device=device,dtype=torch.int64)
    multiplicities[:,image]=prefix[(positions[selected]-image_start+1).clamp(0,576)]
    sizes=multiplicities[None].expand(32,len(query_ranks),count).masked_fill(~allowed,0)
    scores=score_codes(dots,state['shifts'][:,None,None]);probs=probabilities(scores,sizes)
    values=vectors[36+group].double();accumulators=(probs.double()@values).to(torch.int64)
    if not bool(((accumulators>=-(1<<31))&(accumulators<(1<<31))).all()):raise ValueError('Native attention accumulation overflow')
    return dict(probabilities=probs,accumulators=accumulators,value_requests=int((sizes>0).sum()))

@torch.inference_mode()
def project_output(accumulators,projection_exponents,weights,weight_exponents,output_exponents):
    """accumulators[Q,N,D] actual signed32 attention sums, powers[A] fixed.
    weights[Q,D,H] encoded output rows, weight/output exponents[Q] frozen.
    contexts[N,H] interpreted from true grouped-value units and divisor65535;
    source-input exponents[N] define exact integer context transfer. raw[N,Q,D]
    and codes same axes are native dot and signed8 output-interface values.
    Nonzero rows require the existing left-transfer0..31/output-shift1..48
    format; unsupported units raise ValueError. Zero rows select any common
    exponent in that same hardware interval without changing a numerical code.
    """
    count=accumulators.shape[1];device=accumulators.device
    if accumulators.shape!=(32,count,64) or weights.shape!=(32,64,2048) or weights.dtype!=torch.int8:raise ValueError('Invalid output projection shape')
    if projection_exponents.shape!=(40,) or weight_exponents.shape!=(32,) or output_exponents.shape!=(32,):raise ValueError('Invalid output units')
    accumulators=accumulators.to(torch.int64)
    value_exp=projection_exponents[36+torch.arange(32,device=device)//8]
    contexts=(accumulators.double()*torch.exp2(value_exp.double())[:,None,None]/65535).permute(1,0,2).reshape(count,2048)
    unused,pe=_quantize(contexts,per_row=True)
    zero_rows=~accumulators.ne(0).any(dim=(0,2))
    if bool(zero_rows.any()):
        # An all-zero context has no physical exponent. Select a unit satisfying
        # every existing five-bit transfer and output requantization field.
        lower=torch.maximum(value_exp.max()-31,(output_exponents-weight_exponents-48).max())
        upper=torch.minimum(value_exp.min(),(output_exponents-weight_exponents-1).min())
        if bool(lower>upper):raise ValueError('No native common unit even for zero context')
        pe=torch.where(zero_rows[:,None],upper.to(pe.dtype),pe)
    transfer=value_exp[:,None]-pe[:,0][None,:]
    if not bool(((transfer>=0)&(transfer<=31)).all()):raise ValueError('Context units cannot fit transfer primitive')
    magnitude=accumulators.abs().to(torch.int64)<<transfer[:,:,None]
    context_codes=(((magnitude+32767)//65535)*torch.where(accumulators<0,-1,1)).clamp(-128,127).to(torch.int8).permute(1,0,2).reshape(count,2048)
    raw=_dot(context_codes,weights.reshape(2048,2048)).to(torch.int64).reshape(count,32,64)
    shifts=output_exponents[None,:]-pe-weight_exponents[None,:]
    if not bool(((shifts>0)&(shifts<49)).all()):raise ValueError('Output units cannot fit projection primitive')
    codes=_requantize(raw,shifts[:,:,None],8).to(torch.int8)
    return dict(context_codes=context_codes,context_exponents=pe[:,0],raw=raw,codes=codes,shifts=shifts)
