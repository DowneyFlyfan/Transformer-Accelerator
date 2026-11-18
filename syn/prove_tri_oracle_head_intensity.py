"""Check mapped score-packet/intensity transitions against word-level arithmetic.

The numerical head-ratio threshold remains a local reconstruction choice.
Upstream score production, parent tag handling, liveness and physical timing
are outside this verifier's scope. Only UNSAT establishes equivalence.
"""
from pathlib import Path
if not __debug__:
    raise RuntimeError('Mapped intensity verification requires Python assertions; optimized mode is disabled')
import z3


def require_unsat(result,label):
    assert result==z3.unsat,('Intensity equivalence not proved',label,str(result))


class WordBridge:
    """Preserve each Boolean graph leaf; derive words from the same leaves."""
    def __init__(self,graph):
        self.graph=graph;self.variables={};self.converted={};self.checks=[]

    def boolean(self,name):
        if name not in self.variables:self.variables[name]=z3.Bool(name)
        return self.variables[name]

    def word(self,name,width):
        assert width>0
        return self.pack([self.boolean(f'{name}[{bit}]') for bit in range(width)])

    @staticmethod
    def pack(bits):
        assert bits
        pieces=[z3.If(bit,z3.BitVecVal(1,1),z3.BitVecVal(0,1)) for bit in reversed(bits)]
        return z3.Concat(pieces) if len(pieces)>1 else pieces[0]

    def convert(self,roots):
        def visit(root):
            if root not in self.converted:
                operator,*arguments=self.graph.nodes[root]
                if operator=='c':value=z3.BoolVal(bool(arguments[0]))
                elif operator=='v':value=self.boolean(arguments[0])
                elif operator=='!':value=z3.Not(visit(arguments[0]))
                else:
                    functions={'&':z3.And,'|':z3.Or,'^':z3.Xor}
                    assert operator in functions,'Unknown Boolean graph operation'
                    value=functions[operator](*(visit(child) for child in arguments))
                self.converted[root]=value
            return self.converted[root]
        return [visit(root) for root in roots]

    def check(self,actual,expected,*,label,conditions=(),timeout_ms=120000):
        import time
        assert actual and len(actual)==len(expected)
        solver=z3.SolverFor('QF_BV');solver.set(timeout=timeout_ms,max_memory=1024)
        solver.add(*conditions,z3.Or(*(a!=b for a,b in zip(actual,expected,strict=True))))
        print('INTENSITY_QUERY_START',label,flush=True)
        start=time.monotonic();result=solver.check();seconds=time.monotonic()-start
        if result!=z3.unsat:
            detail=solver.model() if result==z3.sat else solver.reason_unknown()
            raise AssertionError(('Intensity equivalence not proved',label,str(result),str(detail)))
        require_unsat(result,label)
        self.checks.append(dict(label=label,result='unsat',seconds=seconds,outputs=len(actual)))
        print('INTENSITY_QUERY_UNSAT',label,seconds,flush=True)


def reference_hits(scores,mask,cutoff):
    assert len(scores)==8 and 0<=mask<256
    return sum(bool(mask&(1<<lane)) and value>cutoff for lane,value in enumerate(scores))


def reference_maximum(scores,mask,previous):
    assert len(scores)==8 and 0<=mask<256
    return max([previous]+[score for lane,score in enumerate(scores) if mask&(1<<lane)])


FIELDS=[('state',3),('rows_left',13),('beat_index',2),('row_max',32),('cutoff',34),
        ('total_inner',18),('total_outer',18),('row_has_sink',1),('out_error',1)]


