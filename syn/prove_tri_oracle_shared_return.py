"""Verify mapped shared-receiver ownership and attention response transport.

The raw receiver outputs form an explicit declared-output boundary. Numerical
score production, eventual completion, full prediction and accuracy are separate.
"""
if not __debug__:raise RuntimeError('Shared return verification requires assertions')
from pathlib import Path
import re,z3


def ownership_invariant(owned,busy,paired):
    assert all(z3.is_bool(x) for x in (owned,busy,paired)),'Expected three Boolean physical flags'
    return z3.Implies(owned,z3.And(busy,z3.Not(paired)))


def ownership_reference_next(owned,busy,paired,attention_accept,attention_terminal,
                             receiver_accept,receiver_terminal,receiver_paired):
    assert all(z3.is_bool(x) for x in (owned,busy,paired,attention_accept,attention_terminal,
        receiver_accept,receiver_terminal,receiver_paired)),'Expected Boolean ownership events'
    return (z3.If(attention_accept,z3.BoolVal(True),z3.If(attention_terminal,z3.BoolVal(False),owned)),
            z3.If(receiver_accept,z3.BoolVal(True),z3.If(receiver_terminal,z3.BoolVal(False),busy)),
            z3.If(receiver_accept,receiver_paired,paired))


def shared_environment(original,*,body_overrides=None):
    from prove_tri_oracle_command_admission import AdmissionRoutes
    from prove_tri_oracle_tile_score_packet import primary_tile_state
    from prove_tri_oracle_packaged_products import liberty_group
    source=original['routes'];absolute=original['paths']['arbiter'];top=source.contexts[source.walk(absolute)][0]
    overrides=body_overrides or {};assert set(overrides)<=source.masters
    routes=AdmissionRoutes(lambda master:overrides[master] if master in overrides else source.body(master),
        source.masters,source.library,source.states,top,guard=source.guard)
    wrapper=routes.child('','compute');cuts=[]
    for context in ('',wrapper):
        module=routes.module(routes.contexts[context][0])
        for instance,(master,_) in module.cells.items():
            if master not in routes.masters or not master.startswith('tri_oracle_'):continue
            if context=='' and instance=='compute':continue
            child=routes.child(context,instance);ports=routes.ports(master)
            outputs={bit for name,direction in ports.directions.items() if direction=='output' for bit in ports.net_bits(name)}
            routes.offpath[child]=outputs;cuts.append(dict(context=child,master=master,output_bits=len(outputs)))
    selected=[('','attention_owned_reg'),(wrapper,'busy_reg'),(wrapper,'paired_reg')]
    masters={routes.module(routes.contexts[context][0]).cells[instance][0] for context,instance in selected}
    tables=[]
    for paths in original['sources'].values():
        standard,=(p for p in paths if p.name.startswith('tcbn28'));text=standard.read_text();table={}
        for master in sorted(masters):
            match,=re.finditer(r'(?m)^cell\s*\('+re.escape(master)+r'\)\s*\{',text)
            table[master]=primary_tile_state(liberty_group(text,match.end()))
        tables.append(table)
    assert len(tables)==3 and tables[0]==tables[1]==tables[2],'Shared ownership primary models differ across corners'
    return dict(routes=routes,wrapper=wrapper,selected=selected,primary=tables[0],
                boundary_cuts=cuts,absolute_arbiter=absolute)


