"""Prove actual layer/row ownership from common reset and mapped state updates."""
if not __debug__:raise RuntimeError('Layer/row ownership verification requires assertions')
from pathlib import Path
import re,z3


def ownership_invariant(layer,row):
    assert layer.size()==4 and row.size()==5,'Unexpected ownership state widths'
    return z3.Or(z3.And(z3.Or(*(layer==code for code in (0,4,5,6,8,11))),row==0),
        z3.And(z3.Or(*(layer==code for code in (1,2,3,9,10))),z3.ULE(row,2)),
        z3.And(layer==7,z3.Or(row==0,z3.UGE(row,3))))


def physical_register(routes,bridge,context,instance,primary):
    """Evaluate one actual FF model without losing hierarchical Q/QN identity."""
    from prove_tri_oracle_packaged_products import parse_function
    module=routes.module(routes.contexts[context][0]);master,raw=module.cells[instance]
    assert routes.states.get(master)=={'ff':1},'Unsupported epoch register kind'
    pins={name:module.expression(value) for name,value in raw.items()}
    description=primary[master]
    assert parse_function(description['clocked_on'])=='CP' and pins['CP']==('clk',),'Epoch register clock differs'
    q,=pins['Q'];assert routes.library[master,'Q']['function']=='IQ','Epoch register Q polarity differs'
    old=routes.trace(context,q)
    def function(expression):
        values={'IQ':old,'IQN':routes.graph.operation('!',old)}
        for name in set(re.findall(r'[A-Za-z_]\w*',expression))-values.keys():
            assert routes.library[master,name]['direction']=='input' and len(pins[name])==1,'Invalid epoch register input'
            values[name]=routes.trace(context,pins[name][0])
        return routes.graph.function(expression,values)
    reset='clear' if 'clear' in description else 'preset' if 'preset' in description else None
    assert reset is not None,'Epoch register lacks asynchronous reset'
    values=bridge.convert([old,function(description['next_state']),function(description[reset]),routes.trace(context,'clk')])
    return dict(old=values[0],data=values[1],reset=values[2],clock=values[3],reset_value=int(reset=='preset'),
                instance=instance,master=master,q=q)


def state_word(routes,bridge,context,width,primary):
    module=routes.module(routes.contexts[context][0]);assert module.declared['state']==(width-1,0),'Epoch state shape differs'
    records=[]
    for bit in range(width):
        record=physical_register(routes,bridge,context,f'state_reg[{bit}]',primary)
        assert record['q']==f'state[{bit}]','Epoch state is not its actual primary Q output'
        records.append(record)
    return dict(old=bridge.pack([record['old'] for record in records]),
        data=bridge.pack([record['data'] for record in records]),
        reset_value=sum(record['reset_value']<<bit for bit,record in enumerate(records)),
        records=records,bits=width)


def epoch_environment(original,*,body_overrides=None):
    """Universally quantify layer inputs, preserving all layer/row connections."""
    from prove_tri_oracle_command_admission import AdmissionRoutes
    from prove_tri_oracle_tile_score_packet import primary_tile_state
    from prove_tri_oracle_packaged_products import liberty_group
    source=original['routes'];absolute=original['paths']['layer']
    context=source.walk(absolute);layer_master=source.contexts[context][0]
    overrides=body_overrides or {}
    assert set(overrides)<=source.masters,'Unknown epoch body override'
    body=lambda master:overrides[master] if master in overrides else source.body(master)
    routes=AdmissionRoutes(body,source.masters,source.library,source.states,layer_master,guard=source.guard)
    row=routes.child('','attention');roots=('',row);cuts=[]
    for context in roots:
        module=routes.module(routes.contexts[context][0])
        for instance,(master,pins) in module.cells.items():
            if master not in routes.masters or not master.startswith('tri_oracle_'):continue
            if context=='' and instance=='attention':continue
            child=routes.child(context,instance);ports=routes.ports(master)
            outputs={bit for name,direction in ports.directions.items() if direction=='output' for bit in ports.net_bits(name)}
            routes.offpath[child]=outputs
            cuts.append(dict(context=child,master=master,output_bits=len(outputs)))
    masters={routes.module(routes.contexts[context][0]).cells[f'state_reg[{bit}]'][0]
             for context,width in (('',4),(row,5)) for bit in range(width)}
    tables=[]
    for paths in original['sources'].values():
        standard,=(path for path in paths if path.name.startswith('tcbn28'))
        text=standard.read_text();table={}
        for master in sorted(masters):
            match,=re.finditer(r'(?m)^cell\s*\('+re.escape(master)+r'\)\s*\{',text)
            table[master]=primary_tile_state(liberty_group(text,match.end()))
        tables.append(table)
    assert len(tables)==3 and tables[0]==tables[1]==tables[2],'Epoch primary state functions differ across corners'
    return dict(routes=routes,row=row,primary=tables[0],boundary_cuts=cuts,absolute_layer=absolute)