def specification(bridge):
    """Separate word-level specification; no mapped gate structure is reused."""
    old={name:(bridge.boolean(name) if width==1 else bridge.word(name,width)) for name,width in FIELDS}
    state=old['state'];beat=old['beat_index'];rows=old['rows_left']
    cfg=bridge.boolean('cfg_valid');valid=bridge.boolean('in_valid');last=bridge.boolean('in_last')
    ready=bridge.boolean('out_ready');lanes=bridge.word('in_lanes',8);data=bridge.word('in_scores',256)
    alpha=bridge.word('cfg_alpha',32);cfg_rows=bridge.word('cfg_rows',13);den=bridge.word('cfg_ratio_den',8)
    ratio_bit=bridge.word('serial_ratio.ratio_bit',3)
    scores=[z3.Extract(32*lane+31,32*lane,data) for lane in range(8)]
    enabled=[z3.Extract(lane,lane,lanes)==1 for lane in range(8)]
    updated=old['row_max']
    for score,on in zip(scores,enabled,strict=True):updated=z3.If(z3.And(on,score>updated),score,updated)
    hits=z3.BitVecVal(0,18)
    for score,on in zip(scores,enabled,strict=True):
        hits=hits+z3.If(z3.And(on,z3.SignExt(2,score)>old['cutoff']),z3.BitVecVal(1,18),z3.BitVecVal(0,18))
    expected_last=z3.And(state==3,beat==3,rows==1)
    region=bridge.word('in_region',2)
    expected_region=z3.If(state==1,z3.BitVecVal(0,2),z3.If(state==2,z3.BitVecVal(1,2),z3.BitVecVal(2,2)))
    malformed=z3.Or(region!=expected_region,last!=expected_last)
    bad=z3.Or(malformed,z3.And(state==1,beat==3,z3.Not(old['row_has_sink']),lanes==0))
    active=z3.And(z3.Or(state==1,state==2,state==3),valid)
    ok=z3.And(active,z3.Not(bad));load=z3.And(state==0,cfg)
    new_row=z3.And(ok,state==3,beat==3,z3.Not(expected_last))
    bad_cfg=z3.Or(cfg_rows==0,z3.UGT(cfg_rows,4096),den==0)
    next_state=z3.If(state==7,z3.BitVecVal(6,3),state)
    next_state=z3.If(load,z3.If(bad_cfg,z3.BitVecVal(6,3),z3.BitVecVal(1,3)),next_state)
    next_state=z3.If(z3.And(active,bad),z3.If(last,z3.BitVecVal(6,3),z3.BitVecVal(5,3)),next_state)
    normal=z3.If(state==1,z3.If(beat==3,z3.BitVecVal(2,3),z3.BitVecVal(1,3)),
        z3.If(state==2,z3.If(beat==3,z3.BitVecVal(3,3),z3.BitVecVal(2,3)),
            z3.If(beat==3,z3.If(expected_last,z3.BitVecVal(4,3),z3.BitVecVal(1,3)),z3.BitVecVal(3,3))))
    next_state=z3.If(ok,normal,next_state)
    next_state=z3.If(z3.Or(z3.And(state==4,ratio_bit==0),z3.And(state==5,valid,last)),z3.BitVecVal(6,3),next_state)
    next_state=z3.If(z3.And(state==6,ready),z3.BitVecVal(0,3),next_state)
    minimum=z3.BitVecVal(1<<31,32)
    result=dict(state=next_state,
        rows_left=z3.If(load,cfg_rows,z3.If(new_row,rows-1,rows)),
        beat_index=z3.If(load,z3.BitVecVal(0,2),z3.If(ok,beat+1,beat)),
        row_max=z3.If(z3.Or(load,new_row),minimum,z3.If(z3.And(ok,state==1),updated,old['row_max'])),
        cutoff=z3.If(z3.And(ok,state==1,beat==3),z3.SignExt(2,updated)-z3.ZeroExt(2,alpha),old['cutoff']),
        total_inner=z3.If(load,z3.BitVecVal(0,18),z3.If(z3.And(ok,state==2),old['total_inner']+hits,old['total_inner'])),
        total_outer=z3.If(load,z3.BitVecVal(0,18),z3.If(z3.And(ok,state==3),old['total_outer']+hits,old['total_outer'])),
        row_has_sink=z3.If(z3.Or(load,new_row),z3.BoolVal(False),z3.If(z3.And(ok,state==1),z3.Or(old['row_has_sink'],lanes!=0),old['row_has_sink'])),
        out_error=z3.If(load,bad_cfg,z3.If(z3.Or(z3.And(active,bad),state==7),z3.BoolVal(True),old['out_error'])))
    return old,result,dict(updated_max=updated,beat_hits=hits,load=load,ok=ok,new_row=new_row)


