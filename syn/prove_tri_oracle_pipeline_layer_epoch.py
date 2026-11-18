"""Prove mapped projection ownership excludes active attention-layer states."""
if not __debug__:raise RuntimeError('Pipeline ownership verification requires assertions')
from pathlib import Path
import re,z3


def exclusion_invariant(busy,layer):
    assert z3.is_bool(busy) and layer.size()==4,'Unexpected projection ownership width'
    return z3.Implies(busy,layer==0)


def pipeline_environment(original,*,body_overrides=None):
    from prove_tri_oracle_command_admission import AdmissionRoutes
    from prove_tri_oracle_tile_score_packet import primary_tile_state
    from prove_tri_oracle_packaged_products import liberty_group
    source=original['routes'];absolute=original['paths']['pipeline']
    top=source.contexts[source.walk(absolute)][0];overrides=body_overrides or {}
    assert set(overrides)<=source.masters,'Unknown pipeline body override'
    body=lambda master:overrides[master] if master in overrides else source.body(master)
    routes=AdmissionRoutes(body,source.masters,source.library,source.states,top,guard=source.guard)
    layer=routes.child('','attention');cuts=[]
    for context in ('',layer):
        module=routes.module(routes.contexts[context][0])
        for instance,(master,pins) in module.cells.items():
            if master not in routes.masters or not master.startswith('tri_oracle_'):continue
            if context=='' and instance=='attention':continue
            child=routes.child(context,instance);ports=routes.ports(master)
            outputs={bit for name,direction in ports.directions.items() if direction=='output' for bit in ports.net_bits(name)}
            routes.offpath[child]=outputs
            cuts.append(dict(context=child,master=master,output_bits=len(outputs)))
    selected=[('', 'projection_busy_reg')]+[(layer,f'state_reg[{bit}]') for bit in range(4)]
    masters={routes.module(routes.contexts[context][0]).cells[instance][0] for context,instance in selected}
    tables=[]
    for paths in original['sources'].values():
        standard,=(path for path in paths if path.name.startswith('tcbn28'))
        text=standard.read_text();table={}
        for master in sorted(masters):
            match,=re.finditer(r'(?m)^cell\s*\('+re.escape(master)+r'\)\s*\{',text)
            table[master]=primary_tile_state(liberty_group(text,match.end()))
        tables.append(table)
    assert len(tables)==3 and tables[0]==tables[1]==tables[2],'Pipeline primary state functions differ across corners'
    return dict(routes=routes,layer=layer,primary=tables[0],boundary_cuts=cuts,absolute_pipeline=absolute)


