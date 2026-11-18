"""Verify mapped command storage, initialization and actual tensor input route."""
if not __debug__:raise RuntimeError('Command verification requires Python assertions')
import z3
import re
from pathlib import Path

def key_for_column(query,column):
    assert query.size()==13 and type(column) is int and 0<=column<96
    recent=z3.ZeroExt(4,query)&z3.BitVecVal(131040,17)
    region,offset=divmod(column,32)
    return z3.BitVecVal(column,17) if region==0 else recent+(offset-64 if region==1 else offset)

def reference_keep(query,count,row,column):
    assert query.size()==13 and count.size()==5 and type(row) is int and 0<=row<16
    assert type(column) is int and 0<=column<160
    if column>=96:return z3.BoolVal(False)
    return z3.And(z3.ULT(z3.BitVecVal(row,5),count),z3.ULE(key_for_column(query,column),z3.ZeroExt(4,query)+row))

def reference_channel(query,count,column):
    assert query.size()==13 and count.size()==5 and type(column) is int and 0<=column<160
    if column>=96:return z3.BitVecVal(0,16)
    key=key_for_column(query,column);last=z3.ZeroExt(4,query)+z3.ZeroExt(12,count)-1
    return z3.If(z3.ULE(key,last),z3.Extract(15,0,key),z3.BitVecVal(0,16))

def decode_keep_index(index):
    assert type(index) is int and 0<=index<2560,'Invalid160-column keep bit'
    return divmod(index,160)

def initialized_column(state,key,column):
    assert state.size()==3 and key.size()==7 and type(column) is int and 0<=column<160
    if column>=96:return z3.BoolVal(True)
    return z3.Or(z3.UGE(state,2),z3.And(state==1,z3.UGT(key,column)))


def command_registers(bridge):
    records=[]
    for instance,(master,pins) in bridge.model.module.cells.items():
        match=re.fullmatch(r'(tensor_cfg_keep|tensor_cfg_channels)_reg\[(\d+)\]',instance)
        if not match:continue
        prefix,index=match[1],int(match[2]);assert 0<=index<2560
        output,=bridge.model.module.expression(pins['Q'])
        assert output==f'{prefix}[{index}]','Command register semantic output differs'
        update,reset,reset_value=bridge.model.transition(instance,output)
        assert reset is not None and reset_value==0,'Command register reset differs'
        old,=bridge.convert([bridge.model.cone(output)]);next_bit,=bridge.convert([update]);clear,=bridge.convert([reset])
        row,column=decode_keep_index(index) if prefix=='tensor_cfg_keep' else divmod(index,16)
        # Channels use column-major16-bit words; keep uses token-major160-bit rows.
        if prefix=='tensor_cfg_channels':column,word_bit=row,column;row=None
        else:word_bit=None
        records.append(dict(instance=instance,index=index,prefix=prefix,column=column,row=row,word_bit=word_bit,
            old=old,data=next_bit,reset=clear,reset_value=reset_value))
    assert sum(x['prefix']=='tensor_cfg_keep' for x in records)==2048,'Retained keep inventory differs'
    assert sum(x['prefix']=='tensor_cfg_channels' for x in records)==932,'Retained channel inventory differs'
    assert len({x['instance'] for x in records})==len(records)==2980
    return records


def command_reference_bit(record,geometry):
    if record['prefix']=='tensor_cfg_keep':
        return reference_keep(geometry['query'],geometry['tokens'],record['row'],record['column'])
    word=reference_channel(geometry['query'],geometry['tokens'],record['column'])
    return z3.Extract(record['word_bit'],record['word_bit'],word)==1


def command_invariant(records,geometry,*,next_state=False,reset=False):
    clauses=[]
    for record in records:
        actual=z3.BoolVal(False) if reset else record['data' if next_state else 'old']
        initialized=initialized_column(geometry['state'],geometry['key'],record['column'])
        clauses.append(z3.Implies(initialized,actual==command_reference_bit(record,geometry)))
    return z3.And(*clauses)


def prove_command_storage(parent_bridge,tile_bridge,raw,parent,tile,*,only_query=None,activation=()):
    from prove_tri_oracle_tile_geometry import epoch_invariant,bound_parent_port,mapped_word,geometry_check
    records=command_registers(tile_bridge);initial=len(tile_bridge.checks)
    fields=tile['fields'];old={name:field['old'] for name,field in fields.items()}
    following={name:field['data'] for name,field in fields.items()}
    reset={name:z3.BitVecVal(field['reset_value'],field['bits']) for name,field in fields.items()}
    old_parent={name:parent[name]['old'] for name in ('state','query','tokens','query_addr','key_base')}
    scalar=epoch_invariant(old_parent,old);rst=tile_bridge.boolean('rst_n')
    ready=bound_parent_port(parent_bridge,raw,'batch_ready',1)==mapped_word(tile_bridge,'batch_ready',1)
    def check(actual,wanted,*,label,conditions=()):
        return geometry_check(tile_bridge,actual,wanted,label=label,conditions=conditions,
                              only_query=only_query,activation=activation)
    check([x['reset'] for x in records],[z3.Not(rst)]*len(records),label='all2980_command_register_reset_bindings')
    expected=[]
    for record in records:
        write=z3.And(old['state']==1,old['key']==record['column']) if record['column']<96 else z3.BoolVal(False)
        expected.append(z3.If(write,command_reference_bit(record,old),record['old']))
    check([x['data'] for x in records],expected,label='all2980_command_register_next_values',conditions=[rst,scalar])
    invariant=command_invariant(records,old)
    check([command_invariant(records,reset,reset=True)],[z3.BoolVal(True)],label='command_initialization_reset_basis')
    check([command_invariant(records,following,next_state=True)],[z3.BoolVal(True)],
          label='command_actual_prefix_initialization_induction',conditions=[rst,scalar,ready,invariant])
    check([x['data'] for x in records],[x['old'] for x in records],label='all_command_payload_held_when_submit_stalls',
          conditions=[rst,scalar,invariant,old['state']==2,z3.Not(tile_bridge.boolean('tensor_cfg_ready'))])
    assert only_query is None or len(tile_bridge.checks)==initial+1,'Targeted command query absent'
    return dict(records=records,old_scalar=old,invariant=invariant,scalar_invariant=scalar,
        register_bits=len(records),keep_bits=2048,channel_bits=932,padding_register_bits=sum(x['column']>=96 for x in records),
        reset_basis_verified=True,actual_prefix_initialization_induction_verified=True,
        completed_columns=96,keep_token_stride=160,output_valid_state=2,
        full_consumer_routing_verified=False)


