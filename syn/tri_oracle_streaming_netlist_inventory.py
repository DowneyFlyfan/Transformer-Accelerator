"""Streaming structural census. Never infer access behavior from inventories."""
from collections import Counter
from hashlib import sha256
import re

MODULE=re.compile(r'^\s*module\s+(\S+)\s*\(')
INSTANCE=re.compile(r'^\s*([A-Za-z_$][\w$]*)\s+(\\\S+|[A-Za-z_$][\w$]*)\s*\(')
HEADER_PREFIX=re.compile(r'^\s*[A-Za-z_$][\w$]*(?:\s+(?:\\\S+|[A-Za-z_$][\w$]*))?\s*$')
MEMORY=re.compile(r'^ts[56]n28hpcpsvta(\d+)x(\d+)m\w+$',re.IGNORECASE)

def require(condition,message):
    if not condition:raise ValueError(message)

def identifier(value):
    return value[1:] if value.startswith('\\') else value

def placement_histogram(stream):
    """Count component masters only; this is not a placement/pose validator."""
    counts=Counter();expected=None;active=False;complete=False
    for line in stream:
        header=re.match(r'^COMPONENTS (\d+)\s*;',line)
        if header:
            require(expected is None,'Multiple component sections')
            expected=int(header[1]);active=True;continue
        if line.strip()=='END COMPONENTS':
            require(active,'Unmatched component section end')
            active=False;complete=True;continue
        if active and line.startswith('- '):
            parts=line.split();require(len(parts)>=3,'Incomplete component row')
            counts[parts[2]]+=1
    require(expected is not None and complete and not active,'Missing or truncated component section')
    require(sum(counts.values())==expected,'Incomplete component inventory')
    return dict(counts)

def inspect(open_source,top,standard_cells):
    """open_source returns a fresh readable stream; all passes are read-only."""
    names=set();inside=None
    with open_source() as stream:
        for line in stream:
            m=MODULE.match(line)
            if m:
                require(inside is None,'Nested module declaration')
                inside=identifier(m[1]);require(inside not in names,'Duplicate module '+inside)
                names.add(inside)
            elif line.strip().startswith('endmodule'):
                require(inside is not None,'Unmatched endmodule');inside=None
    require(inside is None,'Unterminated module')
    require(top in names,'Top module missing')
    modules={};current=None;seen=set();fingerprint=None;pending=''
    with open_source() as stream:
        for line in stream:
            m=MODULE.match(line)
            if m:
                name=identifier(m[1]);current=dict(children=[],memories=[],leaves=Counter(),unknown=Counter())
                modules[name]=current;seen=set();fingerprint=sha256();pending=''
            if current is None:continue
            fingerprint.update(line.encode())
            if line.strip().startswith('endmodule'):
                current['sha256']=fingerprint.hexdigest();current=None;pending='';continue
            header=pending+line
            m=INSTANCE.match(header)
            pending=header if not m and HEADER_PREFIX.fullmatch(header) else ''
            if not m or m[1]=='module':continue
            master,instance=map(identifier,m.groups())
            require(instance not in seen,'Duplicate instance '+instance);seen.add(instance)
            require('/' not in instance,'Ambiguous path delimiter in instance '+instance)
            if master in names:current['children'].append((instance,master))
            elif MEMORY.fullmatch(master):current['memories'].append((instance,master))
            elif master in standard_cells:current['leaves'][master]+=1
            else:current['unknown'][master]+=1
    macro_paths=[];module_counts=Counter();leaf_counts=Counter();selected_owners=[]
    def visit(master,path,ancestors):
        require(master not in ancestors,'Recursive module '+master)
        module=modules[master]
        require(not module['unknown'],'Unknown reachable cell masters '+str(module['unknown']))
        module_counts[master]+=1;leaf_counts.update(module['leaves'])
        if path and any(x in path.rsplit('/',1)[-1] for x in ('packed_loader','normalizer','activation_path','replay_table')):
            selected_owners.append(dict(path=path,master=master,module_sha256=module['sha256']))
        for name,cell in module['memories']:
            match=MEMORY.fullmatch(cell);words,bits=map(int,match.groups())
            require(words*bits%8==0,'Nonbyte compiled memory')
            macro_paths.append(dict(path='/'.join(filter(None,(path,name))),master=cell,words=words,bits_per_word=bits,bytes=words*bits//8))
            leaf_counts[cell]+=1
        for name,child in module['children']:
            visit(child,'/'.join(filter(None,(path,name))),ancestors|{master})
    visit(top,'',set())
    by_master={}
    for memory in macro_paths:
        value=by_master.setdefault(memory['master'],dict(macros=0,bytes=0,words=memory['words'],bits_per_word=memory['bits_per_word']))
        value['macros']+=1;value['bytes']+=memory['bytes']
    return dict(top=top,module_definitions=len(names),reachable_module_instances=dict(module_counts),
                unreachable_definitions=sorted(names-set(module_counts)),leaf_instances=dict(leaf_counts),
                memory_macro_count=len(macro_paths),compiled_memory_bytes=sum(m['bytes'] for m in macro_paths),
                by_master=by_master,memories=macro_paths,selected_owners=selected_owners)
