"""Prove saved parent configuration and reset-based owned-transaction safety.

Tile outputs are arbitrary binary cutpoints. No tile arithmetic, eventual
completion, intensity accumulation, response tags or physical timing is proved.
"""
from hashlib import sha256
from pathlib import Path

from prove_tri_oracle_head_ratio_sequence import SequentialClassifier,equal_functions
from prove_tri_oracle_packaged_products import BooleanGraph,memory_guard
from prove_tri_oracle_parent_reset import Module

LOCAL_BUSY = {1:{1,2,5,6},2:{2,3,5,6},3:{1,3,4,5,6},4:{4,6},5:{5,6}}


class ParentCone(SequentialClassifier):
    """Keep actual primitive logic; conservatively cut declared tile outputs."""
    def __init__(self,body,library,states,children):
        self.module=Module(body);self.body_sha256=self.module.sha256
        self.library,self.states=library,states;self.graph=BooleanGraph()
        self.inputs={bit for name,direction in self.module.directions.items() if direction=='input' for bit in self.module.net_bits(name)}
        self.drivers={};self.cones={};self.visiting=set();self.used_pins=set();self.boundaries=set()

        def install(net,driver):
            assert not net.startswith("1'") and net not in self.inputs,'Input or constant has an internal driver'
            assert net not in self.drivers,'Multiple parent drivers'
            self.drivers[net]=driver

        for net,source in self.module.assignments.items():install(net,('assign',source))
        for instance,(master,raw) in self.module.cells.items():
            if master in children:
                child=children[master]
                assert not raw.keys()-child.directions.keys(),'Unknown child port'
                assert {name for name,direction in child.directions.items() if direction=='input'}<=raw.keys(),'Missing tile input binding'
                for pin,expression in raw.items():
                    bits=self.module.expression(expression);direction=child.directions[pin]
                    assert direction in ('input','output'),'Unsupported tile direction'
                    if not bits and direction=='output':continue
                    assert len(bits)==len(child.net_bits(pin)),'Tile port width differs'
                    if direction=='output':
                        for bit in bits:install(bit,('boundary',instance,pin));self.boundaries.add(bit)
                continue
            pins={}
            for pin,expression in raw.items():
                bits=self.module.expression(expression)
                assert len(bits)<=1 and (master,pin) in library,'Unknown or vector primitive pin'
                pins[pin]=bits[0] if bits else ''
            for pin,net in pins.items():
                direction=library[master,pin]['direction'];assert direction in ('input','output')
                if direction=='output' and net:install(net,('cell',master,pin,pins))
        for name in ('clk','rst_n'):
            assert self.module.directions.get(name)=='input' and self.module.declared[name] is None,'Clock/reset port differs'

    def cone(self,net):
        if net in self.boundaries:return self.graph.variable(net)
        return super().cone(net)


def member_bits(graph,word,allowed):
    """Exact enum membership; reduce irrelevant output bits before substitution."""
    allowed=set(allowed)
    if not word or any(type(value) is not int or not 0<=value<(1<<len(word)) for value in allowed):
        raise ValueError('Invalid enum membership domain')

    def build(bit,values):
        if not values:return 0
        if len(values)==1<<(len(word)-bit):return 1
        low=build(bit+1,{value>>1 for value in values if not value&1})
        high=build(bit+1,{value>>1 for value in values if value&1})
        if low==high:return low
        return graph.operation('|',graph.operation('&',graph.operation('!',word[bit]),low),graph.operation('&',word[bit],high))
    return build(0,allowed)


def parent_fields():
    fields=[]
    for register,port,width,start in [('ratio_num','cfg_ratio_num',8,307),('ratio_den','cfg_ratio_den',8,299),
                                       ('alpha','cfg_alpha',32,328),('tag','cfg_tag',32,360)]:
        fields.extend((f'{register}_reg[{bit}]',f'head_request[{start+bit}]',f'{port}[{bit}]') for bit in range(width))
    fields.extend((f'classifier_owner_reg[{bit}]',f'head_request[{395+bit}]',None) for bit in range(5))
    return fields


