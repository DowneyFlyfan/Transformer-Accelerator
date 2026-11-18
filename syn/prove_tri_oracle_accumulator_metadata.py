"""Check mapped accepted-command identity through the compute/writeback pipeline.

The read-or-forward lemma assumes an explicit synchronous memory contract.
It does not certify the compiler model, complete memory histories or accuracy.
"""
if not __debug__:raise RuntimeError('Metadata verification requires assertions')
from pathlib import Path
from hashlib import sha256,file_digest
import gc,json,resource,sys,time
import z3
from prove_tri_oracle_head_intensity import WordBridge
from prove_tri_oracle_packaged_accumulators import (
    AccumulatorRoutes,core_environment,compiled_memory_library,primary_models,local_source_paths)


PREDECESSOR_SHA256='243e63667471d75d1ce2282cad14553b79ccf130cd87877742100985de17e8e1'


def qualified_predecessor(content):
    """The published accumulator summary, not a replacement self-signed root."""
    assert sha256(content).hexdigest()==PREDECESSOR_SHA256,'Metadata predecessor digest differs from published8ae24fe'
    result=json.loads(content)
    assert result['state']=='mapped_accumulator_local_arithmetic_and_capture_qualified'
    assert result['core_count']==result['array_count']==20 and result['memory_words']==640
    return result


def queue_next(old,cmd_valid,cmd_slot,cmd_accumulate,out_ready,cmd_ready,rst_n):
    """Seven-stage elastic reference: pending, array0..3, writeback, done."""
    assert set(old)=={'valid','slot','accumulate'}
    assert len(old['valid'])==len(old['slot'])==7 and len(old['accumulate'])==6
    valid=old['valid'];slot=old['slot'];accum=old['accumulate']
    ready=z3.Or(z3.Not(valid[4]),out_ready)
    accept=z3.And(cmd_valid,cmd_ready,ready)
    transfer=z3.And(valid[4],out_ready)
    new_valid=[z3.If(ready,z3.And(cmd_valid,cmd_ready),valid[0])]
    new_valid += [z3.If(ready,valid[i-1],valid[i]) for i in range(1,5)]
    new_valid += [transfer,valid[5]]
    new_slot=[z3.If(accept,cmd_slot,slot[0])]
    new_slot += [z3.If(ready,slot[i-1],slot[i]) for i in range(1,5)]
    new_slot += [z3.If(transfer,slot[4],slot[5]),z3.If(valid[5],slot[5],slot[6])]
    new_accum=[z3.If(accept,cmd_accumulate,accum[0])]
    new_accum += [z3.If(ready,accum[i-1],accum[i]) for i in range(1,5)]
    new_accum += [z3.If(transfer,accum[4],accum[5])]
    return dict(valid=[z3.And(rst_n,value) for value in new_valid],
        slot=[z3.If(rst_n,value,z3.BitVecVal(0,4)) for value in new_slot],
        accumulate=[z3.And(rst_n,value) for value in new_accum])


def prefetch_base(memory,slot,write_valid,write_slot,write_data):
    """Conditional on an enabled, settled read of memory[slot] this cycle."""
    assert memory.sort()==z3.ArraySort(z3.BitVecSort(4),z3.BitVecSort(32))
    assert slot.size()==write_slot.size()==4 and write_data.size()==32 and z3.is_bool(write_valid)
    updated=z3.If(write_valid,z3.Store(memory,write_slot,write_data),memory)
    collision=z3.And(write_valid,write_slot==slot)
    return z3.If(collision,write_data,z3.Select(memory,slot)),updated


def register_layout():
    core=['command_pending_reg','read_accumulate_reg','writeback_valid_reg','writeback_accumulate_reg','done_valid_reg']
    core += [f'{prefix}_reg[{bit}]' for prefix in ('read_slot','writeback_slot','done_output') for bit in range(4)]
    core += [f'slot_pipe_reg[{stage}][{bit}]' for stage in range(4) for bit in range(4)]
    core += [f'accumulate_pipe_reg[{stage}]' for stage in range(4)]
    return [('',name) for name in core]+[('compute',f'valid_reg[{bit}]') for bit in range(4)]


