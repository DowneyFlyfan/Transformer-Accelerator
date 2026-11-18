"""Compose qualified mapped arithmetic stages with ordered output-memory history.

The pipeline latency and partial-sum format are local implementation choices.
Numerical provenance starts at the processing-array operand/mask interface;
input-memory contents and whole-chip prediction behavior remain separate.
"""
if not __debug__:raise RuntimeError('Numeric history verification requires assertions')
from pathlib import Path
from hashlib import sha256,file_digest
import gc,json,resource,sys,time
from itertools import product
import z3

CONTRACT_ROOTS={
    'product':('records/tri_oracle_packaged_product_next_states.json','a8304c395845b4da35a4a2ea21e486e85eaac567ad8305adae8b924985202d2e'),
    'reduction':('records/tri_oracle_packaged_reduction_next_states.json','a419fcf207ec8f572a207ebc7e6f336624396bd11477b1b43663acc2833914a1'),
    'valid':('records/tri_oracle_packaged_valid_next_states.json','6e83a85405295e61d61fb01d0e335ca333500092a9b02cc9a50ad2bfaed08751'),
    'metadata':('records/tri_oracle_accumulator_metadata_history.json','c8b10ec0944a10ea68d5d338493ce06d951ebe5be6ee853fbc43a9788a5feb66'),
    'service':('records/tri_oracle_output_memory_service_history.json','a5d46def3a3d50390aaaa1fb3dff825567e30e91671311b4c36652ff8589d7c1')}
EXTRA_ROUTE_INPUTS={'.cache/wide_packaged_host_link/head_ratio_proof/configuration_qualified.json':
    '66c1f136766622b83789c6ce7b9213a527a2c09879389294d127a1c00f94e064'}


def load_contract(kind,content):
    assert sha256(content).hexdigest()==CONTRACT_ROOTS[kind][1],'Numeric contract digest differs from published root'
    record=json.loads(content)
    states=dict(product='packaged_signed_product_next_states_exhaustively_verified',
        reduction='packaged_signed_reduction_next_states_symbolically_verified',valid='packaged_local_valid_transitions_and_clears_verified',
        metadata='mapped_accepted_command_metadata_trace_refinement_verified',
        service='mapped_output_memory_service_refinement_verified_relative_to_explicit_memory_contract')
    assert record['state']==states[kind],'Numeric contract state is unqualified'
    assert record['array_instances' if kind in ('product','reduction','valid') else 'core_count']==20,'Numeric contract coverage differs'
    return record


def require_array_contract(body,name,certificates):
    digest=sha256(body).hexdigest()
    for kind in ('product','reduction','valid'):
        assert name in certificates[kind]['arrays'],'Numeric array name is absent from qualified local contract'
        assert certificates[kind]['arrays'][name]['array_module_sha256']==digest,'Numeric array body differs from qualified local contract'
    return digest


def expected_evidence_inventory(root,certificates,sources=None):
    from prove_tri_oracle_packaged_accumulators import local_source_paths
    expected=dict(EXTRA_ROUTE_INPUTS)
    def add(name,wanted):assert expected.setdefault(name,wanted)==wanted,('Conflicting numeric evidence',name)
    for kind,(name,wanted) in CONTRACT_ROOTS.items():
        add(name,wanted)
        for path,digest in certificates[kind]['evidence_sha256'].items():add(path,digest)
    if sources is None:sources=local_source_paths((root/'syn/prove_tri_oracle_numeric_pipeline_history.py',
        root/'syn/test_tri_oracle_numeric_pipeline_history_logic.py'),root/'syn')
    for path in sources:
        with path.open('rb') as stream:add(str(path.relative_to(root)),file_digest(stream,'sha256').hexdigest())
    return expected


def masked_products(a,b,enabled):
    assert len(a)==len(b)==len(enabled)==8
    assert all(x.size()==8 for x in [*a,*b]) and all(z3.is_bool(e) for e in enabled)
    return [z3.If(e,z3.SignExt(8,x)*z3.SignExt(8,y),z3.BitVecVal(0,16)) for x,y,e in zip(a,b,enabled)]


