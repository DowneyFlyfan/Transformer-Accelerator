"""Exact binary32-bit legacy encoder with an explicit physical-input entrypoint.

Caller/source axes: raw_bits[M,N] and gamma_bits[N] or[M,N] contain original
unsigned32 binary32 words, M>=1 and N=8..4096 in octets. No tensor, floating
value, model, trained parameter or arithmetic oracle is imported. This module
preserves encode_input_bits and adds explicit encode_physical_input_bits.
The physical entrypoint selects a raw-unit floor, not a normalization role.

Bounds: each finite word decodes to a <=24-bit magnitude significand and an
integer binary power -149..104. Unit selection compares <=31-bit integers for
raw width32, <=24-bit integers for gain width24. Reencoding left shifts only
when the selected positive-limit unit bounds the result to width-1 bits.
Right rounding uses a <=25-bit addition; shifts larger than24 yield zero
without constructing large integers. Epsilon values are fixed unsigned64
constants, independently checked against the frozen rational oracle outside
this implementation. No arbitrary precision product or floating operation is
needed. Metadata units and counters are small built-in integers.
"""

# Index i represents the raw dyadic exponent i-32, through exponent zero.
# Source definition: nearest(2**(16-2*e)/100000), with halfway away from zero.
_EPSILON_Q16_BY_RAW_UNIT = (
    12089258196146291747, 3022314549036572937, 755578637259143234,
    188894659314785809, 47223664828696452, 11805916207174113,
    2951479051793528, 737869762948382, 184467440737096,
    46116860184274, 11529215046068, 2882303761517, 720575940379,
    180143985095, 45035996274, 11258999068, 2814749767, 703687442,
    175921860, 43980465, 10995116, 2748779, 687195, 171799, 42950,
    10737, 2684, 671, 168, 42, 10, 3, 1,
)


def _check_row(words, features):
    """Caller words[N]; read-only validation, with no output allocation."""
    if type(words) is not list or len(words) != features:
        raise ValueError('Uniform complete bit rows required')
    for word in words:
        if type(word) is not int or not 0 <= word < (1 << 32):
            raise ValueError('Exact built-in unsigned32 bit words required')
        if ((word >> 23) & 255) == 255:
            raise ValueError('Finite binary32 words required')


def _magnitude(word):
    """Validated word scalar -> unsigned significand<=24bits, power scalar.

    The original magnitude is significand*2**power, including subnormals.
    Sign and signed zero are handled only when producing integer codes.
    """
    exponent = (word >> 23) & 255
    fraction = word & 0x7fffff
    if exponent == 0:
        return fraction, -149
    return fraction | (1 << 23), exponent - 150


def _minimal_unit(words, width):
    """Validated original row[N] -> smallest positive-limit dyadic unit.

    Finite binary32 magnitude bit patterns are numerically ordered. If f is
    floor(log2(maximum)), the initial unit f-(width-2) puts maximum/unit in
    [2**(width-2),2**(width-1)). At most one increment is necessary to meet
    the symmetric positive limit 2**(width-1)-1. Its preceding unit cannot
    fit, which proves minimality. All-zero original rows use unit zero.
    """
    maximum = max(word & 0x7fffffff for word in words)
    if maximum == 0:
        return 0
    significand, power = _magnitude(maximum)
    unit = power + significand.bit_length() - 1 - (width - 2)
    shift = power - unit
    limit = (1 << (width - 1)) - 1
    if shift >= 0:
        exceeds = (significand << shift) > limit
    else:
        exceeds = significand > (limit << -shift)
    return unit + int(exceeds)


def _encode_row(words, unit):
    """Original validated bits[N], final unit -> new exact integer codes[N].

    Direct original-bit rounding avoids rounding at a minimal unit and again
    at the POST floor. Fresh result is never an input or shared row object.
    """
    result = []
    for word in words:
        significand, power = _magnitude(word)
        shift = power - unit
        if significand == 0:
            magnitude = 0
        elif shift >= 0:
            magnitude = significand << shift
        else:
            right = -shift
            magnitude = 0 if right > 24 else (significand + (1 << (right - 1))) >> right
        result.append(-magnitude if word >> 31 else magnitude)
    return result


