"""Input-word snapshot provenance under explicit normal-operation memory rules.

Compiler timing and unknown-state behavior are outside the two-state contract.
Upstream residual-bank leases and truthful tile-reload acknowledgements need
their own parent-controller qualification before whole-chip input claims.
"""
if not __debug__:raise RuntimeError('Input memory history requires assertions')
from pathlib import Path
from hashlib import file_digest,sha256
import gc,json,resource,sys,time
import z3

NUMERIC_ROOT=('records/tri_oracle_numeric_pipeline_memory_history.json',
    '9136b47883d63d188fc48132a427880236b296ab8577456ca5b35e6c5b92757d')
MEMORY_CONTRACT='Known binary inputs and initialized requested words; normal power/test configuration and stable common rising clock. Enabled reads settle Q to the pre-edge selected word; enabled writes atomically update unmasked bits and retain Q; disabled ports retain memory and Q. Foundry timing, initialization-X propagation and injected faults are outside this contract.'
SNAPSHOT_SCOPE='One arbitrary128-bit weight or mask bank and both64-bit activation banks; instantiated by checked routes for every physical bank.'
RESULT_SCOPE='Actual400 compiled input macros and980 physical controller/metadata roles across20 numeric-root-matched cores. Weight/mask byte order, row masks, load/error guards, admission/ownership transitions and pending read-snapshot history are conditional on the stated normal binary synchronous memory contract. The actual parent selects activation bank0, whose reset/next-state invariant excludes interference from bank1 residual clients. Truthful reload acknowledgement and correct task/tile data epochs, initialized-content provenance, compiler timing/X behavior, full tensor prediction and paper matching remain unqualified. Existing numeric proofs are composed at their original operand boundary, not reexecuted.'


def merge_pinned_inputs(*inventories):
    result={}
    for inventory in inventories:
        for name,digest in inventory.items():
            assert result.setdefault(name,digest)==digest,('Conflicting pinned input',name)
    return result


def memory_step(memory,q,ce_n,we_n,address,data,bit_mask=None):
    assert z3.is_bool(ce_n) and z3.is_bool(we_n)
    assert memory.sort()==z3.ArraySort(address.sort(),data.sort()) and q.size()==data.size()
    if bit_mask is None:bit_mask=z3.BitVecVal(0,data.size())
    assert bit_mask.size()==data.size()
    read=z3.And(z3.Not(ce_n),we_n);write=z3.And(z3.Not(ce_n),z3.Not(we_n))
    old=z3.Select(memory,address);merged=(old&bit_mask)|(data&~bit_mask)
    return dict(memory=z3.If(write,z3.Store(memory,address,merged),memory),
        q=z3.If(read,old,q),read=read,write=write)


def input_snapshot_operands(state):
    return [state['weights']['q'],state['masks']['q'],
        z3.If(state['bank'],state['inputs'][1]['q'],state['inputs'][0]['q'])]


def input_snapshot_invariant(state):
    return z3.Implies(state['pending'],z3.And(*[actual==state['snapshot'][name]
        for actual,name in zip(input_snapshot_operands(state),('weight','mask','activation'),strict=True)]))


def input_snapshot_step(old,request,ready,rst,*,advance_memory=memory_step):
    """A command reads at this edge; an older pending command consumes old Q."""
    def step(state,pins):
        return advance_memory(state['memory'],state['q'],**pins)
    selected=z3.If(request['bank'],z3.Select(old['inputs'][1]['memory'],request['activation_address']),
        z3.Select(old['inputs'][0]['memory'],request['activation_address']))
    references=dict(weight=z3.Select(old['weights']['memory'],request['weight_address']),
        mask=z3.Select(old['masks']['memory'],request['mask_address']),activation=selected)
    return dict(weights=step(old['weights'],request['weights']),masks=step(old['masks'],request['masks']),
        inputs=[step(state,pins) for state,pins in zip(old['inputs'],request['inputs'],strict=True)],
        pending=z3.And(rst,z3.If(ready,request['accepted'],old['pending'])),
        bank=z3.And(rst,z3.If(request['accepted'],request['bank'],old['bank'])),
        snapshot={name:z3.If(request['accepted'],value,old['snapshot'][name]) for name,value in references.items()})


