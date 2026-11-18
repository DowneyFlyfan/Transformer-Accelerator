"""Compose mapped producer acceptance with qualified tensor-command transport.

Accepted-command safety does not establish eventual acceptance, full prediction,
task accuracy, physical timing, or the paper's undisclosed numerical settings.
"""
if not __debug__:raise RuntimeError('Accepted command verification requires assertions')
from pathlib import Path
import z3


def accepted_witness(conditions):
    solver=z3.SolverFor('QF_BV');solver.set(timeout=120000,max_memory=1024)
    solver.add(*conditions);result=solver.check()
    assert result==z3.sat,('Accepted command witness absent',str(result))
    return 'sat'


def acceptance_queries(bridge,terms,*,only_query=None,activation=()):
    """Derive modes from acceptance; none of the desired modes is assumed."""
    from prove_tri_oracle_tile_geometry import geometry_check
    t=terms
    assert (t['producer_state'].size(),t['layer'].size(),t['arbiter'].size(),t['owner_state'].size())==(3,4,4,5)
    accepted=z3.And(t['reset'],t['producer_valid'],t['producer_ready'])
    conditions=[t['reset'],accepted]
    def check(actual,wanted,label,*,when=()):
        return geometry_check(bridge,actual,wanted,label=label,conditions=when,
                              only_query=only_query,activation=activation)
    check([t['producer_valid']],[t['producer_state']==2],'actual_producer_valid_is_submit')
    check([t['layer']==5,z3.Not(t['projection']),t['arbiter']==0,z3.Not(t['owned']),t['enabled']],
          [z3.BoolVal(True)]*5,'accepted_producer_implies_actual_attention_mode',when=conditions)
    check([t['selected'],z3.Not(t['paired']),z3.Not(t['wrapper_busy']),t['owner_state']==0],
          [z3.BoolVal(True)]*4,'accepted_producer_selects_unpaired_idle_receiver',when=conditions)
    check([t['owner_valid'],t['owner_ready']],[z3.BoolVal(True)]*2,
          'accepted_producer_implies_actual_receiver_handshake',when=conditions)
    return dict(accepted=accepted,conditions=conditions)


def prove_acceptance(environment,*,only_query=None,activation=()):
    from prove_tri_oracle_tile_command_routes import route_word
    from prove_tri_oracle_head_intensity import WordBridge
    from prove_tri_oracle_tile_geometry import geometry_check
    routes=environment['routes'];paths=environment['paths'];bridge=WordBridge(routes.graph)
    def word(role,name,width,direction=None):
        return route_word(routes,bridge,paths[role],name,width,direction=direction)
    context=routes.walk(paths['pipeline']);root=routes.trace(context,'tensor_cfg_activation_stride[11]')
    node=routes.graph.nodes[root]
    assert node[0]=='v' and routes.sequential_cuts[node[1]]['instance']=='projection_busy_reg','Projection selector is not actual state'
    projection,=bridge.convert([root])
    terms=dict(reset=bridge.boolean('top.rst_n'),producer_state=word('tile','state',3),
        producer_valid=word('tile','tensor_cfg_valid',1,'output'),producer_ready=word('tile','tensor_cfg_ready',1,'input'),
        layer=word('layer','state',4),projection=projection,arbiter=word('arbiter','state',4),
        owned=word('arbiter','attention_owned',1),enabled=word('arbiter','attention_enable',1,'input'),
        selected=word('arbiter','attention_selected',1),wrapper_busy=word('wrapper','busy',1),
        owner_state=word('owner','state',5),paired=word('owner','cfg_paired',1,'input'),
        owner_valid=word('owner','cfg_valid',1,'input'),owner_ready=word('owner','cfg_ready',1,'output'))
    result=acceptance_queries(bridge,terms,only_query=only_query,activation=activation)
    clocks=[word(role,name,1,'input') for role in ('parent','tile','owner') for name in ('clk','rst_n')]
    geometry_check(bridge,clocks,[bridge.boolean('top.'+name) for _ in range(3) for name in ('clk','rst_n')],
        label='actual_accepted_producer_receiver_common_clock_reset',only_query=only_query,activation=activation)
    assert only_query is None or len(bridge.checks)==1,'Targeted accepted-command query absent'
    routes.guard()
    return dict(**result,bridge=bridge,terms=terms,queries=bridge.checks)


