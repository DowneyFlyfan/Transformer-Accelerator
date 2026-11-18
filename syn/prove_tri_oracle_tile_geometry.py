"""Prove actual parent batch geometry and tile causal-limit components."""
if not __debug__:raise RuntimeError('Geometry verification requires Python assertions')
import z3
from pathlib import Path
import re
from prove_tri_oracle_head_intensity import WordBridge
from prove_tri_oracle_tile_score_packet import TileCone
from prove_tri_oracle_head_configuration import ParentCone

class ContextBridge(WordBridge):
    def __init__(self,model,namespace,*,upstream=None,bindings=None):
        super().__init__(model.graph)
        self.model=model;self.namespace=namespace;self.upstream=upstream;self.bound_inputs={};self.bindings={}
        assert namespace and (upstream is None)==(bindings is None),'Missing input composition context'
        if upstream is not None:
            for name,direction in model.module.directions.items():
                if direction!='input':continue
                assert name in bindings,('Missing actual input binding',name)
                formal=model.module.net_bits(name);actual=upstream.model.module.expression(bindings[name])
                assert len(formal)==len(actual),('Actual input binding width differs',name)
                for bit,net in zip(formal,actual,strict=True):self.bindings[bit]=net

    def boolean(self,name):
        if name not in self.variables:
            if self.upstream is not None and name in self.model.inputs:
                net=self.bindings[name]
                value,=self.upstream.convert([self.upstream.model.cone(net)])
                self.variables[name]=value;self.bound_inputs[name]=net
            else:self.variables[name]=z3.Bool(self.namespace+'.'+name)
        return self.variables[name]

    def check(self,*args,**kwargs):
        from prove_tri_oracle_packaged_products import memory_guard
        memory_guard(8.5)
        result=super().check(*args,**kwargs)
        memory_guard(8.5)
        return result

def clipped_limit(query,token,start):
    assert query.size()==13 and token.size()==4 and start.size()==16
    bound=z3.ZeroExt(4,query)+z3.ZeroExt(13,token)+1
    origin=z3.ZeroExt(1,start);span=bound-origin
    return z3.If(z3.ULE(bound,origin),z3.BitVecVal(0,6),
                 z3.If(z3.UGE(span,32),z3.BitVecVal(32,6),z3.Extract(5,0,span)))


class GeometryParent(ParentCone):
    transition=TileCone.transition


def register_vector(bridge,prefix,indices):
    old=[];data=[];resets=[];value=0
    for position,index in enumerate(indices):
        instance=f'{prefix}_reg[{index}]'
        _,pins=bridge.model.module.cells[instance]
        output,=bridge.model.module.expression(pins['Q'])
        update,reset,reset_value=bridge.model.transition(instance,output)
        assert reset is not None and reset_value in (0,1),('Geometry register lacks reset',instance)
        old.append(bridge.model.cone(output));data.append(update);resets.append(reset)
        value|=reset_value<<position
    return dict(old=bridge.pack(bridge.convert(old)),data=bridge.pack(bridge.convert(data)),
                resets=bridge.convert(resets),reset_value=value,bits=len(indices))


def mapped_word(bridge,name,width):
    roots=[bridge.model.cone(f'{name}[{bit}]' if width>1 else name) for bit in range(width)]
    values=bridge.convert(roots)
    return bridge.pack(values) if width>1 else values[0]


def bound_parent_port(parent,raw,name,width):
    bits=parent.model.module.expression(raw[name]);assert len(bits)==width,'Parent tile port width differs'
    values=parent.convert([parent.model.cone(bit) for bit in reversed(bits)])
    return parent.pack(values) if width>1 else values[0]


def geometry_check(bridge,actual,wanted,*,label,conditions=(),only_query=None,activation=()):
    assert only_query is None or (type(only_query) is str and only_query),'Invalid geometry query selector'
    if only_query is not None and only_query!=label:return False
    bridge.check(actual,wanted,label=label,conditions=[*conditions,*activation])
    return True


