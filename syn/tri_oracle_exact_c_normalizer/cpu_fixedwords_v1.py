"""Exact encoded normalization using fixed five-word unsigned arithmetic.

There are no imports, floating operations, tensors, oracle or integer-sqrt
fallbacks. Each wide value is a newly initialized little-endian tuple[5] of
unsigned32 limbs; no scalar reconstructs that value. Scalar partial products
and shift/carry temporaries stay inside unsigned64 (subtraction uses signed33).

Logical axes: M independent caller rows; N features, 8..4096 in octets.
raw[M,N] signed32 and gain[N] or gain[M,N] signed24 are caller-initialized lists.
epsilon[M] unsigned64 and gamma_exponent[M] signed8 are encoded metadata.
All result arrays are newly initialized lists; inputs are read-only.
This CPU implementation is not evidence of GPU or hardware execution.
"""

WORD_MASK = 0xffffffff
ZERO = (0,0,0,0,0)


def _check_words(value):
    """Caller/internal value[5] -> validation only; each limb is scalar uint32."""
    if type(value) not in (tuple,list) or len(value)!=5:
        raise ValueError('exact five-word value required')
    for limb in value:
        if type(limb) is not int or not 0<=limb<=WORD_MASK:
            raise ValueError('unsigned32 limb required')


def _from_u64(value):
    """Bounded caller scalar uint64 -> new little-endian words[5]."""
    if type(value) is not int or not 0<=value<=0xffffffffffffffff:
        raise ValueError('unsigned64 scalar required')
    return (value&WORD_MASK,value>>32,0,0,0)


def _compare(a,b):
    """Two internal words[5] -> scalar -1/0/+1 by highest differing limb."""
    _check_words(a);_check_words(b)
    for index in range(4,-1,-1):
        if a[index]!=b[index]:
            return 1 if a[index]>b[index] else -1
    return 0


def _add(a,b):
    """Internal words[5] -> new words[5]; scalar total <=2^33-1, carry<=1."""
    _check_words(a);_check_words(b)
    result=[0]*5;carry=0
    for index in range(5):
        total=a[index]+b[index]+carry
        result[index]=total&WORD_MASK;carry=total>>32
    if carry:
        raise OverflowError('five-word addition overflow')
    return tuple(result)


def _sub(a,b):
    """Internal words[5], a>=b -> new words[5]; difference is signed33."""
    _check_words(a);_check_words(b)
    result=[0]*5;borrow=0
    for index in range(5):
        difference=a[index]-b[index]-borrow
        borrow=int(difference<0)
        result[index]=difference+(0x100000000 if borrow else 0)
    if borrow:
        raise ValueError('five-word subtraction underflow')
    return tuple(result)


def _left(a,amount):
    """Internal words[5], scalar shift0..159 -> new checked words[5].

    Each word<<bits has bits<=31 and is at most (2^32-1)<<31 <2^63.
    A zero subword shift never evaluates a complementary shift by32.
    """
    _check_words(a)
    if type(amount) is not int or not 0<=amount<160:
        raise ValueError('shift must be integer0..159')
    whole,bits=divmod(amount,32);result=[0]*5
    for index in range(5):
        destination=index+whole
        if destination>=5:
            if a[index]:
                raise OverflowError('five-word left shift overflow')
            continue
        shifted=a[index]<<bits
        result[destination]|=shifted&WORD_MASK
        carry=shifted>>32
        if carry:
            if destination+1>=5:
                raise OverflowError('five-word left shift overflow')
            result[destination+1]|=carry
    return tuple(result)


def _right(a,amount):
    """Internal words[5], scalar shift0..159 -> new logical words[5].

    Nonzero complementary subword shifts are1..31, so merged scalar <2^64.
    """
    _check_words(a)
    if type(amount) is not int or not 0<=amount<160:
        raise ValueError('shift must be integer0..159')
    whole,bits=divmod(amount,32);result=[0]*5
    for index in range(5):
        source=index+whole
        if source<5:
            merged=a[source]>>bits
            if bits and source+1<5:
                merged|=a[source+1]<<(32-bits)
            result[index]=merged&WORD_MASK
    return tuple(result)