def grouped_sums(products,stage):
    assert len(products)==8 and stage in range(4) and all(x.size()==16 for x in products)
    width=16+stage;group=1<<stage
    return [sum((z3.SignExt(stage,x) for x in products[start:start+group]),z3.BitVecVal(0,width))
            for start in range(0,8,group)]


def pipeline_step(old,in_valid,out_ready,incoming,rst):
    assert set(old)=={'valid','data','slot','accumulate'} and all(len(old[k])==4 for k in old)
    ready=z3.Or(z3.Not(old['valid'][3]),out_ready)
    data=[]
    for stage in range(4):
        assert len(old['data'][stage])==8>>stage and all(x.size()==16+stage for x in old['data'][stage])
        capture=z3.And(ready,in_valid if stage==0 else old['valid'][stage-1])
        computed=incoming['products'] if stage==0 else [z3.SignExt(1,a)+z3.SignExt(1,b)
            for a,b in zip(old['data'][stage-1][::2],old['data'][stage-1][1::2])]
        data.append([z3.If(capture,new,previous) for new,previous in zip(computed,old['data'][stage],strict=True)])
    new_valid=[z3.And(rst,z3.If(ready,previous,current))
        for previous,current in zip([in_valid,*old['valid'][:3]],old['valid'])]
    slots=[incoming['slot'],*old['slot'][:3]];accumulates=[incoming['accumulate'],*old['accumulate'][:3]]
    return dict(valid=new_valid,data=data,
        slot=[z3.If(rst,z3.If(ready,new,current),z3.BitVecVal(0,4)) for new,current in zip(slots,old['slot'])],
        accumulate=[z3.And(rst,z3.If(ready,new,current)) for new,current in zip(accumulates,old['accumulate'])]),ready


def ghost_step(ghost,valid,ready,in_valid,products):
    # Ghosts retain original accepted products, without sharing the reduction tree.
    return [[z3.If(z3.And(ready,in_valid if stage==0 else valid[stage-1]),source,held)
             for source,held in zip(products if stage==0 else ghost[stage-1],ghost[stage])]
            for stage in range(4)]


def stage_invariant(state,ghost,stage):
    return z3.Implies(state['valid'][stage],z3.And(*[actual==wanted for actual,wanted in
        zip(state['data'][stage],grouped_sums(ghost[stage],stage),strict=True)]))


def append_partial(memory,slot,accumulate,total):
    assert total.size()==19 and slot.size()==4
    value=z3.SignExt(13,total)+z3.If(accumulate,z3.Select(memory,slot),z3.BitVecVal(0,32))
    return z3.Store(memory,slot,value)


def fold_pending(memory,state,ghost):
    # The highest occupied stage is oldest. Repeated slots must retain this order.
    for stage in reversed(range(4)):
        changed=append_partial(memory,state['slot'][stage],state['accumulate'][stage],grouped_sums(ghost[stage],3)[0])
        memory=z3.If(state['valid'][stage],changed,memory)
    return memory


