"""Host-only linkage: current chip, accepted scale command, shared narrow port.

Only the existing inner command module changes. Every old module remains in
place, and all newly mapped internal module names receive a private namespace.
No new physical top-level port is introduced. This does not qualify placement.
"""
if not __debug__:
    raise RuntimeError("Verification requires assertions")

from hashlib import file_digest
from pathlib import Path
import argparse, json, mmap, re, shutil

ROOT=Path.cwd().resolve()
WORK=ROOT/'.cache/channel_scale_integration_20261120'
SOURCE=ROOT/'.cache/wide_packaged_host_link/drive_repair/branch_repair/native_trial_runtime_guarded/native/cold.v'
MAPPED=WORK/'mapping_v2'
PARENT='tri_oracle_chip_command_layer_parallel_chip'
BASE_SHA='5f25540c4d485d66fcfb8408b6710379160c555ad33802df5072868d3b7a5846'
MODULE=re.compile(rb'(?m)^\s*module\s+(\w+)\s*\(')
END=re.compile(rb'(?m)^\s*endmodule\b')
BUS={'req_valid':1,'req_ready':1,'req_address':64,'req_length':5,
     'rsp_valid':1,'rsp_ready':1,'rsp_last':1,'rsp_error':1,'rsp_data':64}
PREFIX='tri_oracle_chscale_v1_'
INSTANCE=re.compile(r'(?m)^[ \t]*([\w$]+)[ \t]+(\\\S+|[\w$]+)[ \t]*\(\s*\.')

def verify_reference_closure(text,known):
    references=list(INSTANCE.findall(text))
    missing={master for master,instance in references if master not in known}
    if missing:raise ValueError(('Unresolved mapped masters',sorted(missing)))
    return references

def sha(path):
    with path.open('rb') as f:return file_digest(f,'sha256').hexdigest()

def once(text,old,new):
    assert text.count(old)==1,('Expected unique connection',old,text.count(old))
    return text.replace(old,new)

def block(text,master,instance):
    mark=f'   {master} {instance} ('
    start=text.index(mark)
    return start,text.index(');',start)+2

def ports(text,master):
    header,=re.findall(rf'(?ms)^module {master}\s*\((.*?)\);',text)
    return set(re.findall(r'\\\S+|\b[A-Za-z_]\w*',header))

def pinset(text):
    return set(re.findall(r'\.((?:\\\S+)|\w+)\s*\(',text))

def bind(mapping):
    return ',\n      '.join(f'.{pin}({net})' for pin,net in mapping.items())

def renamed_sources():
    texts={}
    for name in ('dispatcher','writer','arbiter'):
        directory=MAPPED/name
        status=json.loads((directory/'native_status.json').read_text())
        assert status['passed'] and status['owned_group_terminal'] and status['exit_status']==0
        for source,want in json.loads((directory/'sources.json').read_text()).items():
            assert sha(ROOT/source)==want,('Mapped source changed',source)
        path=directory/'netlist.v'
        assert sha(path)==status['output_sha256']['netlist.v']
        texts[name]=path.read_text()
    definitions=[x.decode() for text in texts.values() for x in MODULE.findall(text.encode())]
    assert len(definitions)==len(set(definitions))
    names={name:PREFIX+name.removeprefix('tri_oracle_') for name in definitions}
    replace=re.compile(r'\b('+ '|'.join(map(re.escape,sorted(names,key=len,reverse=True)))+r')\b')
    return {k:replace.sub(lambda m:names[m[0]],v) for k,v in texts.items()},names

def link_parent(text,texts,names):
    assert 'tri_channel_' not in text and 'tri_projection_' not in text and 'tri_scale_' not in text
    declarations='\n   wire tri_channel_mode;\n   wire [63:0] tri_channel_scale_base;\n'
    for label in ('tri_projection','tri_scale'):
        for name,width in BUS.items():
            size=f'[{width-1}:0] ' if width>1 else ''
            declarations+=f'   wire {size}{label}_{name};\n'
    header,delimiter,rest=text.partition(');')
    assert delimiter
    text=header+delimiter+declarations+rest

    old='tri_oracle_indexed_chip_dispatch';new=names['tri_oracle_channel_indexed_dispatch']
    a,b=block(text,old,'dispatch');original=text[a:b]
    dispatch=once(original,f'{old} dispatch (',f'{new} dispatch (\n      .layer_feedforward_channel_scales(tri_channel_mode),\n      .layer_feedforward_scale_base(tri_channel_scale_base),')
    assert pinset(dispatch)==ports(texts['dispatcher'],new)
    text=text[:a]+dispatch+text[b:]

    old='tri_oracle_decoder_bank_writeback';new=names['tri_oracle_selectable_bank_writeback']
    a,b=block(text,old,'bank_writeback');original=text[a:b]
    writer=once(original,f'{old} bank_writeback (',f'{new} bank_writeback (\n      .frame_channel_scales(tri_channel_mode),\n      .frame_scale_base(tri_channel_scale_base),\n      '+bind({name:f'tri_scale_{name}' for name in BUS})+',')
    assert pinset(writer)==ports(texts['writer'],new)
    text=text[:a]+writer+text[b:]

    match,=re.finditer(r'(?m)^   (\w+) direct_projection \(',text)
    a,b=block(text,match[1],'direct_projection');projection=text[a:b]
    for name in BUS:
        projection=once(projection,f'.{name}(proj_{name})',f'.{name}(tri_projection_{name})')
    text=text[:a]+projection+text[b:]

    arbiter=names['tri_oracle_narrow_read_arbiter']
    connections={'clk':'clk','rst_n':'rst_n'}
    for name in BUS:
        connections['mem_'+name]='proj_'+name
        if name in ('req_address','req_length','rsp_data'):
            for bit,label in enumerate(('tri_projection','tri_scale')):
                connections[f'\\client_{name}[{bit}] ']=f'{label}_{name}'
        else:
            connections['client_'+name]='{'+f'tri_scale_{name}, tri_projection_{name}'+'}'
    assert {s.strip() for s in connections}==ports(texts['arbiter'],arbiter)
    position=text.rindex('endmodule')
    text=text[:position]+f'   {arbiter} shared_channel_scale_read_port (\n      '+bind(connections)+');\n'+text[position:]
    assert text.partition(');')[0]==header,'Changed external parent header'
    return text