def prove_parent(model):
    graph=model.graph;fields=parent_fields();data=[];resets=[];state_data=[]
    for instance,output,_ in fields:
        value,reset,reset_value=model.transition(instance,output)
        assert reset_value==0,'Parent saved field reset value differs'
        data.append(value);resets.append(reset)
    for bit in range(3):
        value,reset,reset_value=model.transition(f'state_reg[{bit}]',f'state[{bit}]')
        assert reset_value==0,'Parent state reset value differs'
        state_data.append(value);resets.append(reset)
    equal_functions(graph,resets,[graph.operation('!',graph.variable('rst_n'))]*88)
    held=[graph.variable(output) for _,output,_ in fields]
    field_cases=0

    def control(state,**extra):
        return {'rst_n':1,**{f'state[{bit}]':(state>>bit)&1 for bit in range(3)},**extra}

    for state in range(8):
        settings=control(state)
        if state==0:settings['cfg_valid']=0
        equal_functions(graph,graph.substitute(data,settings),held);field_cases+=1
        equal_functions(graph,graph.substitute([model.cone('cfg_ready')],control(state)),[int(state==0)])
        equal_functions(graph,graph.substitute([model.cone('head_request[394]')],control(state)),[int(state==1)])
        expected_ack=graph.variable('out_ready') if state==4 else 0
        equal_functions(graph,graph.substitute([model.cone('head_request[392]')],control(state)),[expected_ack])
        expected_valid=1 if state==5 else graph.variable('head_response[70]') if state==4 else 0
        equal_functions(graph,graph.substitute([model.cone('out_valid')],control(state)),[expected_valid])
    load=control(0,cfg_valid=1)
    equal_functions(graph,graph.substitute(data[:80],load),[graph.variable(port) for _,_,port in fields[:80]])
    for head_id in range(32):
        settings=load|{f'cfg_head_id[{bit}]':(head_id>>bit)&1 for bit in range(5)}
        owner=head_id-20 if head_id>=20 else head_id
        assert 0<=owner<20
        equal_functions(graph,graph.substitute(data[80:],settings),[(owner>>bit)&1 for bit in range(5)])

    def expect(state,allowed,extra=None):
        actual=graph.substitute(state_data,control(state,**(extra or {})))
        equal_functions(graph,[member_bits(graph,actual,allowed)],[1])

    expect(0,{0},{'cfg_valid':0});expect(0,{1,5},{'cfg_valid':1})
    for ready in (0,1):expect(1,{2 if ready else 1},{'head_response[72]':ready})
    expect(2,{2,3});expect(3,{2,3,4})
    for valid in (0,1):
        for ready in (0,1):expect(4,{0 if valid and ready else 4},{'head_response[70]':valid,'out_ready':ready})
    for ready in (0,1):expect(5,{0 if ready else 5},{'out_ready':ready})
    return dict(module_sha256=model.body_sha256,saved_field_registers=85,state_registers=3,
        asynchronous_zero_registers=88,field_hold_cases=field_cases,owner_input_cases=32,
        parent_reachable_states=list(range(6)),tile_outputs_are_unconstrained=True,
        external_configuration_ready_verified=True,configuration_and_retirement_controls_verified=True,
        tag_forwarding_to_classifiers_verified=False,exact_wait_batch_final_selection_verified=False)


def prove_local_safety(model):
    graph=model.graph;data=[];resets=[]
    for bit in range(3):
        value,reset,reset_value=model.transition(f'state_reg[{bit}]',f'state[{bit}]')
        assert reset_value==0,'Local state reset value differs'
        data.append(value);resets.append(reset)
    equal_functions(graph,resets,[graph.operation('!',graph.variable('rst_n'))]*3)
    for state in range(8):
        control={'rst_n':1,**{f'state[{bit}]':(state>>bit)&1 for bit in range(3)}}
        equal_functions(graph,graph.substitute([model.cone('cfg_ready')],control),[int(state==0)])
        equal_functions(graph,graph.substitute([model.cone('out_valid')],control),[int(state==6)])
        if state==0:
            for cfg in (0,1):
                actual=graph.substitute(data,control|{'cfg_valid':cfg})
                equal_functions(graph,[member_bits(graph,actual,{1,6} if cfg else {0})],[1])
        elif state in LOCAL_BUSY:
            equal_functions(graph,[member_bits(graph,graph.substitute(data,control),LOCAL_BUSY[state])],[1])
        elif state==6:
            for ready in (0,1):
                actual=graph.substitute(data,control|{'out_ready':ready})
                equal_functions(graph,[member_bits(graph,actual,{0 if ready else 6})],[1])
    return dict(module_sha256=model.body_sha256,reset_state=0,reachable_states=list(range(7)),
        busy_successors_exclude_idle_and_illegal_seven=True,configuration_ready_iff_idle=True,
        result_valid_iff_hold=True,retirement_iff_ready=True)


