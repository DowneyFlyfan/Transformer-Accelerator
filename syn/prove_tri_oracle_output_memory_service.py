"""Output-memory service refinement relative to a stated foundry memory contract.

Archived native evidence is finite compatibility evidence, not a new whole-chip
run or a universal proof of the vendor model's timing/unknown-state behavior.
"""
if not __debug__:raise RuntimeError('Memory service verification requires assertions')
from pathlib import Path
from hashlib import sha256,file_digest
import gc,json,re,resource,sys,time
import z3


STATE_WIDTHS=dict(wb_valid=1,wb_slot=4,sum=19,accumulate=1,forward=1,forward_data=32,q=32,
    recent_valid=1,recent_slot=4,recent_data=32,result_valid=1,bypass=1,bypass_data=32,held=32)
INPUT_WIDTHS=dict(array_valid=1,array_slot=4,array_sum=19,array_accumulate=1,read_valid=1,read_slot=4)
VENDOR_CONTRACT='Known two-state memory/inputs; common stable rising clocks; enabled noncolliding read settles to the selected pre-edge memory word before next sampling edge; enabled writes commit atomically; disabled reads retain Q. Analog timing, initialization-X safety and asynchronous clock faults are outside the theorem.'


def output_data(state):
    return z3.If(state['result_valid'],z3.If(state['bypass'],state['bypass_data'],state['q']),state['held'])


def accumulation_base(state):return z3.If(state['forward'],state['forward_data'],state['q'])


def writeback_data(state):
    return z3.SignExt(13,state['sum'])+z3.If(state['accumulate'],accumulation_base(state),z3.BitVecVal(0,32))


def service_step(old,request,rst_n):
    """All old values are sampled before writes and delayed memory-Q updates."""
    assert set(old)==set(STATE_WIDTHS)|{'memory'} and set(request)==set(INPUT_WIDTHS)
    current=z3.And(old['wb_valid'],request['read_slot']==old['wb_slot'])
    recent=z3.And(old['recent_valid'],request['read_slot']==old['recent_slot'])
    miss=z3.And(request['read_valid'],z3.Not(current),z3.Not(recent))
    accepted=z3.And(rst_n,request['array_valid'],z3.Not(miss))
    address=z3.If(miss,request['read_slot'],request['array_slot'])
    collision=z3.And(old['wb_valid'],address==old['wb_slot'])
    read_enable=z3.And(rst_n,z3.Or(miss,accepted),z3.Not(collision))
    write_enable=z3.And(rst_n,old['wb_valid']);data=writeback_data(old)
    def cleared(value):
        return z3.And(rst_n,value) if z3.is_bool(value) else z3.If(rst_n,value,z3.BitVecVal(0,value.size()))
    new=dict(memory=z3.If(write_enable,z3.Store(old['memory'],old['wb_slot'],data),old['memory']),
        q=z3.If(read_enable,z3.Select(old['memory'],address),old['q']),wb_valid=accepted,
        wb_slot=cleared(z3.If(accepted,request['array_slot'],old['wb_slot'])),
        sum=cleared(z3.If(accepted,request['array_sum'],old['sum'])),
        accumulate=cleared(z3.If(accepted,request['array_accumulate'],old['accumulate'])),
        forward=cleared(z3.If(accepted,collision,old['forward'])),
        forward_data=cleared(z3.If(z3.And(accepted,collision),data,old['forward_data'])),
        recent_valid=cleared(z3.Or(old['recent_valid'],old['wb_valid'])),
        recent_slot=cleared(z3.If(old['wb_valid'],old['wb_slot'],old['recent_slot'])),
        recent_data=cleared(z3.If(old['wb_valid'],data,old['recent_data'])),
        result_valid=cleared(request['read_valid']),
        bypass=cleared(z3.If(request['read_valid'],z3.Or(current,recent),old['bypass'])),
        bypass_data=cleared(z3.If(z3.And(request['read_valid'],current),accumulation_base(old),
            z3.If(z3.And(request['read_valid'],recent),old['recent_data'],old['bypass_data']))),
        held=cleared(z3.If(old['result_valid'],output_data(old),old['held'])))
    signals=dict(current_hit=current,recent_hit=recent,external_miss=miss,accepted_array=accepted,
        array_out_ready=z3.Not(miss),read_address=address,read_enable=read_enable,write_enable=write_enable,
        collision=collision,writeback_data=data,base=accumulation_base(old))
    return new,signals