def input_snapshot_obligations(advance=input_snapshot_step):
    def state(name,address_bits,data_bits):
        return dict(memory=z3.Array('input.'+name+'.memory',z3.BitVecSort(address_bits),z3.BitVecSort(data_bits)),
            q=z3.BitVec('input.'+name+'.q',data_bits))
    def pins(name,address_bits,data_bits,masked):
        result=dict(ce_n=z3.Bool('input.'+name+'.ce_n'),we_n=z3.Bool('input.'+name+'.we_n'),
            address=z3.BitVec('input.'+name+'.address',address_bits),data=z3.BitVec('input.'+name+'.data',data_bits))
        if masked:result['bit_mask']=z3.BitVec('input.'+name+'.bit_mask',data_bits)
        return result
    old=dict(weights=state('weights',5,128),masks=state('masks',5,128),
        inputs=[state(f'activation{bank}',9,64) for bank in range(2)],
        pending=z3.Bool('input.pending'),bank=z3.Bool('input.bank'),
        snapshot={name:z3.BitVec('input.snapshot.'+name,width) for name,width in [('weight',128),('mask',128),('activation',64)]})
    request=dict(accepted=z3.Bool('input.accepted'),bank=z3.Bool('input.request_bank'),
        weight_address=z3.BitVec('input.request_weight_address',5),mask_address=z3.BitVec('input.request_mask_address',5),
        activation_address=z3.BitVec('input.request_activation_address',9),
        weights=pins('weights',5,128,True),masks=pins('masks',5,128,True),
        inputs=[pins(f'activation{bank}',9,64,False) for bank in range(2)])
    ready=z3.Bool('input.ready');rst=z3.Bool('input.rst_n');accepted=request['accepted']
    read=lambda pin:z3.And(z3.Not(pin['ce_n']),pin['we_n'])
    selected=lambda values,bank:z3.If(bank,values[1],values[0])
    all_reads=[read(request[name]) for name in ('weights','masks')]
    activation_reads=[read(pin) for pin in request['inputs']]
    activation_addresses=[pin['address'] for pin in request['inputs']]
    # Each implication is discharged on the actual mapped ports by
    # prove_input_owner_and_bytes, subject to its explicit residual-client rule.
    admission=z3.Implies(accepted,z3.And(rst,ready))
    reads=z3.Implies(accepted,z3.And(*all_reads,selected(activation_reads,request['bank']),
        request['weights']['address']==request['weight_address'],request['masks']['address']==request['mask_address'],
        selected(activation_addresses,request['bank'])==request['activation_address']))
    stalled=z3.Implies(z3.And(old['pending'],z3.Not(ready)),
        z3.And(*[z3.Not(value) for value in all_reads],z3.Not(selected(activation_reads,old['bank']))))
    contract=(admission,reads,stalled)
    new=advance(old,request,ready,rst)
    references=[z3.Select(old['weights']['memory'],request['weight_address']),
        z3.Select(old['masks']['memory'],request['mask_address']),
        selected([z3.Select(bank['memory'],request['activation_address']) for bank in old['inputs']],request['bank'])]
    queries=[('input_reset_drops_pending_without_initializing_memory',(z3.Not(rst),),z3.And(z3.Not(new['pending']),z3.Not(new['bank']))),
        ('accepted_command_captures_preedge_memory_words',(*contract,accepted),z3.And(new['pending'],new['bank']==request['bank'],
            *[actual==wanted for actual,wanted in zip(input_snapshot_operands(new),references,strict=True)],
            *[new['snapshot'][name]==wanted for name,wanted in zip(('weight','mask','activation'),references,strict=True)])),
        ('pending_snapshot_history_successor',(*contract,input_snapshot_invariant(old)),input_snapshot_invariant(new)),
        ('parent_bank0_commands_preserve_bank0_selection_history',
            (z3.Not(old['bank']),z3.Not(request['bank'])),z3.Not(new['bank'])),
        ('processing_array_consumes_previous_snapshot_before_new_reads',
            (*contract,input_snapshot_invariant(old),old['pending'],ready,rst),
            z3.And(*[actual==old['snapshot'][name] for actual,name in zip(input_snapshot_operands(old),('weight','mask','activation'),strict=True)]))]
    return queries,dict(old=old,request=request,ready=ready,rst=rst,new=new)


def prove_input_snapshot_history():
    queries=[]
    for label,conditions,claim in input_snapshot_obligations()[0]:
        solver=z3.SolverFor('QF_AUFBV');solver.set(timeout=120000,max_memory=1024)
        solver.add(*conditions,z3.Not(claim));started=time.monotonic();result=solver.check()
        assert result==z3.unsat,('Input snapshot history not proved',label,str(result),
            str(solver.model()) if result==z3.sat else solver.reason_unknown())
        queries.append(dict(label=label,result='unsat',seconds=time.monotonic()-started))
    return dict(queries=queries,memory_contract=MEMORY_CONTRACT,
        snapshot_scope=SNAPSHOT_SCOPE,
        universal_compiler_memory_semantics_verified=False,upstream_residual_lease_contract_verified=False,
        truthful_reload_acknowledgement_verified=False)


def controller_layout():
    return [('input_owner',f'outstanding_reg[{bit}]') for bit in range(3)]+[
        ('input_owner','softmax_owns_input_reg'),('input_owner','activation_reload_required_reg'),
        ('grouped_input_banks','probability_owner_reg'),('','input_bank_reg'),('','load_error_reg')]


def input_controller_contexts(module):
    contexts=('input_owner','grouped_input_banks')
    assert all(name in module.cells for name in contexts),'Missing input-memory owner controller'
    residual='residual_input_bank_lease' in module.cells
    wanted={'residual_lease','residual_ce_n','residual_we_n','residual_addr','residual_d','residual_q'} if residual else set()
    assert {name for name in module.directions if name.startswith('residual_')}==wanted,'Residual controller interface differs'
    return contexts+(('residual_input_bank_lease',) if residual else ())


