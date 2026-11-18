"""Verify mapped tile score-buffer capture and packet-emission components.

Row-limit generation, tensor command geometry and upstream arithmetic are
separate obligations. An unreset buffer must not emit ordinary valid data
before capture. Error packets have explicitly invalid region metadata.
"""
if not __debug__:
    raise RuntimeError('Tile packet verification requires Python assertions')
from pathlib import Path
import re
import z3
from prove_tri_oracle_head_intensity import WordBridge,require_counterexample
from prove_tri_oracle_head_ratio import ClassifierCone
from prove_tri_oracle_packaged_products import BRACES,liberty_group,parse_function,memory_guard


def primary_tile_state(description):
    starts={match.end()-1:match for match in re.finditer(r'\bff\s*\(([^)]*)\)\s*\{',description)}
    direct=[];depth=0
    for token in BRACES.finditer(description):
        if token[0]=='{':
            if depth==0 and token.start() in starts:direct.append(starts[token.start()])
            depth+=1
        elif token[0]=='}':depth-=1
    assert depth==0 and len(direct)==1,'Expected one primary flip-flop'
    match,=direct
    assert [part.strip() for part in match[1].split(',')]==['IQ','IQN'],'Unsupported primary state variables'
    text=liberty_group(description,match.end());attribute=re.compile(r'\b(\w+)\s*:\s*"([^"]*)"\s*;')
    entries=attribute.findall(text);result=dict(entries)
    assert len(result)==len(entries) and not attribute.sub('',text).strip(),'Unknown state statements'
    assert set(result) in [{'clocked_on','next_state'},{'clocked_on','next_state','clear'},
                          {'clocked_on','next_state','preset'}],'Unsupported primary state attributes'
    for expression in result.values():parse_function(expression)
    return result


class TileCone(ClassifierCone):
    def transition(self,instance,expected_output):
        master,raw=self.module.cells[instance]
        assert self.states[master]=={'ff':1},'Unsupported tile state kind'
        pins={name:self.module.expression(value) for name,value in raw.items()}
        description=self.library[master,'__tile_ff__']
        assert parse_function(description['clocked_on'])=='CP' and pins['CP']==('clk',),'Tile register clock differs'
        assert pins['Q']==(expected_output,) and self.library[master,'Q']['function']=='IQ','Tile register output differs'
        state=self.graph.variable(expected_output)
        def function(expression):
            values={'IQ':state,'IQN':self.graph.operation('!',state)}
            for name in set(re.findall(r'[A-Za-z_]\w*',expression))-values.keys():
                assert self.library[master,name]['direction']=='input' and len(pins[name])==1,'Invalid state input'
                values[name]=self.cone(pins[name][0])
            return self.graph.function(expression,values)
        reset='clear' if 'clear' in description else 'preset' if 'preset' in description else None
        return (function(description['next_state']),function(description[reset]) if reset else None,
                int(reset=='preset') if reset else None)


def packet_expressions(bridge,old):
    """Independent word-level packet contract; configuration geometry is opaque."""
    state=old['state'];beat=old['score_beat'];token=old['token_index']
    batch=bridge.boolean('batch_valid');valid=bridge.boolean('tensor_out_valid')
    done=bridge.boolean('tensor_done_valid');ready=bridge.boolean('score_ready')
    last=z3.ZeroExt(1,token)+1==old['tokens']
    bad=z3.Or(bridge.word('tensor_out_tag',32)!=old['tag'],bridge.word('tensor_out_token',4)!=token,
              bridge.boolean('tensor_out_last')!=last,bridge.word('tensor_out_count',8)!=96)
    done_bad=z3.Or(bridge.boolean('tensor_done_error'),bridge.word('tensor_done_tag',32)!=old['tag'],
                  old['extra_packet'],valid)
    capture=z3.And(state==3,z3.Not(done),valid,z3.Not(bad))
    load=z3.And(state==0,batch)
    b=lambda value:z3.BitVecVal(value,3)
    successor={
        1:z3.If(old['key_index']==95,b(2),b(1)),
        2:z3.If(bridge.boolean('tensor_cfg_ready'),b(3),b(2)),
        3:z3.If(done,b(7),z3.If(valid,z3.If(bad,b(6),z3.If(last,b(5),b(4))),b(3))),
        4:z3.If(ready,z3.If(beat==11,z3.If(last,b(0),b(3)),b(4)),b(4)),
        5:z3.If(done,z3.If(done_bad,b(7),b(4)),b(5)),
        6:z3.If(done,b(7),b(6)),7:z3.If(ready,b(0),b(7))}
    fields=dict(
        key_index=z3.If(load,z3.BitVecVal(0,7),z3.If(z3.And(state==1,old['key_index']!=95),old['key_index']+1,old['key_index'])),
        token_index=z3.If(load,z3.BitVecVal(0,4),z3.If(z3.And(state==4,ready,beat==11,z3.Not(last)),token+1,token)),
        score_beat=z3.If(load,z3.BitVecVal(0,4),z3.If(z3.And(state==4,ready),z3.If(beat==11,z3.BitVecVal(0,4),beat+1),beat)),
        extra_packet=z3.If(load,z3.BoolVal(False),z3.If(z3.And(state==5,valid),z3.BoolVal(True),old['extra_packet'])),
        tag=z3.If(load,bridge.word('batch_tag',32),old['tag']),
        tokens=z3.If(load,bridge.word('batch_queries',5),old['tokens']),
        last_batch=z3.If(load,bridge.boolean('batch_last'),old['last_batch']),
        saved_scores=z3.If(capture,bridge.word('tensor_out_data',3072),old['saved_scores']))
    return dict(next_state=successor,fields=fields,capture=capture,last_token=last,done_bad=done_bad)