def history_invariant(state,reference_data,reference_valid):
    return z3.And(z3.Implies(state['wb_valid'],accumulation_base(state)==z3.Select(state['memory'],state['wb_slot'])),
        z3.Implies(state['recent_valid'],state['recent_data']==z3.Select(state['memory'],state['recent_slot'])),
        state['result_valid']==reference_valid,output_data(state)==reference_data)


def logical_memory(state):
    return z3.If(state['wb_valid'],z3.Store(state['memory'],state['wb_slot'],writeback_data(state)),state['memory'])


def prove_history():
    """Reset basis plus invariant-preserving refinement for arbitrary known data."""
    old={name:z3.Bool('history.'+name) if width==1 else z3.BitVec('history.'+name,width) for name,width in STATE_WIDTHS.items()}
    old['memory']=z3.Array('history.memory',z3.BitVecSort(4),z3.BitVecSort(32))
    request={name:z3.Bool('request.'+name) if width==1 else z3.BitVec('request.'+name,width) for name,width in INPUT_WIDTHS.items()}
    previous_data=z3.BitVec('reference.last_data',32);previous_valid=z3.Bool('reference.last_valid');rst=z3.Bool('core.rst_n')
    new,signals=service_step(old,request,rst)
    reset,_=service_step(old,request,z3.BoolVal(False))
    invariant=history_invariant(old,previous_data,previous_valid)
    reference_data=z3.If(rst,z3.If(request['read_valid'],z3.Select(old['memory'],request['read_slot']),previous_data),z3.BitVecVal(0,32))
    reference_valid=z3.And(rst,request['read_valid'])
    pending=logical_memory(old)
    partial=z3.SignExt(13,request['array_sum'])+z3.If(request['array_accumulate'],z3.Select(pending,request['array_slot']),z3.BitVecVal(0,32))
    serialized=z3.If(rst,z3.If(signals['accepted_array'],z3.Store(pending,request['array_slot'],partial),pending),old['memory'])
    queries=[]
    for label,proposition,conditions in (
        ('service_reset_basis',history_invariant(reset,z3.BitVecVal(0,32),z3.BoolVal(False)),()),
        ('service_history_successor',history_invariant(new,reference_data,reference_valid),(invariant,)),
        ('service_serialized_pending_fold',logical_memory(new)==serialized,(invariant,)),
        ('service_no_macro_port_contention',z3.Not(z3.And(signals['read_enable'],signals['write_enable'],signals['read_address']==old['wb_slot'])),())):
        solver=z3.SolverFor('QF_AUFBV');solver.set(timeout=120000,max_memory=1024)
        solver.add(*conditions,z3.Not(proposition));started=time.monotonic();status=solver.check()
        assert status==z3.unsat,('Memory service history not proved',label,str(status),str(solver.model()) if status==z3.sat else solver.reason_unknown())
        queries.append(dict(label=label,result='unsat',seconds=time.monotonic()-started))
    return dict(queries=queries,word_bits=32,address_bits=4,memory_contract_assumption=VENDOR_CONTRACT,
        universal_vendor_semantics_verified=False,reset_cancels_pending_but_retains_memory=True,
        read_response_semantics='Pre-current-write snapshot; stable last response while invalid.')


METADATA_SHA256='c8b10ec0944a10ea68d5d338493ce06d951ebe5be6ee853fbc43a9788a5feb66'


def physical_old_bit(routes,bridge,instance):
    module=routes.module(routes.contexts[''][0]);master,pins=module.cells[instance]
    assert routes.states[master]=={'ff':1} and routes.library[master,'Q']['function']=='IQ','Memory service old state kind/polarity differs'
    q,=module.expression(pins['Q'])
    stem=q if q in module.declared else q.rsplit('[',1)[0]
    assert q in module.bits and module.directions.get(stem)!='input','Memory service FF Q is not a declared state net'
    assert routes.drivers('',q)==[('cell',instance,master,'Q',0,1,pins)],'Memory service FF Q lacks its exact sole driver'
    value,=bridge.convert([routes.trace('',q)])
    return value


def physical_old_word(routes,bridge,base,start,width):
    return bridge.pack([physical_old_bit(routes,bridge,f'{base}[{bit}]') for bit in range(start,start+width)])