def prove_pipeline(environment,*,only_query=None,activation=()):
    from prove_tri_oracle_head_intensity import WordBridge
    from prove_tri_oracle_layer_row_epoch import physical_register,state_word
    from prove_tri_oracle_tile_command_routes import route_word
    from prove_tri_oracle_tile_geometry import geometry_check
    routes=environment['routes'];bridge=WordBridge(routes.graph);context=environment['layer']
    busy=physical_register(routes,bridge,'','projection_busy_reg',environment['primary'])
    assert busy['q']=='tensor_cfg_activation_stride[11]','Actual projection selector alias differs'
    layer=state_word(routes,bridge,context,4,environment['primary'])
    records=[busy,*layer['records']];rst=bridge.boolean('top.rst_n')
    def check(actual,wanted,*,label,conditions=()):
        routes.guard()
        result=geometry_check(bridge,actual,wanted,label=label,conditions=conditions,only_query=only_query,activation=activation)
        routes.guard();return result
    check([record['clock'] for record in records],[bridge.boolean('top.clk')]*5,
          label='all5_projection_layer_state_clocks')
    check([record['reset'] for record in records],[z3.Not(rst)]*5,
          label='all5_projection_layer_state_reset_bindings')
    stride=route_word(routes,bridge,'','tensor_cfg_activation_stride',32,direction='output')
    check([z3.Extract(11,11,stride)==1],[busy['old']],label='actual_projection_selector_alias_identity')
    check([exclusion_invariant(z3.BoolVal(bool(busy['reset_value'])),z3.BitVecVal(layer['reset_value'],4))],
          [z3.BoolVal(True)],label='projection_layer_actual_reset_basis')
    invariant=exclusion_invariant(busy['old'],layer['old'])
    check([exclusion_invariant(busy['data'],layer['data'])],[z3.BoolVal(True)],
          label='projection_layer_actual_state_induction',conditions=[rst,invariant])
    check([z3.Not(busy['old'])],[z3.BoolVal(True)],label='active_attention_layer_excludes_projection',
          conditions=[invariant,layer['old']!=0])
    features=route_word(routes,bridge,'','tensor_cfg_feature_words',10,direction='output')
    check([features,stride],[z3.BitVecVal(8,10),z3.BitVecVal(64,32)],label='head_mode_actual_tensor_feature_format',
          conditions=[invariant,layer['old']==5])
    assert only_query is None or len(bridge.checks)==1,'Targeted pipeline query absent'
    witnesses=[]
    if only_query is None:
        for busy_code,layer_code in ((True,0),(False,5)):
            solver=z3.SolverFor('QF_BV');solver.set(timeout=120000,max_memory=1024)
            solver.add(rst,invariant,busy['old']==busy_code,layer['old']==layer_code)
            result=solver.check();assert result==z3.sat,('Projection domain witness absent',busy_code,layer_code,str(result))
            witnesses.append(dict(projection_busy=busy_code,layer_state=layer_code,result='sat',
                                  full_clock_history_reachability_verified=False))
    return dict(bridge=bridge,busy=busy,layer=layer,invariant=invariant,queries=bridge.checks,witnesses=witnesses)