def prove_epoch(environment,*,only_query=None,activation=()):
    from prove_tri_oracle_head_intensity import WordBridge
    from prove_tri_oracle_layer_row_epoch import physical_register
    from prove_tri_oracle_tile_command_routes import route_word
    from prove_tri_oracle_tile_geometry import geometry_check
    routes=environment['routes'];bridge=WordBridge(routes.graph)
    records=[physical_register(routes,bridge,context,instance,environment['primary'])
             for context,instance in environment['selected']]
    assert [r['q'] for r in records]==['attention_owned','busy','paired'],'Shared ownership primary Q identities differ'
    old=[r['old'] for r in records];following=[r['data'] for r in records];rst=bridge.boolean('top.rst_n')
    def check(actual,wanted,label,*,conditions=()):
        routes.guard();result=geometry_check(bridge,actual,wanted,label=label,conditions=conditions,
            only_query=only_query,activation=activation);routes.guard();return result
    check([r['clock'] for r in records],[bridge.boolean('top.clk')]*3,'all3_shared_ownership_state_clocks')
    check([r['reset'] for r in records],[z3.Not(rst)]*3,'all3_shared_ownership_state_reset_bindings')
    check([ownership_invariant(*(z3.BoolVal(bool(r['reset_value'])) for r in records))],
          [z3.BoolVal(True)],'shared_ownership_actual_reset_basis')
    invariant=ownership_invariant(*old)
    check([ownership_invariant(*following)],[z3.BoolVal(True)],'shared_ownership_actual_state_induction',conditions=[rst,invariant])
    def word(context,name,direction=None):return route_word(routes,bridge,context,name,1,direction=direction)
    attention_accept=z3.And(word('','attention_cfg_valid','input'),word('','attention_cfg_ready','output'))
    attention_terminal=z3.And(word('','attention_done_valid','output'),word('','attention_done_ready','input'))
    child=environment['wrapper']
    receiver_accept=z3.And(word(child,'cfg_valid','input'),word(child,'cfg_ready','output'))
    receiver_terminal=z3.And(word(child,'done_valid','output'),word(child,'done_ready','input'))
    receiver_paired=word(child,'cfg_paired','input')
    check(following,list(ownership_reference_next(*old,attention_accept,attention_terminal,
          receiver_accept,receiver_terminal,receiver_paired)),
          'all3_shared_flag_actual_next_values',conditions=[rst])
    check([following[0],following[1],z3.Not(following[2])],[z3.BoolVal(True)]*3,
          'attention_acceptance_acquires_owned_busy_unpaired',conditions=[rst,attention_accept])
    check([following[0],following[1],z3.Not(following[2])],[z3.BoolVal(True)]*3,
          'owned_attention_retains_receiver_until_terminal_accept',
          conditions=[rst,invariant,old[0],z3.Not(attention_terminal)])
    check(following,[z3.BoolVal(False)]*3,'owned_attention_terminal_accept_releases_receiver',
          conditions=[rst,invariant,old[0],attention_terminal])
    selected=route_word(routes,bridge,'','attention_selected',1)
    check([selected,old[1],z3.Not(old[2])],[z3.BoolVal(True)]*3,
          'owned_attention_holds_selected_busy_unpaired',conditions=[invariant,old[0]])
    assert only_query is None or len(bridge.checks)==1,'Targeted shared ownership query absent'
    witnesses=[];event_witnesses=[]
    if only_query is None:
        from prove_tri_oracle_accepted_command import accepted_witness
        for values in ((False,False,False),(False,True,True),(True,True,False)):
            result=accepted_witness([rst,invariant,*(value==wanted for value,wanted in zip(old,values,strict=True))])
            witnesses.append(dict(owned=values[0],busy=values[1],paired=values[2],result=result,
                                  full_clock_history_reachability_verified=False))
        for event,conditions in (
            ('attention_acquisition',[rst,attention_accept]),
            ('stalled_terminal',[rst,invariant,old[0],word('','attention_done_valid','output'),
                                 z3.Not(word('','attention_done_ready','input'))]),
            ('terminal_retirement',[rst,invariant,old[0],attention_terminal])):
            result=accepted_witness(conditions)
            event_witnesses.append(dict(event=event,result=result,full_clock_history_reachability_verified=False))
    return dict(bridge=bridge,records=records,old=old,following=following,invariant=invariant,
                queries=bridge.checks,witnesses=witnesses,event_witnesses=event_witnesses)


