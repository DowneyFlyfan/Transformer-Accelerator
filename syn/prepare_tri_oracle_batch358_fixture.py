"""Prepare a trained first-layer batched affine tile with original quantization.

M=16 captured positions of the first fitting image,H=2048 input features,
D=5632 complete trained projection rows,O=160 original rows0..159. Full
gate/up matrices are quantized before slicing. Token-specific sign prediction
is retained as existing per-token hardware masks. This is a raw gate-projection
tile,not complete gated feed-forward,model execution or paper performance.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import torch
from safetensors import safe_open
from tri_oracle_integer_reference import _dot,_quantize
from prepare_tri_oracle_format331_fixtures import write_hex


def sha(path):
    """Scalar source path -> streamed scalar digest,without tensor allocation."""
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


@torch.inference_mode()
def main():
    """Frozen captures contain22 dictionaries of activation/residual[256,H].
    The first16 rows belong to image0 and its16 original selected positions.
    a/r[M,H] are transferred to CUDA; full gate/up[D,H] float32 parameters come
    from original pinned shards. qgate/qup[D,H] are unchanged signed8 codes.
    codes[M,H],exponents[M,1] use unchanged per-row power-of-two quantization.
    normalized/norm[M,H] implement the canonical pre-learned-scale prediction
    encoding; signs[M,H], gate/up_signs[O,H], margins[M,O],keep[M,O] define
    current sign-margin masks. raw/expected[M,O] are exact integer dot sums.

    CPU activation[M*H],weights[O*H],normalized[M,H],retained[M,O] andexpected
    lists are copied from those tensors. Independent scalar sign counts and
    H-term integer sums must match every CUDA mask/output before hex export.
    No loss,optimizer,answers,policy fitting or model output replacement occurs.
    File paths/keys are scalar source identifiers; scored/inputs/architecture,
    index/audit/report are file-derived JSON metadata,not model tensors.
    """
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    output=root/'records/batch358_fixture_preparation.json';directory=root/'.cache/model_reference/batch358'
    assert not output.exists() and not directory.exists()
    score_path=root/'records/format348_official_scoring.json';scored=json.loads(score_path.read_text())
    assert sha(score_path)=='4058babfdfac37391cb8b6ddffc9446d70c3237ccea2e611f82a4d2fc1c902f2'
    inputs=dict(scored['source_sha256'])
    for path in [Path(__file__).resolve(),score_path,root/'syn/prepare_tri_oracle_format331_fixtures.py',
                 root/'records/batch358_architecture_validation.json']:
        inputs[str(path)]=sha(path)
    architecture=json.loads((root/'records/batch358_architecture_validation.json').read_text())
    assert architecture['source_audits_completed']==3 and architecture['render_visually_verified']
    assert architecture['source_sha256'][str(Path(__file__).resolve())]==sha(__file__)
    assert sha(architecture['pdf'])==architecture['pdf_sha256'];inputs[architecture['pdf']]=architecture['pdf_sha256']
    assert all(sha(path)==digest for path,digest in inputs.items())
    captured_path=root/'.cache/model_reference/format320/captured_rows.pt'
    assert sha(captured_path)=='3569905e763143ec61458315db2014da3a399e18d4d87d561eeed1ff40ebcfea'
    captured=torch.load(captured_path,map_location='cpu',weights_only=True)
    assert len(captured)==22 and captured[0]['activation'].shape==captured[0]['residual'].shape==(256,2048)
    audit=json.loads((root/'records/format320_multi_image_range_audit.json').read_text())
    positions=audit['inputs'][0]['selected_token_positions']
    assert audit['inputs'][0]['index']==0 and audit['inputs'][0]['prefill_tokens']==606 and len(positions)==16
    model=root/'.cache/model_reference/tiny_llava_v1'
    index=json.loads((model/'model.safetensors.index.json').read_text())
    epsilon=json.loads((model/'config.json').read_text())['text_config']['rms_norm_eps']
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0]>10*1024**3
    torch.cuda.set_per_process_memory_fraction(.84);torch.cuda.reset_peak_memory_stats()
    started=time.monotonic();matrices={}
    for kind in ['gate','up']:
        keys=[key for key in index['weight_map'] if key.endswith('.layers.0.mlp.'+kind+'_proj.weight')]
        assert len(keys)==1
        with safe_open(model/index['weight_map'][keys[0]],framework='pt',device='cpu') as shard:
            matrices[kind]=shard.get_tensor(keys[0]).to('cuda')
        assert matrices[kind].shape==(5632,2048)
        assert bool(torch.isfinite(matrices[kind]).all())
    qgate,gate_exponent=_quantize(matrices['gate']);qup,up_exponent=_quantize(matrices['up'])
    a=captured[0]['activation'][:16].to('cuda');r=captured[0]['residual'][:16].to('cuda')
    assert bool(torch.isfinite(a).all() & torch.isfinite(r).all())
    codes,exponents=_quantize(a,per_row=True)
    normalized=r*torch.rsqrt(r.square().mean(dim=-1,keepdim=True)+epsilon)*256
    norm=(normalized.sign()*torch.floor(normalized.abs()+.5)).clamp(-32768,32767).to(torch.int32)
    outliers=norm.abs()>768
    signs=(torch.where(norm<0,-1,1)*outliers).to(torch.int8)
    gate_signs=torch.where(qgate[:160]<0,-1,1).to(torch.int8)
    up_signs=torch.where(qup[:160]<0,-1,1).to(torch.int8)
    gate_margin=_dot(signs,gate_signs);up_margin=_dot(signs,up_signs)
    keep=~((outliers.sum(dim=-1)[:,None]>0)&(gate_margin<=0)&(up_margin==0))
    raw=_dot(codes,qgate[:160]);expected=raw.masked_fill(~keep,0)
    activation=codes.cpu().reshape(-1).tolist();weights=qgate[:160].cpu().reshape(-1).tolist()
    normalized=norm.cpu().tolist();retained=keep.cpu().tolist();expected_list=expected.cpu().tolist()
    scalar=[]
    gate_rows=qgate[:160].cpu().tolist();up_rows=qup[:160].cpu().tolist()
    for token in range(16):
        features=[(i,-1 if value<0 else 1) for i,value in enumerate(normalized[token]) if abs(value)>768]
        row_values=[]
        for row in range(160):
            gm=sum(sign*(-1 if gate_rows[row][feature]<0 else 1) for feature,sign in features)
            um=sum(sign*(-1 if up_rows[row][feature]<0 else 1) for feature,sign in features)
            kept=not(bool(features) and gm<=0 and um==0)
            assert kept==retained[token][row]
            value=sum(activation[token*2048+f]*weights[row*2048+f] for f in range(2048)) if kept else 0
            assert value==expected_list[token][row]
            row_values.append(value)
        scalar.append(row_values)
    assert scalar==expected_list and any(v for row in scalar for v in row)
    directory.mkdir()
    for name,values,bits in [('activation',activation,8),('gate',weights,8),
                            ('keep',[int(v) for row in retained for v in row],8),
                            ('expected',[v for row in scalar for v in row],32)]:
        write_hex(directory/(name+'.hex'),values,bits)
    assert all(sha(path)==digest for path,digest in inputs.items())
    report=dict(state='trained_batched_affine_fixture_scalar_cuda_equal',source_sha256=inputs,
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),fixture=str(directory),
        original_layer=0,original_output_rows=list(range(160)),captured_image_index=0,captured_rows=list(range(16)),
        original_token_positions=positions,
        token_rows=16,hidden_features=2048,output_rows=160,full_trained_weight_rows=5632,
        full_weight_quantization_before_slice=True,gate_weight_scale_exponent=int(gate_exponent),up_weight_scale_exponent=int(up_exponent),
        activation_scale_exponents=exponents[:,0].cpu().tolist(),exact_output_words=2560,
        predicted_skipped_pairs=int((~keep).sum()),independent_scalar_masks_and_outputs_verified=True,
        files_sha256={str(path):sha(path) for path in sorted(directory.iterdir())},
        elapsed_seconds=time.monotonic()-started,graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
        source_hardware_verified=False,complete_gated_feedforward_verified=False,full_model_verified=False,
        full_paper_results_matched=False,scope=__doc__)
    output.write_text(json.dumps(report,indent=2)+'\n')
    print('BATCH358_TRAINED_FIXTURE_READY',report['predicted_skipped_pairs'],'skipped',report['exact_output_words'],'exact words',flush=True)


if __name__=='__main__':main()
