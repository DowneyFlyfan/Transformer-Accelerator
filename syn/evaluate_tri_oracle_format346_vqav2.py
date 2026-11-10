"""Evaluate first-token-protected formats on the unchanged64-question pilot.

B=1 image/question; Tq=question-dependent prefill; H=2048 hidden; K=5632
intermediate channels; V=32064 vocabulary; A=1..16 generated answer tokens.
Attention, vision, normalization, residuals and vocabulary head remain floating.
Reproduce prior floating and extended dense/predicted answers before new results.
Global token0 keeps322 formats; ordinary rows use335. Decode offsets never restart
at zero. The known pilot is reused; no fresh benchmark or paper-matching claim.
"""
from pathlib import Path
import datetime
import hashlib
import json
import os
import sys
import time
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
sys.dont_write_bytecode = True
sys.path.insert(0, 'syn')
import torch
from PIL import Image
from transformers import AutoTokenizer, LlavaForConditionalGeneration, LlavaProcessor
from transformers.models.clip.image_processing_pil_clip import CLIPImageProcessorPil
from tri_oracle_integer_reference import IntegerFeedForwardReference
from tri_oracle_format345_first_token import evaluate_protected


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class LayerReplacement:
    def __init__(self, index, layer):
        """index: scalar layer number; layer: original trained decoder module.
        Trained gate/up[K,H], down[H,K] initialize the existing reference;
        saved residual[T,H] is captured from the original normalization input.
        All reference initialization and arithmetic are unchanged.
        """
        self.index = index
        calibration = json.loads(Path('.cache/model_reference/format335/layer_policy.json').read_text())
        assert calibration['state']=='row_balanced_exponent_bucket_policy' and len(calibration['layers'])==22
        self.policy = calibration['layers'][index]
        self.first_policy = json.loads(Path('.cache/model_reference/format322/layer_policy.json').read_text())['layers'][index]
        self.token_offset = 0  # Scalar global sequence offset,reset independently for each phase.
        self.reference = IntegerFeedForwardReference(
            layer.mlp.gate_proj.weight, layer.mlp.up_proj.weight,
            layer.mlp.down_proj.weight, layer.post_attention_layernorm.variance_epsilon)
        self.residual = None  # [T,H], set by the pre-normalization hook.
        self.trace = []
        self.phase = None
        self.prune = False

    def begin_phase(self, phase):
        """Caller phase is scalar metadata;reset global token offset before each new sequence."""
        self.phase = phase
        self.token_offset = 0

    def before_norm(self, module, args):
        """args[0]: actual pre-learned-scale residual[B,T,H] from decoder.
        Reshape to[T,H] for the unchanged reference; module is the original norm.
        """
        self.residual = args[0].reshape(-1, 2048)

    def after_mlp(self, module, args, output):
        """args[0]: actual normalized activation[B,T,H]; output: float[B,T,H].
        raw[T,H] integer sums and values[T,H] dequantized output come from
        the unchanged reference. Global token0 uses the retained322 pair;
        other rows are grouped by input-derived scale exponent and restored
        to original row order. stats contains row-wise[T] counts/shifts and
        norm_codes[T,H]. Return[B,T,H] in the original model output dtype.
        """
        assert args[0].ndim == 3 and args[0].shape[0] == 1, 'One sequence per hook is required'
        activation = args[0].reshape(-1, 2048)
        assert self.residual is not None and self.residual.shape == activation.shape
        start = self.token_offset  # Scalar global position of first caller row.
        raw, values, stats = evaluate_protected(self.reference,
            activation, self.residual, self.policy, self.first_policy, start, prune=self.prune)
        self.token_offset += activation.shape[0]
        assert raw.shape == values.shape == activation.shape
        assert bool(torch.isfinite(values).all())
        self.trace.append({
            'phase': self.phase, 'input_shape': list(args[0].shape),
            'global_token_offset': start, 'protected_rows': int(start == 0),
            'predicted_skip_channels': int(stats['skip_count'].sum()),
            'total_channels': activation.shape[0] * 5632,
            'up_endpoint_codes': int(stats['up_endpoint_codes'].sum()),
            'gated_endpoint_codes': int(stats['gated_endpoint_codes'].sum()),
            'gain_min': int(stats['up_gain_bits'].min()),
            'gain_max': int(stats['up_gain_bits'].max()),
            'down_shift_min': int(stats['down_shift'].min()),
            'down_shift_max': int(stats['down_shift'].max())})
        self.residual = None
        return values.reshape_as(output).to(output.dtype)