def prove_numeric_invariants(maximum_count=131072):
    """Inductive range certificate composed with the actual next-state checks.

    R is the captured valid row count; r is rows_left. An inner/outer beat
    budget is 4*(R-r), plus progress in the current row. Valid packet steps
    advance exactly one applicable budget. A stall preserves budgets/counts;
    an error freezes counts until a new configuration clears them. At final
    Classify/Hold, r=1 and both budgets are4*R. Consequently each count is at
    most8*4*4096, below2**18, so proved modular updates equal integer sums.
    """
    bridge=WordBridge(None)
    signed_max=bridge.word('invariant_maximum',32)
    alpha=bridge.word('invariant_unsigned_alpha',32)
    wide=z3.SignExt(2,signed_max)-z3.ZeroExt(2,alpha)
    bridge.check([wide<=z3.BitVecVal((1<<31)-1,34),wide>=z3.BitVecVal(-(1<<31)-((1<<32)-1),34)],
        [z3.BoolVal(True),z3.BoolVal(True)],label='signed34_cutoff_write_range')
    hit_bits=[bridge.boolean(f'invariant_hit{lane}') for lane in range(8)]
    hit_sum=sum((z3.If(bit,z3.BitVecVal(1,18),z3.BitVecVal(0,18)) for bit in hit_bits),z3.BitVecVal(0,18))
    bridge.check([z3.ULE(hit_sum,8)],[z3.BoolVal(True)],label='eight_lane_hit_count_range')
    R,r,inner,outer,hit=z3.Ints('configured_rows remaining_rows inner_intensity outer_intensity beat_hits')
    basic=[R>=1,R<=4096,r>=1,r<=R,inner>=0,outer>=0,hit>=0,hit<=8]
    cases=[]

    def budgets(phase,beat,remaining):
        complete=4*(R-remaining)
        inside=beat if phase==2 else 4 if phase in (3,4,6) else 0
        outside=beat if phase==3 else 4 if phase in (4,6) else 0
        return complete+inside,complete+outside

    for phase in (1,2,3,4,6):
        for beat in (range(4) if phase in (1,2,3) else [0]):
            for final in ([False,True] if phase==3 and beat==3 else [None]):
                conditions=list(basic)
                if phase in (4,6):conditions.append(r==1)
                if final is not None:conditions.append(r==1 if final else r>1)
                before_inner,before_outer=budgets(phase,beat,r)
                conditions.extend([inner<=8*before_inner,outer<=8*before_outer])
                next_r=r;next_beat=(beat+1)%4 if phase in (1,2,3) else beat
                next_phase=phase
                if phase==1 and beat==3:next_phase=2
                if phase==2 and beat==3:next_phase=3
                if phase==3 and beat==3:
                    next_phase=4 if final else 1
                    if not final:next_r=r-1
                after_inner,after_outer=budgets(next_phase,next_beat,next_r)
                next_inner=inner+hit if phase==2 else inner
                next_outer=outer+hit if phase==3 else outer
                conclusion=z3.And(next_r>=1,next_r<=R,after_inner>=0,after_outer>=0,
                    after_inner<=4*R,after_outer<=4*R,next_inner>=0,next_outer>=0,
                    next_inner<=8*after_inner,next_outer<=8*after_outer,
                    next_inner<=maximum_count,next_outer<=maximum_count,
                    next_inner<(1<<18),next_outer<(1<<18))
                solver=z3.Solver();solver.set(timeout=30000,max_memory=512)
                solver.add(*conditions,z3.Not(conclusion));result=solver.check()
                require_unsat(result,f'intensity_budget_phase{phase}_beat{beat}_final{final}')
                cases.append(dict(phase=phase,beat=beat,final=final,result='unsat'))
    assert 0<=0<=8*4*4096<(1<<18)
    return dict(cutoff_reset=0,cutoff_write_minimum=-(1<<31)-((1<<32)-1),
        cutoff_write_maximum=(1<<31)-1,cutoff_upper_bound_preserved=True,
        maximum_configured_rows=4096,beats_per_region_per_row=4,lanes_per_beat=8,
        maximum_region_intensity=8*4*4096,count_bits=18,count_wrap_impossible_for_valid_packets=True,
        checked_normal_and_result_budget_steps=cases,numerical_lemma_checks=bridge.checks,
        reset_and_configuration_zero_counts_are_basis=True,
        stalls_preserve_counts_and_progress=True,malformed_packets_freeze_counts_until_reconfiguration=True,
        remaining_rows_one_applies_only_to_successful_classify_and_hold=True,
        malformed_or_invalid_hold_uses_zero_configuration_or_frozen_prior_count_bound=True,
        composition_requires_actual_score_packet_next_state_equivalence=True)


