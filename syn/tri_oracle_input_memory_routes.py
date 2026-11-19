"""Trace physical input memories using checked compiler bus views and Q pins."""
if not __debug__:raise RuntimeError('Input memory routes require assertions')
import re
from prove_tri_oracle_packaged_accumulators import AccumulatorRoutes,liberty_direct_attributes

LAYOUTS={
    'TS5N28HPCPSVTA32X128M2FW':dict(data_width=128,address_width=5,masked=True),
    'TS5N28HPCPSVTA512X64M4F':dict(data_width=64,address_width=9,masked=False)}
PREFIXES={'weights':(16,'TS5N28HPCPSVTA32X128M2FW'),
          'masks':(2,'TS5N28HPCPSVTA32X128M2FW'),
          'inputs':(2,'TS5N28HPCPSVTA512X64M4F')}


def liberty_direct_groups(text):
    """Find real direct groups while consuming comments and quoted strings."""
    quoted=r'"(?:\\.|[^"\\])*"'
    pattern=re.compile(quoted+r'|/\*[\s\S]*?\*/|//[^\n]*|/\*|"|'
        r'(?P<kind>\b[A-Za-z_]\w*)\s*\((?P<arguments>(?:'+quoted+r'|[^()"])*?)\)\s*\{|[{}]')
    groups=[];depth=0;current=None
    for token in pattern.finditer(text):
        raw=token[0]
        assert raw!='/*','Unclosed Liberty comment'
        assert raw!='"','Unclosed Liberty quoted string'
        if raw.startswith(('"','/*','//')):continue
        if token['kind'] is not None:
            if depth==0:
                arguments=token['arguments'].strip()
                if re.fullmatch(quoted,arguments):arguments=arguments[1:-1]
                current=(token['kind'],arguments,token.end())
            depth+=1
        elif raw=='{':
            assert depth>0,'Input memory declaration group header differs'
            depth+=1
        elif raw=='}':
            depth-=1;assert depth>=0,'Invalid Liberty group nesting'
            if depth==0:
                assert current is not None,'Input memory declaration group differs'
                kind,arguments,opening=current;groups.append((kind,arguments,text[opening:token.start()]));current=None
    assert depth==0,'Unclosed Liberty declaration group'
    return groups


def memory_bus_view(text,master,*,data_width,address_width,masked):
    top=liberty_direct_groups(text)
    libraries=[body for kind,_,body in top if kind=='library']
    if libraries:
        assert len(top)==len(libraries)==1,'Input memory library declaration differs'
        top=liberty_direct_groups(libraries[0])
    def group(groups,kind,argument):
        found=[body for name,args,body in groups if name==kind and args==argument]
        assert len(found)==1,'Input memory '+kind+' declaration differs'
        return found[0]
    body=group(top,'cell',master);children=liberty_direct_groups(body);result={}
    widths=dict(Q=data_width,D=data_width,A=address_width)
    if masked:widths['BWEB']=data_width
    for name,width in widths.items():
        raw=group(children,'bus',name);attributes=liberty_direct_attributes(raw)
        direction='output' if name=='Q' else 'input'
        assert attributes.get('direction')==direction,'Input memory bus direction differs'
        assert 'three_state' not in attributes,'Input memory bus three_state is unsupported'
        typename=attributes['bus_type']
        shape=liberty_direct_attributes(group(top,'type',typename))
        assert shape==dict(base_type='array',data_type='bit',bit_width=str(width),bit_from=str(width-1),bit_to='0',downto='true'),'Input memory bus type differs'
        pins=[(argument,body) for kind,argument,body in liberty_direct_groups(raw) if kind=='pin']
        assert len(pins)==1,'Input memory pin declaration differs'
        assert pins[0][0]==f'{name}[{width-1}:0]','Input memory bus pin range differs'
        properties=liberty_direct_attributes(pins[0][1])
        assert properties.get('direction',direction)==direction,'Input memory bus direction conflicts'
        assert 'three_state' not in properties,'Input memory bus pin three_state is unsupported'
        result[master,f'{name}[{width-1}:0]']=dict(direction=direction)
    return result


def compiled_input_bus_views(environment):
    tables=[]
    for paths in environment['sources'].values():
        table={}
        for master,layout in LAYOUTS.items():
            prefix=master.lower()+'_'
            path,=(p for p in paths if p.name.startswith(prefix))
            table.update(memory_bus_view(path.read_text(),master,**layout))
        tables.append(table)
    assert len(tables)==3 and tables[0]==tables[1]==tables[2],'Input memory bus views differ across corners'
    return tables[0]


class InputMemoryRoutes(AccumulatorRoutes):
    """Retain all combinational logic between exact physical memory state cuts."""
    def __init__(self,*args,**kwargs):
        self.input_q_sources={}
        super().__init__(*args,**kwargs)
        module=self.module(self.contexts[''][0]);self.input_memories={}
        for prefix,(count,wanted_master) in PREFIXES.items():
            for bank in range(count):
                instance=f'{prefix}[{bank}]';master,pins=module.cells[instance]
                assert master==wanted_master,'Input memory master differs'
                layout=LAYOUTS[master];width=layout['data_width']
                widths=dict(Q=width,D=width,A=layout['address_width'],CLK=1,CEB=1,WEB=1)
                if layout['masked']:widths['BWEB']=width
                assert set(pins)==set(widths),'Input memory pin inventory differs'
                assert all(len(module.expression(pins[pin]))==size for pin,size in widths.items()),'Input memory pin width differs'
                assert module.expression(pins['CLK'])==('clk',),'Input memory clock differs'
                assert all(self.direction(master,pin)==('output' if pin=='Q' else 'input') for pin in pins),'Input memory pin direction differs'
                outputs=list(reversed(module.expression(pins['Q'])))
                for bit,net in enumerate(outputs):
                    stem=net if net in module.declared else net.rsplit('[',1)[0]
                    assert net in module.bits and module.directions.get(stem)!='input','Input memory Q is not a declared non-input net'
                    assert net not in self.input_q_sources and net not in self.memory_sources,'Input memory Q bit is repeated'
                    expected=('cell',instance,master,'Q',width-1-bit,width,pins)
                    assert self.drivers('',net)==[expected],'Input memory Q lacks its exact sole physical driver'
                    self.input_q_sources[net]=f'physical_memory.{instance}.Q[{bit}]'
                self.input_memories[instance]=dict(master=master,width=width,address_width=layout['address_width'],
                    masked=layout['masked'],outputs=outputs,pins=pins)
        assert len(self.input_memories)==20 and len(self.input_q_sources)==2432

    def direction(self,master,pin):
        if master in LAYOUTS and pin in ('Q','D','A','BWEB'):
            layout=LAYOUTS[master]
            assert pin!='BWEB' or layout['masked'],'Unexpected input memory mask pin'
            width=layout['address_width'] if pin=='A' else layout['data_width']
            direction='output' if pin=='Q' else 'input'
            assert self.library[master,f'{pin}[{width-1}:0]']['direction']==direction,'Input memory bus direction differs'
            return direction
        return super().direction(master,pin)

    def trace(self,context,net):
        if context=='' and net in self.input_q_sources:return self.graph.variable(self.input_q_sources[net])
        return super().trace(context,net)
