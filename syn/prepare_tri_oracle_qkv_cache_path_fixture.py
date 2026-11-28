"""Two captured layer-19 slots for the real projection/cache component test.

Register the host preparation run with experiment-summary before --prepare.
Tensor dot products are an explicitly modeled input boundary. The DUT still
executes its own rotary transform, quantization, cache writer and read protocol.
No model execution, graphics processor, native simulation or fitted parameter.
"""
from __future__ import annotations

from array import array
from pathlib import Path
import argparse
import hashlib
import json
import os
import resource
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
FRAME=ROOT/'.cache/late_clipping_20261121/frame_integration'
SOURCE=FRAME/'current_integer_attention_fixed_scales_v2'
RECEIPT_SHA='bc296dad3c27873e1a9f7c8fd642b55c906a09e7876412793e65ffc84c597293'
INPUTS_SHA='793ad430fcd6be485b5d835df4d8f2f646e6614f75e42ef49e4afec6e5898ec7'
BROKER=FRAME/'complete_head_broker_v1/trained32_reference.json'
BROKER_SHA='707e4f73e2a2241b23e9c0cbd0d0d4bd4b9a3c208b41c9492e4deef97296ef2d'
HEADS=40;TOKENS=281;LANES=64;HIDDEN=2048


def need(value,why):
    if value is not True:raise ValueError(why)


def identity(s):
    return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_size,s.st_mtime_ns,s.st_ctime_ns]


def closed(path,expected=None):
    """path/expected: scalar canonical source and optional scalar SHA256.
    raw[bytes]: exact saved byte stream; row: scalar closed-file metadata.
    """
    path=path.resolve(strict=True);before=identity(path.stat())
    with path.open('rb') as stream:
        need(identity(os.fstat(stream.fileno()))==before,'source FD identity')
        raw=stream.read()
        need(stream.read(1)==b'' and identity(os.fstat(stream.fileno()))==before,'complete source EOF')
    need(identity(path.stat())==before and len(raw)==before[5],'source unchanged')
    sha=hashlib.sha256(raw).hexdigest();need(expected is None or sha==expected,'exact captured operand SHA256')
    return raw,dict(path=str(path),bytes=len(raw),sha256=sha,complete_EOF=True,
                    identity_before=before,identity_after_fd=before,identity_after_path=before)


def nearest(value,shift):
    """value/shift: scalar exact integer numerator and nonnegative bit count.
    q,r: scalar quotient/remainder. 2*r>=2**shift is exactly nearest/ties-away.
    """
    q,r=divmod(abs(value),1<<shift)
    q+=int(2*r>=(1<<shift))
    return max(-128,min(127,-q if value<0 else q))


def packed(values,bits):
    """values[N]: source lane order, zero-init scalar result with N*bits bits."""
    return sum((int(value)&((1<<bits)-1))<<(bits*index) for index,value in enumerate(values))