def metadata_environment(original,path,*,overrides=None):
    from prove_tri_oracle_command_admission import parse_admission_module
    from link_tri_oracle_indexed_whole_chip import signature
    from prove_tri_oracle_packaged_products import memory_guard
    base=core_environment(original,path);source=original['routes']
    root=base['master'];root_module=source.module(root);array=root_module.cells['compute'][0]
    changed=overrides or {};assert set(changed)<={root,array},'Unexpected metadata body override'
    for master,body in changed.items():assert signature(body)==signature(source.body(master)),'Metadata fault changed port signature'
    original_array=parse_admission_module(source.body(array))
    aliases=set(base['reset_inputs'])
    # Some physical reset ports guard acceptance without driving any selected
    # register's reset pin. Names only identify candidates; the hierarchy
    # equality query below establishes each candidate's reset semantics.
    import re
    aliases.update(name for name,direction in root_module.directions.items()
                   if direction=='input' and root_module.declared[name] is None and re.fullmatch(r'p\d+',name))
    for context,instance in register_layout():
        module=original_array if context else root_module
        _,pins=module.cells[instance];reset,=module.expression(pins['CDN'])
        if context:
            assert module.directions.get(reset)=='input' and module.declared[reset] is None,'Metadata array reset must be a scalar input'
            reset,=root_module.expression(root_module.cells['compute'][1][reset])
        assert root_module.directions.get(reset)=='input' and root_module.declared[reset] is None,'Metadata reset must resolve to a core interface input'
        aliases.add(reset)
    ancestry=original['reset_routes'];absolute=ancestry.walk(path);binding=WordBridge(ancestry.graph)
    reference,=binding.convert([ancestry.trace(absolute,'rst_n')])
    binding.check(binding.convert([ancestry.trace(absolute,net) for net in sorted(aliases)]),
        [reference]*len(aliases),label='metadata_additional_reset_aliases_equal_core_reset')
    getter=lambda master:changed[master] if master in changed else source.body(master)
    routes=AccumulatorRoutes(getter,source.masters,source.library|original['memory_bus_library'],source.states,root,
        memory_master='TS6N28HPCPSVTA16X128M2F',guard=lambda:memory_guard(8.5))
    child=routes.child('','compute');ports=routes.ports(array)
    assert {name for name,direction in ports.directions.items() if direction=='output'}=={'in_ready','out_valid','out_sums'}
    routes.offpath[child]=set(ports.net_bits('out_sums'))
    kinds={routes.module(routes.contexts[context][0]).cells[name][0] for context,name in register_layout()}
    cache=original.setdefault('primary_models_by_master_set',{});key=frozenset(kinds)
    if key not in cache:cache[key]=primary_models(original,kinds)
    result=dict(routes=routes,master=root,array_master=array,primary=cache[key],reset_inputs=sorted(aliases),
        hierarchy_bindings=base['hierarchy_bindings']+binding.checks,absolute_context=path,
        core_module_sha256=sha256(getter(root)).hexdigest(),array_module_sha256=sha256(getter(array)).hexdigest())
    del original_array,base
    return result


