"""Trace actual tensor command routes with qualified sequential polarities."""
if not __debug__:raise RuntimeError('Command route verification requires Python assertions')
from contextlib import contextmanager
from pathlib import Path
from prove_tri_oracle_head_routing import HeadRoutes
from prove_tri_oracle_parent_reset import ResetHierarchy
from prove_tri_oracle_parent_reset import Module
from link_tri_oracle_indexed_whole_chip import DECLARATION
import re
from collections import defaultdict

class CommandRoutes(HeadRoutes):
    def __init__(self,body,masters,library,states,top,*,tile=None,parent=None,offpath=None,guard=lambda:None):
        ResetHierarchy.__init__(self,body,masters,library,states,guard=guard)
        self.contexts['']=top,None,None
        self.driver_indexes={};self.port_signatures={}
        self.tile=self.walk(tile);self.parent=self.walk(parent);self.offpath={};self.sequential_cuts={}
        self.port_modules={};self.input_links={}
        for context,names in (offpath or {}).items():
            context=self.walk(context);module=self.ports(self.contexts[context][0])
            selected=set()
            for name in names:
                assert module.directions.get(name)=='output','Offpath cut must be a declared output'
                selected.update(module.net_bits(name))
            self.offpath[context]=selected

    def walk(self,path):
        if path is None:return None
        context=''
        for instance in path.split('/'):
            if instance:context=self.child(context,instance)
        return context

    def ports(self,master):
        if master in self.modules:return self.modules[master]
        if master not in self.port_modules:
            body=self.body(master);end=body.index(b');')+2
            self.port_modules[master]=Module(body[:end]+b'\n'+b'\n'.join(x[0] for x in DECLARATION.finditer(body[end:]))+b'\nendmodule')
        return self.port_modules[master]

    def drivers(self,context,net):
        """Index the complete context once, including scalar temporary nets."""
        module=self.module(self.contexts[context][0])
        assert net in module.bits,'Undeclared command route net'
        if context not in self.driver_indexes:
            indexed=defaultdict(list)
            for left,right in module.assignments.items():indexed[left].append(('assign',right))
            for instance,(master,pins) in module.cells.items():
                for pin,value in pins.items():
                    direction=self.direction(master,pin)
                    assert direction in ('input','output'),'Unsupported command route direction'
                    if direction!='output':continue
                    bits=module.expression(value)
                    for offset,bit in enumerate(bits):
                        assert bit in module.bits,'Command output drives an undeclared bit or constant'
                        indexed[bit].append(('cell',instance,master,pin,offset,len(bits),pins))
            self.driver_indexes[context]=indexed
        return self.driver_indexes[context].get(net,[])

    def trace(self,context,net):
        if net in ("1'b0","1'b1"):return int(net[-1])
        key=context,net
        if key in self.cones:return self.cones[key]
        if net in self.offpath.get(context,set()):return self.graph.variable(f'offpath.{context}.{net}')
        assert key not in self.visiting,'Combinational command route cycle'
        self.visiting.add(key)
        module=self.module(self.contexts[context][0]);assert net in module.bits,'Undeclared command route bit'
        drivers=self.drivers(context,net)
        stem=net if net in module.declared else net.rsplit('[',1)[0]
        if module.directions.get(stem)=='input':
            assert not drivers,'Command input has internal driver'
            _,parent,pins=self.contexts[context]
            if parent is None:result=self.graph.variable('top.'+net)
            else:
                link=context,stem
                if link not in self.input_links:
                    formal=module.net_bits(stem);owner=self.module(self.contexts[parent][0])
                    actual=owner.expression(pins[stem]);assert len(formal)==len(actual),'Command input binding width differs'
                    self.input_links[link]=dict(zip(formal,actual,strict=True))
                result=self.trace(parent,self.input_links[link][net])
        else:
            assert len(drivers)==1,('Expected one command route driver',context,net,len(drivers))
            driver,=drivers
            if driver[0]=='assign':result=self.trace(context,driver[1])
            else:
                _,instance,master,pin,offset,width,connected=driver
                if master in self.masters:
                    formal=self.ports(master).net_bits(pin);assert len(formal)==width,'Command output binding width differs'
                    result=self.trace(self.child(context,instance),formal[offset])
                elif self.states.get(master):
                    result=self.sequential(context,net,instance,master,pin,offset,width,connected,module)
                else:
                    assert width==1 and offset==0,'Nonscalar command primitive output'
                    function=self.library[master,pin].get('function');assert function,'Missing command gate function'
                    values={}
                    for symbol in set(re.findall(r'[A-Za-z_]\w*',function)):
                        assert self.library[master,symbol]['direction']=='input','Gate function references noninput'
                        bits=module.expression(connected[symbol]);assert len(bits)==1,'Nonscalar command primitive input'
                        values[symbol]=self.trace(context,bits[0])
                    result=self.graph.function(function,values)
        self.visiting.remove(key);self.cones[key]=result
        return result

    def sequential(self,context,net,instance,master,pin,offset,width,connected,module):
        assert self.states[master]=={'ff':1},'Unsupported command sequential cut'
        assert width==1 and offset==0,'Nonscalar command sequential source'
        function=self.library[master,pin].get('function')
        assert function in ('IQ','IQN'),'Unsupported command state polarity'
        q=module.expression(connected.get('Q',''))
        if q:
            assert len(q)==1 and self.library[master,'Q']['function']=='IQ','Unknown command companion polarity'
            name=q[0]
        else:name=instance+':IQ'
        prefix='tile' if context==self.tile else 'parent' if context==self.parent else context
        leaf=prefix+'.'+name
        value=self.graph.variable(leaf)
        self.sequential_cuts[leaf]=dict(context=context,instance=instance,master=master,q=list(q))
        result=value if function=='IQ' else self.graph.operation('!',value)
        return result