def proof_obligations(advance=pipeline_step):
    from prove_tri_oracle_output_memory_service import STATE_WIDTHS,service_step,history_invariant,logical_memory,accumulation_base
    from prove_tri_oracle_accumulator_metadata import queue_next
    old=dict(valid=[z3.Bool(f'numeric.valid{i}') for i in range(4)],
        data=[[z3.BitVec(f'numeric.data{stage}.{i}',16+stage) for i in range(8>>stage)] for stage in range(4)],
        slot=[z3.BitVec(f'numeric.slot{i}',4) for i in range(4)],
        accumulate=[z3.Bool(f'numeric.accumulate{i}') for i in range(4)])
    ghost=[[z3.BitVec(f'numeric.ghost{stage}.{i}',16) for i in range(8)] for stage in range(4)]
    incoming=dict(products=[z3.BitVec(f'numeric.product{i}',16) for i in range(8)],
        slot=z3.BitVec('numeric.input_slot',4),accumulate=z3.Bool('numeric.input_accumulate'))
    valid=z3.Bool('numeric.in_valid');rst=z3.Bool('numeric.rst_n')
    service={name:z3.Bool('service.'+name) if width==1 else z3.BitVec('service.'+name,width) for name,width in STATE_WIDTHS.items()}
    service['memory']=z3.Array('service.memory',z3.BitVecSort(4),z3.BitVecSort(32))
    read_valid=z3.Bool('service.read_valid');read_slot=z3.BitVec('service.read_slot',4)
    request=dict(array_valid=old['valid'][3],array_slot=old['slot'][3],array_sum=old['data'][3][0],
        array_accumulate=old['accumulate'][3],read_valid=read_valid,read_slot=read_slot)
    updated,signals=service_step(service,request,rst)
    out_ready=z3.Bool('numeric.out_ready');reference_ready=z3.Or(z3.Not(old['valid'][3]),out_ready)
    new,actual_ready=advance(old,valid,out_ready,incoming,rst)
    new_ghost=ghost_step(ghost,old['valid'],reference_ready,valid,incoming['products'])
    invariant=z3.And(*[stage_invariant(old,ghost,stage) for stage in range(4)])
    previous_data=z3.BitVec('service.reference_data',32);previous_valid=z3.Bool('service.reference_valid')
    service_invariant=history_invariant(service,previous_data,previous_valid)
    reset,_=advance(old,valid,out_ready,incoming,z3.BoolVal(False))
    queries=[('pipeline_ready_matches_available_output',(),actual_ready==reference_ready),
        ('pipeline_reset_cancels_valid_without_initializing_data',(),z3.And(*[z3.Not(x) for x in reset['valid']]))]
    # Use the published physical-role convention: pending0,array1..4,WB5,done6.
    # Incoming operands are accepted at the later array handshake, not at a
    # simultaneous external command admission into pending0.
    queue=dict(valid=[valid,*old['valid'],service['wb_valid'],z3.Bool('metadata.done_valid')],
        slot=[incoming['slot'],*old['slot'],service['wb_slot'],service['recent_slot']],
        accumulate=[incoming['accumulate'],*old['accumulate'],service['accumulate']])
    projected=queue_next(queue,z3.Bool('metadata.cmd_valid'),z3.BitVec('metadata.cmd_slot',4),
        z3.Bool('metadata.cmd_accumulate'),out_ready,z3.Bool('metadata.cmd_ready'),rst)
    observed=[*new['valid'],*new['slot'],*new['accumulate'],updated['wb_valid'],updated['wb_slot'],updated['accumulate'],updated['recent_slot']]
    wanted=[*projected['valid'][1:5],*projected['slot'][1:5],*projected['accumulate'][1:5],
        projected['valid'][5],projected['slot'][5],projected['accumulate'][5],projected['slot'][6]]
    queries += [('certified_metadata_projection_matches_numeric_and_writeback_successors',
        (out_ready==signals['array_out_ready'],),z3.And(*[a==b for a,b in zip(observed,wanted,strict=True)]))]
    queries += [(f'pipeline_stage{stage}_history_successor',(invariant,),stage_invariant(new,new_ghost,stage)) for stage in range(4)]
    queries += [('pipeline_final_sum_equals_accepted_eight_product_dot',(invariant,),
        z3.Implies(old['valid'][3],old['data'][3][0]==grouped_sums(ghost[3],3)[0]))]
    before=fold_pending(logical_memory(service),old,ghost)
    after=fold_pending(logical_memory(updated),new,new_ghost)
    accept=z3.And(reference_ready,valid)
    expected=z3.If(rst,z3.If(accept,append_partial(before,incoming['slot'],incoming['accumulate'],
        grouped_sums(incoming['products'],3)[0]),before),service['memory'])
    # These are sufficient, weaker hypotheses than the full combined invariant.
    # In particular no recent-cache or response-state fact is needed for ordering.
    base_invariant=z3.Implies(service['wb_valid'],accumulation_base(service)==z3.Select(service['memory'],service['wb_slot']))
    queries += [('accepted_input_updates_ordered_pending_memory_fold',
        (stage_invariant(old,ghost,3),base_invariant,out_ready==signals['array_out_ready']),after==expected)]
    response=z3.If(rst,z3.If(read_valid,z3.Select(service['memory'],read_slot),previous_data),z3.BitVecVal(0,32))
    queries += [('numeric_pipeline_preserves_prewrite_read_response_history',(invariant,service_invariant),
        history_invariant(updated,response,z3.And(rst,read_valid)))]
    return queries