def clone_environment(environment,master,body):
    """Mutate only one in-memory body, retaining exact hierarchy and output cuts."""
    from prove_tri_oracle_command_admission import AdmissionRoutes
    original=environment['routes'];paths=environment['paths']
    assert master in original.masters
    routes=AdmissionRoutes(lambda name:body if name==master else original.body(name),
        original.masters,original.library,original.states,original.contexts[''][0],
        tile=paths['tile'],parent=paths['parent'],guard=original.guard)
    for path,bits in original.offpath.items():
        context=routes.walk(path);ports=routes.ports(routes.contexts[context][0])
        outputs={bit for name,direction in ports.directions.items() if direction=='output' for bit in ports.net_bits(name)}
        assert bits<=outputs,'Altered acceptance cut is not a declared output'
        routes.offpath[context]=set(bits)
    return dict(environment,routes=routes)


def prove_accepted_payload(environment,routed,contract,command,*,only_query=None,activation=()):
    from prove_tri_oracle_tile_command_routes import route_word
    from prove_tri_oracle_tile_command import reference_channel,reference_keep
    from prove_tri_oracle_tile_geometry import geometry_check
    routes=environment['routes'];bridge=contract['bridge'];geometry=command['old_scalar']
    conditions=[*contract['conditions'],command['scalar_invariant'],command['invariant']]
    def check(actual,wanted,label):
        routes.guard()
        result=geometry_check(bridge,actual,wanted,label=label,conditions=conditions,
                              only_query=only_query,activation=activation)
        routes.guard();return result
    check(routed['conditions'],[z3.BoolVal(True)]*len(routed['conditions']),
          'actual_acceptance_discharges_prior_route_mode_conditions')
    owner=environment['paths']['owner']
    channels=route_word(routes,bridge,owner,'cfg_channels',2560,direction='input')
    keep=route_word(routes,bridge,owner,'cfg_keep',2560,direction='input')
    check([channels],[z3.Concat(*reversed([reference_channel(geometry['query'],geometry['tokens'],column)
                                         for column in range(160)]))],'all2560_accepted_owner_channel_bits')
    check([keep],[bridge.pack([reference_keep(geometry['query'],geometry['tokens'],row,column)
                              for row in range(16) for column in range(160)])],'all2560_accepted_owner_keep_bits')
    headers=[('cfg_tokens',5,geometry['tokens']),('cfg_tag',32,geometry['tag']),
        ('cfg_count',8,z3.BitVecVal(96,8)),('cfg_dense_rows',17,z3.ZeroExt(6,geometry['rows'])),
        ('cfg_feature_words',10,z3.BitVecVal(8,10)),('cfg_activation_stride',32,z3.BitVecVal(64,32)),
        ('cfg_activation_base',64,geometry['query_addr']),('cfg_weight_base',64,geometry['key_base'])]
    check([route_word(routes,bridge,owner,name,width,direction='input') for name,width,_ in headers],
          [wanted for _,_,wanted in headers],'all8_accepted_owner_command_headers')
    if only_query is not None:
        assert len(bridge.checks)==1,'Targeted accepted-payload query absent'
    return dict(routed,bridge=bridge,conditions=conditions,accepted=contract['accepted'],channels=channels,keep=keep,
                cfg_valid=contract['terms']['owner_valid'],cfg_ready=contract['terms']['owner_ready'])


