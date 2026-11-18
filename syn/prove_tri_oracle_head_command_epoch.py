"""Track accepted head-command controller history in the exact mapped design.

The auxiliary history Boolean is a proof monitor, not a physical register.
Numerical score production, eventual progress and model accuracy are separate.
"""
if not __debug__:raise RuntimeError('Head command epoch verification requires assertions')
from pathlib import Path
import re,z3


def parent_tile_invariant(parent,tile):
    assert parent.size()==tile.size()==3,'Unexpected parent/tile state widths'
    return z3.Or(parent==3,z3.And(z3.Or(*(parent==code for code in (0,1,2,4,5))),tile==0))


def head_invariant(history,layer,parent,tile,owned,last):
    assert all(z3.is_bool(x) for x in (history,owned,last)) and layer.size()==4 and parent.size()==tile.size()==3
    return z3.Implies(history,z3.And(layer==5,parent==3,
        z3.Or(*(tile==code for code in (3,4,5,6))),owned,z3.Implies(tile==4,z3.Not(last))))


def next_history(old,accept,terminal):
    assert all(z3.is_bool(x) for x in (old,accept,terminal))
    return z3.If(accept,z3.BoolVal(True),z3.If(terminal,z3.BoolVal(False),old))


def epoch_environment(original,*,body_overrides=None):
    from prove_tri_oracle_command_admission import AdmissionRoutes
    from prove_tri_oracle_tile_score_packet import primary_tile_state
    from prove_tri_oracle_packaged_products import liberty_group
    source=original['routes'];absolute=original['paths']['pipeline'].rsplit('/',1)[0]
    assert all(path.startswith(absolute+'/') for path in original['paths'].values())
    paths={role:path[len(absolute)+1:] for role,path in original['paths'].items()}
    root=source.contexts[source.walk(absolute)][0];overrides=body_overrides or {};assert set(overrides)<=source.masters
    routes=AdmissionRoutes(lambda master:overrides[master] if master in overrides else source.body(master),
        source.masters,source.library,source.states,root,tile=paths['tile'],parent=paths['parent'],guard=source.guard)
    contexts={role:routes.walk(path) for role,path in paths.items()}
    kept={contexts[role] for role in ('pipeline','layer','parent','tile','frame','arbiter','wrapper')}
    cuts=[]
    for context in ('',*sorted(kept)):
        module=routes.module(routes.contexts[context][0])
        for instance,(master,_) in module.cells.items():
            if master not in routes.masters or not master.startswith('tri_oracle_'):continue
            child=routes.child(context,instance)
            if child in kept:continue
            ports=routes.ports(master)
            outputs={bit for name,direction in ports.directions.items() if direction=='output' for bit in ports.net_bits(name)}
            routes.offpath[child]=outputs;cuts.append(dict(context=child,master=master,output_bits=len(outputs)))
    selected=[(contexts[role],f'state_reg[{bit}]') for role,width in (('layer',4),('parent',3),('tile',3)) for bit in range(width)]
    selected.extend((contexts['tile'],f'{prefix}_reg[{bit}]') for prefix,width in (('token_index',4),('tensor_cfg_tokens',5)) for bit in range(width))
    selected.extend((contexts[role],instance) for role,instance in (
        ('pipeline','projection_busy_reg'),('arbiter','attention_owned_reg'),('wrapper','busy_reg'),('wrapper','paired_reg')))
    masters={routes.module(routes.contexts[context][0]).cells[instance][0] for context,instance in selected}
    tables=[]
    for sources in original['sources'].values():
        standard,=(p for p in sources if p.name.startswith('tcbn28'));text=standard.read_text();table={}
        for master in sorted(masters):
            match,=re.finditer(r'(?m)^cell\s*\('+re.escape(master)+r'\)\s*\{',text)
            table[master]=primary_tile_state(liberty_group(text,match.end()))
        tables.append(table)
    assert len(tables)==3 and tables[0]==tables[1]==tables[2],'Head epoch primary models differ across corners'
    assert len(selected)==23
    return dict(routes=routes,contexts=contexts,paths=paths,absolute_shared=absolute,primary=tables[0],boundary_cuts=cuts)


