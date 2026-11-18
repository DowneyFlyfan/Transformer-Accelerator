"""Activated defects must fail actual producer, route and receiver checks."""
if not __debug__:raise RuntimeError('Command corruption verification requires Python assertions')
import z3
from hashlib import sha256


def replace_bus_bit(name,width,index,replacement):
    assert type(width) is int and type(index) is int and 0<=index<width,'Corrupted bit outside bus'
    pieces=[]
    if index+1<width:pieces.append(f'{name}[{width-1}:{index+1}]')
    pieces.append(replacement)
    if index:pieces.append(f'{name}[{index-1}:0]')
    return '{'+','.join(pieces)+'}' if len(pieces)>1 else pieces[0]


def selector_inverter_pin(function):
    from prove_tri_oracle_packaged_products import parse_function
    assert parse_function(function)==('!','I'),'Selector fault target is not the actual final inverter'
    return 'I'


def command_corruption_controls(data,environment,routed):
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_intensity import require_counterexample,WordBridge
    from prove_tri_oracle_tile_geometry import geometry_models,prove_parent_geometry,prove_tile_geometry,register_vector
    from prove_tri_oracle_tile_command import prove_command_storage,reference_channel,reference_keep
    from prove_tri_oracle_tile_command_routes import CommandRoutes,route_word
    from prove_tri_oracle_tile_command_capture import prove_owner_captures
    original=sha256(data['tile_body']).hexdigest();routes=environment['routes'];paths=environment['paths'];rejected=[]
    def sat_control(label,query,function,**metadata):
        routes.guard()
        try:function()
        except AssertionError as error:
            require_counterexample(error,expected_query=query)
            rejected.append(dict(control=label,result='sat',rejection_query=query,**metadata))
            print('COMMAND_CORRUPTION_REJECTED',label,query,flush=True)
        else:raise AssertionError(('Command corruption accepted',label))
        routes.guard()
    controls=[
        ('producer_sink_keep_dropped','tensor_cfg_keep_reg[0]',{'D':"1'b0"},0,'write',
         'all2980_command_register_next_values'),
        ('producer_recent_channel_bit_lost','tensor_cfg_channels_reg[1030]',{'D':"1'b0"},64,'write',
         'all2980_command_register_next_values'),
        ('producer_second_query_causal_keep_lost','tensor_cfg_keep_reg[225]',{'D':"1'b0"},65,'second_query',
         'all2980_command_register_next_values'),
        ('producer_write_enable_frozen','tensor_cfg_keep_reg[0]',{'E':"1'b0"},0,'freeze',
         'all2980_command_register_next_values'),
        ('producer_stalled_payload_clobbered','tensor_cfg_keep_reg[0]',{'D':"1'b0",'E':"1'b1"},95,'stall',
         'all_command_payload_held_when_submit_stalls'),
        ('producer_reset_disconnected','tensor_cfg_keep_reg[0]',{'CDN':"1'b1"},0,'reset',
         'all2980_command_register_reset_bindings')]
    for label,instance,pins,key,mode,query in controls:
        altered=data['tile_body']
        for pin,value in pins.items():altered=replace_instance_pin(altered,instance,pin,value.encode())
        p,t,raw=geometry_models(data,tile_body=altered)
        parent=prove_parent_geometry(p,raw);tile=prove_tile_geometry(t,p,raw,parent)
        old={name:field['old'] for name,field in tile['fields'].items()}
        if mode=='reset':active=[z3.Not(t.boolean('rst_n'))]
        else:
            count,total=(2,98) if mode=='second_query' else (1,97)
            active=[t.boolean('rst_n'),parent['state']['old']==3,parent['query']['old']==96,parent['tokens']['old']==total,
                    old['state']==(2 if mode=='stall' else 1),old['query']==96,old['tokens']==count,
                    old['key']==key,old['token']==0,old['beat']==0]
            if mode=='freeze':active.append(z3.Not(t.boolean('tensor_cfg_keep[0]')))
            if mode=='stall':active.append(z3.Not(t.boolean('tensor_cfg_ready')))
        sat_control(label,query,lambda:prove_command_storage(p,t,raw,parent,tile,only_query=query,activation=active),
                    instance=instance,changed_pins=pins,activation=mode,altered_module_sha256=sha256(altered).hexdigest())
    altered=replace_instance_pin(data['tile_body'],'tensor_cfg_keep_reg[0]','CP',b"1'b0")
    p,t,raw=geometry_models(data,tile_body=altered);parent=prove_parent_geometry(p,raw);tile=prove_tile_geometry(t,p,raw,parent)
    try:prove_command_storage(p,t,raw,parent,tile)
    except AssertionError as error:
        assert str(error)=='Tile register clock differs',('Unrelated producer clock rejection',str(error))
        rejected.append(dict(control='producer_command_wrong_clock',rejection=str(error)))
    else:raise AssertionError('Producer wrong clock accepted')
    # Clone only in memory; every other body still comes from the read-only candidate.
    def clone(master,body):
        checker=CommandRoutes(lambda name:body if name==master else routes.body(name),routes.masters,routes.library,routes.states,
            routes.contexts[''][0],tile=paths['tile'],parent=paths['parent'],guard=routes.guard)
        for context,bits in routes.offpath.items():
            context=checker.walk(context);ports=checker.ports(checker.contexts[context][0])
            declared={bit for name,direction in ports.directions.items() if direction=='output' for bit in ports.net_bits(name)}
            assert bits<=declared,'Altered command boundary is not an output'
            checker.offpath[context]=set(bits)
        return checker,WordBridge(checker.graph)
    wrapper=routes.walk(paths['wrapper']);wrapper_master=routes.contexts[wrapper][0];wrapper_body=routes.body(wrapper_master)
    for label,pin,index,replacement,target,role,name,width in [
        ('route_cross_token_keep_stride','cfg_keep',225,'cfg_keep[65]','all2560_owner_keep_input_bits','owner','cfg_keep',2560),
        ('route_recent_key_bit_lost','cfg_channels',1030,"1'b0",'all2560_owner_channel_input_bits','owner','cfg_channels',2560),
        ('route_command_count_wrong','cfg_count',None,"8'd95",'all_owner_command_header_fields','owner','cfg_count',8),
        ('route_owner_valid_dropped','cfg_valid',None,"1'b0",'actual_command_valid_ready_roundtrip','owner','cfg_valid',1),
        ('route_owner_reset_stuck_high','rst_n',None,"1'b1",'producer_and_owner_common_clock_and_reset','owner','rst_n',1)]:
        value=replace_bus_bit(pin,2560,index,replacement) if index is not None else replacement
        altered=replace_instance_pin(wrapper_body,'tensor',pin,value.encode())
        checker,bridge=clone(wrapper_master,altered)
        actual=route_word(checker,bridge,paths[role],name,width,direction='input')
        geometry=routed['geometry'];active=list(routed['conditions'])
        if pin=='cfg_keep':
            actual=z3.Extract(index,index,actual)==1
            expected=reference_keep(geometry['query'],geometry['tokens'],1,65)
            active.extend([geometry['query']==96,geometry['tokens']==2])
        elif pin=='cfg_channels':
            actual=z3.Extract(index,index,actual)==1
            expected=z3.Extract(6,6,reference_channel(geometry['query'],geometry['tokens'],64))==1
            active.extend([geometry['query']==96,geometry['tokens']==1])
        elif pin=='cfg_count':expected=z3.BitVecVal(96,8)
        elif pin=='cfg_valid':expected=routed['accepted'];active.append(routed['accepted'])
        else:expected=bridge.boolean('top.rst_n');active=[z3.Not(expected)]
        sat_control(label,target,lambda:bridge.check([actual],[expected],label=target,conditions=active),
                    instance='tensor',pin=pin,activation='conditional_submit' if pin!='rst_n' else 'reset_low',
                    altered_module_sha256=sha256(altered).hexdigest())
    arbiter=routes.walk(paths['arbiter']);driver,=routes.drivers(arbiter,'attention_selected')
    _,instance,master,pin,offset,width,pins=driver
    assert offset==0 and width==1,'Selector fault target is not scalar'
    input_pin=selector_inverter_pin(routes.library[master,pin]['function'])
    arbiter_master=routes.contexts[arbiter][0];body=routes.body(arbiter_master)
    altered=replace_instance_pin(body,instance,input_pin,b"1'b1")
    checker,bridge=clone(arbiter_master,altered)
    actual=route_word(checker,bridge,paths['arbiter'],'attention_selected',1)
    query='actual_attention_selection_paired_and_owner_ready'
    sat_control('route_attention_selector_forced_inactive',query,
                lambda:bridge.check([actual],[z3.BoolVal(True)],label=query,conditions=routed['conditions']),
                instance=instance,pin='I',activation='conditional_submit',altered_module_sha256=sha256(altered).hexdigest())
    owner=routes.walk(paths['owner']);owner_body=routes.body(routes.contexts[owner][0])
    for label,instance,pins,query,mode in [
        ('receiver_sink_keep_dropped','keep_reg[0]',{'D':"1'b0"},'all5120_receiver_command_accepted_payload','accept'),
        ('receiver_capture_enable_frozen','keep_reg[0]',{'E':"1'b0"},'all5120_receiver_command_exact_capture_or_hold','freeze'),
        ('receiver_cross_token_keep_stride','keep_reg[225]',{'D':'cfg_keep[65]'},'all5120_receiver_command_accepted_payload','second_query'),
        ('receiver_stalled_data_clobbered','keep_reg[0]',{'D':"1'b0",'E':"1'b1"},'all5120_receiver_command_retained_without_acceptance','stall'),
        ('receiver_reset_disconnected','keep_reg[0]',{'CDN':"1'b1"},'all5120_receiver_command_reset_bindings','reset')]:
        altered=owner_body
        for pin,value in pins.items():altered=replace_instance_pin(altered,instance,pin,value.encode())
        if mode=='reset':active=[z3.Not(routed['bridge'].boolean('top.rst_n'))]
        else:
            active=list(routed['conditions'])
            active.append(z3.Not(routed['accepted']) if mode=='stall' else routed['accepted'])
            if mode=='freeze':active.append(z3.Not(routed['bridge'].boolean(paths['owner']+'.keep[0]')))
            if mode=='stall':active.append(routed['bridge'].boolean(paths['owner']+'.keep[0]'))
            if mode=='second_query':active.extend([routed['geometry']['query']==96,routed['geometry']['tokens']==2])
        sat_control(label,query,lambda:prove_owner_captures(environment,routed,body=altered,only_query=query,activation=active),
                    instance=instance,changed_pins=pins,activation=mode,altered_module_sha256=sha256(altered).hexdigest())
    altered=replace_instance_pin(owner_body,'keep_reg[0]','CP',b"1'b0")
    try:prove_owner_captures(environment,routed,body=altered)
    except AssertionError as error:
        assert str(error)=='Tile register clock differs',('Unrelated receiver clock rejection',str(error))
        rejected.append(dict(control='receiver_command_wrong_clock',rejection=str(error)))
    else:raise AssertionError('Receiver wrong clock accepted')
    assert len(rejected)==19 and sha256(data['tile_body']).hexdigest()==original,'Corruption inventory or original source changed'
    return rejected
