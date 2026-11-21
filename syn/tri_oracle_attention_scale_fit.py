"""Fixed max-based scales from declared disjoint calibration inputs only.

Rows[L,40] hold query/key/value group maxima; rows[L,32] hold output-group
maxima. L is the number of decoder layers, initialized to zero. Values are
read-only scalar statistics of original forward tensors, not trainable weights.
"""
from copy import deepcopy
import math

def choose_exponent(maximum):
    """Scalar maximum is finite/nonnegative; return signed8 scale power e.
    For maximum=m*2**p, representability maximum<=127*2**e is equivalent
    to m<=127/128 when e=p-7, otherwise e=p-6. Zero uses e=0.
    """
    maximum=float(maximum)
    if not math.isfinite(maximum) or maximum<0:raise ValueError('Finite nonnegative maximum required')
    if maximum==0:return 0
    mantissa,power=math.frexp(maximum)
    return power-7+int(mantissa>127/128)

class FrozenScaleFit:
    def __init__(self,layers=22,fit_cases=tuple(range(8))):
        # qkv[L,40] and output[L,32] initialize to0; seen is scalar identity set.
        if layers<1 or not fit_cases or len(set(fit_cases))!=len(fit_cases):raise ValueError('Nonempty layer/case domain required')
        self.layers=layers;self.fit_cases=tuple(fit_cases);self.seen=set();self._frozen=None
        self.qkv=[[0.]*40 for _ in range(layers)];self.output=[[0.]*32 for _ in range(layers)]

    @property
    def frozen(self):return deepcopy(self._frozen)

    def add(self,case,layer,qkv_maxima,output_maxima):
        # Caller supplies source maxima[40]/[32] for one declared case/layer.
        # Repeated calls aggregate maxima without labels or held data access.
        if self._frozen is not None:raise RuntimeError('Calibration already frozen')
        if case not in self.fit_cases or not 0<=layer<self.layers:raise ValueError('Outside declared fit domain')
        if len(qkv_maxima)!=40 or len(output_maxima)!=32:raise ValueError('Incomplete head groups')
        qkv=list(map(float,qkv_maxima));output=list(map(float,output_maxima))
        for value in qkv+output:choose_exponent(value)
        self.qkv[layer]=[max(a,b) for a,b in zip(self.qkv[layer],qkv,strict=True)]
        self.output[layer]=[max(a,b) for a,b in zip(self.output[layer],output,strict=True)]
        self.seen.add((case,layer))

    def freeze(self):
        if self._frozen is not None:raise RuntimeError('Calibration already frozen')
        if self.seen!={(case,layer) for case in self.fit_cases for layer in range(self.layers)}:
            raise RuntimeError('Missing calibration case or layer')
        self._frozen=dict(fit_cases=list(self.fit_cases),qkv_maxima=deepcopy(self.qkv),output_maxima=deepcopy(self.output),
                          qkv_exponents=[[choose_exponent(value) for value in row] for row in self.qkv],
                          output_exponents=[[choose_exponent(value) for value in row] for row in self.output],
                          rule='Maximum absolute magnitude fits signed8 under a fixed power-of-two scale; no held-data selection')
        return self.frozen