def physical_word(environment,bridge,role,prefix,width):
    from prove_tri_oracle_layer_row_epoch import physical_register
    routes=environment['routes'];context=environment['contexts'][role]
    module=routes.module(routes.contexts[context][0]);assert module.declared[prefix]==(width-1,0),'Head epoch word shape differs'
    records=[physical_register(routes,bridge,context,f'{prefix}_reg[{bit}]',environment['primary']) for bit in range(width)]
    assert [r['q'] for r in records]==[f'{prefix}[{bit}]' for bit in range(width)],'Head epoch physical word aliases differ'
    return dict(old=bridge.pack([r['old'] for r in records]),data=bridge.pack([r['data'] for r in records]),
        reset=z3.BitVecVal(sum(r['reset_value']<<bit for bit,r in enumerate(records)),width),records=records)


def current_register_word(routes,bridge,context,prefix,width):
    """Read actual primary Q outputs, including synthesis-renamed aliases."""
    module=routes.module(routes.contexts[context][0]);values=[]
    for bit in range(width):
        master,pins=module.cells[f'{prefix}_reg[{bit}]']
        assert routes.states.get(master)=={'ff':1} and routes.library[master,'Q']['function']=='IQ','Invalid current register primary Q'
        q,=module.expression(pins['Q']);values.append(routes.trace(context,q))
    return bridge.pack(bridge.convert(values))


def prove_epoch(environment,*,only_query=None,activation=()):
    from prove_tri_oracle_head_intensity import WordBridge
    from prove_tri_oracle_layer_row_epoch import physical_register
    from prove_tri_oracle_tile_command_routes import route_word
    from prove_tri_oracle_pipeline_layer_epoch import exclusion_invariant
    from prove_tri_oracle_shared_return import ownership_invariant
    from prove_tri_oracle_tile_geometry import geometry_check
    from prove_tri_oracle_accepted_command import accepted_witness
    routes=environment['routes'];contexts=environment['contexts'];bridge=WordBridge(routes.graph)
    fields={role:physical_word(environment,bridge,role,'state',width) for role,width in (('layer',4),('parent',3),('tile',3))}
    fields.update(token=physical_word(environment,bridge,'tile','token_index',4),
                  tokens=physical_word(environment,bridge,'tile','tensor_cfg_tokens',5))
    flags={name:physical_register(routes,bridge,contexts[role],instance,environment['primary']) for name,role,instance in (
        ('projection','pipeline','projection_busy_reg'),('owned','arbiter','attention_owned_reg'),
        ('busy','wrapper','busy_reg'),('paired','wrapper','paired_reg'))}
    assert [flags[name]['q'] for name in ('projection','owned','busy','paired')]==['tensor_cfg_activation_stride[11]','attention_owned','busy','paired']
    records=[r for field in fields.values() for r in field['records']]+list(flags.values());assert len(records)==23
    old={name:f['old'] for name,f in fields.items()}|{name:f['old'] for name,f in flags.items()}
    following={name:f['data'] for name,f in fields.items()}|{name:f['data'] for name,f in flags.items()}
    reset={name:f['reset'] for name,f in fields.items()}|{name:z3.BoolVal(bool(f['reset_value'])) for name,f in flags.items()}
    def word(role,name,width,direction=None):return route_word(routes,bridge,contexts[role],name,width,direction=direction)
    rst=bridge.boolean('top.rst_n')
    def prerequisites(values):
        return (parent_tile_invariant(values['parent'],values['tile']),
                exclusion_invariant(values['projection'],values['layer']),
                ownership_invariant(values['owned'],values['busy'],values['paired']))
    prior=prerequisites(old);next_prior=prerequisites(following)
    history=bridge.boolean('proof.head_owned_epoch')
    accept=z3.And(word('tile','tensor_cfg_valid',1,'output'),word('tile','tensor_cfg_ready',1,'input'))
    terminal=z3.And(word('arbiter','attention_done_valid',1,'output'),word('arbiter','attention_done_ready',1,'input'))
    history_next=next_history(history,accept,terminal)
    def last(values):return z3.ZeroExt(1,values['token'])+1==values['tokens']
    def invariant(h,values):return head_invariant(h,values['layer'],values['parent'],values['tile'],values['owned'],last(values))
    ghost=invariant(history,old)
    def check(actual,wanted,label,*,conditions=()):
        routes.guard();result=geometry_check(bridge,actual,wanted,label=label,conditions=conditions,
            only_query=only_query,activation=activation);routes.guard();return result
    check([r['clock'] for r in records],[bridge.boolean('top.clk')]*23,'all23_head_epoch_register_clocks')
    check([r['reset'] for r in records],[z3.Not(rst)]*23,'all23_head_epoch_register_reset_bindings')
    check([*prerequisites(reset),invariant(z3.BoolVal(False),reset)],[z3.BoolVal(True)]*4,'head_epoch_actual_reset_basis')
    for index,label in enumerate(('parent_tile_state_domain','projection_layer_exclusion','shared_receiver_ownership')):
        check([next_prior[index]],[z3.BoolVal(True)],label+'_actual_component_induction',conditions=[rst,prior[index]])
    check([word('parent','out_valid',1,'output')],[z3.BoolVal(False)],
          'parent_wait_never_reports_prediction_completion',conditions=[old['parent']==3])
    active=z3.Or(*(old['tile']==code for code in (3,4,5,6)))
    check([following['parent']==3,following['layer']==5],[z3.BoolVal(True)]*2,
          'active_tile_holds_parent_and_head_layer',conditions=[rst,old['parent']==3,old['layer']==5,active])
    check([old['layer']==5,z3.Not(old['projection']),old['parent']==3,old['tile']==2,
           following['layer']==5,following['parent']==3,following['tile']==3,following['owned'],
           following['busy'],z3.Not(following['paired'])],[z3.BoolVal(True)]*10,
          'actual_head_request_acceptance_enters_wait_packet',conditions=[rst,*prior,accept])
    tile_terminal=z3.And(word('tile','tensor_done_valid',1,'input'),word('tile','tensor_out_ready',1,'output'))
    check([terminal],[tile_terminal],'tracked_head_terminal_matches_real_tile_ready_alias',conditions=[rst,*prior,ghost,history])
    check([invariant(history_next,following)],[z3.BoolVal(True)],'head_command_history_actual_successor_induction',
          conditions=[rst,*prior,ghost])
    check([old['layer']==5,z3.Not(old['projection']),old['owned'],old['busy'],z3.Not(old['paired'])],
          [z3.BoolVal(True)]*5,'active_head_epoch_satisfies_prior_return_modes',conditions=[rst,*prior,ghost,history])
    assert only_query is None or len(bridge.checks)==1,'Targeted head epoch query absent'
    witnesses=[]
    if only_query is None:
        for event,conditions in (
            ('producer_acquisition',[rst,*prior,ghost,z3.Not(history),accept]),
            ('nonlast_emit_terminal_stall',[rst,*prior,ghost,history,old['tile']==4,
                word('arbiter','attention_done_valid',1,'output'),z3.Not(word('arbiter','attention_done_ready',1,'input'))]),
            ('last_wait_done',[rst,*prior,ghost,history,old['tile']==5,last(old),z3.Not(terminal)]),
            ('terminal_retirement',[rst,*prior,ghost,history,terminal])):
            witnesses.append(dict(event=event,result=accepted_witness(conditions),full_clock_history_reachability_verified=False))
    return dict(queries=bridge.checks,witnesses=witnesses,register_bits=23,proof_only_history_bits=1,
                records=records,old=old,following=following,bridge=bridge,history=history,accept=accept,terminal=terminal)