def prove_epoch(environment,*,only_query=None,activation=()):
    from prove_tri_oracle_head_intensity import WordBridge
    from prove_tri_oracle_tile_command_routes import route_word
    from prove_tri_oracle_tile_geometry import geometry_check
    routes=environment['routes'];bridge=WordBridge(routes.graph);row_context=environment['row']
    layer=state_word(routes,bridge,'',4,environment['primary'])
    row=state_word(routes,bridge,row_context,5,environment['primary'])
    records=layer['records']+row['records'];rst=bridge.boolean('top.rst_n')
    def check(actual,wanted,*,label,conditions=()):
        routes.guard()
        result=geometry_check(bridge,actual,wanted,label=label,conditions=conditions,only_query=only_query,activation=activation)
        routes.guard();return result
    check([record['clock'] for record in records],[bridge.boolean('top.clk')]*9,
                 label='all9_layer_row_state_register_clocks')
    check([record['reset'] for record in records],[z3.Not(rst)]*9,
                 label='all9_layer_row_state_register_reset_bindings')
    reset_layer=z3.BitVecVal(layer['reset_value'],4);reset_row=z3.BitVecVal(row['reset_value'],5)
    check([ownership_invariant(reset_layer,reset_row)],[z3.BoolVal(True)],label='layer_row_epoch_actual_reset_basis')
    invariant=ownership_invariant(layer['old'],row['old'])
    check([ownership_invariant(layer['data'],row['data'])],[z3.BoolVal(True)],
                 label='layer_row_epoch_actual_state_induction',conditions=[rst,invariant])
    check([row['old']==0],[z3.BoolVal(True)],label='layer_runhead_implies_row_idle',conditions=[invariant,layer['old']==5])
    flags=[route_word(routes,bridge,row_context,name,1,direction='output') for name in (
        'softmax_request[score_core]','softmax_request[score_tile]')]
    check(flags,[z3.BoolVal(False)]*2,label='layer_runhead_has_no_row_score_modes',conditions=[invariant,layer['old']==5])
    assert only_query is None or len(bridge.checks)==1,'Targeted epoch query absent'
    witnesses=[]
    if only_query is None:
        for layer_code,row_code in ((5,0),(7,8)):
            solver=z3.SolverFor('QF_BV');solver.set(timeout=120000,max_memory=1024)
            solver.add(rst,invariant,layer['old']==layer_code,row['old']==row_code)
            result=solver.check();assert result==z3.sat,('Ownership state domain witness absent',layer_code,row_code,str(result))
            witnesses.append(dict(layer_state=layer_code,row_state=row_code,result='sat',
                                  full_clock_history_reachability_verified=False))
    return dict(bridge=bridge,layer=layer,row=row,invariant=invariant,queries=bridge.checks,witnesses=witnesses)


