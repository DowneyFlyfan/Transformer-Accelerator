"""Account for compiled SRAM and Liberty-declared state on the exact chip."""
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import cache
from hashlib import file_digest
import json
from mmap import ACCESS_READ,mmap
from multiprocessing import get_context
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'.cache/wide_packaged_host_link/storage_accounting'
sys.path.insert(0,str(ROOT/'syn'))
from audit_tri_oracle_wide_packaged_pin_inventory import body
from link_tri_oracle_indexed_whole_chip import spans
from verify_tri_oracle_pad_cold_reload import components
from verify_tri_oracle_serialized_placement_transfer import INSTANCE
from verify_tri_oracle_shared_memory import memory_shape

TOP='tri_oracle_chip_credited_request'
CORNER={'slow':'ssg0p9v125c','typical':'tt1v25c','fast':'ffg1p05vm40c'}
STATE=re.compile(r'(?m)^[ \t]*(ff|latch|statetable|ff_bank|latch_bank)\s*\(([^)]*)\)\s*\{')
BRACES=re.compile(r'"(?:\\.|[^"\\])*"|/\*[\s\S]*?\*/|//[^\n]*|[{}]')
CELL=re.compile(r'(?m)^cell\s*\((\w+)\)\s*\{')


def digest(path):
    with path.open('rb') as stream:return file_digest(stream,'sha256').hexdigest()


def read(path):return json.loads(path.read_text())


def guard():
    value,=re.findall(r'(?m)^MemAvailable:\s+(\d+) kB$',Path('/proc/meminfo').read_text())
    assert int(value)*1024>=6*1024**3,'Host memory reserve reached'


def direct_state_groups(description):
    """Ignore nested test_cell descriptions of the same physical state."""
    starts={match.end()-1:(match[1],match[2]) for match in STATE.finditer(description)}
    result=[];depth=0
    for token in BRACES.finditer(description):
        if token[0]=='{':
            if depth==0 and token.start() in starts:result.append(starts[token.start()])
            depth+=1
        elif token[0]=='}':
            depth-=1
            assert depth>=0
    assert depth==0
    return result


def state_models(path):
    text=path.read_text();result={}
    for match in CELL.finditer(text):
        name=match[1];description=body(text,match.end())
        groups=direct_state_groups(description)
        kinds=Counter()
        gate=bool(re.search(r'(?m)^\s*clock_gating_integrated_cell\s*:',description))
        internal=set()
        for kind,args in groups:
            if kind in ('ff','latch'):
                variables=[x.strip(' \"') for x in args.split(',')]
                assert len(variables)==2 and len(set(variables))==2,(name,kind,args)
                assert not internal.intersection(variables),(name,groups)
                internal.update(variables)
                # The two Liberty variables denote a bit and its complement.
                kinds['clock_gate' if gate else kind]+=1
            elif kind=='statetable':
                labels=re.findall(r'"([^"]*)"',args)
                assert len(labels)==2
                variables=labels[1].split()
                assert variables and len(variables)==len(set(variables))
                kinds['clock_gate' if gate else 'state_table']+=len(variables)
            else:
                raise ValueError(('Unsupported banked state declaration',name,kind,args))
        result[name]=dict(kinds)
    assert result
    return result


def logical_census(path):
    with path.open('rb') as stream,mmap(stream.fileno(),0,access=ACCESS_READ) as text:
        modules=spans(text);locals={};edges={};macros={}
        defined=set(modules)
        for name,bounds in modules.items():
            assert not re.search(rb'(?m)^[ \t]*(?:always(?:_\w+)?|initial|reg)\b',text[bounds[0]:bounds[1]]),name
            counts=Counter();children=[];memory=[]
            for match in INSTANCE.finditer(text,*bounds):
                master=match[1].decode();leaf=match[2].removeprefix(b'\\').decode()
                assert '/' not in leaf,(name,leaf)
                counts[master]+=1
                if master in defined:children.append((leaf,master))
                elif master.startswith(('TS5N28','TS6N28')):memory.append((leaf,master))
            locals[name]=counts;edges[name]=children;macros[name]=memory
        visiting=set()
        @cache
        def census(master):
            assert master not in visiting,master
            visiting.add(master);result=Counter()
            for child,count in locals[master].items():
                if child in defined:result.update({leaf:n*count for leaf,n in census(child).items()})
                else:result[child]+=count
            visiting.remove(master)
            return result
        total=census(TOP)
        memory={}
        def walk(master,prefix):
            for leaf,kind in macros[master]:
                key=prefix+leaf
                assert key not in memory;memory[key]=kind
            for name,child in edges[master]:
                if any(kind.startswith(('TS5N28','TS6N28')) for kind in census(child)):
                    walk(child,prefix+name+'/')
        walk(TOP,'')
        assert Counter(memory.values())=={kind:n for kind,n in total.items() if kind.startswith(('TS5N28','TS6N28'))}
        return {'leaves':dict(total),'memory':memory,'module_count':len(modules)}