def prove_intensity(model,*,timeout_ms=120000,states_to_check=None,query_conditions=None):
    """Prove actual register updates at all encoded states and the reset basis."""
    from prove_tri_oracle_packaged_products import memory_guard
    bridge=WordBridge(model.graph);old,expected,intermediate=specification(bridge)
    selected_states=tuple(range(8)) if states_to_check is None else tuple(states_to_check)
    assert selected_states and len(set(selected_states))==len(selected_states) and all(type(state) is int and 0<=state<8 for state in selected_states)
    actual={};reset_roots=[];expected_reset=[]
    for name,width in FIELDS:
        assert model.module.declared.get(name)==((width-1,0) if width>1 else None),'Intensity field dimension differs'
        roots=[]
        for bit in range(width):
            output=f'{name}[{bit}]' if width>1 else name
            instance=f'{name}_reg[{bit}]' if width>1 else name+'_reg'
            data,reset,value=model.transition(instance,output)
            assert value==int(name=='row_max' and bit==31),('Intensity reset value differs',instance)
            roots.append(data);reset_roots.append(reset)
            expected_reset.append(z3.Not(bridge.boolean('rst_n')))
        bits=bridge.convert(roots)
        actual[name]=bridge.pack(bits) if width>1 else bits[0]
    bridge.check(bridge.convert(reset_roots),expected_reset,label='all_actual_async_reset_bindings',timeout_ms=timeout_ms)
    # A sink update is signed32 maximum minus zero-extended unsigned32 alpha.
    # This mathematical range is below signed32 MAX, and reset cutoff0 has the
    # same bound. Retained cutoff values preserve it. Use the resulting
    # inductive bound when comparing enabled scores to a signed34 threshold.
    cutoff_bound=old['cutoff']<=z3.BitVecVal((1<<31)-1,34)
    extra=[] if query_conditions is None else query_conditions(bridge,old)
    for state in selected_states:
        memory_guard(8.5)
        bridge.check([actual[name] for name,_ in FIELDS],[expected[name] for name,_ in FIELDS],
            label=f'all_score_packet_next_fields_state{state}',
            conditions=[bridge.boolean('rst_n'),old['state']==state,cutoff_bound,*extra],timeout_ms=timeout_ms)
        print('INTENSITY_STATE_PROVED',state,flush=True)
    error=old['out_error']
    roots=[model.cone('out_inner['+str(bit)+']') for bit in range(18)]
    outer=[model.cone('out_outer['+str(bit)+']') for bit in range(18)]
    actual_outputs=[bridge.pack(bridge.convert(roots)),bridge.pack(bridge.convert(outer)),
                    bridge.convert([model.cone('in_ready')])[0],
                    bridge.convert([model.cone('cfg_ready')])[0],bridge.convert([model.cone('out_valid')])[0]]
    bridge.check(actual_outputs,[z3.If(error,z3.BitVecVal(0,18),old['total_inner']),
        z3.If(error,z3.BitVecVal(0,18),old['total_outer']),
        z3.Or(old['state']==1,old['state']==2,old['state']==3,old['state']==5),old['state']==0,old['state']==6],
        label='ready_valid_and_error_masked_intensity_outputs',timeout_ms=timeout_ms)
    return dict(module_sha256=model.body_sha256,registered_bits=sum(width for _,width in FIELDS),
        encoded_states=len(selected_states),checked_state_codes=list(selected_states),checks=bridge.checks,cutoff_upper_bound_required=True,
        maximum_configured_rows=4096,maximum_region_intensity=4096*4*8,
        count_width=18,upstream_score_production_verified=False,complete_response_tag_behavior_verified=False)


