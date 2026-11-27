"""Feed-forward reference at the actual signed-code normalization boundary.

M=token rows, H=input features, K=intermediate channels, O=output features.
The intended complete trained dimensions are H=2048,K=5632,O=2048. Small
aligned matrices are accepted for arithmetic tests. This version uses scalar
per-tensor weight exponents and ordinary prefill only. It does not implement
protected-first tokens, decoding, attention, normalization, or model accuracy.

Inputs are actual normalizer codes, signed9 activation exponents, and distinct
pre-gamma outlier/sign planes. No activation re-quantization or rounded-Q8
outlier detection occurs here. Existing plain feed-forward rounding and SiLU
(sigmoid linear unit) arithmetic are retained, with fresh prediction features.
No training, loss function, optimizer, or hardware performance claim is made.
"""
import torch
import torch.nn.functional as functional

from tri_oracle_integer_reference import _requantize
from tri_oracle_model_reference import silu_code


def _signed9(value, name):
    """Caller scalar field -> checked Python integer; no tensor allocation.

    value/name are supplied scalar metadata; no float or Boolean coercion.
    """
    if type(value) is not int or not -256 <= value <= 255:
        raise ValueError(name + ' must be a signed9 Python integer')
    return value


def _policy_table(policy, layer):
    """Caller frozen scalar policy/layer -> bucket dictionary and fallback pair.

    table is initialized empty and keyed by signed9 activation exponents.
    item/setting are caller metadata dictionaries; allowed/required are key
    sets; exponent/fit_rows are scalar integers. No tensor or answer is used.
    """
    if (type(policy) is not dict or not {'fallback', 'buckets'} <= policy.keys()
            or set(policy) - {'fallback', 'buckets', 'layer'}):
        raise ValueError('Expected fallback, buckets and optional layer metadata')
    if 'layer' in policy and (type(policy['layer']) is not int or policy['layer'] != layer):
        raise ValueError('Policy and weight bundle layers differ')
    if type(policy['buckets']) is not list:
        raise ValueError('Policy buckets must be a list')

    def pair(setting, bucket=False):
        """Caller scalar setting plus bucket selector -> gain/down scalar pair.

        required/allowed are local metadata key sets, with no tensor axes.
        """
        required = {'maximum_up_gain_bits', 'down_shift_offset'}
        allowed = required | ({'activation_exponent', 'fit_rows'} if bucket else set())
        if type(setting) is not dict or not required <= setting.keys() or set(setting) - allowed:
            raise ValueError('Invalid policy setting fields')
        if bucket and 'activation_exponent' not in setting:
            raise ValueError('Missing activation exponent')
        if 'fit_rows' in setting and (type(setting['fit_rows']) is not int or setting['fit_rows'] <= 0):
            raise ValueError('fit_rows must be a positive Python integer')
        return (_signed9(setting['maximum_up_gain_bits'], 'gain cap'),
                _signed9(setting['down_shift_offset'], 'down offset'))

    fallback = pair(policy['fallback'])
    table = {}
    for item in policy['buckets']:
        setting = pair(item, bucket=True)
        exponent = _signed9(item['activation_exponent'], 'bucket exponent')
        if exponent in table:
            raise ValueError('Duplicate activation-exponent buckets')
        table[exponent] = setting
    return table, fallback


