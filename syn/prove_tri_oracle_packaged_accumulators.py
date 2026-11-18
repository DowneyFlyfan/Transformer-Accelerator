"""Verify actual SRAM write data and captured sums in the mapped compute cores.

The contract is local two-state arithmetic and register transfer. SRAM read
outputs are arbitrary physical memory states; complete memory/command history,
whole tensor scores, accuracy, timing and paper matching remain separate.
"""
if not __debug__:raise RuntimeError('Accumulator verification requires assertions')
from pathlib import Path
from hashlib import file_digest,sha256
import ast,gc,json,re,resource,sys,time
import z3
from prove_tri_oracle_command_admission import AdmissionRoutes
from prove_tri_oracle_head_intensity import WordBridge


def local_source_paths(entries,directory):
    """Include flat local imports even when they occur inside a function."""
    directory=directory.resolve();pending=[path.resolve() for path in entries];seen=set()
    while pending:
        path=pending.pop()
        if path in seen:continue
        assert path.parent==directory and path.suffix=='.py' and path.is_file(),'Unsupported local proof source'
        seen.add(path)
        for node in ast.walk(ast.parse(path.read_text(),filename=str(path))):
            if isinstance(node,ast.ImportFrom):names=[node.module] if node.module and not node.level else []
            elif isinstance(node,ast.Import):names=[alias.name.split('.')[0] for alias in node.names]
            else:continue
            for name in names:
                dependency=directory/(name+'.py')
                if dependency.is_file():pending.append(dependency)
    return sorted(seen)


def validate_prior_records(prior):
    states=dict(product='packaged_signed_product_next_states_exhaustively_verified',
        reduction='packaged_signed_reduction_next_states_symbolically_verified',valid='packaged_local_valid_transitions_and_clears_verified')
    assert set(prior)==set(states),'Missing prior arithmetic record'
    first=prior['product']
    assert len({record['candidate_sha256'] for record in prior.values()})==1,'Different prior arithmetic candidates'
    assert len(first['arrays'])==20,'Missing prior arithmetic arrays'
    for kind,record in prior.items():
        assert record['state']==states[kind] and record['array_instances']==20,'Unqualified prior arithmetic record'
        assert set(record['arrays'])==set(first['arrays']),'Different prior arithmetic array sets'
        assert all(record['arrays'][name]['array_module_sha256']==first['arrays'][name]['array_module_sha256']
                   for name in first['arrays']),'Different prior arithmetic array bodies'


def reference_writeback(sums,memory,forward,accumulate,bypass):
    assert sums.size()==19 and memory.size()==forward.size()==32
    assert z3.is_bool(accumulate) and z3.is_bool(bypass)
    base=z3.If(bypass,forward,memory)
    return z3.SignExt(13,sums)+z3.If(accumulate,base,z3.BitVecVal(0,32))


def physical_pin_expression(module,nets):
    """Render a fault's physical bits without changing escaped net identity."""
    nets=tuple(nets)
    tokens=[]
    for net in nets:
        if net in ("1'b0","1'b1"):tokens.append(net);continue
        if net in module.declared:stem=net;selection=''
        else:
            bit=re.fullmatch(r'(.+)\[(\d+)\]',net);assert bit and bit[1] in module.declared
            stem=bit[1];selection=f'[{bit[2]}]'
        tokens.append((stem if re.fullmatch(r'[A-Za-z_$][\w$]*',stem) else '\\'+stem+' ')+selection)
    assert tokens
    expression='{'+','.join(tokens)+'}'
    assert module.expression(expression)==tuple(nets),'Fault pin expression changed physical identity'
    return expression


