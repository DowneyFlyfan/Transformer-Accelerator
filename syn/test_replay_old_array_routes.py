import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'syn'))
from replay_old_array_routes import OldArrayRoutes
class UniqueStateTests(unittest.TestCase):
 def routes(self,load_unused=False):
  body=b"module pair (clk,A,B,left,right); input clk,A,B; output left,right; wire unused; DFF l (.CP(clk),.D(A),.Q(unused),.QN(left)); DFF r (.CP(clk),.D(B),.Q(unused),.QN(right)); endmodule"
  if load_unused:body=body.replace(b'wire unused;',b'wire unused, observed; BUF b (.I(unused),.Z(observed));')
  library={('DFF',p):dict(direction='input') for p in ('CP','D')}
  library.update({('DFF','Q'):dict(direction='output',function='IQ'),('DFF','QN'):dict(direction='output',function='IQN'),('BUF','I'):dict(direction='input'),('BUF','Z'):dict(direction='output',function='I')})
  return OldArrayRoutes(lambda _:body,{'pair'},library,{'DFF':{'ff':1}},'pair')
 def test_unused_shared_q_does_not_alias_two_live_qn_states(self):
  r=self.routes();roots=[r.trace('','left'),r.trace('','right')];self.assertEqual(len(set().union(*(r.graph.dependencies(x) for x in roots))),2)
 def test_complementary_outputs_can_have_opposite_values(self):
  r=self.routes();roots=[r.trace('','left'),r.trace('','right')]
  cuts={info['instance']:name for name,info in r.sequential_cuts.items()};self.assertEqual(set(cuts),{'l','r'})
  self.assertEqual(r.graph.evaluate(roots,{cuts['l']:0,cuts['r']:1}),[1,0])
 def test_a_consumed_multiple_driver_net_is_still_rejected(self):
  r=self.routes(True)
  with self.assertRaisesRegex(AssertionError,'Expected one command route driver'):r.trace('','observed')
if __name__=='__main__':unittest.main()