def service_environment(original,path,*,overrides=None):
    from prove_tri_oracle_accumulator_metadata import metadata_environment
    from prove_tri_oracle_packaged_accumulators import primary_models
    environment=metadata_environment(original,path,overrides=overrides)
    module=environment['routes'].module(environment['master'])
    names=[f'{prefix}_reg[{bit}]' for prefix in ('recent_data','response_bypass_data','held_result') for bit in range(1024)]
    names += ['recent_valid_reg','response_bypass_reg','result_valid_reg']
    kinds=frozenset(module.cells[name][0] for name in names);cache=original.setdefault('primary_models_by_master_set',{})
    if kinds not in cache:cache[kinds]=primary_models(original,kinds)
    environment.update(primary=cache[kinds],service_register_names=names)
    return environment


def prove_service(environment,*,rows=range(32),only_query=None,activation=()):
    from prove_tri_oracle_head_intensity import WordBridge
    from prove_tri_oracle_layer_row_epoch import physical_register
    from prove_tri_oracle_tile_command_routes import route_word
    from prove_tri_oracle_tile_geometry import geometry_check
    routes=environment['routes'];bridge=WordBridge(routes.graph);records={}
    bridge.variables.update({f'top.{name}':bridge.boolean('top.rst_n') for name in environment['reset_inputs']})
    for name in environment['service_register_names']:
        physical_old_bit(routes,bridge,name)
        record=physical_register(routes,bridge,'',name,environment['primary'])
        assert record['reset_value']==0,'Memory service register reset value differs'
        record['next']=z3.If(record['reset'],z3.BoolVal(False),record['data']);records[name]=record
    assert len(records)==3075
    def vector(prefix,row,key='old'):
        return bridge.pack([records[f'{prefix}_reg[{row*32+bit}]'][key] for bit in range(32)])
    old_flag=lambda name:physical_old_bit(routes,bridge,name+'_reg')
    old_word=lambda name,start,width:physical_old_word(routes,bridge,name+'_reg',start,width)
    rst=bridge.boolean('top.rst_n')
    port=lambda context,name,width,direction:route_word(routes,bridge,context,name,width,direction=direction)
    shared=dict(wb_valid=old_flag('writeback_valid'),wb_slot=old_word('writeback_slot',0,4),
        accumulate=old_flag('writeback_accumulate'),forward=old_flag('accumulator_forward'),
        recent_valid=records['recent_valid_reg']['old'],recent_slot=old_word('done_output',0,4),
        result_valid=records['result_valid_reg']['old'],bypass=records['response_bypass_reg']['old'])
    request=dict(array_valid=port('compute','out_valid',1,'output'),
        array_slot=physical_old_word(routes,bridge,'slot_pipe_reg[3]',0,4),
        array_accumulate=physical_old_bit(routes,bridge,'accumulate_pipe_reg[3]'),
        read_valid=port('','read_valid',1,'input'),read_slot=port('','read_output',4,'input'))
    sums=port('compute','out_sums',608,'output');output=port('','result_data',1024,'output')
    if callable(activation):activation=activation(bridge,shared,request,records)
    def check(actual,expected,label,conditions=()):
        routes.guard();value=geometry_check(bridge,actual,expected,label=label,conditions=conditions,only_query=only_query,activation=activation)
        routes.guard();return value
    check([record['clock'] for record in records.values()],[bridge.boolean('top.clk')]*3075,'all3075_memory_service_register_clocks')
    check([record['reset'] for record in records.values()],[z3.Not(rst)]*3075,'all3075_memory_service_register_reset_bindings')
    check([port('','result_valid',1,'output')],[shared['result_valid']],'actual_public_result_valid_binding')
    scalar_queries=False;signals=None
    for row in rows:
        old=dict(shared,sum=old_word('writeback_sums',row*19,19),forward_data=old_word('accumulator_forward_data',row*32,32),
            q=bridge.pack([bridge.boolean(f'physical_memory.outputs[{row//4}].Q[{row%4*32+bit}]') for bit in range(32)]),
            recent_data=vector('recent_data',row),bypass_data=vector('response_bypass_data',row),held=vector('held_result',row),
            memory=z3.Array(f'contract.row{row}.memory',z3.BitVecSort(4),z3.BitVecSort(32)))
        offered=request|dict(array_sum=z3.Extract(row*19+18,row*19,sums))
        new,signals=service_step(old,offered,rst)
        if not scalar_queries:
            check([records[name+'_reg']['next'] for name in ('recent_valid','result_valid','response_bypass')],
                [new[name] for name in ('recent_valid','result_valid','bypass')],'actual_memory_service_scalar_next_states')
            check([port('compute','out_ready',1,'input')],[signals['array_out_ready']],'actual_external_read_miss_backpressures_array')
            scalar_queries=True
        actual_data=bridge.pack(bridge.convert([routes.trace('',net) for net in routes.memory['data_words'][row]]))
        check([actual_data],[signals['writeback_data']],f'actual_output_word{row}_prepared_write_data')
        for prefix,field in (('recent_data','recent_data'),('response_bypass_data','bypass_data'),('held_result','held')):
            check([vector(prefix,row,'next')],[new[field]],f'actual_output_word{row}_{prefix}_next_state')
        check([z3.Extract(row*32+31,row*32,output)],[output_data(old)],f'actual_output_word{row}_public_response')
    assert signals is not None
    module=routes.module(environment['master'])
    for bank,instance in enumerate(routes.memory['instances']):
        _,pins=module.cells[instance]
        def actual_pin(pin):
            nets=module.expression(pins[pin]);values=bridge.convert([routes.trace('',net) for net in reversed(nets)])
            return values[0] if len(values)==1 else bridge.pack(values)
        check([actual_pin(name) for name in ('AA','WEB','AB','REB')],
            [shared['wb_slot'],z3.Not(signals['write_enable']),signals['read_address'],z3.Not(signals['read_enable'])],
            f'actual_memory{bank}_full_read_write_controls')
    witnesses=[]
    if only_query is None:
        for mode in ('current_write_hit','recent_hit','external_miss','array_collision','array_read','held_response'):
            solver=z3.SolverFor('QF_BV');solver.set(timeout=120000,max_memory=1024);solver.add(rst)
            if mode=='current_write_hit':solver.add(request['read_valid'],signals['current_hit'])
            elif mode=='recent_hit':solver.add(request['read_valid'],z3.Not(signals['current_hit']),signals['recent_hit'])
            elif mode=='external_miss':solver.add(signals['external_miss'])
            elif mode=='array_collision':solver.add(signals['accepted_array'],signals['collision'])
            elif mode=='array_read':solver.add(signals['accepted_array'],signals['read_enable'])
            else:solver.add(z3.Not(request['read_valid']),shared['result_valid'])
            assert solver.check()==z3.sat,'Memory service mode witness absent'
            witnesses.append(dict(mode=mode,result='sat'))
    assert only_query is None or len(bridge.checks)==1,'Targeted memory service query absent'
    return dict(queries=bridge.checks,words=len(rows),selected_register_bits=3075,local_mode_witnesses=witnesses,
        graph_nodes=len(routes.graph.nodes),bridge=bridge,shared=shared,request=request,records=records)


