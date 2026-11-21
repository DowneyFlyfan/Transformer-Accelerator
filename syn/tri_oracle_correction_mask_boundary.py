"""Restore only proven zero bits removed at the old hierarchical mask cut."""
if not __debug__:
    raise RuntimeError('Boundary verification requires nonoptimized Python')

import re

NAMES = {
    'mask_start': ('packet_mask_start', 15, range(7660, 7656, -1)),
    'mask_count': ('compute_mask_count', 6, range(7664, 7660, -1)),
}


def compact(value):
    return re.sub(r'\s+', '', value)


def expected(port, restored):
    signal, highest, floating = NAMES[port]
    upper = [f'{signal}[{bit}]' for bit in range(highest, 3, -1)]
    lower = ["1'b0"] * 4 if restored else [f'UNCONNECTED_HIER_Z{bit}' for bit in floating]
    return '{' + ','.join(upper + lower) + '}'


def restore(text, linker):
    begin, end, master, pins = linker.child(text, 'compute')
    if master != 'tri_oracle_native_token_map_copy_3':
        raise ValueError('Unexpected mask consumer')
    for port in NAMES:
        if compact(pins[port]) != expected(port, False):
            raise ValueError('Unexpected original floating mask expression: ' + port)
        pins[port] = expected(port, True)
    return text[:begin] + linker.emit(master, 'compute', pins) + text[end:]


def verify(text, linker):
    _, _, master, pins = linker.child(text, 'compute')
    if master != 'tri_oracle_native_token_map_copy_3':
        raise ValueError('Unexpected restored mask consumer')
    for port in NAMES:
        if compact(pins[port]) != expected(port, True):
            raise ValueError('Required mask zero bits are not restored: ' + port)
    return True
