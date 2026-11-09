"""Exercise the existing integer feed-forward method in all22 language layers.

Inference diagnostic only: attention, vision, normalization and residual sums
remain floating. The software still evaluates dense matrices when pruning.
No task-accuracy, chip performance or energy claim follows from this sample.
B=1 image/question; T=600 prefill tokens or1 decode token; H=2048 hidden
features; K=5632 intermediate channels; V=32064 vocabulary entries.
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
import torch
from PIL import Image
from transformers import AutoTokenizer, LlavaForConditionalGeneration, LlavaProcessor
from transformers.models.clip.image_processing_pil_clip import CLIPImageProcessorPil
from tri_oracle_integer_reference import IntegerFeedForwardReference


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
        self.reference = IntegerFeedForwardReference(
            layer.mlp.gate_proj.weight, layer.mlp.up_proj.weight,
            layer.mlp.down_proj.weight, layer.post_attention_layernorm.variance_epsilon)
        self.residual = None  # [T,H], set by the pre-normalization hook.
        self.trace = []
        self.phase = None
        self.prune = False

    def before_norm(self, module, args):
        """args[0]: actual pre-learned-scale residual[B,T,H] from decoder.
        Reshape to[T,H] for the unchanged reference; module is the original norm.
        """
        self.residual = args[0].reshape(-1, 2048)

    def after_mlp(self, module, args, output):
        """args[0]: actual normalized activation[B,T,H]; output: float[B,T,H].
        raw[T,H] integer sums and values[T,H] dequantized output come from
        the existing reference. stats contains row-wise[T] counts/shifts and
        norm_codes[T,H]. Return[B,T,H] in the original model output dtype.
        """
        activation = args[0].reshape(-1, 2048)
        assert self.residual is not None and self.residual.shape == activation.shape
        raw, values, stats = self.reference.evaluate(
            activation, self.residual, prune=self.prune,
            maximum_up_gain_bits=7, down_shift_offset=-1,
            gate_threshold=0, up_window=0)
        assert raw.shape == values.shape == activation.shape
        assert bool(torch.isfinite(values).all())
        self.trace.append({
            'phase': self.phase, 'input_shape': list(args[0].shape),
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
    """Load one pinned model/image and exercise baseline,dense,predicted cases.
    Inputs: token IDs/mask[B,600], image pixels[B,3,336,336] from the pinned
    processor config and tokenizer. first logits[B,1,V] are teacher-forced;
    generated[B,660] contains600 input and60 forced-length output token IDs.
    No training loss or optimizer is used.
    """
    started = time.monotonic()
    result_path = Path('records/all_layer_integer_model_validation.json')
    assert not result_path.exists(), 'Refusing to replace an existing experiment'
    candidate = json.loads(Path('records/model_reference_candidate.json').read_text())
    files = ['syn/tri_oracle_all_layer_integer_model_validation.py',
             'syn/tri_oracle_integer_reference.py', 'syn/tri_oracle_model_reference.py',
             '.cache/model_reference/ai2d-demo.jpg',
             '.cache/model_reference/tiny_llava_v1/config.json',
             '.cache/model_reference/tiny_llava_v1/tokenizer.json',
             '.cache/model_reference/tiny_llava_v1/preprocessor_config.json']
    inputs_sha = {p: sha(p) for p in files}
    for item in candidate['verified_weights']:
        assert sha(item['path']) == item['sha256'], item['path']
        inputs_sha[item['path']] = item['sha256']
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    torch.cuda.reset_peak_memory_stats()
    free, total = torch.cuda.mem_get_info()
    assert free >= 10 * 1024**3, 'Insufficient graphics memory reserve'
    root = '.cache/model_reference/tiny_llava_v1'
    tokenizer = AutoTokenizer.from_pretrained(root, local_files_only=True)
    image_processor = CLIPImageProcessorPil.from_pretrained(root, local_files_only=True)
    processor = LlavaProcessor(
        image_processor=image_processor, tokenizer=tokenizer, patch_size=14,
        vision_feature_select_strategy='default', num_additional_image_tokens=1)
    image = Image.open('.cache/model_reference/ai2d-demo.jpg').convert('RGB')
    prompt = 'USER: <image>\nWhat does the label 15 represent? Answer briefly.\nASSISTANT:'
    inputs = processor(images=image, text=prompt, return_tensors='pt').to('cuda')
    assert list(inputs['input_ids'].shape) == [1, 600]
    assert list(inputs['pixel_values'].shape) == [1, 3, 336, 336]
    assert int((inputs['input_ids'] == 32000).sum()) == 576
    model = LlavaForConditionalGeneration.from_pretrained(
        root, local_files_only=True, dtype=torch.float32,
        attn_implementation='sdpa', use_kernels=False).to('cuda').eval()
    layers = model.model.language_model.layers
    assert len(layers) == 22 and all(p.is_cuda for p in model.parameters())
    settings = {'do_sample': False, 'min_new_tokens': 60, 'max_new_tokens': 60,
                'use_cache': True}
    first = model(**inputs, use_cache=False, logits_to_keep=1).logits.float()
    baseline_logits = first[0, -1].clone()  # [V], same fixed prompt.
    generated = model.generate(**inputs, **settings)
    baseline_tokens = generated[0, 600:].tolist()  # [60] output token IDs.
    assert len(baseline_tokens) == 60
    result = {
        'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'state': 'running', 'checkpoint_revision': candidate['revision'],
        'input_sha256': inputs_sha, 'prompt': prompt, 'prefill_tokens': 600,
        'decode_tokens': 60, 'model_dtype': 'float32', 'generation_settings': settings,
        'baseline_tokens': baseline_tokens,
        'baseline_answer': tokenizer.decode(baseline_tokens, skip_special_tokens=True),
        'cases': [], 'scope': __doc__}
    result_path.write_text(json.dumps(result, indent=2) + '\n')
    print('FULL_MODEL_BASELINE_PASS prefill=600 decode=60', flush=True)
    replacements = [LayerReplacement(i, layer) for i, layer in enumerate(layers)]
    for prune in (False, True):
        handles = []
        case = {'prune': prune, 'state': 'running'}
        try:
            for replacement, layer in zip(replacements, layers):
                replacement.trace = []
                replacement.prune = prune
                replacement.phase = 'teacher_forced_prefill'
                handles.extend([
                    layer.post_attention_layernorm.register_forward_pre_hook(replacement.before_norm),
                    layer.mlp.register_forward_hook(replacement.after_mlp)])
            first = model(**inputs, use_cache=False, logits_to_keep=1).logits.float()
            test_logits = first[0, -1]  # [V], same input as baseline.
            relative = (test_logits - baseline_logits).norm() / baseline_logits.norm()
            case['first_answer_logit_relative_l2'] = float(relative)
            case['first_answer_argmax_matches'] = bool(test_logits.argmax() == baseline_logits.argmax())
            for replacement in replacements:
                replacement.phase = 'generation'
            generated = model.generate(**inputs, **settings)
            tokens = generated[0, 600:].tolist()  # [60] output token IDs.
            assert len(tokens) == 60
            for replacement in replacements:
                trace = replacement.trace
                assert len(trace) == 61 and trace[0]['input_shape'] == [1, 600, 2048]
                assert trace[1]['input_shape'] == [1, 600, 2048]
                assert all(t['input_shape'] == [1, 1, 2048] for t in trace[2:])
            case.update(state='completed', generated_tokens=tokens,
                        answer=tokenizer.decode(tokens, skip_special_tokens=True),
                        matching_token_positions=sum(a == b for a, b in zip(tokens, baseline_tokens)),
                        layers_exercised=len(replacements))
        except Exception as error:
            case.update(state='failed', exception=repr(error))
        finally:
            for handle in handles:
                handle.remove()
        case['per_layer_traces'] = {str(r.index): r.trace for r in replacements}
        result['cases'].append(case)
        result_path.write_text(json.dumps(result, indent=2) + '\n')
        print('ALL_LAYER_INTEGER_CASE', prune, case['state'], case.get('exception', ''), flush=True)
    assert all(sha(p) == h for p, h in inputs_sha.items()), 'Experiment input drift'
    result.update(
        state='completed' if all(c['state'] == 'completed' for c in result['cases']) else 'failed',
        elapsed_seconds=time.monotonic()-started,
        graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
        graphics_peak_reserved_bytes=torch.cuda.max_memory_reserved(),
        whole_model_integer=False, dataset_accuracy_verified=False,
        hardware_cycle_or_energy_verified=False, paper_results_matched=False)
    result_path.write_text(json.dumps(result, indent=2) + '\n')
    return 0 if result['state'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