def input_environment(original,path,*,overrides=None):
    from tri_oracle_input_memory_routes import InputMemoryRoutes,compiled_input_bus_views
    from prove_tri_oracle_accumulator_metadata import metadata_environment,register_layout
    from prove_tri_oracle_packaged_accumulators import primary_models
    from prove_tri_oracle_packaged_products import memory_guard
    from prove_tri_oracle_head_intensity import WordBridge
    from link_tri_oracle_indexed_whole_chip import signature
    base=metadata_environment(original,path);source=original['routes'];root=base['master']
    module=source.module(root)
    assert module.declared['cmd_activation']==(9,0) and module.directions['cmd_activation']=='input','Input activation command shape differs'
    ancestry=original['reset_routes'];absolute=ancestry.walk(path);binding=WordBridge(ancestry.graph)
    actual_bank,=binding.convert([ancestry.trace(absolute,'cmd_activation[9]')])
    binding.check([actual_bank],[z3.BoolVal(False)],label='actual_parent_routes_matrix_activation_commands_to_bank0')
    base['hierarchy_bindings']=[*base['hierarchy_bindings'],*binding.checks]
    controller_contexts=input_controller_contexts(module)
    controllers={module.cells[name][0] for name in controller_contexts}
    changed=overrides or {};assert set(changed)<={root,base['array_master'],*controllers},'Unexpected input-memory override'
    for master,body in changed.items():assert signature(body)==signature(source.body(master)),'Input-memory fault changed interface'
    if 'input_bus_views' not in original:original['input_bus_views']=compiled_input_bus_views(original)
    getter=lambda master:changed[master] if master in changed else source.body(master)
    routes=InputMemoryRoutes(getter,source.masters,source.library|original['memory_bus_library']|original['input_bus_views'],
        source.states,root,memory_master='TS6N28HPCPSVTA16X128M2F',guard=lambda:memory_guard(8.5))
    for name in controller_contexts:
        child=routes.child('',name);del routes.offpath[child]
    array=routes.child('','compute');routes.offpath[array]=set(routes.ports(base['array_master']).net_bits('out_sums'))
    layout=register_layout()+controller_layout()
    kinds=frozenset(routes.module(routes.contexts[context][0]).cells[name][0] for context,name in layout)
    cache=original.setdefault('primary_models_by_master_set',{})
    if kinds not in cache:cache[kinds]=primary_models(original,kinds)
    return dict(base,routes=routes,primary=cache[kinds],register_layout=layout,
        residual_client_present='residual_input_bank_lease' in controller_contexts,
        parent_activation_bank_zero_bound=True,
        core_module_sha256=sha256(getter(root)).hexdigest(),
        controller_module_sha256={name:sha256(getter(module.cells[name][0])).hexdigest()
            for name in controller_contexts})


