"""Export validation must reject corrupted or mismatched physical codebooks."""
from pathlib import Path
import sys,unittest
import torch
sys.path.insert(0,str(Path(__file__).resolve().parent))


class CodeExportTest(unittest.TestCase):
    def fixtures(self):
        # Original/current tensors[K=2,H=3] are local signed8 CPU fixtures.
        gate=torch.tensor([[0,-1,127],[-128,1,2]],dtype=torch.int8)
        up=-torch.ones(2,3,dtype=torch.int8)
        payload=dict(gate=gate.clone(),up=up.clone(),gate_exponent=-3,up_exponent=-2)
        payload['gate'][0,0]=1
        return gate,up,payload

    def test_valid_changes_preserve_signed_endpoints_and_inputs(self):
        from export_tri_oracle_gate_up_codes import validate_payload
        gate,up,payload=self.fixtures();saved=gate.clone()
        validate_payload(payload,gate,up,-3,-2)
        self.assertTrue(torch.equal(gate,saved))
        self.assertEqual(int(payload['gate'][0,2]),127)
        self.assertEqual(int(payload['gate'][1,0]),-128)

    def test_one_corrupted_code_is_rejected(self):
        from export_tri_oracle_gate_up_codes import validate_payload
        gate,up,payload=self.fixtures();payload['up'][1,2]=1
        with self.assertRaisesRegex(ValueError,'code step'):
            validate_payload(payload,gate,up,-3,-2)

    def test_wrong_shape_dtype_or_exponent_is_rejected(self):
        from export_tri_oracle_gate_up_codes import validate_payload
        for field,value in (('gate',torch.zeros(3,2,dtype=torch.int8)),
                            ('up',torch.zeros(2,3)),('gate_exponent',-4),('up_exponent',True)):
            gate,up,payload=self.fixtures();payload[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                validate_payload(payload,gate,up,-3,-2)


if __name__=='__main__':unittest.main()