def _dot_codes(left, right):
    """Caller signed8 left[B,R],right[N,R] -> exact signed32[B,N] dot sums.

    B is selected token rows, R the complete reduction dimension, N output
    channels. CPU casts[ B,R]/[N,R] use signed64 multiplication. CUDA
    (Compute Unified Device Architecture) padded[P,R], P>=32 and divisible16,
    is zero-initialized by functional.pad for the native signed8 kernel.
    rows/padded_rows are scalar sizes. Constructor bounds R to keep sums32-bit.
    """
    if left.device.type == 'cpu':
        return (left.to(torch.int64) @ right.to(torch.int64).t()).to(torch.int32)
    rows = left.shape[0]
    padded_rows = max(32, ((rows + 15) // 16) * 16)
    padded = functional.pad(left.contiguous(), (0, 0, 0, padded_rows - rows))
    return torch._int_mm(padded, right.t())[:rows]


class CodeInputFeedForwardReference:
    @torch.inference_mode()
    def __init__(self, gate, up, down, *, gate_exponent, up_exponent,
                 down_exponent, layer, checkpoint_revision):
        """Caller quantized gate/up[K,H],down[O,K], all signed8 on one device.

        Scalar per-tensor exponents, layer0..21 and checkpoint revision are
        caller bundle metadata; the revision string is not provenance proof.
        Internal weight tensors clone the caller matrices. Gate/up sign
        tables[K,H] derive from stored codes: negative iff code<0, zero positive.
        silu_response[65536] is initialized from the existing scalar transfer
        function; this software lookup size is not a hardware memory proposal.
        value/size are scalar validation metadata; all scalar fields are ints.
        """
        if (any(not isinstance(value, torch.Tensor) for value in (gate, up, down))
                or any(value.dtype != torch.int8 or value.device.type not in ('cpu', 'cuda')
                       for value in (gate, up, down))):
            raise ValueError('Signed8 matrices on a CPU or graphics processor required')
        if (gate.ndim != 2 or up.shape != gate.shape or down.ndim != 2
                or down.shape[1] != gate.shape[0]
                or any(value.device != gate.device for value in (up, down))):
            raise ValueError('Incompatible weight matrix shapes or devices')
        if (not 0 < gate.shape[1] <= 65535 or not 0 < gate.shape[0] <= 65535
                or gate.shape[1] % 16 or gate.shape[0] % 16
                or down.shape[0] <= 0 or down.shape[0] % 8):
            raise ValueError('Unsupported matrix alignment or accumulation bound')
        if type(layer) is not int or not 0 <= layer < 22:
            raise ValueError('Weight bundle layer must be0..21')
        if type(checkpoint_revision) is not str or not checkpoint_revision.strip():
            raise ValueError('Nonempty checkpoint revision metadata required')
        self.gate_exponent = _signed9(gate_exponent, 'gate exponent')
        self.up_exponent = _signed9(up_exponent, 'up exponent')
        self.down_exponent = _signed9(down_exponent, 'down exponent')
        self.layer, self.checkpoint_revision = layer, checkpoint_revision
        self.hidden, self.channels, self.outputs = gate.shape[1], gate.shape[0], down.shape[0]
        self.device = gate.device
        self._gate, self._up, self._down = (value.contiguous().clone() for value in (gate, up, down))
        self._gate_sign = torch.where(self._gate < 0, -1, 1).to(torch.int8)  # [K,H], code-derived signs.
        self._up_sign = torch.where(self._up < 0, -1, 1).to(torch.int8)  # [K,H], code-derived signs.
        self._silu_response = torch.tensor([silu_code(value) for value in range(-32768, 32768)],
                                          dtype=torch.int64, device=self.device)  # [65536], scalar LUT enumeration.

    @torch.inference_mode()
    def evaluate_codes(self, codes, eA, outlier_mask, outlier_negative, *,
                       layer, global_positions, phase, policy, prune):
        """Actual codes[M,H] signed8, eA[M] signed64 carrying signed9 values.

        Actual outlier_mask/outlier_negative[M,H] are Boolean pre-gamma planes;
        negative must be a subset of mask. global_positions[M] signed64 are
        unique positive positions, possibly unsorted; phase1 means ordinary
        prefill only. Scalar layer matches the bundle; prune is Boolean.
        policy is a caller frozen exponent table, not selected by outputs.

        table/fallback are checked scalar dictionaries/pairs; outputs is an
        initially empty trace dictionary. exponent/gain_cap/down_offset and
        derived shifts/gain are scalar integers. positions[B] selects original
        row indices for one eA bucket, initialized from nonzero(eA==exponent).
        active/negative[B,H] select actual planes; signals[B,H] is signed8
        +1/-1/0. count[B] is signed32. gate_margin/up_margin, gate_dot/up_dot
        [B,K] are exact signed32 sums. skip[B,K] and keep[B,K] are Booleans.
        row_codes[B,H] selects actual code rows; shift tensors[B,1] are filled
        from configuration. gate_q8/up_q8/products/gated[B,K] are signed64;
        down_input[B,K] is signed8 after optional skip zeroing. raw[B,O] is
        signed32. group stores those tensors plus filled scalar stats[B].
        Each output[M,...] is empty-allocated on the first group, then every
        original row is written once via index_copy_. name/value are trace
        keys/tensors, initialized by iteration. No floating activation exists.
        """
        if (type(layer) is not int or layer != self.layer or type(phase) is not int
                or phase != 1 or type(prune) is not bool):
            raise ValueError('Matching layer and ordinary prefill phase1 required')
        if (not isinstance(codes, torch.Tensor) or codes.dtype != torch.int8
                or codes.ndim != 2 or codes.shape[0] == 0 or codes.shape[1] != self.hidden
                or codes.device != self.device):
            raise ValueError('Expected nonempty signed8 code matrix on bundle device')
        for value in (eA, global_positions):  # [M], caller scalar-per-row tensors.
            if (not isinstance(value, torch.Tensor) or value.dtype != torch.int64
                    or value.shape != (codes.shape[0],) or value.device != self.device):
                raise ValueError('Expected signed64 per-row exponent/position vectors')
        for value in (outlier_mask, outlier_negative):  # [M,H], caller actual feature planes.
            if (not isinstance(value, torch.Tensor) or value.dtype != torch.bool
                    or value.shape != codes.shape or value.device != self.device):
                raise ValueError('Expected Boolean feature planes on bundle device')
        if (not bool(((eA >= -256) & (eA <= 255)).all())
                or not bool((global_positions > 0).all())
                or torch.unique(global_positions).numel() != codes.shape[0]
                or bool((outlier_negative & ~outlier_mask).any())):
            raise ValueError('Invalid exponent, ordinary position or outlier sign subset')
        table, fallback = _policy_table(policy, layer)
        outputs = {}
        for exponent in sorted(set(eA.tolist())):
            positions = torch.nonzero(eA == exponent, as_tuple=True)[0]  # [B], original row indices.
            gain_cap, down_offset = table.get(exponent, fallback)
            gate_shift = -(exponent + self.gate_exponent + 8)
            original_up_shift = -(exponent + self.up_exponent + 8)
            gain = min(original_up_shift, gain_cap)
            up_shift = original_up_shift - gain
            down_shift = max(0, gain + down_offset)
            if any(value < 0 or value > 63 for value in (gate_shift, up_shift, down_shift)):
                raise ValueError('Number format does not fit unsigned six-bit hardware shifts')
            active = outlier_mask.index_select(0, positions)  # [B,H], actual active bits.
            negative = outlier_negative.index_select(0, positions)  # [B,H], actual raw sign bits.
            signals = (torch.where(negative, -1, 1) * active).to(torch.int8)  # [B,H], signed indicators.
            count = active.sum(dim=-1, dtype=torch.int32)  # [B], actual outlier count.
            gate_margin = _dot_codes(signals, self._gate_sign)  # [B,K], exact sign margins.
            up_margin = _dot_codes(signals, self._up_sign)  # [B,K], exact sign margins.
            skip = (count[:, None] > 0) & (gate_margin <= 0) & (up_margin == 0)  # [B,K], local branch intersection.
            row_codes = codes.index_select(0, positions)  # [B,H], unchanged actual signed8 inputs.
            gate_dot = _dot_codes(row_codes, self._gate)  # [B,K], complete trained projections.
            up_dot = _dot_codes(row_codes, self._up)  # [B,K], complete trained projections.
            shift_tensor = torch.full((positions.numel(), 1), gate_shift, dtype=torch.int64,
                                      device=self.device)  # [B,1], filled hardware gate shift.
            gate_q8 = _requantize(gate_dot, shift_tensor, 16)  # [B,K], saturated signed16 codes.
            shift_tensor.fill_(up_shift)
            up_q8 = _requantize(up_dot, shift_tensor, 16)  # [B,K], compensated signed16 codes.
            products = self._silu_response[gate_q8 + 32768] * up_q8  # [B,K], signed64 products.
            shift_tensor.fill_(8)
            gated = _requantize(products, shift_tensor, 16)  # [B,K], signed16 Q8 gated codes.
            shift_tensor.fill_(down_shift)
            down_input = _requantize(gated, shift_tensor, 8).to(torch.int8)  # [B,K], single signed8 plane.
            if prune:
                down_input = down_input.masked_fill(skip, 0)  # [B,K], predicted channels removed.
            group = dict(raw=_dot_codes(down_input, self._down),
                         gate_margin=gate_margin, up_margin=up_margin, skip=skip, keep=~skip,
                         gate_dot=gate_dot, up_dot=up_dot, gate_q8=gate_q8, up_q8=up_q8,
                         gated=gated, down_input=down_input, outlier_count=count)
            for name, value in (('output_exponents', self.down_exponent + down_shift - 8 - gain),
                                ('gate_shift', gate_shift), ('up_shift', up_shift),
                                ('down_shift', down_shift), ('up_gain_bits', gain)):
                group[name] = torch.full((positions.numel(),), value, dtype=torch.int64,
                                         device=self.device)  # [B], configured physical units/statistics.
            for name, value in group.items():  # [B,O], [B,K] or [B], actual arithmetic tensors.
                if name not in outputs:
                    outputs[name] = torch.empty((codes.shape[0], *value.shape[1:]), dtype=value.dtype,
                                                device=self.device)  # [M,...], filled exactly once per row.
                outputs[name].index_copy_(0, positions, value)
        return outputs