def prove_return_routes(original,*,only_query=None,activation=()):
    from prove_tri_oracle_accepted_command import clone_environment,accepted_witness
    from prove_tri_oracle_head_intensity import WordBridge
    from prove_tri_oracle_tile_command_routes import route_word
    from prove_tri_oracle_tile_geometry import geometry_check
    base=original['routes'];top=base.contexts[''][0]
    environment=clone_environment(original,top,base.body(top));routes=environment['routes'];paths=environment['paths']
    owner=routes.walk(paths['owner']);ports=routes.ports(routes.contexts[owner][0])
    outputs={bit for name,direction in ports.directions.items() if direction=='output' for bit in ports.net_bits(name)}
    routes.offpath[owner]=outputs;bridge=WordBridge(routes.graph)
    def word(role,name,width,direction=None):
        return route_word(routes,bridge,paths[role],name,width,direction=direction)
    owned=word('arbiter','attention_owned',1);busy=word('wrapper','busy',1);paired=word('wrapper','paired',1)
    layer=word('layer','state',4)
    context=routes.walk(paths['pipeline']);root=routes.trace(context,'tensor_cfg_activation_stride[11]')
    node=routes.graph.nodes[root]
    assert node[0]=='v' and routes.sequential_cuts[node[1]]['instance']=='projection_busy_reg','Return projection alias differs'
    projection,=bridge.convert([root])
    from prove_tri_oracle_pipeline_layer_epoch import exclusion_invariant
    head_conditions=[bridge.boolean('top.rst_n'),layer==5,exclusion_invariant(projection,layer),
                     ownership_invariant(owned,busy,paired)]
    conditions=[*head_conditions,owned]
    def check(actual,wanted,label,*,when=None):
        routes.guard();result=geometry_check(bridge,actual,wanted,label=label,
            conditions=conditions if when is None else when,only_query=only_query,activation=activation)
        routes.guard();return result
    check([word(role,name,1,'input') for role in ('arbiter','wrapper','owner','pipeline','layer','parent','tile') for name in ('clk','rst_n')],
          [bridge.boolean('top.'+name) for _ in range(7) for name in ('clk','rst_n')],
          'all7_response_endpoints_common_clock_reset',when=[])
    producer_accept=z3.And(bridge.boolean('top.rst_n'),word('tile','tensor_cfg_valid',1,'output'),
                           word('tile','tensor_cfg_ready',1,'input'))
    shared_accept=z3.And(word('arbiter','attention_cfg_valid',1,'input'),word('arbiter','attention_cfg_ready',1,'output'))
    check([shared_accept],[z3.BoolVal(True)],'actual_producer_handshake_enters_shared_attention_epoch',when=[producer_accept])
    owner_data=word('owner','out_data',5120,'output')
    check([word('tile','tensor_out_data',3072,'input')],[z3.Extract(3071,0,owner_data)],'all3072_returned_owner_score_bits')
    fields=[('tensor_out_tag','out_tag',32),('tensor_out_token','out_token',4),('tensor_out_last','out_last',1),
            ('tensor_out_count','out_count',8),('tensor_done_tag','done_tag',32),('tensor_done_error','done_error',1)]
    check([word('tile',incoming,width,'input') for incoming,_,width in fields],
          [word('owner',outgoing,width,'output') for _,outgoing,width in fields],'all_returned_owner_metadata_and_terminal_fields')
    check([word('tile','tensor_out_valid',1,'input'),word('tile','tensor_done_valid',1,'input')],
          [word('owner','out_valid',1,'output'),word('owner','done_valid',1,'output')],'actual_owner_packet_and_terminal_valid_forwarding')
    check([word('tile','tensor_out_valid',1,'input'),word('tile','tensor_done_valid',1,'input')],
          [z3.BoolVal(False)]*2,'unowned_attention_suppresses_packet_and_terminal_valid',
          when=[*head_conditions,z3.Not(owned)])
    ready=word('tile','tensor_out_ready',1,'output')
    check([word('owner','out_ready',1,'input'),word('owner','done_ready',1,'input')],[ready,ready],
          'actual_owner_packet_and_terminal_ready_feedback')
    witnesses=[];producer_witness=None
    if only_query is None:
        state=word('tile','state',3)
        for code in (3,5,6):
            result=accepted_witness([*conditions,state==code,word('owner','out_valid',1,'output')])
            witnesses.append(dict(tile_state=code,owned=True,result=result,full_clock_history_reachability_verified=False))
        result=accepted_witness([*head_conditions,z3.Not(owned),busy,paired,state==3,
                                 word('owner','out_valid',1,'output')])
        witnesses.append(dict(tile_state=3,owned=False,wrapper_busy=True,wrapper_paired=True,result=result,
                              full_clock_history_reachability_verified=False))
        producer_witness=dict(event='producer_acceptance',result=accepted_witness([producer_accept]),
                              full_clock_history_reachability_verified=False)
    assert only_query is None or len(bridge.checks)==1,'Targeted response route query absent'
    return dict(queries=bridge.checks,witnesses=witnesses,bridge=bridge,conditions=conditions,
                head_conditions=head_conditions,owned=owned,producer_acceptance_witness=producer_witness,
                owner_response_boundary=dict(context=owner,output_bits=len(outputs)),routes=routes)


