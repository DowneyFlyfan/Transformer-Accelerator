"""Recount native high-fanout connectivity using original Liberty pin values."""
from collections import Counter,defaultdict
import csv
from decimal import Decimal
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/".cache/wide_packaged_host_link/pin_load/inventory"
NATIVE=WORK/'native'
sys.path.insert(0,str(ROOT/'syn'))
from audit_tri_oracle_placed_chip_boundary import digest
from plan_tri_oracle_grouped_reset import read_library
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from verify_tri_oracle_booth_placement_timing import constraint_commands
spec=importlib.util.spec_from_file_location('native_pin_reader',WORK.parent/'verify.py')
reader=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def read(path):
    return json.loads(path.read_text())


def table(path,header):
    with path.open() as stream:
        source=csv.DictReader(stream,delimiter='\t')
        assert source.fieldnames==header,(path,source.fieldnames)
        return list(source)


def canonical(path):
    number=re.compile(r'(?<![\w.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])')
    result=Counter()
    for text in constraint_commands(path).elements():
        result[number.sub(lambda m:format(Decimal(m[0]).normalize(),'f'),text)]+=1
    return result


def cap(properties):
    assert properties['direction']=='input'
    values=[Decimal(properties[name]) for name in ('capacitance','rise_capacitance','fall_capacitance') if name in properties]
    assert values and all(value>=0 and value.is_finite() for value in values)
    return max(values)


def library(path,masters):
    result=read_library(path,masters)
    assert {master for master,pin in result}==masters
    # These standard-cell sources supply scalar pin capacitances. Ranged pin
    # models would need explicit additional parsing and are rejected here.
    assert 'capacitance_range' not in path.read_text()
    return result


def body(text,opening):
    depth=1
    # Remove quoted text and comments before matching structural braces.
    tokens=re.compile(r'"(?:\\.|[^"\\])*"|/\*[\s\S]*?\*/|//[^\n]*|[{}]')
    for match in tokens.finditer(text,opening):
        if match[0]=='{':depth+=1
        elif match[0]=='}':depth-=1
        if depth==0:return text[opening:match.start()]
    raise ValueError('Unclosed Liberty group')


def properties(text):
    result={}
    depth=0
    for line in text.splitlines():
        if depth==0:
            match=re.match(r'\s*(direction|(?:max_|rise_|fall_)?capacitance)\s*:\s*([^;]+);',line)
            if match:result[match[1]]=match[2].strip(' "')
        unquoted=re.sub(r'"(?:\\.|[^"\\])*"','',line)
        depth+=unquoted.count('{')-unquoted.count('}')
        assert depth>=0
    assert depth==0
    return result


def memory_pins(path,master,needed):
    text=path.read_text()
    assert re.search(r'capacitive_load_unit\s*\(\s*1\s*,\s*pf\s*\)',text,re.I)
    cell,=re.findall(r'(?m)^\s*cell\s*\(\s*([^\s)]+)\s*\)\s*\{',text)
    assert cell.strip('"')==master
    assert 'capacitance_range' not in text
    result={}
    for bus in re.finditer(r'(?m)^\s*bus\s*\(\s*([^\s)]+)\s*\)\s*\{',text):
        group=body(text,bus.end())
        inherited=properties(group)
        for pin in re.finditer(r'(?m)^\s*pin\s*\(\s*([^\s)]+)\s*\)\s*\{',group):
            label=pin[1].strip('"')
            interval=re.fullmatch(r'([^\[\]]+)\[(\d+):(\d+)\]',label)
            if interval:
                name,first,last=interval[1],int(interval[2]),int(interval[3])
                assert name==bus[1].strip('"')
                names={f'{name}[{bit}]' for bit in range(min(first,last),max(first,last)+1)}
            else:
                names={label}
            selected=names&needed
            if not selected:continue
            attrs=inherited|properties(body(group,pin.end()))
            for name in selected:
                assert (master,name) not in result
                result[master,name]=attrs
    assert {pin for cell,pin in result}==needed,(path,needed-{pin for cell,pin in result})
    return result


