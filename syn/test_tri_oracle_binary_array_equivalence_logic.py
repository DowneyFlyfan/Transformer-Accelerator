"""Reject incomplete or promoted conditional processing-array certificates."""
from pathlib import Path
from copy import deepcopy
from hashlib import sha256
import json,tempfile,unittest
from prove_tri_oracle_binary_array_equivalence import ROOT,ROOTS,ArtifactReader,validate,review_qualified,REVIEW_PATH,RELATED_TEST_LOG_PATH

class BinaryArrayEquivalenceTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.baseline={key:json.loads((ROOT/name).read_text()) for key,(name,_) in ROOTS.items()}
 def check_rejected(self,key,change,message):
  documents=deepcopy(self.baseline);change(documents[key])
  with self.assertRaisesRegex(AssertionError,message):validate(documents)
 def test_complete_current_and_old_arrays_have_conditional_scope(self):
  result=validate(self.baseline)
  self.assertEqual(result.get('array_count'),20)
  self.assertEqual(result.get('rows_per_array'),32)
  self.assertIs(result.get('whole_chip_equivalence_verified'),False)
  self.assertIs(result.get('older_replay_transfer_qualified'),False)
  self.assertIs(result.get('advance_to_clock_distribution_or_routing_allowed'),False)
 def test_unreset_binary_counterexample_is_excluded_by_initialization_contract(self):
  from replay_array_stream import empty_old,empty_new,old_step,new_step
  old=empty_old();old['shadow'][3]=True
  current=empty_new()
  self.assertNotEqual(old_step(old,False,False,0)[1:3],new_step(current,False,False,0)[1:3])
  initialization=validate(self.baseline).get('initialization_contract',{})
  self.assertIs(initialization.get('requires_common_local_reset_or_established_joint_relation'),True)
  self.assertIs(initialization.get('arbitrary_initial_states_covered'),False)
 def test_compared_transactions_start_after_the_reset_relation_is_established(self):
  from replay_array_stream import empty_old,empty_new,old_step,new_step
  old=empty_old();old['shadow'][3]=True;old['running'][3]=True;old['count']=3
  reset_old=old_step(old,False,False,0,False)[0];reset_new=new_step(empty_new(),False,False,0,False)[0]
  self.assertEqual(old_step(reset_old,False,False,0)[1:3],new_step(reset_new,False,False,0)[1:3])
  observation=validate(self.baseline).get('observation_contract',{})
  self.assertIs(observation.get('after_required_initialization'),True)
  self.assertEqual(observation.get('sampled_event'),'global_rising_edge_handshake')
  self.assertIs(observation.get('payload_is_settled'),True)
 def test_invalid_payload_counterexample_is_outside_the_comparison(self):
  from replay_array_stream import empty_old,empty_new,old_step,new_step
  old=empty_old();old['pipe'][3]=17;current=empty_new();current['pipe'][3]=23
  left=old_step(old,False,False,0);right=new_step(current,False,False,0)
  self.assertFalse(left[2]);self.assertFalse(right[2]);self.assertNotEqual(left[3],right[3])
  observation=validate(self.baseline).get('observation_contract',{})
  self.assertIs(observation.get('payload_equivalence_requires_output_valid'),True)
 def test_missing_old_array_cannot_be_qualified(self):self.check_rejected('control',lambda r:r['arrays'].pop(),'Old array coverage')
 def test_duplicate_old_array_cannot_hide_missing_array(self):self.check_rejected('control',lambda r:r['arrays'].__setitem__(-1,r['arrays'][0]),'Old array coverage')
 def test_current_state_inventory_must_bind_actual_array_body(self):
  def change(r):next(x for x in r['arrays'] if x['design']=='current')['module_sha256']='0'*64
  self.check_rejected('state',change,'Current array body binding')
 def test_different_old_standard_cell_master_is_not_covered_by_graph_identity(self):self.check_rejected('graph',lambda r:r['rows'][0].__setitem__('master_change_instances',1),'Old array graph')
 def test_omitted_last_row_arithmetic_query_rejects(self):
  def change(r):r['queries']=[q for q in r['queries'] if q['label']!='row31_final_add']
  self.check_rejected('data',change,'Old data query coverage')
 def test_failed_old_control_query_rejects(self):self.check_rejected('control',lambda r:r['arrays'][0]['queries'][0].__setitem__('result','sat'),'Old control query')
 def test_incomplete_booth_operand_exhaustion_rejects(self):self.check_rejected('booth',lambda r:r['helpers'][0].__setitem__('operand_pairs',65535),'Booth coverage')
 def test_an_extra_array_register_rejects(self):self.check_rejected('state',lambda r:r['arrays'][0].__setitem__('selected_direct_registers',9875),'Complete array state')
 def test_duplicate_joint_query_cannot_replace_successor(self):
  def change(r):r['joint_queries']=[r['joint_queries'][0] if q['label']=='complete_actual_row_and_ring_joint_successor' else q for q in r['joint_queries']]
  self.check_rejected('joint',change,'Joint query coverage')
 def test_unexecuted_actual_body_mutation_is_not_fault_evidence(self):self.check_rejected('faults',lambda r:r['controls'][0].__setitem__('actual_mapped_body_mutation',False),'Actual mapped fault controls')
 def test_unmasked_array_payload_observer_rejects(self):self.check_rejected('fanout',lambda r:r['cores'][0].__setitem__('direct_public_output_sinks',1),'Invalid payload fanout')
 def test_joint_fault_with_reset_asserted_rejects(self):self.check_rejected('joint',lambda r:r['semantic_model_faults'][0]['witness'].__setitem__('rst','False'),'Joint fault activation')
 def test_hash_conflict_is_rejected(self):
  reader=ArtifactReader(ROOT);reader.add_pin('same','0'*64)
  with self.assertRaisesRegex(AssertionError,'Conflicting'):reader.add_pin('same','1'*64)
 def test_json_is_parsed_from_verified_bytes_and_changes_reject(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'.cache/wide_packaged_host_link/owner_score_proof') as folder:
   root=Path(folder);p=root/'input.json';p.write_bytes(b'{"value":1}');wanted=sha256(p.read_bytes()).hexdigest();reader=ArtifactReader(root)
   self.assertEqual(reader.read_json('input.json',wanted),{'value':1})
   p.write_bytes(b'{"value":2}')
   with self.assertRaisesRegex(AssertionError,'digest'):reader.read_json('input.json',wanted)
class ReviewGateTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.cache/wide_packaged_host_link/owner_score_proof');self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def fixture(self,critical=(),fixed=1,count=241,ending='OK'):
  review=self.root/REVIEW_PATH;review.parent.mkdir(parents=True,exist_ok=True)
  review.write_text(json.dumps({'critical':list(critical),'important':[{'id':'I1','problem':'example'}],'minor':[]}))
  log=self.root/RELATED_TEST_LOG_PATH;log.write_text(f'Ran {count} tests in 0.100s\n\n{ending}\n')
  return ArtifactReader(self.root),sha256(review.read_bytes()).hexdigest(),fixed,sha256(log.read_bytes()).hexdigest()
 def test_review_and_successful_complete_suite_release_only_local_gate(self):self.assertTrue(review_qualified(*self.fixture()))
 def test_critical_review_issue_blocks(self):
  with self.assertRaisesRegex(AssertionError,'Critical'):review_qualified(*self.fixture(critical=['unfixed']))
 def test_unfixed_important_review_issue_blocks(self):
  with self.assertRaisesRegex(AssertionError,'Important'):review_qualified(*self.fixture(fixed=0))
 def test_failed_suite_is_never_counted_as_success(self):
  with self.assertRaisesRegex(AssertionError,'Successful related tests'):review_qualified(*self.fixture(ending='FAILED (failures=1)'))
 def test_shorter_suite_cannot_satisfy_coverage(self):
  with self.assertRaisesRegex(AssertionError,'Related test coverage'):review_qualified(*self.fixture(count=240))
 def test_unverified_test_log_digest_blocks(self):
  reader,review,fixed,_=self.fixture()
  with self.assertRaisesRegex(AssertionError,'digest'):review_qualified(reader,review,fixed,'0'*64)
 def test_absent_review_stays_unqualified(self):self.assertFalse(review_qualified(ArtifactReader(self.root),None,None,None))

if __name__=='__main__':unittest.main()