def epoch_corruption_controls(original):
    from hashlib import sha256
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_intensity import WordBridge,require_counterexample
    from prove_tri_oracle_tile_command_routes import route_word
    base=shared_environment(original);routes=base['routes'];wrapper=base['wrapper']
    arbiter_master=routes.contexts[''][0];wrapper_master=routes.contexts[wrapper][0]
    bodies={master:routes.body(master) for master in (arbiter_master,wrapper_master)}
    controls=[
        ('attention_owned_spurious_start',arbiter_master,'attention_owned_reg',{'D':"1'b1",'E':"1'b1"},'idle'),
        ('receiver_busy_premature_clear',wrapper_master,'busy_reg',{'D':"1'b0",'SE':"1'b0"},'hold'),
        ('receiver_paired_spurious_set',wrapper_master,'paired_reg',{'D':"1'b1",'E':"1'b1"},'hold'),
        ('attention_owned_terminal_clear_blocked',arbiter_master,'attention_owned_reg',{'D':"1'b1",'E':"1'b1"},'terminal'),
        ('attention_accepted_in_paired_mode',arbiter_master,'compute',{'cfg_paired':"1'b1"},'accept'),
        ('attention_owned_never_acquires',arbiter_master,'attention_owned_reg',{'D':"1'b0",'E':"1'b1"},'acquire'),
        ('attention_owned_clears_while_terminal_stalls',arbiter_master,'attention_owned_reg',{'D':"1'b0",'E':"1'b1"},'stall'),
        ('receiver_busy_reset_disconnected',wrapper_master,'busy_reg',{'CDN':"1'b1"},'reset')]
    rejected=[]
    for label,master,instance,pins,mode in controls:
        altered=bodies[master]
        for pin,value in pins.items():altered=replace_instance_pin(altered,instance,pin,value.encode())
        environment=shared_environment(original,body_overrides={master:altered})
        changed=environment['routes'];bridge=WordBridge(changed.graph);child=environment['wrapper']
        def word(context,name,direction=None):return route_word(changed,bridge,context,name,1,direction=direction)
        rst=bridge.boolean('top.rst_n')
        if mode=='reset':active=[z3.Not(rst)];query='all3_shared_ownership_state_reset_bindings'
        else:
            owned=word('','attention_owned');busy=word(child,'busy');paired=word(child,'paired')
            active=[rst,owned==(mode in ('hold','terminal','stall')),busy==(mode in ('hold','terminal','stall')),z3.Not(paired)]
            if mode=='idle':
                active.append(z3.Not(word(child,'accept')));query='all3_shared_flag_actual_next_values'
            elif mode=='hold':
                active.append(z3.Not(word(child,'done_valid','output')))
                query='owned_attention_retains_receiver_until_terminal_accept'
            elif mode=='terminal':
                active.extend([word('','attention_done_valid','output'),word('','attention_done_ready','input')])
                query='owned_attention_terminal_accept_releases_receiver'
            elif mode=='stall':
                active.extend([word('','attention_done_valid','output'),z3.Not(word('','attention_done_ready','input'))])
                query='owned_attention_retains_receiver_until_terminal_accept'
            else:
                active.extend([word('','attention_cfg_valid','input'),word('','attention_cfg_ready','output')])
                query='attention_acceptance_acquires_owned_busy_unpaired'
        try:prove_epoch(environment,only_query=query,activation=active)
        except AssertionError as error:
            require_counterexample(error,expected_query=query)
            rejected.append(dict(control=label,result='sat',query=query,activation=mode,instance=instance,
                changed_pins=pins,altered_module_sha256=sha256(altered).hexdigest()))
            print('SHARED_RETURN_CORRUPTION_REJECTED',label,query,flush=True)
        else:raise AssertionError(('Shared epoch corruption accepted',label))
    altered=replace_instance_pin(bodies[wrapper_master],'busy_reg','CP',b"1'b0")
    try:prove_epoch(shared_environment(original,body_overrides={wrapper_master:altered}))
    except AssertionError as error:
        assert str(error)=='Epoch register clock differs',('Unrelated shared clock rejection',str(error))
        rejected.append(dict(control='receiver_busy_wrong_clock',rejection=str(error),altered_module_sha256=sha256(altered).hexdigest()))
    else:raise AssertionError('Shared receiver wrong clock accepted')
    assert len(rejected)==9
    return rejected


