"""Dispatch input rows to calibrated formats without changing integer arithmetic.

M=token rows,H=input features,O=output features. Policies use only the exponent
already derived from each activation row's magnitude. No answers, model logits,
target values or prediction outcomes select formats at inference time.
"""
import torch
from tri_oracle_integer_reference import _quantize


def evaluate_policy(reference,activation,residual,policy,*,prune):
    """reference: existing trained IntegerFeedForwardReference, unchanged.
    activation/residual[M,H]: caller's normalized activation/pre-scale residual.
    policy: frozen scalar metadata with fallback pair and exponent bucket list.
    prune: caller Boolean selecting the existing unchanged sign-margin mask.

    exponent[M] is activation-derived; table maps scalar exponents to settings.
    positions[B] selects B possibly nonconsecutive original rows per exponent.
    raw/values[B,O],stats norm_codes[B,H] and other stats[B] come from reference.
    outputs[M,O] and statistics[M,...] are initialized empty, then every original
    row is written exactly once with index_copy. Preserve caller row order.
    """
    if activation.ndim!=2 or activation.shape!=residual.shape or activation.shape[0]==0:
        raise ValueError('Matching nonempty activation/residual matrices required')
    table={item['activation_exponent']:item for item in policy['buckets']}
    if len(table)!=len(policy['buckets']):
        raise ValueError('Duplicate activation-exponent buckets')
    exponent=_quantize(activation,per_row=True)[1][:,0]  # [M], input-only integer exponent.
    outputs=None  # (raw[M,O],values[M,O],statistics), allocated from first actual group.
    for value in sorted(set(exponent.tolist())):
        positions=torch.nonzero(exponent==value,as_tuple=True)[0]  # [B], original row indices.
        setting=table.get(value,policy['fallback'])  # Scalar frozen gain cap/down offset.
        raw,values,stats=reference.evaluate(activation.index_select(0,positions),
            residual.index_select(0,positions),prune=prune,
            maximum_up_gain_bits=setting['maximum_up_gain_bits'],
            down_shift_offset=setting['down_shift_offset'],gate_threshold=0,up_window=0)
        if outputs is None:
            outputs=(torch.empty((activation.shape[0],raw.shape[1]),dtype=raw.dtype,device=raw.device),
                     torch.empty((activation.shape[0],values.shape[1]),dtype=values.dtype,device=values.device),
                     {key:torch.empty((activation.shape[0],*item.shape[1:]),dtype=item.dtype,device=item.device)
                      for key,item in stats.items()})
        outputs[0].index_copy_(0,positions,raw)
        outputs[1].index_copy_(0,positions,values)
        for key,item in stats.items():outputs[2][key].index_copy_(0,positions,item)
    return outputs
