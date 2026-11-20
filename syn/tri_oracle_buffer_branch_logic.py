"""Strict mapped-module comparison for canonical escaped instance names."""
from tri_oracle_mapped_module import normalize_module,read_module,pin_fields


def prove_module(before,after,rewires,additions):
    initial=read_module(normalize_module(before))
    result=read_module(normalize_module(after))
    assert initial[:2]==result[:2] and initial[4]==result[4]
    assert initial[2]|{branch:None for _,_,branch in additions.values()}==result[2]
    assert result[3].keys()==initial[3].keys()|additions.keys()
    canonical_names={name.removeprefix(chr(92)) for name in initial[3]}
    assert len(canonical_names)==len(initial[3])
    assert rewires.keys()<=canonical_names
    for name,(master,fields) in initial[3].items():
        observed_master,observed_fields=result[3][name]
        assert master==observed_master
        canonical_name=name.removeprefix(chr(92))
        if canonical_name in rewires:
            canonical={pin.removeprefix(chr(92)):' '.join(expr.split()) for pin,expr in pin_fields(fields).items()}
            for pin,(old,branch) in rewires[canonical_name].items():
                assert canonical[pin]==old
                canonical[pin]=branch
            measured={pin.removeprefix(chr(92)):' '.join(expr.split()) for pin,expr in pin_fields(observed_fields).items()}
            assert canonical==measured
        else:
            assert fields==observed_fields
    for name,(master,upstream,branch) in additions.items():
        observed_master,fields=result[3][name]
        assert observed_master==master and pin_fields(fields)=={'I':upstream,'Z':branch}