def prove_input_owner_and_bytes(environment,*,only_query=None,activation=()):
    from prove_tri_oracle_head_intensity import WordBridge
    from prove_tri_oracle_layer_row_epoch import physical_register
    from prove_tri_oracle_numeric_pipeline_history import physical_state_bit
    from prove_tri_oracle_tile_command_routes import route_word
    routes=environment['routes'];bridge=WordBridge(routes.graph);rst=bridge.boolean('top.rst_n')
    bridge.variables.update({f'top.{name}':rst for name in environment['reset_inputs']})
    records={}
    for context,name in environment['register_layout']:
        actual,_=physical_state_bit(routes,bridge,context,name)
        record=physical_register(routes,bridge,context,name,environment['primary'])
        assert z3.eq(actual,record['old']),'Input controller state identity differs'
        wanted=int((context,name)==('input_owner','activation_reload_required_reg'))
        assert record['reset_value']==wanted,'Input controller reset value differs'
        record['next']=z3.If(record['reset'],z3.BoolVal(bool(wanted)),record['data']);records[context,name]=record
    assert len(records)==49
    if callable(activation):activation=activation(bridge,routes,records)
    bit=lambda ctx,name,key='old':records[ctx,name][key]
    port=lambda ctx,name,width,direction:route_word(routes,bridge,ctx,name,width,direction=direction)
    def check(actual,wanted,label,conditions=()):
        from prove_tri_oracle_tile_geometry import geometry_check
        routes.guard();geometry_check(bridge,actual,wanted,label=label,conditions=conditions,
            only_query=only_query,activation=activation);routes.guard()
    check([r['clock'] for r in records.values()],[bridge.boolean('top.clk')]*49,'all49_input_controller_common_clocks')
    check([r['reset'] for r in records.values()],[z3.Not(rst)]*49,'all49_input_controller_common_reset_bindings')
    qword=lambda prefix,start,count,width:bridge.pack([bridge.boolean(f'physical_memory.{prefix}[{bank}].Q[{b}]')
        for bank in range(start,start+count) for b in range(width)])
    bank=bit('','input_bank_reg');selected=z3.If(bank,qword('inputs',1,1,64),qword('inputs',0,1,64))
    check([port('compute','operand_b',2048,'input')],[qword('weights',0,16,128)],'all2048_weight_bits_reach_correct_processing_lanes')
    check([port('compute','lane_enable',256,'input')],[qword('masks',0,2,128)],'all256_mask_bits_reach_correct_processing_lanes')
    check([port('compute','operand_a',2048,'input')],[z3.Concat(*([selected]*32))],'all32_activation_rows_repeat_selected_physical_bank')
    accepted=port('input_owner','compute_accepted',1,'input');done=port('input_owner','compute_done',1,'input')
    available=port('input_owner','softmax_configure',1,'output')
    request=port('input_owner','softmax_request',1,'input');start=port('input_owner','softmax_start',1,'input')
    end=port('input_owner','softmax_end',1,'input');wrote=port('input_owner','softmax_wrote_input',1,'input')
    load_ready=port('','load_ready',1,'output');enabled=port('input_owner','compute_enabled',1,'output')
    reload_ack=port('','activation_reloaded',1,'input');cmd_valid=port('','cmd_valid',1,'input');cmd_ready=port('','cmd_ready',1,'output')
    array_ready=port('compute','in_ready',1,'output');load_valid=port('','load_valid',1,'input')
    accepted_load=z3.And(load_valid,load_ready)
    native_request=port('grouped_input_banks','native_request',1,'input')
    probability_request=port('grouped_input_banks','probability_request',1,'input')
    probability_release=port('grouped_input_banks','probability_release',1,'input')
    probability_grant=port('grouped_input_banks','probability_grant',1,'output')
    def count(key):return bridge.pack([bit('input_owner',f'outstanding_reg[{b}]',key) for b in range(3)])
    owned=lambda key='old':bit('input_owner','softmax_owns_input_reg',key)
    probability=lambda key='old':bit('grouped_input_banks','probability_owner_reg',key)
    reload=lambda key='old':bit('input_owner','activation_reload_required_reg',key)
    def queue_valid(key):return [bit('','command_pending_reg',key)]+[bit('compute',f'valid_reg[{b}]',key) for b in range(4)]+[
        bit('','writeback_valid_reg',key),bit('','done_valid_reg',key)]
    def invariant(key):
        total=sum((z3.If(v,z3.BitVecVal(1,3),z3.BitVecVal(0,3)) for v in queue_valid(key)),z3.BitVecVal(0,3))
        return z3.And(count(key)==total,z3.Implies(owned(key),count(key)==0),z3.Implies(probability(key),owned(key)))
    check([load_ready,enabled,available,cmd_ready,accepted,done,port('compute','in_valid',1,'input')],
        [z3.And(rst,z3.Not(request),z3.Not(owned())),z3.And(load_ready,z3.Not(reload())),
         z3.And(rst,z3.Not(owned()),count('old')==0),z3.And(enabled,array_ready,z3.Not(accepted_load)),
         z3.And(rst,cmd_valid,cmd_ready),bit('','done_valid_reg'),bit('','command_pending_reg')],
        'actual_matrix_admission_and_input_owner_availability')
    check([request,port('grouped_input_banks','owner_available',1,'input'),probability_grant,
           z3.Implies(start,z3.And(available,request))],
        [z3.Or(native_request,probability_request),available,z3.And(available,z3.Not(native_request),z3.Not(probability())),z3.BoolVal(True)],
        'actual_grouped_lease_start_is_quiescent_and_blocks_new_matrix_admission')
    delta=z3.If(accepted,z3.BitVecVal(1,3),z3.BitVecVal(0,3))-z3.If(done,z3.BitVecVal(1,3),z3.BitVecVal(0,3))
    check([count('next'),owned('next'),reload('next'),probability('next'),bit('','input_bank_reg','next'),bit('','command_pending_reg','next')],
        [z3.If(rst,count('old')+delta,z3.BitVecVal(0,3)),
         z3.And(rst,z3.If(start,z3.BoolVal(True),z3.If(end,z3.BoolVal(False),owned()))),
         z3.Or(z3.Not(rst),z3.If(z3.And(owned(),wrote),z3.BoolVal(True),z3.If(z3.And(load_ready,reload_ack),z3.BoolVal(False),reload()))),
         z3.And(rst,z3.If(z3.And(probability_request,probability_grant),z3.BoolVal(True),z3.If(probability_release,z3.BoolVal(False),probability()))),
         z3.And(rst,z3.If(accepted,z3.Extract(9,9,port('','cmd_activation',10,'input'))==1,bank)),
         z3.And(rst,z3.If(array_ready,accepted,bit('','command_pending_reg')))],
        'actual_owner_counter_lease_reload_and_activation_bank_next_states')
    kind=port('','load_kind',2,'input');address=port('','load_addr',10,'input')
    bad=z3.Or(kind==3,z3.And(z3.Or(kind==0,kind==2),z3.UGE(address,32)))
    check([bit('','load_error_reg','next')],[z3.And(rst,accepted_load,bad)],'actual_invalid_load_error_is_reset_dominant')
    check([invariant('next')],[z3.BoolVal(True)],'input_ownership_reset_basis',[z3.Not(rst)])
    check([invariant('next')],[z3.BoolVal(True)],'input_ownership_and_seven_stage_occupancy_successor',[invariant('old')])
    check([z3.Implies(z3.Or(*queue_valid('old')),z3.And(z3.Not(owned()),z3.Not(probability())))],
        [z3.BoolVal(True)],'inflight_matrix_operations_exclude_native_and_probability_ownership',[invariant('old')])
    module=routes.module(environment['master'])
    def memory_pin(instance,name):
        pins=routes.input_memories[instance]['pins'];nets=module.expression(pins[name])
        values=bridge.convert([routes.trace('',net) for net in reversed(nets)])
        return values[0] if len(values)==1 else bridge.pack(values)
    payload=port('','load_data',2048,'input');rows=port('','load_row_enable',32,'input')
    weight_address=port('','cmd_weight',5,'input');mask_address=port('','cmd_mask',5,'input')
    activation_address=port('','cmd_activation',10,'input');address9=z3.Extract(8,0,address)
    for bank_index in range(16):
        instance=f'weights[{bank_index}]'
        row0=z3.Extract(2*bank_index,2*bank_index,rows)==1;row1=z3.Extract(2*bank_index+1,2*bank_index+1,rows)==1
        write=z3.And(rst,accepted_load,kind==0,z3.ULT(address,32),z3.Or(row0,row1));web=z3.Not(write)
        bweb=z3.Concat(z3.If(row1,z3.BitVecVal(0,64),z3.BitVecVal(2**64-1,64)),
            z3.If(row0,z3.BitVecVal(0,64),z3.BitVecVal(2**64-1,64)))
        check([memory_pin(instance,'CEB'),memory_pin(instance,'WEB'),memory_pin(instance,'D'),memory_pin(instance,'BWEB'),
               z3.Implies(z3.Or(write,accepted),memory_pin(instance,'A')==z3.If(write,z3.Extract(4,0,address),weight_address))],
            [z3.And(web,z3.Not(accepted)),web,z3.Extract(bank_index*128+127,bank_index*128,payload),bweb,z3.BoolVal(True)],
            f'physical_weight_bank{bank_index}_read_write_address_payload_and_row_mask')
    for bank_index in range(2):
        instance=f'masks[{bank_index}]';write=z3.And(rst,accepted_load,kind==2,z3.ULT(address,32));web=z3.Not(write)
        check([memory_pin(instance,'CEB'),memory_pin(instance,'WEB'),memory_pin(instance,'D'),memory_pin(instance,'BWEB'),
               z3.Implies(z3.Or(write,accepted),memory_pin(instance,'A')==z3.If(write,z3.Extract(4,0,address),mask_address))],
            [z3.And(web,z3.Not(accepted)),web,z3.Extract(bank_index*128+127,bank_index*128,payload),z3.BitVecVal(0,128),z3.BoolVal(True)],
            f'physical_mask_bank{bank_index}_read_write_address_payload_and_full_mask')
    has_residual=environment['residual_client_present']
    residual=port('','residual_lease',1,'input') if has_residual else z3.BoolVal(False)
    matrix_mode=z3.And(z3.Not(owned()),z3.Not(probability()))
    request_bank=z3.Extract(9,9,activation_address)==1
    assert environment['parent_activation_bank_zero_bound'] is True,'Missing actual parent activation-bank binding'
    check([bit('','input_bank_reg','next')],[z3.BoolVal(False)],'actual_activation_bank0_reset_basis',[z3.Not(rst)])
    check([bit('','input_bank_reg','next')],[z3.BoolVal(False)],'actual_activation_bank0_selection_history_successor',
        [z3.Not(bank),z3.Not(request_bank)])
    for bank_index in range(2):
        instance=f'inputs[{bank_index}]'
        write=z3.And(rst,accepted_load,kind==1,z3.Extract(9,9,address)==bank_index)
        read=z3.And(accepted,request_bank==bool(bank_index));ce=z3.Not(z3.Or(write,read));we=z3.Not(write)
        wanted_data=z3.Extract(63,0,payload);wanted_address=z3.If(write,address9,z3.Extract(8,0,activation_address))
        if bank_index==1 and has_residual:
            ce=z3.If(residual,z3.Or(z3.Not(rst),port('','residual_ce_n',1,'input')),ce)
            we=z3.If(residual,port('','residual_we_n',1,'input'),we)
            wanted_address=z3.If(residual,port('','residual_addr',9,'input'),wanted_address)
            wanted_data=z3.If(residual,port('','residual_d',64,'input'),wanted_data)
        check([memory_pin(instance,'CEB'),memory_pin(instance,'WEB'),memory_pin(instance,'D'),
               z3.Implies(z3.Not(ce),memory_pin(instance,'A')==wanted_address)],
            [ce,we,wanted_data,z3.BoolVal(True)],f'physical_activation_bank{bank_index}_matrix_load_and_residual_mux',[matrix_mode])
    def enabled_read(instance):return z3.And(z3.Not(memory_pin(instance,'CEB')),memory_pin(instance,'WEB'))
    def selected_input_read(select):return z3.If(select,enabled_read('inputs[1]'),enabled_read('inputs[0]'))
    selected_address=z3.If(request_bank,memory_pin('inputs[1]','A'),memory_pin('inputs[0]','A'))
    check([selected_input_read(request_bank),selected_address],
        [z3.BoolVal(True),z3.Extract(8,0,activation_address)],
        'accepted_matrix_command_reads_selected_activation_address_under_actual_parent_bank0_binding',
        [invariant('old'),accepted,z3.Not(request_bank)])
    stalled=z3.And(bit('','command_pending_reg'),z3.Not(array_ready))
    all_reads=[enabled_read(f'weights[{i}]') for i in range(16)]+[enabled_read(f'masks[{i}]') for i in range(2)]+[selected_input_read(bank)]
    check(all_reads,[z3.BoolVal(False)]*19,'stalled_pending_operands_have_no_interfering_memory_read',
        [invariant('old'),stalled,z3.Not(bank)])
    assert only_query is None or len(bridge.checks)==1,'Selected input memory query is absent'
    return dict(queries=bridge.checks,selected_controller_bits=49,input_macro_count=20,physical_input_q_bits=2432,
        controller_module_sha256=environment['controller_module_sha256'],bridge=bridge,records=records,invariant=invariant('old'),
        residual_client_present=has_residual,
        parent_activation_bank_zero_bound=True,
        residual_noninterference_verified_for_current_parent_bank0_commands=True,
        upstream_residual_lease_contract_verified=False,truthful_reload_acknowledgement_verified=False)


