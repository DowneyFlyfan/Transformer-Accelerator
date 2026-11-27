"""Test actual code-input feed-forward arithmetic without a model or accelerator.

M is token rows, H=16 hidden features, K=16 intermediate channels, O=8 outputs.
All tensors originate in literal or deterministic CPU fixtures, never a model,
answer, hardware expected-output helper, floating activation, or old Q8 mask.
No loss, training, optimizer, graphics processor, or native EDA call is involved.
"""
import copy
import importlib
import math
from pathlib import Path
import sys
import unittest

import torch


def rounded(value, shift, bits):
    """Caller integer value/shift/width -> scalar ties-away saturated result.
    magnitude and remainder come from exact divmod, not implementation helpers.
    """
    magnitude, remainder = divmod(abs(value), 2**shift)
    magnitude += int(2*remainder >= 2**shift)
    signed = -magnitude if value < 0 else magnitude
    return min(2**(bits-1)-1, max(-2**(bits-1), signed))


def scalar_expected(codes, exponents, active, negative, gate, up, down,
                    weight_exponents, policy, prune):
    """Independent Python-list evaluator, no imported production arithmetic.

    codes/active/negative[M,H], gate/up[K,H], down[O,K] originate in test tensors
    converted to lists; exponents[M] and weight_exponents[3] are literal units.
    policy/prune are caller scalar metadata. Results use complete row/channel
    lists: raw[M,O], projection/nonlinear/margin/mask lists[M,K], scalar stats[M].
    Loop indices and all arithmetic temporaries are scalar integers. Samples[257]
    are independently evaluated mathematical SiLU values on the specified grid.
    """
    samples = []
    for index in range(257):
        position = -8 + index/16
        value = 256*position/(1+math.exp(-position))
        samples.append((-1 if value < 0 else 1)*math.floor(abs(value)+.5))
    result = {key: [] for key in (
        'raw', 'output_exponents', 'gate_margin', 'up_margin', 'skip', 'keep',
        'gate_dot', 'up_dot', 'gate_q8', 'up_q8', 'gated', 'down_input',
        'outlier_count', 'gate_shift', 'up_shift', 'down_shift', 'up_gain_bits')}
    for row, exponent in enumerate(exponents):
        setting = next((bucket for bucket in policy['buckets']
                        if bucket['activation_exponent'] == exponent), policy['fallback'])
        gate_shift = -exponent-weight_exponents[0]-8
        original_up = -exponent-weight_exponents[1]-8
        gain = min(original_up, setting['maximum_up_gain_bits'])
        up_shift = original_up-gain
        down_shift = max(0, gain+setting['down_shift_offset'])
        count = sum(active[row])
        margins = [[], []]
        projections = [[], []]
        quantized = [[], []]
        skipped, gated, down_inputs = [], [], []
        for channel in range(len(gate)):
            for branch, weights in enumerate((gate, up)):
                margins[branch].append(sum(
                    (1 if bool(negative[row][feature]) == (weight < 0) else -1)
                    for feature, weight in enumerate(weights[channel]) if active[row][feature]))
                projections[branch].append(sum(code*weight for code, weight in
                                               zip(codes[row], weights[channel])))
                quantized[branch].append(rounded(projections[branch][-1],
                                                (gate_shift, up_shift)[branch], 16))
            skip = bool(count and margins[0][-1] <= 0 and margins[1][-1] == 0)
            skipped.append(skip)
            gate_code = quantized[0][-1]
            if gate_code <= -2048:
                nonlinear = 0
            elif gate_code >= 2048:
                nonlinear = gate_code
            else:
                index, fraction = divmod(gate_code+2048, 16)
                nonlinear = rounded(samples[index]*(16-fraction)+samples[index+1]*fraction, 4, 16)
            gated.append(rounded(nonlinear*quantized[1][-1], 8, 16))
            down_inputs.append(0 if prune and skip else rounded(gated[-1], down_shift, 8))
        values = dict(raw=[sum(a*b for a, b in zip(down_inputs, weights)) for weights in down],
                      output_exponents=weight_exponents[2]+down_shift-8-gain,
                      gate_margin=margins[0], up_margin=margins[1], skip=skipped,
                      keep=[not value for value in skipped], gate_dot=projections[0],
                      up_dot=projections[1], gate_q8=quantized[0], up_q8=quantized[1],
                      gated=gated, down_input=down_inputs, outlier_count=count,
                      gate_shift=gate_shift, up_shift=up_shift, down_shift=down_shift,
                      up_gain_bits=gain)
        for key, value in values.items():
            result[key].append(value)
    return result