def prove_metadata(environment,*,only_query=None,activation=()):
    from prove_tri_oracle_layer_row_epoch import physical_register
    from prove_tri_oracle_tile_command_routes import route_word
    from prove_tri_oracle_tile_geometry import geometry_check
    routes=environment['routes'];bridge=WordBridge(routes.graph);records={}
    bridge.variables.update({f'top.{name}':bridge.boolean('top.rst_n') for name in environment['reset_inputs']})
    for context,name in register_layout():
        record=physical_register(routes,bridge,context,name,environment['primary'])
        assert record['reset_value']==0,'Metadata reset value differs'
        record['next']=z3.If(record['reset'],z3.BoolVal(False),record['data'])
        records[context,name]=record
    assert len(records)==41
    def bit(name,key='old',context=''):return records[context,name][key]
    def word(prefix,key='old'):
        return bridge.pack([bit(f'{prefix}_reg[{index}]',key) for index in range(4)])
    def states(key):
        return dict(valid=[bit('command_pending_reg',key)]+[bit(f'valid_reg[{i}]',key,'compute') for i in range(4)]+
                         [bit('writeback_valid_reg',key),bit('done_valid_reg',key)],
            slot=[word('read_slot',key)]+[bridge.pack([bit(f'slot_pipe_reg[{stage}][{i}]',key) for i in range(4)]) for stage in range(4)]+
                 [word('writeback_slot',key),word('done_output',key)],
            accumulate=[bit('read_accumulate_reg',key)]+[bit(f'accumulate_pipe_reg[{i}]',key) for i in range(4)]+
                       [bit('writeback_accumulate_reg',key)])
    old=states('old');actual=states('next');rst=bridge.boolean('top.rst_n')
    port=lambda context,name,width,direction:route_word(routes,bridge,context,name,width,direction=direction)
    cmd_valid=port('','cmd_valid',1,'input');cmd_slot=port('','cmd_output',4,'input')
    cmd_accum=port('','cmd_accumulate',1,'input');cmd_ready=port('','cmd_ready',1,'output')
    load=port('','load_valid',1,'input');compute_grant=port('input_owner','compute_enabled',1,'output')
    out_ready=port('compute','out_ready',1,'input');in_ready=port('compute','in_ready',1,'output')
    if callable(activation):activation=activation(bridge,old,out_ready,in_ready)
    def check(observed,wanted,label,conditions=()):
        routes.guard();result=geometry_check(bridge,observed,wanted,label=label,conditions=conditions,
            only_query=only_query,activation=activation);routes.guard();return result
    check([record['clock'] for record in records.values()],[bridge.boolean('top.clk')]*41,'all41_metadata_register_clocks')
    check([record['reset'] for record in records.values()],[z3.Not(rst)]*41,'all41_metadata_register_reset_bindings')
    check([port('compute','clk',1,'input'),port('compute','rst_n',1,'input')],
        [bridge.boolean('top.clk'),rst],'array_to_core_metadata_clock_reset_bindings')
    ready=z3.Or(z3.Not(old['valid'][4]),out_ready)
    check([in_ready,z3.Implies(cmd_ready,in_ready),z3.Implies(cmd_ready,compute_grant),
           z3.Implies(z3.And(compute_grant,z3.Not(load)),cmd_ready==in_ready)],
          [ready,z3.BoolVal(True),z3.BoolVal(True),z3.BoolVal(True)],'actual_array_ready_and_command_backpressure')
    check([port('compute','in_valid',1,'input'),port('compute','out_valid',1,'output'),port('','done_valid',1,'output'),port('','done_output',4,'output')],
        [old['valid'][0],old['valid'][4],old['valid'][6],old['slot'][6]],'actual_metadata_valid_and_completion_port_bindings')
    expected=queue_next(old,cmd_valid,cmd_slot,cmd_accum,out_ready,cmd_ready,rst)
    for field in ('valid','slot','accumulate'):
        check(actual[field],expected[field],f'actual_seven_stage_{field}_queue_next_states')
    accepted=z3.And(old['valid'][4],out_ready)
    collision=z3.And(old['valid'][5],old['slot'][5]==old['slot'][4])
    module=routes.module(environment['master'])
    for bank,instance in enumerate(routes.memory['instances']):
        _,pins=module.cells[instance]
        def physical(pin):
            nets=module.expression(pins[pin]);values=bridge.convert([routes.trace('',net) for net in reversed(nets)])
            return values[0] if len(values)==1 else bridge.pack(values)
        check([physical('AA'),physical('WEB')],[old['slot'][5],z3.Not(z3.And(rst,old['valid'][5]))],
            f'physical_memory{bank}_writeback_metadata_ownership')
        check([physical('AB'),physical('REB')],[old['slot'][4],collision],
            f'physical_memory{bank}_accepted_array_prefetch_metadata_ownership',[rst,accepted])
    witnesses=[]
    if only_query is None:
        for full in (False,True):
            for enabled in (False,True):
                for admitted in ((False,) if full and not enabled else (False,True)):
                    solver=z3.SolverFor('QF_BV');solver.set(timeout=120000,max_memory=1024)
                    solver.add(rst,old['valid'][4]==full,out_ready==enabled,cmd_ready==admitted,cmd_valid)
                    if admitted:solver.add(z3.Not(load),compute_grant)
                    assert solver.check()==z3.sat,'Missing metadata admission/stall/bubble event-state witness'
                    witnesses.append(dict(array_output_valid=full,array_output_ready=enabled,command_ready=admitted,result='sat'))
    assert only_query is None or len(bridge.checks)==1,'Targeted metadata query absent'
    return dict(queries=bridge.checks,local_event_state_witnesses=witnesses,selected_register_bits=41,
        bridge=bridge,old=old,records=records,graph_nodes=len(routes.graph.nodes),
        admission_dependencies=sorted(routes.graph.dependencies(routes.trace('','cmd_ready'))))


