"""Verify actual tensor header capture and local attention address admission.

Operational mode reachability, score arithmetic, task accuracy and physical
timing remain separate. Observed parent token inputs are eleven physical bits.
"""
if not __debug__:raise RuntimeError('Command admission verification requires Python assertions')
from pathlib import Path
import re,z3
from prove_tri_oracle_tile_command_routes import CommandRoutes
from prove_tri_oracle_head_routing import HeadRoutes


def parse_admission_module(body):
    """Extend pin-token syntax without changing any parsed connection identity.

    The established parser omits colon/dot/dollar in escaped named pins. Give
    only those pin tokens temporary collision-free spellings, parse normally,
    then restore every pin key. Net expressions and declarations are unchanged.
    """
    from hashlib import sha256
    from prove_tri_oracle_parent_reset import Module,identifier,INSTANCE
    prefix=b'__mapped_pin_alias_';assert prefix not in body,'Parser alias prefix already exists'
    aliases={};names={}
    def replace(match):
        token=match[1]
        if re.fullmatch(rb'[\\\w\[\]]+',token):return match[0]
        name=identifier(token.decode())
        if name not in names:
            alias=prefix+str(len(names)).encode();names[name]=alias;aliases[alias.decode()]=name
        return b'.'+names[name]+b'('
    def replace_fields(match):
        start=match.start(3)-match.start();end=match.end(3)-match.start()
        fields=re.sub(rb'\.(\\[A-Za-z0-9_$.\[\]:]+)\s+\(',replace,match[3])
        return match[0][:start]+fields+match[0][end:]
    normalized=INSTANCE.sub(replace_fields,body)
    module=Module(normalized)
    for instance,(master,pins) in list(module.cells.items()):
        restored={aliases.get(pin,pin):value for pin,value in pins.items()}
        assert len(restored)==len(pins),'Parser pin aliases collided'
        module.cells[instance]=master,restored
    module.sha256=sha256(body).hexdigest();module.parser_pin_aliases=aliases
    return module


