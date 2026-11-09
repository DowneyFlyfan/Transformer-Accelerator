"""Exact CUDA integer arithmetic for the locally configured feed-forward path.

M=token rows, H=hidden features, K=intermediate channels, O=output features.
This software reference computes dense matrices, then applies predicted zeros;
it establishes no hardware cycle, traffic, energy or task-accuracy result.
"""
import torch
import torch.nn.functional as functional
from tri_oracle_model_reference import silu_code


def _quantize(values, per_row=False):
    """values: trained float matrix[K,H]/[O,K] or activations[M,H], from caller.
    maximum/mantissa/exponent are scalar for weights or[M,1] for activations.
    codes preserve values shape, signed8; exponent gives physical scale2**e.

    For maximum=m*2**e with .5<=m<1, scale exponent e-7 suffices exactly when
    m*128<=127. Otherwise e-6 is required. This avoids logarithm boundary error.
    """
    maximum=values.abs().amax(dim=-1,keepdim=True) if per_row else values.abs().amax()
    mantissa,exponent=torch.frexp(maximum)
    exponent=exponent-7+(mantissa>127/128).to(torch.int32)
    exponent=torch.where(maximum==0,torch.zeros_like(exponent),exponent)
    scaled=torch.ldexp(values,-exponent)  # same axes as values, floating code units
    codes=(scaled.sign()*torch.floor(scaled.abs()+.5)).clamp(-128,127).to(torch.int8)
    return codes.contiguous(),exponent


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