def prove_parent_geometry(bridge,raw,*,only_query=None,activation=()):
    initial_queries=len(bridge.checks)
    q=register_vector(bridge,'query_position',range(13))
    tokens=register_vector(bridge,'tokens',range(11))
    query_addr=register_vector(bridge,'query_addr',range(64))
    key_base=register_vector(bridge,'key_base',range(64))
    state=register_vector(bridge,'state',range(3));s=state['old']
    assert q['reset_value']==96 and all(x['reset_value']==0 for x in (tokens,query_addr,key_base,state))
    reset=z3.Not(bridge.boolean('rst_n'))
    def check(actual,wanted,*,label,conditions=()):
        return geometry_check(bridge,actual,wanted,label=label,conditions=conditions,only_query=only_query,activation=activation)
    reset_bits=[bit for field in (q,tokens,query_addr,key_base,state) for bit in field['resets']]
    check(reset_bits,[reset]*len(reset_bits),label='parent_geometry_reset_bindings')
    t=z3.ZeroExt(2,tokens['old']);remaining=t-q['old']
    batch=z3.If(z3.UGE(remaining,16),z3.BitVecVal(16,5),z3.Extract(4,0,remaining))
    following=q['old']+z3.ZeroExt(8,batch);last=following==t
    check([bound_parent_port(bridge,raw,'batch_queries',5),bound_parent_port(bridge,raw,'batch_last',1),
           bound_parent_port(bridge,raw,'batch_valid',1)],
          [batch,last,s==2],label='parent_batch_size_last_and_valid')
    ready=bound_parent_port(bridge,raw,'batch_ready',1)
    failed=mapped_word(bridge,'batch_failed',1)
    load=z3.And(s==0,bridge.boolean('cfg_valid'))
    advance=z3.And(s==3,ready,z3.Not(failed),z3.Not(last))
    valid_reset=bridge.boolean('rst_n')
    check([q['data']],[z3.If(load,z3.BitVecVal(96,13),z3.If(advance,following,q['old']))],
          label='parent_query_pointer_load_hold_advance',conditions=[valid_reset])
    check([query_addr['data'],key_base['data']],
          [z3.If(load,bridge.word('cfg_query_base',64),z3.If(advance,query_addr['old']+(z3.ZeroExt(59,batch)<<6),query_addr['old'])),
           z3.If(load,bridge.word('cfg_key_base',64),key_base['old'])],
          label='parent_query_key_base_updates',conditions=[valid_reset])
    check([bound_parent_port(bridge,raw,'batch_query_addr',64),bound_parent_port(bridge,raw,'batch_key_base',64)],
          [query_addr['old'],key_base['old']],label='parent_batch_address_forwarding')
    domain=z3.And(z3.UGE(t,97),z3.UGE(q['old'],96),z3.ULT(q['old'],t))
    check([z3.And(z3.UGE(batch,1),z3.ULE(batch,16),z3.UGT(following,q['old']),z3.ULE(following,t),
                  z3.Implies(z3.Not(last),z3.ULT(following,t)))],[z3.BoolVal(True)],
          label='parent_batch_range_and_progress_lemma',conditions=[domain])
    # These tighten the earlier conservative parent state-domain proof using
    # the actual tile's ready port. Every listed condition is non-reset.
    cfg_ready=bridge.boolean('head_response[72]')
    valid=bridge.boolean('head_response[70]');out_ready=bridge.boolean('out_ready')
    expected={1:z3.If(cfg_ready,z3.BitVecVal(2,3),z3.BitVecVal(1,3)),
              2:z3.If(ready,z3.BitVecVal(3,3),z3.BitVecVal(2,3)),
              3:z3.If(ready,z3.If(z3.Or(failed,last),z3.BitVecVal(4,3),z3.BitVecVal(2,3)),z3.BitVecVal(3,3)),
              4:z3.If(z3.And(valid,out_ready),z3.BitVecVal(0,3),z3.BitVecVal(4,3)),
              5:z3.If(out_ready,z3.BitVecVal(0,3),z3.BitVecVal(5,3))}
    for code in range(1,6):
        check([state['data']],[expected[code]],label=f'parent_geometry_successor_state{code}',conditions=[s==code,valid_reset])
    assert only_query is None or len(bridge.checks)==initial_queries+1,'Targeted parent geometry query absent'
    return dict(query=q,tokens=tokens,state=state,query_addr=query_addr,key_base=key_base,
                batch=batch,following=following,last=last,domain=domain,load=load,advance=advance)


