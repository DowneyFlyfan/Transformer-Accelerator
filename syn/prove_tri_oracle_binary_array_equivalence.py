"""Authenticate conditional binary equivalence of the20 mapped processing arrays.

This composes local mapped proofs and freshly repeatable joint row induction.
It does not release physical implementation or transfer native simulation.
"""
if not __debug__:raise RuntimeError('Array equivalence requires assertions')
from pathlib import Path
from hashlib import sha256,file_digest
import ast,json,resource,time,re
ROOT=Path(__file__).resolve().parents[1]
ROOTS={'arithmetic': ('.cache/wide_packaged_host_link/owner_score_proof/replay_arithmetic_abstraction_valid_faults.json',
                '995b8ea756a6663e0a137a891d3afa55398fe55821d2c060ddbefcf8d4d1e9e7'),
 'booth': ('.cache/wide_packaged_host_link/owner_score_proof/replay_old_booth_helpers_env_fixed.json',
           'cf7e72049f055c397004a58bfc84ceb31b8e9fb68a351fecb14fcfda6482376d'),
 'control': ('.cache/wide_packaged_host_link/owner_score_proof/replay_old_all_array_control_local_reset_bound.json',
             '362f91f4c6fcad9fe6f11e8d47332a14fddc3db6ac46ad47214ac7630641730c'),
 'data': ('.cache/wide_packaged_host_link/owner_score_proof/replay_old_array_complete_data_final.json',
          'fabb3bc62215ec8ec7c6b433809ca19b42e003e89718c42781cb430c2ee4a1b6'),
 'fanout': ('.cache/wide_packaged_host_link/owner_score_proof/replay_invalid_payload_fanout.json',
            '2749e4e4001b83ea6b97a16fa60ce6f806d6aaa4a9a5df61b5336d84851f870e'),
 'faults': ('.cache/wide_packaged_host_link/owner_score_proof/replay_old_all_data_valid_faults.json',
            '5ae3de162f59247cc8faf6ebb3cc18708976d63aa4dce47876890aced4c1e4a1'),
 'graph': ('.cache/wide_packaged_host_link/owner_score_proof/replay_old_array_graph_comparison.json',
           '61e213d6672a4de9fb5a47eb11263035f849f754b32a7caf81218451df7c9124'),
 'joint': ('.cache/wide_packaged_host_link/owner_score_proof/replay_joint_row_induction_final.json',
           'efb784fc582ef2e100e6d49d9abede095e97b67e034161b54d31b538566ae86b'),
 'native_models': ('.cache/wide_packaged_host_link/owner_score_proof/replay_native_build_compatibility.json',
                   'd14bd01280578c6b5c4048a381464a6b4b1fbf3981e53a69571a8e67625d3054'),
 'numeric': ('records/tri_oracle_numeric_pipeline_memory_history.json',
             '9136b47883d63d188fc48132a427880236b296ab8577456ca5b35e6c5b92757d'),
 'ring': ('.cache/wide_packaged_host_link/owner_score_proof/replay_ring_fifo_refinement.json',
          '0599a18deee63478b2d515ee4b492642710752dac8ca3a3b8e37dc7a3966f41b'),
 'state': ('.cache/wide_packaged_host_link/owner_score_proof/replay_complete_array_state_accounting.json',
           'cb920d67ef6b799bd0829ecf220fc80d54eeb86dbf0529e584b69dec20dd7bfa'),
 'stream': ('.cache/wide_packaged_host_link/owner_score_proof/replay_stream_induction608_accept_fixed.json',
            '7f4247e1ecf5814bbbd08201232d842a1f7b3684000920434ff67b8129788cee')}
SOURCE_ALIASES={'.cache/wide_packaged_host_link/owner_score_proof/replay_arithmetic_abstraction.py': 'syn/replay_arithmetic_abstraction.py',
 '.cache/wide_packaged_host_link/owner_score_proof/replay_array_stream.py': 'syn/replay_array_stream.py',
 '.cache/wide_packaged_host_link/owner_score_proof/replay_clock_gate_contract.py': 'syn/replay_clock_gate_contract.py',
 '.cache/wide_packaged_host_link/owner_score_proof/replay_graph_liveness.py': 'syn/replay_graph_liveness.py',
 '.cache/wide_packaged_host_link/owner_score_proof/replay_old_array_routes.py': 'syn/replay_old_array_routes.py',
 '.cache/wide_packaged_host_link/owner_score_proof/replay_resize_liberty.py': 'syn/replay_resize_liberty.py',
 '.cache/wide_packaged_host_link/owner_score_proof/replay_verilog_function.py': 'syn/replay_verilog_function.py'}