def rejection_controls(environment,routed,command):
    from hashlib import sha256
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_intensity import require_counterexample
    from prove_tri_oracle_tile_command_controls import replace_bus_bit,selector_inverter_pin
    routes=environment['routes'];paths=environment['paths'];rejected=[]
    def body_at(role):
        context=routes.walk(paths[role]);master=routes.contexts[context][0]
        return master,routes.body(master)
    parent_master,parent_body=body_at('parent');wrapper_master,wrapper_body=body_at('wrapper')
    controls=[
        ('producer_ready_bypasses_all_admission',parent_master,parent_body,'tile','tensor_cfg_ready',"1'b1",
         'accepted_producer_implies_actual_attention_mode','mode'),
        ('accepted_receiver_valid_dropped',wrapper_master,wrapper_body,'tensor','cfg_valid',"1'b0",
         'accepted_producer_implies_actual_receiver_handshake','handshake'),
        ('accepted_receiver_wrong_paired_mode',wrapper_master,wrapper_body,'tensor','cfg_paired',"1'b1",
         'accepted_producer_selects_unpaired_idle_receiver','paired'),
        ('accepted_count_wrong',wrapper_master,wrapper_body,'tensor','cfg_count',"8'd95",
         'all8_accepted_owner_command_headers','payload'),
        ('accepted_cross_token_keep_stride',wrapper_master,wrapper_body,'tensor','cfg_keep',
         replace_bus_bit('cfg_keep',2560,225,'cfg_keep[65]'),'all2560_accepted_owner_keep_bits','keep'),
        ('accepted_owner_reset_disconnected',wrapper_master,wrapper_body,'tensor','rst_n',"1'b1",
         'actual_accepted_producer_receiver_common_clock_reset','reset')]
    arbiter_master,arbiter_body=body_at('arbiter');context=routes.walk(paths['arbiter'])
    driver,=routes.drivers(context,'attention_selected');_,instance,master,pin,offset,width,_=driver
    assert offset==0 and width==1
    input_pin=selector_inverter_pin(routes.library[master,pin]['function'])
    controls.append(('accepted_selector_forced_inactive',arbiter_master,arbiter_body,instance,input_pin,"1'b1",
                     'accepted_producer_selects_unpaired_idle_receiver','selector'))
    for label,master,body,instance,pin,value,query,mode in controls:
        altered=replace_instance_pin(body,instance,pin,value.encode())
        changed=clone_environment(environment,master,altered)
        # Build only the actual cones; targeted checking excludes unrelated queries.
        if mode in ('payload','keep'):
            contract=prove_acceptance(changed);contract['bridge'].checks.clear()
            active=list(contract['conditions'])
            if mode=='keep':active.extend([command['old_scalar']['query']==96,command['old_scalar']['tokens']==2])
            operation=lambda:prove_accepted_payload(changed,routed,contract,command,only_query=query,activation=active)
        else:
            from prove_tri_oracle_head_intensity import WordBridge
            from prove_tri_oracle_tile_command_routes import route_word
            bridge=WordBridge(changed['routes'].graph)
            if mode=='reset':active=[z3.Not(bridge.boolean('top.rst_n'))]
            else:
                active=[bridge.boolean('top.rst_n'),
                    route_word(changed['routes'],bridge,paths['tile'],'tensor_cfg_valid',1,direction='output'),
                    route_word(changed['routes'],bridge,paths['tile'],'tensor_cfg_ready',1,direction='input')]
                if mode=='mode':active.append(route_word(changed['routes'],bridge,paths['layer'],'state',4)==0)
            operation=lambda:prove_acceptance(changed,only_query=query,activation=active)
        try:operation()
        except AssertionError as error:
            require_counterexample(error,expected_query=query)
            rejected.append(dict(control=label,result='sat',query=query,activation=mode,instance=instance,pin=pin,
                                 altered_module_sha256=sha256(altered).hexdigest()))
            print('ACCEPTED_COMMAND_CORRUPTION_REJECTED',label,query,flush=True)
        else:raise AssertionError(('Accepted command corruption accepted',label))
    assert len(rejected)==7
    return rejected