def geometry_pairs():
    """Common-reset invariant: an active tile belongs to waiting parent3.

    Parent2/Idle accepts one valid geometry snapshot. Parent3 cannot advance
    the query while the tile is active because ready is false. Both wait one
    edge after the tile returns to Idle before another batch is offered.
    These successor domains are separately checked on the actual mapped FSMs.
    """
    domain={(parent,0) for parent in (0,1,2,4,5)}|{(3,tile) for tile in range(8)}
    edges=0
    local={1:{1,2},2:{2,3},3:{3,4,5,6,7},4:{0,3,4},5:{4,5,7},6:{6,7},7:{0,7}}
    for parent,tile in domain:
        assert tile==0 or parent==3
        if parent==0:successors={(next_parent,0) for next_parent in (0,1,5)}
        elif parent==1:successors={(next_parent,0) for next_parent in (1,2)}
        elif parent==2:successors={(3,1)}
        elif parent==3 and tile==0:successors={(2,0),(4,0)}
        elif parent==3:successors={(3,next_tile) for next_tile in local[tile]}
        elif parent==4:successors={(0,0),(4,0)}
        else:successors={(0,0),(5,0)}
        assert successors<=domain,'Parent/tile geometry epoch is not closed'
        edges+=len(successors)
    return dict(state_pairs=len(domain),checked_edges=edges,reset_pair=[0,0],
        active_tile_implies_parent_wait=True,parent_query_held_during_active_tile=True,
        eventual_completion_verified=False)