def rejection_controls(original,path):
    """Reject activated corruptions of actual cells and memory-port bindings."""
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_intensity import require_counterexample
    from prove_tri_oracle_packaged_accumulators import physical_pin_expression
    base=service_environment(original,path);routes=base['routes'];master=base['master']
    module=routes.module(master);body=routes.body(master);faults=[]
    def add(label,edits,query,mode):
        changed=body
        for instance,pin,value in edits:changed=replace_instance_pin(changed,instance,pin,value.encode())
        faults.append((label,changed,query,mode))
    def force(instance,value):
        pins=module.cells[instance][1]
        return [(instance,'D',value)]+([(instance,'E',"1'b1")] if 'E' in pins else [])
    recent='actual_output_word0_recent_data_next_state';bypass='actual_output_word0_response_bypass_data_next_state'
    scalar='actual_memory_service_scalar_next_states';memory='actual_memory0_full_read_write_controls'
    add('recent_write_data_lost',force('recent_data_reg[0]',"1'b0"),recent,'write')
    data_bit=physical_pin_expression(module,[routes.memory['data_words'][0][0]])
    add('current_hit_returns_new_write_instead_of_old_base',force('response_bypass_data_reg[0]',data_bit),bypass,'current_new')
    add('current_hit_capture_replaced_by_hold',force('response_bypass_data_reg[0]',module.cells['response_bypass_data_reg[0]'][1]['Q']),bypass,'current_hold')
    add('response_bypass_flag_lost',force('response_bypass_reg',"1'b0"),scalar,'current_hit')
    add('response_valid_lost',force('result_valid_reg',"1'b0"),scalar,'read')
    add('held_response_data_lost',force('held_result_reg[0]',"1'b0"),'actual_output_word0_held_result_next_state','held')
    bits=list(module.expression(module.cells['outputs[0]'][1]['Q']));bits[-1],bits[-2]=bits[-2],bits[-1]
    add('physical_memory_response_bit_swap',[('outputs[0]','Q',physical_pin_expression(module,bits))],
        'actual_output_word0_public_response','held')
    add('same_slot_read_write_collision_enabled',[('outputs[0]','REB',"1'b0")],memory,'collision')
    add('external_read_uses_wrong_memory_address',[('outputs[0]','AB',"4'b0")],memory,'miss')
    add('recent_write_valid_lost',force('recent_valid_reg',"1'b0"),scalar,'recent_valid')
    add('held_response_reset_disconnected',[('held_result_reg[0]','CDN',"1'b1")],
        'all3075_memory_service_register_reset_bindings','reset')
    rejected=[]
    del base;gc.collect()
    for label,changed,query,mode in faults:
        environment=service_environment(original,path,overrides={master:changed});changed_routes=environment['routes']
        def activation(bridge,shared,request,records):
            rst=bridge.boolean('top.rst_n')
            if mode=='reset':return [z3.Not(rst)]
            conditions=[rst]
            q=bridge.word('physical_memory.outputs[0].Q',32)
            old_word=lambda name,width:physical_old_word(changed_routes,bridge,name+'_reg',0,width)
            if mode=='write':conditions += [shared['wb_valid'],z3.Not(shared['accumulate']),old_word('writeback_sums',19)==1]
            elif mode in ('current_new','current_hold','current_hit'):
                conditions += [shared['wb_valid'],request['read_valid'],request['read_slot']==1,shared['wb_slot']==1,
                    z3.Not(shared['recent_valid']),z3.Not(shared['forward']),z3.Not(shared['accumulate']),
                    old_word('writeback_sums',19)==1,q==(0 if mode=='current_new' else 1),
                    z3.Not(records['response_bypass_data_reg[0]']['old'])]
            elif mode=='read':conditions += [request['read_valid']]
            elif mode=='held':conditions += [shared['result_valid'],z3.Not(shared['bypass']),q==1]
            elif mode=='collision':conditions += [shared['wb_valid'],request['array_valid'],z3.Not(request['read_valid']),
                shared['wb_slot']==1,request['array_slot']==1]
            elif mode=='miss':conditions += [request['read_valid'],z3.Not(shared['wb_valid']),z3.Not(shared['recent_valid']),request['read_slot']==1]
            elif mode=='recent_valid':conditions += [shared['wb_valid'],z3.Not(shared['recent_valid'])]
            else:raise AssertionError('Unknown output service fault activation')
            return conditions
        try:prove_service(environment,rows=range(1),only_query=query,activation=activation)
        except AssertionError as error:
            require_counterexample(error,expected_query=query)
            rejected.append(dict(control=label,query=query,result='sat',activation=mode,
                altered_modules_sha256={master:sha256(changed).hexdigest()}))
            print('OUTPUT_SERVICE_CORRUPTION_REJECTED',label,query,flush=True)
        else:raise AssertionError(('Output service corruption accepted',label))
        del environment;gc.collect()
    changed=replace_instance_pin(body,'held_result_reg[0]','CP',b"1'b0")
    try:prove_service(service_environment(original,path,overrides={master:changed}),rows=range(1))
    except AssertionError as error:
        assert str(error)=='Epoch register clock differs',('Unrelated output service clock rejection',str(error))
        rejected.append(dict(control='held_response_wrong_clock',rejection=str(error),altered_modules_sha256={master:sha256(changed).hexdigest()}))
    else:raise AssertionError('Output service wrong clock accepted')
    assert len(rejected)==12 and len({tuple(sorted(row['altered_modules_sha256'].items())) for row in rejected})==12
    return rejected