def abstract_successors(parent,head,cfg_valid,external_ready):
    """Overapproximate tile/score behavior, preserving shared handshake equations."""
    cfg_ready=int(head==0);valid=int(head==6)
    local_cfg=int(parent==1);local_ready=int(parent==4 and external_ready)
    if parent==0:parents={1,5} if cfg_valid else {0}
    elif parent==1:parents={2 if cfg_ready else 1}
    elif parent==2:parents={2,3}
    elif parent==3:parents={2,3,4}
    elif parent==4:parents={0 if valid and external_ready else 4}
    elif parent==5:parents={0 if external_ready else 5}
    else:raise ValueError('Unqualified parent state')
    if head==0:heads={1,6} if local_cfg else {0}
    elif head==6:heads={0 if local_ready else 6}
    elif head in LOCAL_BUSY:heads=LOCAL_BUSY[head]
    else:raise ValueError('Unqualified classifier state')
    return {(p,h) for p in parents for h in heads}


def transaction_invariant():
    """Finite inductive check, based at common reset parent0/all classifiers0.

    Every nonselected head has cfg_valid=out_ready=0 and remains Idle. Owner
    changes only on a parent Idle load, when all heads are Idle. Therefore a
    selected-head abstraction is exact for this safety invariant after the
    routing and register-update component contracts have been verified.
    """
    domain={(0,0),(1,0),(5,0)}|{(parent,head) for parent in (2,3,4) for head in range(1,7)}
    assert (0,0) in domain
    transitions=accepts=0
    for parent,head in domain:
        accepted=int(parent in (2,3,4))
        for cfg_valid in (0,1):
            for ready in (0,1):
                local_accept=int(parent==1 and head==0)
                assert accepted+local_accept<=1,'More than one local configuration accept'
                for next_parent,next_head in abstract_successors(parent,head,cfg_valid,ready):
                    assert (next_parent,next_head) in domain,'Owned transaction invariant is not closed'
                    next_accepted=0 if next_parent==0 else accepted+local_accept
                    assert next_accepted==int(next_parent in (2,3,4)),'Configuration accept count is inconsistent'
                    if next_parent==0 and parent in (2,3,4):
                        assert parent==4 and head==6 and ready and next_head==0,'Parent/head retirement is not coupled'
                    transitions+=1;accepts+=local_accept
    return dict(common_reset_basis='parent0 and all20 classifier states0',abstract_mode_pairs=len(domain),
        checked_edges=transitions,local_accept_edges=accepts,
        single_owned_active_classifier=True,at_most_one_local_accept_per_parent_transaction=True,
        invalid_parent_configuration_creates_no_local_accept=True,
        parent_and_selected_head_retire_together=True,
        eventual_completion_verified=False)


def replace_instance_pin(body,instance,pin,replacement):
    """Change exactly one actual binding in memory for negative controls."""
    from prove_tri_oracle_parent_reset import INSTANCE,identifier
    from prove_tri_oracle_packaged_products import PIN
    matches=[match for match in INSTANCE.finditer(body) if identifier(match[2].decode())==instance]
    assert len(matches)==1,'Expected exactly one mutation instance'
    match,=matches
    bindings=[item for item in PIN.finditer(match[3]) if identifier(item[1].decode())==pin]
    assert len(bindings)==1,'Expected exactly one mutation pin'
    binding,=bindings
    fields=match[3][:binding.start(2)]+replacement+match[3][binding.end(2):]
    changed=body[:match.start(3)]+fields+body[match.end(3):]
    assert changed!=body,'Ineffective configuration mutation'
    return changed