class CodeInputReferenceTests(unittest.TestCase):
    def setUp(self):
        """Literal/deterministic CPU-only fixtures, all owned by this test.
        gate/up[16,16],down[8,16] are signed8 trained-code stand-ins. codes[3,16]
        are deterministic signed8 C outputs; eA/positions[3] are signed64 units
        and global positions; active/negative[3,16] are Boolean feature planes.
        All remaining self fields are scalar metadata or the imported class.
        """
        path = Path(__file__).resolve().with_name('tri_oracle_code_input_reference_v1.py')
        self.assertTrue(path.is_file(), 'The code-input reference module is missing')
        sys.path.insert(0, str(path.parent))
        self.reference_class = importlib.import_module('tri_oracle_code_input_reference_v1').CodeInputFeedForwardReference
        torch.set_num_threads(1)
        self.gate = torch.tensor([[(channel*3+feature*5)%11-5 for feature in range(16)]
                                  for channel in range(16)], dtype=torch.int8)  # [K,H].
        self.up = torch.tensor([[(channel*7+feature*2)%9-4 for feature in range(16)]
                                for channel in range(16)], dtype=torch.int8)  # [K,H].
        self.down = torch.tensor([[(output*3+channel*2)%7-3 for channel in range(16)]
                                  for output in range(8)], dtype=torch.int8)  # [O,K].
        self.codes = torch.tensor([[64,-32,127,-128,3,-5,1,-1,11,-12,21,-22,7,-8,9,-10],
                                   [-1,2,-3,4,-5,6,-7,8,-9,10,-11,12,-13,14,-15,16],
                                   [33,-27,18,-19,4,-6,8,-2,14,-9,3,-7,15,-16,2,-1]],
                                  dtype=torch.int8)  # [M,H], literal actual-code stand-ins.
        self.exponents = torch.tensor([-6,-7,-6], dtype=torch.int64)  # [M], literal actual eA.
        self.positions = torch.tensor([9,2,7], dtype=torch.int64)  # [M], deliberately unsorted.
        self.active = torch.zeros((3,16), dtype=torch.bool)  # [M,H], then literal feature assignment.
        self.active[0,:2] = True
        self.active[1,3:6] = True
        self.negative = torch.zeros((3,16), dtype=torch.bool)  # [M,H], subset of active.
        self.negative[0,1] = True
        self.negative[1,4] = True
        self.policy = dict(fallback=dict(maximum_up_gain_bits=1, down_shift_offset=-1), buckets=[])
        self.weight_exponents = (-4,-4,-4)

    def construct(self, **changes):
        """Caller scalar overrides plus fixture weights[K,H]/[O,K] -> real class."""
        arguments = dict(gate=self.gate, up=self.up, down=self.down,
                         gate_exponent=self.weight_exponents[0], up_exponent=self.weight_exponents[1],
                         down_exponent=self.weight_exponents[2], layer=0,
                         checkpoint_revision='test-frozen-checkpoint')
        arguments.update(changes)
        return self.reference_class(**arguments)

    def evaluate(self, reference=None, **changes):
        """Fixture tensors[M,H]/[M] and caller overrides -> actual result dictionary."""
        arguments = dict(codes=self.codes, eA=self.exponents, outlier_mask=self.active,
                         outlier_negative=self.negative, layer=0, global_positions=self.positions,
                         phase=1, policy=self.policy, prune=True)
        arguments.update(changes)
        return (reference or self.construct()).evaluate_codes(**arguments)

    def compare_scalar(self, actual, *, prune=True, policy=None):
        """Actual tensor results[M,O]/[M,K]/[M] compared with independent lists."""
        expected = scalar_expected(self.codes.tolist(), self.exponents.tolist(), self.active.tolist(),
                                   self.negative.tolist(), self.gate.tolist(), self.up.tolist(),
                                   self.down.tolist(), self.weight_exponents, policy or self.policy, prune)
        self.assertEqual(set(expected)-set(actual), set())
        for key, value in expected.items():
            self.assertEqual(actual[key].tolist(), value, key)
        self.assertEqual(actual['raw'].dtype, torch.int32)
        self.assertEqual(actual['output_exponents'].dtype, torch.int64)
        self.assertEqual(actual['skip'].dtype, torch.bool)
        self.assertEqual(actual['keep'].dtype, torch.bool)

    def test_complete_intermediates_match_independent_scalar_without_pruning(self):
        # Catches wrong integer dot, rounding, nonlinear, physical unit or output layout.
        actual = self.evaluate(prune=False)  # Actual complete matrices[M,K]/[M,O] from fixture.
        self.compare_scalar(actual, prune=False)
        self.assertTrue(bool((actual['raw'] != 0).any()))

    def test_hand_checked_linear_tail_and_signed8_saturation(self):
        # Literal trace:64*32=2048;64*4=256;2048*256/256=2048;round(2048/16)=128->127.
        self.gate.zero_(); self.up.zero_(); self.down.zero_(); self.active.zero_(); self.negative.zero_()
        self.gate[0,0] = 32; self.up[0,0] = 4; self.down[:,0] = 1
        self.exponents.fill_(-4)
        self.policy['fallback'] = dict(maximum_up_gain_bits=0, down_shift_offset=4)
        actual = self.evaluate()  # [M,K]/[M,O], actual integer trace from modified literal matrices.
        self.assertEqual(actual['gate_dot'][0,0].item(), 2048)
        self.assertEqual(actual['up_dot'][0,0].item(), 256)
        self.assertEqual(actual['gated'][0,0].item(), 2048)
        self.assertEqual(actual['down_input'][0,0].item(), 127)
        self.assertEqual(actual['raw'][0].tolist(), [127]*8)
        self.assertEqual(actual['output_exponents'].tolist(), [-8]*3)
        self.compare_scalar(actual)

    def test_signed_half_ties_round_away(self):
        # Linear-tail channels yield gated+/-1024; shifting11 must give+/-1.
        self.gate.zero_(); self.up.zero_(); self.down.zero_(); self.active.zero_(); self.negative.zero_()
        self.gate[:2,0] = 32; self.up[0,0] = 2; self.up[1,0] = -2
        self.down[0,0] = 1; self.down[1,1] = 1
        self.exponents.fill_(-4)
        self.policy['fallback'] = dict(maximum_up_gain_bits=0, down_shift_offset=11)
        actual = self.evaluate()  # Actual [M,K]/[M,O] from literal half-tie fixture.
        self.assertEqual(actual['down_input'][0,:2].tolist(), [1,-1])
        self.assertEqual(actual['raw'][0,:2].tolist(), [1,-1])
        self.compare_scalar(actual)

    def test_quantized_zero_weight_is_positive_and_feature_sign_is_pre_gamma(self):
        # Using zero-valued weight signs or code sign instead of actual raw sign changes margins.
        self.gate.zero_(); self.up.zero_(); self.active.zero_(); self.negative.zero_()
        self.active[:,0] = True
        self.codes[:,0] = -64  # [M] post-negative-gamma codes; pre-gamma outlier sign remains positive.
        actual = self.evaluate()  # Actual margins[M,K] from C feature planes and zero weight codes.
        self.assertEqual(actual['gate_margin'].tolist(), [[1]*16]*3)
        self.assertEqual(actual['up_margin'].tolist(), [[1]*16]*3)
        self.assertFalse(bool(actual['skip'].any()))
        self.codes[:,0] = 0  # Rounded/zero-gamma output cannot erase a genuine pre-gamma outlier.
        zero_codes = self.evaluate()  # Actual margins[M,K] after literal code-only change.
        self.assertEqual(zero_codes['gate_margin'].tolist(), actual['gate_margin'].tolist())
        self.assertEqual(zero_codes['up_margin'].tolist(), actual['up_margin'].tolist())

    def test_gate_up_intersection_and_skip_to_keep_inversion(self):
        # For signs(+,-), first five channel margin pairs are(0,0),(-2,0),(2,0),(-2,2),(-2,-2).
        self.gate[:5,:2] = torch.tensor([[0,0],[-1,1],[1,-1],[-1,1],[-1,1]], dtype=torch.int8)  # [5,2], literal.
        self.up[:5,:2] = torch.tensor([[0,0],[0,0],[0,0],[1,-1],[-1,1]], dtype=torch.int8)  # [5,2], literal.
        actual = self.evaluate()  # Actual channel masks[M,K] and full down outputs[M,O].
        self.assertEqual(actual['gate_margin'][0,:5].tolist(), [0,-2,2,-2,-2])
        self.assertEqual(actual['up_margin'][0,:5].tolist(), [0,0,0,2,-2])
        self.assertEqual(actual['skip'][0,:5].tolist(), [True,True,False,False,False])
        self.assertTrue(torch.equal(actual['keep'], ~actual['skip']))
        self.assertFalse(bool(actual['skip'][2].any()), 'No outliers must preserve every channel')
        self.assertTrue(bool(actual['keep'][2].all()))
        self.compare_scalar(actual)

    def test_actual_exponent_policy_and_unsorted_original_row_order(self):
        # Re-quantizing magnitudes or sorting returned rows changes these scalar-unit results.
        policy = dict(layer=0, fallback=dict(maximum_up_gain_bits=1, down_shift_offset=-1),
                      buckets=[dict(activation_exponent=-7, fit_rows=23,
                                    maximum_up_gain_bits=-2, down_shift_offset=2)])
        actual = self.evaluate(policy=policy)  # Actual mixed-policy tensors[M,K]/[M,O].
        self.assertEqual(actual['gate_shift'].tolist(), [2,3,2])
        self.assertEqual(actual['up_gain_bits'].tolist(), [1,-2,1])
        self.assertEqual(actual['up_shift'].tolist(), [1,5,1])
        self.assertEqual(actual['down_shift'].tolist(), [0,0,0])
        self.compare_scalar(actual, policy=policy)
        changed = self.evaluate(codes=torch.zeros_like(self.codes), policy=policy)  # [M,H], zero initialized.
        for key in ('gate_shift','up_shift','down_shift','up_gain_bits','output_exponents'):
            self.assertTrue(torch.equal(actual[key], changed[key]), key)

    def test_shift_endpoints_and_negative_up_gain(self):
        # Prevent shift63 overflow, accidental left shift, or loss of negative gain compensation.
        self.exponents.fill_(-1)
        self.weight_exponents = (-70,-70,-4)
        self.policy['fallback'] = dict(maximum_up_gain_bits=0, down_shift_offset=63)
        actual = self.evaluate()  # [M,K]/[M], actual largest representable right shifts.
        self.assertEqual(actual['gate_shift'].tolist(), [63]*3)
        self.assertEqual(actual['up_shift'].tolist(), [63]*3)
        self.assertEqual(actual['down_shift'].tolist(), [63]*3)
        self.compare_scalar(actual)
        self.weight_exponents = (-4,-4,-4); self.exponents.fill_(-6)
        self.policy['fallback'] = dict(maximum_up_gain_bits=-2, down_shift_offset=2)
        actual = self.evaluate()  # [M,K]/[M], actual negative-gain arithmetic.
        self.assertEqual(actual['up_gain_bits'].tolist(), [-2]*3)
        self.assertEqual(actual['up_shift'].tolist(), [4]*3)
        self.assertEqual(actual['output_exponents'].tolist(), [-10]*3)
        self.compare_scalar(actual)

    def test_invalid_shift_calculations_are_rejected(self):
        for exponent in (-3,-73):
            with self.subTest(exponent=exponent), self.assertRaises(ValueError):
                self.evaluate(eA=torch.full_like(self.exponents, exponent))  # [M], literal invalid derived shift.
        with self.assertRaises(ValueError):
            self.evaluate(policy=dict(fallback=dict(maximum_up_gain_bits=0, down_shift_offset=64), buckets=[]))

    def test_constructor_rejects_invalid_shapes_dtypes_devices_and_bundle_identity(self):
        cases = [dict(gate=self.gate.float()), dict(up=self.up[:15]), dict(down=self.down[:7]),
                 dict(gate=self.gate[:,:15], up=self.up[:,:15]),
                 dict(down=self.down[:,:15]), dict(gate=torch.empty((16,16), device='meta', dtype=torch.int8)),
                 dict(layer=-1), dict(layer=22), dict(layer=True), dict(gate_exponent=True),
                 dict(up_exponent=-4.5), dict(checkpoint_revision=''), dict(checkpoint_revision=None)]
        for changes in cases:  # Each scalar dictionary selects a real constructor validation failure.
            with self.subTest(fields=tuple(changes)), self.assertRaises(ValueError):
                self.construct(**changes)

    def test_input_tensor_shapes_dtypes_devices_and_signed9_range_are_checked(self):
        cases = [dict(codes=self.codes.to(torch.int16)), dict(codes=self.codes.float()),
                 dict(codes=self.codes[:,:15]), dict(codes=self.codes[:0]),
                 dict(eA=self.exponents.float()), dict(eA=self.exponents[:,None]),
                 dict(eA=torch.tensor([-257,-6,-6], dtype=torch.int64)),
                 dict(eA=torch.tensor([256,-6,-6], dtype=torch.int64)),
                 dict(outlier_mask=self.active.to(torch.int8)), dict(outlier_negative=self.negative.to(torch.int8)),
                 dict(outlier_mask=self.active[:,:15]),
                 dict(outlier_negative=torch.empty((3,16), device='meta', dtype=torch.bool))]
        for changes in cases:  # Tensor variants inherit fixture dimensions unless explicitly invalidated.
            with self.subTest(fields=tuple(changes)), self.assertRaises(ValueError):
                self.evaluate(**changes)
        malformed = self.negative.clone()  # [M,H], owned Boolean feature-plane mutation.
        malformed[2,8] = True
        with self.assertRaises(ValueError):
            self.evaluate(outlier_negative=malformed)

    def test_only_ordinary_phase_unique_positive_positions_and_matching_layer_are_allowed(self):
        cases = [dict(phase=value) for value in (0,2,3,True,-1)]
        cases += [dict(layer=1), dict(layer=True), dict(prune=1),
                  dict(global_positions=torch.tensor([0,2,7], dtype=torch.int64)),
                  dict(global_positions=torch.tensor([9,2,2], dtype=torch.int64)),
                  dict(global_positions=self.positions.float()), dict(global_positions=self.positions[:,None])]
        for changes in cases:  # Positions[M] and scalar phase/layer/prune variants.
            with self.subTest(fields=tuple(changes)), self.assertRaises(ValueError):
                self.evaluate(**changes)

    def test_policy_rejects_ambiguous_unknown_or_mismatched_fields(self):
        pair = dict(maximum_up_gain_bits=1, down_shift_offset=-1)
        bucket = dict(activation_exponent=-6, **pair)
        cases = [dict(fallback=pair, buckets=[bucket,bucket]),
                 dict(fallback=pair, buckets=[], layer=1),
                 dict(fallback=pair, buckets=[], unknown=0),
                 dict(fallback=dict(**pair, unknown=0), buckets=[]),
                 dict(fallback=pair, buckets=[dict(**bucket, fit_rows=0)]),
                 dict(fallback=pair, buckets=[dict(**bucket, fit_rows=True)]),
                 dict(fallback=pair, buckets=[dict(**bucket, extra=1)]),
                 dict(fallback=dict(maximum_up_gain_bits=True, down_shift_offset=0), buckets=[]),
                 dict(fallback=dict(maximum_up_gain_bits=1), buckets=[]),
                 dict(fallback=pair, buckets=None)]
        for policy in cases:  # Scalar policy dictionaries copied before evaluation; no tensor metadata.
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                self.evaluate(policy=copy.deepcopy(policy))


if __name__ == '__main__':
    unittest.main()
