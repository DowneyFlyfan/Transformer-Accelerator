"""Bidirectional context conversion for independently scaled attention heads.

Standalone extension: the integrated chip still needs the direction control.
No training, fitted targets, complete-integer/model or paper-matching claim.
"""
import torch
from tri_oracle_integer_reference import _quantize,_dot,_requantize

@torch.inference_mode()
def project_output(accumulators,projection_exponents,weights,weight_exponents,output_exponents):
    """accumulators[Q,N,D] actual signed32 attention sums, powers[A] fixed.
    weights[Q,D,H] encoded output rows, weight/output exponents[Q] frozen.
    contexts[N,H] interpreted from true grouped-value units and divisor65535;
    source-input exponents[N] define exact integer context transfer. raw[N,Q,D]
    and codes same axes are native dot and signed8 output-interface values.
    Nonzero rows require bidirectional transfer-31..31/output-shift1..48
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
        # the signed-transfer and existing output requantization fields.
        lower=torch.maximum(value_exp.max()-31,(output_exponents-weight_exponents-48).max())
        output_upper=(output_exponents-weight_exponents-1).min()
        legacy_upper=torch.minimum(value_exp.min(),output_upper)
        expanded_upper=torch.minimum(value_exp.min()+31,output_upper)
        if bool(lower>expanded_upper):raise ValueError('No bidirectional common unit even for zero context')
        # Preserve every previously valid zero descriptor; otherwise use a unit
        # in the expanded signed-transfer interval, without changing any code.
        upper=torch.where(lower<=legacy_upper,legacy_upper,expanded_upper)
        pe=torch.where(zero_rows[:,None],upper.to(pe.dtype),pe)
    transfer=value_exp[:,None]-pe[:,0][None,:]
    if not bool(((transfer>=-31)&(transfer<=31)).all()):raise ValueError('Context units cannot fit bidirectional transfer primitive')
    # Both tensors[Q,N,1] encode the exact rational binary transfer. Nonnegative
    # shifts preserve legacy bytes; right shifts require the new standalone RTL.
    magnitude=accumulators.abs().to(torch.int64)<<transfer.clamp_min(0)[:,:,None]
    denominator=torch.full_like(transfer,65535)<<(-transfer).clamp_min(0)
    denominator=denominator[:,:,None]
    context_codes=(((magnitude+denominator//2)//denominator)*torch.where(accumulators<0,-1,1)).clamp(-128,127).to(torch.int8).permute(1,0,2).reshape(count,2048)
    raw=_dot(context_codes,weights.reshape(2048,2048)).to(torch.int64).reshape(count,32,64)
    shifts=output_exponents[None,:]-pe-weight_exponents[None,:]
    if not bool(((shifts>0)&(shifts<49)).all()):raise ValueError('Output units cannot fit projection primitive')
    codes=_requantize(raw,shifts[:,:,None],8).to(torch.int8)
    return dict(context_codes=context_codes,context_exponents=pe[:,0],raw=raw,codes=codes,shifts=shifts)