@torch.inference_mode()
def main():
    """Run float/two extended controls/protected dense/protected predicted on64 fixed pairs.
    New audit/fitted/previous/loader/policies variables are frozen JSON metadata;
    previous maps mode/question scalar keys to original answer token-ID lists.

    Cached CPU inputs: IDs/mask[1,Tq], pixels[1,3,336,336], from pinned configs.
    baseline_logits stores64 original CUDA[V] vectors; other CUDA tensors are
    per-question. No training, loss, optimizer or hardware timing is involved.
    """
    started = time.monotonic()
    output = Path('records/format346_vqav2_inference.json')
    assert not output.exists()
    manifest_path = Path('.cache/model_reference/vqav2_pilot/manifest.json')
    admitted = json.loads(Path('records/vqav2_pilot_data_qualification.json').read_text())
    assert admitted['dataset_preparation_passed'] and sha(manifest_path) == admitted['manifest_sha256']
    manifest = json.loads(manifest_path.read_text())
    audit_path=Path('records/format320_multi_image_range_audit.json')
    fitted_path=Path('records/format335_rowbalanced_calibration.json')
    fitted_guard_path=Path('records/format336_gpu_guard_result.json')
    policy_path=Path('.cache/model_reference/format335/layer_policy.json')
    prior_path=Path('records/format324_vqav2_inference.json')
    prior_qualified_path=Path('records/format325_gpu_guard_result.json')
    audit=json.loads(audit_path.read_text());fitted=json.loads(fitted_path.read_text())
    fitted_guard=json.loads(fitted_guard_path.read_text());prior=json.loads(prior_path.read_text())
    prior_qualified=json.loads(prior_qualified_path.read_text())
    assert fitted_guard['state']=='completed' and fitted_guard['native_exit_status']==0
    assert sha(fitted_path)==fitted_guard['summary_sha256']
    assert fitted['state']=='row_balanced_input_exponent_policies_fitted'
    assert sha(policy_path)==fitted['generated_sha256'][str(policy_path.resolve())]
    assert prior['state']=='completed' and prior_qualified['state']=='completed' and prior_qualified['native_exit_status']==0 and prior_qualified['input_drift']==[]
    assert sha(prior_path)==prior_qualified['summary_sha256']=='357565db2a2a594cf90041b5026a8e584928b3467d030766f2368539f419999b'
    assert len(audit['inputs'])==16 and audit['image_pixels_disjoint_from_evaluation'] is True
    old_policies=json.loads(Path('.cache/model_reference/format322/layer_policy.json').read_text())['layers']
    new_policies=json.loads(policy_path.read_text())['layers']
    assert len(old_policies)==len(new_policies)==22
    previous={(case['mode'],case['question_id']):case['answer_tokens'] for case in prior['cases']}
    assert len(previous)==256
    rejection_path=Path('records/format340_candidate_rejection.json')
    protection_path=Path('records/format343_propagation_audit.json')
    protection_guard_path=Path('records/format344_gpu_guard_result.json')
    assert sha(rejection_path)=='c86f7cd79aa3421e06107ec8683b786a9bc8f92511b6630fa4eb822241371260'
    protection=json.loads(protection_path.read_text());protection_guard=json.loads(protection_guard_path.read_text())
    assert protection_guard['state']=='completed' and protection_guard['native_exit_status']==0 and protection_guard['input_drift']==[]
    assert sha(protection_path)==protection_guard['summary_sha256']
    assert protection['all22_first_token_prefixes_bitwise_preserved'] is True
    model_directory=Path('.cache/model_reference/tiny_llava_v1')
    loader=json.loads(Path('records/format320_loader_metadata.json').read_text())
    assert {p.name for p in model_directory.iterdir() if p.is_file()}==set(loader['snapshot_file_names'])
    samples = manifest['samples']
    assert len(samples) == 64 and len({sample['image_id'] for sample in samples}) == 64
    candidate = json.loads(Path('records/model_reference_candidate.json').read_text())
    paths = [str(manifest_path), 'records/integer_format_decomposition_01.json',
             'syn/tri_oracle_integer_reference.py', 'syn/tri_oracle_model_reference.py',
             'syn/tri_oracle_format335_policy.py', 'syn/tri_oracle_format345_first_token.py',
             'syn/test_tri_oracle_format345_first_token.py', __file__]
    inputs = {**audit['source_sha256'],**fitted['source_sha256'],**{
        str(path):sha(path) for path in [*paths,audit_path,fitted_path,fitted_guard_path,
                                      policy_path,prior_path,prior_qualified_path,
                                      rejection_path,protection_path,protection_guard_path]}}
    assert all(sha(path)==digest for path,digest in inputs.items())
    for item in [*candidate['verified_weights'], *manifest['images'].values()]:
        assert sha(item['path']) == item['sha256']
        inputs[item['path']] = item['sha256']
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0] > 10 * 1024**3
    torch.cuda.set_per_process_memory_fraction(.84)
    torch.cuda.reset_peak_memory_stats()
    root = '.cache/model_reference/tiny_llava_v1'
    tokenizer = AutoTokenizer.from_pretrained(root, local_files_only=True)
    image_processor = CLIPImageProcessorPil.from_pretrained(root, local_files_only=True)
    processor = LlavaProcessor(image_processor=image_processor, tokenizer=tokenizer,
        patch_size=14, vision_feature_select_strategy='default', num_additional_image_tokens=1)
    cached = []  #64 CPU batches: IDs/mask[1,Tq], pixels[1,3,336,336].
    for sample in samples:
        with Image.open(sample['image']) as opened:
            image = opened.convert('RGB')
            prompt = 'USER: <image>\n' + sample['question'] + '\nAnswer the question using a single word or phrase.\nASSISTANT:'
            batch = processor(images=image, text=prompt, return_tensors='pt')
        assert batch['input_ids'].shape[0] == 1 and batch['pixel_values'].shape == (1, 3, 336, 336)
        assert 577 <= batch['input_ids'].shape[1] <= 2048
        cached.append(batch)
    # Original trained parameter matrices retain their checkpoint shapes.
    model = LlavaForConditionalGeneration.from_pretrained(root, local_files_only=True,
        dtype=torch.float32, attn_implementation='sdpa', use_kernels=False).to('cuda').eval()
    layers = model.model.language_model.layers
    assert len(layers) == 22
    replacements, handles, baseline_logits, baseline_ids = [], [], [], []
    record = {'state': 'running', 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_sha256': inputs, 'checkpoint_revision': candidate['revision'],
        'sample_count': 64, 'maximum_answer_tokens': 16, 'cases': [],
        'prompt_matches_paper_verified': False,
        'calibration': 'Frozen335 ordinary-row policy plus322 global token0 format; reset global offsets before teacher/generation and advance during decode.',
        'first_token_control_is_local_reconstruction_choice': True,
        'whole_model_integer': False, 'official_scoring_executed': False,
        'paper_accuracy_verified': False, 'scope': __doc__}

    def status():
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2) + '\n')
        temporary.replace(output)

    try:
        for mode in ['floating','extended_integer_dense','extended_integer_predicted','integer_dense','integer_predicted']:
            if mode == 'extended_integer_dense':
                for index, layer in enumerate(layers):
                    replacement = LayerReplacement(index, layer)
                    replacements.append(replacement)
                    handles.extend([layer.post_attention_layernorm.register_forward_pre_hook(replacement.before_norm),
                                    layer.mlp.register_forward_hook(replacement.after_mlp)])
            for replacement in replacements:
                replacement.prune = mode in ('extended_integer_predicted','integer_predicted')
                replacement.policy=(dict(fallback=old_policies[replacement.index],buckets=[])
                                    if mode in ('extended_integer_dense','extended_integer_predicted')
                                    else new_policies[replacement.index])
            for index, sample in enumerate(samples):
                batch = {name: value.to('cuda') for name, value in cached[index].items()}  #[1,Tq] / [1,3,336,336].
                prefill = batch['input_ids'].shape[1]  # Actual Tq.
                for replacement in replacements:
                    replacement.trace.clear()
                    replacement.begin_phase('teacher_forced_prefill')
                logits = model(**batch, use_cache=False, logits_to_keep=1).logits[0, -1].float()  #[V].
                assert logits.shape == (32064,) and bool(torch.isfinite(logits).all())
                if mode == 'floating':
                    baseline_logits.append(logits.detach().clone())  #64*[V], original model.
                baseline = baseline_logits[index]  #[V], same question/image.
                relative_error = float((logits - baseline).norm() / baseline.norm())  # Scalar relative L2.
                for replacement in replacements:
                    replacement.begin_phase('generation')
                generated = model.generate(**batch, max_new_tokens=16, do_sample=False, use_cache=True)  #[1,Tq+A].
                answer_ids = generated[0, prefill:].tolist()  # List[A], includes generated end token.
                assert 1 <= len(answer_ids) <= 16
                answer = processor.batch_decode(generated[:, prefill:], skip_special_tokens=True)[0]
                if mode=='floating':
                    assert answer_ids==previous[('floating',sample['question_id'])],'Original floating answers changed'
                if mode in ('extended_integer_dense','extended_integer_predicted'):
                    old_mode='integer_dense' if mode=='extended_integer_dense' else 'integer_predicted'
                    assert answer_ids==previous[(old_mode,sample['question_id'])],'Extended baseline answers changed'
                if mode == 'floating':
                    baseline_ids.append(answer_ids)
                for replacement in replacements:
                    assert len(replacement.trace) == len(answer_ids) + 1
                    assert [item['input_shape'] for item in replacement.trace[:2]] == [[1, prefill, 2048]] * 2
                    assert all(item['input_shape'] == [1, 1, 2048] for item in replacement.trace[2:])
                    assert [item['global_token_offset'] for item in replacement.trace] == [0,0] + list(range(prefill,prefill+len(answer_ids)-1))
                    assert [item['protected_rows'] for item in replacement.trace] == [1,1] + [0]*(len(answer_ids)-1)
                trace = [item for replacement in replacements for item in replacement.trace if item['phase'] == 'generation']
                case = {'mode': mode, 'question_id': sample['question_id'], 'image_id': sample['image_id'],
                    'prefill_tokens': prefill, 'answer_tokens': answer_ids, 'answer': answer,
                    'first_logit_relative_l2': relative_error,
                    'first_argmax_matches': bool(logits.argmax() == baseline.argmax()),
                    'token_matches_over_overlap': sum(left == right for left, right in zip(answer_ids, baseline_ids[index])),
                    'overlap_positions': min(len(answer_ids), len(baseline_ids[index])),
                    'integer_layers': len(replacements), 'per_layer_calls': [len(item.trace) for item in replacements],
                    'per_layer_token_offsets': [[entry['global_token_offset'] for entry in item.trace] for item in replacements],
                    'per_layer_protected_rows': [[entry['protected_rows'] for entry in item.trace] for item in replacements],
                    'predicted_zero_channels': sum(item['predicted_skip_channels'] for item in trace),
                    'total_generation_channels': sum(item['total_channels'] for item in trace)}
                record['cases'].append(case)
                record['current_mode'] = mode
                status()
                print('FORMAT346_VQAV2_PILOT', mode, index + 1, 'qid', sample['question_id'], 'error', relative_error, 'answer', repr(answer), flush=True)
        assert len(record['cases']) == 320
        assert {p.name for p in model_directory.iterdir() if p.is_file()}==set(loader['snapshot_file_names'])
        assert all(sha(path) == fingerprint for path, fingerprint in inputs.items())
        decode_calls = {mode: sum(sum(max(0, count - 2) for count in case['per_layer_calls'])
                                  for case in record['cases'] if case['mode'] == mode)
                        for mode in ['extended_integer_dense','extended_integer_predicted','integer_dense','integer_predicted']}
        record.update(state='completed',
            incremental_decode_offsets_verified=all(decode_calls[mode] > 0 for mode in ['integer_dense','integer_predicted']),
            generation_decode_calls_by_mode=decode_calls, elapsed_seconds=time.monotonic() - started,
            graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
            graphics_peak_reserved_bytes=torch.cuda.max_memory_reserved())
        status()
    finally:
        for handle in handles:
            handle.remove()
    print('FORMAT346_VQAV2_EXECUTION_FINISHED', flush=True)


if __name__ == '__main__':
    main()