def main(output):
    output=output.resolve()
    assert not Path('/.dockerenv').exists()
    assert output.is_relative_to(ROOT/'.cache'),'Generated artifacts belong in .cache'
    assert not output.exists(),'Never overwrite a linked candidate'
    available=next(int(row.split()[1])*1024 for row in Path('/proc/meminfo').read_text().splitlines() if row.startswith('MemAvailable:'))
    assert available>=10*2**30 and shutil.disk_usage(ROOT).free>=20*2**30
    assert sha(SOURCE)==BASE_SHA
    texts,names=renamed_sources()
    with SOURCE.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as code:
        definitions=list(MODULE.finditer(code));known={d[1].decode() for d in definitions}
        assert len(known)==len(definitions) and not known.intersection(names.values())
        start,=[d for d in definitions if d[1].decode()==PARENT]
        end=END.search(code,start.end()).end()
        original=code[start.start():end].decode()
        saved=(WORK/(PARENT+'.v')).read_text().rstrip('\n')
        assert original.lstrip('\n')==saved.lstrip('\n')
        top=link_parent(original,texts,names).encode()
        old_bundle=ROOT/'.cache/wide_packaged_host_link/drive_repair/branch_repair/current_feedforward_20261120_v1/bundle.sv'
        libraries=[Path(p) for p in re.findall(r'(?m)^`include "([^"]+)"$',old_bundle.read_text())
                   if '/VERILOG/' in p or '/.cache/physical/library/' in p]
        assert len(libraries)==7
        library_masters=set()
        for library in libraries:
            with library.open('rb') as stream,mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as model:
                library_masters.update(d[1].decode() for d in MODULE.finditer(model))
        references=verify_reference_closure(top.decode()+'\n'+'\n'.join(texts.values()),known|set(names.values())|library_masters)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.mkdir()
        (output/'inner_command.v').write_bytes(top+b'\n')
        target=output/'candidate.v'
        with target.open('xb') as out:
            for offset in range(0,start.start(),4*1024**2):out.write(code[offset:min(offset+4*1024**2,start.start())])
            out.write(top)
            for offset in range(end,len(code),4*1024**2):out.write(code[offset:offset+4*1024**2])
            for name in ('dispatcher','writer','arbiter'):out.write(('\n'+texts[name]+'\n').encode())
    evidence=dict(state='linked_unplaced_unqualified_candidate',source_sha256=BASE_SHA,candidate_sha256=sha(target),
        changed_parent=PARENT,unchanged_parent_external_ports=True,unchanged_old_module_count=len(known)-1,
        added_module_renames=names,source_offsets=[start.start(),end],inner_command_sha256=sha(output/'inner_command.v'),
        source_sha256_after=sha(SOURCE),clock_distribution_or_routing_allowed=False,
        checked_changed_and_appended_instances=len(references),library_definitions=len(library_masters),
        mapped_master_reference_closure_verified=True,
        accepted_mapping_receipts={name:{item:sha(MAPPED/name/item) for item in ('native_status.json','sources.json','netlist.v','unresolved.rpt')} for name in texts},
        library_sha256={str(path.relative_to(ROOT)):sha(path) for path in libraries},
        linker_sha256=sha(Path(__file__)),
        frozen_parent_snapshot_sha256=sha(WORK/(PARENT+'.v')),
        library_bundle_sha256=sha(old_bundle),
        mapping_inputs={name:sha(MAPPED/name/'netlist.v') for name in texts})
    assert evidence['source_sha256_after']==BASE_SHA
    (output/'linkage.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print('CURRENT_CHANNEL_SCALE_LINKED',evidence['candidate_sha256'])

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='Fresh output directory under .cache; uses the existing baseline and mapped-block artifacts.')
    main(parser.parse_args().output)
