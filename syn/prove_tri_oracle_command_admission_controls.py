"""Activated mapped faults for header capture and address admission."""
if not __debug__:raise RuntimeError('Admission corruption checks require Python assertions')
from hashlib import sha256
import z3


def rejection_controls(data,environment,routed,address):
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_intensity import require_counterexample
    from prove_tri_oracle_tile_geometry import geometry_models,register_vector
    from prove_tri_oracle_command_admission import prove_parent_addresses,prove_receiver_admission
    routes=environment['routes'];owner=environment['paths']['owner'];rejected=[]
    def reject(label,query,function,**metadata):
        routes.guard()
        try:function()
        except AssertionError as error:
            require_counterexample(error,expected_query=query)
            rejected.append(dict(control=label,result='sat',query=query,**metadata))
            print('ADMISSION_CORRUPTION_REJECTED',label,query,flush=True)
        else:raise AssertionError(('Admission corruption accepted',label))
        routes.guard()
    def fields(p,t):
        parent={name:register_vector(p,prefix,range(width)) for name,prefix,width in (
            ('state','state',3),('query','query_position',13),('tokens','tokens',11),
            ('query_addr','query_addr',64),('key_base','key_base',64))}
        tile=dict(fields={name:register_vector(t,prefix,indices) for name,prefix,indices in (
            ('query','first_query',range(13)),('inner','tile_start',range(22,30)),
            ('rows','tensor_cfg_dense_rows',range(11)),('query_addr','tensor_cfg_activation_base',range(64)),
            ('key_base','tensor_cfg_weight_base',range(64)),('state','state',range(3)),
            ('tokens','tensor_cfg_tokens',range(5)),('tag','tensor_cfg_tag',range(32)),
            ('token','token_index',range(4)),('key','key_index',range(7)),('beat','score_beat',range(4)),
            ('limits','row_limits',range(18)))})
        return parent,tile
    originals={name:sha256(data[name]).hexdigest() for name in ('parent_body','tile_body')}
    for label,instance,pin,value,query,query_base,key_base in (
        ('query_overflow_rejection_state_lost','state_reg[2]','D',"1'b0",'parent_observed_configuration_admission',2**64-56,0),
        ('key_overflow_rejection_state_lost','state_reg[2]','D',"1'b0",'parent_observed_configuration_admission',0,2**64-97*64+8),
        ('query_capture_creates_wrapped_span','query_addr_reg[63]','D',"1'b1",'parent_actual_address_invariant_induction',2**63-56,0)):
        altered=replace_instance_pin(data['parent_body'],instance,pin,value.encode())
        p,t,raw=geometry_models(data,parent_body=altered);parent,tile=fields(p,t)
        active=[p.boolean('rst_n'),parent['state']['old']==0,p.boolean('cfg_valid'),p.word('cfg_tokens',11)==97,
                p.word('cfg_ratio_den',8)==1,p.word('cfg_query_base',64)==query_base,p.word('cfg_key_base',64)==key_base]
        reject(label,query,lambda:prove_parent_addresses(p,t,raw,parent,tile,only_query=query,activation=active),
               instance=instance,pin=pin,activation='idle_config_load',altered_module_sha256=sha256(altered).hexdigest())
    context=routes.walk(owner);body=routes.body(routes.contexts[context][0]);b=routed['bridge']
    local=lambda name:b.boolean(owner+'.'+name)
    for label,instance,pins,query,mode in (
        ('header_tag_bit_lost','tag_reg[0]',{'D':"1'b0"},'all313_header_register_capture_or_hold','tag'),
        ('header_query_base_bit_lost','activation_base_reg[3]',{'D':"1'b0"},'all313_header_register_capture_or_hold','address'),
        ('header_feature_partition_bit_wrong','part_words_reg[1]',{'D':'cfg_feature_words[2]'},'all313_header_register_capture_or_hold','partition'),
        ('header_paired_capture_enable_frozen','paired_reg',{'E':"1'b0"},'all313_header_register_capture_or_hold','paired'),
        ('header_packed_capture_enable_frozen','packed_weights_reg',{'E':"1'b0"},'all313_header_register_capture_or_hold','packed'),
        ('header_cluster_mode_stuck','local_scores_reg',{'D':"1'b1"},'all313_header_register_capture_or_hold','cluster'),
        ('header_core_mode_stuck','single_core_scores_reg',{'D':"1'b1"},'all313_header_register_capture_or_hold','core'),
        ('header_owner_cluster_bit_lost','score_cluster_reg[2]',{'D':"1'b0"},'all313_header_register_capture_or_hold','owner'),
        ('header_stalled_tag_clobbered','tag_reg[0]',{'D':"1'b0",'E':"1'b1"},'all313_header_register_retained_without_acceptance','stall'),
        ('header_reset_disconnected','tag_reg[0]',{'CDN':"1'b1"},'all319_header_control_reset_bindings','reset'),
        ('accepted_header_error_forced','done_error_reg',{'D':"1'b1"},'accepted_attention_header_enters_validate_without_error','accepted'),
        ('accepted_header_validate_entry_lost','state_reg[0]',{'D':"1'b0"},'accepted_attention_header_enters_validate_without_error','accepted')):
        altered=body
        for pin,value in pins.items():altered=replace_instance_pin(altered,instance,pin,value.encode())
        if mode=='reset':active=[z3.Not(local('rst_n'))]
        elif mode=='accepted':active=[*routed['conditions'],address['invariant'],routed['accepted']]
        else:
            active=[local('rst_n'),b.word(owner+'.state',5)==0,local('cfg_valid')==(mode!='stall')]
            if mode=='tag':active.append(local('cfg_tag[0]'))
            elif mode=='address':active.append(local('cfg_activation_base[3]'))
            elif mode=='partition':active.extend([z3.Not(local('softmax_request[score_core]')),b.word(owner+'.cfg_feature_words',10)==8])
            elif mode=='paired':active.extend([local('paired'),z3.Not(local('cfg_paired'))])
            elif mode=='packed':active.extend([local('packed_weights'),z3.Not(local('cfg_packed_weights'))])
            elif mode=='cluster':active.append(z3.Not(local('softmax_request[score_tile]')))
            elif mode=='core':active.append(z3.Not(local('softmax_request[score_core]')))
            elif mode=='owner':active.append(local('softmax_request[owner][4]'))
            else:active.append(local('done_tag[0]'))
        reject(label,query,lambda:prove_receiver_admission(environment,routed,address,body=altered,only_query=query,activation=active),
               instance=instance,changed_pins=pins,activation=mode,altered_module_sha256=sha256(altered).hexdigest())
    altered=replace_instance_pin(body,'tag_reg[0]','CP',b"1'b0")
    try:prove_receiver_admission(environment,routed,address,body=altered)
    except AssertionError as error:
        assert str(error)=='Tile register clock differs',('Unrelated header clock failure',str(error))
        rejected.append(dict(control='header_wrong_clock',rejection=str(error)))
    else:raise AssertionError('Header wrong clock accepted')
    assert len(rejected)==16 and all(sha256(data[name]).hexdigest()==digest for name,digest in originals.items())
    return rejected