def memory_pins(module,master,*,banks=8):
    """Physical128-bit macro ports, returned as little-endian32-bit words."""
    data=[];outputs=[];seen=set();instances=[]
    for bank in range(banks):
        instance=f'outputs[{bank}]';actual,raw=module.cells[instance]
        assert actual==master,'Accumulator memory master differs'
        assert all(module.expression(raw[pin])==('clk',) for pin in ('CLKW','CLKR')),'Accumulator memory clock differs'
        for pin,width in (('WEB',1),('REB',1),('AA',4),('AB',4)):
            assert len(module.expression(raw[pin]))==width,f'Accumulator memory {pin} width differs'
        d=list(reversed(module.expression(raw['D'])));q=list(reversed(module.expression(raw['Q'])))
        assert len(d)==len(q)==128,'Accumulator memory width differs'
        assert not seen.intersection(q) and len(set(q))==128,'Repeated memory output'
        seen.update(q);instances.append(instance)
        data.extend(tuple(d[start:start+32]) for start in range(0,128,32))
        outputs.extend(tuple(q[start:start+32]) for start in range(0,128,32))
    return dict(data_words=data,output_words=outputs,instances=instances)


def memory_bus_direction(library,master,pin):
    width={'D':128,'Q':128,'AA':4,'AB':4}[pin]
    properties=library.get((master,f'{pin}[{width-1}:0]'))
    expected='output' if pin=='Q' else 'input'
    assert properties is not None and properties.get('direction')==expected,'Accumulator memory Liberty bus differs'
    return expected


def liberty_direct_attributes(text):
    """Ignore nested groups, strings and comments when reading attributes."""
    pattern=re.compile(r'"(?:\\.|[^"\\])*"|/\*[\s\S]*?\*/|//[^\n]*|[{}]|(\w+)\s*:\s*("(?:\\.|[^"\\])*"|[^;{}]+)\s*;')
    depth=0;attributes={}
    for token in pattern.finditer(text):
        if token[0]=='{':depth+=1
        elif token[0]=='}':depth-=1
        elif depth==0 and token[1] is not None:
            assert token[1] not in attributes,'Duplicate memory bus attribute'
            attributes[token[1]]=token[2].strip()
        assert depth>=0,'Invalid memory bus nesting'
    assert depth==0,'Unclosed memory bus nesting'
    return attributes


def memory_bus_library(text,master):
    """Read inherited macro-bus direction with exact type and pin ranges."""
    from prove_tri_oracle_packaged_products import liberty_group
    cell,=re.finditer(r'\bcell\s*\(\s*'+re.escape(master)+r'\s*\)\s*\{',text)
    body=liberty_group(text,cell.end());result={}
    for name,width in (('Q',128),('D',128),('AA',4),('AB',4)):
        bus,=re.finditer(r'\bbus\s*\(\s*'+name+r'\s*\)\s*\{',body)
        raw=liberty_group(body,bus.end())
        attributes=liberty_direct_attributes(raw)
        direction='output' if name=='Q' else 'input'
        assert attributes.get('direction')==direction,'Wrong memory bus direction'
        typename=attributes['bus_type']
        definition,=re.finditer(r'\btype\s*\(\s*'+re.escape(typename)+r'\s*\)\s*\{',text)
        shape=liberty_direct_attributes(liberty_group(text,definition.end()))
        assert shape==dict(base_type='array',data_type='bit',bit_width=str(width),bit_from=str(width-1),bit_to='0',downto='true'),'Wrong memory bus type'
        pins=list(re.finditer(r'\bpin\s*\(([^)]+)\)\s*\{',raw))
        assert len(pins)==1 and pins[0][1].strip()==f'{name}[{width-1}:0]','Wrong memory bus pin range'
        properties=liberty_direct_attributes(liberty_group(raw,pins[0].end()))
        assert properties.get('direction',direction)==direction,'Conflicting memory bus pin direction'
        result[master,f'{name}[{width-1}:0]']=dict(direction=direction)
    return result


def compiled_memory_library(environment):
    master='TS6N28HPCPSVTA16X128M2F';tables=[]
    for paths in environment['sources'].values():
        path,=(p for p in paths if p.name.startswith('ts6n28hpcpsvta16x128m2f_'))
        tables.append(memory_bus_library(path.read_text(),master))
    assert len(tables)==3 and tables[0]==tables[1]==tables[2],'Accumulator memory buses differ across corners'
    return tables[0]