def verify(output):
    from hashlib import file_digest
    import json,time,resource
    from prove_tri_oracle_packaged_products import ROOT,memory_guard
    from prove_tri_oracle_head_score_frontend import revalidate_evidence
    from prove_tri_oracle_tile_geometry import load_models,geometry_models,prove_parent_geometry,prove_tile_geometry,prove_coupled_epoch
    from prove_tri_oracle_tile_command import prove_command_storage
    from prove_tri_oracle_tile_command_routes import command_route_environment,prove_command_routes
    from prove_tri_oracle_tile_command_capture import prove_owner_captures
    assert not Path('/.dockerenv').exists()
    assert output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);start=time.monotonic();evidence={}
    def pin(path,wanted=None):
        with path.open('rb') as stream:digest=file_digest(stream,'sha256').hexdigest()
        assert wanted is None or wanted==digest,('Changed accepted-command input',path)
        name=str(path.relative_to(ROOT));assert evidence.setdefault(name,digest)==digest
        return path
    priors={}
    for name,state in [('tile_command','mapped_command_storage_conditional_routes_and_receiver_capture_verified'),
                       ('pipeline_layer_epoch','mapped_projection_layer_exclusion_induction_verified')]:
        prior=json.loads(pin(ROOT/f'records/tri_oracle_packaged_{name}.json').read_text())
        assert prior['state']==state;priors[name]=prior
        for path,digest in prior['evidence_sha256'].items():pin(ROOT/path,digest)
    pipeline=priors['pipeline_layer_epoch']
    full_name,=[name for name in pipeline['evidence_sha256'] if name.endswith('/pipeline_layer_epoch_controls.json')]
    for name,digest in json.loads((ROOT/full_name).read_text())['evidence_sha256'].items():pin(ROOT/name,digest)
    for path in (Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_accepted_command_logic.py',
                 ROOT/'verilog/tri_oracle_batched_frame393.sv'):pin(path)
    data=load_models(pin);assert data['candidate_sha256']==pipeline['candidate_sha256']==priors['tile_command']['candidate_sha256']
    p,t,raw=geometry_models(data);parent=prove_parent_geometry(p,raw);tile=prove_tile_geometry(t,p,raw,parent)
    prove_coupled_epoch(p,t,raw,parent,tile);command=prove_command_storage(p,t,raw,parent,tile)
    with command_route_environment(pin) as environment:
        assert environment['candidate_sha256']==data['candidate_sha256']
        routed=prove_command_routes(environment,p,t,parent,tile,command)
        contract=prove_acceptance(environment)
        accepted=prove_accepted_payload(environment,routed,contract,command)
        witnesses=[];geometry=command['old_scalar']
        for query,count,total in ((96,1,97),(96,16,112),(2032,15,2047)):
            result=accepted_witness([*accepted['conditions'],geometry['query']==query,geometry['tokens']==count,
                                     parent['tokens']['old']==total])
            witnesses.append(dict(query=query,queries=count,total=total,result=result,full_clock_history_reachability_verified=False))
        receiver=prove_owner_captures(environment,accepted)
        corruptions=rejection_controls(environment,routed,command)
        routes=environment['routes'];paths=environment['paths']
        for role in ('pipeline','layer'):
            assert routes.module(routes.contexts[routes.walk(paths[role])][0]).sha256==pipeline['component'][role+'_module_sha256']
            assert paths[role]==pipeline['component']['absolute_'+role+'_context']
        assert receiver['owner_module_sha256']==priors['tile_command']['receiver']['owner_module_sha256']
        assert paths['owner']==priors['tile_command']['conditional_routes']['owner']
        details=dict(absolute_contexts=paths,module_sha256={role:routes.module(routes.contexts[routes.walk(path)][0]).sha256
            for role,path in paths.items()},boundary_cuts={path:len(bits) for path,bits in routes.offpath.items()},
            graph_nodes=len(routes.graph.nodes),sequential_cut_bits=len(routes.sequential_cuts))
    revalidate_evidence(evidence,ROOT)
    report=dict(state='mapped_accepted_tensor_command_transport_verified',candidate_sha256=data['candidate_sha256'],
        component=details,acceptance_and_payload_queries=contract['bridge'].checks,receiver_capture=receiver,
        accepted_state_witnesses=witnesses,rejected_corruptions=corruptions,evidence_sha256=evidence,
        accepted_event='rst_n && producer_valid && producer_ready',
        prior_operational_modes_discharged_for_actual_accepted_commands=True,
        qualified_scalar_and_initialized_producer_invariants_required=True,
        full_clock_history_reachability_verified=False,eventual_command_acceptance_verified=False,
        returned_score_and_tag_correctness_verified=False,full_head_prediction_verified=False,task_accuracy_verified=False,
        physical_timing_verified=False,complete_paper_architecture_verified=False,
        advance_to_clock_distribution_or_routing_allowed=False,wall_seconds=time.monotonic()-start,
        peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    with output.open('x') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    import argparse,resource
    resource.setrlimit(resource.RLIMIT_AS,(3*2**30,3*2**30))
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    report=verify(parser.parse_args().output)
    print(report['state'],report['wall_seconds'],flush=True)
