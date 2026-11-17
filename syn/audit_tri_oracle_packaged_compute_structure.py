"""Inspect actual packaged compute registers, cluster ownership and shared wiring."""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
from hashlib import file_digest
import json
from mmap import ACCESS_READ,mmap
from multiprocessing import get_context
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'.cache/wide_packaged_host_link/architecture_check'
sys.path.insert(0,str(ROOT/'syn'))
from audit_tri_oracle_mapped_redundancy import hierarchy,audit,SHARED_HEAD,SHARED_STRIP
from audit_tri_oracle_shared_prediction_roles import scan_head,scan_feedforward,SIGN_BANK
from audit_tri_oracle_booth_operand_spans import CELL
from verify_tri_oracle_booth_chip_link import named_bindings
from verify_tri_oracle_serialized_placement_transfer import catalog
from verify_tri_oracle_booth_chip_compute_geometry import compute_paths,connected_cluster_members
from verify_tri_oracle_booth_chip_geometry import geometry
from link_tri_oracle_indexed_whole_chip import signature
from audit_tri_oracle_packaged_storage import guard

TOP='tri_oracle_chip_credited_request'
PRODUCT=re.compile(rb'product\[(\d+)\]\.value\[(\d+)\]')
RESULT=re.compile(rb'out_sums\[(\d+)\]')


def sha(path):
 with path.open('rb') as f:return file_digest(f,'sha256').hexdigest()


def inspect_array(body,flip_flops):
 ports=signature(body)
 expected={'operand_a':(b'input',b'[2047:0]'),'operand_b':(b'input',b'[2047:0]'),
           'lane_enable':(b'input',b'[255:0]'),'out_sums':(b'output',b'[607:0]')}
 assert all(ports.get(k)==v for k,v in expected.items()),'Compute array port dimensions differ'
 products=Counter();results=Counter();types=Counter();result_clocks=Counter()
 for kind,instance,fields in CELL.findall(body):
  master=kind.decode()
  if master not in flip_flops:continue
  pins=named_bindings(fields)
  if 'Q' not in pins:continue
  net=pins['Q'].removeprefix(b'\\')
  if match:=PRODUCT.fullmatch(net):
   lane,bit=map(int,match.groups())
   assert instance.removeprefix(b'\\')==f'product[{lane}].value_reg[{bit}]'.encode(), 'Product register name and driven bit differ'
   assert pins.get('CP')==b'clk','Product register clock differs from array clock'
   assert flip_flops[master]=={'ff':1},'Product state is not one flip-flop'
   products[tuple(map(int,match.groups()))]+=1;types[master]+=1
  if match:=RESULT.fullmatch(net):
   assert flip_flops[master]=={'ff':1},'Result state is not one flip-flop'
   results[int(match[1])]+=1
   result_clocks[pins.get('CP',b'').decode()]+=1
 assert products==Counter((lane,bit) for lane in range(256) for bit in range(16)), 'Missing, repeated or crossed product register bit'
 assert results==Counter(range(608)), 'Missing or repeated result register bit'
 assert all(result_clocks),'Missing result register clock'
 return {'registered_product_groups':256,'product_bits_per_group':16,'registered_product_bits':sum(products.values()),
         'registered_result_bits':sum(results.values()),'product_register_masters':dict(types),
         'result_register_clock_nets':dict(result_clocks)}


def inspect_range(task):
 path,bounds,states=task
 with path.open('rb') as stream,mmap(stream.fileno(),0,access=ACCESS_READ) as source:
  return inspect_array(source[slice(*bounds)],states)


