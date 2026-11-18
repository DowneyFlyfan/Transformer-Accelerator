"""Prove mapped parent score forwarding and owned classifier input routes.

Tile outputs are independent binary cutpoints. This does not prove the tile's
score arithmetic, complete response tags, eventual completion or timing.
"""
if not __debug__:
    raise RuntimeError('Score frontend verification requires Python assertions')
from pathlib import Path
import z3
from prove_tri_oracle_head_intensity import WordBridge,require_counterexample
from prove_tri_oracle_head_ratio_sequence import equal_functions


def port_value(model,bridge,pins,name,width):
    bits=model.module.expression(pins[name])
    assert len(bits)==width,('Tile semantic port width differs',name)
    roots=bridge.convert([model.cone(bit) for bit in reversed(bits)])
    return bridge.pack(roots) if width>1 else roots[0]


def check_tag_guard(model,bridge,pins,saved_tag_bits,guarded_region_bits,*,mismatch_only=False):
    actual_tag=port_value(model,bridge,pins,'score_tag',len(saved_tag_bits))
    stored=bridge.pack(bridge.convert([model.cone(bit) for bit in saved_tag_bits]))
    region=port_value(model,bridge,pins,'score_region',2)
    actual=bridge.pack(bridge.convert([model.cone(bit) for bit in guarded_region_bits]))
    expected=z3.If(actual_tag==stored,region,z3.BitVecVal(3,2))
    conditions=[actual_tag!=stored,region==0] if mismatch_only else []
    bridge.check([actual],[expected],label='parent_score_tag_invalid_region_guard',conditions=conditions)


def prove_parent_frontend(model):
    bridge=WordBridge(model.graph);_,pins=model.module.cells['tile']
    check_tag_guard(model,bridge,pins,[f'head_request[{360+bit}]' for bit in range(32)],
                    [f'head_request[{264+bit}]' for bit in range(2)])
    for pin,start,width in [('score_data',0,256),('score_lanes',256,8),('score_last',298,1),('score_valid',393,1)]:
        roots=bridge.convert([model.cone(f'head_request[{start+bit}]') for bit in range(width)])
        actual=bridge.pack(roots) if width>1 else roots[0]
        bridge.check([actual],[port_value(model,bridge,pins,pin,width)],label='parent_'+pin+'_forwarding')
    bridge.check([port_value(model,bridge,pins,'score_ready',1)],
                 [bridge.boolean('head_response[71]')],label='parent_selected_classifier_ready_feedback')
    saved_tag=bridge.pack(bridge.convert([model.cone(f'head_request[{360+bit}]') for bit in range(32)]))
    bridge.check([port_value(model,bridge,pins,'batch_tag',32)],[saved_tag],label='parent_batch_tag_forwarding')
    next_tokens=[];stored_bits=[];resets=[];next_state=[]
    for bit in range(11):
        instance=f'tokens_reg[{bit}]';_,raw=model.module.cells[instance]
        output,=model.module.expression(raw['Q'])
        data,reset,value=model.transition(instance,output);assert value==0,'Saved token reset value differs'
        next_tokens.append(data);stored_bits.append(model.cone(output));resets.append(reset)
    assert not any(f'tokens_reg[{bit}]' in model.module.cells for bit in (11,12)),'Unexpected wider saved token specialization'
    for bit in range(3):
        data,reset,value=model.transition(f'state_reg[{bit}]',f'state[{bit}]')
        assert value==0,'Parent state reset differs';next_state.append(data);resets.append(reset)
    bridge.check(bridge.convert(resets),[z3.Not(bridge.boolean('rst_n'))]*14,label='parent_token_and_state_reset_bindings')
    stored=bridge.pack(bridge.convert(stored_bits));incoming=bridge.word('cfg_tokens',11)
    state=bridge.word('state',3);load=z3.And(state==0,bridge.boolean('cfg_valid'))
    bridge.check([bridge.pack(bridge.convert(next_tokens))],[z3.If(load,incoming,stored)],
                 label='parent_saved11_token_load_and_hold',conditions=[bridge.boolean('rst_n')])
    # Synthesis shares the two upper subtraction bits at request327. The
    # otherwise unused request326 is undriven and is never read/coerced here.
    row_nets=[f'head_request[{315+bit}]' for bit in range(11)]+['head_request[327]']*2
    row_roots=[model.cone(bit) for bit in row_nets]
    rows=bridge.pack(bridge.convert(row_roots))
    bridge.check([rows],[z3.ZeroExt(2,stored)-z3.BitVecVal(96,13)],label='parent13_row_count_from_shared_sign')
    dependencies=set().union(*(model.graph.dependencies(root) for root in [*next_tokens,*next_state,*row_roots]))
    assert not dependencies & {'cfg_tokens[11]','cfg_tokens[12]'},'Undriven high token inputs affect qualified behavior'
    successor=bridge.pack(bridge.convert(next_state))
    bridge.check([z3.UGT(incoming,96)],[z3.BoolVal(True)],label='parent_accepted_config_has_positive_row_count',
                 conditions=[state==0,bridge.boolean('cfg_valid'),successor==1,bridge.boolean('rst_n')])
    witnesses=[]
    for tokens in (97,2047):
        solver=z3.SolverFor('QF_BV');solver.set(timeout=30000,max_memory=512)
        solver.add(state==0,bridge.boolean('cfg_valid'),successor==1,incoming==tokens,
                   bridge.word('cfg_ratio_den',8)==1,bridge.word('cfg_query_base',64)==0,
                   bridge.word('cfg_key_base',64)==0,bridge.boolean('rst_n'))
        result=solver.check();assert result==z3.sat,('Token acceptance witness missing',tokens,str(result))
        witnesses.append(tokens)
    return dict(module_sha256=model.body_sha256,checks=bridge.checks,saved_token_bits=11,
        accepted_token_minimum=97,represented_token_maximum=2047,accepted_row_minimum=1,accepted_row_maximum=1951,
        endpoint_acceptance_witnesses=witnesses,shared_row_sign_request_bit=327,unused_request_bit326_not_coerced=True,
        unused_high_cfg_token_inputs_do_not_affect_qualified_behavior=True,
        complete_response_tag_behavior_verified=False,tile_score_production_verified=False)


