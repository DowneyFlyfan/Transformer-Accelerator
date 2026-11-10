"""Scalar reference for the paper's raster-order sign-based token merging."""


def merge_signs(signs, image_width, sign_width, minimum_matches):
    """Map packed sign vectors to original representatives in raster order.

    Signs are packed with one bit per feature. The threshold is inclusive.
    If both neighbors match, the upper representative has local priority.
    Returned kind codes are new=0, left=1, and up=2.
    """
    assert image_width > 0 and signs and len(signs) % image_width == 0
    assert 0 <= minimum_matches <= sign_width
    max_differences = sign_width - minimum_matches
    origins, kinds = [], []
    for index, sign in enumerate(signs):
        if index >= image_width:
            upper = origins[index - image_width]
            if (sign ^ signs[upper]).bit_count() <= max_differences:
                origins.append(upper)
                kinds.append(2)
                continue
        if index % image_width:
            left = origins[index - 1]
            if (sign ^ signs[left]).bit_count() <= max_differences:
                origins.append(left)
                kinds.append(1)
                continue
        origins.append(index)
        kinds.append(0)
    return origins, kinds
