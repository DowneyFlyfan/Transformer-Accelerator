"""Trace rejected335 policies on one original fitting-image prefill,without answers.

Compare unchanged floating,accepted322,all335,and335-only-at-layer2 paths.
Log input-exponent coverage and local error against each original floating MLP
on its actual quantized-prefix input. No policy fitting,task scoring or hardware
claim. B=1 image,T=606 tokens,H=2048 hidden,V=32064 vocabulary;R=group rows.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('HF_HUB_OFFLINE','1')
os.environ.setdefault('TRANSFORMERS_OFFLINE','1')
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import torch
from PIL import Image
from transformers import AutoTokenizer,LlavaForConditionalGeneration,LlavaProcessor
from transformers.models.clip.image_processing_pil_clip import CLIPImageProcessorPil
from tri_oracle_integer_reference import _quantize
from evaluate_tri_oracle_format337_vqav2 import LayerReplacement


def sha(path):
    """Scalar file path -> streamed scalar digest,without tensor allocation."""
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


@torch.inference_mode()
def main():
    """Read pinned scalar metadata and original fit-image pixels[height,width,3].
    Processor creates IDs/mask[1,T],pixels[1,3,336,336]; original model returns
    logits[1,1,V]. CPU captured data contains22 activation matrices[256,H];
    row0 gives frozen first-token scale exponents,checked against actual float.
    Existing337 replacement objects hold unchanged trained integer references.
    All trace rows are scalar metadata; no model tensors/weights are saved.
    """
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    output=root/'records/format341_propagation_audit.json';assert not output.exists()
    score_path=root/'records/format339_official_scoring.json';scored=json.loads(score_path.read_text())
    assert scored['state']=='official_rowbalanced_pilot_scoring_completed_baselines_reproduced'
    assert scored['results']['integer_dense']['official_vqa_consensus_percent_on64']==0
    inputs=dict(scored['source_sha256'])
    for path in [Path(__file__),score_path]:inputs[str(path)]=sha(path)
    assert all(sha(path)==digest for path,digest in inputs.items())
    model_path=root/'.cache/model_reference/tiny_llava_v1'
    loader=json.loads((root/'records/format320_loader_metadata.json').read_text())
    assert {p.name for p in model_path.iterdir() if p.is_file()}==set(loader['snapshot_file_names'])
    cases=json.loads((root/'.cache/model_reference/ai2d285/inputs.json').read_text())['cases']
    case=cases[0]  # Only image/question fields are consumed;options/gold fields are not used.
    assert sha(case['image'])==case['image_sha256']
    captured=torch.load(root/'.cache/model_reference/format320/captured_rows.pt',map_location='cpu',weights_only=True)
    frozen_exponents=[int(_quantize(layer['activation'][0:1],per_row=True)[1].item()) for layer in captured]
    old=json.loads((root/'.cache/model_reference/format322/layer_policy.json').read_text())['layers']
    new=json.loads((root/'.cache/model_reference/format335/layer_policy.json').read_text())['layers']
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0]>10*1024**3
    torch.cuda.set_per_process_memory_fraction(.84);torch.cuda.reset_peak_memory_stats()
    tokenizer=AutoTokenizer.from_pretrained(model_path,local_files_only=True)
    image_processor=CLIPImageProcessorPil.from_pretrained(model_path,local_files_only=True)
    processor=LlavaProcessor(image_processor=image_processor,tokenizer=tokenizer,
        patch_size=14,vision_feature_select_strategy='default',num_additional_image_tokens=1)
    with Image.open(case['image']) as opened:
        batch=processor(images=opened.convert('RGB'),text='USER: <image>\n'+case['question']+'\nAnswer briefly.\nASSISTANT:',return_tensors='pt').to('cuda')
    assert batch['input_ids'].shape==(1,606) and batch['pixel_values'].shape==(1,3,336,336)
    model=LlavaForConditionalGeneration.from_pretrained(model_path,local_files_only=True,
        dtype=torch.float32,attn_implementation='sdpa',use_kernels=False).to('cuda').eval()
    layers=model.model.language_model.layers;assert len(layers)==22
    observed=[]  #22 scalar original floating first-token exponents.

    def observe_norm(module,args,value):
        """Original normalization output value[1,T,H];returnNone to preserve it.
        activation[T,H] is a view;quantization returns input-only exponents[T,1].
        """
        observed.append(int(_quantize(value.reshape(-1,2048),per_row=True)[1][0,0]))

    handles=[layer.post_attention_layernorm.register_forward_hook(observe_norm) for layer in layers]
    try:baseline=model(**batch,use_cache=False,logits_to_keep=1).logits[0,-1].float()  # [V].
    finally:
        for handle in handles:handle.remove()
    assert observed==frozen_exponents,'Original fitting input/model no longer reproduces frozen exponents'
    replacements=[LayerReplacement(index,layer) for index,layer in enumerate(layers)]
    started=time.monotonic()
    record=dict(state='tracing',source_sha256=inputs,started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        image_pixel_sha256=case['pixel_sha256'],prefill_tokens=606,frozen_float_first_exponents=frozen_exponents,
        original_float_exponents_reproduced=True,modes=[],labels_used=False,policies_fitted=False,
        task_accuracy_verified=False,hardware_verified=False,full_paper_results_matched=False,scope=__doc__)

    def save():
        record['elapsed_seconds']=time.monotonic()-started
        temporary=output.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(output)

    def diagnostic_hook(replacement,index,trace):
        """Capture existing replacement,index scalar,and caller trace metadata list.
        Hook args[0]/original[1,T,H] are actual activation/float MLP output.
        actual[1,T,H] is existing replacement output;row errors[T] are logging only.
        Exponents[T] identify selected bucket/fallback without changing arithmetic.
        """
        def after(module,args,original):
            activation=args[0].reshape(-1,2048)  # [T,H],actual quantized-prefix normalized input.
            exponents=_quantize(activation,per_row=True)[1][:,0]  # [T],input-derived integer scales.
            actual=replacement.after_mlp(module,args,original)  # [1,T,H],unchanged337 arithmetic.
            relative=(actual.reshape(-1,2048)-original.reshape(-1,2048)).norm(dim=-1)/original.reshape(-1,2048).norm(dim=-1).clamp_min(1e-20)
            known={item['activation_exponent']:item for item in replacement.policy['buckets']}
            first=int(exponents[0]);selected=known.get(first,replacement.policy['fallback'])
            unique,counts=exponents.unique(return_counts=True)
            trace.append(dict(layer=index,first_exponent=first,frozen_float_first_exponent=frozen_exponents[index],
                exponent_histogram={str(int(e)):int(n) for e,n in zip(unique,counts)},
                supported_exponents=sorted(known),first_used_fallback=first not in known,
                first_policy={key:selected[key] for key in ['maximum_up_gain_bits','down_shift_offset']},
                fallback_rows=sum(int(n) for e,n in zip(unique,counts) if int(e) not in known),
                first_local_relative_error=float(relative[0]),mean_local_relative_error=float(relative.mean()),
                first_float_output_norm=float(original.reshape(-1,2048)[0].norm()),
                first_integer_output_norm=float(actual.reshape(-1,2048)[0].norm())))
            return actual
        return after

    save()
    for mode in ['extended322','rowbalanced335_all','rowbalanced335_layer2_only']:
        trace=[];handles=[]
        for index,(replacement,layer) in enumerate(zip(replacements,layers)):
            replacement.policy=new[index] if mode=='rowbalanced335_all' or (mode=='rowbalanced335_layer2_only' and index==2) else dict(fallback=old[index],buckets=[])
            replacement.prune=False;replacement.phase='diagnostic_prefill';replacement.trace.clear()
            handles.extend([layer.post_attention_layernorm.register_forward_pre_hook(replacement.before_norm),
                            layer.mlp.register_forward_hook(diagnostic_hook(replacement,index,trace))])
        try:logits=model(**batch,use_cache=False,logits_to_keep=1).logits[0,-1].float()  # [V].
        finally:
            for handle in handles:handle.remove()
        assert len(trace)==22 and all(len(item.trace)==1 for item in replacements)
        record['modes'].append(dict(mode=mode,first_logit_relative_error=float((logits-baseline).norm()/baseline.norm()),
            argmax_matches=bool(logits.argmax()==baseline.argmax()),trace=trace))
        save();print('FORMAT341_MODE',mode,record['modes'][-1]['first_logit_relative_error'],flush=True)
    assert all(sha(path)==digest for path,digest in inputs.items())
    assert {p.name for p in model_path.iterdir() if p.is_file()}==set(loader['snapshot_file_names'])
    record.update(state='one_fit_image_propagation_diagnostics_completed',graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated())
    save();print('FORMAT341_COMPLETED',flush=True)


if __name__=='__main__':main()
