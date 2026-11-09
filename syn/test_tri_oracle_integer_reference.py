"""GPU integer reference against archived real-model independent golden outputs.
B=1 batch, M=4 selected positions, H=2048 hidden, K=5632 intermediate.
No expectation is produced by the implementation being tested.
"""
import json
import os
from pathlib import Path
import unittest
os.environ["USE_HUB_KERNELS"]="NO"
os.environ["HF_HUB_OFFLINE"]="1"
import torch
from safetensors import safe_open
from tri_oracle_integer_reference import IntegerFeedForwardReference


class IntegerReferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Load real checkpoint matrices and the four archived source/golden rows.
        Class attributes: reference holds fixed trained matrices; activation and
        residual[M,H] originate in the completed image-conditioned forward.
        Expected dense/predicted Python lists[M,H] come from the independently
        verified earlier NumPy/scalar experiment, not the new implementation.
        """
        torch.set_num_threads(1)
        if not torch.cuda.is_available():
            raise RuntimeError("This exact integer backend requires the local graphics processor")
        folder=Path(".cache/model_reference/tiny_llava_v1")
        index=json.loads((folder/"model.safetensors.index.json").read_text())["weight_map"]
        state={}
        for unit in ["gate", "up", "down"]:
            key="language_model.model.layers.0.mlp."+unit+"_proj.weight"
            with safe_open(folder/index[key],framework="pt",device="cpu") as weights:
                state[unit]=weights.get_tensor(key).cuda()  # gate/up[K,H], down[H,K]
        source=json.loads(Path(".cache/model_reference/image_quantization_samples.json").read_text())
        cls.reference=IntegerFeedForwardReference(state["gate"],state["up"],state["down"],source["epsilon"])
        cls.activation=torch.tensor([s["ffn_activation"] for s in source["samples"]],device="cuda",dtype=torch.float32)  # [M,H], actual normalized inputs
        cls.residual=torch.tensor([s["residual_before_rms"] for s in source["samples"]],device="cuda",dtype=torch.float32)  # [M,H], actual pre-scale residuals
        cls.dense=[s["dense_expected"] for s in source["samples"]]
        cls.predicted=[s["predicted_expected"] for s in source["samples"]]
        cls.norm=[s["norm_codes"] for s in source["samples"]]

    def test_actual_dense_outputs_match_all_8192_independent_words(self):
        """Catches incorrect quantization, signed dot sums, nonlinear or output scaling."""
        raw,values,stats=self.reference.evaluate(self.activation,self.residual,prune=False)
        # raw/values[M,H]; stats tensors have shapes documented by evaluate.
        self.assertEqual(raw.cpu().tolist(),self.dense)
        # Independent archived format: down exponent-7, shift6, up gain7 and
        # eight fractional bits give physical output scale2**(-7+6-8-7).
        expected=torch.tensor(self.dense,dtype=torch.float32)*(2.0**-16)  # [M,H], archived raw words with literal physical scale
        torch.testing.assert_close(values.cpu(),expected,rtol=0,atol=0)
        self.assertEqual(stats["norm_codes"].cpu().tolist(),self.norm)
        self.assertEqual(stats["up_gain_bits"].cpu().tolist(),[7,7,7,7])
        self.assertEqual(stats["down_shift"].cpu().tolist(),[6,6,6,6])

    def test_actual_predicted_outputs_match_all_8192_independent_words(self):
        """Catches wrong outlier sign, predictor branch intersection or skipped channel mapping."""
        raw,values,stats=self.reference.evaluate(self.activation,self.residual,prune=True)
        # raw/values[M,H], prediction counts[M].
        self.assertEqual(raw.cpu().tolist(),self.predicted)
        expected=torch.tensor(self.predicted,dtype=torch.float32)*(2.0**-16)  # [M,H], same independently archived physical format
        torch.testing.assert_close(values.cpu(),expected,rtol=0,atol=0)
        self.assertEqual(stats["skip_count"].cpu().tolist(),[825,951,999,869])

    def test_compensated_values_with_literal_positive_zero_and_negative_gains(self):
        """Catches a missing/wrong gain or down-shift exponent in returned values.

        One nonzero channel: gate1, up1/2, input1. SiLU(1) rounds to187/256.
        At gain0, gatedQ8=round(187*128/256)=94. At gain3, gatedQ8=748
        and down shift3 gives94. At gain-2, gatedQ8=round(187*32/256)=23.
        The signed8 down weight1 has code64 and exponent-6. These independent
        literal outputs include row signs and power-of-two weight fractions.
        """
        gate=torch.zeros((16,16),dtype=torch.float32,device="cuda")  # [K=16,H=16], literal matrix
        up=torch.zeros_like(gate)  # [K,H], literal matrix
        down=torch.zeros((8,16),dtype=torch.float32,device="cuda")  # [O=8,K], literal rows
        gate[0,0]=1;up[0,0]=.5
        down[:,0]=torch.tensor([1,.5,-1,-.5,.25,-.25,0,0],device="cuda")  # [O], explicit down coefficients
        activation=torch.zeros((1,16),dtype=torch.float32,device="cuda")  # [M=1,H], literal vector
        activation[0,0]=1
        reference=IntegerFeedForwardReference(gate,up,down,0)
        cases=[
            (0,[6016,3008,-6016,-3008,1504,-1504,0,0],[.3671875,.18359375,-.3671875,-.18359375,.091796875,-.091796875,0,0]),
            (3,[6016,3008,-6016,-3008,1504,-1504,0,0],[.3671875,.18359375,-.3671875,-.18359375,.091796875,-.091796875,0,0]),
            (-2,[1472,736,-1472,-736,368,-368,0,0],[.359375,.1796875,-.359375,-.1796875,.08984375,-.08984375,0,0]),
        ]
        for gain,words,physical in cases:
            with self.subTest(gain=gain):
                raw,values,stats=reference.evaluate(activation,activation,prune=False,maximum_up_gain_bits=gain,down_shift_offset=0)
                # raw/values[1,O]; expected[1,O] literal physical units.
                self.assertEqual(raw.cpu().tolist(),[words])
                expected=torch.tensor([physical],dtype=torch.float32)
                torch.testing.assert_close(values.cpu(),expected,rtol=0,atol=0)


if __name__=="__main__":
    unittest.main()