OLD='18bc427f73d8c5cd867fc35fa9efd891d3374fd82f73db0824275c8dd9e01498'
CURRENT='024fa9b5fa813f0c070db18a828e8c33a00c5c89d88671ea39488a8772c13b31'
REVIEW_SHA256='2fdb37b2438050e1e461ec92fe025bf3265da398c97f32f122c0271e5a5ab8ba'
REVIEW_IMPORTANT_FIXED=1
RELATED_TEST_LOG_SHA256='206f63fbc9d8810fe747b576851ba08a373d5c9bd347fdeda9614d957f55796b'

class ArtifactReader:
 def __init__(self,root):self.root=Path(root);self.evidence={}
 def add_pin(self,name,wanted):
  assert isinstance(name,str) and not Path(name).is_absolute() and '..' not in Path(name).parts,'Invalid artifact path'
  assert isinstance(wanted,str) and len(wanted)==64 and all(c in '0123456789abcdef' for c in wanted),'Invalid artifact digest'
  assert self.evidence.setdefault(name,wanted)==wanted,('Conflicting artifact digest',name)
 def read_bytes(self,name,wanted):
  content=(self.root/name).read_bytes();assert sha256(content).hexdigest()==wanted,('Artifact digest mismatch',name)
  self.add_pin(name,wanted);return content
 def read_json(self,name,wanted):return json.loads(self.read_bytes(name,wanted))
 def collect(self,value):
  if isinstance(value,dict):
   for name,wanted in value.get('evidence_sha256',{}).items():self.add_pin(name,wanted)
   for key,child in value.items():
    if key!='evidence_sha256':self.collect(child)
  elif isinstance(value,list):
   for child in value:self.collect(child)
 def revalidate(self):
  for name,wanted in self.evidence.items():
   with (self.root/name).open('rb') as stream:actual=file_digest(stream,'sha256').hexdigest()
   assert actual==wanted,('Artifact digest changed',name)

def queries(rows,expected,message):
 assert len(rows)==len(expected) and {r['label'] for r in rows}==set(expected),message+' coverage'
 assert all(r['result']=='unsat' for r in rows),message+' result'