def verify():
 assert __debug__ and Path.cwd()==ROOT and not Path('/.dockerenv').exists()
 guard(); evidence={}
 def pin(p,expected=None):
  value=sha(p);assert expected is None or value==expected,p
  evidence[str(p.relative_to(ROOT))]=value;return p
 def read(p):return json.loads(pin(p).read_text())
 logic=read(ROOT/'records/tri_oracle_packaged_resize_logic.json')
 storage=read(ROOT/'records/tri_oracle_packaged_storage_accounting.json')
 placement=read(ROOT/'records/tri_oracle_wide_packetized_native_placement.json')
 targets=read(ROOT/'records/paper_result_targets.json')
 source=pin(ROOT/'.cache/wide_packaged_host_link/placement/native/cold.v',logic['source_cold_netlist_sha256'])
 candidate=pin(ROOT/'.cache/wide_packaged_host_link/drive_repair/host_legalized/candidate.v',logic['candidate_sha256'])
 assert storage['source_cold_netlist_sha256']==logic['source_cold_netlist_sha256']
 assert storage['candidate_sha256']==logic['candidate_sha256']
 for name,want in storage['evidence_sha256'].items():pin(ROOT/name,want)
 name,=storage['full_detail_cache'];detail=json.loads(pin(ROOT/name,storage['full_detail_cache'][name]).read_text())
 states={n:v['state_kinds'] for n,v in detail['standard_cell_state_by_master'].items()}
 assert targets['silicon']['processing_element_array_per_core']==[32,8]
 assert targets['silicon']['processing_element_precision']=='signed INT8'
 pin(ROOT/targets['source'],'6d6b998c459ade605e082d723374462e1d14b53d6a6b13063ca0f8d1180b1d9f')
 before,after=hierarchy(source),hierarchy(candidate)
 assert before==after and len(after)==771
 topology=audit(after,top=TOP)
 with ExitStack() as stack:
  modules=catalog(stack,[candidate]);members=compute_paths(modules)
  owners=connected_cluster_members(members,5,4)
  assert len(members)==len({m for _,m in members})==20
  tasks=[(candidate,modules[master][1:],states) for path,master in members]
  with ProcessPoolExecutor(max_workers=4,mp_context=get_context('spawn')) as pool:
   arrays=list(pool.map(inspect_range,tasks))
  shared=topology['additional_shared_prediction_instances'];assert len(shared)==2
  head,=(v for v in shared.values() if v.startswith(SHARED_HEAD))
  strip,=(v for v in shared.values() if v.startswith(SHARED_STRIP))
  def text(master):
   code,lo,hi=modules[master];return code[lo:hi]
  roles={'attention_tile_scheduler':scan_head(text(head),after[head]),
         'feedforward_metadata_and_sign_replay':scan_feedforward(text(strip),after[strip],text(SIGN_BANK))}
 layout=ROOT/'.cache/wide_packaged_host_link/placement/native/layout.def'
 pin(layout,placement['evidence_sha256'][str(layout.relative_to(ROOT))])
 die,units,rows,regions,groups,blockages=geometry(layout,verify_top=True)
 assert [(hi-lo)/(1000*units) for lo,hi in zip(die[:2],die[2:],strict=True)]==[3.6,3.6]
 assert len(regions)==len(groups)==20
 assert {name.replace(b'\\',b'').removesuffix(b'/') for name in groups}==set(owners.values())
 for module in ('audit_tri_oracle_mapped_redundancy','audit_tri_oracle_shared_prediction_roles',
                'audit_tri_oracle_booth_operand_spans','verify_tri_oracle_booth_chip_link',
                'verify_tri_oracle_serialized_placement_transfer','verify_tri_oracle_booth_chip_compute_geometry',
                'verify_tri_oracle_booth_chip_geometry','link_tri_oracle_indexed_whole_chip',
                'audit_tri_oracle_packaged_storage'):
  pin(ROOT/'syn'/f'{module}.py')
 pin(Path(__file__).resolve());guard()
 result={'state':'packaged_register_geometry_and_reachable_prediction_ownership_verified',
         'source_cold_netlist_sha256':logic['source_cold_netlist_sha256'],'candidate_sha256':logic['candidate_sha256'],
         'logical_top':TOP,'module_definitions':len(after),'clusters':topology['clusters'],
         'additional_shared_prediction_instances':shared,'shared_prediction_wiring':roles,
         'array_instances':len(members),'array_geometry':[32,8],'operand_bits':8,
         'array_register_inventory':{master:row for (path,master),row in zip(members,arrays,strict=True)},
         'total_registered_product_bits':sum(a['registered_product_bits'] for a in arrays),
         'total_registered_result_bits':sum(a['registered_result_bits'] for a in arrays),
         'die_dimensions_mm':[3.6,3.6],'array_placement_groups':len(groups),
         'complete_paper_architecture_verified':False,'advance_to_clock_distribution_or_routing_allowed':False,
         'evidence_sha256':evidence,
         'scope':'Structural inspection of the actual packaged top, before and after the exact 620 substitutions. '
                 'All twenty flattened arrays have 256 distinct 16-bit product register groups, 608 registered result bits and the disclosed operand dimensions. '
                 'Every array belongs to the matching four-core cluster and placement group. Shared score and prediction-response wiring is checked from named connections. '
                 'Die dimensions and group membership use the original cold placement; resized placement legality is not established here. '
                 'These checks do not prove multiplication or reduction arithmetic, full prediction behavior, full chip control, clock generation, trained full-model execution, accuracy or timing. '
                 'The hold-only advancement policy remains in force.'}
 WORK.mkdir(exist_ok=True);(WORK/'verified_structure.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
 print('PACKAGED_COMPUTE_STRUCTURE_VERIFIED',len(members),result['total_registered_product_bits'],result['total_registered_result_bits'],flush=True)
 return result


if __name__=='__main__':verify()