def prove_tile_geometry(bridge,parent,raw,parent_fields,*,only_query=None,activation=()):
    initial_queries=len(bridge.checks)
    fields={name:register_vector(bridge,prefix,indices) for name,prefix,indices in [
        ('query','first_query',range(13)),('inner','tile_start',range(22,30)),
        ('rows','tensor_cfg_dense_rows',range(11)),('query_addr','tensor_cfg_activation_base',range(64)),
        ('key_base','tensor_cfg_weight_base',range(64)),('state','state',range(3)),
        ('tokens','tensor_cfg_tokens',range(5)),('tag','tensor_cfg_tag',range(32)),
        ('token','token_index',range(4)),('key','key_index',range(7)),
        ('beat','score_beat',range(4)),('limits','row_limits',range(18))]}
    assert all(field['reset_value']==0 for field in fields.values()),'Tile geometry reset value differs'
    def check(actual,wanted,*,label,conditions=()):
        return geometry_check(bridge,actual,wanted,label=label,conditions=conditions,only_query=only_query,activation=activation)
    reset_bits=[bit for field in fields.values() for bit in field['resets']]
    check(reset_bits,[z3.Not(bridge.boolean('rst_n'))]*len(reset_bits),label='tile_geometry_reset_bindings')
    s=fields['state']['old'];pstate=parent_fields['state']['old']
    load=z3.And(s==0,bridge.boolean('batch_valid'));rst=bridge.boolean('rst_n')
    pq=parent_fields['query']['old'];pt=parent_fields['tokens']['old']
    recent=(z3.ZeroExt(3,pq)&z3.BitVecVal(65504,16));inner=recent-64
    expected={'query':pq,'inner':z3.Extract(13,6,inner),'rows':pt,
        'query_addr':parent_fields['query_addr']['old'],'key_base':parent_fields['key_base']['old']}
    check([fields[name]['data'] for name in expected],
          [z3.If(load,value,fields[name]['old']) for name,value in expected.items()],
          label='tile_shared_geometry_snapshot_load_and_hold',conditions=[rst])
    check([fields['tokens']['data']],[z3.If(load,parent_fields['batch'],fields['tokens']['old'])],
          label='tile_batch_query_count_snapshot',conditions=[rst])
    check([fields['state']['data']],[z3.BitVecVal(1,3)],label='parent_accepted_batch_enters_tile_prepare',
          conditions=[rst,s==0,pstate==2,parent_fields['domain']])
    # All scalar geometry inputs to active tile epochs are held snapshots.
    # The accepted parent domain and common-reset pair invariant establish
    # this coherence; no disconnected nominal upper input is read or zeroed.
    q=fields['query']['old'];token=fields['token']['old'];count=fields['tokens']['old']
    stored_recent=(z3.ZeroExt(3,q)&z3.BitVecVal(65504,16));stored_inner=stored_recent-64
    coherent=z3.And(z3.UGE(q,96),z3.ULE(q,2047),
        fields['inner']['old']==z3.Extract(13,6,stored_inner),
        z3.UGE(count,1),z3.ULE(count,16),z3.ULT(z3.ZeroExt(1,token),count))
    last=z3.ZeroExt(1,token)+1==count
    bad=z3.Or(bridge.word('tensor_out_tag',32)!=fields['tag']['old'],
        bridge.word('tensor_out_token',4)!=token,bridge.boolean('tensor_out_last')!=last,
        bridge.word('tensor_out_count',8)!=96)
    capture=z3.And(s==3,z3.Not(bridge.boolean('tensor_done_valid')),bridge.boolean('tensor_out_valid'),z3.Not(bad))
    limits=[clipped_limit(q,token,origin) for origin in (z3.BitVecVal(0,16),stored_inner,stored_recent)]
    expected_limits=z3.Concat(*reversed(limits))
    check([fields['limits']['data']],[z3.If(capture,expected_limits,fields['limits']['old'])],
          label='all18_causal_row_limit_updates',conditions=[rst,coherent])
    check([z3.And(limits[0]==32,limits[1]==32,z3.ULE(limits[2],32),z3.UGE(limits[2],1))],
          [z3.BoolVal(True)],label='three_region_causal_limit_bounds',conditions=[coherent])
    # Shared wire equation comes from the already qualified Phase A ready
    # output. Preserve separate parent/tile namespaces in this composition.
    ready=bound_parent_port(parent,raw,'batch_ready',1)
    hold=z3.And(rst,pstate==3,s!=0,ready==(s==0))
    check([parent_fields['query']['data'],parent_fields['query_addr']['data']],
          [parent_fields['query']['old'],parent_fields['query_addr']['old']],
          label='waiting_parent_holds_geometry_while_tile_active',conditions=[hold])
    witnesses=[]
    old_parent={name:parent_fields[name]['old'] for name in ('state','query','tokens','query_addr','key_base')}
    old_tile={name:field['old'] for name,field in fields.items()}
    invariant=epoch_invariant(old_parent,old_tile)
    for query,queries,index,total in ((96,1,0,97),(96,16,15,112),(112,16,15,128),(2032,15,14,2047)):
        solver=z3.SolverFor('QF_BV');solver.set(timeout=30000,max_memory=512)
        solver.add(rst,coherent,capture,invariant,ready==(s==0),q==query,count==queries,token==index,
                   parent_fields['tokens']['old']==total)
        result=solver.check();assert result==z3.sat,('Causal capture witness absent',query,queries,index,str(result))
        witnesses.append(dict(query=query,batch_queries=queries,token_index=index,parent_tokens=total))
    assert only_query is None or len(bridge.checks)==initial_queries+1,'Targeted tile geometry query absent'
    return dict(fields=fields,coherent=coherent,capture=capture,invariant_capture_satisfiability_witnesses=witnesses,
                parent_tile_epoch=geometry_pairs())


