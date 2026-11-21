"""Exact rational oracle at all signed8 thresholds and signed32 endpoints.

No neural-network computation, fitting, labels or floating-point reference.
Signed32 input, sign/direction bit and five-bit magnitude are scalar fields.
"""
from pathlib import Path
import hashlib,json,random,sys
OUT=(Path(sys.argv[1]) if len(sys.argv)>1 else Path.cwd()/'.cache/signed_context_transfer_vectors').resolve()
assert OUT.is_relative_to((Path.cwd()/'.cache').resolve()),'Generated vectors belong under project .cache'
OUT.mkdir(parents=True,exist_ok=True)

def oracle(accumulator,shift):
    magnitude=abs(accumulator)
    numerator=magnitude<<shift if shift>=0 else magnitude
    denominator=65535 if shift>=0 else 65535<<-shift
    code=(numerator+denominator//2)//denominator
    return max(-128,min(127,-code if accumulator<0 else code))

def decomposed(accumulator,shift):
    if shift>=0:return oracle(accumulator,shift)
    magnitude=abs(accumulator);right=-shift
    rounded=(magnitude>>right)+((magnitude>>(right-1))&1)
    return oracle(-rounded if accumulator<0 else rounded,0)

def run():
    values=set()
    for shift in range(-31,32):
        for endpoint in [-2**31,-2**31+1,-8388480,-1,0,1,8388480,2**31-2,2**31-1]:values.add((endpoint,shift))
        for code in range(129):
            odd=(2*code+1)*65535
            boundary=(odd+(1<<(shift+1))-1)//(1<<(shift+1)) if shift>=0 else odd<<(-shift-1)
            for magnitude in [boundary-1,boundary,boundary+1]:
                for sign in [-1,1]:
                    accumulator=magnitude*sign
                    if magnitude>=0 and -2**31<=accumulator<2**31:values.add((accumulator,shift))
    randomizer=random.Random(20261121)
    for _ in range(20000):values.add((randomizer.randrange(-2**31,2**31),randomizer.randrange(-31,32)))
    ordered=sorted(values,key=lambda value:(value[1],value[0]))
    for accumulator,shift in ordered:assert oracle(accumulator,shift)==decomposed(accumulator,shift),(accumulator,shift)
    path=OUT/'vectors.hex'
    with path.open('x') as stream:
        for accumulator,shift in ordered:
            word=(((accumulator&0xffffffff)<<6)|(int(shift<0)<<5)|abs(shift))<<8|(oracle(accumulator,shift)&255)
            stream.write(f'{word:012x}\n')
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    receipt=dict(state='rational_oracle_and_decomposition_agree',cases=len(ordered),right_cases=sum(shift<0 for _,shift in ordered),
        shift_range=[-31,31],all_reachable_signed8_rounding_and_saturation_boundaries=True,signed32_endpoints=True,
        source_sha256=sha(Path(__file__)),vectors_sha256=sha(path),vectors_bytes=path.stat().st_size,
        rtl_verified=False,physical_integration_verified=False,paper_matching=False)
    (OUT/'vector_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':run()
