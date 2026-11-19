"""Word abstractions of exact separately bound arithmetic-stage contracts.

Old compressed words denote the actual sign-extended IQ register projections.
They are represented as19-bit words; this model admits extra nonphysical states.
Actual mapped bindings, clocks and reset behavior must be composed separately.
"""
import z3

def compress3(x,y,z):
 assert all(z3.is_bv(v) and v.size()==19 for v in (x,y,z))
 return x^y^z,((x&y)|((x|y)&z))<<1

def compress4(x,y,z,w):
 s,c=compress3(x,y,z);return compress3(s,c,w)

def total(words):
 assert words and all(z3.is_bv(v) and v.size()==19 for v in words)
 return sum(words,z3.BitVecVal(0,19))

def collapse_old(old):
 assert set(old)=={'products','first','second','final'}
 assert len(old['products'])==8 and all(v.size()==16 for v in old['products'])
 assert len(old['first'])==4 and len(old['second'])==2 and old['final'].size()==19
 return [total([z3.SignExt(3,v) for v in old['products']]),total(old['first']),total(old['second']),old['final']]

def collapse_new(data):
 assert len(data)==4 and all(len(row)==8>>stage and all(v.size()==16+stage for v in row) for stage,row in enumerate(data))
 return [total([z3.SignExt(3-stage,v) for v in row]) for stage,row in enumerate(data)]

def old_row_step(old,incoming,hold):
 collapse_old(old)
 assert len(incoming)==8 and all(v.size()==16 for v in incoming) and z3.is_bool(hold)
 first=[]
 for group in range(2):first.extend(compress4(*[z3.SignExt(3,v) for v in old['products'][group*4:group*4+4]]))
 return dict(products=list(incoming),first=first,second=list(compress4(*old['first'])),final=z3.If(hold,old['final'],total(old['second'])))