def rejection_controls(parent_body,library,states,children,checker):
    """Reject actual field/clock/reset/bus faults without editing the candidate."""
    from prove_tri_oracle_head_routing import HeadRoutes,prove_routes
    original_sha=sha256(parent_body).hexdigest()
    original_library=[(key,dict(value)) for key,value in sorted(library.items())]
    rejected=[]

    def reject(label,action,wanted):
        try:action()
        except (AssertionError,ValueError,KeyError) as error:
            reason=str(error)
            assert wanted in reason,('Unrelated configuration rejection',label,reason)
            rejected.append(dict(control=label,rejection=reason))
        else:raise AssertionError(('Corrupted configuration accepted',label))

    for label,instance,pin,value,wanted in [
        ('wrong_parent_register_clock','ratio_num_reg[0]','CP',b'cfg_valid','Register clock differs'),
        ('disconnected_parent_register_reset','ratio_num_reg[0]','CDN',b"1'b1",'Mapped sequence transition differs'),
        ('lost_parent_scan_feedback','ratio_num_reg[0]','SI',b"1'b0",'Mapped sequence transition differs'),
        ('stuck_parent_owner_load','classifier_owner_reg[0]','D',b"1'b0",'Mapped sequence transition differs'),
    ]:
        changed=replace_instance_pin(parent_body,instance,pin,value)
        reject(label,lambda changed=changed:prove_parent(ParentCone(changed,library,states,children)),wanted)

    for label,target,pin,value in [
        ('disconnected_selected_numerator',checker.heads[0],'cfg_ratio_num',b"8'b0"),
        ('disconnected_owner_configuration_valid',checker.heads[0],'cfg_valid',b"1'b0"),
        ('disconnected_head_clock',checker.heads[0],'clk',b"1'b0"),
        ('disconnected_selected_response',checker.scheduler,'head_response',b"73'b0"),
    ]:
        master,parent,_=checker.contexts[target]
        instance=target.rsplit('/',1)[-1]
        parent_master=checker.contexts[parent][0]
        changed=replace_instance_pin(checker.body(parent_master),instance,pin,value)
        mutated=HeadRoutes(lambda name:changed if name==parent_master else checker.body(name),
                           checker.masters,library,states,checker.contexts[''][0],checker.scheduler,
                           checker.heads,guard=checker.guard)
        reject(label,lambda:prove_routes(mutated),'Mapped sequence transition differs')
    assert sha256(parent_body).hexdigest()==original_sha,'Original parent bytes changed'
    assert [(key,dict(value)) for key,value in sorted(library.items())]==original_library,'Original library changed'
    return rejected