def prove_history():
    queries=[];partitions=[]
    for label,conditions,proposition in proof_obligations():
        cases=[()]
        if label=='accepted_input_updates_ordered_pending_memory_fold':
            rst=z3.Bool('numeric.rst_n')
            flags=[*[z3.Bool(f'numeric.valid{i}') for i in range(4)],z3.Bool('numeric.in_valid'),z3.Bool('numeric.out_ready')]
            cases=[(z3.Not(rst),)]+[(rst,*[flag==value for flag,value in zip(flags,values)])
                for values in product((False,True),repeat=6)]
            coverage=z3.SolverFor('QF_BV');coverage.add(z3.Not(z3.Or(*[z3.And(*case) for case in cases])))
            assert coverage.check()==z3.unsat,'Numeric fold case partition is incomplete'
            partitions.append(dict(label=label,result='unsat',reset_cases=1,nonreset_cases=64,
                variables=[str(flag) for flag in flags]))
        results=[]
        for index,case in enumerate(cases):
            solver=z3.SolverFor('QF_AUFBV');solver.set(timeout=120000,max_memory=1024)
            solver.add(*conditions,*case,z3.Not(proposition));started=time.monotonic()
            print('NUMERIC_HISTORY_QUERY_START',label,index,flush=True);result=solver.check()
            assert result==z3.unsat,('Numeric pipeline history not proved',label,index,str(result),
                str(solver.model()) if result==z3.sat else solver.reason_unknown())
            results.append(dict(case=index,result='unsat',seconds=time.monotonic()-started))
            print('NUMERIC_HISTORY_QUERY_UNSAT',label,index,results[-1]['seconds'],flush=True)
        queries.append(dict(label=label,result='unsat',seconds=sum(r['seconds'] for r in results),
            exhaustive_control_cases=len(cases),case_results=results))
    return dict(queries=queries,control_partition_coverage=partitions,pipeline_stages=4,original_products_per_row=8,product_bits=16,dot_bits=19,
        input_memory_contents_verified=False,unknown_state_or_analog_timing_verified=False,
        reference_scope='Accepted processing-array operands/masks, typed local stage contracts and explicit two-state output-memory service contract.')


def physical_state_bit(routes,bridge,context,instance):
    module=routes.module(routes.contexts[context][0]);master,pins=module.cells[instance]
    assert routes.states[master]=={'ff':1} and routes.library[master,'Q']['function']=='IQ','Numeric state kind/polarity differs'
    assert module.expression(pins['CP'])==('clk',),'Numeric register clock differs'
    q,=module.expression(pins['Q']);stem=q if q in module.declared else q.rsplit('[',1)[0]
    assert q in module.bits and module.directions.get(stem)!='input','Numeric Q is not a declared non-input net'
    assert routes.drivers(context,q)==[('cell',instance,master,'Q',0,1,pins)],'Numeric Q lacks exact sole physical driver'
    value,=bridge.convert([routes.trace(context,q)])
    return value,q


