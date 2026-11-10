"""Complete trained first-language-layer fixture for one shared fabric.

M=16 captured tokens, H=2048 model inputs and outputs, D=5632 intermediate
channels. Export every original gate/up/down weight, per-token mask and shift,
all down-input codes and all final integer sums. Full CUDA and independent CPU
arithmetic must agree. Prepared masks and input normalization remain external;
no whole-model accuracy or physical-performance result is inferred.
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
from tri_oracle_model_reference import requantize,silu_code


def sha(path):
    """Caller scalar path initializes a streamed scalar digest; no tensors."""
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


@torch.inference_mode()
def main():
    """Captured CPU dictionaries initialize activation/residual[256,H].
    a/r[M,H] select first16 image0 rows. Pinned float gate/up[D,H] and down[H,D]
    initialize unchanged canonical CUDA reference and its signed8 weight codes.
    full_raw/full_values[M,H],stats[M,...] come from protected dispatch.
    codes[M,H],exponents[M,1],norm/signs[M,H],gate/up_margins/skip[M,D] retain
    canonical activation quantization and prediction. gate/up_raw,gate/up_q,
    products,gated,down_input[M,D] use unchanged signed integer arithmetic.
    reconstructed[M,H] equals all canonical raw outputs; selected prior379 and
    prior386 arrays retain their exact original indices and words.

    CPU lists activation[M,H],gate/up[D,H],down[H,D],norm[M,H],skip[M,D],
    gate/up_raw[M,D],gated[M,D],intermediate[M,D],final[M,H] independently
    check every mask, full-H branch dot, nonlinear code and full-D output dot.
    Shifts[M,3] come from frozen stats. Archive streams flatten these axes
    row-major. Remaining variables are scalar paths/metadata/indices. No
    fitting, training, loss, optimizer or task scoring occurs.
    """
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    output=root/'records/batch389_fixture_preparation.json';directory=root/'.cache/model_reference/batch389'
    assert not output.exists() and not directory.exists()
    architecture_path=root/'records/batch389_architecture_validation.json'
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
    previous_path=root/'records/batch386_fixture_preparation.json';previous=json.loads(previous_path.read_text())
    assert previous['state']=='full_width_trained_down_fixture_scalar_cuda_equal'
    inputs[str(previous_path)]=sha(previous_path)
    inputs[str(root/'syn/tri_oracle_model_reference.py')]=sha(root/'syn/tri_oracle_model_reference.py')
    inputs.update(prior['files_sha256']);inputs.update(previous['files_sha256'])
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
    previous_inputs=[int(v,16) for v in (Path(previous['fixture'])/'activation.hex').read_text().split()]
    assert previous_inputs==[v&255 for v in down_input.cpu().reshape(-1).tolist()]
    previous_outputs=[int(v,16) for v in (Path(previous['fixture'])/'expected.hex').read_text().split()]
    assert previous_outputs==[v&0xffffffff for v in full_raw[:,previous['selected_output_rows']].cpu().reshape(-1).tolist()]
    activation=codes.cpu().tolist();gate_rows=reference.gate.cpu().tolist();up_rows=reference.up.cpu().tolist()
    down_rows=reference.down.cpu().tolist();norm=stats['norm_codes'].cpu().tolist();skip_rows=skip.cpu().tolist()
    gate_sums=gate_raw.masked_fill(skip,0).cpu().tolist();up_sums=up_raw.masked_fill(skip,0).cpu().tolist()
    gated_rows=gated.masked_fill(skip,0).cpu().tolist();intermediate=down_input.cpu().tolist();final=full_raw.cpu().tolist()
    shifts=[[int(stats[key][token]) for key in ['gate_shift','up_shift','down_shift']] for token in range(16)]
    for token in range(16):
        outliers=[(f,-1 if value<0 else 1) for f,value in enumerate(norm[token]) if abs(value)>768]
        gate_shift,up_shift,down_shift=shifts[token]
        for channel in range(5632):
            gm=sum(sign*(-1 if gate_rows[channel][f]<0 else 1) for f,sign in outliers)
            um=sum(sign*(-1 if up_rows[channel][f]<0 else 1) for f,sign in outliers)
            skipped=bool(outliers) and gm<=0 and um==0
            assert skipped==skip_rows[token][channel]
            g=sum(x*w for x,w in zip(activation[token],gate_rows[channel])) if not skipped else 0
            u=sum(x*w for x,w in zip(activation[token],up_rows[channel])) if not skipped else 0
            assert g==gate_sums[token][channel] and u==up_sums[token][channel]
            result=requantize(silu_code(requantize(g,gate_shift,16))*requantize(u,up_shift,16),8,16)
            assert result==gated_rows[token][channel] and requantize(result,down_shift,8)==intermediate[token][channel]
        for row in range(2048):
            assert sum(x*w for x,w in zip(intermediate[token],down_rows[row]))==final[token][row]
    assert any(v for row in final for v in row)
    directory.mkdir()
    for name,values,bits in [('activation',activation,8),('gate',gate_rows,8),('up',up_rows,8),
                             ('down',down_rows,8),('intermediate',intermediate,8),('expected',final,32),('shifts',shifts,8)]:
        write_hex(directory/(name+'.hex'),(int(v) for row in values for v in row),bits)
    write_hex(directory/'keep.hex',(int(not v) for row in skip_rows for v in row),8)
    assert all(sha(p)==h for p,h in inputs.items())
    report=dict(state='complete_trained_layer_fixture_scalar_cuda_equal',
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=inputs,
        fixture=str(directory),original_layer=0,tokens=16,input_features=2048,intermediate_features=5632,output_features=2048,
        original_token_positions=prior['original_token_positions'],all_original_rows_preserved=True,
        complete_canonical_output_reconstruction_equal=True,prior379_gated_and_down_subsets_equal=True,
        prior386_complete_down_inputs_and_selected_outputs_equal=True,independent_scalar_complete_layer_equal=True,
        exact_gate_up_words=180224,exact_intermediate_bytes=90112,exact_final_outputs=32768,
        hardware_shifts=shifts,predicted_skipped_pairs=int(skip.sum()),
        files_sha256={str(p):sha(p) for p in sorted(directory.iterdir())},
        graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),elapsed_seconds=time.monotonic()-started,
        source_hardware_verified=False,whole_model_verified=False,full_paper_results_matched=False,scope=__doc__)
    output.write_text(json.dumps(report,indent=2)+'\n');print('BATCH389_COMPLETE_LAYER_FIXTURE_READY',flush=True)



if __name__=='__main__':main()