class AccumulatorRoutes(AdmissionRoutes):
    def __init__(self,*args,memory_master,**kwargs):
        self.memory_master=memory_master
        super().__init__(*args,**kwargs)
        module=self.module(self.contexts[''][0]);self.memory=memory_pins(module,memory_master)
        self.memory_sources={}
        for word,nets in enumerate(self.memory['output_words']):
            for bit,net in enumerate(nets):
                stem=net if net in module.declared else net.rsplit('[',1)[0]
                assert net in module.bits and module.directions.get(stem)!='input','Memory Q must be a declared non-input net'
                self.memory_sources[net]=f'physical_memory.outputs[{word//4}].Q[{word%4*32+bit}]'
        assert len(self.memory_sources)==1024
        assert self.direction(memory_master,'Q')=='output','Accumulator memory Q direction differs'
        for instance,(master,_) in module.cells.items():
            if master in self.masters:
                child=self.child('',instance);ports=self.ports(master)
                self.offpath[child]={bit for name,direction in ports.directions.items() if direction=='output' for bit in ports.net_bits(name)}
        for word,nets in enumerate(self.memory['output_words']):
            instance=f'outputs[{word//4}]';_,pins=module.cells[instance]
            for bit,net in enumerate(nets):
                expected=('cell',instance,memory_master,'Q',127-(word%4*32+bit),128,pins)
                assert self.drivers('',net)==[expected],'Memory Q must have its exact sole physical macro driver'

    def direction(self,master,pin):
        if master==self.memory_master and pin in ('D','Q','AA','AB'):
            return memory_bus_direction(self.library,master,pin)
        return super().direction(master,pin)

    def trace(self,context,net):
        if context=='' and net in self.memory_sources:
            return self.graph.variable(self.memory_sources[net])
        return super().trace(context,net)


def primary_models(environment,masters):
    from prove_tri_oracle_packaged_products import liberty_group
    from prove_tri_oracle_tile_score_packet import primary_tile_state
    tables=[]
    for paths in environment['sources'].values():
        standard,=(p for p in paths if p.name.startswith('tcbn28'));text=standard.read_text();table={}
        for master in masters:
            match,=re.finditer(r'(?m)^cell\s*\('+re.escape(master)+r'\)\s*\{',text)
            table[master]=primary_tile_state(liberty_group(text,match.end()))
        tables.append(table)
    assert len(tables)==3 and tables[0]==tables[1]==tables[2],'Accumulator primary models differ across corners'
    return tables[0]


def core_environment(original,path,*,body_override=None):
    from prove_tri_oracle_packaged_products import memory_guard
    source=original['routes'];context=source.walk(path);master=source.contexts[context][0]
    assert master.startswith('tri_oracle_sram_memory_compute_verified_'),'Unexpected compute memory module'
    body=source.body(master);getter=lambda name:body_override if name==master and body_override is not None else source.body(name)
    routes=AccumulatorRoutes(getter,source.masters,source.library|original['memory_bus_library'],source.states,master,
        memory_master='TS6N28HPCPSVTA16X128M2F',guard=lambda:memory_guard(8.5))
    module=routes.module(master)
    names=[f'writeback_sums_reg[{bit}]' for bit in range(608)]
    names += [f'accumulator_forward_data_reg[{bit}]' for bit in range(1024)]
    names += ['writeback_accumulate_reg','accumulator_forward_reg','writeback_valid_reg']
    names += [f'writeback_slot_reg[{bit}]' for bit in range(4)]
    names += [f'slot_pipe_reg[3][{bit}]' for bit in range(4)]+['accumulate_pipe_reg[3]']
    kinds=frozenset(module.cells[name][0] for name in names)
    cache=original.setdefault('primary_models_by_master_set',{})
    if kinds not in cache:cache[kinds]=primary_models(original,kinds)
    models=cache[kinds]
    # Reset inputs were split into many physical aliases during synthesis.
    # Establish each alias from the actual enclosing hierarchy before binding
    # the local arithmetic model; arbitrary unrelated core inputs stay free.
    from prove_tri_oracle_packaged_products import parse_function
    actual=source.module(master);reset_inputs=set()
    for name in names:
        kind,raw=actual.cells[name]
        assert parse_function(models[kind]['clear'])==('!','CDN'),'Unsupported accumulator reset function'
        reset,=actual.expression(raw['CDN'])
        assert actual.directions.get(reset)=='input' and actual.declared[reset] is None,'Accumulator reset is not a scalar interface input'
        reset_inputs.add(reset)
    assert actual.directions.get('rst_n')=='input' and actual.declared['rst_n'] is None
    reset_inputs.add('rst_n')
    ancestry=original['reset_routes'];reset_context=ancestry.walk(path)
    binding=WordBridge(ancestry.graph)
    core_reset_root=ancestry.trace(reset_context,'rst_n')
    core_reset,=binding.convert([core_reset_root])
    binding.check(binding.convert([ancestry.trace(reset_context,net) for net in sorted(reset_inputs)]),
        [core_reset]*len(reset_inputs),label='actual_hierarchy_all_core_reset_aliases_equal_core_reset')
    binding.check([z3.And(z3.Not(binding.boolean('top.rst_n')),core_reset)],[z3.BoolVal(False)],
        label='actual_hierarchy_global_reset_clears_core_reset')
    binding.check(binding.convert([ancestry.trace(reset_context,'clk')]),[binding.boolean('top.clk')],label='actual_hierarchy_core_clock')
    return dict(routes=routes,master=master,body_sha256=sha256(body if body_override is None else body_override).hexdigest(),
                absolute_context=path,primary=models,register_names=names,reset_inputs=sorted(reset_inputs),hierarchy_bindings=binding.checks,
                hierarchy_reset_dependencies=sorted(ancestry.graph.dependencies(core_reset_root)))


