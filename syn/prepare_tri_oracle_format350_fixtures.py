"""Prepare protected-format programming fixtures from the actual model prefix.

B=1 image, T=606 prefill tokens, H=2048 input/output features, D=5632 original
intermediate channels. For each of22 language layers retain global token0 and
one ordinary token with largest output energy. Choose two original32-channel
groups and35 consecutive original outputs for informative hardware coverage.
Full matrices are quantized before selection; neither policy nor model changes.
These are selected contributions, not complete layer sums or paper accuracy.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import torch
import torch.nn.functional as functional
from PIL import Image
from transformers import AutoTokenizer, LlavaForConditionalGeneration, LlavaProcessor
from transformers.models.clip.image_processing_pil_clip import CLIPImageProcessorPil
from evaluate_tri_oracle_format346_vqav2 import LayerReplacement
from tri_oracle_format345_first_token import evaluate_protected
from tri_oracle_integer_reference import _dot, _quantize, _requantize
from prepare_tri_oracle_format331_fixtures import hardware_shifts, write_hex
from tri_oracle_cached_feedforward_model_validation import scalar_outputs


def sha(path):
    """Caller scalar path -> streamed scalar digest, no tensor allocation."""
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def select_coverage(inputs, weights, *, output_count=35):
    """Caller signed8 down inputs[D] and weights[O,D], from full quantization.
    Scores[D] sum absolute represented channel contributions over original O
    rows; group_scores[D/32] pool those scores without signed cancellation.
    selected[64] preserves original channel IDs in two sorted original groups.
    partial[O] is their actual signed contribution; windows[O-count+1] sums
    absolute partial outputs. Return two Python group IDs and original start.
    CPU unit controls or CUDA trained tensors use identical integer operations.
    """
    if (inputs.ndim != 1 or weights.ndim != 2 or weights.shape[1] != inputs.numel()
            or inputs.numel() < 64 or inputs.numel() % 32
            or type(output_count) is not int or not 1 <= output_count <= weights.shape[0]
            or inputs.device != weights.device):
        raise ValueError('Aligned channels and a legal original-output window required')
    scores = inputs.to(torch.int64).abs() * weights.to(torch.int32).abs().sum(dim=0)
    group_scores = scores.reshape(-1, 32).sum(dim=1)
    groups = sorted(torch.argsort(group_scores, descending=True, stable=True)[:2].tolist())
    selected = torch.tensor([channel for group in groups for channel in range(group*32, (group+1)*32)],
                            dtype=torch.int64, device=inputs.device)
    partial = (weights.index_select(1, selected).to(torch.int32)
               * inputs.index_select(0, selected).to(torch.int32)[None, :]).sum(dim=1)
    windows = partial.abs().unfold(0, output_count, 1).sum(dim=1)
    start = int(windows.argmax())
    if int(windows[start]) == 0:
        raise ValueError('All-zero selected contribution cannot qualify programming')
    return groups, start


@torch.inference_mode()
def main():
    """Pinned image pixels and tokenizer produce IDs/mask[1,T], pixels[1,3,336,336].
    Original floating model has22 language layers;346 replacement objects hold
    full trained gate/up[D,H],down[H,D] signed8 references. Hooks capture actual
    normalized activation/residual[T,H] before replacing output[1,T,H]. Each
    selected role recomputes raw/values[1,H] and statistics and checks its value
    bitwise against the actual full-prefill hook output at that global position.

    Per role, codes[1,H], norm[H], full gate/up dots[1,D], gate/up/gated/down
    codes[1,D], and skip[1,D] use unchanged arithmetic. Full raw[1,H] must match
    the canonical reference. Selected64 channels retain original D stride;
    gate/up[64,H],down[35,D] and exact scalar expected[35] become hex fixtures.
    Padded down weights[48,64] provide an independent CUDA integer cross-check.
    No loss, optimizer, task scoring, answer consumption or hardware run occurs.
    """
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    output = root/'records/format350_fixture_preparation.json'
    directory = root/'.cache/model_reference/format350'
    assert not output.exists() and not directory.exists()
    qualified_path = root/'records/format349_protected_generation_qualification.json'
    assert sha(qualified_path) == 'f9a00bfef3120aad7adf05945c9b0f311582aac7d18ab46845dc83377d1f8f9c'
    qualified = json.loads(qualified_path.read_text())
    score_path = root/'records/format348_official_scoring.json'
    assert sha(score_path) == qualified['official_scoring_sha256']
    scored = json.loads(score_path.read_text())
    assert qualified['all320_cases_completed'] and qualified['incremental_decode_exercised_in_both_protected_modes']
    inputs = dict(scored['source_sha256'])
    for path in [Path(__file__), qualified_path, score_path,
                 root/'syn/test_tri_oracle_format350_coverage.py',
                 root/'syn/prepare_tri_oracle_format331_fixtures.py',
                 root/'syn/tri_oracle_cached_feedforward_model_validation.py',
                 root/'records/format350_architecture_validation.json']:
        inputs[str(path)] = sha(path)
    architecture = json.loads((root/'records/format350_architecture_validation.json').read_text())
    assert architecture['source_audits_completed'] == 3 and architecture['render_visually_verified']
    assert architecture['source_sha256'][str(Path(__file__).resolve())] == sha(__file__)
    assert sha(architecture['pdf']) == architecture['pdf_sha256']
    inputs[architecture['pdf']] = architecture['pdf_sha256']
    assert all(sha(path) == digest for path, digest in inputs.items())
    case = json.loads((root/'.cache/model_reference/ai2d285/inputs.json').read_text())['cases'][0]
    assert sha(case['image']) == case['image_sha256']
    model_path = root/'.cache/model_reference/tiny_llava_v1'
    loader = json.loads((root/'records/format320_loader_metadata.json').read_text())
    assert {p.name for p in model_path.iterdir() if p.is_file()} == set(loader['snapshot_file_names'])
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0] > 10*1024**3
    torch.cuda.set_per_process_memory_fraction(.84)
    torch.cuda.reset_peak_memory_stats()
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    image_processor = CLIPImageProcessorPil.from_pretrained(model_path, local_files_only=True)
    processor = LlavaProcessor(image_processor=image_processor, tokenizer=tokenizer,
                              patch_size=14, vision_feature_select_strategy='default', num_additional_image_tokens=1)
    with Image.open(case['image']) as opened:
        batch = processor(images=opened.convert('RGB'), text='USER: <image>\n'+case['question']+
                          '\nAnswer briefly.\nASSISTANT:', return_tensors='pt').to('cuda')
    assert batch['input_ids'].shape == (1, 606) and batch['pixel_values'].shape == (1, 3, 336, 336)
    model = LlavaForConditionalGeneration.from_pretrained(model_path, local_files_only=True,
        dtype=torch.float32, attn_implementation='sdpa', use_kernels=False).to('cuda').eval()
    layers = model.model.language_model.layers
    assert len(layers) == 22
    replacements = [LayerReplacement(index, layer) for index, layer in enumerate(layers)]
    directory.mkdir()
    started = time.monotonic()
    record = dict(state='preparing', started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_sha256=inputs, image_pixel_sha256=case['pixel_sha256'], prefill_tokens=606,
        layers=[], coverage_selection_only=True, policies_fitted=False, labels_used=False,
        source_hardware_verified=False, compiled_memory_verified=False,
        hardware_full_model_configuration_verified=False, full_paper_results_matched=False, scope=__doc__)

    def save():
        """Atomically persist caller scalar/JSON metadata, no model tensors."""
        record['elapsed_seconds'] = time.monotonic()-started
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(output)

    def capture(replacement, layer_index):
        """Closure captures scalar layer index and346 reference/policy object.
        The hook receives original activation/output[1,T,H]; residual[T,H]
        comes from original normalization's pre-hook, then is cleared by346.
        All local tensor dimensions follow main's complete arithmetic pipeline.
        """
        def after(module, args, original):
            activation = args[0].reshape(-1, 2048)
            residual = replacement.residual
            assert activation.shape == residual.shape == (606, 2048)
            actual = replacement.after_mlp(module, args, original)
            ordinary_position = 1+int(actual[0, 1:].float().square().sum(dim=-1).argmax())
            entries = []
            for role, position in [('first', 0), ('ordinary', ordinary_position)]:
                a, r = activation[position:position+1], residual[position:position+1]  # each[1,H].
                raw, values, stats = evaluate_protected(replacement.reference, a, r,
                    replacement.policy, replacement.first_policy, position, prune=True)
                assert torch.equal(values[0], actual[0, position]), 'Isolated row differs from actual protected prefix'
                reference = replacement.reference
                codes, exponent = _quantize(a, per_row=True)
                setting = replacement.first_policy if position == 0 else next(
                    (item for item in replacement.policy['buckets'] if item['activation_exponent'] == int(exponent.item())),
                    replacement.policy['fallback'])
                fields = hardware_shifts(int(exponent.item()), reference.gate_exponent, reference.up_exponent,
                    setting['maximum_up_gain_bits'], setting['down_shift_offset'])
                assert all(int(stats[key].item()) == fields[key] for key in ('gate_shift', 'up_shift', 'down_shift'))
                assert int(stats['up_gain_bits'].item()) == fields['gain']
                shifts = [fields[key] for key in ('gate_shift', 'up_shift', 'down_shift')]
                signs = (torch.where(stats['norm_codes'] < 0, -1, 1)*(stats['norm_codes'].abs() > 768)).to(torch.int8)
                gm, um = _dot(signs, reference.gate_sign), _dot(signs, reference.up_sign)  # each[1,D].
                skip = (stats['outlier_count'][:, None] > 0) & (gm <= 0) & (um == 0)
                assert int(skip.sum()) == int(stats['skip_count'].item())
                gate_q = _requantize(_dot(codes, reference.gate), stats['gate_shift'][:, None], 16)
                up_q = _requantize(_dot(codes, reference.up), stats['up_shift'][:, None], 16)
                gated = _requantize(reference.silu_response[gate_q+32768]*up_q,
                                    torch.full_like(stats['down_shift'][:, None], 8), 16)
                down_input = _requantize(gated, stats['down_shift'][:, None], 8).to(torch.int8).masked_fill(skip, 0)
                assert torch.equal(_dot(down_input, reference.down), raw), 'Full integer sum reconstruction differs'
                groups, start = select_coverage(down_input[0], reference.down)
                ids = [channel for group in groups for channel in range(group*32, (group+1)*32)]
                selected = torch.tensor(ids, dtype=torch.int64, device='cuda')  # [64], original IDs.
                activation_list = codes[0].cpu().tolist()  # [H] signed8.
                norm_list = stats['norm_codes'][0].cpu().tolist()  # [H] signed16.
                gate = reference.gate.index_select(0, selected).cpu().reshape(-1).tolist()  # [64*H].
                up = reference.up.index_select(0, selected).cpu().reshape(-1).tolist()  # [64*H].
                down = reference.down[start:start+35].cpu().reshape(-1).tolist()  # [35*D].
                skip_list = skip[0].index_select(0, selected).cpu().tolist()  # [64].
                outliers = [(i, -1 if v < 0 else 1) for i, v in enumerate(norm_list) if abs(v) > 768]
                cpu_skip = []
                for channel in range(64):
                    gate_margin = sum(sign*(-1 if gate[channel*2048+feature] < 0 else 1) for feature, sign in outliers)
                    up_margin = sum(sign*(-1 if up[channel*2048+feature] < 0 else 1) for feature, sign in outliers)
                    cpu_skip.append(bool(outliers) and gate_margin <= 0 and up_margin == 0)
                assert cpu_skip == skip_list, 'Independent scalar predictor differs'
                expected = scalar_outputs(activation_list, gate, up, down, ids, skip_list, shifts)
                final_weights = functional.pad(reference.down[start:start+35].index_select(1, selected), (0, 0, 0, 13))
                check = _dot(down_input.index_select(1, selected), final_weights)  # [1,48].
                assert check[0, :35].cpu().tolist() == expected and any(expected)
                fixture = directory/f'layer{layer_index:02d}_{role}'
                fixture.mkdir()
                for name, items, bits in [('activation', activation_list, 8), ('norm', norm_list, 16),
                        ('gate', gate, 8), ('up', up, 8), ('down', down, 8),
                        ('skip', [int(v) for v in skip_list], 8), ('expected', expected, 32),
                        ('groups', groups, 16), ('configuration', [*shifts, start, 35], 32)]:
                    write_hex(fixture/(name+'.hex'), items, bits)
                entry = dict(role=role, global_token_position=position, fixture=str(fixture), policy=setting,
                    activation_exponent=int(exponent.item()), fields=fields, selected_groups=groups,
                    selected_channels=ids, original_output_start=start, expected_outputs=35,
                    nonzero_outputs=sum(value != 0 for value in expected), selected_skipped_channels=sum(skip_list),
                    full_skipped_channels=int(skip.sum()), outlier_features=len(outliers),
                    full_prefill_hook_value_bitwise_equal=True, full_integer_raw_bitwise_equal=True,
                    independent_predictor_equal=True, scalar_and_cuda_partial_outputs_identical=True,
                    negative_shift_controls={}, files_sha256={str(path): sha(path) for path in sorted(fixture.iterdir())})
                for key, shift_index in [('wrong_up_shift', 1), ('wrong_down_shift', 2)]:
                    changed = shifts.copy()
                    changed[shift_index] += 1
                    assert changed[shift_index] <= 63
                    wrong = scalar_outputs(activation_list, gate, up, down, ids, skip_list, changed)
                    entry['negative_shift_controls'][key] = dict(changed_shift=changed[shift_index],
                        different_output_sums=sum(left != right for left, right in zip(expected, wrong)))
                entries.append(entry)
                print('FORMAT350_FIXTURE', layer_index, role, position, fields, 'nonzero', entry['nonzero_outputs'], flush=True)
            record['layers'].append(dict(layer=layer_index, fixtures=entries))
            save()
            return actual
        return after

    save()
    handles = []
    for index, (replacement, layer) in enumerate(zip(replacements, layers)):
        replacement.prune = True
        replacement.begin_phase('hardware_fixture_prefill')
        handles.extend([layer.post_attention_layernorm.register_forward_pre_hook(replacement.before_norm),
                        layer.mlp.register_forward_hook(capture(replacement, index))])
    try:
        model(**batch, use_cache=False, logits_to_keep=1)
    finally:
        for handle in handles:
            handle.remove()
    assert len(record['layers']) == 22 and all(len(layer['fixtures']) == 2 for layer in record['layers'])
    controls = {}
    for role, key in [('first', 'wrong_up_shift'), ('ordinary', 'wrong_up_shift'), ('ordinary', 'wrong_down_shift')]:
        candidates = [(layer['layer'], fixture) for layer in record['layers'] for fixture in layer['fixtures']
                      if fixture['role'] == role and fixture['negative_shift_controls'][key]['different_output_sums'] > 0]
        assert candidates, 'No informative trained negative control for '+role+'/'+key
        layer, fixture = candidates[0]
        controls[role+'_'+key] = dict(layer=layer, **fixture['negative_shift_controls'][key])
    assert all(sha(path) == digest for path, digest in inputs.items())
    assert {p.name for p in model_path.iterdir() if p.is_file()} == set(loader['snapshot_file_names'])
    record.update(state='all44_protected_prefix_fixtures_prepared_scalar_cuda_equal',
        fixture_count=44, selected_negative_controls=controls, graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
        graphics_peak_reserved_bytes=torch.cuda.max_memory_reserved())
    save()
    print('FORMAT350_PREPARATION_COMPLETED', controls, flush=True)


if __name__ == '__main__':
    main()
