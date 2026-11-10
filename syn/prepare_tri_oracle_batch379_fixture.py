"""Prepare paired gate/up and nonlinear outputs from the unchanged trained model.

M=16 captured tokens, H=2048 input features, D=5632 complete trained channels,
S=80 selected original channels spread across D. Full weight matrices are
quantized before selection. The frozen protected-token precision policy and
canonical arithmetic are unchanged; masks remain prepared inputs. This is a
gated intermediate tile, not a complete feedforward layer or paper benchmark.
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
from tri_oracle_integer_reference import _dot,_quantize,_requantize
from tri_oracle_model_reference import requantize,silu_code
from prepare_tri_oracle_format331_fixtures import hardware_shifts,write_hex


def sha(path):
    """Caller scalar path initializes a streamed scalar digest; no tensors."""
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


@torch.inference_mode()
def main():
    """Captured CPU dictionaries initialize activation/residual[256,H].
    a/r[M,H] are their first16 image0 rows. Full float gate/up[D,H] parameters
    initialize signed8 qgate/qup[D,H] using canonical per-matrix quantization.
    selected[S] is arange(S)*71, preserving original IDs0..5609. gate/up[S,H]
    are index-selected codes; codes[M,H],exponents[M,1] derive from a.
    normalized/norm/signs[M,H] and gate/up_signs[S,H] initialize margins[M,S]
    and keep[M,S]. gate/up_raw[M,S] come from exact CUDA integer products.
    shifts[M,3] come only from frozen input-exponent policies and global token
    positions; gate/up_q[M,S],response[65536],product/gated/down_input[M,S]
    implement the unchanged16-bit SiLU gate followed by signed8 conversion.

    CPU activation[M,H],gate/up[S,H],norm[M,H],keep[M,S],raw[M,S],gated[M,S]
    and down[M,S] lists independently check scalar masks and H-term dot sums,
    rounding, saturation and mathematical SiLU interpolation. Archive arrays
    flatten row-major. All other variables are scalar paths/configuration,
    hashes, loop indices or JSON metadata. No training/loss/optimizer occurs.
    """
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    output=root/'records/batch379_fixture_preparation.json'
    directory=root/'.cache/model_reference/batch379'
    assert not output.exists() and not directory.exists()
    architecture_path=root/'records/batch379_architecture_validation.json'
    architecture=json.loads(architecture_path.read_text())
    assert architecture['source_audits_completed']==3 and architecture['render_visually_verified'] is True
    assert architecture['source_sha256'][str(Path(__file__).resolve())]==sha(__file__)
    assert sha(architecture['pdf'])==architecture['pdf_sha256']
    score_path=root/'records/format348_official_scoring.json'
    assert sha(score_path)=='4058babfdfac37391cb8b6ddffc9446d70c3237ccea2e611f82a4d2fc1c902f2'
    scored=json.loads(score_path.read_text());inputs=dict(scored['source_sha256'])
    for path in [Path(__file__).resolve(),architecture_path,Path(architecture['pdf']),score_path,
                 root/'syn/tri_oracle_integer_reference.py',root/'syn/tri_oracle_model_reference.py',
                 root/'syn/prepare_tri_oracle_format331_fixtures.py']:
        inputs[str(path)]=sha(path)
    assert all(sha(path)==digest for path,digest in inputs.items())
    capture=root/'.cache/model_reference/format320/captured_rows.pt'
    assert sha(capture)=='3569905e763143ec61458315db2014da3a399e18d4d87d561eeed1ff40ebcfea'
    captured=torch.load(capture,map_location='cpu',weights_only=True)
    assert len(captured)==22 and captured[0]['activation'].shape==captured[0]['residual'].shape==(256,2048)
    positions=json.loads((root/'records/format320_multi_image_range_audit.json').read_text())['inputs'][0]['selected_token_positions']
    assert len(positions)==16 and positions[0]==0 and all(p>0 for p in positions[1:])
    model=root/'.cache/model_reference/tiny_llava_v1'
    index=json.loads((model/'model.safetensors.index.json').read_text())
    epsilon=json.loads((model/'config.json').read_text())['text_config']['rms_norm_eps']
    first=json.loads((root/'.cache/model_reference/format322/layer_policy.json').read_text())['layers'][0]
    ordinary=json.loads((root/'.cache/model_reference/format335/layer_policy.json').read_text())['layers'][0]
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0]>10*1024**3
    torch.cuda.set_per_process_memory_fraction(.84);torch.cuda.reset_peak_memory_stats()
    started=time.monotonic();matrices={}
    for kind in ['gate','up']:
        keys=[key for key in index['weight_map'] if key.endswith('.layers.0.mlp.'+kind+'_proj.weight')]
        assert len(keys)==1
        with safe_open(model/index['weight_map'][keys[0]],framework='pt',device='cpu') as shard:
            matrices[kind]=shard.get_tensor(keys[0]).to('cuda')
        assert matrices[kind].shape==(5632,2048) and bool(torch.isfinite(matrices[kind]).all())
    qgate,gate_exponent=_quantize(matrices['gate']);qup,up_exponent=_quantize(matrices['up'])
    selected=torch.arange(80,dtype=torch.int64,device='cuda')*71
    gate=qgate.index_select(0,selected);up=qup.index_select(0,selected)
    a=captured[0]['activation'][:16].to('cuda');r=captured[0]['residual'][:16].to('cuda')
    codes,exponents=_quantize(a,per_row=True)
    assert bool(torch.isfinite(a).all() & torch.isfinite(r).all())
    normalized=r*torch.rsqrt(r.square().mean(dim=-1,keepdim=True)+epsilon)*256
    norm=(normalized.sign()*torch.floor(normalized.abs()+.5)).clamp(-32768,32767).to(torch.int32)
    signs=(torch.where(norm<0,-1,1)*(norm.abs()>768)).to(torch.int8)
    gate_signs=torch.where(gate<0,-1,1).to(torch.int8);up_signs=torch.where(up<0,-1,1).to(torch.int8)
    gate_margin=_dot(signs,gate_signs);up_margin=_dot(signs,up_signs)
    keep=~(((norm.abs()>768).sum(dim=-1)[:,None]>0)&(gate_margin<=0)&(up_margin==0))
    fields=[]
    for token,exponent in enumerate(exponents[:,0].cpu().tolist()):
        setting=first if positions[token]==0 else next((item for item in ordinary['buckets']
                if item['activation_exponent']==exponent),ordinary['fallback'])
        fields.append(hardware_shifts(exponent,int(gate_exponent),int(up_exponent),
            setting['maximum_up_gain_bits'],setting['down_shift_offset']))
    shifts=torch.tensor([[f[key] for key in ['gate_shift','up_shift','down_shift']] for f in fields],dtype=torch.int64,device='cuda')
    gate_raw=_dot(codes,gate).masked_fill(~keep,0);up_raw=_dot(codes,up).masked_fill(~keep,0)
    gate_q=_requantize(gate_raw,shifts[:,0:1],16);up_q=_requantize(up_raw,shifts[:,1:2],16)
    response=torch.tensor([silu_code(v) for v in range(-32768,32768)],dtype=torch.int64,device='cuda')
    product=response[gate_q+32768]*up_q
    gated=_requantize(product,torch.full((16,1),8,dtype=torch.int64,device='cuda'),16)
    down_input=_requantize(gated,shifts[:,2:3],8)
    activation=codes.cpu().tolist();gate_list=gate.cpu().tolist();up_list=up.cpu().tolist()
    norm_list=norm.cpu().tolist();keep_list=keep.cpu().tolist()
    raw_gate=gate_raw.cpu().tolist();raw_up=up_raw.cpu().tolist()
    gated_list=gated.cpu().tolist();down_list=down_input.cpu().tolist()
    for token in range(16):
        outliers=[(f,-1 if v<0 else 1) for f,v in enumerate(norm_list[token]) if abs(v)>768]
        for row in range(80):
            gm=sum(s*(-1 if gate_list[row][f]<0 else 1) for f,s in outliers)
            um=sum(s*(-1 if up_list[row][f]<0 else 1) for f,s in outliers)
            kept=not(bool(outliers) and gm<=0 and um==0);assert kept==keep_list[token][row]
            g=sum(x*w for x,w in zip(activation[token],gate_list[row])) if kept else 0
            u=sum(x*w for x,w in zip(activation[token],up_list[row])) if kept else 0
            assert g==raw_gate[token][row] and u==raw_up[token][row]
            nonlinear=requantize(silu_code(requantize(g,fields[token]['gate_shift'],16))*requantize(u,fields[token]['up_shift'],16),8,16)
            assert nonlinear==gated_list[token][row]
            assert requantize(nonlinear,fields[token]['down_shift'],8)==down_list[token][row]
    old=json.loads((root/'records/batch358_fixture_preparation.json').read_text())
    original_codes=Path(old['fixture'])/'activation.hex';assert sha(original_codes)==old['files_sha256'][str(original_codes)]
    assert [int(x,16) for x in original_codes.read_text().split()]==[v&255 for row in activation for v in row]
    directory.mkdir()
    arrays=[('activation',activation,8),('gate',gate_list,8),('up',up_list,8),
            ('keep',keep_list,8),('gate_raw',raw_gate,32),('up_raw',raw_up,32),
            ('gated',gated_list,16),('down_input',down_list,8)]
    for name,values,bits in arrays:write_hex(directory/(name+'.hex'),[int(v) for row in values for v in row],bits)
    write_hex(directory/'channels.hex',selected.cpu().tolist(),16)
    write_hex(directory/'shifts.hex',[v for row in shifts.cpu().tolist() for v in row],8)
    assert all(sha(path)==digest for path,digest in inputs.items())
    report=dict(state='trained_paired_gated_fixture_scalar_cuda_equal',
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=inputs,
        fixture=str(directory),original_layer=0,token_rows=16,hidden_features=2048,
        full_trained_channels=5632,selected_channels=selected.cpu().tolist(),original_token_positions=positions,
        hardware_fields=fields,gate_weight_exponent=int(gate_exponent),up_weight_exponent=int(up_exponent),
        full_weight_quantization_before_selection=True,exact_projection_words=2560,
        exact_gated_words=1280,exact_down_input_words=1280,predicted_skipped_pairs=int((~keep).sum()),
        independent_scalar_masks_projection_and_nonlinear_equal=True,activation_codes_equal_prior358=True,
        files_sha256={str(p):sha(p) for p in sorted(directory.iterdir())},
        graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),elapsed_seconds=time.monotonic()-started,
        source_hardware_verified=False,complete_feedforward_verified=False,full_paper_results_matched=False,scope=__doc__)
    output.write_text(json.dumps(report,indent=2)+'\n')
    print('BATCH379_TRAINED_PAIRED_FIXTURE_READY',report['predicted_skipped_pairs'],'skipped',flush=True)


if __name__=='__main__':main()