def rejection_controls(original):
    from hashlib import sha256
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_intensity import WordBridge,require_counterexample
    from prove_tri_oracle_tile_command_routes import route_word
    base=pipeline_environment(original);routes=base['routes'];master=routes.contexts[''][0]
    body=routes.body(master);before=sha256(body).hexdigest();rejected=[]
    raw=routes.module(master).cells['projection_busy_reg'][1]
    assert 'CDN' in raw and 'CP' in raw,'Projection primary interface differs'
    controls=[(f'{name}_busy_mask_bypassed','attention',{name:name},'induction',name)
              for name in ('frame_valid','restore_valid','head_valid','row_valid')]
    spurious={'D':"1'b1"}
    if 'E' in raw:spurious['E']="1'b1"
    controls.extend([
        ('projection_spurious_start_during_head','projection_busy_reg',spurious,'induction','spurious'),
        ('projection_reset_disconnected','projection_busy_reg',{'CDN':"1'b1"},'reset','reset')])
    for label,instance,pins,target,mode in controls:
        altered=body
        for pin,value in pins.items():altered=replace_instance_pin(altered,instance,pin,value.encode())
        environment=pipeline_environment(original,body_overrides={master:altered})
        changed=environment['routes'];bridge=WordBridge(changed.graph)
        layer=route_word(changed,bridge,environment['layer'],'state',4)
        busy,=bridge.convert([changed.trace('','tensor_cfg_activation_stride[11]')])
        top=changed.module(changed.contexts[''][0])
        def input_bit(name):
            assert top.directions.get(name)=='input' and top.declared[name] is None,'Fault activation is not a physical input'
            return bridge.boolean('top.'+name)
        query='all5_projection_layer_state_reset_bindings' if target=='reset' else 'projection_layer_actual_state_induction'
        if mode=='reset':active=[z3.Not(input_bit('rst_n'))]
        else:
            active=[input_bit('rst_n'),busy==(mode!='spurious'),layer==(5 if mode=='spurious' else 0),
                    z3.Not(input_bit('projection_done_ready'))]
            active.extend(input_bit(name)==(name==mode) for name in ('frame_valid','restore_valid','head_valid','row_valid'))
        try:prove_pipeline(environment,only_query=query,activation=active)
        except AssertionError as error:
            require_counterexample(error,expected_query=query)
            rejected.append(dict(control=label,result='sat',query=query,activation=mode,instance=instance,
                                 changed_pins=pins,altered_module_sha256=sha256(altered).hexdigest()))
            print('PIPELINE_CORRUPTION_REJECTED',label,query,flush=True)
        else:raise AssertionError(('Projection/attention corruption accepted',label))
    altered=replace_instance_pin(body,'projection_busy_reg','CP',b"1'b0")
    environment=pipeline_environment(original,body_overrides={master:altered})
    try:prove_pipeline(environment)
    except AssertionError as error:
        assert str(error)=='Epoch register clock differs',('Unrelated pipeline clock rejection',str(error))
        rejected.append(dict(control='projection_wrong_clock',rejection=str(error)))
    else:raise AssertionError('Projection wrong clock accepted')
    assert len(rejected)==7 and sha256(body).hexdigest()==before
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
        assert wanted is None or wanted==digest,('Changed pipeline ownership input',path)
        name=str(path.relative_to(ROOT));assert evidence.setdefault(name,digest)==digest
        return path
    prior=json.loads(pin(ROOT/'records/tri_oracle_packaged_layer_row_epoch.json').read_text())
    assert prior['state']=='mapped_layer_row_ownership_induction_verified'
    for name,digest in prior['evidence_sha256'].items():pin(ROOT/name,digest)
    full_name,=[name for name in prior['evidence_sha256'] if name.endswith('/layer_row_epoch_qualified.json')]
    full=json.loads((ROOT/full_name).read_text())
    for name,digest in full['evidence_sha256'].items():pin(ROOT/name,digest)
    for path in (Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_pipeline_layer_epoch_logic.py'):pin(path)
    with command_route_environment(pin) as original:
        assert original['candidate_sha256']==prior['candidate_sha256']
        environment=pipeline_environment(original);result=prove_pipeline(environment)
        corruptions=rejection_controls(original)
        routes=environment['routes'];layer_context=environment['layer']
        layer=routes.module(routes.contexts[layer_context][0]);pipeline=routes.module(routes.contexts[''][0])
        assert layer.sha256==prior['component']['layer_module_sha256'],'Projection attention-layer body differs'
        assert environment['absolute_pipeline']+'/'+layer_context==prior['component']['absolute_layer_context'],'Projection attention-layer instance differs'
        details=dict(pipeline_module_sha256=pipeline.sha256,layer_module_sha256=layer.sha256,
            absolute_pipeline_context=environment['absolute_pipeline'],absolute_layer_context=environment['absolute_pipeline']+'/'+layer_context,
            busy_register_alias=result['busy']['q'],projection_physical_state_bits=1,layer_physical_state_bits=4,
            common_reset_state=[result['busy']['reset_value'],result['layer']['reset_value']],ownership_state_pairs=17,
            state_satisfiability_witnesses=result['witnesses'],boundary_cuts=environment['boundary_cuts'],
            all_component_inputs_universally_quantified=True,graph_nodes=len(routes.graph.nodes),sequential_cut_bits=len(routes.sequential_cuts))
    revalidate_evidence(evidence,ROOT)
    report=dict(state='mapped_projection_layer_exclusion_induction_verified',candidate_sha256=prior['candidate_sha256'],
        queries=result['queries'],component=details,rejected_corruptions=corruptions,evidence_sha256=evidence,wall_seconds=time.monotonic()-start,
        peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        prior_command_projection_inactive_condition_discharged_after_common_reset=True,
        eventual_projection_or_attention_completion_verified=False,upstream_mode_reachability_verified=False,
        tensor_command_generation_verified=False,full_head_prediction_verified=False,task_accuracy_verified=False,
        physical_timing_verified=False,complete_paper_architecture_verified=False,advance_to_clock_distribution_or_routing_allowed=False)
    with output.open('x') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    import argparse,resource
    resource.setrlimit(resource.RLIMIT_AS,(3*2**30,3*2**30))
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    report=verify(parser.parse_args().output)
    print(report['state'],report['wall_seconds'],flush=True)