def require_counterexample(error,*,expected_query=None):
    payload=error.args[0] if error.args else None
    assert isinstance(payload,tuple) and len(payload)==4 and payload[0]=='Intensity equivalence not proved' and payload[2]=='sat',(
        'Corruption did not produce an intended SAT counterexample',str(error))
    assert expected_query is None or payload[1]==expected_query,('Corruption failed in the wrong query',payload[1],expected_query)


def rejection_controls(body,library,states,timeout_ms):
    from hashlib import sha256
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_ratio_sequence import SequentialClassifier
    original=sha256(body).hexdigest();saved_library=[(key,dict(row)) for key,row in sorted(library.items())]
    rejected=[]
    for label,instance,pin,value,target,settings in [
        ('cutoff_sign_data_stuck_zero','cutoff_reg[33]','D',b"1'b0",1,
         dict(beat_index=3,rows_left=1,row_has_sink=True)),
        ('sink_maximum_bit_frozen','row_max_reg[0]','D',b'row_max[0]',1,
         dict(beat_index=0,rows_left=1,row_max=-(1<<31),row_has_sink=False)),
        ('inner_intensity_bit_frozen','total_inner_reg[0]','D',b'total_inner[0]',2,
         dict(beat_index=0,rows_left=1,row_max=1,cutoff=0,total_inner=0,total_outer=0,row_has_sink=True,cfg_alpha=1)),
        ('beat_index_bit_frozen','beat_index_reg[0]','D',b'beat_index[0]',1,
         dict(beat_index=0,rows_left=1,row_max=-(1<<31),row_has_sink=False)),
        ('row_count_decrement_frozen','rows_left_reg[0]','D',b'rows_left[0]',3,
         dict(beat_index=3,rows_left=2,row_max=1,cutoff=0,total_inner=0,total_outer=0,row_has_sink=True,cfg_alpha=1)),
        ('cutoff_reset_disconnected','cutoff_reg[0]','CDN',b"1'b1",None,{}),
    ]:
        altered=replace_instance_pin(body,instance,pin,value)
        if target is not None:
            settings={**dict(in_valid=True,in_region=target-1,in_last=False,in_lanes=1,
                             cfg_valid=False,cfg_ratio_den=1,cfg_ratio_num=1,
                             cfg_rows=settings['rows_left']),**settings}
        model=SequentialClassifier(altered,library,states)
        def conditions(bridge,old):
            result=[]
            for name,value in settings.items():
                if name in old:actual=old[name]
                elif type(value) is bool:actual=bridge.boolean(name)
                else:
                    first,last=model.module.declared[name];actual=bridge.word(name,abs(first-last)+1)
                result.append(actual==value)
            return result
        expected_query='all_actual_async_reset_bindings' if target is None else f'all_score_packet_next_fields_state{target}'
        try:prove_intensity(model,timeout_ms=timeout_ms,states_to_check=None if target is None else [target],query_conditions=conditions)
        except AssertionError as error:
            require_counterexample(error,expected_query=expected_query)
            payload=error.args[0]
            rejected.append(dict(control=label,rejection_query=payload[1],result='sat',
                                 activated_state=target,preconditions=settings,
                                 counterexample_sha256=sha256(payload[3].encode()).hexdigest()))
        else:raise AssertionError(('Intensity corruption accepted',label))
    altered=replace_instance_pin(body,'cutoff_reg[0]','CP',b'cfg_valid')
    try:prove_intensity(SequentialClassifier(altered,library,states),timeout_ms=timeout_ms)
    except AssertionError as error:
        assert str(error)=='Register clock differs','Clock rejected for an unrelated reason'
        rejected.append(dict(control='cutoff_register_wrong_clock',rejection='Register clock differs'))
    else:raise AssertionError('Wrong intensity clock accepted')
    assert sha256(body).hexdigest()==original and [(key,dict(row)) for key,row in sorted(library.items())]==saved_library
    return rejected


