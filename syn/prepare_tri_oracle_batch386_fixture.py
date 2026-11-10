"""Full5632-feature down-projection fixture from the unchanged protected model.

M=16 captured tokens, H=2048 model inputs/outputs, D=5632 intermediate
features, S=160 original output rows. Full trained matrices are quantized before
selection. Complete canonical gate/up/nonlinear results initialize down inputs;
this fixture does not itself execute those operations in hardware.
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
from tri_oracle_integer_reference import IntegerFeedForwardReference,_dot,_quantize,_requantize
from tri_oracle_format345_first_token import evaluate_protected
from prepare_tri_oracle_format331_fixtures import write_hex


def sha(path):
    """Caller scalar path initializes a streamed scalar digest; no tensors."""
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


@torch.inference_mode()
def main():
    """Captured CPU dictionaries initialize activation/residual[256,H].
    a/r[M,H] select their first16 image0 token rows. Original finite float
    gate/up[D,H],down[H,D] initialize the unchanged trained reference on CUDA.
    evaluate_protected returns full_raw/full_values[M,H],stats[M,...] from
    the frozen first-token and ordinary policies. codes[M,H],exponents[M,1]
    derive from a. norm_codes/signs[M,H] and margins/skip[M,D] reconstruct the
    exact canonical mask; gate/up_raw,gate/up_q,product,gated,down_input[M,D]
    use unchanged quantization, SiLU and rounding. reconstructed[M,H] must
    equal complete canonical full_raw, not only a selected output slice.

    selected[S]=floor(arange(S)*(H-1)/(S-1)) preserves original output IDs,
    including0/2047. weights[S,D],expected[M,S] initialize independent CPU
    weight[S,D],activation[M,D],expected[M,S] lists and D-term scalar sums.
    Prior379 signed gated/down arrays[M,80] must exactly match index-selected
    full results. All other variables are paths, JSON metadata, scalar hashes
    or loop indices. No training, loss, optimizer or scoring occurs.
    """
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    output=root/'records/batch386_fixture_preparation.json';directory=root/'.cache/model_reference/batch386'
    assert not output.exists() and not directory.exists()
    architecture_path=root/'records/batch386_architecture_validation.json'
    architecture=json.loads(architecture_path.read_text())
    assert architecture['source_audits_completed']==3 and architecture['render_visually_verified'] is True
    assert architecture['source_sha256'][str(Path(__file__).resolve())]==sha(__file__)
    assert sha(architecture['pdf'])==architecture['pdf_sha256']
    score_path=root/'records/format348_official_scoring.json'
    assert sha(score_path)=='4058babfdfac37391cb8b6ddffc9446d70c3237ccea2e611f82a4d2fc1c902f2'
    inputs=dict(json.loads(score_path.read_text())['source_sha256'])
    prior_path=root/'records/batch379_fixture_preparation.json';prior=json.loads(prior_path.read_text())
    assert prior['state']=='trained_paired_gated_fixture_scalar_cuda_equal'
    for path in [Path(__file__).resolve(),architecture_path,Path(architecture['pdf']),score_path,prior_path,
                 root/'syn/tri_oracle_integer_reference.py',root/'syn/tri_oracle_format345_first_token.py',
                 root/'syn/prepare_tri_oracle_format331_fixtures.py']:
        inputs[str(path)]=sha(path)
    inputs.update(prior['files_sha256'])
    assert all(sha(p)==h for p,h in inputs.items())
    captured=torch.load(root/'.cache/model_reference/format320/captured_rows.pt',map_location='cpu',weights_only=True)
    assert len(captured)==22 and captured[0]['activation'].shape==captured[0]['residual'].shape==(256,2048)
    model=root/'.cache/model_reference/tiny_llava_v1'
    index=json.loads((model/'model.safetensors.index.json').read_text())
    epsilon=json.loads((model/'config.json').read_text())['text_config']['rms_norm_eps']
    first=json.loads((root/'.cache/model_reference/format322/layer_policy.json').read_text())['layers'][0]
    ordinary=json.loads((root/'.cache/model_reference/format335/layer_policy.json').read_text())['layers'][0]
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0]>10*1024**3
    torch.cuda.set_per_process_memory_fraction(.84);torch.cuda.reset_peak_memory_stats()
    started=time.monotonic();matrices={}
    for kind in ['gate','up','down']:
        keys=[key for key in index['weight_map'] if key.endswith('.layers.0.mlp.'+kind+'_proj.weight')]
        assert len(keys)==1
        with safe_open(model/index['weight_map'][keys[0]],framework='pt',device='cpu') as shard:
            matrices[kind]=shard.get_tensor(keys[0]).to('cuda')
        assert matrices[kind].shape==((2048,5632) if kind=='down' else (5632,2048))
    reference=IntegerFeedForwardReference(matrices['gate'],matrices['up'],matrices['down'],epsilon)
    a=captured[0]['activation'][:16].to('cuda');r=captured[0]['residual'][:16].to('cuda')
    full_raw,full_values,stats=evaluate_protected(reference,a,r,ordinary,first,0,prune=True)
    codes,exponents=_quantize(a,per_row=True)
    signs=(torch.where(stats['norm_codes']<0,-1,1)*(stats['norm_codes'].abs()>768)).to(torch.int8)
    gate_margin=_dot(signs,reference.gate_sign);up_margin=_dot(signs,reference.up_sign)
    skip=(stats['outlier_count'][:,None]>0)&(gate_margin<=0)&(up_margin==0)
    gate_raw=_dot(codes,reference.gate);up_raw=_dot(codes,reference.up)
    gate_q=_requantize(gate_raw,stats['gate_shift'][:,None],16)
    up_q=_requantize(up_raw,stats['up_shift'][:,None],16)
    product=reference.silu_response[gate_q+32768]*up_q
    gated=_requantize(product,torch.full((16,1),8,dtype=torch.int64,device='cuda'),16)
    down_input=_requantize(gated,stats['down_shift'][:,None],8).to(torch.int8).masked_fill(skip,0)
    reconstructed=_dot(down_input,reference.down)
    assert torch.equal(reconstructed,full_raw) and bool(torch.isfinite(full_values).all())
    for name,actual,bits in [('down_input',down_input,8),('gated',gated.masked_fill(skip,0),16)]:
        archived=[int(v,16) for v in (Path(prior['fixture'])/(name+'.hex')).read_text().split()]
        chosen=actual[:,prior['selected_channels']].cpu().reshape(-1).tolist()
        assert archived==[int(v)&((1<<bits)-1) for v in chosen],'Full reference differs from paired379 '+name
    selected=torch.arange(160,dtype=torch.int64,device='cuda')*2047//159
    weights=reference.down.index_select(0,selected);expected=_dot(down_input,weights)
    assert torch.equal(expected,full_raw.index_select(1,selected))
    activation_list=down_input.cpu().tolist();weight_list=weights.cpu().tolist();expected_list=expected.cpu().tolist()
    for token in range(16):
        for row in range(160):
            assert sum(x*w for x,w in zip(activation_list[token],weight_list[row]))==expected_list[token][row]
    assert any(v for row in expected_list for v in row)
    directory.mkdir()
    for name,values,bits in [('activation',activation_list,8),('weight',weight_list,8),('expected',expected_list,32)]:
        write_hex(directory/(name+'.hex'),[v for row in values for v in row],bits)
    write_hex(directory/'channels.hex',selected.cpu().tolist(),16)
    write_hex(directory/'keep.hex',[1]*(16*160),8)
    assert all(sha(p)==h for p,h in inputs.items())
    report=dict(state='full_width_trained_down_fixture_scalar_cuda_equal',
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=inputs,
        fixture=str(directory),original_layer=0,token_rows=16,input_features=5632,
        original_model_hidden_features=2048,full_trained_output_rows=2048,selected_output_rows=selected.cpu().tolist(),
        original_token_positions=prior['original_token_positions'],full_weight_quantization_before_selection=True,
        complete_canonical_output_reconstruction_equal=True,prior379_gated_and_down_subsets_equal=True,
        independent_scalar_dot_outputs_equal=True,exact_outputs=2560,
        hardware_fields=[{k:int(stats[k][t]) for k in ['gate_shift','up_shift','down_shift']} for t in range(16)],
        predicted_zero_inputs=int(skip.sum()),zero_down_inputs=int((down_input==0).sum()),
        files_sha256={str(p):sha(p) for p in sorted(directory.iterdir())},
        graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),elapsed_seconds=time.monotonic()-started,
        source_hardware_verified=False,complete_feedforward_hardware_verified=False,full_paper_results_matched=False,scope=__doc__)
    output.write_text(json.dumps(report,indent=2)+'\n');print('BATCH386_FULL_WIDTH_DOWN_FIXTURE_READY',flush=True)


if __name__=='__main__':main()
