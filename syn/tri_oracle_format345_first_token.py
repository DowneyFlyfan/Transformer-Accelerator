"""Protect global token0 while preserving existing ordinary-row arithmetic.

M=contiguous token rows,H=input features,O=output features;one model sequence.
The caller supplies its global token offset. A one-row incremental decode must
use the ordinary policy whenever its offset is positive. This is a local
precision-control reconstruction,not a disclosed paper configuration.
"""
import torch
from tri_oracle_format335_policy import evaluate_policy


def evaluate_protected(reference,activation,residual,ordinary_policy,first_policy,token_offset,*,prune):
    """reference: unchanged trained integer arithmetic object.
    activation/residual[M,H]: caller normalized input/pre-scale residual.
    ordinary_policy: frozen335 exponent table/fallback;first_policy: frozen322
    scalar gain cap/down offset. token_offset: caller's nonnegative Python int.
    prune: caller Boolean for the existing unchanged sign-margin prediction.

    first raw/values[1,O],stats[1,...] use the accepted first-token pair.
    rest raw/values[M-1,O],stats[M-1,...] come from existing ordinary dispatch.
    Concatenated outputs[M,O] and all statistics[M,...] preserve token order.
    No model logits,target values,answers or calibration updates are consumed.
    """
    if type(token_offset) is not int or token_offset<0:
        raise ValueError('A nonnegative integer global token offset is required')
    if activation.ndim!=2 or activation.shape!=residual.shape or activation.shape[0]==0:
        raise ValueError('Matching nonempty activation/residual matrices required')
    if token_offset>0:
        return evaluate_policy(reference,activation,residual,ordinary_policy,prune=prune)
    first=reference.evaluate(activation[:1],residual[:1],prune=prune,
        maximum_up_gain_bits=first_policy['maximum_up_gain_bits'],
        down_shift_offset=first_policy['down_shift_offset'],gate_threshold=0,up_window=0)
    if activation.shape[0]==1:return first
    rest=evaluate_policy(reference,activation[1:],residual[1:],ordinary_policy,prune=prune)
    return (torch.cat([first[0],rest[0]],dim=0),torch.cat([first[1],rest[1]],dim=0),
            {key:torch.cat([first[2][key],rest[2][key]],dim=0) for key in first[2]})