def bind_pipeline(environment,certificates):
    """Check the same physical states/interfaces certified by all local proofs."""
    from prove_tri_oracle_head_intensity import WordBridge
    from prove_tri_oracle_tile_command_routes import route_word
    routes=environment['routes'];master=environment['array_master'];module=routes.module(master)
    digest=require_array_contract(routes.body(master),master,certificates)
    context=routes.child('','compute');assert routes.offpath[context]==set(module.net_bits('out_sums'))
    # Expose actual registered outputs instead of retaining the former numerical cut.
    del routes.offpath[context]
    bridge=WordBridge(routes.graph);rst=bridge.boolean('top.rst_n')
    bridge.variables.update({f'top.{name}':rst for name in environment['reset_inputs']})
    for name,width,direction in [('operand_a',2048,'input'),('operand_b',2048,'input'),('lane_enable',256,'input'),('out_sums',608,'output')]:
        assert module.directions[name]==direction and module.declared[name]==(width-1,0),'Numeric array interface differs'
        if direction=='input':
            assert all(not routes.drivers(context,bit) for bit in module.net_bits(name)),'Numeric array input has an internal driver'
    product_count=reduction_count=0;last=[]
    for lane in range(256):
        for bit in range(16):
            _,q=physical_state_bit(routes,bridge,context,f'product[{lane}].value_reg[{bit}]')
            assert q==f'product[{lane}].value[{bit}]','Numeric product bit order differs'
            product_count+=1
    for stage in range(3):
        for row in range(32):
            for pair in range(4>>stage):
                for bit in range(17+stage):
                    value,q=physical_state_bit(routes,bridge,context,f'reduction[{stage}].row[{row}].sum[{pair}].value_reg[{bit}]')
                    wanted=f'out_sums[{row*19+bit}]' if stage==2 else f'reduction[{stage}].row[{row}].sum[{pair}].value[{bit}]'
                    assert q==wanted,'Numeric reduction bit order differs'
                    if stage==2:last.append(value)
                    reduction_count+=1
    valid=[physical_state_bit(routes,bridge,context,f'valid_reg[{stage}]')[0] for stage in range(4)]
    assert product_count==4096 and reduction_count==3936 and len(last)==608
    port=lambda ctx,name,width,direction:route_word(routes,bridge,ctx,name,width,direction=direction)
    out_ready=port(context,'out_ready',1,'input');in_ready=port(context,'in_ready',1,'output')
    pending,_=physical_state_bit(routes,bridge,'','command_pending_reg')
    bridge.check([port(context,'clk',1,'input'),port(context,'rst_n',1,'input')],
        [bridge.boolean('top.clk'),rst],label='numeric_array_common_core_clock_and_reset')
    bridge.check([port(context,'in_valid',1,'input'),port(context,'out_valid',1,'output'),in_ready],
        [pending,valid[3],z3.Or(z3.Not(valid[3]),out_ready)],label='numeric_array_pending_valid_and_global_stall_bindings')
    bridge.check([port(context,'out_sums',608,'output')],[bridge.pack(last)],label='all32_actual_numeric_output_word_bindings')
    # State roles must coincide with those in the metadata and memory contracts.
    def core_word(prefix,width):
        return bridge.pack([physical_state_bit(routes,bridge,'',f'{prefix}_reg[{bit}]')[0] for bit in range(width)])
    wb_valid,_=physical_state_bit(routes,bridge,'','writeback_valid_reg')
    recent_valid,_=physical_state_bit(routes,bridge,'','recent_valid_reg')
    read_slot=port('','read_output',4,'input');read_valid=port('','read_valid',1,'input')
    current=z3.And(wb_valid,read_slot==core_word('writeback_slot',4))
    recent=z3.And(recent_valid,read_slot==core_word('done_output',4))
    bridge.check([out_ready],[z3.Not(z3.And(read_valid,z3.Not(current),z3.Not(recent)))],
        label='numeric_output_acceptance_uses_actual_memory_service_backpressure')
    from prove_tri_oracle_accumulator_metadata import register_layout
    roles=[]
    for role_context,instance in register_layout():
        _,q=physical_state_bit(routes,bridge,role_context,instance)
        roles.append(dict(context=role_context,instance=instance,q=q))
    assert len(roles)==41 and len({(r['context'],r['instance']) for r in roles})==41
    return dict(queries=bridge.checks,physical_product_bits=product_count,physical_reduction_bits=reduction_count,
        physical_valid_bits=4,array_module_sha256=digest,former_output_sum_cut_removed=True,
        physical_metadata_role_bits=41,metadata_role_bindings=roles,
        arithmetic_transfer_scope='Unchanged exact bodies of independently qualified product/reduction/valid local next-state proofs.')