class AdmissionRoutes(CommandRoutes):
    """Retain dependency-scoped strict lookup for unrelated unsupported macros."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.scoped_contexts=set()

    def module(self,master):
        if master not in self.modules:
            self.guard();self.modules[master]=parse_admission_module(self.body(master))
        return self.modules[master]

    def drivers(self,context,net):
        if context not in self.scoped_contexts:
            try:return super().drivers(context,net)
            except ValueError as error:
                assert str(error).startswith('Unknown library pin on reset cone:'),'Unrelated route inventory failure'
                self.scoped_contexts.add(context)
        # Unlike the eager performance index, this established implementation
        # asks pin directions only for connections that mention the wanted net.
        # An unknown direction on a relevant connection still raises normally.
        return HeadRoutes.drivers(self,context,net)

HEADER_WIDTHS={'tag':32,'tokens':5,'feature_words':10,'dense_rows':17,'count':8,
    'activation_base':64,'weight_base':64,'up_weight_base':64,'activation_stride':32,'paired':1,'part_words':8,
    'packed_weights':1,'local_scores':1,'single_core_scores':1,'score_core':2,'score_cluster':3}
SCALAR_HEADER_FIELDS={'paired','packed_weights','local_scores','single_core_scores'}


def last_byte(base,rows):
    assert base.size()==64 and rows.size()==65,'Memory span widths differ'
    return z3.ZeroExt(1,base)+(rows<<6)-1


def reference_parent_bad(tokens,denominator,query_base,key_base):
    assert tokens.size()==11,'Only eleven observed parent token bits are qualified'
    assert denominator.size()==8 and query_base.size()==key_base.size()==64
    total=z3.ZeroExt(54,tokens);maximum=z3.BitVecVal(2**64-1,65)
    return z3.Or(z3.ULE(tokens,96),denominator==0,z3.Extract(2,0,query_base)!=0,z3.Extract(2,0,key_base)!=0,
                 z3.UGT(last_byte(query_base,total-96),maximum),z3.UGT(last_byte(key_base,total),maximum))


def address_invariant(parent):
    active=z3.Or(*(parent['state']==value for value in (1,2,3,4)))
    total=z3.ZeroExt(54,parent['tokens']);query=z3.ZeroExt(52,parent['query'])
    maximum=z3.BitVecVal(2**64-1,65)
    return z3.Implies(active,z3.And(z3.Extract(2,0,parent['query_addr'])==0,
        z3.Extract(2,0,parent['key_base'])==0,z3.ULE(last_byte(parent['query_addr'],total-query),maximum),
        z3.ULE(last_byte(parent['key_base'],total),maximum)))


def header_source(field,index):
    assert field in HEADER_WIDTHS and type(index) is int and 0<=index<HEADER_WIDTHS[field],'Invalid receiver header bit'
    scalar={'paired':'cfg_paired','packed_weights':'cfg_packed_weights','local_scores':'softmax_request[score_tile]',
            'single_core_scores':'softmax_request[score_core]'}
    if field in scalar:return scalar[field]
    if field in ('score_core','score_cluster'):return f'softmax_request[owner][{index+(2 if field=="score_cluster" else 0)}]'
    return f'cfg_feature_words[{index+2}]' if field=='part_words' else f'cfg_{field}[{index}]'


def reference_part_words(feature_words,single_core):
    assert feature_words.size()==10 and z3.is_bool(single_core),'Invalid feature partition input'
    return z3.If(single_core,z3.Extract(7,0,feature_words),z3.Extract(9,2,feature_words))


def prove_parent_addresses(bridge,tile_bridge,raw,parent,tile,*,only_query=None,activation=()):
    from prove_tri_oracle_tile_geometry import epoch_invariant,bound_parent_port,mapped_word,geometry_check
    initial=len(bridge.checks)
    fields={name:parent[name] for name in ('state','query','tokens','query_addr','key_base')}
    old={name:field['old'] for name,field in fields.items()};following={name:field['data'] for name,field in fields.items()}
    reset={name:z3.BitVecVal(field['reset_value'],field['bits']) for name,field in fields.items()}
    old_tile={name:field['old'] for name,field in tile['fields'].items()}
    scalar=epoch_invariant(old,old_tile);invariant=address_invariant(old)
    cfg_tokens=bridge.word('cfg_tokens',11)
    bad=reference_parent_bad(cfg_tokens,bridge.word('cfg_ratio_den',8),bridge.word('cfg_query_base',64),bridge.word('cfg_key_base',64))
    ready=bound_parent_port(bridge,raw,'batch_ready',1)==mapped_word(tile_bridge,'batch_ready',1)
    def check(actual,wanted,*,label,conditions=()):
        return geometry_check(bridge,actual,wanted,label=label,conditions=conditions,only_query=only_query,activation=activation)
    check([fields['state']['data']],
        [z3.If(bridge.boolean('cfg_valid'),z3.If(bad,z3.BitVecVal(5,3),z3.BitVecVal(1,3)),z3.BitVecVal(0,3))],
        label='parent_observed_configuration_admission',conditions=[bridge.boolean('rst_n'),old['state']==0])
    check([address_invariant(reset)],[z3.BoolVal(True)],label='parent_address_invariant_reset_basis')
    check([address_invariant(following)],[z3.BoolVal(True)],label='parent_actual_address_invariant_induction',
        conditions=[bridge.boolean('rst_n'),scalar,ready,invariant])
    assert only_query is None or len(bridge.checks)==initial+1,'Targeted parent admission query absent'
    return dict(invariant=invariant,old=old,following=following,queries=bridge.checks[initial:],
                observed_token_bits=11,minimum_tokens=97,maximum_tokens=2047,
                address_alignment_bytes=8,feature_bytes_per_query=64)


def owner_header_model(environment,body=None):
    from prove_tri_oracle_tile_command_capture import owner_capture_model
    from prove_tri_oracle_tile_score_packet import primary_tile_state
    from prove_tri_oracle_packaged_products import liberty_group
    model=owner_capture_model(environment,body)
    selected=set(HEADER_WIDTHS)|{'state','done_error'}
    masters=set()
    for instance,(master,_) in model.module.cells.items():
        match=re.fullmatch(r'(\w+)_reg(?:\[\d+\])?',instance)
        if match and match[1] in selected:
            assert model.states.get(master)=={'ff':1},'Receiver header state kind differs'
            masters.add(master)
    tables=[]
    for paths in environment['sources'].values():
        standard,=(path for path in paths if path.name.startswith('tcbn28'))
        text=standard.read_text();table={}
        for master in sorted(masters):
            match,=re.finditer(r'(?m)^cell\s*\('+re.escape(master)+r'\)\s*\{',text)
            table[master]=primary_tile_state(liberty_group(text,match.end()))
        tables.append(table)
    assert len(tables)==3 and tables[0]==tables[1]==tables[2],'Receiver header primary functions differ across corners'
    model.library=dict(model.library)
    model.library.update({(master,'__tile_ff__'):description for master,description in tables[0].items()})
    return model


def header_registers(bridge):
    records=[];inventory={field:set() for field in HEADER_WIDTHS}
    for instance,(master,pins) in sorted(bridge.model.module.cells.items()):
        match=re.fullmatch(r'(\w+)_reg(?:\[(\d+)\])?',instance)
        if not match or match[1] not in HEADER_WIDTHS:continue
        field=match[1];index=int(match[2]) if match[2] is not None else 0
        assert (match[2] is None)==(field in SCALAR_HEADER_FIELDS),'Receiver header scalar shape differs'
        source=header_source(field,index);inventory[field].add(index)
        q,=bridge.model.module.expression(pins['Q'])
        update,reset,reset_value=bridge.model.transition(instance,q)
        assert reset is not None and reset_value==0,'Receiver header reset differs'
        old,=bridge.convert([bridge.model.cone(q)]);data,=bridge.convert([update]);clear,=bridge.convert([reset])
        incoming=bridge.boolean(source)
        if field=='part_words':
            part=reference_part_words(bridge.word('cfg_feature_words',10),bridge.boolean('softmax_request[score_core]'))
            incoming=z3.Extract(index,index,part)==1
        records.append(dict(instance=instance,field=field,index=index,old=old,data=data,clear=clear,incoming=incoming))
    assert all(inventory[field]==set(range(width)) for field,width in HEADER_WIDTHS.items()),'Receiver header inventory differs'
    assert len(records)==sum(HEADER_WIDTHS.values())==313
    return records


def prove_receiver_admission(environment,routed,address,*,body=None,only_query=None,activation=()):
    from prove_tri_oracle_tile_geometry import register_vector,geometry_check,ContextBridge
    from prove_tri_oracle_tile_command_routes import route_word
    model=owner_header_model(environment,body)
    # Prove the local interface contract for every possible input value first.
    # Unpaired attention does not depend on the unused up-base's upstream
    # memory producer. Its value remains unconstrained; it is never zeroed.
    owner=environment['routes'].walk(environment['paths']['owner'])
    bridge=ContextBridge(model,owner)
    records=header_registers(bridge);state=register_vector(bridge,'state',range(5))
    update,reset,reset_value=model.transition('done_error_reg','done_error')
    assert reset is not None and reset_value==0,'Receiver error register reset differs'
    error,clear=bridge.convert([update,reset]);rst=bridge.boolean('rst_n')
    capture=z3.And(bridge.boolean('cfg_valid'),state['old']==0)
    def check(actual,wanted,*,label,conditions=()):
        environment['routes'].guard()
        result=geometry_check(bridge,actual,wanted,label=label,conditions=conditions,only_query=only_query,activation=activation)
        environment['routes'].guard();return result
    check([state['old']],[routed['owner_state']],label='receiver_header_state_route_identity')
    check([*[record['clear'] for record in records],*state['resets'],clear],
          [z3.Not(rst)]*319,label='all319_header_control_reset_bindings')
    check([record['data'] for record in records],
          [z3.If(capture,record['incoming'],record['old']) for record in records],
          label='all313_header_register_capture_or_hold',conditions=[rst])
    check([record['data'] for record in records],[record['old'] for record in records],
          label='all313_header_register_retained_without_acceptance',conditions=[rst,z3.Not(capture)])
    bound={'cfg_'+field:width for field,width in HEADER_WIDTHS.items()
           if field not in ('part_words','up_weight_base','packed_weights','local_scores','single_core_scores','score_core','score_cluster')}
    bound.update(cfg_valid=1,clk=1,rst_n=1,cfg_packed_weights=1)
    bound.update({'softmax_request[score_core]':1,'softmax_request[score_tile]':1})
    bindings=[]
    for name,width in bound.items():
        print('ADMISSION_COMPOSE_INPUT',name,flush=True)
        actual=route_word(environment['routes'],routed['bridge'],owner,name,width,direction='input')
        local=bridge.boolean(name) if width==1 else bridge.word(name,width)
        bindings.append(local==actual)
    conditions=[*routed['admission_conditions'],address['invariant'],*bindings,capture]
    witnesses=[]
    for query,count,total in ((96,1,97),(2032,15,2047)):
        solver=z3.SolverFor('QF_BV');solver.set(timeout=120000,max_memory=1024)
        solver.add(*conditions,routed['geometry']['query']==query,routed['geometry']['tokens']==count,
            address['old']['tokens']==total,address['old']['query_addr']==2**64-count*64,
            address['old']['key_base']==2**64-total*64)
        result=solver.check();assert result==z3.sat,('Composed header boundary witness absent',query,str(result))
        witnesses.append(dict(query=query,queries=count,total=total,result='sat',query_and_key_last_byte=2**64-1,
                              whole_chip_clock_history_reachability_verified=False))
    check([state['data'],error],[z3.BitVecVal(1,5),z3.BoolVal(False)],
          label='accepted_attention_header_enters_validate_without_error',conditions=conditions)
    rows=z3.ZeroExt(6,routed['geometry']['rows']);channels=routed['channels']
    check([z3.And(*(z3.ULT(z3.ZeroExt(1,z3.Extract(16*column+15,16*column,channels)),rows) for column in range(96)))],
          [z3.BoolVal(True)],label='all96_selected_channels_below_dense_rows',conditions=conditions)
    assert only_query is None or len(bridge.checks)==1,'Targeted receiver admission query absent'
    return dict(module_sha256=model.body_sha256,header_register_bits=313,header_fields=len(HEADER_WIDTHS),
                local_input_contract_universal=True,composed_input_fields=bound,unused_up_base_unconstrained=True,
                unused_softmax_owner_unconstrained=True,boundary_witnesses=witnesses,
                reset_and_control_bits=319,queries=bridge.checks,
                conditional_mode_reachability_verified=False,complete_tensor_execution_verified=False)


def verify(output):
    import json,time,resource
    from hashlib import file_digest
    from prove_tri_oracle_packaged_products import ROOT,memory_guard
    from prove_tri_oracle_head_score_frontend import revalidate_evidence
    from prove_tri_oracle_tile_geometry import load_models,geometry_models,prove_parent_geometry,prove_tile_geometry,epoch_invariant
    from prove_tri_oracle_tile_command import command_registers,command_invariant
    from prove_tri_oracle_tile_command_routes import command_route_environment,prove_command_routes
    assert not Path('/.dockerenv').exists()
    assert output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);start=time.monotonic();evidence={}
    def pin(path,wanted=None):
        with path.open('rb') as stream:digest=file_digest(stream,'sha256').hexdigest()
        assert wanted is None or wanted==digest,('Changed admission input',path)
        name=str(path.relative_to(ROOT));assert evidence.setdefault(name,digest)==digest
        return path
    prior=json.loads(pin(ROOT/'records/tri_oracle_packaged_tile_command.json').read_text())
    assert prior['state']=='mapped_command_storage_conditional_routes_and_receiver_capture_verified'
    for name,digest in prior['evidence_sha256'].items():pin(ROOT/name,digest)
    full_name,=[name for name in prior['evidence_sha256'] if name.endswith('/command_controls_parsed.json')]
    full=json.loads((ROOT/full_name).read_text())
    for name,digest in full['evidence_sha256'].items():pin(ROOT/name,digest)
    prior_queries=[*full['scalar_parent_queries'],*full['tile_and_command_queries'],*full['conditional_routes']['queries'],*full['receiver']['queries']]
    assert len(prior_queries)==36 and all(query['result']=='unsat' for query in prior_queries),'Prior command proof is not complete'
    assert len(full['rejected_corruptions'])==19
    for path in (Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_command_admission_logic.py',
                 ROOT/'syn/prove_tri_oracle_command_admission_controls.py'):pin(path)
    data=load_models(pin);assert data['candidate_sha256']==prior['candidate_sha256']
    p,t,raw=geometry_models(data)
    parent=prove_parent_geometry(p,raw);tile=prove_tile_geometry(t,p,raw,parent)
    address=prove_parent_addresses(p,t,raw,parent,tile)
    old={name:field['old'] for name,field in tile['fields'].items()}
    parent_old={name:parent[name]['old'] for name in ('state','query','tokens','query_addr','key_base')}
    records=command_registers(t)
    # Reuse the candidate/source-bound prior reset+transition induction. Do not
    # replace it with an assumption justified only by a success Boolean.
    command=dict(old_scalar=old,invariant=command_invariant(records,old),scalar_invariant=epoch_invariant(parent_old,old))
    with command_route_environment(pin) as environment:
        assert environment['candidate_sha256']==data['candidate_sha256']
        original=environment['routes']
        scoped=AdmissionRoutes(original.body,original.masters,original.library,original.states,original.contexts[''][0],
            tile=environment['paths']['tile'],parent=environment['paths']['parent'],guard=original.guard)
        for context,bits in original.offpath.items():
            context=scoped.walk(context);ports=scoped.ports(scoped.contexts[context][0])
            outputs={bit for name,direction in ports.directions.items() if direction=='output' for bit in ports.net_bits(name)}
            assert bits<=outputs,'Admission offpath boundary is not an output'
            scoped.offpath[context]=set(bits)
        from prove_tri_oracle_tile_command_routes import route_word
        row=environment['paths']['layer']+'/attention';context=scoped.walk(row)
        # Refine two previously abstract row outputs using their actual gates.
        # Other row outputs keep the prior declared-port abstraction.
        for name in ('softmax_request[score_core]','softmax_request[score_tile]'):
            ports=scoped.ports(scoped.contexts[context][0]);assert ports.directions.get(name)=='output'
            scoped.offpath[context].remove(name)
        environment['routes']=scoped
        routed=prove_command_routes(environment,p,t,parent,tile,command)
        row_state=route_word(scoped,routed['bridge'],row,'state',5)
        routed['admission_conditions']=[*routed['conditions'],row_state==0]
        routed['bridge'].check([route_word(scoped,routed['bridge'],environment['paths']['owner'],name,1,direction='input')
                for name in ('cfg_packed_weights','softmax_request[score_core]','softmax_request[score_tile]')],
            [z3.BoolVal(False)]*3,label='attention_auxiliary_modes_inactive_with_row_idle',conditions=routed['admission_conditions'])
        routed['bridge'].check([route_word(scoped,routed['bridge'],row,name,1,direction='input') for name in ('clk','rst_n')],
            [routed['bridge'].boolean('top.'+name) for name in ('clk','rst_n')],label='actual_row_common_clock_and_reset')
        receiver=prove_receiver_admission(environment,routed,address)
        from prove_tri_oracle_command_admission_controls import rejection_controls
        corruptions=rejection_controls(data,environment,routed,address)
        modes=dict(required_actual_row_state=0,row_state_history_verified=False,
            row_context=row,row_module_sha256=scoped.module(scoped.contexts[context][0]).sha256,
            actual_route_and_auxiliary_queries=routed['bridge'].checks,
            parser_alias_counts={master:len(module.parser_pin_aliases) for master,module in scoped.modules.items()
                                 if getattr(module,'parser_pin_aliases',{})},
            dependency_scoped_lookup_contexts=sorted(scoped.scoped_contexts))
    revalidate_evidence(evidence,ROOT)
    report=dict(state='mapped_header_capture_and_conditional_address_admission_components_verified',
        candidate_sha256=data['candidate_sha256'],parent_module_sha256=p.model.body_sha256,
        parent_address={name:value for name,value in address.items() if name not in ('invariant','old','following')},
        receiver=receiver,reused_candidate_bound_command_induction=True,
        operational_modes=modes,rejected_corruptions=corruptions,
        required_additional_operational_assumption='Actual row controller is Idle; its history relative to layer RunHead remains unproved',
        evidence_sha256=evidence,wall_seconds=time.monotonic()-start,
        peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        corruption_controls_verified=True,tensor_command_generation_verified=False,
        upstream_mode_reachability_verified=False,full_head_prediction_verified=False,task_accuracy_verified=False,
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