def input_fault_specifications(get_body,root):
    """Derive each exact query/activation/body mutation from the selected circuit."""
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_command_admission import parse_admission_module
    module=parse_admission_module(get_body(root))
    owner=module.cells['input_owner'][0];controls=[]
    def add(label,master,instance,pins,query,case):
        body=get_body(master)
        for pin,value in pins.items():body=replace_instance_pin(body,instance,pin,value.encode())
        controls.append((label,{master:body},query,case))
    def force(context,instance,value):
        master=module.cells[context][0] if context else root
        _,pins=parse_admission_module(get_body(master)).cells[instance]
        return dict(D=value,**({'E':"1'b1"} if 'E' in pins else {}),**({'SE':"1'b0"} if 'SE' in pins else {}))
    weight_query='physical_weight_bank0_read_write_address_payload_and_row_mask'
    add('weight_read_address_lost',root,'weights[0]',{'A':"5'b0"},weight_query,'read_weight')
    add('weight_write_payload_lost',root,'weights[0]',{'D':"128'b0"},weight_query,'load_weight')
    add('weight_row_mask_lost',root,'weights[0]',{'BWEB':"128'b0"},weight_query,'load_weight')
    add('weight_write_disabled',root,'weights[0]',{'WEB':"1'b1"},weight_query,'load_weight')
    q=module.expression(module.cells['weights[0]'][1]['Q'])
    add('physical_weight_q_bit_order_reversed',root,'weights[0]',{'Q':'{'+','.join(reversed(q))+'}'},
        'all2048_weight_bits_reach_correct_processing_lanes','physical_words')
    add('mask_read_address_lost',root,'masks[0]',{'A':"5'b0"},
        'physical_mask_bank0_read_write_address_payload_and_full_mask','read_mask')
    add('activation_read_address_lost',root,'inputs[0]',{'A':"9'b0"},
        'physical_activation_bank0_matrix_load_and_residual_mux','read_activation')
    add('activation_write_payload_lost',root,'inputs[1]',{'D':"64'b0"},
        'physical_activation_bank1_matrix_load_and_residual_mux','load_activation')
    add('accepted_input_bank_wrong',root,'input_bank_reg',force('','input_bank_reg',"1'b1"),
        'actual_owner_counter_lease_reload_and_activation_bank_next_states','read_activation')
    add('accepted_outstanding_increment_lost',owner,'outstanding_reg[0]',force('input_owner','outstanding_reg[0]',"1'b0"),
        'actual_owner_counter_lease_reload_and_activation_bank_next_states','read_activation')
    assert 'SDN' in parse_admission_module(get_body(owner)).cells['activation_reload_required_reg'][1],'Reload flag no longer has its expected preset pin'
    add('reload_required_reset_disconnected',owner,'activation_reload_required_reg',{'SDN':"1'b1"},
        'all49_input_controller_common_reset_bindings','reset')
    structural=[('input_macro_clock_disconnected',root,'inputs[0]','CLK',"1'b0",'Input memory clock differs'),
        ('input_macro_address_truncated',root,'weights[0]','A',"4'b0",'Input memory pin width differs'),
        ('input_macro_q_driver_collision',root,'inputs[0]','Q',module.cells['inputs[1]'][1]['Q'],'Input memory Q lacks its exact sole physical driver'),
        ('owner_register_clock_disconnected',owner,'outstanding_reg[0]','CP',"1'b0",'Numeric register clock differs')]
    return controls,structural