def verify(output):
    from hashlib import file_digest
    import json
    import resource
    import time
    from prove_tri_oracle_packaged_products import ROOT,memory_guard
    from prove_tri_oracle_tile_geometry import load_models,geometry_models,prove_parent_geometry,prove_tile_geometry,prove_coupled_epoch
    from prove_tri_oracle_head_score_frontend import revalidate_evidence
    assert not Path('/.dockerenv').exists()
    assert output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);start=time.monotonic();evidence={}
    def pin(path,wanted=None):
        with path.open('rb') as f:digest=file_digest(f,'sha256').hexdigest()
        assert wanted is None or wanted==digest,('Changed command proof input',path)
        name=str(path.relative_to(ROOT));assert evidence.setdefault(name,digest)==digest
        return path
    prior=json.loads(pin(ROOT/'records/tri_oracle_packaged_tile_geometry.json').read_text())
    assert prior['state']=='mapped_parent_tile_geometry_and_causal_limits_verified'
    for name,digest in prior['evidence_sha256'].items():pin(ROOT/name,digest)
    full_name,=[name for name in prior['evidence_sha256'] if name.endswith('/geometry_final_checked.json')]
    full=json.loads((ROOT/full_name).read_text())
    for name,digest in full['evidence_sha256'].items():pin(ROOT/name,digest)
    for path in [Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_tile_command_logic.py',
                 ROOT/'syn/prove_tri_oracle_tile_command_routes.py',ROOT/'syn/test_tri_oracle_tile_command_routes_logic.py',
                 ROOT/'syn/prove_tri_oracle_tile_command_capture.py',ROOT/'syn/prove_tri_oracle_tile_command_controls.py',
                 ROOT/'syn/test_tri_oracle_tile_command_controls_logic.py']:pin(path)
    data=load_models(pin);assert data['candidate_sha256']==prior['candidate_sha256']
    p,t,raw=geometry_models(data)
    parent=prove_parent_geometry(p,raw);tile=prove_tile_geometry(t,p,raw,parent)
    prove_coupled_epoch(p,t,raw,parent,tile)
    command=prove_command_storage(p,t,raw,parent,tile)
    from prove_tri_oracle_tile_command_routes import command_route_environment,prove_command_routes
    with command_route_environment(pin) as environment:
        assert environment['candidate_sha256']==data['candidate_sha256']
        routed=prove_command_routes(environment,p,t,parent,tile,command)
        from prove_tri_oracle_tile_command_capture import prove_owner_captures
        receiver=prove_owner_captures(environment,routed)
        from prove_tri_oracle_tile_command_controls import command_corruption_controls
        corruptions=command_corruption_controls(data,environment,routed)
        routes=environment['routes']
        route_report={name:routed[name] for name in ('owner','witnesses','queries','channels_verified_bits','keep_verified_bits',
            'header_fields','conditional_consumer_routing_verified','upstream_mode_reachability_verified')}
        route_report.update(module_sha256={name:module.sha256 for name,module in routes.modules.items()},
                            graph_nodes=len(routes.graph.nodes),sequential_cut_bits=len(routes.sequential_cuts))
    revalidate_evidence(evidence,ROOT)
    report=dict(state='mapped_command_storage_conditional_routes_and_receiver_capture_verified',
        candidate_sha256=data['candidate_sha256'],parent_sha256=p.model.body_sha256,tile_sha256=t.model.body_sha256,
        scalar_parent_queries=p.checks,tile_and_command_queries=t.checks,
        producer={name:value for name,value in command.items() if name not in ('records','old_scalar','invariant','scalar_invariant')},
        conditional_routes=route_report,
        receiver=receiver,
        rejected_corruptions=corruptions,
        evidence_sha256=evidence,wall_seconds=time.monotonic()-start,
        peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        full_consumer_routing_verified=False,corruption_controls_verified=True,
        tensor_command_generation_verified=False,tile_score_production_verified=False,full_head_prediction_verified=False,
        task_accuracy_verified=False,physical_timing_verified=False,complete_paper_architecture_verified=False,
        advance_to_clock_distribution_or_routing_allowed=False)
    with output.open('x') as f:f.write(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    import argparse,resource
    resource.setrlimit(resource.RLIMIT_AS,(3*2**30,3*2**30))
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    result=verify(parser.parse_args().output)
    print(result['state'],result['wall_seconds'],flush=True)