def packet_safety():
    """Inductive history: ordinary Emit has a captured, current-token buffer.

    Last-token status is stable between configuration/row retirement because
    the proved metadata/token updates hold it. Read captures that same status;
    last rows must pass WaitDone certification before entering Emit. No
    score-buffer reset is assumed. Idle counters may initially be arbitrary.
    """
    from itertools import product
    domain={(0,beat,False,last,False) for beat in range(16) for last in (False,True)}
    domain|={(state,0,False,last,False) for state in (1,2,3,6) for last in (False,True)}
    domain|={(5,0,True,True,False)}
    domain|={(7,0,captured,last,False) for captured in (False,True) for last in (False,True)}
    domain|={(4,beat,True,last,last) for beat in range(12) for last in (False,True)}
    edges=0
    for state,beat,captured,last,certified in domain:
        if state==4:assert captured and 0<=beat<=11 and (not last or certified)
        for batch,bad_cfg,key_terminal,cfg_ready,out_valid,done,bad_packet,done_bad,ready in product((False,True),repeat=9):
            next_state=state;next_beat=beat;next_capture=captured;next_cert=certified;next_lasts=[last]
            if state==0 and batch:
                next_state=7 if bad_cfg else 1;next_beat=0;next_capture=False;next_cert=False;next_lasts=[False,True]
            elif state==1:next_state=2 if key_terminal else 1
            elif state==2:next_state=3 if cfg_ready else 2
            elif state==3:
                if done:next_state=7
                elif out_valid:
                    if bad_packet:next_state=6
                    else:next_state=5 if last else 4;next_capture=True
            elif state==4 and ready:
                if beat==11:
                    next_state=0 if last else 3;next_beat=0;next_capture=False;next_cert=False
                    if not last:next_lasts=[False,True]
                else:next_beat+=1
            elif state==5 and done:
                next_state=7 if done_bad else 4;next_cert=not done_bad
            elif state==6 and done:next_state=7
            elif state==7 and ready:next_state=0;next_capture=False;next_cert=False
            for next_last in next_lasts:
                assert (next_state,next_beat,next_capture,next_last,next_cert) in domain,'Packet history invariant is not closed'
                edges+=1
    return dict(abstract_modes=len(domain),checked_edges=edges,common_reset_state=0,
        score_buffer_reset_assumed=False,ordinary_emit_requires_capture=True,
        normal_emit_beat_bound_verified=True,last_row_emit_requires_completion_certification=True,
        token_retirement_requires_fresh_capture_for_next_ordinary_emit=True,
        inherited_binary_settled_clock_and_valid_tensor_data_required=True,
        eventual_completion_verified=False)


REGISTERS=[('state','state',3),('key_index','key_index',7),('token_index','token_index',4),
           ('score_beat','score_beat',4),('extra_packet','extra_packet',1),
           ('tag','tensor_cfg_tag',32),('tokens','tensor_cfg_tokens',5),('last_batch','last_batch',1),
           ('saved_scores','saved_scores',3072),('row_limits','row_limits',18)]