def verify(output,*,prototype=False):
    from prove_tri_oracle_tile_command_routes import command_route_environment
    from prove_tri_oracle_command_admission import AdmissionRoutes
    from prove_tri_oracle_packaged_accumulators import compiled_memory_library,local_source_paths
    from prove_tri_oracle_packaged_products import ROOT,memory_guard
    from prove_tri_oracle_head_score_frontend import revalidate_evidence
    assert not Path('/.dockerenv').exists() and output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);start=time.monotonic();pins={}
    def pin(path,wanted=None):
        with path.open('rb') as stream:actual=file_digest(stream,'sha256').hexdigest()
        assert wanted is None or actual==wanted,('Changed output service input',path)
        assert pins.setdefault(str(path.relative_to(ROOT)),actual)==actual
        return path
    prior=json.loads(pin(ROOT/'records/tri_oracle_accumulator_metadata_history.json',METADATA_SHA256).read_text())
    assert prior['state']=='mapped_accepted_command_metadata_trace_refinement_verified' and prior['core_count']==20
    for name,digest in prior['evidence_sha256'].items():pin(ROOT/name,digest)
    full_name,=(name for name in prior['evidence_sha256'] if name.endswith('/metadata_review_fixed.json'))
    full=json.loads((ROOT/full_name).read_text())
    for name,digest in full['evidence_sha256'].items():pin(ROOT/name,digest)
    predecessor={core['absolute_context']:core for core in prior['core_modules']}
    local_sources=local_source_paths((Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_output_memory_service_logic.py'),ROOT/'syn')
    for path in local_sources:pin(path)
    cores=[];corruptions=[]
    with command_route_environment(pin) as original:
        assert original['candidate_sha256']==prior['candidate_sha256']
        original['memory_bus_library']=compiled_memory_library(original);source=original['routes']
        original['reset_routes']=AdmissionRoutes(source.body,source.masters,source.library,source.states,source.contexts[''][0],guard=source.guard)
        original['reset_routes'].modules=source.modules
        for bank in range(1 if prototype else 5):
            for core in range(1 if prototype else 4):
                path=original['paths']['owner']+f'/fabric/clusters[{bank}].unit/selected_bank{bank}.block_instance/source_cluster/implementation/cores[{core}]/compute'
                environment=service_environment(original,path);previous=predecessor[path]
                assert environment['core_module_sha256']==previous['core_module_sha256'] and environment['array_module_sha256']==previous['array_module_sha256'],'Output service predecessor body binding differs'
                result=prove_service(environment,rows=range(1 if prototype else 32))
                cores.append(dict(bank=bank,core=core,absolute_context=path,module=environment['master'],
                    core_module_sha256=environment['core_module_sha256'],array_module=environment['array_master'],array_module_sha256=environment['array_module_sha256'],
                    queries=result['queries'],hierarchy_bindings=environment['hierarchy_bindings'],words=result['words'],
                    selected_register_bits=result['selected_register_bits'],local_mode_witnesses=result['local_mode_witnesses'],
                    actual_reset_inputs=environment['reset_inputs']))
                del environment,result;gc.collect()
        if not prototype:corruptions=rejection_controls(original,cores[0]['absolute_context'])
    history=prove_history()
    loaded={Path(module.__file__).resolve() for module in sys.modules.values() if getattr(module,'__file__',None)
            and Path(module.__file__).resolve().parent==ROOT/'syn'}
    assert loaded<=set(local_sources),('Unpinned output service source',loaded-set(local_sources))
    revalidate_evidence(pins,ROOT)
    report=dict(state='mapped_output_memory_service_prototype' if prototype else 'mapped_output_memory_service_refinement_verified_relative_to_explicit_memory_contract',
        candidate_sha256=prior['candidate_sha256'],cores=cores,core_count=len(cores),history_theorem=history,
        rejected_mutations=corruptions,conditional_service_refinement_verified=not prototype,
        evidence_sha256=pins,local_source_files=len(local_sources),all_loaded_local_sources_pinned=True,
        equivalence_queries=sum(len(core['queries'])+len(core['hierarchy_bindings']) for core in cores),
        wall_seconds=time.monotonic()-start,peak_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        universal_compiler_memory_semantics_verified=False,complete_memory_history_verified=False,
        complete_tensor_scores_verified=False,task_accuracy_verified=False,physical_timing_verified=False,
        complete_paper_architecture_verified=False,advance_to_clock_distribution_or_routing_allowed=False,
        scope=f'Actual{len(cores)}cores/{sum(core["words"] for core in cores)}words, response/cache/hold register transfer and full read/write controls relative to the explicit two-state foundry-memory contract. Conditional history induction establishes old-data reads, recent-write cache, response holds and serial accepted-partial folds. Archived model compatibility is separate finite evidence; compiler timing/unknown-state semantics, input numerical provenance and complete tensor/paper execution remain unqualified.')
    with output.open('x') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    print(report['state'],len(cores),sum(core['words'] for core in cores),report['wall_seconds'],flush=True)


if __name__=='__main__':
    import argparse
    resource.setrlimit(resource.RLIMIT_AS,(3*2**30,3*2**30))
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);parser.add_argument('--prototype',action='store_true')
    args=parser.parse_args();verify(args.output,prototype=args.prototype)