class IntegerFeedForwardReference:
    @torch.inference_mode()
    def __init__(self,gate,up,down,epsilon):
        """gate/up[K,H], down[O,K]: trained finite floating tensors on one GPU.
        epsilon: scalar actual post-attention root-mean-square norm epsilon.
        Stores signed8 weight codes with the same shapes and scalar exponents.
        Sign tables[K,H] map negative to-1 and nonnegative (including zero) to+1.
        silu_response[65536] enumerates the exact sampled/interpolated scalar
        transfer function in software; it is not a proposed hardware table size.
        """
        if gate.ndim!=2 or up.shape!=gate.shape or down.ndim!=2 or down.shape[1]!=gate.shape[0]:
            raise ValueError("Incompatible feed-forward matrix shapes")
        if any(not value.is_cuda or value.device!=gate.device or not bool(torch.isfinite(value).all()) for value in (gate,up,down)) or epsilon<0:
            raise ValueError("Finite matrices on one graphics processor and nonnegative epsilon required")
        self.hidden=gate.shape[1];self.channels=gate.shape[0]
        if max(self.hidden,self.channels)>65535 or self.hidden%16 or self.channels%16 or down.shape[0]%8:
            raise ValueError("Unsupported integer matrix alignment or accumulation bound")
        self.device=gate.device;self.epsilon=float(epsilon)
        self.gate,self.gate_exponent=_quantize(gate)
        self.up,self.up_exponent=_quantize(up)
        self.down,self.down_exponent=_quantize(down)
        self.gate_exponent=int(self.gate_exponent);self.up_exponent=int(self.up_exponent);self.down_exponent=int(self.down_exponent)
        self.gate_sign=torch.where(self.gate<0,-1,1).to(torch.int8)  # [K,H], supplied quantized weight signs
        self.up_sign=torch.where(self.up<0,-1,1).to(torch.int8)  # [K,H]
        self.silu_response=torch.tensor([silu_code(value) for value in range(-32768,32768)],dtype=torch.int64,device=self.device)  # [65536], exact signed16 gate-code transfer response

    @torch.inference_mode()
    def evaluate(self,activation,residual,*,prune,maximum_up_gain_bits=7,down_shift_offset=-1,gate_threshold=0,up_window=0):
        """activation/residual[M,H]: actual normalized input/pre-scale residual.
        Scalar prune and format/threshold arguments are local software policy.
        Gain may be negative (up attenuation); it is bounded by the activation-derived
        up shift, never a dot maximum. The hardware UP_SHIFT stays nonnegative;
        down shift=max(0,gain+offset). All resulting shifts must fit hardware0..63.
        Returns raw signed32[M,O], dequantized float32[M,O], and diagnostic stats.
        Stats norm_codes[M,H]; all other tensor statistics have one entry per row.
        """
        if activation.ndim!=2 or activation.shape!=residual.shape or activation.shape[1]!=self.hidden or activation.shape[0]==0:
            raise ValueError("Expected matching nonempty token matrices")
        if activation.device!=self.device or residual.device!=self.device or not bool(torch.isfinite(activation).all() & torch.isfinite(residual).all()) or up_window<0:
            raise ValueError("Invalid activation, residual, device or threshold")
        codes,exponent=_quantize(activation,per_row=True)  # [M,H], exponent[M,1]
        gate_shift=-(exponent+self.gate_exponent+8)  # [M,1], Q8 conversion shift
        original_up_shift=-(exponent+self.up_exponent+8)  # [M,1]
        gain=torch.minimum(original_up_shift,torch.full_like(original_up_shift,maximum_up_gain_bits))  # [M,1], input-derived valid precision gain
        up_shift=original_up_shift-gain  # [M,1]
        down_shift=(gain+down_shift_offset).clamp_min(0)  # [M,1], fixed policy relative to gain
        for shift in (gate_shift,up_shift,down_shift):
            if not bool(((shift>=0)&(shift<=63)).all()):
                raise ValueError("Format cannot be represented by existing hardware shifts")
        denominator=(residual.double().square().mean(dim=-1,keepdim=True)+self.epsilon).sqrt()  # [M,1], pre-learned-scale normalization
        if not bool((denominator>0).all()):
            raise ValueError("Undefined root-mean-square normalization")
        normalized=residual.double()*256/denominator  # [M,H], Q8 floating code units
        norm_codes=(normalized.sign()*torch.floor(normalized.abs()+.5)).clamp(-32768,32767).to(torch.int32)  # [M,H], exact local prediction encoding
        outliers=norm_codes.abs()>768  # [M,H], strict three-sigma mask
        outlier_count=outliers.sum(dim=-1,dtype=torch.int32)  # [M]
        signs=(torch.where(norm_codes<0,-1,1)*outliers).to(torch.int8)  # [M,H], sign0 where no outlier
        gate_margin=_dot(signs,self.gate_sign)  # [M,K], exact same-sign minus opposite-sign counts
        up_margin=_dot(signs,self.up_sign)  # [M,K]
        skip=(outlier_count[:,None]>0)&(gate_margin<=gate_threshold)&(up_margin>=-up_window)&(up_margin<=up_window)  # [M,K], current local branch intersection
        gate_dot=_dot(codes,self.gate)  # [M,K], exact signed32 dot sums
        up_dot=_dot(codes,self.up)  # [M,K]
        gate_q8=_requantize(gate_dot,gate_shift,16)  # [M,K], signed16 Q8 gate
        up_q8=_requantize(up_dot,up_shift,16)  # [M,K], signed16 Q8 with compensated gain
        products=self.silu_response[gate_q8+32768]*up_q8  # [M,K], signed64 integer products
        gated=_requantize(products,torch.full_like(down_shift,8),16)  # [M,K], signed16 gated Q8
        down_input=_requantize(gated,down_shift,8).to(torch.int8)  # [M,K], signed8 down inputs
        if prune:down_input=down_input.masked_fill(skip,0)
        raw=_dot(down_input,self.down)  # [M,O], exact signed32 output accumulations
        values=torch.ldexp(raw.float(),self.down_exponent+down_shift-8-gain)  # [M,O], compensated floating interpretation
        stats={"norm_codes":norm_codes,"up_gain_bits":gain[:,0],"gate_shift":gate_shift[:,0],"up_shift":up_shift[:,0],"down_shift":down_shift[:,0],"outlier_count":outlier_count,"skip_count":skip.sum(dim=-1,dtype=torch.int32),"up_endpoint_codes":((up_q8==-32768)|(up_q8==32767)).sum(dim=-1,dtype=torch.int32),"gated_endpoint_codes":((gated==-32768)|(gated==32767)).sum(dim=-1,dtype=torch.int32)}
        return raw,values,stats