def _signed8_unit(unit):
    if not -128 <= unit <= 127:
        raise ValueError('Unit exceeds signed8 metadata')
    return unit


def _epsilon(unit):
    if unit < -32:
        raise ValueError('Physical epsilon exceeds unsigned64')
    return 0 if unit >= 1 else _EPSILON_Q16_BY_RAW_UNIT[unit + 32]


def encode_input_bits(raw_bits, gamma_bits, role):
    """Return exactly five fresh built-in list/int fields from original bits.

    raw_bits[M,N] is caller-owned. gamma_bits[N] initializes one broadcast
    signed24 gain vector, or gamma_bits[M,N] initializes independent rows.
    gain axes are preserved. raw[M,N] is signed32; gain is signed24; raw and
    gamma exponent lists[M] carry signed8 units; epsilon_q16[M] is unsigned64.
    PRE uses the minimal raw unit and rejects unsupported metadata/epsilon.
    POST floors only the raw unit at -32, then reencodes original bits once.
    All input rows are validated before any output is returned. A later bad
    row rejects the entire call; no caller-owned list is modified or retained.
    """
    if type(role) is not str or role not in ('PRE', 'POST'):
        raise ValueError('Explicit exact PRE or POST role required')
    if type(raw_bits) is not list or not raw_bits or type(raw_bits[0]) is not list:
        raise ValueError('Nonempty raw bit matrix required')
    rows, features = len(raw_bits), len(raw_bits[0])
    if not 8 <= features <= 4096 or features % 8:
        raise ValueError('Complete feature octets8..4096 required')
    if type(gamma_bits) is not list or not gamma_bits:
        raise ValueError('Nonempty gain bit vector or matrix required')
    rowwise = type(gamma_bits[0]) is list
    if rowwise and len(gamma_bits) != rows:
        raise ValueError('One gain row per raw row required')
    for words in raw_bits:
        _check_row(words, features)
    source_gains = gamma_bits if rowwise else [gamma_bits]
    for words in source_gains:
        _check_row(words, features)

    # New gain rows[G,N], G=M for rowwise input and1 for broadcast input.
    encoded_gains, gain_units = [], []
    for words in source_gains:
        unit = _signed8_unit(_minimal_unit(words, 24))
        encoded_gains.append(_encode_row(words, unit))
        gain_units.append(unit)

    # New raw rows[M,N] and independent metadata lists[M], no output aliases.
    encoded_raw, raw_units, epsilons = [], [], []
    for words in raw_bits:
        unit = _minimal_unit(words, 32)
        if role == 'POST':
            unit = max(unit, -32)
        unit = _signed8_unit(unit)
        epsilon = _epsilon(unit)
        encoded_raw.append(_encode_row(words, unit))
        raw_units.append(unit)
        epsilons.append(epsilon)
    gamma_units = list(gain_units) if rowwise else [gain_units[0] for _ in range(rows)]
    return {
        'raw': encoded_raw,
        'gain': encoded_gains if rowwise else encoded_gains[0],
        'raw_unit_exponent': raw_units,
        'gamma_exponent': gamma_units,
        'epsilon_q16': epsilons,
    }


def encode_physical_input_bits(raw_bits, gamma_bits):
    """Explicit physical-C boundary; no normalization role is inferred.

    Caller original raw_bits[M,N] and gamma_bits[N] or[M,N] have the same
    exact bit/shape/type/freshness contract as the legacy entrypoint. Apply
    max(minimal_raw_unit,-32) and direct original-bit rounding for every row;
    gamma retains its unchanged minimal signed24 unit and signed8 checks.
    The existing POST numeric codec supplies exactly that floor operation.
    This wrapper neither accepts nor assigns a layer/normalization-role tag.
    It does not make legacy PRE accept a previously unsupported raw unit.
    """
    return encode_input_bits(raw_bits, gamma_bits, 'POST')