def route_word(routes,bridge,path,name,width,*,direction=None):
    """Trace numeric words least-significant bit first; never infer missing bits."""
    context=routes.walk(path);module=routes.module(routes.contexts[context][0])
    assert type(width) is int and width>0 and name in module.declared,'Missing command word'
    assert module.declared[name]==((width-1,0) if width>1 else None),'Command word width differs'
    assert direction is None or module.directions.get(name)==direction,'Command word direction differs'
    values=bridge.convert([routes.trace(context,f'{name}[{bit}]' if width>1 else name) for bit in range(width)])
    return bridge.pack(values) if width>1 else values[0]


@contextmanager
def command_route_environment(pin):
    """Keep the exact candidate mapped while reading full primary corner views."""
    import json
    from mmap import mmap,ACCESS_READ
    from prove_tri_oracle_packaged_products import CANDIDATE,ROOT,memory_guard
    from prove_tri_oracle_head_routing import routing_libraries
    from link_tri_oracle_indexed_whole_chip import spans
    structure=json.loads(pin(ROOT/'records/tri_oracle_packaged_compute_structure.json').read_text())
    storage=json.loads(pin(ROOT/'records/tri_oracle_packaged_storage_accounting.json').read_text())
    config=json.loads(pin(ROOT/'.cache/wide_packaged_host_link/head_ratio_proof/configuration_qualified.json').read_text())
    detail_name,=storage['full_detail_cache']
    detail=json.loads(pin(ROOT/detail_name,storage['full_detail_cache'][detail_name]).read_text())
    states={name:row['state_kinds'] for name,row in detail['standard_cell_state_by_master'].items()}
    masters=set(storage['compiled_memory_by_master']);sources={}
    for suffix in ('tt1v25c','ssg0p9v125c','ffg1p05vm40c'):
        rows=[(name,digest) for name,digest in structure['evidence_sha256'].items() if name.endswith(suffix+'.lib')]
        assert len(rows)==7,'Expected all seven command route library views'
        sources[suffix]=[pin(ROOT/name,digest) for name,digest in rows]
        standard,=(path for path in sources[suffix] if path.name.startswith('tcbn28'))
        masters.update(name.strip() for name in re.findall(r'(?m)^cell\s*\(([^)]+)\)\s*\{',standard.read_text()))
    library=next(iter(routing_libraries(sources,masters).values()))
    wanted=structure['candidate_sha256'];pin(CANDIDATE,wanted)
    with CANDIDATE.open('rb') as stream,mmap(stream.fileno(),0,access=ACCESS_READ) as source:
        definitions=spans(source);parent=config['scheduler_path']
        assert parent.endswith('/attention/predictor'),'Unexpected predictor context'
        pipeline=parent[:-len('/attention/predictor')]
        assert pipeline.endswith('/attention_pipeline'),'Unexpected attention pipeline context'
        shared=pipeline[:-len('/attention_pipeline')]
        paths=dict(parent=parent,tile=parent+'/tile',pipeline=pipeline,layer=pipeline+'/attention',
                   frame=shared+'/feedforward',arbiter=shared+'/feedforward/compute',
                   wrapper=shared+'/feedforward/compute/compute',owner=shared+'/feedforward/compute/compute/tensor')
        checker=CommandRoutes(lambda master:source[slice(*definitions[master])],set(definitions),library,states,
            structure['logical_top'],tile=paths['tile'],parent=parent,guard=lambda:memory_guard(8.5))
        for path in (pipeline+'/projection',paths['layer']+'/attention'):
            context=checker.walk(path);ports=checker.ports(checker.contexts[context][0])
            checker.offpath[context]=set(bit for name,direction in ports.directions.items() if direction=='output'
                                       for bit in ports.net_bits(name))
        for path in paths.values():checker.walk(path)
        yield dict(routes=checker,paths=paths,candidate_sha256=wanted,sources=sources,states=states)