def input_rejection_controls(original,path):
    """Activate faults in actual mapped bodies, retaining the original interface."""
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_intensity import require_counterexample
    from prove_tri_oracle_tile_command_routes import route_word
    base=input_environment(original,path);routes=base['routes'];root=base['master']
    controls,structural=input_fault_specifications(routes.body,root)
    rejected=[];del base;gc.collect()
    for label,overrides,query,case in controls:
        environment=input_environment(original,path,overrides=overrides);changed=environment['routes']
        def activate(bridge,actual,records):
            rst=bridge.boolean('top.rst_n')
            if case=='reset':return [z3.Not(rst)]
            if case=='physical_words':return [rst,bridge.boolean('physical_memory.weights[0].Q[0]'),
                z3.Not(bridge.boolean('physical_memory.weights[0].Q[127]'))]
            port=lambda name,width,direction='input':route_word(actual,bridge,'',name,width,direction=direction)
            conditions=[rst,z3.Not(records['input_owner','softmax_owns_input_reg']['old']),
                z3.Not(records['grouped_input_banks','probability_owner_reg']['old'])]
            if case.startswith('read_'):
                conditions += [port('cmd_valid',1),port('cmd_ready',1,'output'),z3.Not(port('load_valid',1)),
                    z3.Not(records['input_owner','activation_reload_required_reg']['old'])]
                conditions += [z3.Not(records['input_owner',f'outstanding_reg[{bit}]']['old']) for bit in range(3)]
                conditions += [z3.Not(records['','done_valid_reg']['old'])]
                if case=='read_weight':conditions += [port('cmd_weight',5)==1]
                elif case=='read_mask':conditions += [port('cmd_mask',5)==1]
                elif case=='read_activation':conditions += [port('cmd_activation',10)==1]
                else:raise AssertionError('Unknown input read fault activation')
            else:
                assert case in ('load_weight','load_activation'),'Unknown input load fault activation'
                activation=case=='load_activation'
                conditions += [port('load_valid',1),port('load_ready',1,'output'),
                    port('load_kind',2)==(1 if activation else 0),port('load_addr',10)==(512 if activation else 1),
                    port('load_row_enable',32)==1,z3.Extract(127,0,port('load_data',2048))==1]
                if environment['residual_client_present']:conditions += [z3.Not(port('residual_lease',1))]
            return conditions
        try:prove_input_owner_and_bytes(environment,only_query=query,activation=activate)
        except AssertionError as error:
            require_counterexample(error,expected_query=query)
            rejected.append(dict(control=label,query=query,result='sat',activation=case,
                altered_modules_sha256={master:sha256(body).hexdigest() for master,body in overrides.items()}))
            print('INPUT_MEMORY_BODY_FAULT_REJECTED',label,flush=True)
        else:raise AssertionError(('Input-memory body fault accepted',label))
        del environment;gc.collect()
    for label,master,instance,pin,value,wanted in structural:
        body=replace_instance_pin(routes.body(master),instance,pin,value.encode())
        try:prove_input_owner_and_bytes(input_environment(original,path,overrides={master:body}))
        except AssertionError as error:
            assert str(error)==wanted,('Unrelated input-memory structural rejection',label,str(error))
            rejected.append(dict(control=label,rejection=wanted,altered_modules_sha256={master:sha256(body).hexdigest()}))
            print('INPUT_MEMORY_STRUCTURE_FAULT_REJECTED',label,flush=True)
        else:raise AssertionError(('Input-memory structural fault accepted',label))
    assert len(rejected)==15 and len({tuple(sorted(row['altered_modules_sha256'].items())) for row in rejected})==15
    return rejected


