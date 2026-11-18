"""Compose the actual tensor receiver's retained command registers with routes."""
if not __debug__:raise RuntimeError('Command capture verification requires Python assertions')
import re
import z3
from prove_tri_oracle_head_intensity import WordBridge


class OwnerRouteBridge(WordBridge):
    """Resolve receiver inputs through actual connections, preserving state names."""
    def __init__(self,model,routes,upstream,owner):
        super().__init__(model.graph)
        self.model=model;self.routes=routes;self.upstream=upstream;self.owner=routes.walk(owner)

    def boolean(self,name):
        if name not in self.variables:
            if name in self.model.inputs or name in getattr(self.model,'boundaries',set()):
                value,=self.upstream.convert([self.routes.trace(self.owner,name)])
            else:value=self.upstream.boolean(self.owner+'.'+name)
            self.variables[name]=value
        return self.variables[name]


def owner_capture_model(environment,body=None):
    """Full owner body, exact primary register semantics at all three corners."""
    from prove_tri_oracle_tile_geometry import GeometryParent
    from prove_tri_oracle_tile_score_packet import primary_tile_state
    from prove_tri_oracle_packaged_products import liberty_group
    routes=environment['routes'];owner=routes.walk(environment['paths']['owner'])
    master=routes.contexts[owner][0]
    original=routes.body(master)
    module=routes.module(master)
    payload_masters={cell for name,(cell,_) in module.cells.items() if re.fullmatch(r'(channels|keep)_reg\[\d+\]',name)}
    assert payload_masters and all(routes.states.get(cell)=={'ff':1} for cell in payload_masters),'Receiver payload state kind differs'
    primary=[]
    for paths in environment['sources'].values():
        standard,=(path for path in paths if path.name.startswith('tcbn28'))
        text=standard.read_text();models={}
        for cell in sorted(payload_masters):
            match,=re.finditer(r'(?m)^cell\s*\('+re.escape(cell)+r'\)\s*\{',text)
            models[cell]=primary_tile_state(liberty_group(text,match.end()))
        primary.append(models)
    assert len(primary)==3 and primary[0]==primary[1]==primary[2],'Receiver primary state models differ across corners'
    library=dict(routes.library)
    library.update({(cell,'__tile_ff__'):description for cell,description in primary[0].items()})
    children={cell:routes.ports(cell) for cell,_ in module.cells.values() if cell in routes.masters}
    return GeometryParent(original if body is None else body,library,routes.states,children)


def prove_owner_captures(environment,routed,*,body=None,only_query=None,activation=()):
    """Prove reset, exact capture and retention on all 5,120 physical bits."""
    from prove_tri_oracle_tile_geometry import geometry_check
    model=owner_capture_model(environment,body)
    bridge=OwnerRouteBridge(model,environment['routes'],routed['bridge'],environment['paths']['owner'])
    records=[]
    for instance,(master,pins) in sorted(model.module.cells.items()):
        match=re.fullmatch(r'(channels|keep)_reg\[(\d+)\]',instance)
        if not match:continue
        field,index=match[1],int(match[2]);assert 0<=index<2560,'Receiver command bit outside bus'
        q,=model.module.expression(pins['Q'])
        update,reset,reset_value=model.transition(instance,q)
        assert reset is not None and reset_value==0,'Receiver command reset differs'
        old,=bridge.convert([model.cone(q)]);data,=bridge.convert([update]);clear,=bridge.convert([reset])
        incoming=bridge.boolean(f'cfg_{field}[{index}]')
        records.append(dict(instance=instance,field=field,index=index,old=old,data=data,clear=clear,incoming=incoming))
    assert len(records)==5120 and all(sum(record['field']==field for record in records)==2560 for field in ('channels','keep')),'Receiver command inventory differs'
    rst=bridge.boolean('rst_n');capture=z3.And(routed['cfg_valid'],routed['cfg_ready'])
    def check(actual,wanted,*,label,conditions=()):
        environment['routes'].guard()
        result=geometry_check(bridge,actual,wanted,label=label,conditions=conditions,only_query=only_query,activation=activation)
        environment['routes'].guard();return result
    check([record['clear'] for record in records],[z3.Not(rst)]*len(records),label='all5120_receiver_command_reset_bindings')
    check([record['data'] for record in records],
          [z3.If(capture,record['incoming'],record['old']) for record in records],
          label='all5120_receiver_command_exact_capture_or_hold',conditions=[rst])
    check([record['data'] for record in records],
          [z3.Extract(record['index'],record['index'],routed[record['field']])==1 for record in records],
          label='all5120_receiver_command_accepted_payload',conditions=[*routed['conditions'],capture])
    check([record['data'] for record in records],[record['old'] for record in records],
          label='all5120_receiver_command_retained_without_acceptance',conditions=[rst,z3.Not(capture)])
    assert only_query is None or len(bridge.checks)==1,'Targeted receiver command query absent'
    return dict(owner_module_sha256=model.body_sha256,register_bits=len(records),channels_bits=2560,keep_bits=2560,
                queries=bridge.checks,reset_and_capture_verified=True,conditional_accepted_payload_verified=True)