def epoch_invariant(parent,tile):
    ps=parent['state'];ts=tile['state'];pq=parent['query'];pt=parent['tokens']
    recent=z3.ZeroExt(3,pq)&z3.BitVecVal(65504,16)
    remaining=z3.ZeroExt(2,pt)-pq
    batch=z3.If(z3.UGE(remaining,16),z3.BitVecVal(16,5),z3.Extract(4,0,remaining))
    pairs=z3.Or(z3.And(ps==3,z3.ULE(ts,7)),
                z3.And(z3.Or(*(ps==value for value in (0,1,2,4,5))),ts==0))
    active_parent=z3.Or(*(ps==value for value in (1,2,3,4)))
    active_tile=ts!=0
    limits=[z3.Extract(6*region+5,6*region,tile['limits']) for region in range(3)]
    return z3.And(pairs,*(z3.ULE(value,32) for value in limits),
        z3.Implies(active_parent,z3.And(z3.UGE(pt,97),z3.UGE(pq,96),z3.ULT(pq,z3.ZeroExt(2,pt)),z3.Extract(3,0,pq)==0)),
        z3.Implies(active_tile,z3.And(tile['query']==pq,tile['inner']==z3.Extract(13,6,recent-64),
            tile['rows']==pt,tile['tokens']==batch,tile['query_addr']==parent['query_addr'],
            tile['key_base']==parent['key_base'],z3.ULT(z3.ZeroExt(1,tile['token']),tile['tokens']),
            z3.ULE(tile['key'],95),z3.ULE(tile['beat'],11))))


def prove_coupled_epoch(parent_bridge,tile_bridge,raw,parent,tile):
    """Actual mapped transition induction; the finite pair list is not proof
    of numeric coherence by itself. Check reset basis and one unrestricted
    settled non-reset edge on the actual state equations for all saved fields.
    """
    names=('state','query','tokens','query_addr','key_base')
    pfields={name:parent[name] for name in names};tfields=tile['fields']
    old_parent={name:field['old'] for name,field in pfields.items()}
    old_tile={name:field['old'] for name,field in tfields.items()}
    next_parent={name:field['data'] for name,field in pfields.items()}
    next_tile={name:field['data'] for name,field in tfields.items()}
    reset_parent={name:z3.BitVecVal(field['reset_value'],field['bits']) for name,field in pfields.items()}
    reset_tile={name:z3.BitVecVal(field['reset_value'],field['bits']) for name,field in tfields.items()}
    tile_bridge.check([epoch_invariant(reset_parent,reset_tile)],[z3.BoolVal(True)],label='coupled_geometry_reset_basis')
    ready=bound_parent_port(parent_bridge,raw,'batch_ready',1)
    actual_ready=mapped_word(tile_bridge,'batch_ready',1)
    tile_bridge.check([actual_ready],[old_tile['state']==0],label='coupled_actual_tile_ready_equation')
    tile_bridge.check([epoch_invariant(next_parent,next_tile)],[z3.BoolVal(True)],
        label='coupled_actual_geometry_inductive_step',
        conditions=[tile_bridge.boolean('rst_n'),epoch_invariant(old_parent,old_tile),ready==actual_ready])
    return dict(actual_state_equation_induction_verified=True,reset_basis_verified=True,
        scalar_fields_parent=len(pfields),scalar_fields_tile=len(tfields),
        qualified_parent_tokens_minimum=97,qualified_parent_tokens_maximum=2047,
        query_start=96,maximum_batch_queries=16,key_prepare_index_maximum=95,score_beat_maximum=11,
        causal_row_limit_maximum=32,common_reset_aborts_epoch=True,
        eventual_completion_verified=False)