def return_corruption_controls(original,qualified):
    from hashlib import sha256
    from prove_tri_oracle_accepted_command import clone_environment
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_intensity import WordBridge,require_counterexample
    from prove_tri_oracle_tile_command_routes import route_word
    from prove_tri_oracle_tile_command_controls import replace_bus_bit
    routes=original['routes'];paths=original['paths']
    def body_at(role):
        context=routes.walk(paths[role]);master=routes.contexts[context][0]
        return master,routes.body(master)
    parent_master,parent_body=body_at('parent');wrapper_master,wrapper_body=body_at('wrapper')
    controls=[
        ('returned_score_bit_lost',parent_master,parent_body,'tile','tensor_out_data',
         replace_bus_bit('tensor_out_data',3072,0,"1'b0"),'all3072_returned_owner_score_bits','data'),
        ('returned_tag_lost',parent_master,parent_body,'tile','tensor_out_tag',"32'd0",
         'all_returned_owner_metadata_and_terminal_fields','tag'),
        ('returned_count_wrong',parent_master,parent_body,'tile','tensor_out_count',"8'd95",
         'all_returned_owner_metadata_and_terminal_fields','count'),
        ('returned_packet_valid_dropped',parent_master,parent_body,'tile','tensor_out_valid',"1'b0",
         'actual_owner_packet_and_terminal_valid_forwarding','valid'),
        ('returned_raw_owner_ready_dropped',wrapper_master,wrapper_body,'tensor','out_ready',"1'b0",
         'actual_owner_packet_and_terminal_ready_feedback','ready'),
        ('returned_terminal_error_lost',parent_master,parent_body,'tile','tensor_done_error',"1'b0",
         'all_returned_owner_metadata_and_terminal_fields','error'),
        ('unowned_predictor_spurious_packet_valid',parent_master,parent_body,'tile','tensor_out_valid',"1'b1",
         'unowned_attention_suppresses_packet_and_terminal_valid','unowned')]
    rejected=[]
    for label,master,body,instance,pin,value,query,mode in controls:
        altered=replace_instance_pin(body,instance,pin,value.encode());changed=clone_environment(original,master,altered)
        checker=changed['routes'];owner=checker.walk(paths['owner']);ports=checker.ports(checker.contexts[owner][0])
        checker.offpath[owner]={bit for name,direction in ports.directions.items() if direction=='output' for bit in ports.net_bits(name)}
        bridge=WordBridge(checker.graph)
        def word(role,name,width,direction=None):return route_word(checker,bridge,paths[role],name,width,direction=direction)
        # One activated differing bit refutes the complete proved payload
        # equality. Avoid bit-blasting another 3072-bit equality just to find it.
        conditions=qualified['conditions']
        if mode=='data':
            actual,wanted=bridge.convert([checker.trace(checker.walk(paths['tile']),'tensor_out_data[0]'),
                                          checker.trace(owner,'out_data[0]')])
            active=[wanted];checked_bits=1
        elif mode=='unowned':
            actual=word('tile','tensor_out_valid',1,'input');wanted=z3.BoolVal(False);checked_bits=1
            active=[z3.Not(qualified['owned'])];conditions=qualified['head_conditions']
        else:
            specifications={'tag':('tile','tensor_out_tag','owner','out_tag',32),
                'count':('tile','tensor_out_count','owner','out_count',8),
                'valid':('tile','tensor_out_valid','owner','out_valid',1),
                'ready':('owner','out_ready','tile','tensor_out_ready',1),
                'error':('tile','tensor_done_error','owner','done_error',1)}
            actual_role,actual_name,wanted_role,wanted_name,checked_bits=specifications[mode]
            actual=word(actual_role,actual_name,checked_bits,'input')
            wanted=word(wanted_role,wanted_name,checked_bits,'output')
            active=[wanted==(1 if mode=='tag' else 96)] if mode in ('tag','count') else [wanted]
        try:bridge.check([actual],[wanted],label=query,conditions=[*conditions,*active])
        except AssertionError as error:
            require_counterexample(error,expected_query=query)
            rejected.append(dict(control=label,result='sat',query=query,activation=mode,instance=instance,pin=pin,
                checked_response_bits=checked_bits,altered_module_sha256=sha256(altered).hexdigest()))
            print('SHARED_RETURN_CORRUPTION_REJECTED',label,query,flush=True)
        else:raise AssertionError(('Shared response corruption accepted',label))
    assert len(rejected)==7
    return rejected


