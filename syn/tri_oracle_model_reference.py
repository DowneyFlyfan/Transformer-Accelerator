"""Pinned first-language-layer reference, complete gate/up/down or a small slice.

B=1 batch; T=prompt tokens; H=2048 hidden features; I=5632 intermediate
channels; K=64 or5632 selected intermediate channels; O=35 or2048 output rows.
This is not full vision-language inference, accuracy calibration, or the
paper's unpublished quantization recipe. Integer arithmetic is independent
of the Verilog implementation; no hardware function/table is imported.
"""
import hashlib
import json
import math
import os
from pathlib import Path


def requantize(value, shift, bits):
    """Scalar integers: signed value -> ties-away shift -> signed bits saturation.

    value comes from an exact dot/product; shift and bits are local format
    configuration. magnitude and rounded are scalar integer intermediates.
    """
    magnitude = abs(int(value))
    rounded = (magnitude + (1 << (shift - 1))) >> shift if shift else magnitude
    rounded = -rounded if value < 0 else rounded
    return max(-(1 << (bits - 1)), min((1 << (bits - 1)) - 1, rounded))


def select_up_shift(magnitude, original_shift):
    """Scalar peak raw up dot and original physical-format shift -> safer precision.

    magnitude comes from max(abs(up_dots)); original_shift is the scalar local
    scale budget. shift is the smallest nonnegative shift avoiding16-bit peak
    clipping, bounded by the original. Output interpretation compensates gain.
    """
    shift = 0
    while shift < original_shift and magnitude > 32767 * (1 << shift):
        shift += 1
    return shift


def silu_code(value):
    """Scalar signed code/256 -> sampled/interpolated sigmoid linear unit.

    value is a gate code. position/index/remainder are scalar grid coordinates;
    samples is two scalar mathematical samples; blend is their integer numerator.
    Samples are derived from exp(), independently of the hardware lookup table.
    """
    if value <= -2048:
        return 0
    if value >= 2048:
        return value
    position = value + 2048
    index, remainder = divmod(position, 16)
    samples = [round(256 * (-8 + point / 16) / (1 + math.exp(8 - point / 16)))
               for point in (index, index + 1)]
    blend = samples[0] * (16 - remainder) + samples[1] * remainder
    return requantize(blend, 4, 16)


def rms_prediction_codes(values, epsilon):
    """Pre-weight root-mean-square normalized prediction vector as signedQ8.

    values: scalar list [H] from last-token attention residual, before learned
    normalization weights. epsilon: scalar from checkpoint configuration.
    denominator: scalar root of mean squares plus epsilon, initialized from
    values. value and scaled: scalar per-feature intermediates. result: [H]
    signed16 codes/256, ties away; no mean subtraction or learned-weight mixing.
    """
    if not values or epsilon < 0 or not all(math.isfinite(value) for value in values):
        raise ValueError('Invalid root-mean-square normalization input')
    denominator = math.sqrt(math.fsum(value*value for value in values)/len(values)+epsilon)
    if denominator == 0:
        raise ValueError('Root-mean-square denominator is zero')
    result = []
    for value in values:
        scaled = value*256/denominator
        result.append(max(-32768,min(32767,(-1 if scaled<0 else 1)*math.floor(abs(scaled)+.5))))
    return result


def classify_prediction(gate_margins, up_margins, outlier_count, gate_threshold=0, up_window=0):
    """Independent scalar sign-estimator decisions from Fig31.6.5 structure.

    gate_margins/up_margins: [K] integer lists from outlier sign-match counts.
    outlier_count, gate_threshold, up_window: scalar count/configuration values.
    gate/up/skip: [K] Boolean lists initialized from the two separate tests.
    Nonpositive gate default, inclusive comparison and symmetric up window are
    local choices; the paper does not publish numerical decision thresholds.
    """
    if len(gate_margins)!=len(up_margins) or outlier_count<0 or up_window<0:
        raise ValueError('Invalid prediction counts or window')
    gate = [bool(outlier_count) and value<=gate_threshold for value in gate_margins]
    up = [bool(outlier_count) and -up_window<=value<=up_window for value in up_margins]
    skip = [left and right for left,right in zip(gate,up)]
    return gate,up,skip