def load_models(pin):
    from hashlib import sha256
    import json
    from prove_tri_oracle_parent_reset import Module
    from prove_tri_oracle_parent_clock import read_clock_library
    from prove_tri_oracle_packaged_products import ROOT,liberty_group
    from prove_tri_oracle_tile_score_packet import primary_tile_state
    from link_tri_oracle_indexed_whole_chip import DECLARATION,signature
    stage=ROOT/'.cache/wide_packaged_host_link/head_ratio_proof'
    prior=json.loads(pin(ROOT/'records/tri_oracle_packaged_tile_score_packet.json').read_text())
    for name,digest in prior['evidence_sha256'].items():pin(ROOT/name,digest)
    full_name,=[name for name in prior['evidence_sha256'] if name.endswith('/tile_packet_qualified.json')]
    full=json.loads((ROOT/full_name).read_text())
    assert full['state']==prior['state']=='mapped_tile_score_buffer_and_packet_components_verified'
    for name,digest in full['evidence_sha256'].items():pin(ROOT/name,digest)
    tile_body=pin(stage/'tile_geometry.body.v',full['packet']['module_sha256']).read_bytes()
    parent_body=pin(stage/'parent_geometry.body.v',full['unused_ready_alias']['parent_module_sha256']).read_bytes()
    storage=json.loads((ROOT/'records/tri_oracle_packaged_storage_accounting.json').read_text())
    name,=storage['full_detail_cache']
    detail=json.loads(pin(ROOT/name,storage['full_detail_cache'][name]).read_text())
    states={name:row['state_kinds'] for name,row in detail['standard_cell_state_by_master'].items()}
    tile=Module(tile_body);parent=Module(parent_body);tile_master,raw=parent.cells['tile']
    assert tile_master==prior['tile_master']
    masters={master for module in (tile,parent) for master,_ in module.cells.values() if master!=tile_master}
    sequential={master for master in masters if states.get(master)}
    libraries=[]
    for suffix in ('tt1v25c','ssg0p9v125c','ffg1p05vm40c'):
        name,=[name for name in full['evidence_sha256'] if Path(name).name==f'tcbn28hpcplusbwp12t40p140{suffix}.lib']
        path=ROOT/name;library=read_clock_library(path,masters)
        library={key:{name:value for name,value in row.items() if name in ('direction','function')} for key,row in library.items()}
        text=path.read_text()
        for master in sequential:
            match,=re.finditer(r'(?m)^cell\s*\('+re.escape(master)+r'\)\s*\{',text)
            library[master,'__tile_ff__']=primary_tile_state(liberty_group(text,match.end()))
        libraries.append(library)
    assert libraries[0]==libraries[1]==libraries[2],'Geometry functions or primary state models differ across corners'
    signature(tile_body);end=tile_body.index(b');')+2
    child=Module(tile_body[:end]+b'\n'+b'\n'.join(match[0] for match in DECLARATION.finditer(tile_body[end:]))+b'\nendmodule')
    return dict(tile_body=tile_body,parent_body=parent_body,library=libraries[0],states=states,
        child=child,tile_master=tile_master,raw=raw,candidate_sha256=prior['candidate_sha256'])


def geometry_models(data,parent_body=None,tile_body=None):
    parent=GeometryParent(data['parent_body'] if parent_body is None else parent_body,
        data['library'],data['states'],{data['tile_master']:data['child']})
    tile=TileCone(data['tile_body'] if tile_body is None else tile_body,data['library'],data['states'])
    p=ContextBridge(parent,'parent');raw=parent.module.cells['tile'][1]
    t=ContextBridge(tile,'tile',upstream=p,bindings=raw)
    return p,t,raw