def semantic_controls():
    """Counterexamples target the composition model, not edited circuit bodies."""
    def wrong_lanes(old,valid,ready,incoming,rst):
        return pipeline_step(old,valid,ready,dict(incoming,products=list(reversed(incoming['products']))),rst)
    def wrong_ready(old,valid,ready,incoming,rst):return pipeline_step(old,valid,z3.BoolVal(True),incoming,rst)
    def wrong_sign(old,valid,ready,incoming,rst):
        new,available=pipeline_step(old,valid,ready,incoming,rst)
        value=z3.ZeroExt(1,old['data'][0][0])+z3.ZeroExt(1,old['data'][0][1])
        new['data'][1][0]=z3.If(z3.And(available,old['valid'][0]),value,old['data'][1][0]);return new,available
    def wrong_slot(old,valid,ready,incoming,rst):return pipeline_step(old,valid,ready,dict(incoming,slot=old['slot'][0]),rst)
    def wrong_accumulate(old,valid,ready,incoming,rst):return pipeline_step(old,valid,ready,dict(incoming,accumulate=z3.Not(incoming['accumulate'])),rst)
    rejected=[]
    for name,advance,label in [('wrong_product_lane_order',wrong_lanes,'pipeline_stage0_history_successor'),
        ('advances_during_stall',wrong_ready,'pipeline_ready_matches_available_output'),
        ('negative_product_zero_extended',wrong_sign,'pipeline_stage1_history_successor'),
        ('pending_slot_displaced',wrong_slot,'certified_metadata_projection_matches_numeric_and_writeback_successors'),
        ('pending_accumulation_inverted',wrong_accumulate,'certified_metadata_projection_matches_numeric_and_writeback_successors')]:
        _,conditions,proposition=next(q for q in proof_obligations(advance) if q[0]==label)
        solver=z3.SolverFor('QF_BV');solver.set(timeout=120000,max_memory=1024);solver.add(*conditions,z3.Not(proposition))
        if name=='negative_product_zero_extended':solver.add(z3.Bool('numeric.rst_n'),z3.Bool('numeric.out_ready'),
            z3.Bool('numeric.valid0'),z3.BitVec('numeric.data0.0',16)==0xffff,z3.BitVec('numeric.data0.1',16)==0)
        if name.startswith('pending_'):solver.add(z3.Bool('numeric.rst_n'),z3.Bool('numeric.in_valid'),z3.Bool('numeric.out_ready'))
        if name=='pending_slot_displaced':solver.add(z3.BitVec('numeric.input_slot',4)==2,z3.BitVec('numeric.slot0',4)==1)
        assert solver.check()==z3.sat,('Numeric composition fault lacks counterexample',name)
        rejected.append(dict(control=name,query=label,result='sat',fault_scope='composition_model_not_actual_body_mutation'))
    return rejected