def rejection_controls(original,path):
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_intensity import require_counterexample
    from prove_tri_oracle_tile_command_routes import route_word
    base=metadata_environment(original,path);routes=base['routes'];root=base['master'];array=base['array_master']
    controls=[]
    def add(label,master,instance,pins,query,case):
        body=routes.body(master)
        for pin,value in pins.items():body=replace_instance_pin(body,instance,pin,value.encode())
        controls.append((label,{master:body},query,case))
    def force(context,instance,value):
        _,pins=routes.module(routes.contexts[context][0]).cells[instance]
        return dict(D=value,**({'E':"1'b1"} if 'E' in pins else {}),**({'SE':"1'b0"} if 'SE' in pins else {}))
    add('accepted_pending_valid_lost',root,'command_pending_reg',force('','command_pending_reg',"1'b0"),
        'actual_seven_stage_valid_queue_next_states','admit')
    add('accepted_slot_bit_lost',root,'read_slot_reg[0]',force('','read_slot_reg[0]',"1'b0"),
        'actual_seven_stage_slot_queue_next_states','admit')
    add('array_slot_advances_during_stall',root,'slot_pipe_reg[3][0]',{'E':"1'b1"},
        'actual_seven_stage_slot_queue_next_states','stall')
    add('array_accumulation_flag_lost',root,'accumulate_pipe_reg[2]',force('','accumulate_pipe_reg[2]',"1'b0"),
        'actual_seven_stage_accumulate_queue_next_states','advance')
    add('array_valid_stage_lost',array,'valid_reg[2]',force('compute','valid_reg[2]',"1'b0"),
        'actual_seven_stage_valid_queue_next_states','advance')
    add('array_output_backpressure_disconnected',root,'compute',{'out_ready':"1'b1"},
        'actual_seven_stage_valid_queue_next_states','external_miss')
    add('completion_slot_bit_lost',root,'done_output_reg[0]',force('','done_output_reg[0]',"1'b0"),
        'actual_seven_stage_slot_queue_next_states','complete')
    add('prefetch_uses_wrong_command_slot',root,'outputs[0]',{'AB':"4'b0"},
        'physical_memory0_accepted_array_prefetch_metadata_ownership','prefetch')
    add('pending_reset_disconnected',root,'command_pending_reg',{'CDN':"1'b1"},
        'all41_metadata_register_reset_bindings','reset')
    rejected=[]
    del base;gc.collect()
    for label,overrides,query,case in controls:
        environment=metadata_environment(original,path,overrides=overrides);changed=environment['routes']
        def activate(bridge,old,out_ready,in_ready):
            rst=bridge.boolean('top.rst_n')
            if case=='reset':return [z3.Not(rst)]
            conditions=[rst]
            port=lambda name,width:route_word(changed,bridge,'',name,width,direction='input')
            if case=='admit':
                conditions += [port('cmd_valid',1),route_word(changed,bridge,'','cmd_ready',1,direction='output'),port('cmd_output',4)==1]
            elif case=='stall':
                conditions += [old['valid'][4],z3.Not(out_ready),old['slot'][4]==0,old['slot'][3]==1]
            elif case=='advance':
                conditions += [in_ready,old['valid'][2],old['accumulate'][2]]
            elif case=='external_miss':
                module=changed.module(environment['master']);_,pins=module.cells['recent_valid_reg'];q,=module.expression(pins['Q'])
                recent,=bridge.convert([changed.trace('',q)])
                conditions += [old['valid'][4],port('read_valid',1),z3.Not(old['valid'][5]),z3.Not(recent)]
            elif case=='complete':conditions += [old['valid'][5],old['slot'][5]==1]
            elif case=='prefetch':conditions += [old['valid'][4],out_ready,old['slot'][4]==1]
            else:raise AssertionError('Unknown metadata fault activation')
            return conditions
        try:prove_metadata(environment,only_query=query,activation=activate)
        except AssertionError as error:
            require_counterexample(error,expected_query=query)
            rejected.append(dict(control=label,query=query,result='sat',activation=case,
                altered_modules_sha256={master:sha256(body).hexdigest() for master,body in overrides.items()}))
            print('METADATA_CORRUPTION_REJECTED',label,query,flush=True)
        else:raise AssertionError(('Metadata corruption accepted',label))
        del environment;gc.collect()
    body=replace_instance_pin(original['routes'].body(array),'valid_reg[3]','CP',b"1'b0")
    try:prove_metadata(metadata_environment(original,path,overrides={array:body}))
    except AssertionError as error:
        assert str(error)=='Epoch register clock differs',('Unrelated metadata clock rejection',str(error))
        rejected.append(dict(control='array_metadata_wrong_clock',rejection=str(error),altered_modules_sha256={array:sha256(body).hexdigest()}))
    else:raise AssertionError('Metadata wrong clock accepted')
    assert len(rejected)==10 and len({tuple(sorted(item['altered_modules_sha256'].items())) for item in rejected})==10
    return rejected