def _multiply_word(a,factor):
    """Internal words[5], scalar uint32 factor -> new checked words[5].

    Limb*factor+carry <= (2^32-1)^2+(2^32-1) =2^64-2^32.
    Carry is at most2^32-1; no scalar holds the wide product.
    """
    _check_words(a)
    if type(factor) is not int or not 0<=factor<=WORD_MASK:
        raise ValueError('unsigned32 factor required')
    result=[0]*5;carry=0
    for index in range(5):
        total=a[index]*factor+carry
        result[index]=total&WORD_MASK;carry=total>>32
    if carry:
        raise OverflowError('five-word scalar multiplication overflow')
    return tuple(result)


def _multiply(a,b):
    """Two internal words[5] -> new checked words[5], schoolbook products.

    Each temporary is ai*bj+old_word+carry <=(2^32-1)^2+2*(2^32-1)
    =2^64-1. Every term is nonnegative; any nonzero omitted product/carry
    therefore proves overflow and is rejected instead of silently wrapping.
    """
    _check_words(a);_check_words(b)
    result=[0]*5
    for left_index in range(5):
        carry=0
        for right_index in range(5):
            destination=left_index+right_index
            if destination>=5:
                if a[left_index] and b[right_index]:
                    raise OverflowError('five-word multiplication overflow')
                continue
            total=a[left_index]*b[right_index]+result[destination]+carry
            result[destination]=total&WORD_MASK;carry=total>>32
        if carry:
            raise OverflowError('five-word multiplication overflow')
    return tuple(result)


def _rounded_magnitude(numerator,unit_denominator):
    """Internal exact A[5], B[5]>0 -> scalar rounded magnitude0..128.

    The row scale proves A<=127^2*B. This is the hardware's eight restoring
    steps: remainder=4A; delta=B<<14; root_term initially0; accept iff the
    unsigned remainder covers root_term+delta. Shift/quarter after each step,
    append the accepted bit, then return (root_code+1)>>1 (half away from0).
    remainder/root_term/delta/trial are initialized words[5], never scalars.
    Scalar root_code is eight bits, and its final +1 fits nine bits.
    """
    _check_words(numerator);_check_words(unit_denominator)
    if _compare(unit_denominator,ZERO)==0:
        raise ValueError('positive unit denominator required')
    remainder=_left(numerator,2);delta=_left(unit_denominator,14)
    root_term=ZERO;root_code=0
    for iteration in range(8):
        trial=_add(root_term,delta)
        accepted=_compare(remainder,trial)>=0
        if accepted:
            remainder=_sub(remainder,trial)
        root_term=_add(_right(root_term,1),delta if accepted else ZERO)
        root_code=((root_code&127)<<1)|int(accepted)
        delta=_right(delta,2)
    return (root_code+1)>>1


def _validate(raw,gain,epsilon_q16,gamma_exponent):
    """Caller list axes -> scalar (M,N) and read-only gain row views[M,N].

    M,N are initialized from caller lengths. gain_rows is a new list of
    caller row references (or repeated broadcast reference), never mutated.
    All structural/raw/metadata errors are detected before any row arithmetic.
    Invalid gain codes are intentionally per-row error2, including Boolean or
    noninteger codes; malformed gain geometry is a global ValueError.
    """
    if type(raw) is not list or not raw or type(raw[0]) is not list:
        raise ValueError('nonempty list of raw rows required')
    rows=len(raw);features=len(raw[0])
    if not 8<=features<=4096 or features%8:
        raise ValueError('feature count must be8..4096 in octets')
    for row in raw:
        if type(row) is not list or len(row)!=features:
            raise ValueError('uniform complete raw rows required')
        for value in row:
            if type(value) is not int or not -(1<<31)<=value<(1<<31):
                raise ValueError('signed32 raw code required')
    if type(epsilon_q16) is not list or len(epsilon_q16)!=rows:
        raise ValueError('one unsigned64 epsilon per row required')
    for value in epsilon_q16:
        if type(value) is not int or not 0<=value<=0xffffffffffffffff:
            raise ValueError('unsigned64 epsilon required')
    if type(gamma_exponent) is not list or len(gamma_exponent)!=rows:
        raise ValueError('one signed8 gamma exponent per row required')
    for value in gamma_exponent:
        if type(value) is not int or not -128<=value<=127:
            raise ValueError('signed8 gamma exponent required')
    if type(gain) is not list or not gain:
        raise ValueError('gain list required')
    if type(gain[0]) is list:
        if len(gain)!=rows:
            raise ValueError('rowwise gain count mismatch')
        for row in gain:
            if type(row) is not list or len(row)!=features:
                raise ValueError('rowwise gain feature mismatch')
        gain_rows=gain
    else:
        if len(gain)!=features or any(type(value) is list for value in gain):
            raise ValueError('broadcast gain feature mismatch')
        gain_rows=[gain for row_index in range(rows)]
    return rows,features,gain_rows