def verify(output):
    """Bind route, state and ownership contracts to one immutable candidate."""
    from hashlib import file_digest
    import json
    import re
    import resource
    import time
    from audit_tri_oracle_mapped_redundancy import CHILD
    from link_tri_oracle_indexed_whole_chip import spans,signature,DECLARATION
    from prove_tri_oracle_head_routing import HeadRoutes,prove_routes,routing_libraries
    from prove_tri_oracle_head_ratio import prove_module
    from prove_tri_oracle_head_ratio_sequence import primary_state,prove_sequence,register_specification,range_invariant
    from prove_tri_oracle_packaged_products import CANDIDATE,ROOT,liberty_group

    assert __debug__ and not Path('/.dockerenv').exists()
    assert output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);started=time.monotonic();evidence={}

    def pin(path,expected=None):
        with path.open('rb') as stream:actual=file_digest(stream,'sha256').hexdigest()
        assert expected is None or actual==expected,('Changed configuration proof input',path)
        assert evidence.setdefault(str(path.relative_to(ROOT)),actual)==actual
        return path

    prior=json.loads(pin(ROOT/'records/tri_oracle_packaged_head_ratio_sequence.json').read_text())
    for name,digest in prior['evidence_sha256'].items():pin(ROOT/name,digest)
    structure=json.loads(pin(ROOT/'records/tri_oracle_packaged_compute_structure.json').read_text())
    storage=json.loads(pin(ROOT/'records/tri_oracle_packaged_storage_accounting.json').read_text())
    assert structure['candidate_sha256']==storage['candidate_sha256']==prior['candidate_sha256']
    detail_name,=storage['full_detail_cache']
    detail=json.loads(pin(ROOT/detail_name,storage['full_detail_cache'][detail_name]).read_text())
    states={name:row['state_kinds'] for name,row in detail['standard_cell_state_by_master'].items()}
    source=CANDIDATE.read_bytes();assert sha256(source).hexdigest()==prior['candidate_sha256']
    pin(CANDIDATE,prior['candidate_sha256']);definitions=spans(source)

    def body(master):return source[slice(*definitions[master])]

    schedulers=[];heads={};target_masters={}
    def walk(master,path,parents):
        assert master not in parents,'Recursive configuration hierarchy'
        if master.startswith('tri_oracle_attention_head_predictor415_CORE_HEAD_PREDICTOR1'):
            schedulers.append(path);target_masters[path]=master
        if master.startswith('tri_oracle_attention_head_classifier410_SERIAL_RATIO1_SHARED_CONFIG1'):
            match,=re.finditer(r'clusters\[(\d+)\]\.unit/selected_bank(\d+)\.block_instance/source_cluster/implementation/cores\[(\d+)\]/head\.predict/classifier$',path)
            bank,other,core=map(int,match.groups());assert bank==other and 0<=bank<5 and 0<=core<4
            owner=4*bank+core;assert owner not in heads;heads[owner]=path;target_masters[path]=master
        lo,hi=definitions[master];children={}
        for match in CHILD.finditer(source,lo,hi):
            kind,instance=(item.decode() for item in match.groups())
            if kind not in definitions:
                assert kind.startswith(('TS5N28','TS6N28'));continue
            assert instance not in children;children[instance]=kind
        for instance,kind in children.items():
            local=instance.removeprefix('\\');assert '/' not in local,'Ambiguous hierarchy separator'
            walk(kind,path+'/'+local if path else local,parents|{master})
    walk(structure['logical_top'],'',set());scheduler,=schedulers
    assert set(heads)==set(range(20))
    arithmetic=json.loads((ROOT/'records/tri_oracle_packaged_head_ratio_arithmetic.json').read_text())
    for path in heads.values():assert sha256(body(target_masters[path])).hexdigest()==arithmetic['module_sha256'][target_masters[path]]

    sources={};masters=set(storage['compiled_memory_by_master'])
    for corner in ('tt1v25c','ssg0p9v125c','ffg1p05vm40c'):
        rows=[(name,digest) for name,digest in structure['evidence_sha256'].items() if name.endswith(corner+'.lib')]
        assert len(rows)==7,'Expected standard cells and six memory views'
        sources[corner]=[pin(ROOT/name,digest) for name,digest in rows]
        standard,=(path for path in sources[corner] if path.name.startswith('tcbn28hpcplus'))
        masters.update(name.strip() for name in re.findall(r'(?m)^cell\s*\(([^)]+)\)\s*\{',standard.read_text()))
    tables=routing_libraries(sources,masters)
    modules={master:Module(body(master)) for master in target_masters.values()}
    sequential={modules[target_masters[scheduler]].cells[instance][0] for instance,_,_ in parent_fields()}
    sequential.update(modules[target_masters[scheduler]].cells[f'state_reg[{bit}]'][0] for bit in range(3))
    sequential.update(modules[target_masters[path]].cells[instance][0] for path in heads.values() for instance,_,_ in register_specification())
    for corner,library in tables.items():
        standard,=(path for path in sources[corner] if path.name.startswith('tcbn28hpcplus'))
        text=standard.read_text()
        for master in sequential:
            match,=re.finditer(r'(?m)^cell\s*\('+re.escape(master)+r'\)\s*\{',text)
            library[master,'__sequence_ff__']=primary_state(liberty_group(text,match.end()))
        for path in heads.values():
            master=modules[target_masters[path]].cells['streaming_reg'][0]
            library[master,'__capture_ff__']=library[master,'__sequence_ff__']
    libraries=list(tables.values());assert libraries[0]==libraries[1]==libraries[2],'Sequential functions differ across corners'
    library=libraries[0]
    for name in ['prove_tri_oracle_head_configuration.py','test_tri_oracle_head_configuration_logic.py',
                 'prove_tri_oracle_head_routing.py','test_tri_oracle_head_routing_logic.py']:
        pin(ROOT/'syn'/name)
    checker=HeadRoutes(body,set(definitions),library,states,structure['logical_top'],scheduler,heads,
                       guard=lambda:memory_guard(8.5))
    routes=prove_routes(checker);print('CONFIGURATION_ROUTES_PROVED',flush=True)
    parent_master=target_masters[scheduler];parent_module=modules[parent_master]
    tile_children={name:(instance,pins) for instance,(name,pins) in parent_module.cells.items() if name in definitions}
    assert len(tile_children)==1,'Expected one parent tile child'
    tile_master,(tile_instance,_)=next(iter(tile_children.items()))
    assert tile_instance=='tile' and tile_master.startswith('tri_oracle_attention_tile_batch413'),'Unknown parent child'
    # Parse only actual port declarations; the child's internal arithmetic is
    # intentionally unconstrained in this parent-control safety proof.
    tile_body=body(tile_master);signature(tile_body)
    end=tile_body.index(b');')+2
    tile_ports=Module(tile_body[:end]+b'\n'+b'\n'.join(match[0] for match in DECLARATION.finditer(tile_body[end:]))+b'\nendmodule')
    children={tile_master:tile_ports}
    parent=prove_parent(ParentCone(body(parent_master),library,states,children))
    parent['tile_module_sha256']=sha256(tile_body).hexdigest()
    print('PARENT_CONFIGURATION_STATE_PROVED',flush=True)
    local={}
    for owner,path in sorted(heads.items()):
        memory_guard(8.5);master=target_masters[path]
        model=SequentialClassifier(body(master),library,states)
        local[master]=dict(owner=owner,path=path,safety=prove_local_safety(model),
                           arithmetic=prove_module(model),epoch=prove_sequence(model))
        print('OWNED_CLASSIFIER_PROVED',owner,master,flush=True)
    invariant=transaction_invariant();bounds=range_invariant()
    rejected=rejection_controls(body(parent_master),library,states,children,checker)
    for name,digest in evidence.copy().items():pin(ROOT/name,digest)
    report=dict(state='mapped_owned_head_configuration_safety_verified',candidate_sha256=prior['candidate_sha256'],
        scheduler_path=scheduler,scheduler_master=parent_master,routes=routes,parent=parent,classifiers=local,
        ownership_invariant=invariant,range_invariant=bounds,evidence_sha256=evidence,
        wall_seconds=time.monotonic()-started,peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        parent_numeric_configuration_stable_during_owned_transactions=True,
        common_reset_basis_required=True,binary_settled_clock_edges_required=True,
        reset_interruptions_abort_owned_epochs=True,
        assumptions=[
            'A common reset establishes parent state0 and all20 classifier states0 before an owned transaction.',
            'State is sampled on settled binary positive clock edges; reset stays deasserted throughout each uninterrupted classification epoch.',
            'A reset interruption aborts the current owned epoch; uninterrupted coefficient stability is not claimed across reset.'
        ],
        corruption_controls_verified=True,rejected_controls=rejected,intensity_accumulation_verified=False,eventual_completion_verified=False,
        complete_response_tag_stability_verified=False,full_head_prediction_verified=False,
        complete_paper_architecture_verified=False,task_accuracy_verified=False,physical_timing_verified=False,
        advance_to_clock_distribution_or_routing_allowed=False,
        scope='Candidate-bound numerical configuration and ownership safety from common reset. '
              'All48 numeric input bits reach each of20 actual classifiers; owner-gated configuration, input-valid and retirement controls, '
              'selected non-tag response routes and common clock/reset endpoints are verified. '
              'The actual85 saved parent fields and3 state registers satisfy clear/load/hold and all32 head-id normalizations. '
              'Actual local controller domains compose with shared ready/valid equations to prove at most one owned accept, '
              'idle nonowners, stable numeric coefficients during reset-deasserted owned epochs, and coupled retirement. '
              'Rerun local ratio arithmetic and8-step epoch proofs establish exact integer comparison for their existing18-bit intensity registers. '
              'Tile outputs remain arbitrary binary cuts. Reset interrupts and aborts an epoch. '
              'Intensity computation, eventual completion, full response/tag behavior, full prediction, task accuracy, physical timing and paper-result matching remain unqualified.')
    with output.open('x') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    arguments=parser.parse_args();result=verify(arguments.output)
    print(result['state'],result['wall_seconds'],flush=True)