def prove_command_routes(environment,parent_bridge,tile_bridge,parent,tile,command):
    """Conditional data and handshake composition, with nonvacuous modes.

    The caller separately proves the producer invariant on actual transitions.
    Admission of RunHead, nonprojection and available arbitration remains an
    explicit upstream obligation. No sequence reachability follows from SAT.
    """
    import z3
    from prove_tri_oracle_head_intensity import WordBridge
    from prove_tri_oracle_tile_command import reference_channel,reference_keep
    routes=environment['routes'];paths=environment['paths'];bridge=WordBridge(routes.graph)
    def word(role,name,width,direction=None):
        return route_word(routes,bridge,paths[role],name,width,direction=direction)
    layer_state=word('layer','state',4)
    # Synthesis retained projection_busy at its activation-stride[11] alias.
    context=routes.walk(paths['pipeline']);root=routes.trace(context,'tensor_cfg_activation_stride[11]')
    node=routes.graph.nodes[root]
    assert node[0]=='v' and routes.sequential_cuts[node[1]]['instance']=='projection_busy_reg','Projection selector is not its actual state bit'
    projection,=bridge.convert([root])
    arbiter_state=word('arbiter','state',4)
    owned=word('arbiter','attention_owned',1)
    enabled=word('arbiter','attention_enable',1,'input')
    selected=word('arbiter','attention_selected',1)
    wrapper_busy=word('wrapper','busy',1)
    owner_state=word('owner','state',5)
    paired=word('owner','cfg_paired',1,'input')
    cfg_valid=word('owner','cfg_valid',1,'input');cfg_ready=word('owner','cfg_ready',1,'output')
    tile_ready=word('tile','tensor_cfg_ready',1,'input')
    geometry=command['old_scalar']
    operational=[bridge.boolean('top.rst_n'),layer_state==5,z3.Not(projection),arbiter_state==0,z3.Not(owned),enabled]
    conditions=[*operational,command['scalar_invariant'],command['invariant'],geometry['state']==2]
    def check(actual,wanted,*,label,extra=()):
        routes.guard();bridge.check(actual,wanted,label=label,conditions=[*conditions,*extra]);routes.guard()
    # Test assumptions themselves before proving implications from them.
    witnesses=[]
    for query,count,total,busy,state in ((96,1,97,False,0),(96,16,112,True,0),(2032,15,2047,False,1)):
        solver=z3.SolverFor('QF_BV');solver.set(timeout=120000,max_memory=1024)
        solver.add(*conditions,geometry['query']==query,geometry['tokens']==count,
                   parent['tokens']['old']==total,wrapper_busy==busy,owner_state==state)
        result=solver.check();assert result==z3.sat,('Command operational witness absent',query,count,str(result))
        witnesses.append(dict(query=query,queries=count,total=total,wrapper_busy=busy,owner_state=state,result='sat',
                              clock_history_reachability_verified=False))
    check([selected,paired,cfg_ready],[z3.BoolVal(True),z3.BoolVal(False),owner_state==0],label='actual_attention_selection_paired_and_owner_ready')
    accepted=z3.And(z3.Not(wrapper_busy),owner_state==0)
    check([cfg_valid,tile_ready],[accepted,accepted],label='actual_command_valid_ready_roundtrip')
    channels=word('owner','cfg_channels',2560,'input');keep=word('owner','cfg_keep',2560,'input')
    expected_channels=z3.Concat(*reversed([reference_channel(geometry['query'],geometry['tokens'],column) for column in range(160)]))
    expected_keep=bridge.pack([reference_keep(geometry['query'],geometry['tokens'],row,column) for row in range(16) for column in range(160)])
    check([channels],[expected_channels],label='all2560_owner_channel_input_bits')
    check([keep],[expected_keep],label='all2560_owner_keep_input_bits')
    header_specs=[('cfg_tokens',5,geometry['tokens']),('cfg_tag',32,geometry['tag']),
        ('cfg_count',8,z3.BitVecVal(96,8)),('cfg_dense_rows',17,z3.ZeroExt(6,geometry['rows'])),
        ('cfg_feature_words',10,z3.BitVecVal(8,10)),('cfg_activation_stride',32,z3.BitVecVal(64,32)),
        ('cfg_activation_base',64,geometry['query_addr']),('cfg_weight_base',64,geometry['key_base'])]
    check([word('owner',name,width,'input') for name,width,_ in header_specs],
          [expected for _,_,expected in header_specs],label='all_owner_command_header_fields')
    bridge.check([word(role,name,1,'input') for role in ('parent','tile','owner') for name in ('clk','rst_n')],
                 [bridge.boolean('top.'+name) for _ in range(3) for name in ('clk','rst_n')],
                 label='producer_and_owner_common_clock_and_reset')
    return dict(bridge=bridge,conditions=conditions,operational=operational,channels=channels,keep=keep,
                geometry=geometry,
                accepted=accepted,cfg_valid=cfg_valid,cfg_ready=cfg_ready,owner_state=owner_state,
                witnesses=witnesses,queries=bridge.checks,owner=paths['owner'],
                channels_verified_bits=2560,keep_verified_bits=2560,header_fields=len(header_specs),
                conditional_consumer_routing_verified=True,upstream_mode_reachability_verified=False)