def prove_core(environment,*,rows=range(32),only_query=None,activation=()):
    from prove_tri_oracle_layer_row_epoch import physical_register
    from prove_tri_oracle_tile_command_routes import route_word
    from prove_tri_oracle_tile_geometry import geometry_check
    routes=environment['routes'];bridge=WordBridge(routes.graph);records={}
    bridge.variables.update({f'top.{name}':bridge.boolean('top.rst_n') for name in environment['reset_inputs']})
    for instance in environment['register_names']:
        records[instance]=physical_register(routes,bridge,'',instance,environment['primary'])
        assert records[instance]['reset_value']==0,'Accumulator state reset value differs'
    def vector(prefix,start,width,key='old'):
        return bridge.pack([records[f'{prefix}_reg[{bit}]'][key] for bit in range(start,start+width)])
    def flag(name,key='old'):return records[name+'_reg'][key]
    rst=bridge.boolean('top.rst_n')
    def check(actual,wanted,label,conditions=()):
        routes.guard();result=geometry_check(bridge,actual,wanted,label=label,conditions=conditions,
            only_query=only_query,activation=activation);routes.guard();return result
    if callable(activation):activation=activation(bridge,records)
    check([x['clock'] for x in records.values()],[bridge.boolean('top.clk')]*len(records),'all1644_accumulator_register_clocks')
    check([x['reset'] for x in records.values()],[z3.Not(rst)]*len(records),'all1644_accumulator_register_reset_bindings')
    assert len(records)==1644
    check([route_word(routes,bridge,'compute',name,1,direction='input') for name in ('clk','rst_n')],
        [bridge.boolean('top.'+name) for name in ('clk','rst_n')],'array_to_core_clock_reset_bindings')
    valid=route_word(routes,bridge,'compute','out_valid',1,direction='output')
    ready=route_word(routes,bridge,'compute','out_ready',1,direction='input')
    accept=z3.And(valid,ready)
    check([flag('writeback_valid','data')],[accept],'actual_writeback_valid_captures_array_handshake',[rst])
    sums=route_word(routes,bridge,'compute','out_sums',608,direction='output')
    check([vector('writeback_sums',0,608,'data')],
        [z3.If(accept,sums,vector('writeback_sums',0,608))],'all608_actual_array_sum_capture_or_hold',[rst])
    slot=vector('writeback_slot',0,4)
    array_slot=bridge.pack([records[f'slot_pipe_reg[3][{bit}]']['old'] for bit in range(4)])
    collision=z3.And(flag('writeback_valid'),array_slot==slot)
    check([vector('writeback_slot',0,4,'data'),flag('writeback_accumulate','data')],
        [z3.If(accept,array_slot,slot),z3.If(accept,records['accumulate_pipe_reg[3]']['old'],flag('writeback_accumulate'))],
        'actual_writeback_metadata_capture_or_hold',[rst])
    check([flag('accumulator_forward','data')],[z3.If(accept,collision,flag('accumulator_forward'))],
        'actual_forward_flag_capture_or_hold',[rst])
    for bank,instance in enumerate(routes.memory['instances']):
        _,raw=routes.module(environment['master']).cells[instance]
        write_bit,=routes.module(environment['master']).expression(raw['WEB'])
        write_enable,=bridge.convert([routes.trace('',write_bit)])
        address=bridge.pack(bridge.convert([routes.trace('',bit) for bit in reversed(routes.module(environment['master']).expression(raw['AA']))]))
        check([write_enable,address],[z3.Not(z3.And(rst,flag('writeback_valid'))),slot],f'physical_output_memory{bank}_write_enable_and_address')
        read_address=bridge.pack(bridge.convert([routes.trace('',bit) for bit in reversed(routes.module(environment['master']).expression(raw['AB']))]))
        read_bit,=routes.module(environment['master']).expression(raw['REB'])
        read_disable,=bridge.convert([routes.trace('',read_bit)])
        check([read_address,read_disable],[array_slot,collision],f'physical_output_memory{bank}_accepted_sum_read_address_and_enable',[rst,accept])
    for row in rows:
        captured=vector('writeback_sums',row*19,19)
        forward=vector('accumulator_forward_data',row*32,32)
        memory=bridge.pack([bridge.boolean(f'physical_memory.outputs[{row//4}].Q[{row%4*32+bit}]') for bit in range(32)])
        actual=bridge.pack(bridge.convert([routes.trace('',net) for net in routes.memory['data_words'][row]]))
        expected=reference_writeback(captured,memory,forward,flag('writeback_accumulate'),flag('accumulator_forward'))
        check([actual],[expected],f'physical_memory_word{row}_signed_accumulation')
        check([vector('accumulator_forward_data',row*32,32,'data')],
            [z3.If(z3.And(accept,collision),expected,forward)],f'physical_forward_word{row}_capture_or_hold',[rst])
    witnesses=[]
    if only_query is None:
        for accumulate in (False,True):
            for bypass in (False,True):
                for handshake in (False,True):
                    solver=z3.SolverFor('QF_BV');solver.set(timeout=120000,max_memory=1024)
                    solver.add(rst,flag('writeback_accumulate')==accumulate,flag('accumulator_forward')==bypass,accept==handshake)
                    assert solver.check()==z3.sat,'Accumulator local mode/handshake witness missing'
                    witnesses.append(dict(accumulate=accumulate,forward=bypass,accepted_array=handshake,result='sat'))
    assert only_query is None or len(bridge.checks)==1,'Targeted accumulator query absent'
    return dict(queries=bridge.checks,selected_register_bits=len(records),words=len(rows),
        local_event_state_witnesses=witnesses,bridge=bridge,records=records,graph_nodes=len(routes.graph.nodes),memory=routes.memory)