def prepare(output):
    """All arithmetic is independently computed with Python integers.

    activation[T,H]=saved signed8 compact activations, weights[A,D,H]=saved
    trained signed8 weights; T281,H2048,A40,D64. a0/a1[H] select ranks0/1.
    raw[A,2,D] is an independent exact dot product initialized empty.
    cosine/sine[2,D/2] are captured signed16 Q14 coefficients.
    vectors[A,2,D] are independent nearest/ties-away signed8 projections.
    The first36 heads rotate lower/upper32 lanes; four V heads do not rotate.
    base[A],bias[2],units[A] come from the fixed disjoint-scale receipt.
    expected[A,T,D] is comparison-only saved projection, never DUT input.
    Every remaining loop index/address/hash/count is scalar metadata.
    """
    resource.setrlimit(resource.RLIMIT_AS,(128<<20,)*2);resource.setrlimit(resource.RLIMIT_CPU,(30,)*2)
    need(__debug__ and sys.dont_write_bytecode and Path.cwd().resolve()==ROOT
         and not Path('/.dockerenv').exists(),'ordinary host Python-B from project')
    available=next(int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    need(available>=9<<30,'host9GiB admission preserves8GiB floor')
    output=output.resolve();need(output.is_relative_to(ROOT/'.cache') and not output.exists(),'fresh project-cache output')
    reads={}
    def read(path,want=None):
        raw,row=closed(path,want);reads[row['path']]=row;return raw
    receipt=json.loads(read(SOURCE/'receipt.json',RECEIPT_SHA))
    json.loads(read(SOURCE/'inputs.json',INPUTS_SHA))
    broker=json.loads(read(BROKER,BROKER_SHA))
    need(receipt['layer']==broker['layer']==19 and receipt['retained_tokens']==281
         and broker['query_rank']==1 and broker['visible_keys']==2,'same captured layer19/rank-one fixture')
    data={}
    for name,nbytes in [('activation',TOKENS*HIDDEN),('weights',HEADS*LANES*HIDDEN),
                        ('cos',TOKENS*32*2),('sin',TOKENS*32*2),('projected',HEADS*TOKENS*LANES)]:
        declared=receipt['files']['data/'+name+'.bin']
        data[name]=read(SOURCE/'data'/(name+'.bin'),declared['sha256'])
        need(len(data[name])==declared['bytes']==nbytes,'exact captured tensor shape '+name)
    activation=array('b',data['activation']);weights=array('b',data['weights'])
    a0=activation[:HIDDEN];a1=activation[HIDDEN:2*HIDDEN]
    raw=[[[0]*LANES for _ in range(2)] for _ in range(HEADS)]
    for head in range(HEADS):
        for lane in range(LANES):
            begin=(head*LANES+lane)*HIDDEN;w=weights[begin:begin+HIDDEN]
            for token,a in enumerate((a0,a1)):
                dot=sum(int(x)*int(y) for x,y in zip(a,w))
                need(-(1<<31)<=dot<(1<<31) and abs(dot)<=HIDDEN*128*128,'exact signed32 dot bound')
                raw[head][token][lane]=dot
    cosine=[list(struct.unpack_from('<32h',data['cos'],token*64)) for token in range(2)]
    sine=[list(struct.unpack_from('<32h',data['sin'],token*64)) for token in range(2)]
    base=receipt['projection_base_shifts'];bias=receipt['projection_biases'][:2];units=receipt['projection_output_exponents']
    need(len(base)==len(units)==40 and len(bias)==2,'actual scale axes')
    need(all(type(v)is int and 0<=v<=63 for v in base+bias)
         and all(type(v)is int and -256<=v<=255 for v in units),'native packed shift/unit domains')
    vectors=[[[0]*LANES for _ in range(2)] for _ in range(HEADS)]
    for head in range(HEADS):
        for token in range(2):
            shift=base[head]+bias[token];need(0<shift<63,'captured effective shift')
            for lane in range(32):
                low=raw[head][token][lane];high=raw[head][token][lane+32]
                lower=low*cosine[token][lane]-high*sine[token][lane] if head<36 else low
                upper=high*cosine[token][lane]+low*sine[token][lane] if head<36 else high
                need(-(1<<48)<=lower<(1<<48) and -(1<<48)<=upper<(1<<48),'signed49 rotary bound')
                vectors[head][token][lane]=nearest(lower,shift)
                vectors[head][token][lane+32]=nearest(upper,shift)
            offset=(head*TOKENS+token)*LANES
            need(bytes(x&255 for x in vectors[head][token])==data['projected'][offset:offset+LANES],
                 'independent projection equals actual saved vector')
    need(len(broker['rows'])==32,'complete trained broker source')
    for head,row in enumerate(broker['rows']):
        need(row['head']==head and row['query']==vectors[head][1],'same broker query')
        need(row['keys']==vectors[32+head//8] and row['values']==vectors[36+head//8]
             and row['value_exponent']==units[36+head//8],'same broker key/value/unit')
    for path,row in reads.items():need(closed(Path(path),row['sha256'])[1]==row,'all original operands rechecked')
    output.mkdir(parents=True)
    def emit(name,words,digits):
        with (output/name).open('x') as stream:stream.write(''.join(f'{value:0{digits}x}\n' for value in words))
    emit('raw32.hex',[packed(raw[h][t],32) for h in range(40) for t in range(2)],512)
    emit('expected.hex',[packed(vectors[h][t],8) for h in range(40) for t in range(2)],128)
    emit('cos.hex',[packed(row,16) for row in cosine],128);emit('sin.hex',[packed(row,16) for row in sine],128)
    emit('config.hex',[packed(base,6),packed(bias+[0]*14,6),packed(units,9)],90)
    artifacts={p.name:closed(p)[1] for p in output.iterdir()}
    report=dict(schema='trained_two_slot_qkv_cache_fixture_v1',layer=19,compact_ranks=[0,1],cache_slots=[0,1],
        source_receipt_sha256=RECEIPT_SHA,broker_reference_sha256=BROKER_SHA,
        exact_dot_values=5120,integer_multiply_adds=2*40*64*2048,projected_bytes_compared=5120,
        broker_query_key_value_bytes_compared=3072,head_units=units,
        provider_boundary='Saved trained signed8 activation/weight exact dot outputs only; real DUT performs rotary/requantization/store/cache.',
        input_records=reads,artifact_records=artifacts,native_execution_performed=False,
        real_tensor_engine_executed=False,full_attention_executed=False,full_model_verified=False,paper300_release_allowed=False)
    with (output/'fixture.json').open('x') as stream:json.dump(report,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps(dict(output=str(output),exact_dot_values=5120,matched_vectors=80)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--prepare',action='store_true');p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();need(args.prepare is True,'explicit registered host preparation only');prepare(args.out)
