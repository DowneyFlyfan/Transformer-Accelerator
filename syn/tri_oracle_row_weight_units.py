"""Stream frozen trained-weight units; no model or accelerator execution."""
from pathlib import Path
import hashlib
import json
import math
import struct
import numpy as np


def exponent_for_maximum(maximum):
    """maximum is a finite nonnegative scalar from trained float32 values."""
    if not math.isfinite(maximum) or maximum<0:raise ValueError('Invalid weight maximum')
    if maximum==0:return 0
    mantissa,power=math.frexp(maximum)
    return power-7+int(mantissa>127/128)


def _encode(values,exponents):
    """values[R,F] are trained float32 rows; exponents[R] come from maxima.
    R is chunk rows and F is input features. scaled/rounded/codes[R,F]
    initialize from power-of-two scaling, float32 half addition and signed8
    clipping, respectively. The returned array owns only the current chunk.
    """
    scaled=np.ldexp(values,-exponents[:,None])
    rounded=np.sign(scaled)*np.floor(np.abs(scaled)+np.float32(.5))
    return np.clip(rounded,-128,127).astype(np.int8)


def quantize_row(values):
    """values[F] are literal or trained row values from the caller.
    row[1,F] is initialized as finite float32; its scalar maximum determines
    the signed power-of-two exponent. Return signed8 bytes[F] and that unit.
    """
    with np.errstate(over='raise',invalid='raise'):
        try:row=np.asarray(values,dtype=np.float32)
        except FloatingPointError as error:raise ValueError('Nonfinite trained weight') from error
    if row.ndim!=1 or not row.size or not np.isfinite(row).all():raise ValueError('Expected finite nonempty weight row')
    exponent=exponent_for_maximum(float(np.abs(row).max()))
    codes=_encode(row[None,:],np.asarray([exponent],dtype=np.int32))
    return codes.tobytes(),exponent


def scalar_code(value,exponent):
    """Independently encode one exact float32 scalar using scalar IEEE rounding."""
    scaled=math.ldexp(float(value),-int(exponent))
    added=struct.unpack('<f',struct.pack('<f',abs(scaled)+.5))[0]
    magnitude=math.floor(added)
    return max(-128,min(127,-magnitude if value<0 else magnitude))

def inspect_matrix(path,key,rows_per_chunk=32):
    """Read actual safetensors float32 weights[R,F] without mapping the model.

    R is all output rows, F is trained input features. chunk[C,F] is initialized
    from at most rows_per_chunk binary rows. maxima/mantissas/powers/units[C]
    derive only from those weights. codes[C,F] are signed8; no output target is
    read. Scalar row-unit checks cover all R rows. Sampled scalar code checks
    cover the first/last row and first/middle/last feature of each chunk.
    Header, shape, offsets, digests and result lists are scalar metadata.
    """
    if not isinstance(rows_per_chunk,int) or not 1<=rows_per_chunk<=64:raise ValueError('Invalid bounded chunk size')
    path=Path(path);code_digest=hashlib.sha256();payload_digest=hashlib.sha256()
    row_exponents=[];global_maximum=0.;checked=0
    with path.open('rb') as stream:
        raw=stream.read(8)
        if len(raw)!=8:raise ValueError('Truncated safetensors header')
        header_bytes,=struct.unpack('<Q',raw)
        if not 2<=header_bytes<=16*2**20:raise ValueError('Invalid safetensors header size')
        header=stream.read(header_bytes)
        if len(header)!=header_bytes:raise ValueError('Truncated safetensors metadata')
        descriptor=json.loads(header)[key]
        shape=descriptor['shape'];offsets=descriptor['data_offsets']
        if descriptor['dtype']!='F32' or len(shape)!=2 or any(type(d) is not int or d<=0 for d in shape):raise ValueError('Expected trained float32 matrix')
        if len(offsets)!=2 or any(type(d) is not int or d<0 for d in offsets):raise ValueError('Invalid data offsets')
        rows,features=shape;begin,end=offsets
        if end-begin!=rows*features*4 or 8+header_bytes+end>path.stat().st_size:raise ValueError('Matrix byte extent disagrees with shape')
        stream.seek(8+header_bytes+begin)
        for start in range(0,rows,rows_per_chunk):
            count=min(rows_per_chunk,rows-start);payload=stream.read(count*features*4)
            if len(payload)!=count*features*4:raise ValueError('Truncated trained matrix')
            payload_digest.update(payload)
            chunk=np.frombuffer(payload,dtype='<f4').reshape(count,features)
            if not np.isfinite(chunk).all():raise ValueError('Nonfinite trained matrix')
            maxima=np.abs(chunk).max(axis=1)
            mantissas,powers=np.frexp(maxima)
            units=powers-7+(mantissas>np.float32(127/128)).astype(np.int32)
            units=np.where(maxima==0,0,units).astype(np.int32)
            if [int(x) for x in units]!=[exponent_for_maximum(float(x)) for x in maxima]:raise ValueError('Scalar row unit mismatch')
            row_exponents.extend(int(x) for x in units)
            global_maximum=max(global_maximum,float(maxima.max()))
            codes=_encode(chunk,units)
            for row in sorted({0,count-1}):
                for feature in sorted({0,features//2,features-1}):
                    if int(codes[row,feature])!=scalar_code(float(chunk[row,feature]),int(units[row])):raise ValueError('Independent scalar weight code mismatch')
                    checked+=1
            code_digest.update(codes.tobytes())
    global_exponent=exponent_for_maximum(global_maximum)
    return dict(shape=shape,descriptor=descriptor,row_exponents=row_exponents,
        global_exponent=global_exponent,relative_row_deltas=[global_exponent-e for e in row_exponents],
        scalar_row_units_checked=len(row_exponents),independent_scalar_codes_checked=checked,
        code_sha256=code_digest.hexdigest(),payload_sha256=payload_digest.hexdigest())

def pack_metadata(gate,up):
    """gate/up[K] are frozen three-bit offsets in original output-row order.
    Each scalar packet holds up to80 pairs, six bits per channel. No tensor
    output or activation selects these input-independent trained units.
    """
    if len(gate)!=len(up) or not gate:raise ValueError('Unpaired row metadata')
    if any(type(value) is not int or not 0<=value<=7 for value in [*gate,*up]):raise ValueError('Row metadata does not fit three bits')
    packets=[]
    for start in range(0,len(gate),80):
        count=min(80,len(gate)-start);word=0
        for index in range(count):word|=(gate[start+index]|(up[start+index]<<3))<<(6*index)
        packets.append(dict(start=start,count=count,word_hex=f'{word:0120x}'))
    return packets
