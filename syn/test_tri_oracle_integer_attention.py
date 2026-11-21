"""Actual zero-interface regression, with no graphics allocation required."""
import os,sys,unittest
from pathlib import Path
os.environ.update(OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
import torch
from tri_oracle_integer_attention import project_output,project_qkv,classify_heads,attend
class ZeroContext(unittest.TestCase):
    def test_zero_has_representable_native_units(self):
        # All tensors are CPU physical-format constants with shapes as named.
        accum=torch.zeros((32,1,64),dtype=torch.int32)
        projection_exponents=torch.full((40,),-5,dtype=torch.int64)
        weights=torch.zeros((32,64,2048),dtype=torch.int8)
        weight_exponents=torch.zeros(32,dtype=torch.int64)
        output_exponents=torch.full((32,),-7,dtype=torch.int64)
        try:result=project_output(accum,projection_exponents,weights,weight_exponents,output_exponents)
        except ValueError as error:self.fail('Valid zero context rejected: '+str(error))
        self.assertFalse(bool(result['context_codes'].any()))
        self.assertFalse(bool(result['codes'].any()))
        self.assertTrue(bool(((result['shifts']>0)&(result['shifts']<49)).all()))
class AttentionContracts(unittest.TestCase):
    def cache(self,count=41):
        # Caller-owned signed8 cache[A=40,T,D=64], fixed exponents[A].
        values=torch.zeros((40,count,64),dtype=torch.int8)
        for group in range(4):values[36+group]=group+1
        return values,torch.full((40,),-5,dtype=torch.int64)
    def test_single_visible_key_preserves_grouped_values(self):
        vectors,exponents=self.cache()
        positions=list(range(5))+[5]+list(range(581,616))
        state=classify_heads(vectors,exponents,41)
        result=attend(vectors,exponents,positions,[0]*576,5,[0],state)
        self.assertEqual(result['probabilities'][:,:,0].tolist(),[[65535]]*32)
        self.assertFalse(bool(result['probabilities'][:,:,1:].any()))
        for head in range(32):self.assertEqual(result['accumulators'][head,0].tolist(),[65535*(head//8+1)]*64)
    def test_classifier_counts_its_two_native_bands(self):
        vectors,exponents=self.cache(100);state=classify_heads(vectors,exponents,100)
        # Four query rows96..99 have32inner keys each and1+2+3+4recent.
        self.assertEqual([r['inner'] for r in state['records']],[128]*32)
        self.assertEqual([r['recent'] for r in state['records']],[10]*32)
        self.assertEqual([r['alpha'] for r in state['records']],[32768]*32)
        self.assertFalse(bool(state['flags'].any()))
    def test_cache_unit_mismatch_is_rejected(self):
        vectors,exponents=self.cache();state=classify_heads(vectors,exponents,41)
        positions=list(range(5))+[5]+list(range(581,616))
        with self.assertRaises(ValueError):attend(vectors,exponents+1,positions,[0]*576,5,[0],state)
    def test_zero_projection_preserves_legal_descriptor_fields(self):
        # Actual core geometry, all-zero input/weights; cosine1 in Q14 units.
        hidden=torch.zeros((1,2048));weights=torch.zeros((40,64,2048),dtype=torch.int8)
        weight_units=torch.zeros(40,dtype=torch.int64);output_units=torch.ones(40,dtype=torch.int64)
        cosine=torch.full((1,32),16384,dtype=torch.int16);sine=torch.zeros((1,32),dtype=torch.int16)
        result=project_qkv(hidden,weights,weight_units,output_units,cosine,sine)
        self.assertFalse(bool(result['vectors'].any()))
        self.assertEqual(result['base_shifts'].tolist(),[15]*36+[1]*4)
        self.assertEqual(result['biases'].tolist(),[0])

if __name__=='__main__':unittest.main()