def conditional_prefetch_proof():
    memory=z3.Array('memory',z3.BitVecSort(4),z3.BitVecSort(32))
    slot=z3.BitVec('accepted_slot',4);write_slot=z3.BitVec('write_slot',4)
    write_data=z3.BitVec('write_data',32);valid=z3.Bool('write_valid')
    actual,updated=prefetch_base(memory,slot,valid,write_slot,write_data)
    solver=z3.SolverFor('QF_AUFBV');solver.set(timeout=120000,max_memory=1024)
    solver.add(actual!=z3.Select(updated,slot));start=time.monotonic();status=solver.check()
    assert status==z3.unsat,('Conditional read-or-forward lemma not proved',str(status))
    return dict(result='unsat',seconds=time.monotonic()-start,word_bits=32,address_bits=4,
        assumption='Enabled settled noncolliding synchronous read yields the pre-edge memory word; writes commit atomically. Compiler-model timing and unknown-state behavior are NOT certified here.',
        compiler_memory_contract_verified=False)


def verify(output,*,prototype=False):
    from prove_tri_oracle_tile_command_routes import command_route_environment
    from prove_tri_oracle_command_admission import AdmissionRoutes
    from prove_tri_oracle_packaged_products import ROOT,memory_guard
    from prove_tri_oracle_head_score_frontend import revalidate_evidence
    assert not Path('/.dockerenv').exists() and output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);start=time.monotonic();pins={}
    def pin(path,wanted=None):
        with path.open('rb') as stream:digest=file_digest(stream,'sha256').hexdigest()
        assert wanted is None or digest==wanted,('Changed metadata input',path)
        assert pins.setdefault(str(path.relative_to(ROOT)),digest)==digest
        return path
    prior=qualified_predecessor(pin(ROOT/'records/tri_oracle_packaged_accumulator_next_states.json',PREDECESSOR_SHA256).read_bytes())
    for name,digest in prior['evidence_sha256'].items():pin(ROOT/name,digest)
    detailed_name,=(name for name in prior['evidence_sha256'] if name.endswith('/all_core_accumulation_review_fixed.json'))
    detail=json.loads((ROOT/detailed_name).read_text())
    for name,digest in detail['evidence_sha256'].items():pin(ROOT/name,digest)
    local_sources=local_source_paths((Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_accumulator_metadata_logic.py'),ROOT/'syn')
    for path in local_sources:pin(path)
    predecessor={core['absolute_context']:core for core in detail['cores']}
    cores=[];corruptions=[]
    with command_route_environment(pin) as original:
        assert original['candidate_sha256']==prior['candidate_sha256']
        original['memory_bus_library']=compiled_memory_library(original);source=original['routes']
        original['reset_routes']=AdmissionRoutes(source.body,source.masters,source.library,source.states,source.contexts[''][0],guard=source.guard)
        original['reset_routes'].modules=source.modules
        for bank in range(1 if prototype else 5):
            for core in range(1 if prototype else 4):
                path=original['paths']['owner']+f'/fabric/clusters[{bank}].unit/selected_bank{bank}.block_instance/source_cluster/implementation/cores[{core}]/compute'
                environment=metadata_environment(original,path);previous=predecessor[path]
                assert environment['core_module_sha256']==previous['module_sha256'] and environment['array_module_sha256']==previous['array_module_sha256'],'Metadata predecessor body binding differs'
                result=prove_metadata(environment)
                cores.append(dict(bank=bank,core=core,absolute_context=path,module=environment['master'],core_module_sha256=environment['core_module_sha256'],
                    array_module=environment['array_master'],array_module_sha256=environment['array_module_sha256'],queries=result['queries'],
                    hierarchy_bindings=environment['hierarchy_bindings'],local_event_state_witnesses=result['local_event_state_witnesses'],
                    admission_dependencies=result['admission_dependencies'],actual_reset_inputs=environment['reset_inputs'],physical_register_bits=41))
                del environment,result;gc.collect()
        if not prototype:corruptions=rejection_controls(original,cores[0]['absolute_context'])
    lemma=conditional_prefetch_proof()
    loaded={Path(module.__file__).resolve() for module in sys.modules.values() if getattr(module,'__file__',None)
            and Path(module.__file__).resolve().parent==ROOT/'syn'}
    assert loaded<=set(local_sources),('Unpinned metadata source',loaded-set(local_sources))
    revalidate_evidence(pins,ROOT)
    report=dict(state='mapped_metadata_prototype' if prototype else 'mapped_accepted_command_metadata_trace_refinement_verified',
        candidate_sha256=prior['candidate_sha256'],cores=cores,core_count=len(cores),conditional_prefetch_lemma=lemma,
        rejected_mutations=corruptions,metadata_trace_refinement_verified=not prototype,
        local_source_files=len(local_sources),all_loaded_local_sources_pinned=True,
        equivalence_queries=sum(len(core['queries'])+len(core['hierarchy_bindings']) for core in cores),
        evidence_sha256=pins,wall_seconds=time.monotonic()-start,peak_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        compiler_memory_contract_verified=False,complete_memory_history_verified=False,complete_tensor_scores_verified=False,
        complete_paper_architecture_verified=False,task_accuracy_verified=False,physical_timing_verified=False,
        advance_to_clock_distribution_or_routing_allowed=False,
        scope=f'Actual {len(cores)} cores: common-reset and next-state refinement of41physical metadata/valid bits to a seven-stage elastic queue. Accepted commands are actual cmd_valid/cmd_ready handshakes; ready must respect array backpressure and compute grant, and a granted idle-load interface admits an available array. Input-owner grant/load policy is an explicit upstream boundary. Array ready/valid are traced through its actual four registers; only sum-data ports remain cut. All states and external input assignments are quantified, proving reset-epoch metadata trace equivalence by reset basis and successor equality. SAT mode witnesses are local assignments only. Read-or-forward lemma assumes an enabled settled synchronous memory read; the compiler contract, external-read service, data/command alignment, complete memory/tensor histories, accuracy and physical timing remain separate.')
    with output.open('x') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    print(report['state'],len(cores),report['wall_seconds'],flush=True)


if __name__=='__main__':
    import argparse
    resource.setrlimit(resource.RLIMIT_AS,(3*2**30,3*2**30))
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);parser.add_argument('--prototype',action='store_true')
    args=parser.parse_args();verify(args.output,prototype=args.prototype)