def verify():
    guard()
    placement=read(ROOT/'records/tri_oracle_wide_packetized_native_placement.json')
    logic=read(ROOT/'records/tri_oracle_packaged_resize_logic.json')
    source=ROOT/'.cache/wide_packaged_host_link/placement/native/cold.v'
    candidate=ROOT/'.cache/wide_packaged_host_link/drive_repair/host_legalized/candidate.v'
    layout=ROOT/'.cache/wide_packaged_host_link/placement/native/layout.def'
    assert digest(source)==placement['native_cold_netlist_sha256']==logic['source_cold_netlist_sha256']
    assert digest(candidate)==logic['candidate_sha256'] and digest(layout)==placement['evidence_sha256'][str(layout.relative_to(ROOT))]
    with ProcessPoolExecutor(max_workers=2,mp_context=get_context('spawn')) as pool:
        before,after=list(pool.map(logical_census,(source,candidate)))
    assert before['memory']==after['memory'] and before['module_count']==after['module_count']==771
    physical=Counter();fixed={}
    for index,(raw,pose) in enumerate(components(layout)):
        if index%100000==0:guard()
        master,status,*_=pose;physical[master]+=1
        if status=='FIXED':
            name=raw.decode().replace('\\','')
            assert name not in fixed;fixed[name]=master
    assert physical==before['leaves'] and sum(physical.values())==3900032
    assert fixed==before['memory'] and len(fixed)==631
    expected=physical.copy()
    plan=read(ROOT/'.cache/wide_packaged_host_link/drive_repair/prepared.json')
    for row in plan['replacements']:
        expected[row['old_master']]-=1;expected[row['new_master']]+=1
    expected=+expected
    assert expected==after['leaves']
    cfg=read(ROOT/'.cache/wide_packaged_host_link/pin_load/inventory/prepared.json')
    states={};evidence={}
    for corner,suffix in CORNER.items():
        path,=(ROOT/name for name in cfg['evidence_sha256'] if Path(name).name==f'tcbn28hpcplusbwp12t40p140{suffix}.lib')
        assert digest(path)==cfg['evidence_sha256'][str(path.relative_to(ROOT))]
        states[corner]=state_models(path);evidence[str(path.relative_to(ROOT))]=digest(path)
    assert states['slow']==states['typical']==states['fast']
    standard=states['slow']
    # This cell contains one physical flip-flop and a nested test-cell model.
    assert standard['GSDFCNQMCOD1BWP12T30P140']=={'ff':1}
    capacities={};memory_details={}
    legacy=read(ROOT/'records/tri_oracle_booth_compiled_memory.json')
    for master,count in Counter(fixed.values()).items():
        model,=(ROOT/name for name in legacy['evidence_sha256'] if '/VERILOG/' in name and Path(name).name.upper().startswith(master+'_'))
        assert digest(model)==legacy['evidence_sha256'][str(model.relative_to(ROOT))]
        geometry=set()
        for suffix in CORNER.values():
            library,=(ROOT/name for name in cfg['evidence_sha256'] if Path(name).name.lower().startswith(master.lower()+'_') and name.endswith(suffix+'.lib'))
            assert digest(library)==cfg['evidence_sha256'][str(library.relative_to(ROOT))]
            geometry.add(memory_shape(model.read_text(),library.read_text(),master))
            evidence[str(library.relative_to(ROOT))]=digest(library)
        (depth,width),=geometry
        capacities[master]=depth*width//8
        memory_details[master]={'instances':count,'words':depth,'word_bits':width,'bytes':count*capacities[master]}
        evidence[str(model.relative_to(ROOT))]=digest(model)
    core=defaultdict(Counter);aggregator=Counter();other=Counter()
    owner=re.compile(r'.*/clusters\[([0-4])\]\.unit/selected_bank\1\.block_instance/source_cluster/implementation/(.*)$')
    core_role=re.compile(r'cores\[([0-3])\]/compute/(inputs|weights|outputs|masks)\[\d+\]$')
    for name,master in fixed.items():
        size=capacities[master];group=owner.fullmatch(name)
        if group and (role:=core_role.fullmatch(group[2])):
            core[group[1],role[1]][role[2]]+=size
        elif group and re.fullmatch(r'aggregate_memory\[\d+\]',group[2]):aggregator[group[1]]+=size
        else:other[master]+=size
    expected_core={'inputs':8192,'weights':8192,'outputs':2048,'masks':1024}
    assert set(core)=={(str(c),str(i)) for c in range(5) for i in range(4)}
    assert all(amount==expected_core for amount in core.values())
    assert aggregator=={str(c):2048 for c in range(5)}
    total=sum(item['bytes'] for item in memory_details.values())
    assert sum(sum(value.values()) for value in core.values())+sum(aggregator.values())+sum(other.values())==total
    totals={};per_master={}
    for label,census in (('source',before['leaves']),('resized',after['leaves'])):
        bits=Counter();detail={}
        for master,count in census.items():
            if master in capacities:continue
            assert master in standard,('Unknown physical leaf',master)
            for kind,width in standard[master].items():bits[kind]+=width*count
            if standard[master]:detail[master]={'instances':count,'state_bits_per_instance':sum(standard[master].values()),'state_kinds':standard[master]}
        totals[label]=dict(bits);per_master[label]=detail
    assert totals['source']==totals['resized']
    targets=read(ROOT/'records/paper_result_targets.json')
    paper=ROOT/targets['source']
    assert digest(paper)=='6d6b998c459ade605e082d723374462e1d14b53d6a6b13063ca0f8d1180b1d9f'
    for path in (source,candidate,layout,paper,ROOT/'records/paper_result_targets.json',
                 ROOT/'records/tri_oracle_wide_packetized_native_placement.json',ROOT/'records/tri_oracle_packaged_resize_logic.json',
                 ROOT/'.cache/wide_packaged_host_link/drive_repair/prepared.json',ROOT/'records/tri_oracle_booth_compiled_memory.json',
                 Path(__file__).resolve(),ROOT/'syn/audit_tri_oracle_wide_packaged_pin_inventory.py',
                 ROOT/'syn/verify_tri_oracle_shared_memory.py',ROOT/'syn/verify_tri_oracle_serialized_placement_transfer.py',
                 ROOT/'syn/link_tri_oracle_indexed_whole_chip.py',ROOT/'syn/verify_tri_oracle_pad_cold_reload.py'):
        evidence[str(path.relative_to(ROOT))]=digest(path)
    result={'state':'exact_packaged_candidate_sram_and_standard_cell_state_accounted',
            'source_cold_netlist_sha256':digest(source),'candidate_sha256':digest(candidate),
            'physical_components':3900032,'compiled_memory_instances':len(fixed),
            'compiled_memory_bytes':total,'compiled_memory_binary_kib':total/1024,
            'compiled_memory_by_master':memory_details,'core_memory_bytes_per_core':expected_core,
            'core_count':len(core),'aggregator_input_output_bytes':dict(aggregator),
            'other_compiled_support_bytes':sum(other.values()),
            'standard_cell_state_bits':totals['resized'],'resize_preserves_all_state_bits':True,
            'standard_cell_total_state_bits':sum(totals['resized'].values()),
            'paper_memory_reference':{
                'architecture_figure':'31.6.2','summary_figure':'31.6.7',
                'published_capacity_kind':'SRAM','published_capacity_label_KB':405,
                'exact_byte_count_and_unit_convention_disclosed':False,
                'core_bank_labels_KB':{'IMEM':8,'WMEM':8,'OMEM':2,'SMEM':1},
                'candidate_role_to_bank_label':{'inputs':'IMEM','weights':'WMEM','outputs':'OMEM','masks':'SMEM'},
                'aggregator_input_output_label_KB':2,
                'binary_label_nominal_bytes':405*1024,
                'difference_from_binary_nominal_bytes':total-405*1024,
                'rounded_binary_kib':(2*total+1024)//2048,
                'decimal_label_nominal_bytes':405000,
                'difference_from_decimal_nominal_bytes':total-405000,
                'rounded_decimal_kb':(2*total+1000)//2000,
                'support_table_capacities_individually_disclosed':False,
                'interpretation':'The labeled core-bank and aggregator capacities are compared '
                                 'using binary kilobytes, as in the compiled power-of-two banks. '
                                 'The complete macro capacity rounds to the paper label under '
                                 'that interpretation; exact byte-for-byte agreement is not claimed.'},
            'standard_cell_state_by_master':per_master['resized'],
            'paper_comparison':{'source_figures':['31.6.2','31.6.7'],'label':'SRAM','label_KB':405,
                                'exact_byte_count_disclosed':False,'rounded_binary_kib':(2*total+1024)//2048,
                                'difference_from_exact_405_binary_kib_bytes':total-405*1024,
                                'rounding_interpretation':'Consistent with a rounded binary-kilobyte label; not proof of exact paper byte capacity.',
                                'register_state_included_in_sram_label':False},
            'evidence_sha256':evidence,
            'scope':'Every logical physical leaf matches the original full placement census; the exact resized '
                    'candidate changes only the approved standard-cell variants. Compiled-memory shapes agree '
                    'between Verilog compiler models and all three Liberty corners. Standard-cell state is '
                    'counted from top-level Liberty state groups, excluding duplicated nested test-cell models. '
                    'This is a library-level logical-state census, excluding analog internal nodes and timing notifiers. '
                    'Paper capacities are checked at labeled core and aggregator roles; other support storage '
                    'is fully counted without inventing unpublished per-table sizes. Access methodology, '
                    'complete trained mapped execution, accuracy, timing and routing remain unqualified.'}
    WORK.mkdir(exist_ok=True)
    (WORK/'verified.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print('PACKAGED_STORAGE_ACCOUNTING_VERIFIED',len(fixed),total,dict(totals['resized']),flush=True)
    return result


if __name__=='__main__':
    assert __debug__ and Path.cwd()==ROOT and not Path('/.dockerenv').exists()
    verify()
