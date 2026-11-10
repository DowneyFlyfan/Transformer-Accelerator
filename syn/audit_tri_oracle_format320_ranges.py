"""Multi-image calibration and range isolation for the unchanged integer path.

The trained vision-language model remains floating and unmodified. Capture
sixteen token rows from each of sixteen label-independent diagram inputs.
Fit fixed layer formats on eight images; measure on eight other images.
The separate64-question evaluation images are excluded by decoded pixel hash.
No task score, integer whole-model result or chip performance is established.

Shape symbols: B=1 image/question; T=actual prefill length; S=16 selected rows
per image; M=128 calibration/held rows or256 combined rows; H=2048 hidden
features; K=5632 intermediate channels; V=32064 vocabulary entries.
Q8 means fixed point with eight fractional bits. No loss or optimizer is used.
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
import torch.nn.functional as functional
from PIL import Image
from transformers import AutoTokenizer,LlavaForConditionalGeneration,LlavaProcessor
from transformers.models.clip.image_processing_pil_clip import CLIPImageProcessorPil
from tri_oracle_integer_reference import IntegerFeedForwardReference,_quantize,_dot


def sha(path):
    """path: caller file name, scalar string/Path; stream/hash: file and scalar digest."""
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def pixel_identity(path):
    """path: image file from manifest. image: decoded RGB[height,width,3].
    width/height: image-derived scalars; result: scalar dimensions+pixel digest.
    """
    with Image.open(path) as opened:
        image=opened.convert('RGB')
        width,height=image.size
        return hashlib.sha256(width.to_bytes(4,'big')+height.to_bytes(4,'big')+image.tobytes()).hexdigest()


class Capture:
    def __init__(self,index):
        """index: caller scalar decoder layer. selected[S]: caller-initialized
        CUDA token indices. pending[S,H]: pre-normalization residual, then CPU.
        activations/residuals/targets: lists of original CPU float32[S,H] rows.
        """
        self.index=index
        self.selected=None
        self.pending=None
        self.activations=[]
        self.residuals=[]
        self.targets=[]

    def before_norm(self,module,args):
        """module: original trained normalization; args[0] is its residual[B,T,H].
        rows[T,H] is a view, pending[S,H] an indexed CPU copy; returns None so the
        original normalization is unchanged. selected[S] comes from main.
        """
        rows=args[0].reshape(-1,2048)
        assert rows.shape[0]>=16 and self.pending is None
        self.pending=rows.index_select(0,self.selected).detach().cpu()

    def after_mlp(self,module,args,output):
        """module: original trained feed-forward block. args[0]/output[B,T,H]
        supply normalized input and original float result. activation/target[S,H]
        are selected CPU copies; pending[S,H] is the matching residual. Lists
        append one[S,H] tensor per image; no replacement output is returned.
        """
        activation=args[0].reshape(-1,2048).index_select(0,self.selected).detach().cpu()
        target=output.reshape(-1,2048).index_select(0,self.selected).detach().cpu()
        assert self.pending is not None and activation.shape==target.shape==self.pending.shape==(16,2048)
        self.activations.append(activation)
        self.residuals.append(self.pending)
        self.targets.append(target)
        self.pending=None


def relative_error(values,target):
    """values/target[M,H]: caller results/original captured outputs. delta[M,H]
    and scalar norms are derived here. Return scalar relative Euclidean error.
    """
    delta=values-target
    return float(delta.norm()/target.norm().clamp_min(1e-20))


def rounding_overflows(raw,shift):
    """raw[M,K]: existing exact signed32 dots/products; shift[M,1]: configured
    nonnegative right shifts. magnitude/rounded[M,K] are unclamped unsigned64
    magnitudes; half[M,1] gives ties-away rounding. Scalar result counts values
    outside signed16 including the asymmetric negative endpoint.
    """
    magnitude=raw.to(torch.int64).abs()
    half=torch.where(shift>0,torch.bitwise_left_shift(torch.ones_like(shift,dtype=torch.int64),(shift-1).clamp_min(0)),0)
    rounded=torch.bitwise_right_shift(magnitude+half,shift)
    return int(((raw>=0)&(rounded>32767) | (raw<0)&(rounded>32768)).sum())


@torch.inference_mode()
def range_isolation(layer,reference,activation,residual,target,policy):
    """layer: pinned original decoder; reference: unchanged integer object.
    activation/residual/target[M,H]: captured normalized/pre-norm/original output
    rows. policy: two scalar fixed-format fields. gate/up/product[M,K] and
    rebuilt[M,H] re-evaluate original float arithmetic. codes[M,H],exponent[M,1]
    come from unchanged quantization; gate_dot/up_dot[M,K] are exact signed32.
    raw/values[M,H], stats norm_codes[M,H]/counters[M] come from evaluate.
    gain/gate_shift/up_shift[M,1] are stats views. gate_limited[M,K] and
    gate_only[M,H] isolate only the signed16 Q8 gate range. product_limit[M,1]
    and product_limited[M,K] isolate the configured gated-value range, then
    product_only[M,H] uses the original down weights. No result replaces a
    model output; all returned quantities are scalar diagnostics.
    """
    gate=functional.linear(activation,layer.mlp.gate_proj.weight)
    up=functional.linear(activation,layer.mlp.up_proj.weight)
    product=functional.silu(gate)*up
    rebuilt=functional.linear(product,layer.mlp.down_proj.weight)
    assert relative_error(rebuilt,target)<.0001,'Captured original forward differs from its source formula'
    raw,values,stats=reference.evaluate(activation,residual,prune=False,**policy)
    codes,exponent=_quantize(activation,per_row=True)
    gate_dot=_dot(codes,reference.gate)
    up_dot=_dot(codes,reference.up)
    gate_shift=stats['gate_shift'][:,None]
    up_shift=stats['up_shift'][:,None]
    gain=stats['up_gain_bits'][:,None]
    gate_limited=gate.clamp(-128,32767/256)
    gate_only=functional.linear(functional.silu(gate_limited)*up,layer.mlp.down_proj.weight)
    product_limit=torch.ldexp(torch.ones_like(gain,dtype=torch.float32),-gain)/256
    product_limited=product.clamp(min=-32768*product_limit,max=32767*product_limit)
    product_only=functional.linear(product_limited,layer.mlp.down_proj.weight)
    return dict(rows=activation.shape[0],intermediate_values=gate.numel(),
        float_rebuild_relative_error=relative_error(rebuilt,target),
        dense_integer_relative_error=relative_error(values,target),
        gate_true_abs_max=float(gate.abs().max()),up_true_abs_max=float(up.abs().max()),
        gated_true_abs_max=float(product.abs().max()),
        true_gate_outside_signed16_q8=int(((gate< -128)|(gate>32767/256)).sum()),
        exact_integer_gate_rounding_overflows=rounding_overflows(gate_dot,gate_shift),
        exact_integer_up_rounding_overflows=rounding_overflows(up_dot,up_shift),
        gated_endpoint_codes=int(stats['gated_endpoint_codes'].sum()),
        only_gate_range_limited_relative_error=relative_error(gate_only,target),
        only_gated_range_limited_relative_error=relative_error(product_only,target))


@torch.inference_mode()
def main():
    """Paths/manifests/policy/candidates/records are input-derived Python metadata;
    indexes and loop counters are scalar. image is RGB[h,w,3]. batch IDs/mask[B,T]
    and pixels[B,3,336,336] are processor-initialized CUDA tensors. selected[S]
    is a uniform token-index vector. logits[B,1,V] are original model output.
    captures hold22*16 CPU triples[S,H]. all_a/all_r/all_y[M,H], M=256, concatenate
    each layer; a/r/y[128,H] and held_a/r/y[128,H] are disjoint image slices.
    raw/values[128,H], stats as evaluate; loss is scalar relative squared error.
    model/layers are pinned trained original modules; reference initializes from
    their gate/up[K,H],down[H,K] float weights. No trainable state is changed.
    """
    root=Path(__file__).resolve().parents[1]
    os.chdir(root)
    out=root/'.cache/model_reference/format320'
    result=root/'records/format320_multi_image_range_audit.json'
    assert not result.exists() and not out.exists()
    manifest_path=root/'.cache/model_reference/ai2d285/inputs.json'
    evaluation_path=root/'.cache/model_reference/vqav2_pilot/manifest.json'
    manifest=json.loads(manifest_path.read_text())
    evaluation=json.loads(evaluation_path.read_text())
    candidate=json.loads((root/'records/model_reference_candidate.json').read_text())
    old_policy=json.loads((root/'.cache/model_reference/calibration283_layer_policy.json').read_text())
    # Receipts are frozen anchors, not hashes newly assigned to current payloads.
    prepared_path=root/'records/ai2d285_inputs_result.json'
    reconstructed_path=root/'records/calibration283_policy_reconstruction.json'
    evaluation_qualified_path=root/'records/vqav2_pilot_data_qualification.json'
    loader_path=root/'records/format320_loader_metadata.json'
    prepared=json.loads(prepared_path.read_text())
    reconstructed=json.loads(reconstructed_path.read_text())
    evaluation_qualified=json.loads(evaluation_qualified_path.read_text())
    loader=json.loads(loader_path.read_text())
    assert prepared['state']=='independent_input_diagnostic_manifest_prepared'
    assert sha(manifest_path)==prepared['generated_sha256'][str(manifest_path)]
    policy_path=root/'.cache/model_reference/calibration283_layer_policy.json'
    assert sha(policy_path)==reconstructed['policy_sha256']==manifest['frozen_calibration_policy_sha256']
    assert evaluation_qualified['dataset_preparation_passed'] is True
    assert evaluation_qualified['sample_count']==evaluation_qualified['unique_images']==64
    assert sha(evaluation_path)==evaluation_qualified['manifest_sha256']
    assert loader['state']=='pinned_upstream_loader_metadata_and_shard_membership_verified'
    assert loader['revision']==candidate['revision']
    assert loader['candidate_record_sha256']==sha(root/'records/model_reference_candidate.json')
    model_directory=root/'.cache/model_reference/tiny_llava_v1'
    assert {p.name for p in model_directory.iterdir() if p.is_file()}==set(loader['snapshot_file_names'])
    assert sha(model_directory/'config.json')==candidate['config_sha256']
    cases=manifest['cases'];assert len(cases)==16
    assert len(evaluation['images'])==len(evaluation['samples'])==64
    evaluation_image_hashes={str(item['image_id']):item['sha256'] for item in evaluation_qualified['verified_images']}
    assert set(evaluation_image_hashes)==set(evaluation['images']) and len(evaluation_image_hashes)==64
    identities={str(p):sha(p) for p in [Path(__file__),manifest_path,evaluation_path,
        root/'records/model_reference_candidate.json',prepared_path,reconstructed_path,
        evaluation_qualified_path,loader_path,policy_path,
        root/'syn/tri_oracle_integer_reference.py',root/'syn/tri_oracle_model_reference.py']}
    for mapping in [prepared['generated_sha256'],loader['metadata_sha256'],loader['weight_sha256']]:
        for filename,digest in mapping.items():
            assert sha(filename)==digest
            identities[str(Path(filename))]=digest
    for image_id,item in evaluation['images'].items():
        path=root/item['path']
        assert sha(path)==item['sha256']==evaluation_image_hashes[image_id]
        assert path.stat().st_size==item['bytes']
        identities[str(path)]=item['sha256']
    for case in cases:
        assert sha(case['image'])==case['image_sha256'] and pixel_identity(case['image'])==case['pixel_sha256']
        identities[case['image']]=case['image_sha256']
    evaluation_pixels={pixel_identity(item['path']) for item in evaluation['images'].values()}
    assert len(evaluation_pixels)==64 and len({case['pixel_sha256'] for case in cases})==16
    assert not evaluation_pixels.intersection(case['pixel_sha256'] for case in cases)
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0]>10*1024**3
    torch.cuda.set_per_process_memory_fraction(.84)
    torch.cuda.reset_peak_memory_stats()
    out.mkdir()
    started=time.monotonic()
    record=dict(state='loading_original_model',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_sha256=identities,checkpoint_revision=candidate['revision'],
        calibration_images=8,held_images=8,selected_token_rows_per_image=16,
        evaluation_images_excluded=len(evaluation_pixels),image_pixels_disjoint_from_evaluation=True,
        labels_used=False,model_weights_changed=False,whole_model_integer=False,
        dataset_accuracy_verified=False,hardware_configuration_mapping_verified=False,
        full_paper_results_matched=False,scope=__doc__,layers=[],inputs=[])
    def save(**changes):
        record.update(changes,elapsed_seconds=time.monotonic()-started)
        temporary=result.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(result)
    save()
    tokenizer=AutoTokenizer.from_pretrained(root/'.cache/model_reference/tiny_llava_v1',local_files_only=True)
    image_processor=CLIPImageProcessorPil.from_pretrained(root/'.cache/model_reference/tiny_llava_v1',local_files_only=True)
    processor=LlavaProcessor(image_processor=image_processor,tokenizer=tokenizer,patch_size=14,
        vision_feature_select_strategy='default',num_additional_image_tokens=1)
    model=LlavaForConditionalGeneration.from_pretrained(root/'.cache/model_reference/tiny_llava_v1',
        local_files_only=True,dtype=torch.float32,attn_implementation='sdpa',use_kernels=False).to('cuda').eval()
    layers=model.model.language_model.layers;assert len(layers)==22
    captures=[Capture(index) for index in range(22)]
    handles=[]
    try:
        for capture,layer in zip(captures,layers):
            handles.extend([layer.post_attention_layernorm.register_forward_pre_hook(capture.before_norm),
                            layer.mlp.register_forward_hook(capture.after_mlp)])
        for index,case in enumerate(cases):
            with Image.open(case['image']) as opened:
                image=opened.convert('RGB')
                batch=processor(images=image,text='USER: <image>\n'+case['question']+'\nAnswer briefly.\nASSISTANT:',return_tensors='pt').to('cuda')
            assert batch['input_ids'].shape[0]==1 and batch['pixel_values'].shape==(1,3,336,336)
            selected=torch.linspace(0,batch['input_ids'].shape[1]-1,16,device='cuda').round().long()
            assert selected.unique().numel()==16
            for capture in captures:capture.selected=selected
            logits=model(**batch,use_cache=False,logits_to_keep=1).logits
            assert logits.shape==(1,1,32064) and bool(torch.isfinite(logits).all())
            record['inputs'].append(dict(index=index,image_pixel_sha256=case['pixel_sha256'],
                split='calibration' if index<8 else 'held',prefill_tokens=batch['input_ids'].shape[1],
                selected_token_positions=selected.tolist()))
            save(state='capturing_original_rows')
            print('FORMAT320_CAPTURE',index+1,'of16',flush=True)
    finally:
        for handle in handles:handle.remove()
    assert all(len(c.activations)==len(c.residuals)==len(c.targets)==16 and c.pending is None for c in captures)
    captured_path=out/'captured_rows.pt'
    torch.save([dict(activation=torch.cat(c.activations),residual=torch.cat(c.residuals),target=torch.cat(c.targets)) for c in captures],captured_path)
    for index,(capture,layer) in enumerate(zip(captures,layers)):
        all_a=torch.cat(capture.activations).to('cuda');all_r=torch.cat(capture.residuals).to('cuda');all_y=torch.cat(capture.targets).to('cuda')
        assert all_a.shape==all_r.shape==all_y.shape==(256,2048)
        a,r,y=all_a[:128],all_r[:128],all_y[:128]
        held_a,held_r,held_y=all_a[128:],all_r[128:],all_y[128:]
        reference=IntegerFeedForwardReference(layer.mlp.gate_proj.weight,layer.mlp.up_proj.weight,
            layer.mlp.down_proj.weight,layer.post_attention_layernorm.variance_epsilon)
        candidates=[]
        for gain in [0,2,4,6,7]:
            for offset in [-6,-4,-2,-1,0,1,2,3,4,6]:
                raw,values,stats=reference.evaluate(a,r,prune=False,maximum_up_gain_bits=gain,down_shift_offset=offset)
                loss=relative_error(values,y)
                candidates.append(dict(maximum_up_gain_bits=gain,down_shift_offset=offset,relative_error=loss))
        best=min(candidates,key=lambda row:row['relative_error'])
        new=dict(maximum_up_gain_bits=best['maximum_up_gain_bits'],down_shift_offset=best['down_shift_offset'])
        old={key:old_policy['layers'][index][key] for key in ['maximum_up_gain_bits','down_shift_offset']}
        row=dict(layer=index,old_policy=old,new_policy=new,candidate_grid=candidates)
        for name,policy in [('old',old),('new',new)]:
            raw,values,stats=reference.evaluate(a,r,prune=False,**policy);row[name+'_calibration_error']=relative_error(values,y)
            raw,values,stats=reference.evaluate(held_a,held_r,prune=False,**policy);row[name+'_held_error']=relative_error(values,held_y)
        row['old_range_isolation']=range_isolation(layer,reference,all_a,all_r,all_y,old)
        row['new_range_isolation']=range_isolation(layer,reference,all_a,all_r,all_y,new)
        record['layers'].append(row);save(state='calibrating_and_auditing_ranges')
        print('FORMAT320_LAYER',index,'oldheld',row['old_held_error'],'newheld',row['new_held_error'],flush=True)
        del reference
    policy_path=out/'layer_policy.json'
    policy_path.write_text(json.dumps(dict(state='multi_image_fixed_layer_policy',checkpoint_revision=candidate['revision'],
        calibration_images=8,held_images=8,layers=[dict(layer=row['layer'],**row['new_policy']) for row in record['layers']],
        dataset_accuracy_verified=False,hardware_configuration_mapping_verified=False),indent=2)+'\n')
    assert all(sha(path)==digest for path,digest in identities.items())
    assert {p.name for p in model_directory.iterdir() if p.is_file()}==set(loader['snapshot_file_names'])
    save(state='multi_image_fixed_format_and_range_diagnostic_completed',
         generated_sha256={str(p):sha(p) for p in [captured_path,policy_path]},
         graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),graphics_peak_reserved_bytes=torch.cuda.max_memory_reserved())
    print('FORMAT320_COMPLETED layers=22 calibration_rows=128 held_rows=128',flush=True)


if __name__=='__main__':
    main()
