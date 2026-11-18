"""Exercise real integer routing and late correction on small graphics fixtures."""
from copy import copy
from collections import Counter
from hashlib import sha256
from pathlib import Path
import sys,unittest
from types import SimpleNamespace
from tempfile import NamedTemporaryFile
import torch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'syn'))


def fixture_configure(item,projection,index,codebook,context):
    """Self-contained baseline callback for32-feature synthetic comparisons.
    first/ordinary/calibrated references contain signed8 weights[K,H]/[O,K].
    Original Down[O,K] is per-output quantized; scales[O,1] and loaded codes
    come from this test's temporary file. No archived source or data is read.
    """
    from tri_oracle_integer_reference import _quantize
    from measure_tri_oracle_reciprocal_weight_equalization import evaluate_pair
    first=copy(item.reference);ordinary=copy(first)
    ordinary.down,scales=_quantize(projection.down_proj.weight,per_row=True)
    ordinary.down_exponent=scales.T
    record=torch.load(codebook,map_location='cpu',weights_only=True)
    calibrated=copy(ordinary);calibrated.down=record['codes'].to(ordinary.device)
    calibrated.down_exponent=record['scale'].to(ordinary.device).T
    assert torch.equal(calibrated.down_exponent,ordinary.down_exponent)
    def evaluate(activation,residual,**settings):
        """Inputs[M,H] use class evaluator outputs[M,O] and stats[M,...].
        For this tiny fixture only, public evaluate_pair independently supplies
        late-corrected values[M,O]. All possible32-channel integer sums are
        below2^24, so inversion of the power-of-two output scale[M,O] recovers
        exact signed32 totals[M,O] from float32 without precision loss.
        """
        prefill=item.decoder.prefill_active;first_row=prefill and context['calls'][index]==0
        context['calls'][index]+=1
        if first_row:assert activation.shape[0]==1 and int(item.decoder.positions[0])==0
        use_calibrated=prefill and not first_row and context['calibrated']
        reference=first if first_row else calibrated if use_calibrated else ordinary
        if use_calibrated:context['weight_rows'][index]+=activation.shape[0]
        raw,values,stats=reference.evaluate(activation,residual,**settings)
        if prefill and context['clipping'] and 17<=index<22:
            assert reference.channels*2*128*128<2**24
            policy=dict(buckets=[],fallback={name:settings[name] for name in ('maximum_up_gain_bits','down_shift_offset')})
            values=evaluate_pair(reference,activation,residual,policy,late=True)['pruned']
            scale=reference.down_exponent+stats['down_shift'][:,None]-8-stats['up_gain_bits'][:,None]
            raw=torch.ldexp(values.double(),-scale).to(torch.int32)
            context['clip_rows'][index]+=activation.shape[0]
            context['workload']['rows']+=activation.shape[0]
        return raw,values,stats
    item.reference.evaluate=evaluate