def normalize24_cpu_fixedwords(raw,gain,epsilon_q16,gamma_exponent):
    """CPU list ABI: encoded caller inputs -> fresh six-field output lists.

    Inputs: raw[M,N] signed32, gain[N] or[M,N] signed24, epsilon_q16[M]
    uint64, gamma_exponent[M] signed8; M independent rows, N octet features.
    All arrays below are new, except explicitly read-only caller row views.

    Per row: products[N] are bounded signed56 scalars (absolute <=2^54).
    energy/denominator/max_square/scale_numerator/scale_budget/unit_denominator
    and outlier_budget are words[5], initialized from ZERO or exact limb ops.
    energy<=2^74; denominator<2^91 fits92; scale numerator<=2^136.
    unit denominator<2^138, restoring delta<2^152, trial<2^153 all fit160.
    codes and three Boolean planes are initialized [N]; returned fields become
    codes/planes[M,N], activation_exponent[M] signed9, error_codes[M] int32.
    Error1 is zero D; error2 is invalid gain, with all row outputs zero/false.
    Nonzero M-products use eGamma+shift; zero products force eA0 without losing
    raw pre-gamma outlier features. No GPU, model, phase or residual join occurs.
    """
    rows,features,gain_rows=_validate(raw,gain,epsilon_q16,gamma_exponent)
    answer={'codes':[],'activation_exponent':[],'outlier_mask':[],
            'normalized_negative':[],'outlier_negative':[],'error_codes':[]}
    for row_index in range(rows):
        row=raw[row_index];row_gain=gain_rows[row_index]
        codes=[0]*features;outliers=[False]*features
        product_negative=[False]*features;outlier_negative=[False]*features
        exponent=0;error=0
        if any(type(value) is not int or not -(1<<23)<=value<(1<<23) for value in row_gain):
            error=2
        else:
            energy=ZERO;products=[];maximum=0
            for value,coefficient in zip(row,row_gain):
                # value^2<=2^62; |value*coefficient|<=2^54, both fit uint64.
                energy=_add(energy,_from_u64(value*value))
                product=value*coefficient;products.append(product)
                magnitude=-product if product<0 else product
                if magnitude>maximum:
                    maximum=magnitude
            denominator=_add(_left(energy,16),_multiply_word(_from_u64(epsilon_q16[row_index]),features))
            if _compare(denominator,ZERO)==0:
                error=1
            else:
                maximum_words=_from_u64(maximum)
                max_square=_multiply(maximum_words,maximum_words)
                scale_numerator=_left(_multiply_word(max_square,features),16)
                scale_budget=_multiply_word(denominator,16129);shift=0
                while _compare(scale_numerator,scale_budget)>0:
                    if shift==23:
                        raise ArithmeticError('signed24 proven output-unit domain exceeded')
                    scale_budget=_left(scale_budget,2);shift+=1
                unit_denominator=_left(denominator,2*shift)
                outlier_budget=_multiply_word(denominator,9)
                exponent=gamma_exponent[row_index]+shift if maximum else 0
                for lane in range(features):
                    product=products[lane];magnitude=-product if product<0 else product
                    magnitude_words=_from_u64(magnitude)
                    numerator=_left(_multiply_word(_multiply(magnitude_words,magnitude_words),features),16)
                    rounded=_rounded_magnitude(numerator,unit_denominator)
                    signed=-rounded if product<0 else rounded
                    codes[lane]=max(-128,min(127,signed))
                    raw_square=_from_u64(row[lane]*row[lane])
                    outlier_numerator=_left(_multiply_word(raw_square,features),16)
                    outliers[lane]=_compare(outlier_numerator,outlier_budget)>0
                    product_negative[lane]=product<0
                    outlier_negative[lane]=row[lane]<0 and outliers[lane]
        answer['codes'].append(codes);answer['activation_exponent'].append(exponent)
        answer['outlier_mask'].append(outliers);answer['normalized_negative'].append(product_negative)
        answer['outlier_negative'].append(outlier_negative);answer['error_codes'].append(error)
    return answer
