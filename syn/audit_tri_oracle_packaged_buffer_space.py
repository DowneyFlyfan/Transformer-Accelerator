"""Recount unrepaired local nets against native pin inventories and placed origins."""
from collections import Counter,defaultdict
from contextlib import ExitStack
from hashlib import file_digest
from pathlib import Path
import csv,json,re,sys
ROOT=Path(__file__).resolve().parents[1]; WORK=ROOT/'.cache/wide_packaged_host_link/drive_repair'
sys.path.insert(0,str(ROOT/'syn'))
from build_tri_oracle_booth_chip_seed import hierarchy
from verify_tri_oracle_serialized_placement_transfer import catalog
from verify_tri_oracle_pad_cold_reload import components
from audit_tri_oracle_booth_operand_spans import CELL
from plan_tri_oracle_booth_pin_load_repair import empty_grid
from audit_tri_oracle_pad_ring_clearance import dimensions
from verify_tri_oracle_booth_chip_link import named_bindings


def sha(path):
 with path.open('rb') as f:return file_digest(f,'sha256').hexdigest()


def check_endpoints(found,driver,count,histogram):
 assert found.count(driver)==1,'Driver differs from native topology'
 loads=[x for x in found if x!=driver]
 assert len(loads)==count,'Sink count differs from native topology'
 assert Counter(m+'/'+p for n,m,p in loads)==histogram,'Native sink-type histogram differs'
 return loads