def packet_query(bridge,actual,expected,*,label,conditions=(),selected_label=None,activation=()):
    if selected_label is not None and label!=selected_label:return False
    bridge.check(actual,expected,label=label,conditions=[*conditions,*activation])
    return True


def prove_packet(model,*,only_query=None,activation=None):
    bridge=WordBridge(model.graph);old={};data={};resets=[];nonreset=0
    for field,prefix,width in REGISTERS:
        outputs=[];updates=[]
        for bit in range(width):
            instance=f'{prefix}_reg[{bit}]' if width>1 else prefix+'_reg'
            _,pins=model.module.cells[instance];output,=model.module.expression(pins['Q'])
            value,reset,reset_value=model.transition(instance,output)
            if field=='saved_scores':assert reset is None and reset_value is None,'Score buffer unexpectedly reset'
            elif reset is not None:
                assert reset_value==0,('Packet register reset value differs',instance);resets.append(reset)
            elif field=='state':raise AssertionError('Tile state requires a reset basis')
            else:nonreset+=1
            outputs.append(model.cone(output));updates.append(value)
        observed=bridge.convert(outputs);updated=bridge.convert(updates)
        old[field]=bridge.pack(observed) if width>1 else observed[0]
        data[field]=bridge.pack(updated) if width>1 else updated[0]
    expected=packet_expressions(bridge,old)
    active=[] if activation is None else activation(bridge,old,expected)
    def check(actual,wanted,*,label,conditions=()):
        return packet_query(bridge,actual,wanted,label=label,conditions=conditions,
                            selected_label=only_query,activation=active)
    check(bridge.convert(resets),[z3.Not(bridge.boolean('rst_n'))]*len(resets),label='tile_packet_reset_bindings')
    check([data['saved_scores']],[expected['fields']['saved_scores']],label='all3072_score_buffer_capture_and_hold',conditions=[bridge.boolean('rst_n')])
    names=['key_index','token_index','score_beat','extra_packet','tag','tokens','last_batch']
    check([data[name] for name in names],[expected['fields'][name] for name in names],
                 label='tile_packet_control_and_metadata_updates',conditions=[bridge.boolean('rst_n')])
    for state in range(8):
        memory_guard(8.5)
        if state==0:
            actual=z3.If(bridge.boolean('batch_valid'),z3.Or(data['state']==1,data['state']==7),data['state']==0)
            check([actual],[z3.BoolVal(True)],label='tile_idle_configuration_successor_domain',conditions=[old['state']==0,bridge.boolean('rst_n')])
        else:
            check([data['state']],[expected['next_state'][state]],label=f'tile_packet_successor_state{state}',
                         conditions=[old['state']==state,bridge.boolean('rst_n')])
    def word(name,width):
        roots=bridge.convert([model.cone(f'{name}[{bit}]') if width>1 else model.cone(name) for bit in range(width)])
        return bridge.pack(roots) if width>1 else roots[0]
    state=old['state'];beat=old['score_beat'];last=expected['last_token'];error=state==7
    check([word('batch_ready',1),word('score_valid',1),word('score_error',1),word('tensor_cfg_valid',1),
                  word('tensor_out_ready',1),word('score_tag',32),word('score_region',2),word('score_last',1)],
                 [state==0,z3.Or(state==4,error),error,state==2,z3.Or(state==3,state==5,state==6),
                  old['tag'],z3.If(error,z3.BitVecVal(3,2),z3.Extract(3,2,beat)),
                  z3.Or(error,z3.And(old['last_batch'],last,beat==11))],label='tile_score_and_tensor_handshake_outputs')
    payload=word('score_data',256);lanes=word('score_lanes',8)
    check([payload,lanes],[z3.BitVecVal(0,256),z3.BitVecVal(0,8)],label='tile_error_score_payload_masking',conditions=[error])
    for index in range(12):
        selected=z3.Extract((index+1)*256-1,index*256,old['saved_scores'])
        limit=z3.Extract((index//4)*6+5,(index//4)*6,old['row_limits'])
        mask=bridge.pack([z3.ULT(z3.BitVecVal(8*(index%4)+lane,6),limit) for lane in range(8)])
        check([payload,lanes],[selected,mask],label=f'tile_score_slice_and_mask_beat{index}',conditions=[state==4,beat==index])
    check([data['row_limits']],[old['row_limits']],label='tile_row_limits_held_during_score_stall',
                 conditions=[state==4,z3.Not(bridge.boolean('score_ready')),bridge.boolean('rst_n')])
    invariant=packet_safety()
    assert only_query is None or len(bridge.checks)==1,'Targeted packet query was not uniquely checked'
    return dict(module_sha256=model.body_sha256,score_buffer_bits=3072,unreset_score_buffer_bits=3072,
        packet_and_mask_register_bits=sum(width for _,_,width in REGISTERS),other_unreset_register_bits=nonreset,
        checked_reset_register_bits=len(resets),checks=bridge.checks,packet_history=invariant,
        complete_packet_query_inventory=(only_query is None),
        configuration_geometry_validation_verified=False,causal_limit_generation_verified=False,
        tensor_command_generation_verified=False,tile_score_production_verified=False,
        scope='Mapped score-buffer capture/hold, packet control, metadata,12 score slices and lane-mask selection given binary row limits. '
              'Configuration geometry validation is conservatively abstracted at Idle; row-limit generation and tensor command/data production remain unqualified. '
              'The reset-based history invariant prevents ordinary Emit before current-token capture and requires final-row completion certification.')


def unused_output_alias(model,parent,instance,alias):
    """Exclude a nominal output only with proof its parent does not read it."""
    assert model.module.directions.get(alias)=='output' and alias not in model.drivers,'Alias has a mapped driver'
    _,pins=parent.cells[instance];net,=parent.expression(pins[alias])
    assert not net.startswith("1'") and parent.bit_direction(net) is None,'Alias is not an internal unused wire'
    uses=[]
    for left,right in parent.assignments.items():
        if left==net or right==net:uses.append(('assign',left))
    for owner,(_,bindings) in parent.cells.items():
        for name,value in bindings.items():
            if owner==instance and name==alias:continue
            if net in parent.expression(value):uses.append((owner,name))
    assert not uses,('Undriven alias is consumed',uses)
    return dict(alias=alias,tile_internal_driver_count=0,parent_wire=net,parent_consumers=0,
        parent_module_sha256=parent.sha256,unused_alias_not_coerced=True)


def rejection_controls(body,library,states):
    from hashlib import sha256
    from prove_tri_oracle_head_configuration import replace_instance_pin
    original=sha256(body).hexdigest();original_library=[(key,dict(row)) for key,row in sorted(library.items())]
    rejected=[]
    capture=lambda b,o,e:[e['capture'],o['tokens']==16,o['token_index']==0,o['score_beat']==0,
                          o['tag']==17,z3.Not(o['last_batch']),b.boolean('tensor_out_data[0]')]
    stall=lambda b,o,e:[o['state']==4,o['score_beat']==0,z3.Not(b.boolean('score_ready')),
                        o['tokens']==16,o['token_index']==0,z3.Not(o['last_batch']),o['saved_scores']==1]
    advance=lambda b,o,e:[o['state']==4,o['score_beat']==0,b.boolean('score_ready'),
                          o['tokens']==16,o['token_index']==0,z3.Not(o['last_batch'])]
    uncertified=lambda b,o,e:[o['state']==5,o['score_beat']==0,o['tokens']==16,o['token_index']==15,
        z3.Not(o['extra_packet']),z3.Not(b.boolean('tensor_done_valid')),z3.Not(b.boolean('tensor_out_valid'))]
    configure=lambda b,o,e:[o['state']==0,b.boolean('batch_valid'),b.boolean('batch_tag[0]'),b.word('batch_queries',5)==16]
    reset=lambda b,o,e:[z3.Not(b.boolean('rst_n'))]
    model=TileCone(body,library,states)
    _,tag_pins=model.module.cells['tensor_cfg_tag_reg[0]']
    tag_data='D' if 'D' in tag_pins else 'DB'
    faults=[
        ('lost_score_capture_bit','saved_scores_reg[0]','DB',b"1'b0",'all3072_score_buffer_capture_and_hold',capture),
        ('score_stall_retention_lost','saved_scores_reg[0]','DA',b"1'b0",'all3072_score_buffer_capture_and_hold',stall),
        ('score_beat_advance_frozen','score_beat_reg[0]','D',b'score_beat[0]','tile_packet_control_and_metadata_updates',advance),
        ('uncertified_last_row_released','state_reg[0]','D',b"1'b0",'tile_packet_successor_state5',uncertified),
        ('captured_tag_bit_stuck_zero','tensor_cfg_tag_reg[0]',tag_data,b"1'b0",'tile_packet_control_and_metadata_updates',configure),
        ('tile_state_reset_disconnected','state_reg[0]','CDN',b"1'b1",'tile_packet_reset_bindings',reset),
    ]
    for label,instance,port,value,query,active in faults:
        altered=replace_instance_pin(body,instance,port,value)
        try:prove_packet(TileCone(altered,library,states),only_query=query,activation=active)
        except AssertionError as error:
            require_counterexample(error,expected_query=query)
            rejected.append(dict(control=label,instance=instance,pin=port,rejection_query=query,result='sat'))
        else:raise AssertionError(('Packet corruption accepted',label))
    # Actual output-gate input faults, activated at a current-token Emit and
    # an Error packet respectively. Do not accept a timeout or another query.
    for target,label,query,active in [
        ('score_data[0]','score_output_gate_stuck','tile_score_slice_and_mask_beat0',
         lambda b,o,e:[o['state']==4,o['score_beat']==0,o['saved_scores']==1,
                        o['tokens']==16,o['token_index']==0,z3.Not(o['last_batch']),o['row_limits']==(32|(32<<6)|(1<<12))]),
        ('score_lanes[0]','error_lane_mask_gate_stuck','tile_error_score_payload_masking',
         lambda b,o,e:[o['state']==7,o['score_beat']==0,o['saved_scores']==1,
                        o['tokens']==16,o['token_index']==15,z3.Not(o['last_batch']),o['row_limits']==(32|(32<<6)|(32<<12))]),
    ]:
        net=target
        while model.drivers[net][0]=='assign':net=model.drivers[net][1]
        _,kind,output_pin,_=model.drivers[net]
        instance,pins=next((name,raw) for name,(master,raw) in model.module.cells.items()
            if master==kind and model.module.expression(raw.get(output_pin,''))==(net,))
        found=None
        for port,value in pins.items():
            if library[kind,port]['direction']!='input':continue
            bits=model.module.expression(value)
            if len(bits)!=1 or bits[0].startswith("1'"):continue
            for stuck in (0,1):
                altered=replace_instance_pin(body,instance,port,f"1'b{stuck}".encode())
                try:prove_packet(TileCone(altered,library,states),only_query=query,activation=active)
                except AssertionError as error:
                    require_counterexample(error,expected_query=query)
                    found=dict(control=label,instance=instance,pin=port,stuck=stuck,rejection_query=query,result='sat')
                    break
            if found:break
        assert found,('No intended output gate fault detected',label)
        rejected.append(found)
    altered=replace_instance_pin(body,'saved_scores_reg[0]','CP',b'score_ready')
    try:prove_packet(TileCone(altered,library,states))
    except AssertionError as error:
        assert str(error)=='Tile register clock differs',('Unrelated clock rejection',str(error))
        rejected.append(dict(control='score_buffer_wrong_clock',rejection='Tile register clock differs'))
    else:raise AssertionError('Wrong score buffer clock accepted')
    assert len(rejected)==9 and sha256(body).hexdigest()==original
    assert [(key,dict(row)) for key,row in sorted(library.items())]==original_library
    return rejected


def verify(output):
    from hashlib import file_digest,sha256
    import json
    import resource
    import time
    from link_tri_oracle_indexed_whole_chip import spans,signature,DECLARATION
    from prove_tri_oracle_parent_clock import read_clock_library
    from prove_tri_oracle_parent_reset import Module
    from prove_tri_oracle_head_configuration import ParentCone
    from prove_tri_oracle_head_score_frontend import port_value,revalidate_evidence
    from prove_tri_oracle_packaged_products import CANDIDATE,ROOT

    assert not Path('/.dockerenv').exists()
    assert output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);started=time.monotonic();evidence={}
    def pin_evidence(path,wanted=None):
        with path.open('rb') as stream:actual=file_digest(stream,'sha256').hexdigest()
        assert wanted is None or actual==wanted,('Changed tile packet input',path)
        assert evidence.setdefault(str(path.relative_to(ROOT)),actual)==actual
        return path
    prior=json.loads(pin_evidence(ROOT/'records/tri_oracle_packaged_head_score_frontend.json').read_text())
    for name,digest in prior['evidence_sha256'].items():pin_evidence(ROOT/name,digest)
    full_name,=[name for name in evidence if name.endswith('/score_frontend_qualified.json')]
    frontend=json.loads((ROOT/full_name).read_text())
    assert frontend['state']==prior['state']=='mapped_parent_score_guard_and_classifier_payload_verified'
    for name,digest in frontend['evidence_sha256'].items():pin_evidence(ROOT/name,digest)
    config_name,=[name for name in evidence if name.endswith('/configuration_qualified.json')]
    config=json.loads((ROOT/config_name).read_text())
    storage=json.loads((ROOT/'records/tri_oracle_packaged_storage_accounting.json').read_text())
    detail_name,=storage['full_detail_cache']
    detail=json.loads(pin_evidence(ROOT/detail_name,storage['full_detail_cache'][detail_name]).read_text())
    states={name:row['state_kinds'] for name,row in detail['standard_cell_state_by_master'].items()}
    source=CANDIDATE.read_bytes();assert sha256(source).hexdigest()==prior['candidate_sha256']==config['candidate_sha256']
    pin_evidence(CANDIDATE,prior['candidate_sha256']);definitions=spans(source)
    parent_body=source[slice(*definitions[config['scheduler_master']])];parent=Module(parent_body)
    assert parent.sha256==frontend['parent']['module_sha256']
    tile_master,tile_pins=parent.cells['tile'];tile_body=source[slice(*definitions[tile_master])]
    assert sha256(tile_body).hexdigest()==frontend['tile_module_sha256']
    tile=Module(tile_body)
    masters={master for module in (tile,parent) for master,_ in module.cells.values() if master!=tile_master}
    sequential={master for master in masters if states.get(master)}
    libraries=[]
    for corner in ('tt1v25c','ssg0p9v125c','ffg1p05vm40c'):
        name,=[name for name in evidence if Path(name).name==f'tcbn28hpcplusbwp12t40p140{corner}.lib']
        path=ROOT/name;raw=read_clock_library(path,masters)
        library={key:{name:value for name,value in row.items() if name in ('direction','function')} for key,row in raw.items()}
        text=path.read_text()
        for master in sequential:
            match,=re.finditer(r'(?m)^cell\s*\('+re.escape(master)+r'\)\s*\{',text)
            library[master,'__tile_ff__']=primary_tile_state(liberty_group(text,match.end()))
        libraries.append(library)
    assert libraries[0]==libraries[1]==libraries[2],'Tile primary or Boolean functions differ across corners'
    library=libraries[0]
    for name in ['prove_tri_oracle_tile_score_packet.py','test_tri_oracle_tile_score_packet_logic.py']:pin_evidence(ROOT/'syn'/name)
    pin_evidence(ROOT/'verilog/tri_oracle_attention_tile_batch413.sv')
    signature(tile_body);end=tile_body.index(b');')+2
    ports=Module(tile_body[:end]+b'\n'+b'\n'.join(match[0] for match in DECLARATION.finditer(tile_body[end:]))+b'\nendmodule')
    parent_model=ParentCone(parent_body,library,states,{tile_master:ports});bridge=WordBridge(parent_model.graph)
    bridge.check([port_value(parent_model,bridge,tile_pins,'clk',1),port_value(parent_model,bridge,tile_pins,'rst_n',1)],
                 [bridge.boolean('clk'),bridge.boolean('rst_n')],label='tile_parent_clock_reset_connections')
    model=TileCone(tile_body,library,states)
    alias=unused_output_alias(model,parent,'tile','tensor_done_ready')
    packet=prove_packet(model)
    assert packet['complete_packet_query_inventory'] and len(packet['checks'])==26
    rejected=rejection_controls(tile_body,library,states)
    revalidate_evidence(evidence,ROOT)
    report=dict(state='mapped_tile_score_buffer_and_packet_components_verified',candidate_sha256=prior['candidate_sha256'],
        tile_master=tile_master,tile_path=config['scheduler_path']+'/tile',packet=packet,unused_ready_alias=alias,
        rejected_controls=rejected,reference_rtl='verilog/tri_oracle_attention_tile_batch413.sv',
        parent_clock_reset_checks=bridge.checks,evidence_sha256=evidence,
        wall_seconds=time.monotonic()-started,peak_host_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        corruption_controls_verified=True,upstream_completion_ready_routing_verified=False,
        configuration_geometry_validation_verified=False,causal_limit_generation_verified=False,
        tensor_command_generation_verified=False,tile_score_production_verified=False,full_head_prediction_verified=False,
        task_accuracy_verified=False,physical_timing_verified=False,complete_paper_architecture_verified=False,
        advance_to_clock_distribution_or_routing_allowed=False)
    with output.open('x') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    arguments=parser.parse_args();result=verify(arguments.output)
    print(result['state'],result['wall_seconds'],flush=True)