class CodeRoutingTest(unittest.TestCase):
    def test_real_first_ordinary_and_decode_match_the_selected_reference(self):
        # All fixture weights are[K=32,H=32]/[O=32,K=32]; token inputs[M,32].
        # Use the actual integer class and existing baseline/late-correction
        # helpers, with two temporary serialized codebooks removed in finally.
        assert torch.cuda.is_available() and not Path('/.dockerenv').exists()
        torch.set_num_threads(1);torch.manual_seed(7)
        from tri_oracle_gate_up_code_runtime import install
        from tri_oracle_integer_reference import IntegerFeedForwardReference,_quantize
        from export_tri_oracle_gate_up_codes import tensor_sha
        from measure_tri_oracle_reciprocal_weight_equalization import evaluate_pair
        weights=[torch.randn(32,32,device='cuda')*.3 for _ in range(3)]
        for weight in weights[:2]:weight[0,:]=.02
        reference=IntegerFeedForwardReference(*weights,1e-5)
        down,power=_quantize(weights[2],per_row=True)
        gate=reference.gate.clone();up=reference.up.clone()
        gate[0,0]+=1 if int(gate[0,0])<127 else -1
        up[0,0]+=1 if int(up[0,0])<127 else -1
        payload=dict(gate=gate.cpu(),up=up.cpu(),gate_exponent=reference.gate_exponent,up_exponent=reference.up_exponent)
        artifacts=ROOT/'.cache';artifacts.mkdir(exist_ok=True)
        with NamedTemporaryFile(dir=artifacts,prefix='gate_up_route_',suffix='.pt',delete=False) as f:candidate_file=Path(f.name)
        with NamedTemporaryFile(dir=artifacts,prefix='gate_up_down_',suffix='.pt',delete=False) as f:down_file=Path(f.name)
        try:
            torch.save(payload,candidate_file);torch.save(dict(codes=down.cpu(),scale=power.cpu()),down_file)
            exported=dict(layer=17,path=str(candidate_file),sha256=sha256(candidate_file.read_bytes()).hexdigest(),
                original_numeric_sha256={r:tensor_sha(getattr(reference,r)) for r in ('gate','up')},
                candidate_numeric_sha256={r:tensor_sha(payload[r]) for r in ('gate','up')})
            activation=torch.randn(4,32,device='cuda')*.2+.5;residual=torch.randn(4,32,device='cuda')*.1
            residual[:,:2]=10  # Two true normalization outliers exercise pruning on32 features.
            settings=dict(prune=True,maximum_up_gain_bits=7,down_shift_offset=-1,gate_threshold=0,up_window=0)
            policy=dict(buckets=[],fallback=dict(maximum_up_gain_bits=7,down_shift_offset=-1))
            for candidate_mode,selected in ((False,True),(True,False),(True,True)):
                def context():return dict(candidate=candidate_mode,calibrated=True,clipping=True,verify_raw=True,
                    calls=[0]*22,weight_rows=[0]*22,clip_rows=[0]*22,changed_rows=[0]*22,workload=Counter())
                actual_context=context();control_context=context()
                decoder=SimpleNamespace(prefill_active=True,positions=torch.tensor([0],device='cuda'))
                item=SimpleNamespace(reference=copy(reference),decoder=decoder)
                control=SimpleNamespace(reference=copy(reference),decoder=decoder)
                projection=SimpleNamespace(down_proj=SimpleNamespace(weight=weights[2]))
                install(item,projection,17,down_file,actual_context,exported if selected else None,configure=fixture_configure)
                fixture_configure(control,projection,17,down_file,control_context)
                # First prompt token must always use the exact current path.
                got=item.reference.evaluate(activation[:1],residual[:1],**settings)
                wanted=control.reference.evaluate(activation[:1],residual[:1],**settings)
                self.assertTrue(torch.equal(got[0],wanted[0]));self.assertTrue(torch.equal(got[1],wanted[1]))
                # Ordinary prefill must choose candidate only for selected layers.
                got=item.reference.evaluate(activation,residual,**settings)
                if candidate_mode and selected:
                    chosen=copy(reference);chosen.gate=gate;chosen.up=up
                    chosen.gate_sign=torch.where(gate<0,-1,1).to(torch.int8)
                    chosen.up_sign=torch.where(up<0,-1,1).to(torch.int8)
                    chosen.down=down;chosen.down_exponent=power.T
                    wanted=evaluate_pair(chosen,activation,residual,policy,late=True)['pruned']
                    self.assertTrue(torch.equal(got[1],wanted))
                    baseline=control.reference.evaluate(activation,residual,**settings)
                    self.assertFalse(torch.equal(got[1],baseline[1]),'Fixture must detect selecting baseline weights')
                else:
                    wanted=control.reference.evaluate(activation,residual,**settings)
                    self.assertTrue(torch.equal(got[0],wanted[0]));self.assertTrue(torch.equal(got[1],wanted[1]))
                self.assertEqual(actual_context['calls'][17],2)
                self.assertEqual(actual_context['weight_rows'][17],4)
                self.assertEqual(actual_context['clip_rows'][17],5)
                self.assertEqual(actual_context['changed_rows'][17],4 if candidate_mode and selected else 0)
                self.assertEqual(actual_context['workload']['rows'],5)
                if candidate_mode and selected:self.assertGreater(actual_context['workload']['retained_corrections'],0)
                # Generated tokens must return to the original decode path.
                decoder.prefill_active=False
                got=item.reference.evaluate(activation[:1],residual[:1],**settings)
                wanted=control.reference.evaluate(activation[:1],residual[:1],**settings)
                self.assertTrue(torch.equal(got[0],wanted[0]));self.assertTrue(torch.equal(got[1],wanted[1]))
                self.assertEqual(actual_context['calls'][17],3)
                self.assertEqual(actual_context['workload']['rows'],5)
        finally:
            candidate_file.unlink(missing_ok=True);down_file.unlink(missing_ok=True)


if __name__=='__main__':unittest.main()