def verify(output,*,prototype=False):
    from prove_tri_oracle_tile_command_routes import command_route_environment
    from prove_tri_oracle_command_admission import AdmissionRoutes
    from prove_tri_oracle_packaged_accumulators import compiled_memory_library,local_source_paths
    from prove_tri_oracle_accumulator_metadata import metadata_environment
    from prove_tri_oracle_packaged_products import ROOT,memory_guard
    from prove_tri_oracle_head_score_frontend import revalidate_evidence
    assert not Path('/.dockerenv').exists() and output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);started=time.monotonic();pins={}
    def pin(path,wanted=None):
        with path.open('rb') as f:actual=file_digest(f,'sha256').hexdigest()
        assert wanted is None or actual==wanted,('Changed numeric history input',path)
        assert pins.setdefault(str(path.relative_to(ROOT)),actual)==actual
        return path
    certificates={kind:load_contract(kind,pin(ROOT/name,wanted).read_bytes()) for kind,(name,wanted) in CONTRACT_ROOTS.items()}
    for record in certificates.values():
        for name,wanted in record['evidence_sha256'].items():pin(ROOT/name,wanted)
    for name,wanted in EXTRA_ROUTE_INPUTS.items():pin(ROOT/name,wanted)
    assert len({record['candidate_sha256'] for record in certificates.values()})==1,'Numeric contracts use different candidates'
    predecessor={c['absolute_context']:c for c in certificates['service']['core_modules']}
    metadata={c['absolute_context']:c for c in certificates['metadata']['core_modules']}
    sources=local_source_paths((Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_numeric_pipeline_history_logic.py'),ROOT/'syn')
    for path in sources:pin(path)
    expected=expected_evidence_inventory(ROOT,certificates,sources)
    cores=[]
    with command_route_environment(pin) as original:
        assert original['candidate_sha256']==certificates['service']['candidate_sha256']
        original['memory_bus_library']=compiled_memory_library(original);source=original['routes']
        original['reset_routes']=AdmissionRoutes(source.body,source.masters,source.library,source.states,source.contexts[''][0],guard=source.guard)
        original['reset_routes'].modules=source.modules
        for bank in range(1 if prototype else 5):
            for core in range(1 if prototype else 4):
                path=original['paths']['owner']+f'/fabric/clusters[{bank}].unit/selected_bank{bank}.block_instance/source_cluster/implementation/cores[{core}]/compute'
                environment=metadata_environment(original,path)
                for prior in (predecessor[path],metadata[path]):
                    assert environment['core_module_sha256']==prior['core_module_sha256'] and environment['array_module_sha256']==prior['array_module_sha256'],'Numeric core predecessor binding differs'
                binding=bind_pipeline(environment,certificates)
                cores.append(dict(bank=bank,core=core,absolute_context=path,module=environment['master'],
                    core_module_sha256=environment['core_module_sha256'],array_module=environment['array_master'],**binding,
                    hierarchy_bindings=environment['hierarchy_bindings']))
                print('NUMERIC_PIPELINE_CORE_BOUND',bank,core,8036,flush=True)
                del environment;gc.collect()
    history=prove_history();controls=semantic_controls()
    loaded={Path(m.__file__).resolve() for m in sys.modules.values() if getattr(m,'__file__',None) and Path(m.__file__).resolve().parent==ROOT/'syn'}
    assert loaded<=set(sources),('Unpinned numeric source',loaded-set(sources))
    assert pins==expected,'Numeric evidence inventory differs from rooted inputs and current source closure'
    revalidate_evidence(pins,ROOT)
    result=dict(state='numeric_pipeline_binding_prototype' if prototype else 'mapped_numeric_pipeline_and_ordered_memory_fold_verified_relative_to_operand_and_memory_contracts',
        candidate_sha256=certificates['service']['candidate_sha256'],core_count=len(cores),cores=cores,history_theorem=history,
        semantic_counterexamples=controls,evidence_sha256=pins,local_source_files=len(sources),all_loaded_local_sources_pinned=True,
        input_memory_contents_verified=False,complete_tensor_scores_verified=False,task_accuracy_verified=False,
        physical_timing_verified=False,complete_paper_architecture_verified=False,advance_to_clock_distribution_or_routing_allowed=False,
        elapsed_seconds=time.monotonic()-started,peak_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        scope='Current mapped array operand/mask acceptance through four locally chosen arithmetic stages into32-bit output-memory partial sums. Exact published local next-state contracts, freshly checked state/interface/body bindings, universal stage history and exhaustive-control ordered memory-fold induction are composed. Input-memory content/policy provenance, full tensor prediction, initialization-X/analog timing, trained accuracy and paper matching remain unqualified.')
    with output.open('x') as f:f.write(json.dumps(result,indent=2)+'\n')
    print(result['state'],result['core_count'],result['elapsed_seconds'],flush=True)


if __name__=='__main__':
    import argparse
    resource.setrlimit(resource.RLIMIT_AS,(3*2**30,3*2**30))
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);parser.add_argument('--prototype',action='store_true')
    args=parser.parse_args();verify(args.output,prototype=args.prototype)
