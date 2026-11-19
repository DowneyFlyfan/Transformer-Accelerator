"""Symbolic stream model; not an actual mapped-array equivalence certificate."""
import z3

def choose(condition,yes,no):
    return z3.If(condition,yes,no) if z3.is_expr(condition) else (yes if condition else no)

def all_of(*values):
    return z3.And(*values) if any(z3.is_expr(v) for v in values) else all(values)

def any_of(*values):
    return z3.Or(*values) if any(z3.is_expr(v) for v in values) else any(values)

def negate(value):return z3.Not(value) if z3.is_expr(value) else not value

def count_constant(value,number):
    return z3.BitVecVal(number,value.size()) if z3.is_bv(value) else number

def empty_old():return dict(shadow=[False]*4,running=[False]*4,pipe=[0]*4,fifo=[0]*3,count=0)
def empty_new():return dict(valid=[False]*4,pipe=[0]*4)

def old_step(old,valid,ready,data,rst=True):
    outvalid=old['shadow'][3];advance=any_of(negate(outvalid),ready)
    accept=all_of(advance,valid);take=all_of(outvalid,ready)
    buffered=old['count']!=0;full=old['count']==3;completion=old['running'][3]
    pop=all_of(take,buffered)
    push=all_of(completion,choose(take,buffered,negate(full)))
    hold=all_of(completion,full,negate(take))
    one=count_constant(old['count'],1);zero=count_constant(old['count'],0)
    pop_count=choose(pop,one,zero);push_count=choose(push,one,zero)
    index=old['count']-pop_count
    fifo=[]
    for bit in range(3):
        shifted=choose(pop,old['fifo'][min(bit+1,2)],old['fifo'][bit])
        fifo.append(choose(all_of(push,index==bit),old['pipe'][3],shifted))
    following=dict(shadow=[all_of(rst,choose(advance,new,held)) for new,held in zip([valid,*old['shadow'][:3]],old['shadow'])],
        running=[all_of(rst,v) for v in [accept,*old['running'][:2],any_of(old['running'][2],hold)]],
        pipe=[data,*old['pipe'][:2],choose(hold,old['pipe'][3],old['pipe'][2])],
        fifo=fifo,count=choose(rst,old['count']+push_count-pop_count,zero))
    return following,advance,outvalid,choose(buffered,old['fifo'][0],old['pipe'][3])

def new_step(old,valid,ready,data,rst=True):
    outvalid=old['valid'][3];advance=any_of(negate(outvalid),ready)
    following=dict(valid=[all_of(rst,choose(advance,new,held)) for new,held in zip([valid,*old['valid'][:3]],old['valid'])],
        pipe=[choose(all_of(advance,valid if bit==0 else old['valid'][bit-1]),data if bit==0 else old['pipe'][bit-1],old['pipe'][bit]) for bit in range(4)])
    return following,advance,outvalid,old['pipe'][3]