def rejection_controls(original):
    from hashlib import sha256
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_intensity import WordBridge,require_counterexample
    from prove_tri_oracle_tile_command_routes import route_word
    base=epoch_environment(original);routes=base['routes'];contexts=base['contexts'];rejected=[]
    def force_next(role,instance,value):
        module=routes.module(routes.contexts[contexts[role]][0]);raw=module.cells[instance][1]
        assert 'D' in raw
        return {'D':value}|({'E':"1'b1"} if 'E' in raw else {})|({'SE':"1'b0"} if 'SE' in raw else {})
    controls=[
        ('head_layer_premature_exit','layer',{'state_reg[0]':force_next('layer','state_reg[0]',"1'b0")},'layer'),
        ('predictor_parent_premature_exit','parent',{'state_reg[2]':force_next('parent','state_reg[2]',"1'b1")},'parent'),
        ('tile_premature_idle_or_prepare','tile',{'state_reg[1]':force_next('tile','state_reg[1]',"1'b0")},'tile'),
        ('last_score_emitted_before_terminal','tile',{'state_reg[0]':force_next('tile','state_reg[0]',"1'b0")},'last_emit'),
        ('terminal_valid_feedback_lost','parent',{'tile':{'tensor_done_valid':"1'b0"}},'terminal_alias'),
        ('projection_started_during_head_epoch','pipeline',{'projection_busy_reg':force_next('pipeline','projection_busy_reg',"1'b1")},'projection'),
        ('saved_token_count_clobbered_during_emit','tile',{'tensor_cfg_tokens_reg[0]':force_next('tile','tensor_cfg_tokens_reg[0]',"1'b0")},'count'),
        ('token_index_clobbered_during_emit','tile',{'token_index_reg[0]':force_next('tile','token_index_reg[0]',"1'b1")},'token'),
        ('tile_state_reset_disconnected','tile',{'state_reg[0]':{'CDN':"1'b1"}},'reset')]
    for label,role,edits,mode in controls:
        master=routes.contexts[contexts[role]][0];body=routes.body(master);altered=body
        for instance,pins in edits.items():
            for pin,value in pins.items():altered=replace_instance_pin(altered,instance,pin,value.encode())
        environment=epoch_environment(original,body_overrides={master:altered})
        changed=environment['routes'];bridge=WordBridge(changed.graph)
        def word(role,name,width,direction=None):
            return route_word(changed,bridge,environment['contexts'][role],name,width,direction=direction)
        rst=bridge.boolean('top.rst_n')
        if mode=='reset':active=[z3.Not(rst)];query='all23_head_epoch_register_reset_bindings'
        else:
            emit=mode in ('count','token');token=1 if mode=='count' else 0;tokens=3 if mode=='count' else 2 if mode=='token' else 1
            active=[rst,bridge.boolean('proof.head_owned_epoch'),word('layer','state',4)==5,
                word('parent','state',3)==3,word('tile','state',3)==(4 if emit else 3),
                word('tile','token_index',4)==token,word('tile','tensor_cfg_tokens',5)==tokens,
                word('arbiter','attention_owned',1),word('wrapper','busy',1),z3.Not(word('wrapper','paired',1)),
                z3.Not(word('pipeline','tensor_cfg_activation_stride',32,'output')&z3.BitVecVal(2048,32)!=0)]
            terminal=z3.And(word('arbiter','attention_done_valid',1,'output'),word('arbiter','attention_done_ready',1,'input'))
            active.append(terminal if mode=='terminal_alias' else z3.Not(terminal))
            if mode=='tile':active.extend([z3.Not(word('tile','tensor_out_valid',1,'input')),z3.Not(word('tile','tensor_done_valid',1,'input'))])
            if emit:active.append(z3.Not(word('tile','score_ready',1,'input')))
            if mode=='last_emit':
                saved_tag=current_register_word(changed,bridge,environment['contexts']['tile'],'tensor_cfg_tag',32)
                active.extend([word('tile','tensor_out_valid',1,'input'),z3.Not(word('tile','tensor_done_valid',1,'input')),
                    word('tile','tensor_out_tag',32,'input')==saved_tag,
                    word('tile','tensor_out_token',4,'input')==0,word('tile','tensor_out_last',1,'input'),
                    word('tile','tensor_out_count',8,'input')==96])
            query=('projection_layer_exclusion_actual_component_induction' if mode=='projection' else
                   'tracked_head_terminal_matches_real_tile_ready_alias' if mode=='terminal_alias' else
                   'head_command_history_actual_successor_induction')
        try:prove_epoch(environment,only_query=query,activation=active)
        except AssertionError as error:
            require_counterexample(error,expected_query=query)
            rejected.append(dict(control=label,result='sat',query=query,activation=mode,role=role,changed_instances=edits,
                                 altered_module_sha256=sha256(altered).hexdigest()))
            print('HEAD_COMMAND_EPOCH_CORRUPTION_REJECTED',label,query,flush=True)
        else:raise AssertionError(('Head command epoch corruption accepted',label))
    master=routes.contexts[contexts['parent']][0];body=routes.body(master)
    altered=replace_instance_pin(body,'state_reg[0]','CP',b"1'b0")
    try:prove_epoch(epoch_environment(original,body_overrides={master:altered}))
    except AssertionError as error:
        assert str(error)=='Epoch register clock differs',('Unrelated head epoch clock rejection',str(error))
        rejected.append(dict(control='predictor_state_wrong_clock',rejection=str(error),altered_module_sha256=sha256(altered).hexdigest()))
    else:raise AssertionError('Head epoch wrong clock accepted')
    assert len(rejected)==10 and len({x['altered_module_sha256'] for x in rejected})==10
    return rejected