PAYLOAD_FIELDS=[('in_scores',0,256),('in_lanes',256,8),('in_region',264,2),('in_last',298,1),('cfg_rows',315,13)]


def prove_payload_routes(checker):
    assert set(checker.heads)==set(range(20));roots=[];expected=[];heads=[]
    for owner,path in sorted(checker.heads.items()):
        checker.guard();module=checker.module(checker.contexts[path][0])
        for name,start,width in PAYLOAD_FIELDS:
            assert module.directions[name]=='input'
            assert module.declared[name]==((width-1,0) if width>1 else None),'Payload dimension differs'
            for bit in range(width):
                roots.append(checker.trace(path,f'{name}[{bit}]' if width>1 else name))
                index=327 if name=='cfg_rows' and bit==11 else start+bit
                expected.append(checker.graph.variable(f'scheduler.head_request[{index}]'))
        heads.append(dict(owner=owner,path=path,module=checker.contexts[path][0],module_sha256=module.sha256))
    equal_functions(checker.graph,roots,expected)
    leaves=set().union(*(checker.graph.dependencies(root) for root in roots))
    assert 'scheduler.head_request[326]' not in leaves,'Undriven request326 is consumed by a classifier payload'
    return dict(heads=heads,payload_bits=len(roots),bits_per_classifier=280,shared_row_sign_aliases_per_classifier=2,
        unused_request_bit326_absent_from_qualified_payload_inputs=True,
        parent_module_sha256={name:module.sha256 for name,module in checker.modules.items()})


def revalidate_evidence(evidence,root):
    """Independent final file rehash, without the verifier's mutable locals."""
    from hashlib import file_digest
    assert evidence,'Final evidence inventory is empty'
    for name,wanted in evidence.items():
        with (root/name).open('rb') as stream:actual=file_digest(stream,'sha256').hexdigest()
        assert actual==wanted,('Changed final score-frontend evidence',name)
    return len(evidence)