def verify(output):
    from prove_tri_oracle_tile_command_routes import command_route_environment
    from prove_tri_oracle_command_admission import AdmissionRoutes
    from prove_tri_oracle_packaged_accumulators import compiled_memory_library,local_source_paths
    from prove_tri_oracle_packaged_products import ROOT,memory_guard
    from prove_tri_oracle_numeric_pipeline_history import EXTRA_ROUTE_INPUTS
    from prove_tri_oracle_head_score_frontend import revalidate_evidence
    assert not Path('/.dockerenv').exists() and output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);started=time.monotonic();pins={}
    def pin(path,wanted=None):
        with path.open('rb') as stream:actual=file_digest(stream,'sha256').hexdigest()
        assert wanted is None or actual==wanted,('Changed input-memory history input',path)
        assert pins.setdefault(str(path.relative_to(ROOT)),actual)==actual
        return path
    prior=json.loads(pin(ROOT/NUMERIC_ROOT[0],NUMERIC_ROOT[1]).read_text())
    assert prior['state']=='mapped_numeric_pipeline_and_ordered_memory_fold_verified_relative_to_operand_and_memory_contracts'
    assert prior['core_count']==20 and len(prior['core_modules'])==20
    for name,wanted in prior['evidence_sha256'].items():pin(ROOT/name,wanted)
    detail_name,=(name for name in prior['evidence_sha256'] if name.endswith('/numeric_pipeline_all_core_review_fixed.json'))
    detail=json.loads((ROOT/detail_name).read_text())
    for name,wanted in detail['evidence_sha256'].items():pin(ROOT/name,wanted)
    for name,wanted in EXTRA_ROUTE_INPUTS.items():pin(ROOT/name,wanted)
    sources=local_source_paths((Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_input_memory_logic.py'),ROOT/'syn')
    for path in sources:pin(path)
    expected=merge_pinned_inputs({NUMERIC_ROOT[0]:NUMERIC_ROOT[1]},prior['evidence_sha256'],detail['evidence_sha256'],EXTRA_ROUTE_INPUTS,
        {str(path.relative_to(ROOT)):pins[str(path.relative_to(ROOT))] for path in sources})
    cores=[]
    with command_route_environment(pin) as original:
        assert original['candidate_sha256']==prior['candidate_sha256']
        original['memory_bus_library']=compiled_memory_library(original);source=original['routes']
        original['reset_routes']=AdmissionRoutes(source.body,source.masters,source.library,source.states,source.contexts[''][0],guard=source.guard)
        original['reset_routes'].modules=source.modules
        for previous in prior['core_modules']:
            environment=input_environment(original,previous['absolute_context'])
            for key in ('core_module_sha256','array_module_sha256'):
                assert environment[key]==previous[key],('Input-memory numeric predecessor body differs',key)
            result=prove_input_owner_and_bytes(environment)
            assert len(result['queries'])==36 and len(environment['hierarchy_bindings'])==5
            row={key:previous[key] for key in ('bank','core','absolute_context','module','core_module_sha256','array_module','array_module_sha256')}
            row.update({key:result[key] for key in ('queries','selected_controller_bits','input_macro_count','physical_input_q_bits',
                'controller_module_sha256','residual_client_present','parent_activation_bank_zero_bound',
                'residual_noninterference_verified_for_current_parent_bank0_commands','upstream_residual_lease_contract_verified',
                'truthful_reload_acknowledgement_verified')})
            row['hierarchy_bindings']=environment['hierarchy_bindings'];cores.append(row)
            print('INPUT_MEMORY_CORE_BOUND',row['bank'],row['core'],36,5,flush=True)
            del result,environment;gc.collect()
        controls=input_rejection_controls(original,prior['core_modules'][0]['absolute_context'])
    history=prove_input_snapshot_history()
    loaded={Path(module.__file__).resolve() for module in sys.modules.values() if getattr(module,'__file__',None)
        and Path(module.__file__).resolve().parent==ROOT/'syn'}
    assert loaded<=set(sources),('Unpinned input-memory source',loaded-set(sources))
    assert pins==expected,'Input-memory evidence inventory differs from rooted inputs and source closure'
    revalidate_evidence(pins,ROOT)
    result=dict(state='mapped_input_memory_ports_ownership_and_pending_snapshot_history_verified_under_normal_memory_contract',
        candidate_sha256=prior['candidate_sha256'],core_count=len(cores),cores=cores,
        physical_input_macro_count=sum(row['input_macro_count'] for row in cores),
        physical_input_q_bits=sum(row['physical_input_q_bits'] for row in cores),
        controller_and_metadata_role_bindings=sum(row['selected_controller_bits'] for row in cores),
        fresh_equivalence_queries=sum(len(row['queries'])+len(row['hierarchy_bindings']) for row in cores),
        actual_body_fault_controls=controls,pending_snapshot_history=history,
        conditional_input_word_snapshot_history_verified=True,
        residual_noninterference_verified_for_current_parent_bank0_commands=True,
        truthful_reload_acknowledgement_verified=False,correct_task_operand_epoch_verified=False,
        evidence_sha256=pins,transitively_imported_local_source_files=len(sources),
        all_loaded_local_sources_pinned=True,input_memory_contents_verified=False,
        complete_memory_history_verified=False,complete_tensor_scores_verified=False,
        universal_compiler_memory_semantics_verified=False,task_accuracy_verified=False,
        physical_timing_verified=False,complete_paper_architecture_verified=False,
        advance_to_clock_distribution_or_routing_allowed=False,
        elapsed_seconds=time.monotonic()-started,peak_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        scope=RESULT_SCOPE)
    with output.open('x') as stream:stream.write(json.dumps(result,indent=2)+'\n')
    print(result['state'],len(cores),result['fresh_equivalence_queries'],result['elapsed_seconds'],flush=True)


if __name__=='__main__':
    import argparse
    resource.setrlimit(resource.RLIMIT_AS,(3*2**30,3*2**30))
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    verify(parser.parse_args().output)