def rejection_controls(original,path):
    """Require activated counterexamples to actual in-memory pin corruptions."""
    from prove_tri_oracle_head_configuration import replace_instance_pin
    from prove_tri_oracle_head_intensity import require_counterexample
    from prove_tri_oracle_tile_command_routes import route_word
    base=core_environment(original,path);module=base['routes'].module(base['master'])
    body=base['routes'].body(base['master']);faults=[]
    def add(label,edits,query,mode):
        changed=body
        for instance,pin,value in edits:
            changed=replace_instance_pin(changed,instance,pin,value.encode())
        faults.append((label,changed,query,mode))
    def bus_edit(pin,operation):
        bits=list(reversed(module.expression(module.cells['outputs[0]'][1][pin])))
        operation(bits)
        return [('outputs[0]',pin,physical_pin_expression(module,reversed(bits)))]
    def swap(bits,a,b):bits[a],bits[b]=bits[b],bits[a]
    def zero_low_word(bits):bits[:32]=["1'b0"]*32
    def swap_words(bits):bits[:64]=bits[32:64]+bits[:32]
    def zero_high_sign(bits):bits[19:32]=["1'b0"]*13
    word_query='physical_memory_word0_signed_accumulation'
    add('physical_memory_data_zero',bus_edit('D',zero_low_word),word_query,'sum')
    add('physical_memory_data_bit_swap',bus_edit('D',lambda bits:swap(bits,0,1)),word_query,'sum')
    add('physical_memory_data_word_swap',bus_edit('D',swap_words),word_query,'sum')
    add('physical_memory_read_bit_swap',bus_edit('Q',lambda bits:swap(bits,0,1)),word_query,'memory')
    add('negative_sum_high_sign_zeroed',bus_edit('D',zero_high_sign),word_query,'negative')
    for prefix,mode in (('writeback_sums','sum'),('accumulator_forward_data','forward')):
        a=prefix+'_reg[0]';b=prefix+'_reg[1]'
        add(prefix+'_physical_q_swap',[(a,'Q',module.cells[b][1]['Q']),(b,'Q',module.cells[a][1]['Q'])],word_query,mode)
    add('array_sum_capture_disabled',[('writeback_sums_reg[0]','E',"1'b0")],
        'all608_actual_array_sum_capture_or_hold','sum_capture')
    add('forward_data_capture_disabled',[('accumulator_forward_data_reg[0]','E',"1'b0")],
        'physical_forward_word0_capture_or_hold','forward_capture')
    add('writeback_accumulate_capture_zero',[('writeback_accumulate_reg','D',"1'b0")],
        'actual_writeback_metadata_capture_or_hold','metadata')
    add('writeback_slot_capture_zero',[('writeback_slot_reg[0]','D',"1'b0")],
        'actual_writeback_metadata_capture_or_hold','metadata')
    add('forward_flag_capture_zero',[('accumulator_forward_reg','D',"1'b0")],
        'actual_forward_flag_capture_or_hold','forward_capture')
    add('writeback_valid_capture_zero',[('writeback_valid_reg','D',"1'b0")],
        'actual_writeback_valid_captures_array_handshake','metadata')
    add('output_memory_write_disabled',[('outputs[0]','WEB',"1'b1")],
        'physical_output_memory0_write_enable_and_address','write')
    add('output_memory_write_address_bit_swap',bus_edit('AA',lambda bits:swap(bits,0,1)),
        'physical_output_memory0_write_enable_and_address','write')
    add('output_memory_read_disabled',[('outputs[0]','REB',"1'b1")],
        'physical_output_memory0_accepted_sum_read_address_and_enable','read')
    add('output_memory_read_address_bit_swap',bus_edit('AB',lambda bits:swap(bits,0,1)),
        'physical_output_memory0_accepted_sum_read_address_and_enable','read')
    add('captured_sum_reset_disconnected',[('writeback_sums_reg[0]','CDN',"1'b1")],
        'all1644_accumulator_register_reset_bindings','reset')
    rejected=[]
    del base;gc.collect()
    for label,changed,query,mode in faults:
        environment=core_environment(original,path,body_override=changed)
        routes=environment['routes']
        def activation(bridge,records):
            def flag(name):return records[name+'_reg']['old']
            def vector(prefix,start,width):return bridge.pack([records[f'{prefix}_reg[{bit}]']['old'] for bit in range(start,start+width)])
            rst=bridge.boolean('top.rst_n')
            if mode=='reset':return [z3.Not(rst)]
            conditions=[rst]
            if mode in ('sum','memory','negative','forward'):
                conditions.extend([vector('writeback_sums',0,19)==(0x40000 if mode=='negative' else 1 if mode=='sum' else 0),
                    vector('writeback_sums',19,19)==2,flag('writeback_accumulate')==(mode in ('memory','forward')),
                    flag('accumulator_forward')==(mode=='forward'),vector('accumulator_forward_data',0,32)==1])
                if mode=='memory':conditions.append(bridge.word('physical_memory.outputs[0].Q',32)==1)
            else:
                valid=route_word(routes,bridge,'compute','out_valid',1,direction='output')
                ready=route_word(routes,bridge,'compute','out_ready',1,direction='input')
                conditions.extend([valid,ready,z3.Not(route_word(routes,bridge,'','read_valid',1,direction='input')),
                    vector('writeback_slot',0,4)==1,
                    bridge.pack([records[f'slot_pipe_reg[3][{bit}]']['old'] for bit in range(4)])==1,
                    flag('writeback_valid')==(mode!='read'),records['accumulate_pipe_reg[3]']['old'],
                    z3.Not(flag('writeback_accumulate')),vector('writeback_sums',0,19)==1,
                    vector('accumulator_forward_data',0,32)==0])
                if mode=='sum_capture':
                    conditions[-2]=vector('writeback_sums',0,19)==0
                    sums=route_word(routes,bridge,'compute','out_sums',608,direction='output')
                    conditions.append(z3.Extract(18,0,sums)==1)
            return conditions
        try:prove_core(environment,rows=range(1),only_query=query,activation=activation)
        except AssertionError as error:
            require_counterexample(error,expected_query=query)
            rejected.append(dict(control=label,query=query,result='sat',activation=mode,altered_module_sha256=sha256(changed).hexdigest()))
            print('ACCUMULATOR_CORRUPTION_REJECTED',label,query,flush=True)
        else:raise AssertionError(('Accumulator corruption accepted',label))
        del environment;gc.collect()
    changed=replace_instance_pin(body,'writeback_sums_reg[0]','CP',b"1'b0")
    try:prove_core(core_environment(original,path,body_override=changed),rows=range(1))
    except AssertionError as error:
        assert str(error)=='Epoch register clock differs',('Unrelated accumulator clock rejection',str(error))
        rejected.append(dict(control='captured_sum_wrong_clock',rejection=str(error),altered_module_sha256=sha256(changed).hexdigest()))
    else:raise AssertionError('Accumulator wrong clock accepted')
    assert len(rejected)==19 and len({item['altered_module_sha256'] for item in rejected})==19
    return rejected