def rejection_controls(data):
    from hashlib import sha256
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_intensity import require_counterexample
    original={name:sha256(data[name]).hexdigest() for name in ('parent_body','tile_body')}
    rejected=[]
    # Each SAT result must occur in the intended, activated numerical query.
    # Source, library models and candidate remain immutable; mutate only bytes.
    controls=[
        ('parent_query_advance_frozen','parent_body','query_position_reg[4]','D','query_position[4]',
         'parent_query_pointer_load_hold_advance','advance'),
        ('parent_final_batch_count_stuck16','parent_body','tile','batch_queries',"5'b10000",
         'parent_batch_size_last_and_valid','last_batch'),
        ('parent_query_base_capture_bit_stuck','parent_body','query_addr_reg[6]','D',"1'b1",
         'parent_query_key_base_updates','config_load'),
        ('tile_shared_first_query_bit_lost','tile_body','first_query_reg[5]','D',"1'b0",
         'tile_shared_geometry_snapshot_load_and_hold','batch_load'),
        ('tile_inner_alias_bit_wrong','tile_body','tile_start_reg[22]','D',"1'b1",
         'tile_shared_geometry_snapshot_load_and_hold','batch_load'),
        ('recent_causal_limit_capture_bit_lost','tile_body','row_limits_reg[12]','D',"1'b0",
         'all18_causal_row_limit_updates','capture'),
        ('recent_causal_limit_saturates_prematurely','tile_body','row_limits_reg[17]','D',"1'b1",
         'all18_causal_row_limit_updates','capture'),
        ('row_limit_stall_retention_lost','tile_body','row_limits_reg[12]','D',"1'b0",
         'all18_causal_row_limit_updates','stall'),
        ('row_limit_capture_enable_frozen','tile_body','row_limits_reg[17]','E',"1'b0",
         'all18_causal_row_limit_updates','capture_boundary'),
        ('tile_geometry_reset_disconnected','tile_body','first_query_reg[0]','CDN',"1'b1",
         'tile_geometry_reset_bindings','reset')]
    for label,part,instance,pin,replacement,query_label,mode in controls:
        altered=replace_instance_pin(data[part],instance,pin,replacement.encode())
        p,t,raw=geometry_models(data,**{part:altered})
        if part=='parent_body':
            pq=register_vector(p,'query_position',range(13))['old']
            pt=register_vector(p,'tokens',range(11))['old']
            ps=register_vector(p,'state',range(3))['old']
            active=[p.boolean('rst_n')]
            if mode=='advance':
                active.extend([ps==3,pq==96,pt==128,bound_parent_port(p,raw,'batch_ready',1),
                               mapped_word(t,'state',3)==0,z3.Not(mapped_word(p,'batch_failed',1))])
            elif mode=='last_batch':active.extend([ps==2,pq==96,pt==97,mapped_word(t,'state',3)==0])
            else:active.extend([ps==0,p.boolean('cfg_valid'),p.word('cfg_query_base',64)==0,
                p.word('cfg_key_base',64)==0,p.word('cfg_tokens',11)==128,p.word('cfg_ratio_den',8)==1,
                register_vector(p,'state',range(3))['data']==1])
            function=lambda:prove_parent_geometry(p,raw,only_query=query_label,activation=active)
        else:
            parent=prove_parent_geometry(p,raw)
            ps=parent['state']['old'];ts=register_vector(t,'state',range(3))['old']
            active=[t.boolean('rst_n')]
            if mode=='batch_load':active.extend([ps==2,ts==0,parent['query']['old']==96,parent['tokens']['old']==128])
            elif mode in ('capture','capture_boundary','stall'):
                query,total,count,index=(112,128,16,15) if mode=='capture_boundary' else (96,97,1,0)
                old_limits=(32|(32<<6)|(31<<12)) if mode=='capture_boundary' else (32|(32<<6)|(1<<12)) if mode=='stall' else 0
                active.extend([ps==3,ts==(4 if mode=='stall' else 3),parent['query']['old']==query,parent['tokens']['old']==total,
                    register_vector(t,'first_query',range(13))['old']==query,
                    register_vector(t,'tensor_cfg_tokens',range(5))['old']==count,
                    register_vector(t,'token_index',range(4))['old']==index,
                    register_vector(t,'key_index',range(7))['old']==95,
                    register_vector(t,'score_beat',range(4))['old']==0,
                    register_vector(t,'row_limits',range(18))['old']==old_limits,
                    register_vector(t,'tensor_cfg_dense_rows',range(11))['old']==total,
                    register_vector(t,'tensor_cfg_activation_base',range(64))['old']==parent['query_addr']['old'],
                    register_vector(t,'tensor_cfg_weight_base',range(64))['old']==parent['key_base']['old'],
                    z3.Not(t.boolean('tensor_done_valid')),t.boolean('tensor_out_valid')==(mode!='stall'),
                    t.word('tensor_out_tag',32)==register_vector(t,'tensor_cfg_tag',range(32))['old'],
                    t.word('tensor_out_token',4)==index,t.boolean('tensor_out_last'),t.word('tensor_out_count',8)==96])
                if mode=='stall':active.append(z3.Not(t.boolean('score_ready')))
            else:active=[z3.Not(t.boolean('rst_n'))]
            function=lambda:prove_tile_geometry(t,p,raw,parent,only_query=query_label,activation=active)
        try:function()
        except AssertionError as error:
            require_counterexample(error,expected_query=query_label)
            rejected.append(dict(control=label,instance=instance,pin=pin,result='sat',rejection_query=query_label,
                                 activation=mode))
        else:raise AssertionError(('Geometry corruption accepted',label))
    altered=replace_instance_pin(data['tile_body'],'first_query_reg[0]','CP',b"1'b0")
    p,t,raw=geometry_models(data,tile_body=altered)
    parent=prove_parent_geometry(p,raw)
    try:prove_tile_geometry(t,p,raw,parent)
    except AssertionError as error:
        assert str(error)=='Tile register clock differs',('Unrelated geometry clock rejection',str(error))
        rejected.append(dict(control='tile_geometry_wrong_clock',rejection='Tile register clock differs'))
    else:raise AssertionError('Wrong tile geometry clock accepted')
    assert len(rejected)==11 and all(sha256(data[name]).hexdigest()==digest for name,digest in original.items())
    return rejected