def endpoint_audit():
 assert __debug__ and Path.cwd()==ROOT and not Path('/.dockerenv').exists()
 assert int(next(s.split()[1] for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:')))*1024>6*1024**3
 plan=json.loads((WORK/'prepared.json').read_text())
 source=ROOT/'.cache/wide_packaged_host_link/placement/native/cold.v'
 assert sha(source)==plan['source_cold_netlist_sha256']
 native=ROOT/'.cache/wide_packaged_host_link/pin_load/inventory/native'
 native_audit=json.loads((ROOT/'records/tri_oracle_wide_packetized_pin_loads.json').read_text())
 assert native_audit['cold_netlist_sha256']==sha(source)
 for name in ('topology.tsv','sink_types.tsv'):
  assert sha(native/name)==native_audit['evidence_sha256'][str((native/name).relative_to(ROOT))]
 with (native/'topology.tsv').open() as f:topology={r['net']:r for r in csv.DictReader(f,delimiter='\t')}
 wanted={net for row in plan['unresolved'] for net in row['nets']}; assert len(wanted)==24
 hist=defaultdict(Counter)
 with (native/'sink_types.tsv').open() as f:
  for r in csv.DictReader(f,delimiter='\t'):
   if r['net'] in wanted:hist[r['net']][r['base_pin']]=int(r['count'])
 groups=defaultdict(list); result=[]
 with ExitStack() as stack:
  modules=catalog(stack,[source]); children,_=hierarchy(modules)
  for row in plan['unresolved']:
   parent,_,leaf=row['instance'].rpartition('/'); master=b'tri_oracle_chip_credited_request'
   for name in parent.encode().split(b'/'): master=children(master)[name]
   assert children(master)[leaf.encode()].decode()==row['old_master']
   net,=row['nets']; owner,_,local=net.rpartition('/'); assert owner==parent
   groups[master.decode()].append((parent,local,topology[net]))
  for master,rows in groups.items():
   data,start,stop=modules[master]; body=data[start:stop]
   keys={local.encode() for parent,local,info in rows}
   token=re.compile(rb'(?<![\w$])(?:'+b'|'.join(map(re.escape,keys))+rb')(?![\w$])')
   # Direct local connectivity is accepted only when aliases and module ports do not touch it.
   for declaration in re.finditer(rb'(?m)^\s*(?:input|output|inout|assign)\b[^;]*;',body):
    assert not token.search(declaration[0]),(master,'port or alias needs explicit traversal',declaration[0])
   hits=defaultdict(list)
   for cell in CELL.finditer(body):
    kind,raw,fields=cell.groups()
    if not token.search(fields):continue
    assert kind.decode() not in modules,('Hierarchical endpoint needs explicit traversal',master,kind)
    for pin,net in named_bindings(fields).items():
     if net in keys:hits[net].append((raw.removeprefix(b'\\').decode(),kind.decode(),pin))
   for parent,local,info in rows:
    net=parent+'/'+local
    driver_name,driver_pin=info['driver'].rsplit('/',1)
    driver_leaf=driver_name.rsplit('/',1)[1]
    driver_master,pin=info['driver_base_pin'].split('/');assert pin==driver_pin
    driver=(driver_leaf,driver_master,pin)
    loads=check_endpoints(hits[local.encode()],driver,int(info['loads']),hist[net])
    def entry(values):
     name,kind,pin=values
     return {'name':parent+'/'+name,'master':kind,'pin':pin}
    result.append({'module':master,'net':local,'native_net':net,'driver':entry(driver),'sinks':[entry(x) for x in loads]})
 print('DIRECT_LOCAL_ENDPOINTS_RECOUNTED',len(result),sum(len(x['sinks']) for x in result),flush=True)
 wanted_names={x['name'] for row in result for x in (row['driver'],*row['sinks'])}
 locations={}
 layout=ROOT/'.cache/wide_packaged_host_link/placement/native/layout.def'
 assert sha(layout)==native_audit['layout_sha256']
 for name,pose in components(layout):
  key=name.decode().replace('\\','')
  if key in wanted_names:
   assert key not in locations;locations[key]=pose
 assert locations.keys()==wanted_names
 for row in result:
  for endpoint in (row['driver'],*row['sinks']):
   kind,status,x,y,side,halo=locations[endpoint['name']]
   assert kind==endpoint['master'] and status=='PLACED'
   endpoint|={'x':x,'y':y,'orientation':side}
 output={'state':'source_local_endpoints_equal_native_histograms',
         'cold_netlist_sha256':sha(source),'layout_sha256':sha(layout),'nets':result,
         'scope':'Original source placement only. No buffer has been inserted. Sizing and placement changes require a new census.',
         'evidence_sha256':{str(p.relative_to(ROOT)):sha(p) for p in (source,layout,WORK/'prepared.json',native/'topology.tsv',native/'sink_types.tsv',Path(__file__).resolve())}}
 (WORK/'buffer_analysis/endpoints.json').write_text(json.dumps(output,sort_keys=True,indent=2)+'\n')
 print('UNRESOLVED_BUFFER_ENDPOINTS_VERIFIED',len(result),len(wanted_names),flush=True)
 return output



def gap_audit():
 cfg=json.loads((ROOT/'.cache/wide_packaged_host_link/placement/padded_prepared.json').read_text())
 lefs=[ROOT/n for n in cfg['evidence_sha256'] if n.endswith('.lef')]
 for p in lefs:assert sha(p)==cfg['evidence_sha256'][str(p.relative_to(ROOT))]
 sizes=dimensions(lefs,2000)
 layout=ROOT/'.cache/wide_packaged_host_link/placement/native/layout.def'
 grid,rows,keys,left,pitch,height,units,fences,groups=empty_grid(layout,sizes,{'standard_cells':3899401,'fixed_memory_macros':631})
 assert (units,pitch,height)==(2000,280,2400)
 def gaps(board):return Counter(len(m[0]) for line in board for m in re.finditer(b'\x00+',line))
 def capacity(hist):return {str(w):sum((n//w)*k for n,k in hist.items()) for w in (3,4,5,7,9,12,17,22)}
 hist=gaps(grid)
 report={'all_disjoint_slots_by_width':capacity(hist),'all_maximum_gap_sites':max(hist),'regions':{}}
 for name,(a,b,c,d) in fences.items():
  start=max(0,-(-(a-left)//pitch));stop=min(len(grid[0]),(c-left)//pitch)
  sub=[line[start:stop] for y,line in zip(keys,grid,strict=True) if b<=y and y+height<=d]
  hist=gaps(sub)
  report['regions'][name]={'disjoint_slots_by_width':capacity(hist),'maximum_gap_sites':max(hist,default=0),'free_sites':sum(n*k for n,k in hist.items())}
 report['membership']={k.decode().replace('\\',''):v for k,v in groups.items()}
 widths={f'BUFFD{n}BWP12T40P140':sizes[f'BUFFD{n}BWP12T40P140'][0]//pitch for n in (0,1,2,3,4,6,8,12,16)}
 assert min(widths.values())==3 and all(sizes[name][1]==height and sizes[name][0]%pitch==0 for name in widths)
 (WORK/'buffer_analysis/free_gap_probe.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
 return report,widths,lefs


def verify():
 endpoints=endpoint_audit(); space,widths,lefs=gap_audit()
 blocked={n:v for n,v in space['regions'].items() if v['maximum_gap_sites']<min(widths.values())}
 assert len(space['regions'])==20 and len(blocked)==12
 needing_moves=[]
 for net in endpoints['nets']:
  prefix=net['driver']['name'].rpartition('/')[0]+'/'
  regions=[region for member,region in space['membership'].items() if prefix.startswith(member)]
  assert len(regions)<=1
  if regions and regions[0] in blocked:needing_moves.append(net['native_net'])
 assert len(needing_moves)==12
 inputs=[ROOT/'records/tri_oracle_wide_packetized_pin_loads.json',
         ROOT/'.cache/wide_packaged_host_link/placement/padded_prepared.json',
         ROOT/'syn/build_tri_oracle_booth_chip_seed.py',ROOT/'syn/verify_tri_oracle_serialized_placement_transfer.py',
         ROOT/'syn/verify_tri_oracle_pad_cold_reload.py',ROOT/'syn/audit_tri_oracle_booth_operand_spans.py',
         ROOT/'syn/verify_tri_oracle_booth_chip_link.py',ROOT/'syn/plan_tri_oracle_booth_pin_load_repair.py',
         ROOT/'syn/link_tri_oracle_indexed_whole_chip.py',ROOT/'syn/audit_tri_oracle_packed_weight_path.py',
         ROOT/'syn/verify_tri_oracle_booth_chip_geometry.py',ROOT/'syn/audit_tri_oracle_physical_io_budget.py',
         ROOT/'syn/audit_tri_oracle_pad_ring_clearance.py',*lefs,
         WORK/'buffer_analysis/endpoints.json',WORK/'buffer_analysis/free_gap_probe.json']
 result={'state':'native_pin_inventory_recounted_and_original_array_buffer_space_measured',
         'source_cold_netlist_sha256':endpoints['cold_netlist_sha256'],'source_layout_sha256':endpoints['layout_sha256'],
         'unrepaired_nets':len(endpoints['nets']),'sink_pins':sum(len(n['sinks']) for n in endpoints['nets']),
         'drivers_by_master':dict(Counter(n['driver']['master'] for n in endpoints['nets'])),
         'array_regions':len(space['regions']),'examined_buffer_widths_sites':widths,
         'regions_requiring_cell_movement_for_examined_buffers':blocked,
         'affected_unrepaired_nets':needing_moves,'affected_regions_free_sites':sum(v['free_sites'] for v in blocked.values()),
         'all_floorplan_disjoint_slots_by_width':space['all_disjoint_slots_by_width'],
         'evidence_sha256':endpoints['evidence_sha256']|{str(p.relative_to(ROOT)):sha(p) for p in inputs},
         'scope':'Read-only original placement diagnosis. Twenty-four local nets reproduce every native sink-type histogram and driver; all 27,851 sinks and 24 drivers have matching placed origins. '
                 'Twelve affected fenced arrays contain only isolated single-site gaps. The nine examined noninverting buffer variants require at least three adjacent sites, so these variants cannot be added in those regions without cell movement. '
                 'No insertion or repaired placement is qualified. The separate 620-cell sizing candidate requires a new physical census after legalization. Timing, accuracy, clock distribution and routing remain unqualified.'}
 (ROOT/'records/tri_oracle_packaged_buffer_space.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
 print('PACKAGED_BUFFER_SPACE_DIAGNOSIS_VERIFIED',result['unrepaired_nets'],result['sink_pins'],len(blocked),result['affected_regions_free_sites'],flush=True)
 return result


if __name__=='__main__':verify()