def verify(output):
    from hashlib import file_digest
    import json,time,resource
    from prove_tri_oracle_packaged_products import ROOT,memory_guard
    from prove_tri_oracle_head_score_frontend import revalidate_evidence
    from prove_tri_oracle_tile_command_routes import command_route_environment
    from prove_tri_oracle_head_intensity import WordBridge
    from prove_tri_oracle_tile_command_routes import route_word
    from hashlib import sha256
    assert not Path('/.dockerenv').exists()
    assert output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);start=time.monotonic();evidence={}
    def pin(path,wanted=None):
        with path.open('rb') as f:digest=file_digest(f,'sha256').hexdigest()
        assert wanted is None or wanted==digest,('Changed head command epoch input',path)
        assert evidence.setdefault(str(path.relative_to(ROOT)),digest)==digest
        return path
    prior=json.loads(pin(ROOT/'records/tri_oracle_packaged_shared_return.json').read_text())
    assert prior['state']=='mapped_shared_ownership_and_response_transport_verified'
    for name,digest in prior['evidence_sha256'].items():pin(ROOT/name,digest)
    full_name,=[name for name in prior['evidence_sha256'] if name.endswith('/shared_return_qualified.json')]
    for name,digest in json.loads((ROOT/full_name).read_text())['evidence_sha256'].items():pin(ROOT/name,digest)
    for path in (Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_head_command_epoch_logic.py',
                 ROOT/'verilog/tri_oracle_attention_layer427.sv',ROOT/'verilog/tri_oracle_attention_head_predictor415.sv',
                 ROOT/'verilog/tri_oracle_attention_tile_batch413.sv'):pin(path)
    with command_route_environment(pin) as original:
        assert original['candidate_sha256']==prior['candidate_sha256']
        environment=epoch_environment(original);result=prove_epoch(environment)
        corruptions=rejection_controls(original)
        routes=environment['routes'];contexts=environment['contexts']
        anchors=WordBridge(original['routes'].graph)
        anchors.check([route_word(original['routes'],anchors,environment['absolute_shared'],name,1,direction='input')
                       for name in ('clk','rst_n')],[anchors.boolean('top.'+name) for name in ('clk','rst_n')],
                       label='actual_shared_component_clock_reset_anchors')
        accepted=json.loads((ROOT/'records/tri_oracle_packaged_accepted_command.json').read_text())
        for role,digest in accepted['component']['module_sha256'].items():
            master=routes.contexts[contexts[role]][0]
            assert sha256(routes.body(master)).hexdigest()==digest,('Head epoch prior module differs',role)
        assert {role:environment['absolute_shared']+'/'+path for role,path in environment['paths'].items()}==accepted['component']['absolute_contexts']
        component=dict(absolute_shared=environment['absolute_shared'],boundary_cuts=environment['boundary_cuts'],
            shared_module_sha256=routes.module(routes.contexts[''][0]).sha256,
            absolute_contexts={role:environment['absolute_shared']+'/'+path for role,path in environment['paths'].items()},
            module_sha256={role:routes.module(routes.contexts[context][0]).sha256 for role,context in contexts.items()},
            physical_register_bits=23,physical_register_reset_values=[r['reset_value'] for r in result['records']],
            proof_only_auxiliary_history_bits=1,all_component_inputs_universally_quantified=True)
    revalidate_evidence(evidence,ROOT)
    report=dict(state='mapped_accepted_head_command_epoch_induction_verified',candidate_sha256=prior['candidate_sha256'],
        component=component,queries=[*result['queries'],*anchors.checks],event_witnesses=result['witnesses'],
        rejected_corruptions=corruptions,evidence_sha256=evidence,
        wall_seconds=time.monotonic()-start,peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        head_command_epoch_qualified=True,prior_head_return_mode_conditions_discharged_during_tracked_epoch=True,
        numerical_score_production_verified=False,eventual_completion_verified=False,
        full_head_prediction_verified=False,task_accuracy_verified=False,physical_timing_verified=False,
        complete_paper_architecture_verified=False,advance_to_clock_distribution_or_routing_allowed=False)
    with output.open('x') as f:f.write(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    import argparse,resource
    resource.setrlimit(resource.RLIMIT_AS,(3*2**30,3*2**30))
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    report=verify(parser.parse_args().output);print(report['state'],report['wall_seconds'],flush=True)