def verify(output,limit=None,timeout_ms=120000):
    from hashlib import file_digest,sha256
    import json
    import re
    import resource
    import time
    from link_tri_oracle_indexed_whole_chip import spans
    from prove_tri_oracle_parent_reset import Module
    from prove_tri_oracle_parent_clock import read_clock_library
    from prove_tri_oracle_head_ratio_sequence import SequentialClassifier,primary_state
    from prove_tri_oracle_packaged_products import CANDIDATE,ROOT,liberty_group,memory_guard

    assert __debug__ and not Path('/.dockerenv').exists()
    assert output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    assert limit is None or type(limit) is int and 1<=limit<=20
    assert 1<=timeout_ms<=120000
    memory_guard(10);started=time.monotonic();evidence={}
    def pin(path,expected=None):
        with path.open('rb') as stream:actual=file_digest(stream,'sha256').hexdigest()
        assert expected is None or actual==expected,('Changed intensity proof input',path)
        assert evidence.setdefault(str(path.relative_to(ROOT)),actual)==actual
        return path
    prior=json.loads(pin(ROOT/'records/tri_oracle_packaged_head_configuration.json').read_text())
    for name,digest in prior['evidence_sha256'].items():pin(ROOT/name,digest)
    full_name,= [name for name in prior['evidence_sha256'] if name.endswith('/configuration_qualified.json')]
    full=json.loads((ROOT/full_name).read_text())
    for name,digest in full['evidence_sha256'].items():pin(ROOT/name,digest)
    assert full['state']==prior['state']=='mapped_owned_head_configuration_safety_verified'
    assert full['candidate_sha256']==prior['candidate_sha256'] and full['corruption_controls_verified']
    source=CANDIDATE.read_bytes();assert sha256(source).hexdigest()==prior['candidate_sha256']
    pin(CANDIDATE,prior['candidate_sha256']);definitions=spans(source)
    bodies={};owners={}
    for master,row in full['classifiers'].items():
        assert master not in bodies and row['owner'] not in owners
        body=source[slice(*definitions[master])]
        assert sha256(body).hexdigest()==row['safety']['module_sha256']==row['arithmetic']['module_sha256']
        bodies[master]=body;owners[row['owner']]=master
    assert set(owners)==set(range(20))
    storage=json.loads((ROOT/'records/tri_oracle_packaged_storage_accounting.json').read_text())
    detail_name,=storage['full_detail_cache']
    detail=json.loads(pin(ROOT/detail_name,storage['full_detail_cache'][detail_name]).read_text())
    states={name:row['state_kinds'] for name,row in detail['standard_cell_state_by_master'].items()}
    modules={name:Module(body) for name,body in bodies.items()}
    masters={master for module in modules.values() for master,_ in module.cells.values()}
    sequential={master for master in masters if states.get(master)}
    libraries=[]
    for corner in ('tt1v25c','ssg0p9v125c','ffg1p05vm40c'):
        name,= [name for name in evidence if Path(name).name==f'tcbn28hpcplusbwp12t40p140{corner}.lib']
        path=ROOT/name;raw=read_clock_library(path,masters)
        library={key:{name:value for name,value in row.items() if name in ('direction','function')} for key,row in raw.items()}
        text=path.read_text()
        for master in sequential:
            match,=re.finditer(r'(?m)^cell\s*\('+re.escape(master)+r'\)\s*\{',text)
            library[master,'__sequence_ff__']=primary_state(liberty_group(text,match.end()))
        libraries.append(library)
    assert libraries[0]==libraries[1]==libraries[2],'Intensity cell functions differ across corners'
    for name in ['prove_tri_oracle_head_intensity.py','test_tri_oracle_head_intensity_logic.py']:pin(ROOT/'syn'/name)
    invariants=prove_numeric_invariants();results={}
    for owner,master in sorted(owners.items()):
        if limit is not None and len(results)==limit:break
        model=SequentialClassifier(bodies[master],libraries[0],states)
        results[master]=dict(owner=owner,**prove_intensity(model,timeout_ms=timeout_ms))
        print('MAPPED_INTENSITY_CLASSIFIER_PROVED',owner,master,flush=True)
    complete=len(results)==20
    rejected=rejection_controls(bodies[owners[0]],libraries[0],states,timeout_ms) if complete else []
    for name,digest in evidence.copy().items():pin(ROOT/name,digest)
    report=dict(state='mapped_local_head_score_packet_intensity_verified' if complete else 'mapped_head_intensity_diagnostic_subset',
        candidate_sha256=prior['candidate_sha256'],classifiers=results,complete_classifier_inventory=complete,
        z3_version=z3.get_full_version(),solver_timeout_ms=timeout_ms,evidence_sha256=evidence,
        wall_seconds=time.monotonic()-started,peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        numeric_invariants=invariants,cutoff_inductive_upper_bound_verified=complete,reachable_intensity_count_bound_verified=complete,
        corruption_controls_verified=complete,rejected_controls=rejected,full_head_prediction_verified=False,task_accuracy_verified=False,
        complete_paper_architecture_verified=False,physical_timing_verified=False,
        advance_to_clock_distribution_or_routing_allowed=False,
        assumptions=[
            'A common reset establishes the verified register basis before a transaction; reset interruptions abort it.',
            'Binary state is sampled on settled positive clock edges, with reset deasserted during uninterrupted packet processing.',
            'Valid-packet accumulation starts from an accepted nonerror configuration with1..4096 rows; malformed packets freeze prior counts and mask outputs.',
            'The remaining-rows-one budget at Classify/Hold concerns successful packets. Invalid/malformed Hold paths use zeroed or frozen prior count bounds.'
        ],
        scope='All20 candidate-local score-packet controllers and numerical intensity paths, bound to the previously verified parent configuration/clock/reset and local ratio records. '
              'Actual122 register bits match an independent word-level specification for all8 encoded states: masked signed32 sink maxima, final-beat signed34 cutoff with unsigned32 alpha, '
              'strict enabled-lane threshold counts, modular18 accumulation, row/beat progression, stalls, malformed/error retirement, asynchronous reset and ready/valid/error-masked count outputs. '
              'A reset/write/hold cutoff upper-bound invariant justifies the optimized signed comparison. Ghost beat budgets establish at most131072 hits per region on valid packets, '
              'so18-bit modular updates equal integer sums. Error and invalid-configuration paths preserve or zero that bound. '
              'Parent score/tag correctness, end-to-end actual score generation, complete prediction, eventual completion, task accuracy, timing and paper-result matching remain unqualified. '
              'The paper does not disclose the head-ratio threshold; configured threshold values and serial comparison are reconstruction choices.')
    with output.open('x') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    parser.add_argument('--limit',type=int);parser.add_argument('--timeout-ms',type=int,default=120000)
    arguments=parser.parse_args();result=verify(arguments.output,arguments.limit,arguments.timeout_ms)
    print(result['state'],result['wall_seconds'],flush=True)