def verify(output,*,prototype=False):
    from prove_tri_oracle_tile_command_routes import command_route_environment
    from prove_tri_oracle_packaged_products import ROOT,memory_guard
    from prove_tri_oracle_head_score_frontend import revalidate_evidence
    assert not Path('/.dockerenv').exists() and output.resolve().is_relative_to((ROOT/'.cache').resolve()) and not output.exists()
    memory_guard(10);start=time.monotonic();pins={}
    def pin(path,wanted=None):
        with path.open('rb') as f:digest=file_digest(f,'sha256').hexdigest()
        assert wanted is None or digest==wanted,('Changed accumulator input',path)
        assert pins.setdefault(str(path.relative_to(ROOT)),digest)==digest
        return path
    prior={}
    for kind in ('product','reduction','valid'):
        prior[kind]=json.loads(pin(ROOT/f'records/tri_oracle_packaged_{kind}_next_states.json').read_text())
        for name,digest in prior[kind]['evidence_sha256'].items():pin(ROOT/name,digest)
    validate_prior_records(prior)
    local_sources=local_source_paths((Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_packaged_accumulator_logic.py'),ROOT/'syn')
    for path in (*local_sources,ROOT/'verilog/tri_oracle_sram_memory_compute.sv'):pin(path)
    cores=[];arrays=set();rejected=[]
    with command_route_environment(pin) as original:
        original['memory_bus_library']=compiled_memory_library(original)
        source=original['routes']
        original['reset_routes']=AdmissionRoutes(source.body,source.masters,source.library,source.states,source.contexts[''][0],guard=source.guard)
        original['reset_routes'].modules=source.modules
        assert all(x['candidate_sha256']==original['candidate_sha256'] for x in prior.values())
        for bank in range(1 if prototype else 5):
            for core in range(1 if prototype else 4):
                path=original['paths']['owner']+f'/fabric/clusters[{bank}].unit/selected_bank{bank}.block_instance/source_cluster/implementation/cores[{core}]/compute'
                environment=core_environment(original,path)
                master=environment['routes'].module(environment['master']).cells['compute'][0]
                array_sha=sha256(original['routes'].body(master)).hexdigest()
                for record in prior.values():assert record['arrays'][master]['array_module_sha256']==array_sha,'Accumulator array differs from prior arithmetic proof'
                result=prove_core(environment,rows=range(1 if prototype else 32))
                arrays.add(master)
                cores.append(dict(bank=bank,core=core,absolute_context=path,module=environment['master'],module_sha256=environment['body_sha256'],
                    array_module=master,array_module_sha256=array_sha,queries=result['queries'],hierarchy_bindings=environment['hierarchy_bindings'],
                    actual_reset_inputs=environment['reset_inputs'],hierarchy_reset_dependencies=environment['hierarchy_reset_dependencies'],
                    register_bits=result['selected_register_bits'],words=result['words'],graph_nodes=result['graph_nodes'],
                    local_event_state_witnesses=result['local_event_state_witnesses']))
                del environment,result;gc.collect()
        if not prototype:rejected=rejection_controls(original,cores[0]['absolute_context'])
        if not prototype:assert arrays==set(prior['product']['arrays']),'Different prior arithmetic and actual core array coverage'
        hierarchy={name:module.sha256 for name,module in original['reset_routes'].modules.items()}
        candidate=original['candidate_sha256']
    loaded={Path(module.__file__).resolve() for module in sys.modules.values() if getattr(module,'__file__',None)
            and Path(module.__file__).resolve().parent==ROOT/'syn'}
    assert loaded<=set(local_sources),('Unpinned loaded proof sources',loaded-set(local_sources))
    if not prototype:
        assert len(cores)==len(arrays)==20 and sum(core['words'] for core in cores)==640
        assert len({core['absolute_context'] for core in cores})==20
    revalidate_evidence(pins,ROOT)
    report=dict(state='mapped_accumulator_prototype' if prototype else 'mapped_accumulator_local_arithmetic_and_capture_qualified',candidate_sha256=candidate,
        cores=cores,core_count=len(cores),array_count=len(arrays),memory_words=sum(x['words'] for x in cores),evidence_sha256=pins,
        hierarchy_module_sha256=hierarchy,rejected_mutations=rejected,
        local_source_files=len(local_sources),all_loaded_local_sources_pinned=True,
        python_version=sys.version,z3_version=z3.get_full_version(),
        equivalence_queries=sum(len(core['queries'])+len(core['hierarchy_bindings']) for core in cores),
        wall_seconds=time.monotonic()-start,peak_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        memory_history_verified=False,complete_tensor_scores_verified=False,complete_paper_architecture_verified=False,
        task_accuracy_verified=False,physical_timing_verified=False,advance_to_clock_distribution_or_routing_allowed=False,
        scope=f'Actual {len(cores)} cores and {sum(core["words"] for core in cores)} output words: local two-state arithmetic, sole physical memory Q drivers, signed19-to32 accumulation, accepted-sum writeback and forward capture/hold, write controls, accepted-array memory-read controls, clocks and reset aliases. Local reset is intentionally controller-gated; its aliases and chip-reset dominance are traced through actual ancestors. Physical memory Q and unselected register states remain arbitrary; PE output ports are explicit compositional boundaries bound to successful prior array-body proofs. Event witnesses are local assignments, not reset-to-event histories. External read-miss service, memory latency/history, command metadata alignment, complete tensor scores, task accuracy and physical timing remain separate.')
    with output.open('x') as f:f.write(json.dumps(report,indent=2)+'\n')
    print(report['state'],report['core_count'],report['memory_words'],report['wall_seconds'],flush=True)


if __name__=='__main__':
    import argparse
    resource.setrlimit(resource.RLIMIT_AS,(3*2**30,3*2**30))
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);parser.add_argument('--prototype',action='store_true')
    args=parser.parse_args();verify(args.output,prototype=args.prototype)
