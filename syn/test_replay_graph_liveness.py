"""Catch missed hierarchy instances, reachable unknown masters and recursion."""
from pathlib import Path
import unittest
from replay_graph_liveness import inventory

def body(name,instances=''):
 return f'module {name}(a,y); input a; output y; {instances} endmodule'.encode()

class GraphTests(unittest.TestCase):
 def test_shared_submodule_multiplicity_is_not_collapsed(self):
  bodies={'top':body('top','block u0(.a(a),.y(y)); block u1(.a(a),.y(y));'),'block':body('block','AND2 gate(.A(a),.B(a),.Z(y));')}
  result=inventory(set(bodies),bodies.__getitem__,{'AND2'},'top')
  self.assertEqual(result['module_occurrences'],{'top':1,'block':2})
  self.assertEqual(result['leaf_occurrences'],{'AND2':2})
  self.assertEqual(result['modules']['top']['project_instances'],{'u0':'block','u1':'block'})
 def test_unreachable_helper_does_not_become_connected_evidence(self):
  bodies={'top':body('top','BUF gate(.I(a),.Z(y));'),'unused':body('unused','MISSING gate(.I(a),.Z(y));')}
  result=inventory(set(bodies),bodies.__getitem__,{'BUF'},'top')
  self.assertEqual(result['unreachable_modules'],['unused'])
  self.assertEqual(result['leaf_occurrences'],{'BUF':1})
 def test_reachable_unknown_master_is_rejected(self):
  bodies={'top':body('top','MISSING gate(.I(a),.Z(y));')}
  with self.assertRaisesRegex(AssertionError,'Unknown reachable leaf'):inventory(set(bodies),bodies.__getitem__,{'BUF'},'top')
 def test_recursive_hierarchy_is_rejected(self):
  bodies={'top':body('top','block next(.a(a),.y(y));'),'block':body('block','top again(.a(a),.y(y));')}
  with self.assertRaisesRegex(AssertionError,'Recursive'):inventory(set(bodies),bodies.__getitem__,set(),'top')
 def test_requested_definition_must_match_actual_module_name(self):
  bodies={'top':body('other')}
  with self.assertRaisesRegex(AssertionError,'Module name'):inventory(set(bodies),bodies.__getitem__,set(),'top')
if __name__=='__main__':unittest.main()