def rejection_controls(original):
    from hashlib import sha256
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_intensity import require_counterexample,WordBridge
    from prove_tri_oracle_tile_command_routes import route_word
    base=epoch_environment(original);routes=base['routes'];row=base['row']
    layer_master=routes.contexts[''][0];row_master=routes.contexts[row][0]
    sources={name:routes.body(name) for name in (layer_master,row_master)}
    original_hash={name:sha256(body).hexdigest() for name,body in sources.items()};rejected=[]
    controls=[
        ('frame_start_layer_gating_bypassed',layer_master,'attention','frame_valid','frame_valid','induction','head_frame'),
        ('row_start_layer_gating_bypassed',layer_master,'attention','row_valid','row_valid','induction','head_row'),
        ('result_ready_feedback_frozen',layer_master,'attention','result_ready',"1'b0",'induction','row_result'),
        ('layer_leaves_while_row_active',layer_master,'state_reg[0]','D',"1'b0",'induction','row_active'),
        ('row_spurious_result_during_head',row_master,'state_reg[4]','D',"1'b1",'induction','head_idle'),
        ('row_state_reset_disconnected',row_master,'state_reg[0]','CDN',"1'b1",'reset','reset')]
    for label,master,instance,pin,value,target,mode in controls:
        altered=replace_instance_pin(sources[master],instance,pin,value.encode())
        environment=epoch_environment(original,body_overrides={master:altered})
        changed=environment['routes'];bridge=WordBridge(changed.graph)
        layer_old=route_word(changed,bridge,'','state',4)
        row_old=route_word(changed,bridge,environment['row'],'state',5)
        query='all9_layer_row_state_register_reset_bindings' if target=='reset' else 'layer_row_epoch_actual_state_induction'
        if mode=='reset':active=[z3.Not(bridge.boolean('top.rst_n'))]
        else:
            active=[bridge.boolean('top.rst_n')]
            if mode in ('head_frame','head_row','head_idle'):
                active.extend([layer_old==5,row_old==0])
                if mode=='head_frame':active.append(bridge.boolean('top.frame_valid'))
                else:active.append(z3.Not(bridge.boolean('top.frame_valid')))
                if mode=='head_row':active.append(bridge.boolean('top.row_valid'))
            elif mode=='row_result':active.extend([layer_old==7,row_old==16,bridge.boolean('top.result_ready')])
            else:active.extend([layer_old==7,row_old==8,z3.Not(bridge.boolean('top.result_ready'))])
        try:prove_epoch(environment,only_query=query,activation=active)
        except AssertionError as error:
            require_counterexample(error,expected_query=query)
            rejected.append(dict(control=label,result='sat',query=query,activation=mode,instance=instance,pin=pin,
                                 altered_module_sha256=sha256(altered).hexdigest()))
            print('EPOCH_CORRUPTION_REJECTED',label,query,flush=True)
        else:raise AssertionError(('Layer/row corruption accepted',label))
    altered=replace_instance_pin(sources[row_master],'state_reg[0]','CP',b"1'b0")
    environment=epoch_environment(original,body_overrides={row_master:altered})
    try:prove_epoch(environment)
    except AssertionError as error:
        assert str(error)=='Epoch register clock differs',('Unrelated epoch clock failure',str(error))
        rejected.append(dict(control='row_state_wrong_clock',rejection=str(error)))
    else:raise AssertionError('Wrong epoch clock accepted')
    assert len(rejected)==7 and all(sha256(body).hexdigest()==original_hash[name] for name,body in sources.items())
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
        assert wanted is None or wanted==digest,('Changed layer/row proof input',path)
        name=str(path.relative_to(ROOT));assert evidence.setdefault(name,digest)==digest
        return path
    prior=json.loads(pin(ROOT/'records/tri_oracle_packaged_command_admission.json').read_text())
    assert prior['state']=='mapped_header_capture_and_conditional_address_admission_components_verified'
    for name,digest in prior['evidence_sha256'].items():pin(ROOT/name,digest)
    full_name,=[name for name in prior['evidence_sha256'] if name.endswith('/admission_review_fixed.json')]
    full=json.loads((ROOT/full_name).read_text())
    for name,digest in full['evidence_sha256'].items():pin(ROOT/name,digest)
    for path in (Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_layer_row_epoch_logic.py'):pin(path)
    with command_route_environment(pin) as original:
        assert original['candidate_sha256']==prior['candidate_sha256']
        environment=epoch_environment(original);result=prove_epoch(environment)
        corruptions=rejection_controls(original)
        routes=environment['routes']
        row=routes.module(routes.contexts[environment['row']][0]);layer=routes.module(routes.contexts[''][0])
        assert row.sha256==prior['operational_modes']['row_module_sha256'],'Row ownership instance body differs'
        expected_row=full['operational_modes']['row_context']
        assert environment['absolute_layer']+'/'+environment['row']==expected_row,'Admission row instance binding differs'
        assert prior['operational_modes']['required_actual_row_state']==0,'Admission row state requirement differs'
        details=dict(layer_module_sha256=layer.sha256,row_module_sha256=row.sha256,
            absolute_layer_context=environment['absolute_layer'],absolute_row_context=environment['absolute_layer']+'/'+environment['row'],
            layer_physical_state_bits=4,row_physical_state_bits=5,
            boundary_cuts=environment['boundary_cuts'],all_component_inputs_universally_quantified=True,
            common_reset_state=[result['layer']['reset_value'],result['row']['reset_value']],
            ownership_state_pairs=51,state_satisfiability_witnesses=result['witnesses'],
            graph_nodes=len(routes.graph.nodes),sequential_cut_bits=len(routes.sequential_cuts))
    revalidate_evidence(evidence,ROOT)
    report=dict(state='mapped_layer_row_ownership_induction_verified',
        candidate_sha256=prior['candidate_sha256'],queries=result['queries'],component=details,rejected_corruptions=corruptions,
        evidence_sha256=evidence,wall_seconds=time.monotonic()-start,
        peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        prior_admission_row_idle_condition_discharged_after_common_reset=True,
        eventual_head_or_row_completion_verified=False,upstream_mode_reachability_verified=False,
        tensor_command_generation_verified=False,full_head_prediction_verified=False,task_accuracy_verified=False,
        physical_timing_verified=False,complete_paper_architecture_verified=False,
        advance_to_clock_distribution_or_routing_allowed=False)
    with output.open('x') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    import argparse,resource
    resource.setrlimit(resource.RLIMIT_AS,(3*2**30,3*2**30))
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    report=verify(parser.parse_args().output)
    print(report['state'],report['wall_seconds'],flush=True)