def verify():
    config=read(WORK/'prepared.json')
    assert config['state']=='native_complete_packaged_chip_cell_pin_inventory_inputs_verified'
    status=read(NATIVE/'status.json')
    assert status['exit_status']==0 and status['stop_reason'] is None
    assert (WORK/'supervisor_exit_status').read_text().strip()=='0'
    for name,want in config['evidence_sha256'].items():
        assert digest(ROOT/name)==want,name
    content=artifact_fingerprint(ROOT/config['database'])
    assert content==config['checkpoint_content']
    fingerprint=sha256(json.dumps(content,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    console=(NATIVE/'console.log').read_text()
    assert console.splitlines().count('PACKAGED_RAW_INVENTORY_QUERY_COMPLETE')==1
    assert console.splitlines().count('PACKAGED_PIN_LOAD_DELAY_SETTINGS false false')==1
    assert console.splitlines().count('PACKAGED_PIN_LOAD_LAYOUT_VERIFIED 3900032 98.78')==1
    assert not re.search(r'(?m)^\*\*?ERROR:|Started Early Global Route|PreRoute RC Extraction DONE',console)
    topology={}
    for row in table(NATIVE/'topology.tsv',['net','driver','driver_base_pin','loads']):
        assert row['net'] and row['net'] not in topology
        assert row['driver'] and len(row['driver_base_pin'].split('/'))==2
        assert int(row['loads'])>=64
        topology[row['net']]=row
    histograms=defaultdict(dict)
    for row in table(NATIVE/'sink_types.tsv',['net','base_pin','count']):
        net,pin,count=row['net'],row['base_pin'],int(row['count'])
        assert net in topology and pin not in histograms[net] and count>0
        assert len(pin.split('/'))==2
        histograms[net][pin]=count
    assert histograms.keys()==topology.keys()
    assert all(sum(histograms[net].values())==int(row['loads']) for net,row in topology.items())
    sinks={pin for histogram in histograms.values() for pin in histogram}
    drivers={row['driver_base_pin'] for row in topology.values()}
    masters={pin.split('/')[0] for pin in sinks|drivers}
    suffixes={'setup_slow':'ssg0p9v125c','setup_typ':'tt1v25c','hold_fast':'ffg1p05vm40c'}
    summaries={}
    detail=defaultdict(dict)
    violations=set()
    evidence={}
    for view,suffix in suffixes.items():
        paths=[ROOT/name for name in config['evidence_sha256'] if Path(name).name==f'tcbn28hpcplusbwp12t40p140{suffix}.lib']
        path,=paths
        standard_masters={name for name in masters if not name.startswith('TS')}
        pins=library(path,standard_masters)
        memory_masters=masters-standard_masters
        for master in sorted(memory_masters):
            macro_path,=(ROOT/name for name in config['evidence_sha256']
                         if Path(name).name.lower().startswith(master.lower()+'_')
                         and name.endswith(suffix+'.lib'))
            needed={pin.split('/',1)[1] for pin in sinks|drivers if pin.startswith(master+'/')}
            pins.update(memory_pins(macro_path,master,needed))
            evidence[str(macro_path.relative_to(ROOT))]=digest(macro_path)
        models={'/'.join(key):value for key,value in pins.items()}
        assert sinks|drivers<=models.keys()
        native=reader.measured_table(NATIVE/f'{view}.tsv')
        total,=map(int,re.findall(rf'(?m)^PACKAGED_PIN_LOAD_VIEW_COMPLETE {view} (\d+)$',console))
        assert total==len(native) and native.keys()<=topology.keys()
        if view=='setup_slow':
            baseline=set(native)
        else:
            assert set(native)==baseline
        bad=[]
        largest_delta=Decimal(0)
        for net,row in native.items():
            source=topology[net]
            assert row['loads']==int(source['loads']) and row['driver']==source['driver']
            assert row['missing']==0
            output=models[source['driver_base_pin']]
            assert output['direction']=='output' and 'max_capacitance' in output
            limit=Decimal(output['max_capacitance'])
            # Native attributes have finite decimal precision. This is an
            # independent raw-library sum; retain the discrepancy explicitly.
            raw=sum((cap(models[pin])*count for pin,count in histograms[net].items()),Decimal(0))
            delta=abs(raw-row['pin_load_pf'])
            largest_delta=max(largest_delta,delta)
            assert delta<=Decimal('0.00000051')*row['loads'],(view,net,raw,row)
            assert abs(limit-row['limit_pf'])<=Decimal('0.00000051'),(view,net,limit,row['limit_pf'])
            assert raw>=0 and limit>0
            if raw>limit:
                entry={'net':net,'driver':source['driver'],'driver_base_pin':source['driver_base_pin'],
                       'loads':row['loads'],'raw_pin_load_pf':str(raw),'raw_driver_limit_pf':str(limit),
                       'native_pin_load_pf':str(row['pin_load_pf']),'native_driver_limit_pf':str(row['limit_pf']),
                       'ratio':float(raw/limit)}
                bad.append(entry)
                violations.add(net)
            detail[net][view]={'raw_pin_load_pf':str(raw),'raw_driver_limit_pf':str(limit),
                               'native_pin_load_pf':str(row['pin_load_pf']),'native_driver_limit_pf':str(row['limit_pf'])}
        constraints=ROOT/'.cache/wide_packaged_host_link/placement/native'/f'{view}.sdc'
        assert canonical(constraints)==canonical(NATIVE/f'{view}.sdc'),view
        summaries[view]={'screened_nets':len(native),'raw_library_pin_limit_exceedances':len(bad),
                         'native_report_pin_limit_exceedances':sum(row['pin_load_pf']>row['limit_pf'] for row in native.values()),
                         'maximum_native_vs_raw_sum_difference_pf':str(largest_delta),
                         'worst':sorted(bad,key=lambda row:(-row['ratio'],row['net']))[:8]}
        evidence[str(path.relative_to(ROOT))]=digest(path)
    for name in sorted(violations):
        detail[name]['driver']=topology[name]['driver']
        detail[name]['driver_base_pin']=topology[name]['driver_base_pin']
        detail[name]['loads']=int(topology[name]['loads'])
        detail[name]['sink_types']=histograms[name]
    for path in (WORK/'prepared.json',WORK/'run.py',WORK/'pin_load.tcl',Path(__file__).resolve(),
                 WORK/'supervisor_exit_status',NATIVE/'status.json',NATIVE/'console.log',NATIVE/'geometry.rpt',
                 NATIVE/'topology.tsv',NATIVE/'sink_types.tsv',ROOT/'syn/plan_tri_oracle_grouped_reset.py',
                 WORK.parent/'verify.py',ROOT/'records/tri_oracle_wide_packetized_native_placement.json',
                 *(NATIVE/f'{view}.{suffix}' for view in suffixes for suffix in ('tsv','sdc','probe.tsv'))):
        evidence[str(path.relative_to(ROOT))]=digest(path)
    report={'state':'native_packaged_chip_pin_connectivity_recounted_with_original_liberty',
            'cold_netlist_sha256':config['cold_netlist_sha256'],'layout_sha256':config['layout_sha256'],
            'database':config['database'],'database_fingerprint_sha256':fingerprint,
            'distinct_sink_pin_types':len(sinks),'distinct_driver_pin_types':len(drivers),
            'inventoried_single_driver_nets':len(topology),'corners':summaries,
            'distinct_nets_exceeding_a_raw_pin_limit':len(violations),
            'constraints_preserved_in_three_views':True,'high_fanout_substitution_enabled':False,
            'net_load_ignored':False,'native':status,
            'scope':'Original Liberty input-pin maxima and output-capacitance limits on the native connected '
                    'placement, for eligible driven nets with at least 64 sinks. Pin-load sums are independent '
                    'of the finite decimal precision of native attributes. Includes local gated clocks returned '
                    'by the native filter. Wire capacitance, slew, path slack, clock distribution and routing '
                    'are not covered. The saved placement and source checkpoint are unchanged.',
            'evidence_sha256':evidence}
    (WORK/'verified.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    (WORK/'violations.json').write_text(json.dumps({n:detail[n] for n in sorted(violations)},sort_keys=True,indent=2)+'\n')
    print('PACKAGED_RAW_LIBERTY_PIN_LOAD_VERIFIED',len(baseline),len(violations),flush=True)


if __name__=='__main__':
    assert __debug__ and Path.cwd()==ROOT and not Path('/.dockerenv').exists()
    verify()
