import unittest
from replay_array_stream import empty_old,empty_new,old_step,new_step
class StreamTests(unittest.TestCase):
 def test_empty_pipeline_accepts_the_first_transaction(self):
  for initial,step in ((empty_old,old_step),(empty_new,new_step)):
   state,ready,valid,data=step(initial(),True,False,101)
   self.assertTrue(ready);self.assertFalse(valid)
 def test_full_stall_then_drain_retains_four_results_in_order(self):
  for initial,step in ((empty_old,old_step),(empty_new,new_step)):
   state=initial();taken=[]
   for cycle in range(14):
    valid=cycle<4;incoming=[101,202,303,404][cycle] if valid else 0;ready=cycle>=9
    state,inready,outvalid,outdata=step(state,valid,ready,incoming)
    self.assertEqual(inready,cycle<4 or cycle>=9)
    self.assertEqual(outvalid,4<=cycle<=12)
    if outvalid:self.assertEqual(outdata,101 if cycle<=9 else [202,303,404][cycle-10])
    if outvalid and ready:taken.append(outdata)
    if cycle==8 and step==old_step:self.assertEqual(state['count'],3);self.assertTrue(state['running'][3])
   self.assertEqual(taken,[101,202,303,404])
 def test_input_bubbles_preserve_exact_four_cycle_latency(self):
  for initial,step in ((empty_old,old_step),(empty_new,new_step)):
   state=initial();seen=[]
   for cycle in range(10):
    state,ready,valid,data=step(state,cycle in (0,2),True,12 if cycle==0 else 34)
    if valid:seen.append((cycle,data))
   self.assertEqual(seen,[(4,12),(6,34)])
 def test_reset_discards_a_stalled_pipeline(self):
  for initial,step in ((empty_old,old_step),(empty_new,new_step)):
   state=initial()
   for value in (1,2,3,4):state,*_=step(state,True,False,value)
   for _ in range(4):state,*_=step(state,False,False,0)
   state,*_=step(state,False,False,0,rst=False)
   for _ in range(8):
    state,ready,valid,data=step(state,False,True,0)
    self.assertFalse(valid);self.assertTrue(ready)
 def test_backpressure_keeps_a_held_valid_request_unaccepted(self):
  for initial,step in ((empty_old,old_step),(empty_new,new_step)):
   state=initial()
   for value in (101,202,303,404):state,*_=step(state,True,False,value)
   for _ in range(7):
    state,ready,valid,data=step(state,True,False,999)
    self.assertFalse(ready);self.assertTrue(valid);self.assertEqual(data,101)
   seen=[]
   for _ in range(8):
    state,ready,valid,data=step(state,False,True,0)
    if valid:seen.append(data)
   self.assertEqual(seen,[101,202,303,404])
if __name__=='__main__':unittest.main()