def inspect_unused_bindings(checker,model):
    assert 'head_request[326]' in model.module.bits and 'head_request[326]' not in model.drivers,'Request326 has an internal driver'
    _,parent,pins=checker.contexts[checker.scheduler]
    owner=checker.module(checker.contexts[parent][0])
    formal=model.module.net_bits('cfg_tokens');actual=owner.expression(pins['cfg_tokens'])
    assert len(formal)==len(actual)==13
    rows=[]
    for bit in (11,12):
        name=f'cfg_tokens[{bit}]';net=actual[formal.index(name)]
        if net.startswith("1'"):
            kind='constant';drivers=[];direction=None
        else:
            drivers=checker.drivers(parent,net);direction=owner.bit_direction(net)
            kind='undriven_internal_net' if not drivers and direction is None else 'port_or_driven_net'
        rows.append(dict(input=name,source_context=parent,source_net=net,source_kind=kind,
            source_port_direction=direction,internal_driver_count=len(drivers),source_module_sha256=owner.sha256))
    return dict(parent_request326_internal_driver_count=0,unused_high_cfg_token_bindings=rows)


def verify(output):
    from hashlib import file_digest,sha256
    import json
    import re
    import resource
    import time
    from link_tri_oracle_indexed_whole_chip import spans,signature,DECLARATION
    from prove_tri_oracle_head_configuration import ParentCone,replace_instance_pin
    from prove_tri_oracle_head_routing import HeadRoutes,routing_libraries
    from prove_tri_oracle_head_ratio_sequence import primary_state
    from prove_tri_oracle_parent_reset import Module
    from prove_tri_oracle_packaged_products import CANDIDATE,ROOT,liberty_group,memory_guard

    assert not Path('/.dockerenv').exists()
    assert output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);started=time.monotonic();evidence={}
    def pin_evidence(path,expected=None):
        with path.open('rb') as stream:actual=file_digest(stream,'sha256').hexdigest()
        assert expected is None or actual==expected,('Changed score-frontend input',path)
        assert evidence.setdefault(str(path.relative_to(ROOT)),actual)==actual
        return path
    prior=json.loads(pin_evidence(ROOT/'records/tri_oracle_packaged_head_intensity.json').read_text())
    for name,digest in prior['evidence_sha256'].items():pin_evidence(ROOT/name,digest)
    full_name,=[name for name in evidence if name.endswith('/intensity_qualified.json')]
    intensity=json.loads((ROOT/full_name).read_text())
    assert intensity['state']==prior['state']=='mapped_local_head_score_packet_intensity_verified'
    for name,digest in intensity['evidence_sha256'].items():pin_evidence(ROOT/name,digest)
    config_name,=[name for name in evidence if name.endswith('/configuration_qualified.json')]
    config=json.loads((ROOT/config_name).read_text())
    assert prior['candidate_sha256']==config['candidate_sha256']==intensity['candidate_sha256']
    structure=json.loads((ROOT/'records/tri_oracle_packaged_compute_structure.json').read_text())
    storage=json.loads((ROOT/'records/tri_oracle_packaged_storage_accounting.json').read_text())
    detail_name,=storage['full_detail_cache']
    detail=json.loads(pin_evidence(ROOT/detail_name,storage['full_detail_cache'][detail_name]).read_text())
    states={name:row['state_kinds'] for name,row in detail['standard_cell_state_by_master'].items()}
    source=CANDIDATE.read_bytes();assert sha256(source).hexdigest()==prior['candidate_sha256']
    pin_evidence(CANDIDATE,prior['candidate_sha256']);definitions=spans(source)
    def body(master):return source[slice(*definitions[master])]
    heads={row['owner']:row['path'] for row in config['routes']['heads']}
    assert set(heads)==set(range(20))
    parent_master=config['scheduler_master'];parent_body=body(parent_master)
    assert sha256(parent_body).hexdigest()==config['parent']['module_sha256']
    for row in config['routes']['heads']:
        assert sha256(body(row['module'])).hexdigest()==row['module_sha256']==intensity['classifiers'][row['module']]['module_sha256']
    sources={};masters=set(storage['compiled_memory_by_master'])
    for corner in ('tt1v25c','ssg0p9v125c','ffg1p05vm40c'):
        rows=[(name,digest) for name,digest in structure['evidence_sha256'].items() if name.endswith(corner+'.lib')]
        assert len(rows)==7
        sources[corner]=[pin_evidence(ROOT/name,digest) for name,digest in rows]
        standard,=(path for path in sources[corner] if path.name.startswith('tcbn28'))
        masters.update(name.strip() for name in re.findall(r'(?m)^cell\s*\(([^)]+)\)\s*\{',standard.read_text()))
    tables=routing_libraries(sources,masters);parent_module=Module(parent_body)
    sequential={parent_module.cells[f'tokens_reg[{bit}]'][0] for bit in range(11)}
    sequential.update(parent_module.cells[f'state_reg[{bit}]'][0] for bit in range(3))
    for corner,library in tables.items():
        standard,=(path for path in sources[corner] if path.name.startswith('tcbn28'))
        text=standard.read_text()
        for master in sequential:
            match,=re.finditer(r'(?m)^cell\s*\('+re.escape(master)+r'\)\s*\{',text)
            library[master,'__sequence_ff__']=primary_state(liberty_group(text,match.end()))
    libraries=list(tables.values());assert libraries[0]==libraries[1]==libraries[2]
    library=libraries[0]
    tile_children=[(instance,master,pins) for instance,(master,pins) in parent_module.cells.items() if master in definitions]
    (tile_instance,tile_master,tile_pins),=tile_children
    assert tile_instance=='tile' and tile_master.startswith('tri_oracle_attention_tile_batch413')
    tile_body=body(tile_master);signature(tile_body);end=tile_body.index(b');')+2
    child_ports=Module(tile_body[:end]+b'\n'+b'\n'.join(match[0] for match in DECLARATION.finditer(tile_body[end:]))+b'\nendmodule')
    children={tile_master:child_ports}
    for name in ['prove_tri_oracle_head_score_frontend.py','test_tri_oracle_head_score_frontend_logic.py']:pin_evidence(ROOT/'syn'/name)
    checker=HeadRoutes(body,set(definitions),library,states,structure['logical_top'],config['scheduler_path'],heads,
                       guard=lambda:memory_guard(8.5))
    routes=prove_payload_routes(checker);print('ALL20_SCORE_PAYLOAD_ROUTES_PROVED',flush=True)
    model=ParentCone(parent_body,library,states,children)
    parent=prove_parent_frontend(model);print('PARENT_SCORE_TAG_ROW_CONTRACT_PROVED',flush=True)
    unused=inspect_unused_bindings(checker,model)
    # Preserve this first result if later controls reveal a verifier weakness.
    controls=[]
    for label,pin,wanted in [('permuted_score_data','score_data','parent_score_data_forwarding'),
                             ('permuted_lane_mask','score_lanes','parent_score_lanes_forwarding'),
                             ('wrong_selected_ready','score_ready','parent_selected_classifier_ready_feedback')]:
        bits=parent_module.expression(tile_pins[pin])
        value=b'head_response[70]' if pin=='score_ready' else ('{'+','.join(reversed(bits))+'}').encode()
        altered=replace_instance_pin(parent_body,'tile',pin,value)
        try:prove_parent_frontend(ParentCone(altered,library,states,children))
        except AssertionError as error:
            require_counterexample(error,expected_query=wanted)
            controls.append(dict(control=label,rejection_query=wanted,result='sat'))
        else:raise AssertionError(('Score forwarding corruption accepted',label))
    altered=replace_instance_pin(parent_body,'tokens_reg[0]','D',b'head_request[315]')
    try:prove_parent_frontend(ParentCone(altered,library,states,children))
    except AssertionError as error:
        wanted='parent_saved11_token_load_and_hold';require_counterexample(error,expected_query=wanted)
        controls.append(dict(control='frozen_saved_token_load',rejection_query=wanted,result='sat'))
    else:raise AssertionError('Frozen token load accepted')
    # Find a single actual guard input whose stuck value loses rejection for
    # mismatched tags with a valid source region0. Unrelated failures do not pass.
    target='head_request[264]'
    while model.drivers[target][0]=='assign':target=model.drivers[target][1]
    _,kind,pin,_=model.drivers[target]
    guard_instance,guard_pins=next((instance,pins) for instance,(master,pins) in parent_module.cells.items()
        if master==kind and parent_module.expression(pins.get(pin,''))==(target,))
    guard_fault=None
    for input_pin,value in guard_pins.items():
        if library[kind,input_pin]['direction']!='input' or parent_module.expression(value)[0].startswith("1'"):continue
        for stuck in (0,1):
            altered=replace_instance_pin(parent_body,guard_instance,input_pin,f"1'b{stuck}".encode())
            mutated=ParentCone(altered,library,states,children);bridge=WordBridge(mutated.graph)
            try:check_tag_guard(mutated,bridge,mutated.module.cells['tile'][1],
                [f'head_request[{360+bit}]' for bit in range(32)],['head_request[264]','head_request[265]'],mismatch_only=True)
            except AssertionError as error:
                require_counterexample(error,expected_query='parent_score_tag_invalid_region_guard')
                guard_fault=dict(control='lost_mismatched_tag_rejection',instance=guard_instance,pin=input_pin,stuck=stuck,
                    rejection_query='parent_score_tag_invalid_region_guard',result='sat',mismatched_tag_and_source_region_zero_required=True)
                break
        if guard_fault:break
    assert guard_fault,'No intended active mismatch guard fault was rejected';controls.append(guard_fault)
    for label,pin,value in [('disconnected_classifier_rows','cfg_rows',b"13'b0"),('disconnected_classifier_last','in_last',b"1'b0")]:
        path=heads[0];_,parent_context,_=checker.contexts[path];instance=path.rsplit('/',1)[-1]
        master=checker.contexts[parent_context][0]
        altered=replace_instance_pin(body(master),instance,pin,value)
        mutated=HeadRoutes(lambda name:altered if name==master else body(name),set(definitions),library,states,
            structure['logical_top'],config['scheduler_path'],heads,guard=lambda:memory_guard(8.5))
        try:prove_payload_routes(mutated)
        except AssertionError as error:
            assert str(error)=='Mapped sequence transition differs',('Unrelated route rejection',label,str(error))
            controls.append(dict(control=label,rejection='Mapped sequence transition differs'))
        else:raise AssertionError(('Classifier payload corruption accepted',label))
    revalidate_evidence(evidence,ROOT)
    report=dict(state='mapped_parent_score_guard_and_classifier_payload_verified',candidate_sha256=prior['candidate_sha256'],
        routes=routes,parent=parent,unused_bindings=unused,tile_module_sha256=sha256(tile_body).hexdigest(),tile_outputs_are_arbitrary_binary_cutpoints=True,
        rejected_controls=controls,evidence_sha256=evidence,wall_seconds=time.monotonic()-started,
        peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        complete_response_tag_behavior_verified=False,tile_score_production_verified=False,
        full_head_prediction_verified=False,task_accuracy_verified=False,physical_timing_verified=False,
        complete_paper_architecture_verified=False,advance_to_clock_distribution_or_routing_allowed=False,
        scope='Actual tile-port score/lanes/LAST/valid forwarding and selected ready feedback through parent and all20 owned classifier payload paths. '
              'A mismatched binary score tag forces invalid region3, composing with the independently proved local packet rejection rule in active input states. '
              'Eleven actual saved token bits and valid configuration acceptance establish represented tokens97..2047 and rows1..1951. '
              'Both upper classifier row bits share request327; unused undriven request326 is not read or coerced. No source13-bit token-capacity claim. '
              'Common-reset/settled-binary-edge and parent ownership assumptions are inherited from the pinned earlier proofs. '
              'Tile score generation, upstream tensor/tag validity, complete response tags, eventual completion, full prediction, accuracy, timing and paper matching remain unqualified.')
    with output.open('x') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    arguments=parser.parse_args();result=verify(arguments.output)
    print(result['state'],result['wall_seconds'],flush=True)