def validate(d):
 native=d['native_models'];assert native['older_candidate_sha256']==OLD and native['current_candidate_sha256']==CURRENT and native['resized_vendor_nospecify_model_code_equivalence'] is True and len(native['resized_cell_pairs'])==22 and len(native['common_included_sources'])==10,'Native cell model compatibility'
 numeric=d['numeric'];assert numeric['candidate_sha256']==CURRENT and numeric['core_count']==20,'Current numeric candidate'
 cores=numeric['core_modules'];names={r['array_module'] for r in cores}
 assert len(cores)==len(names)==20 and {(r['bank'],r['core']) for r in cores}=={(b,c) for b in range(5) for c in range(4)},'Current array coverage'
 current={r['array_module']:r for r in cores}
 control=d['control'];old={r['module']:r for r in control['arrays']}
 assert control['older_candidate_sha256']==OLD and len(control['arrays'])==len(old)==20 and old.keys()==names,'Old array coverage'
 labels={'older_array_external_ready_valid','older_array_actual_control_resets','older_array_shadow_and_running_valid_next','older_array_actual_fifo_pointer_next','older_array_actual_fifo_occupancy_next','older_array_control_onehot_reset_basis','older_array_control_onehot_successor'}|{f'older_array_actual_clock_enable_RC_CG_HIER_INST{i}' for i in range(8)}
 hierarchy={'older_array_actual_common_local_reset_alias_bindings','global_reset_asserts_older_array_local_reset','older_array_actual_global_clock_binding'}
 assert control['queries']==360 and control['control_bits']==360,'Old control query totals'
 from replay_clock_gate_contract import validate_ckln_model
 assert len(control['primary_clock_gate_views'])==3 and all(validate_ckln_model(v) for v in control['primary_clock_gate_views'].values()),'Old clock-gate contract'
 for name,row in old.items():
  queries(row['queries'],labels,'Old control query');queries(row['hierarchy_bindings'],hierarchy,'Old hierarchy query')
  assert row['absolute_context']==current[name]['absolute_context']+'/compute' and row['selected_control_bits']==18 and len(row['registers'])==18 and len(row['gate_modules'])==8,'Old control binding'
 booth=d['booth'];helpers={r['master']:r for r in booth['helpers']}
 assert booth['older_candidate_sha256']==OLD and len(helpers)==len(booth['helpers'])==256 and booth['signed_operand_pairs_per_helper']==65536 and booth['helper_operand_pairs']==16777216,'Booth coverage'
 assert all(r['operand_pairs']==65536 and r['output_bits']==16 for r in helpers.values()) and len(booth['rejected_mapped_body_faults'])==2,'Booth coverage'
 graph=d['graph'];assert len(graph['rows'])==20 and {r['module'] for r in graph['rows']}==names and graph['cell_pairs']==[],'Old array graph coverage'
 for row in graph['rows']:
  assert row['structural_graph_matches_except_cell_masters'] is True and row['master_change_instances']==0 and row['pin_change_instances']==0 and row['noncell_mismatches']=={},'Old array graph mismatch'
  assert row['module_sha256']==old[row['module']]['module_sha256'],'Old array graph body binding'
 data=d['data'];assert data['older_candidate_sha256']==OLD and data['module']==graph['reference_array'] and data['module_sha256']==old[data['module']]['module_sha256'],'Old data reference binding'
 expected={f'product{i}_operands_and_masked_capture' for i in range(256)}|{f'row{r}_group{g}_first_compressor' for r in range(32) for g in range(2)}|{f'row{r}_{stage}' for r in range(32) for stage in ('second_compressor','final_add')}|{f'fifo_slot{i}_all608_actual_data_inputs' for i in range(3)}|{'all608_output_bits_actual_fifo_selection_and_bypass'}
 queries(data['queries'],expected,'Old data query');assert data['rows']==list(range(32)) and data['selected_data_register_bits']==9856,'Old data row coverage'
 state=d['state'];rows=state['arrays'];assert len(rows)==40 and {(r['design'],r['module']) for r in rows}=={(kind,name) for kind in ('older','current') for name in names},'Complete array state coverage'
 for row in rows:
  is_old=row['design']=='older';name=row['module'];expected_hash=old[name]['module_sha256'] if is_old else current[name]['array_module_sha256']
  assert row['module_sha256']==expected_hash,('Old' if is_old else 'Current')+' array body binding'
  assert row['absolute_context']==current[name]['absolute_context']+'/compute','Complete array state context'
  assert row['complete_direct_state_coverage'] is True and row['selected_direct_registers']==(9874 if is_old else 8036) and row['helper_state_bits']==(8 if is_old else 0) and row['project_helpers']==(264 if is_old else 0),'Complete array state inventory'
  wanted={'product':4096,'first_compressor':2176,'second_compressor':1152,'final_result':608,'result_fifo':1824,'control':18} if is_old else {'product':4096,'reduction':3936,'control':4}
  assert row['role_counts']==wanted,'Complete array state roles'
 arithmetic=d['arithmetic'];a_names={'compress3_preserves_modular_sum19','compress4_preserves_modular_sum19','current_ready_and_reset_valid_match_stream_model','all32_rows_keep_the_same_608_bit_port_order'}|{f'signed_pair_add{w}_embeds_exactly_in19' for w in (16,17,18)}|{f'{kind}_physical_row_stage{i}_collapses_to_stream_payload' for kind in ('older','current') for i in range(4)}
 queries(arithmetic['queries'],a_names,'Arithmetic abstraction query')
 assert arithmetic['current_numeric_contract_sha256']==ROOTS['numeric'][1] and arithmetic['physical_data_contract_root_sha256']==ROOTS['data'][1] and arithmetic['word_bits']==19 and arithmetic['packed_word_bits']==608 and arithmetic['independent_output_rows']==32,'Arithmetic abstraction binding'
 queries(d['stream']['queries'],{'reset_basis','stream_successor','observable_valid_ready_and_payload','full_result_hold_has_no_unprocessed_valid_tail_or_accept'},'Stream query');assert d['stream']['width']==608,'Stream width'
 queries(d['ring']['queries'],{'ring_control_reset_basis','ring_pointer_count_successor','onehot_occupancy_decodes_same_next_count','all608_ring_data_bits_refine_linear_fifo_prefix'},'Ring query');assert d['ring']['word_bits']==608,'Ring width'
 joint=d['joint'];j_names={'generic19_stream_inductive_successor','generic19_stream_ready_valid_and_valid_payload','physical_ring_pointer_and_occupancy_successor','physical_ring_next_valid_prefix_matches_linear_fifo','complete_arithmetic_ring_and_control_reset_basis','actual_next_relation_matches_model_on_valid_fifo_prefix','complete_actual_row_and_ring_joint_successor','complete_actual_row_external_ready_valid_and_payload'}
 queries(joint['joint_queries'],j_names,'Joint query')
 assert joint['arithmetic_queries_reexecuted']==15 and joint['row_word_bits']==19 and joint['independent_physical_rows_per_array']==32 and joint['exact_array_state_inventories']==40,'Joint arithmetic binding'
 assert {r['label'] for r in joint['nonvacuous_activations']}=={'empty_reset_control_relation','full_result_hold_with_source_valid','full_pop_and_push'} and len(joint['nonvacuous_activations'])==3 and all(r['result']=='sat' for r in joint['nonvacuous_activations']),'Joint nonvacuity'
 assert {r['control'] for r in joint['semantic_model_faults']}=={'ring_write_uses_postedge_arithmetic_result','ring_read_pointer_rotates_in_wrong_direction','occupancy_gate_treats_simultaneous_pop_push_as_increment','current_pipeline_releases_a_valid_result_while_stalled'} and len(joint['semantic_model_faults'])==4,'Joint fault coverage'
 assert all(r['result']=='sat' and r['witness']['rst']=='True' and r['scope']=='composed_model_not_actual_netlist_mutation' for r in joint['semantic_model_faults']),'Joint fault activation'
 faults=d['faults']['controls'];assert len(faults)==5 and {r['control'] for r in faults}=={'masked_product_bit0','first_compressor_bit0','second_compressor_carry2','final_result_bit0','fifo_capture_bit0'},'Actual mapped fault controls coverage'
 assert all(r['result']=='sat' and r['actual_mapped_body_mutation'] is True and r['activation']['local_reset_deasserted'] is True and r['original_module_sha256']==data['module_sha256'] and r['altered_module_sha256']!=r['original_module_sha256'] for r in faults),'Actual mapped fault controls binding'
 assert next(r for r in faults if r['control']=='masked_product_bit0')['activation']['input_valid'] is True,'Actual mapped fault controls input activation'
 fanout=d['fanout'];assert fanout['candidate_sha256']==CURRENT and len(fanout['cores'])==20 and {r['array_module'] for r in fanout['cores']}==names,'Invalid payload fanout coverage'
 for row in fanout['cores']:
  c=current[row['array_module']]
  assert row['module']==c['module'] and row['module_sha256']==c['core_module_sha256'] and row['absolute_context']==c['absolute_context'],'Invalid payload fanout body binding'
  assert row['source_payload_bits']==row['first_state_sink_registers']==608 and row['other_state_or_macro_sinks']==row['direct_public_output_sinks']==0,'Invalid payload fanout observers'
 assert len(fanout['service_noninterference'])==1 and fanout['service_noninterference'][0]['result']=='unsat','Invalid payload service noninterference'
 return dict(array_count=20,rows_per_array=32,output_bits=608,older_candidate_sha256=OLD,current_candidate_sha256=CURRENT,proof_inputs_complete=True,known_binary_only=True,initialization_contract=dict(requires_common_local_reset_or_established_joint_relation=True,arbitrary_initial_states_covered=False,reset_scope='common_effective_local_array_reset',required_relation='proved_control_ring_and_valid_payload_joint_relation',comparison_start='after_common_reset_establishes_the_relation_or_after_an_independent_initial_relation_proof'),observation_contract=dict(after_required_initialization=True,sampled_event='global_rising_edge_handshake',payload_is_settled=True,payload_equivalence_requires_output_valid=True),clock_contract=control['clock_contract'],whole_chip_equivalence_verified=False,older_replay_transfer_qualified=False,physical_timing_verified=False,task_accuracy_verified=False,advance_to_clock_distribution_or_routing_allowed=False)