def verify(output):
    from hashlib import file_digest
    import json,time,resource
    from prove_tri_oracle_packaged_products import ROOT,memory_guard
    from prove_tri_oracle_head_score_frontend import revalidate_evidence
    from prove_tri_oracle_tile_command_routes import command_route_environment
    assert not Path('/.dockerenv').exists()
    assert output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);start=time.monotonic();evidence={}
    def pin(path,wanted=None):
        with path.open('rb') as stream:digest=file_digest(stream,'sha256').hexdigest()
        assert wanted is None or digest==wanted,('Changed shared return input',path)
        assert evidence.setdefault(str(path.relative_to(ROOT)),digest)==digest
        return path
    prior=json.loads(pin(ROOT/'records/tri_oracle_packaged_accepted_command.json').read_text())
    assert prior['state']=='mapped_accepted_tensor_command_transport_verified'
    for name,digest in prior['evidence_sha256'].items():pin(ROOT/name,digest)
    full_name,=[name for name in prior['evidence_sha256'] if name.endswith('/accepted_command_qualified.json')]
    for name,digest in json.loads((ROOT/full_name).read_text())['evidence_sha256'].items():pin(ROOT/name,digest)
    for path in (Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_shared_return_logic.py',
                 *(ROOT/'verilog'/name for name in ('tri_oracle_batched_frame393.sv','tri_oracle_batched_shared392.sv',
                    'tri_oracle_batched_nonlinear391.sv','tri_oracle_attention_tile_batch413.sv'))):pin(path)
    with command_route_environment(pin) as original:
        assert original['candidate_sha256']==prior['candidate_sha256']
        environment=shared_environment(original);epoch=prove_epoch(environment);returned=prove_return_routes(original)
        corruptions=epoch_corruption_controls(original)+return_corruption_controls(original,returned)
        routes=environment['routes'];wrapper=environment['wrapper']
        assert environment['absolute_arbiter']==prior['component']['absolute_contexts']['arbiter']
        for role in ('arbiter','wrapper','pipeline','layer','parent','tile','owner'):
            path=original['paths'][role];master=original['routes'].contexts[original['routes'].walk(path)][0]
            assert original['routes'].module(master).sha256==prior['component']['module_sha256'][role],('Changed return component',role)
        component=dict(absolute_arbiter=environment['absolute_arbiter'],absolute_wrapper=original['paths']['wrapper'],
            arbiter_module_sha256=routes.module(routes.contexts[''][0]).sha256,
            wrapper_module_sha256=routes.module(routes.contexts[wrapper][0]).sha256,
            common_reset_values=[r['reset_value'] for r in epoch['records']],ownership_state_triples=5,
            boundary_cuts=environment['boundary_cuts'],owner_response_boundary=returned['owner_response_boundary'],
            all_component_inputs_universally_quantified=True)
    revalidate_evidence(evidence,ROOT)
    report=dict(state='mapped_shared_ownership_and_response_transport_verified',candidate_sha256=prior['candidate_sha256'],
        component=component,ownership_queries=epoch['queries'],response_queries=returned['queries'],
        ownership_witnesses=epoch['witnesses'],response_state_witnesses=returned['witnesses'],
        ownership_event_witnesses=epoch['event_witnesses'],producer_acceptance_witness=returned['producer_acceptance_witness'],
        rejected_corruptions=corruptions,ownership_epoch_and_return_transport_verified=True,evidence_sha256=evidence,
        fault_control_cases=len(corruptions),distinct_mutated_bodies=len({c['altered_module_sha256'] for c in corruptions}),
        wall_seconds=time.monotonic()-start,peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        complete_response_safety_qualified=False,numerical_score_production_verified=False,eventual_completion_verified=False,
        full_head_prediction_verified=False,task_accuracy_verified=False,physical_timing_verified=False,
        complete_paper_architecture_verified=False,advance_to_clock_distribution_or_routing_allowed=False)
    with output.open('x') as f:f.write(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    import argparse,resource
    resource.setrlimit(resource.RLIMIT_AS,(3*2**30,3*2**30))
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    report=verify(parser.parse_args().output);print(report['state'],report['wall_seconds'],flush=True)
