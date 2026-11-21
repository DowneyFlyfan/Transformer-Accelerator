"""Batched exact local score/softmax equations on CPU or GPU integer tensors.

Input/output tensors[...rows,K] retain caller row axes, K<=1024 key slots.
Scores are signed16 codes; sizes are unsigned10 bit multiplicities. No model
weights, fitting, loss or optimizer. Constants match existing mapped modules.
"""
if not __debug__:raise RuntimeError('Assertions required')
import math
import torch

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