REVIEW_PATH='.cache/wide_packaged_host_link/owner_score_proof/binary_array_equivalence_review.json'
RELATED_TEST_LOG_PATH='.cache/wide_packaged_host_link/owner_score_proof/binary_array_related_suite_final.log'

def review_qualified(reader,review_sha,fixed_count,test_sha):
 if review_sha is None:return False
 review=reader.read_json(REVIEW_PATH,review_sha)
 assert set(review)=={'critical','important','minor'} and all(isinstance(v,list) for v in review.values()),'Review schema'
 assert not review['critical'],'Critical review issue remains'
 assert isinstance(fixed_count,int) and fixed_count==len(review['important']),'Important review issue remains'
 text=reader.read_bytes(RELATED_TEST_LOG_PATH,test_sha).decode()
 assert text.rstrip().endswith(chr(10)+'OK') and not re.search(r'(?m)^FAILED\b',text),'Successful related tests required'
 counts=re.findall(r'(?m)^Ran (\d+) tests in ',text)
 assert len(counts)==1 and int(counts[0])>=241,'Related test coverage incomplete'
 return True

def verify(output,*,reprove_joint=False):
 assert not Path('/.dockerenv').exists(),'Run software proof composition on the host'
 from prove_tri_oracle_packaged_products import memory_guard
 memory_guard(10);start=time.monotonic();reader=ArtifactReader(ROOT);documents={key:reader.read_json(name,wanted) for key,(name,wanted) in ROOTS.items()}
 for doc in documents.values():reader.collect(doc)
 for cache_path,public_path in SOURCE_ALIASES.items():
  assert cache_path in reader.evidence,'Unpinned public helper alias'
  reader.add_pin(public_path,reader.evidence[cache_path])
 for path in [Path(__file__).resolve(),ROOT/'syn/test_tri_oracle_binary_array_equivalence_logic.py',*sorted((ROOT/'syn').glob('test_replay*.py'))]:
  with path.open('rb') as stream:reader.add_pin(str(path.relative_to(ROOT)),file_digest(stream,'sha256').hexdigest())
 reader.revalidate();summary=validate(documents)
 if reprove_joint:
  name='.cache/wide_packaged_host_link/owner_score_proof/run_replay_joint_row_induction_final.py';content=(ROOT/name).read_bytes();assert sha256(content).hexdigest()==reader.evidence[name]
  nodes=ast.parse(content,filename=name).body;stop,=[i for i,n in enumerate(nodes) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='result' for t in n.targets)]
  namespace=dict(__file__=str(ROOT/name),__name__='verified_joint_array_reexecution');exec(compile(ast.Module(body=nodes[:stop],type_ignores=[]),str(ROOT/name),'exec'),namespace)
  assert len(namespace['proved'])==15 and len(namespace['checks'])==8 and all(r['result']=='unsat' for r in namespace['checks'])
  assert len(namespace['faults'])==4 and len(namespace['activations'])==3
  assert {r['label']:r['proposition_sha256'] for r in namespace['checks']}=={r['label']:r['proposition_sha256'] for r in documents['joint']['joint_queries']},'Fresh joint proof differs from selected contract'
 reader.revalidate()
 review_complete=review_qualified(reader,REVIEW_SHA256,REVIEW_IMPORTANT_FIXED,RELATED_TEST_LOG_SHA256)
 if review_complete:assert reprove_joint,'Fresh joint proof required for qualification'
 reader.revalidate()
 result=dict(state='all_twenty_mapped_processing_arrays_conditionally_equivalent_for_known_binary_operation' if review_complete else 'conditional_binary_array_equivalence_pending_independent_review',**summary,independent_review_complete=review_complete,postfix_independent_review_performed=False,conditional_binary_array_equivalence_qualified=review_complete,joint_proof_reexecuted=reprove_joint,related_unit_tests_verified=review_complete,evidence_sha256=reader.evidence,elapsed_seconds=time.monotonic()-start,peak_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,scope='Exact20 older/current mapped array bodies under known-binary operation and the low-phase clock contract. Compared transactions start only after common effective local reset establishes the proved joint control/ring/valid-payload relation, or after that initial relation is independently established. Observations are global rising-edge handshakes and settled payloads only while output_valid is asserted; arbitrary initial states are excluded. Typed arithmetic, ring/stream induction, reset, complete state identities and guarded parent consumption are composed. Cached raw proofs are authenticated and optional joint proof rerun is recorded. Unknown-state/vendor-X behavior, compiled saved-state provenance, whole-chip integration, native execution transfer, timing, accuracy and paper matching remain unqualified.')
 output=output.resolve();assert output.is_relative_to(ROOT/'.cache') and not output.exists(),'Preserve outputs and keep proof artifacts in .cache'
 with output.open('x') as stream:stream.write(json.dumps(result,indent=2)+chr(10))
 print(result['state'],20,result['elapsed_seconds'],flush=True)
 return result

if __name__=='__main__':
 import argparse
 resource.setrlimit(resource.RLIMIT_AS,(3*2**30,3*2**30));parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);parser.add_argument('--reprove-joint',action='store_true');args=parser.parse_args();verify(args.output,reprove_joint=args.reprove_joint)
