"""Exact-code query/key/value (QKV) projection reference.

Consumes already-normalized signed8 C codes; it never decodes or re-quantizes
activations. The current trained matrix/unit/rotary table provenance remains
caller-owned. Only the existing full2048->40x64 geometry on one CUDA (Compute
Unified Device Architecture) device is supported. No cache or model is loaded.

_dot and _requantize below are exact source extractions from the unchanged
tri_oracle_integer_reference.py. No new scalar production arithmetic, central
processing unit fallback, automatic compiler or fitted units are introduced.
There is no loss function, optimizer, trainable parameter or accuracy claim.
"""
import torch
import torch.nn.functional as functional


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

def project_qkv_codes(codes, eA, weights, weight_exponents, output_exponents,
                      cosine, sine, *, global_positions):
    """Caller codes[M,H] int8, H2048, M1..1024; eA[M] int64 signed9 units.

    weights[A,D,H] int8, A40 heads (32query/4key/4value), D64 features/head;
    weight_exponents[A]/output_exponents[A] int64 signed9 caller bundle units.
    cosine/sine[M,D/2] int16 signed Q14 caller rotary-position words;
    global_positions[M] int64 unique nonnegative original positions, unsorted.
    All eight inputs are caller-initialized contiguous strided same-CUDA-device
    tensors and remain unchanged. This entry point does not verify their
    trained weight or position/rotary producer provenance.

    inputs is a tuple of caller tensors; count is their scalar row count;
    expected is a tuple of scalar dtype/shape metadata. value/dtype/shape and
    units are validation-loop aliases, not new inputs or arithmetic choices.
    activation[M,H] is a fresh clone initialized from exact caller codes;
    ae[M,1] is an eA view for the unchanged descriptor equations. common[] is
    max(ae); biases[M], fractions[A]=14 for query/key or0 for value,
    base[A] and effective[A,M] are initialized solely from the three supplied
    unit vectors. Every shift is checked before any dot; none is clipped.

    raw[A,M,D] is exact signed32 dot data promoted to signed64 then presented
    contiguous. rotated[A,M,D] is a fresh raw clone; low/high[A36,M,D/2] are
    views of the unmodified raw halves. Local cosine/sine[M,D/2] are signed64
    conversions of the caller words. The first36 heads use split-half rotary
    products; the last4 value heads remain raw. vectors[A,M,D] is signed8
    ties-away/saturated requantization. Return exactly seven separately owned
    contiguous tensors: activation, eA copy, raw, vectors, base, biases and
    original-position copy. Existing Torch operations follow current stream.
    """
    inputs = (codes, eA, weights, weight_exponents, output_exponents,
              cosine, sine, global_positions)
    if any(not isinstance(value, torch.Tensor) for value in inputs):
        raise ValueError('All projection inputs must be tensors')
    if codes.ndim != 2 or not 0 < codes.shape[0] <= 1024:
        raise ValueError('Projection rows must be1..1024 with hidden dimension2048')
    count = codes.shape[0]
    expected = ((torch.int8, (count, 2048)), (torch.int64, (count,)),
                (torch.int8, (40, 64, 2048)), (torch.int64, (40,)),
                (torch.int64, (40,)), (torch.int16, (count, 32)),
                (torch.int16, (count, 32)), (torch.int64, (count,)))
    if codes.device.type != 'cuda' or any(
            value.dtype != dtype or tuple(value.shape) != shape or
            value.layout != torch.strided or not value.is_contiguous() or
            value.device != codes.device
            for value, (dtype, shape) in zip(inputs, expected)):
        raise ValueError('Projection dtype, geometry, layout, contiguity or CUDA device mismatch')
    for units in (eA, weight_exponents, output_exponents):
        if not bool(((units >= -256) & (units <= 255)).all()):
            raise ValueError('Projection unit vectors must fit signed9')
    if not bool((global_positions >= 0).all()) or global_positions.unique().numel() != count:
        raise ValueError('Original positions must be unique and nonnegative')

    # Exact supplied codes/units replace only the old floating _quantize step.
    activation = codes.clone()
    ae = eA[:, None]
    fractions=torch.tensor([14]*36+[0]*4,device=codes.device,dtype=torch.int64)
    common=ae.max();bias=common-ae[:,0];base=output_exponents-common-weight_exponents+fractions
    effective=base[:,None]+bias[None,:]
    if not bool(((base>=0)&(base<=63)).all()&((bias>=0)&(bias<=63)).all()&((effective>0)&(effective<63)).all()):raise ValueError('Projection descriptor cannot represent these units')

    # Canonical native signed8 dot and exact original split-half rotation.
    raw=_dot(activation,weights.reshape(2560,2048)).reshape(count,40,64).permute(1,0,2).to(torch.int64).contiguous()
    rotated=raw.clone();low=raw[:36,:,:32];high=raw[:36,:,32:]
    cosine=cosine.to(torch.int64);sine=sine.to(torch.int64)
    rotated[:36,:,:32]=low*cosine-high*sine;rotated[:36,:,32:]=high*cosine+low*sine
    vectors=_requantize(rotated,effective[:,:,None],8).to(torch.int8).contiguous()
    return dict(activation=activation, activation_exponents=eA.clone(),
                raw=raw, vectors=vectors, base_shifts=base, biases=bias,
                global_positions=global_positions.clone())