def quantize_power2(values):
    """values: float tensor [*D], loaded checkpoint weights or measured activation.

    maximum: scalar maximum absolute input; exponent: scalar power-of-two scale;
    codes: integer tensor [*D], round ties away, saturate to signed eight bits.
    D preserves the caller's feature/channel axes. torch is the imported module.
    """
    import torch
    maximum = float(values.abs().max())
    exponent = math.ceil(math.log2(maximum / 127)) if maximum else 0
    codes = (values.sign() * torch.floor(values.abs() / (2.0 ** exponent) + .5)).clamp(-128, 127).to(torch.int32)
    return codes, exponent


def write_hex(path, values, bits):
    """path: output Path scalar; values: flattened scalar integer iterable.

    bits: scalar word width; stream: file handle; value: each integer scalar.
    Hex words encode signed values in two's complement, in iterable order.
    """
    with path.open('w') as stream:
        for value in values:
            stream.write(f'{int(value) & ((1 << bits)-1):0{bits//4}x}\n')


def prepare():
    """Load one real decoder layer; emit a sliced or complete integer hardware case.

    Every tensor below is annotated at its creation. Other variables are paths,
    configuration dictionaries, Python scalar indices/scales, or file handles.
    """
    os.environ["USE_HUB_KERNELS"] = "NO"
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import torch
    import torch.nn.functional as functional
    from safetensors import safe_open
    from transformers import AutoTokenizer, LlamaConfig
    from transformers.models.llama.modeling_llama import LlamaDecoderLayer, LlamaRotaryEmbedding
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    full_layer = os.environ.get('TRI_ORACLE_REFERENCE_FULL_LAYER','0')=='1'  # scalar Boolean from environment, complete first-layer feed-forward check
    folder = Path('.cache/model_reference/tiny_llava_v1')  # downloaded checkpoint directory
    default_destination = '.cache/model_reference/full_layer_fixture' if full_layer else '.cache/model_reference/feedforward_fixture'  # scalar path string, keep complete and sliced cases separate
    destination = Path(os.environ.get('TRI_ORACLE_MODEL_FIXTURE',default_destination))  # generated fixture directory
    if not destination.resolve().is_relative_to(Path('.cache').resolve()):
        raise ValueError('Reference artifacts must stay in the project cache')
    destination.mkdir(exist_ok=True)
    candidate = json.loads(Path('records/model_reference_candidate.json').read_text())
    if not candidate['weights_downloaded']:
        raise RuntimeError('Finish pinned weight checksums before reference execution')
    configuration = LlamaConfig(**json.loads((folder/'config.json').read_text())['text_config'])
    configuration._attn_implementation = 'eager'
    assert (configuration.hidden_size,configuration.intermediate_size,configuration.num_attention_heads,configuration.num_key_value_heads,configuration.head_dim)==(2048,5632,32,4,64)
    index = json.loads((folder/'model.safetensors.index.json').read_text())['weight_map']
    prefix = 'language_model.model.layers.0.'
    # state: dict of checkpoint tensors for one layer. Attention shapes are
    # query/output [H,H], key/value [256,H]; gate/up [I,H], down [H,I]; norms [H].
    state = {}
    for name, shard in index.items():
        if name.startswith(prefix):
            with safe_open(folder/shard, framework='pt', device='cpu') as weights:
                state[name[len(prefix):]] = weights.get_tensor(name)
    if not state:
        raise RuntimeError('Expected first-language-layer checkpoint keys are absent')
    with torch.device('meta'):
        layer = LlamaDecoderLayer(configuration, layer_idx=0)  # trained parameters with shapes above; no random materialized weights
    assert state['self_attn.q_proj.weight'].shape==(2048,2048)
    assert state['self_attn.k_proj.weight'].shape==(256,2048)
    assert state['mlp.gate_proj.weight'].shape==(5632,2048)
    assert state['mlp.down_proj.weight'].shape==(2048,5632)
    layer.load_state_dict(state, strict=True, assign=True)
    del state
    layer = layer.to(device='cuda', dtype=torch.float32).eval()
    tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True)
    prompt = 'Explain how an attention accelerator reduces memory traffic.'  # fixed text, no image tokens
    token_ids = tokenizer(prompt, return_tensors='pt').input_ids  # [B=1,T] integer vocabulary identifiers
    embedding_key = 'language_model.model.embed_tokens.weight'
    with safe_open(folder/index[embedding_key], framework='pt', device='cpu') as weights:
        embedding = weights.get_tensor(embedding_key)  # [32064,H] checkpoint vocabulary table, memory mapped
        hidden = functional.embedding(token_ids, embedding).cuda()  # [B=1,T,H], selected trained embeddings
    del embedding
    positions = torch.arange(token_ids.shape[1], device='cuda').unsqueeze(0)  # [B=1,T], deterministic token positions
    rotary = LlamaRotaryEmbedding(configuration, device='cuda')  # inverse frequencies [32], original model formula
    position_embeddings = rotary(hidden, positions)  # pair of [B=1,T,64] cosine/sine matrices
    causal = torch.full((token_ids.shape[1], token_ids.shape[1]), float('-inf'), device='cuda').triu(1)[None,None,:,:]  # [B=1,1,T,T] causal additive mask
    with torch.inference_mode():
        # normalized [B,T,H]: trained input root-mean-square normalization.
        normalized = layer.input_layernorm(hidden)
        # attention [B,T,H]: trained grouped-query self attention, causal and rotary.
        attention, attention_probabilities = layer.self_attn(normalized, position_embeddings=position_embeddings, attention_mask=causal)
        # attention_probabilities [B,32,T,T] are unused outside attention.
        del attention_probabilities
        residual = hidden+attention  # [B,T,H], pre-normalization attention residual
        # ffn_input [B,T,H]: true first-block post-attention normalized activation.
        ffn_input = layer.post_attention_layernorm(residual)
        groups = list(range(176)) if full_layer else [52,175]  # scalar group identifiers, all5632 channels or the original64-channel slice
        selected = torch.tensor([group*32+row for group in groups for row in range(32)])  # [K=5632 or64] original intermediate IDs
        gate = layer.mlp.gate_proj.weight[selected].cpu()  # [K,H], trained gate rows
        up = layer.mlp.up_proj.weight[selected].cpu()  # [K,H], trained up rows
        output_start, output_count = (0,2048) if full_layer else (2013,35)  # scalar output range; full-layer hardware driver splits2048 rows into480-row transactions
        down = layer.mlp.down_proj.weight[output_start:output_start+output_count].cpu()  # [O,I], real full row stride
        token_selector = os.environ.get('TRI_ORACLE_REFERENCE_TOKEN','-1')  # scalar selector, coverage-only choice
        token_index = int(token_selector) if token_selector!='first_skip' else -1  # scalar prompt position
        if token_selector=='first_skip':
            selection_gate, selection_gate_exponent = quantize_power2(gate)  # [K,H], scalar exponent; selection uses only signs
            selection_up, selection_up_exponent = quantize_power2(up)  # [K,H], scalar exponent
            token_index = -1
            for candidate_index in range(token_ids.shape[1]):
                candidate_source = residual[0,candidate_index].cpu()  # [H], real pre-scale residual
                candidate_codes = torch.tensor(rms_prediction_codes(candidate_source.tolist(),configuration.rms_norm_eps),dtype=torch.int32)  # [H] signed codes/256
                candidate_outliers = candidate_codes.abs()>768  # [H] Boolean
                candidate_count = int(candidate_outliers.sum())  # scalar
                candidate_gate_margin = 2*((selection_gate[:,candidate_outliers]<0)==(candidate_codes[candidate_outliers]<0)).sum(dim=1)-candidate_count  # [K] signed margins
                candidate_up_margin = 2*((selection_up[:,candidate_outliers]<0)==(candidate_codes[candidate_outliers]<0)).sum(dim=1)-candidate_count  # [K] signed margins
                if any(classify_prediction(candidate_gate_margin.tolist(),candidate_up_margin.tolist(),candidate_count)[2]):
                    token_index=candidate_index
                    break
            if token_index<0:
                raise RuntimeError('No nonempty skip case in this fixed prompt; do not claim pruning coverage')
        if not -token_ids.shape[1]<=token_index<token_ids.shape[1]:
            raise ValueError('Token index outside fixed prompt')
        token_index %= token_ids.shape[1]
        activation = ffn_input[0,token_index].cpu()  # [H], selected actual feed-forward activation
        prediction_input = residual[0,token_index].cpu()  # [H], before learned post-attention normalization weights
        norm_weight = layer.post_attention_layernorm.weight.detach().cpu()  # [H], trained scale excluded from prediction normalization
        floating = down[:,selected] @ (functional.silu(gate @ activation) * (up @ activation))  # [O], floating reference restricted to selected K channels
    activation_codes, activation_exponent = quantize_power2(activation)  # [H], scalar exponent
    gate_codes, gate_exponent = quantize_power2(gate)  # [K,H], scalar exponent
    up_codes, up_exponent = quantize_power2(up)  # [K,H], scalar exponent
    down_codes, down_exponent = quantize_power2(down)  # [O,I], scalar exponent
    gate_shift = -(activation_exponent + gate_exponent + 8)
    up_shift = -(activation_exponent + up_exponent + 8)
    if min(gate_shift,up_shift) < 0 or max(gate_shift,up_shift) > 63:
        raise RuntimeError('Selected power-of-two scales are outside existing hardware shift range')
    norm_codes = torch.tensor(rms_prediction_codes(prediction_input.tolist(),configuration.rms_norm_eps),dtype=torch.int32)  # [H], root-mean-square normalized before learned scale, signed codes/256; follows paper Fig31.6.5 order
    outliers = norm_codes.abs() > 768  # [H] Boolean local three-standard-deviation criterion
    outlier_count = int(outliers.sum())  # scalar shared by all selected channels
    gate_margin = 2*((gate_codes[:,outliers]<0)==(norm_codes[outliers]<0)).sum(dim=1)-outlier_count  # [K] signed count margin
    up_margin = 2*((up_codes[:,outliers]<0)==(norm_codes[outliers]<0)).sum(dim=1)-outlier_count  # [K] signed count margin
    gate_mask,up_mask,skip_mask = classify_prediction(gate_margin.tolist(),up_margin.tolist(),outlier_count)  # Three [K] Boolean lists: one-sided gate, interval up, AND
    skip = torch.tensor(skip_mask,dtype=torch.bool)  # [K] local prediction mask
    gate_dots = gate_codes @ activation_codes  # [K] exact signed32 sums, no overflow atH2048
    up_dots = up_codes @ activation_codes  # [K] exact signed32 sums
    original_up_shift = up_shift  # scalar physical-format shift before linear precision gain
    up_shift = select_up_shift(int(up_dots.abs().max()),original_up_shift)
    up_gain_bits = original_up_shift-up_shift  # scalar gain compensated at output; SiLU gate scale stays unchanged
    gate_q8 = [requantize(value,gate_shift,16) for value in gate_dots.tolist()]  # [K] scalar integer list
    up_q8 = [requantize(value,up_shift,16) for value in up_dots.tolist()]  # [K] scalar integer list
    products = [requantize(silu_code(g)*u,8,16) for g,u in zip(gate_q8,up_q8)]  # [K] signed16 gated codes/256
    down_shift = max(0,math.ceil(math.log2(max(1,max(map(abs,products)))/127)))  # scalar conversion shift
    gated_codes = torch.tensor([0 if bool(drop) else requantize(value,down_shift,8) for drop,value in zip(skip,products)],dtype=torch.int32)  # [K] signed8 gathered activations
    expected = down_codes[:,selected] @ gated_codes  # [O] exact signed32 hardware output sums
    dequantized = expected.float()*(2.0**(down_exponent+down_shift-8-up_gain_bits))  # [O] local floating-unit comparison
    write_hex(destination/'activation.hex',activation_codes.tolist(),8)
    write_hex(destination/'gate.hex',gate_codes.flatten().tolist(),8)
    write_hex(destination/'up.hex',up_codes.flatten().tolist(),8)
    write_hex(destination/'down.hex',down_codes.flatten().tolist(),8)
    write_hex(destination/'norm.hex',norm_codes.tolist(),16)
    write_hex(destination/'expected.hex',expected.tolist(),32)
    write_hex(destination/'skip.hex',skip.int().tolist(),8)
    write_hex(destination/'groups.hex',groups,16)
    write_hex(destination/'configuration.hex',[gate_shift,up_shift,down_shift,output_start,output_count],32)
    # Independent-audit source arrays [H], copied from the actual first block.
    prediction_source = {'residual_before_rms':prediction_input.tolist(),
                         'rms_epsilon':configuration.rms_norm_eps,
                         'learned_normalization_scale':norm_weight.tolist(),
                         'ffn_activation':activation.tolist()}
    (destination/'prediction_source.json').write_text(json.dumps(prediction_source)+'\n')
    manifest = {
        'repository':candidate['repository'],'revision':candidate['revision'],
        'scope':('complete first-language-layer feed-forward computation, selected prompt token,5632 intermediate channels and2048 output rows; no vision/later-block/full-model accuracy claim' if full_layer else 'one real language block, selected prompt token,64 selected intermediate channels and35 output rows; no vision/full-model accuracy claim'),
        'prompt':prompt,'token_ids':token_ids.tolist(),'token_position':token_index,'case_selection':('first prompt position with a nonempty predicted skip mask, for coverage only' if token_selector=='first_skip' else 'explicit prompt token; default last'),'activation_source':'embedding -> trained layer0 RMSNorm/causal grouped-query rotary attention -> residual -> trained post-attention RMSNorm',
        'hidden_features':2048,'dense_intermediate_stride':5632,'selected_groups':groups,'selected_channels':selected.tolist(),
        'output_start':output_start,'output_count':output_count,
        'activation_exponent':activation_exponent,'gate_exponent':gate_exponent,'up_exponent':up_exponent,'down_exponent':down_exponent,
        'gate_shift':gate_shift,'up_shift':up_shift,'down_shift':down_shift,'original_up_shift':original_up_shift,'linear_up_gain_bits':up_gain_bits,
        'prediction_normalization':'root-mean-square of attention residual before learned normalization scale; no centering; epsilon from checkpoint; follows Fig31.6.5',
        'negative_learned_normalization_weights':int((norm_weight<0).sum()),
        'gate_threshold':0,'up_margin_limit':0,'prediction_classifier':'gate_margin<=gate_threshold; abs(up_margin)<=up_margin_limit; AND; thresholds and inclusivity are local choices',
        'outlier_count':outlier_count,'skipped_channels':int(skip.sum()),'nonzero_down_inputs':int((gated_codes!=0).sum()),
        'local_float_max_absolute_error':float((dequantized-floating).abs().max()),
        'local_float_relative_l2_error':float(torch.linalg.vector_norm(dequantized-floating)/torch.linalg.vector_norm(floating)),
        'quantization_scope':'uncalibrated per-tensor power-of-two symmetric scales, signed rounding ties away; linear up gain is compensated in output scale, gate nonlinear scale unchanged; root-mean-square prediction before learned scale; quantization,threshold margin and framing remain local choices, not disclosed paper parameters',
        'rtl_compared':False,'full_paper_accuracy_matched':False,
        'files':{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in [*destination.glob('*.hex'),destination/'prediction_source.json']},
    }
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('TRI_ORACLE_MODEL_FIXTURE_PREPARED',json.dumps(manifest),flush=True)


if __name__=='__main__':
    prepare()