def verify(output):
    from hashlib import file_digest
    import json
    import resource
    import time
    from prove_tri_oracle_packaged_products import ROOT,memory_guard
    from prove_tri_oracle_head_score_frontend import revalidate_evidence
    assert not Path('/.dockerenv').exists()
    assert output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);started=time.monotonic();evidence={}
    def pin(path,wanted=None):
        with path.open('rb') as f:digest=file_digest(f,'sha256').hexdigest()
        assert wanted is None or digest==wanted,('Changed geometry input',path)
        name=str(path.relative_to(ROOT));assert evidence.setdefault(name,digest)==digest
        return path
    data=load_models(pin)
    for path in [Path(__file__),ROOT/'syn/test_tri_oracle_tile_geometry_logic.py',
                 ROOT/'verilog/tri_oracle_attention_head_predictor415.sv',ROOT/'verilog/tri_oracle_attention_tile_batch413.sv']:
        pin(path.resolve())
    p,t,raw=geometry_models(data)
    parent=prove_parent_geometry(p,raw)
    print('PARENT_GEOMETRY_COMPONENTS_PROVED',flush=True)
    tile=prove_tile_geometry(t,p,raw,parent)
    print('TILE_GEOMETRY_COMPONENTS_PROVED',flush=True)
    coupled=prove_coupled_epoch(p,t,raw,parent,tile)
    print('COUPLED_ACTUAL_GEOMETRY_INDUCTION_PROVED',flush=True)
    rejected=rejection_controls(data)
    print('ALL_GEOMETRY_CORRUPTION_CONTROLS_REJECTED',flush=True)
    revalidate_evidence(evidence,ROOT)
    result=dict(state='mapped_parent_tile_geometry_and_causal_limits_verified',candidate_sha256=data['candidate_sha256'],
        parent_sha256=p.model.body_sha256,tile_sha256=t.model.body_sha256,
        parent_checks=p.checks,tile_checks=t.checks,parent_tile_epoch=tile['parent_tile_epoch'],
        coupled_geometry_induction=coupled,
        invariant_consistent_capture_satisfiability_witnesses=tile['invariant_capture_satisfiability_witnesses'],used_tile_inputs=t.bound_inputs,
        parent_query_pointer_range_condition='Accepted parent configuration97..2047 tokens; query starts96 and advances only by min(16,tokens-query) before the final batch.',
        inherited_common_reset_and_binary_settled_edge_conditions=True,
        rejected_controls=rejected,corruption_controls_verified=True,tensor_command_generation_verified=False,
        tile_score_production_verified=False,full_head_prediction_verified=False,task_accuracy_verified=False,
        physical_timing_verified=False,complete_paper_architecture_verified=False,advance_to_clock_distribution_or_routing_allowed=False,
        evidence_sha256=evidence,wall_seconds=time.monotonic()-started,
        peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    with output.open('x') as f:f.write(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    import argparse
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(3*2**30,3*2**30))
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    result=verify(parser.parse_args().output)
    print(result['state'],result['wall_seconds'],flush=True)
