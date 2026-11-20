"""Pack fixed-order cells within per-cell integer bounds."""
import numpy as np


def pack_row(widths, desired, lower, upper):
    widths, desired, lower, upper = [np.asarray(x, dtype=np.int64) for x in (widths,desired,lower,upper)]
    if not (widths.shape == desired.shape == lower.shape == upper.shape) or widths.ndim != 1:
        raise ValueError('One width, desired coordinate and bound pair per cell is required')
    if np.any(widths<=0) or np.any(lower>upper):
        raise ValueError('Invalid physical width or bounds')
    if not len(widths):
        return desired.copy()
    # Cell vectors [cell]. With p_i=sum of earlier widths, x_i=p_i+z_i
    # is nonoverlapping iff z_i is nondecreasing. The feasible envelopes are
    # the prefix maximum of lower_i-p_i and suffix minimum of upper_i-p_i.
    prefix = np.cumsum(widths)-widths
    early = np.maximum.accumulate(lower-prefix)
    late = np.minimum.accumulate((upper-prefix)[::-1])[::-1]
    if np.any(early>late):
        raise ValueError('Infeasible row bounds')
    z = np.maximum.accumulate(np.minimum(np.maximum(desired-prefix,lower-prefix),late))
    # Every preceding clipped value is <= its suffix bound, which is <=
    # the current suffix bound. Thus prefix-max preserves every upper bound.
    return prefix+z
